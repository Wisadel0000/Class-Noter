import threading
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict, Annotated
from loguru import logger
from datetime import date

from core.tools.ToolsManager import ToolsManager
from core.subagent.SubTask import SubTask
from core.wiki.read_wiki_rules import get_wiki_rule
from settings.routers.provider import ProviderRouter

# 定义Agent的消息state    (以类型注解的形式)
class MessageState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    task: SubTask
    llm_calls: int

class SubAgents:
    """提供subagent实例"""
    def __init__(self, provider_router: ProviderRouter, tools_manager: ToolsManager, ):
        self._provider_router = provider_router
        self._tools_manager = tools_manager

        self._tool_sets = ["default","wiki_tool_set"]
        self._agent = self.compile()    #实例
        self._wiki_rules = get_wiki_rule()
        self._system_prompt:str ="""
你是一个wiki笔记自动管理系统中负责完成页面编辑的agent。
请根据你接收到的“本次任务描述”来完成对应的笔记修改任务。“附加信息”中会提供本次任务可能用到的知识点描述或其他提示。
"""
        self._page_lock: dict[str, threading.Lock] = {} #TODO: 页面锁，用于保护同一个文件在一次从‘读’到‘写’的全过程中文件不被其他subagent修改。

    # ------ 向外暴露的方法 ------

    def invoke(self,task:SubTask):
        result_state = self._agent.invoke({"messages": [],"task":task,"llm_calls": 0})
        return result_state["messages"][-1].content

    # ------ Agent结构定义 ------

    # agent节点
    def _agent_node(self,state: dict):
        """"
        agent “观察-执行”循环节点————观察节点
        """
        now_date = f"今日日期为：{date.today().isoformat()}\n"
        model  = self._provider_router.model_route()

        # 提示词获取与构建
        task = state["task"]
        system_msg = f"{self._system_prompt}\n" + f"wiki页面语法规则:\n{self._wiki_rules}\n"
        human_msg = f"""
本次任务描述：
{task.task_describe}
本次任务附加信息：
{task.attachment_content}
"""
        # 工具列表获取
        _tools =  self._tools_manager.get_tool_set_by_list(self._tool_sets)
        # 工具嵌入
        _model_with_tools = model.bind_tools(_tools)

        last_messages = state["messages"]
        last_messages = [SystemMessage(content=system_msg),HumanMessage(content=human_msg)] + last_messages  # TODO记得修改为ChatMessage版本查看效果

        result = _model_with_tools.invoke(last_messages)
        logger.debug(f"subagent工作输出:{result.content}")
        logger.debug(f"subagent本轮工具调用:{result.tool_calls}")

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
        pass
        return

    def _ender(self, state: dict):
        pass
        return

    def _router_before_agent(self, state: MessageState) -> str:
        return "agent"

    def _router_after_agent(self, state: MessageState) -> str:
        # 取出最新的消息
        messages = state["messages"]
        last_message = messages[-1]

        # 观察大模型是否进行了工具调用 （tool_call 字段是否不为空）
        if last_message.tool_calls:
            return "agent_tool"  # 进入agent_tool节点
        else:
            return "end"

    def compile(self):
        # 状态图实例
        _blue_map = StateGraph(MessageState)
        # 节点加入
        _blue_map.add_node("starter", self._starter)
        _blue_map.add_node("agent_node", self._agent_node)
        _blue_map.add_node("agent_tool", self._agent_tool)
        _blue_map.add_node("ender", self._ender)

        # 边加入
        _blue_map.add_edge(START,"starter")
        _blue_map.add_conditional_edges("starter", self._router_before_agent,["agent_node", ])
        _blue_map.add_edge("agent_tool", "agent_node")
        _blue_map.add_conditional_edges("agent_node", self._router_after_agent, ["agent_tool", "ender"])

        return _blue_map.compile()
