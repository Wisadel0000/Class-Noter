from event.event_core import Bus,Loop,Router,Event
from event.events import UserMessage, TaskMessage, MessageToUser
from router.provider import LLMRouter
from core.tools.ToolsManager import ToolsManager

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from loguru import logger

class FrontAgentModule:
    def __init__(self,core_bus_router:Router,core_loop:Loop,local_bus:Bus,local_loop:Loop,provider_router: LLMRouter,tools_manager:ToolsManager):
        self._core_loop = core_loop
        self._local_bus = local_bus
        self._local_loop = local_loop
        self._provider_router = provider_router
        self._tools_manager = tools_manager

        # ------ 注册回调函数 ------
        self._local_bus.subscribe(UserMessage, self.response_message)
        # ------ 订阅总线事件 ------
        core_bus_router.subscribe(UserMessage,self._local_loop)

        # 先注册工具，别一会儿agent创建的时候获取不到（，等之后加了动态中间件就不用考虑加载顺序了
        self._tools_manager.register(name="set_custom_task", tool_func=self.set_custom_task,description="用于给后台的笔记Agent发送自然语言描述的命令")
        self._tools_manager.tool_set_register(set_name="front_agent", tool_names=["set_custom_task"])
        #构建agent对象
        self._agent = self._agent_compile()

    # 记得搭配隔壁的Muilty模块
    def _agent_compile(self):
        agent = create_agent(
            model=self._provider_router.get_default(),
            tools=self._tools_manager.get_tool_set("front_agent"),
            system_prompt="""你是一个课堂助手，负责和用户探讨与学习相关的内容。
                              在后台有一个笔记agent负责根据课堂内容整理结构化的笔记文件库。
                              如果用户有对笔记进行修改的需求，你可以调用工具给后台笔记agent下达任务命令（用自然语言描述任务要求）。""",
            checkpointer=InMemorySaver()
        )
        return agent

    def response_message(self, event: Event):
        message = HumanMessage(content=event.content)
        logger.debug(f"用户发送消息：{event.content}")
        self._messages = self._agent.invoke({"messages": [message]},
                                            config={"configurable": {"thread_id": "1"}},)
        logger.debug(f"前台助手已完成回复：{self._messages['messages'][-1].content}")
        self._core_loop.post(MessageToUser(self._messages["messages"][-1].content))

    # 这个函数是给agent用的工具
    def set_custom_task(self,task_message:str):
        """用于给后台的笔记Agent发送自然语言描述的命令"""
        self._core_loop.post(TaskMessage(content=task_message))
        logger.debug(f"已向创建后台任务，任务正文：{task_message}")
