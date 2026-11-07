"""这个文件负责编写Agent的具体业务代码和构建逻辑"""
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import TypedDict, Annotated
from loguru import logger
from datetime import date

from core.background_agent.BaseTask import AgentTask, MultiTask
from core.background_agent.graphs_manager import GraphBlockManager, GraphTaskManager
from core.tools.ToolsManager import ToolsManager
from settings.routers.provider import ProviderRouter
from event.event_core import Bus, Loop
from core.background_agent._event import AgentLog,TaskStartLog,TaskOverLog

# 定义Agent的消息state    (以类型注解的形式)
class MessageState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    now_task: str
    agent_prompt: str
    work_message: str
    llm_calls: int

class BackgroundAgent:

    def __init__(self, local_bus:Bus, local_loop:Loop, provider_router: ProviderRouter, tools_manager: ToolsManager, graph_block_manager:GraphBlockManager, graph_task_manager:GraphTaskManager):
        self._provider_router = provider_router
        self._tools_manager = tools_manager
        self._block_manager = graph_block_manager
        self._task_manager = graph_task_manager

        self._local_loop = local_loop

        self._stop_working = False
        self._agent: CompiledStateGraph = self.compile()
        self._default_tools = "default" # 通常应该是什么呢，比如说是日志工具
        self._now_task: AgentTask | MultiTask | None = None #agent工作时用这个来访问自己正在进行的工作信息

    def stop_working(self):
        self._stop_working = True

    def invoke(self, task: AgentTask | MultiTask):
        #错误处理
        if not isinstance(task, AgentTask) and not isinstance(task, MultiTask):
            raise TypeError(f"BackAgent模块收到了无法相应的任务类型：{task}")
        logger.info(f"新一轮后台Agent调用已开始，task_name:{task.task_name} id：{id(task)}")
        self._now_task = task
        _messages = self._agent.invoke({"messages": [],"llm_calls": 0})
        self._now_task = None
        # return  _messages["messages"][-1].content # 只返回最后一句（？是不是应该直接没有返回值才对，任务管理器又不管代码执行到哪儿了

    def get_llm_invoke(self):
        """获取一个直接调用LLM模型的方法"""
        # TODO这是坏设计，至少目前我认为把模型暴露给core逻辑是不对的，应该整合一下各个任务不同的提示词拼装逻辑，在那里提供llm调用
        model = self._provider_router.model_route()
        return model.invoke

    # agent节点
    def _agent_node(self,state: dict):
        """"
        agent “观察-执行”循环节点————观察节点
        """
        now_date = f"今日日期为：{date.today().isoformat()}\n"

        model  = self._provider_router.model_route()

        # 提示词获取与构建
        system_prompt = now_date + self._now_task.task_prompt
        human_msg = self._now_task.task_message
        # 工具列表获取

        _tools =  (self._tools_manager.get_tool_set(self._now_task.tool_set_name)
                   + self._tools_manager.get_tool_set(self._default_tools)) #TODO: 如果按现在逻辑从管理器中获取注册过的工具，则需要在管理器中写一套工具表注册器，一键获取注册过的工具列表。给每个不同的任务都注册一个单独的表。这里的直接获取任务的逻辑也要换
        # 工具嵌入
        _model_with_tools = model.bind_tools(_tools)

        # 过滤掉 RemoveMessage(手动清理记忆时产生，但是我们现在不会死循环了不用担心这个（（（（) 等 LangChain 内部消息类型
        # valid_messages = [m for m in state["messages"] if not isinstance(m, RemoveMessage)]

        last_messages = state["messages"]
        # if state.get('llm_calls', 0) == 0: 卧槽谁说这玩意会堆积上下文的
        last_messages = [SystemMessage(content=system_prompt),HumanMessage(content=human_msg)] + last_messages  # TODO记得修改为ChatMessage版本查看效果

        result = _model_with_tools.invoke(last_messages)
        logger.debug(f"agent工作输出:{result.content}")
        logger.debug(f"本轮工具调用:{result.tool_calls}")
        self._local_loop.post(AgentLog(result.content,result.tool_calls))   #发布工作日志

        return {
            "messages": [result], # 调用模型并将返回的消息插入messages（由于messages是增量式更新，所以不用把旧上下文也拼进来）
            "llm_calls": state.get('llm_calls', 0) + 1,
        }

    # 工具节点：输入一个状态（字典），输出一个新包装好的消息列表
    def _agent_tool(self,state: dict):
        """
        agent “观察-执行”循环节点————执行节点
        :param state:
        :return:
        """
        result = [] # 每一条构造处理的ToolMessage会被保存在这里。最后一起插入到messages这个上下文中
        for tool_call in state["messages"][-1].tool_calls: # 遍历ai的调用列表，相应每一条执行请求
            tool = self._tools_manager.get_tool_by_name(tool_call["name"])
            try :
                observation = tool.invoke(tool_call["args"])
            except Exception as e:  #捕获报错信息
                observation = str(e)
            # 返回类型检查
            if observation is None: observation = ""
            if not isinstance(observation, str): observation = str(observation) #确保结果是字符串，不然创建ToolMessage时会报错
            result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"], ))
        return {"messages": result}

    def _starter(self, state: dict):
        """用于处理事件开始前的逻辑，比如整理状态信息和打印日志"""
        self._local_loop.post(TaskStartLog(id(self._now_task),self._now_task.task_name))
        return

    def _ender(self, state: dict):
        """用于处理事件结束后的逻辑，比如打印日志或者保存点什么的（"""
        self._local_loop.post(TaskOverLog(id(self._now_task),self._now_task.task_name))
        logger.info(f"后台任务已完成，\ntask_name:{self._now_task.task_name} id:{id(self._now_task)}")
        return

    def _router_before_agent(self, state: MessageState) -> str:
        task = self._now_task
        return self._block_manager.map_to_in_nodes(task.route_before_agent) # 使用这个函数将所有的图块名路由到正确的节点上

    def _router_after_agent(self, state: MessageState) -> str:
        # 如果外部发起停止指令则直接路由到end
        if self._stop_working:
            logger.warning(f"检测到程序终止事件已终止笔记修改，笔记信息可能丢失，请注意。")
            return "ender"

        # 取出最新的消息
        messages = state["messages"]
        last_message = messages[-1]

        # 观察大模型是否进行了工具调用 （tool_call 字段是否不为空）
        if last_message.tool_calls:
            return "agent_tool"  # 进入agent_tool节点

        task = self._now_task
        return self._block_manager.map_to_in_nodes(task.route_after_agent)

    def compile(self):
        # 状态图实例
        _blue_map = StateGraph(MessageState)
        # 节点加入
        _blue_map.add_node("starter", self._starter)
        _blue_map.add_node("agent_node", self._agent_node)
        _blue_map.add_node("agent_tool", self._agent_tool)
        _blue_map.add_node("ender", self._ender)
        # 自定义子图内节点
        _ls_node = self._block_manager.all_nodes()
        for node in _ls_node:
            _blue_map.add_node(*node)
        # 边加入
        _blue_map.add_edge(START,"starter")
        _blue_map.add_conditional_edges("starter", self._router_before_agent,   # starter -> agent/customize
                                        list(set(
                                            self._block_manager.map_to_in_nodes(
                                                self._task_manager.all_router_before_agent() + ["agent_node", ])))
                                        )
        _blue_map.add_conditional_edges("agent_node", self._router_after_agent, # agent -> tool/ender/customize
                                        list(set(
                                            self._block_manager.map_to_in_nodes(
                                                self._task_manager.all_router_after_agent() + ["agent_tool", "ender"])))
                                        )
        _blue_map.add_edge("agent_tool", "agent_node")  # tool->agent
        # 自定义子图内边
        _ls_edge = self._block_manager.all_edges()
        for edge in _ls_edge:
            if edge[2]:  # 如果是条件边
                _blue_map.add_conditional_edges(edge[0], edge[2], self._block_manager.map_to_in_nodes(edge[1]))
            else:
                _blue_map.add_edge(edge[0], self._block_manager.map_to_in_nodes(edge[1][0]))

        return _blue_map.compile()
