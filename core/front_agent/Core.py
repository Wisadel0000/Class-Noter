from event.event_core import Bus,Loop,Router
from event.events import UserMessage, TaskMessage, MessageToUser, AskForWorkStateReport, WorkStateReport, AppStart, AppClose
from settings.routers.provider import ProviderRouter
from core.tools.ToolsManager import ToolsManager

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage, ChatMessage
from langgraph.checkpoint.memory import InMemorySaver
from queue import Queue
from loguru import logger
import threading


class FrontAgentModule:
    def __init__(self, core_bus_router:Router, core_loop:Loop, local_bus:Bus, local_loop:Loop, provider_router: ProviderRouter, tools_manager:ToolsManager):
        self._core_loop = core_loop
        self._local_bus = local_bus
        self._local_loop = local_loop
        self._provider_router = provider_router
        self._tools_manager = tools_manager

        self._running = True
        self._mailbox = Queue()  #Agent信箱，多个消息在这里排队
        self._stop_signal = object()   #哨兵事件，在停止程序时放进 mailbox
        self._messages = [] #消息记录
        self._talking_lock = threading.Lock()   #对话锁，保证同时只能有一个消息响应事件拿到和写入对话历史

        # ------ 注册回调函数 ------
        self._local_bus.subscribe(AppStart,self.run)
        self._local_bus.subscribe(AppClose,self.stop)
        self._local_bus.subscribe(UserMessage, self.response_message)
        self._local_bus.subscribe(WorkStateReport, self.receive_work_state_report)
        # ------ 订阅总线事件 ------
        core_bus_router.subscribe(AppStart, self._local_loop)
        core_bus_router.subscribe(AppClose, self._local_loop)
        core_bus_router.subscribe(UserMessage,self._local_loop)
        core_bus_router.subscribe(WorkStateReport,self._local_loop)

        # 先注册工具，别一会儿agent创建的时候获取不到（，等之后加了动态中间件就不用考虑加载顺序了
        self._tools_manager.register(name="set_custom_task", tool_func=self.set_custom_task,description="用于给后台的笔记Agent发送自然语言描述的命令")
        self._tools_manager.register(name="ask_for_work_state", tool_func=self.ask_for_work_state,description="用于向后台咨询笔记Agent的工作进度，比如‘现在进展到哪儿了’，‘刚刚勾股定理的知识记录下来了吗’等问题，稍后将会收到工作进度报告")
        self._tools_manager.tool_set_register(set_name="front_agent", tool_names=["set_custom_task","ask_for_work_state",])
        #构建agent对象
        self._agent = self._agent_compile()

    # 记得未来搭配隔壁项目的动态中间件模块实现工具热拉取（记得警告用户在运行时临时修改工具列表可能会导致kv缓存命中率大幅受损 ）
    def _agent_compile(self):
        agent = create_agent(
            model=self._provider_router.get_default_model(),
            tools=self._tools_manager.get_tool_set_by_list(["front_agent","web_search_tools"]),
            system_prompt="""你是一个学习助手，负责和用户探讨与学习相关的内容。
                              在后台有一个笔记agent负责在上课时根据课堂内容整理结构化的笔记文件库，或根据你的命令完成对应的笔记任务，
                              如果用户有对笔记进行修改的需求，你可以调用工具给后台笔记agent下达任务命令（用自然语言描述任务要求）。
                              如果用户需要询问后台工作进度，也有对应工具可以调用，调用后，后台会在整理好工作进度汇报之后向你回信，接到回信后请向用户汇报结果
                              如果用户的问题/困惑涉及需要严谨回答的专业知识，你可以使用联网搜索功能查询相关信息，以提高你提供的解答的准确性和最新性。
                              """,
            checkpointer=InMemorySaver()
        )
        return agent

    #  ------ 消息响应 ------

    # 收到用户的消息
    def response_message(self, event: UserMessage):
        message = HumanMessage(content=event.content)
        logger.debug(f"用户发送消息：{event.content}")
        self._post_message_to_mail(message)
    # 收到工作日志汇报
    def receive_work_state_report(self, event: WorkStateReport):
        message = ChatMessage(content=event.content,role="user",name="后台工作进度汇报")    #创建消息
        self._post_message_to_mail(message)

    # ------ Agent消息投递与回信 ------

    def _post_message_to_mail(self,message: BaseMessage|object):
        self._mailbox.put(message)

    def _message_cost_loop(self):
        while self._running:
            message = self._mailbox.get()
            if message is self._stop_signal:
                break
            try:
                self._anymessage_to_agent(message)
            except TimeoutError as e:
                logger.error(f"agent请求超时:{e}")
                self._core_loop.post(MessageToUser("agent请求超时，请检查网络连接或自定义模型运行状态"))
            except Exception as e:
                logger.error(f"agent请求时意外错误:{e}")
            finally:
                continue
        # 前台Agent不做读写等危险操作，不需要等待结束。不设置必等旗帜，loop线程作为守护线程直接结束

    def _anymessage_to_agent(self,message: BaseMessage):
        with self._talking_lock:
            self._messages = self._agent.invoke({"messages": [message]},
                                                config={"configurable": {"thread_id": "1"}})
            logger.debug(f"前台向用户发送消息：{self._messages['messages'][-1].content}")
            self._core_loop.post(MessageToUser(self._messages["messages"][-1].content))

    # ------ 给agent用的工具（通过发布事件） ------
    def set_custom_task(self,task_message:str):
        """用于给后台的笔记Agent发送自然语言描述的命令"""
        self._core_loop.post(TaskMessage(content=task_message))
        logger.debug(f"已向创建后台任务，任务正文：{task_message}")
    def ask_for_work_state(self, ask_message:str):
        """用问句向后台咨询笔记Agent的工作进度，比如‘现在进展到哪儿了’，‘刚刚勾股定理的知识记录下来了吗’等问题，稍后将会收到工作进度报告"""
        self._core_loop.post(AskForWorkStateReport(content=ask_message))
        logger.debug(f"已向发起任务进度咨询，问题：{ask_message}")

    # ------ 启动&结束 ------
    def stop(self,e:AppClose):
        self._running = False
        self._post_message_to_mail(self._stop_signal)

    def run(self,e:AppStart):
        threading.Thread(target=self._message_cost_loop,daemon=True).start()