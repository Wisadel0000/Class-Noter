"""
日志器
- 以块为单位接收来自Agent的输出信息，并在这里完成对“任务状态”和“日志”的维护 -bingo
- 接收任务开始和任务完成的事件，以按时清理工作日志缓存    -bingo
- 为前台Agent提供事件响应，在前台Agent询问后，整理当前进度介绍，并发送事件向前台回信 -bingo
- 提供日志更新事件，供Gui滚动显示。 --bingo

"""
import threading
from loguru import logger
from time import sleep
from queue import Queue
from langchain_core.messages import SystemMessage,HumanMessage, ChatMessage

from core.background_agent._event import AgentLog,TaskOverLog,TaskStartLog
from core.tools.ToolsManager import ToolsManager
from event.event_core import Bus,Loop,Router,Event
from event.events import AppStart, TaskLogUpdate, AskForWorkStateReport, WorkStateReport
from router.provider import LLMRouter

class LogStore:
    def __init__(self,core_bus_router:Router,core_loop:Loop,local_bus:Bus,local_loop:Loop,provider_router:LLMRouter,tools_manager:ToolsManager):
        self._core_loop:Loop = core_loop
        self._local_bus:Bus = local_bus
        self._local_loop:Loop = local_loop
        self._provider_router = provider_router
        self._tools_manager:ToolsManager = tools_manager

        self._now_task: str | None = None    #当前任务状态
        self._now_messages: list[str] = []      #当前工作日志
        self._running: bool = False  #用于记录当前程序是否正在运行
        self._log_poster_queue: Queue[TaskLogUpdate] = Queue()

        # ------ 注册回调 ------
        # from core
        self._local_bus.subscribe(AppStart, self.when_run_app)
        self._local_bus.subscribe(AskForWorkStateReport,self.work_state_report)
        # from local
        self._local_bus.subscribe(AgentLog,self.receive_agent_log) #模块内事件不用从核心总线上调
        self._local_bus.subscribe(TaskStartLog,self.task_start)
        self._local_bus.subscribe(TaskOverLog,self.task_over)
        # ------ 订阅核心总线事件 ------
        # 在Core中已经完成了对AppStart的订阅，不用写AppStart的订阅
        core_bus_router.subscribe(AskForWorkStateReport,self._local_loop)

    def _log_poster_cycle(self):
        """如果用上面那个延迟发送，每个消息都要申请新线程，太浪费了"""
        wait = 1    # 每轮至少间隔时间
        while self._running:
            sleep(wait)    #每次消息间隔wait秒钟
            event = self._log_poster_queue.get()    #等待
            self._core_loop.post(event)

    def _post_log(self,task:str|None,content:str|None):
        self._log_poster_queue.put(TaskLogUpdate(task,content)) #如果task=None前端/Gui则会显示“空闲中”

    def task_start(self,event:TaskStartLog):
        self._now_task = event.task_name

    def task_over(self,event:TaskOverLog):
        self._post_log(task=None,content="暂无正在进行的工作")  #更新前台日志
        self._now_task = None   #重置
        self._now_messages = [] #清空

    def receive_agent_log(self,event:AgentLog):
        """
        本方法负责收到信息后把信息加入工作历史并发送日志给GUI
        - 如果只有正文输出（多轮调用结束时）或者只有工具调用（某些无显示输出的工具调用轮）输出，则立即发送
        - 如果同时都有，则会间隔一秒钟错峰发送，以免前台显示刷新太快
        """
        if not event.content == "": #如果输出不为空（这里一定是字符串不会是None）
            self._now_messages.append(f"agent输出:{event.content}")    # 加入历史
            self._post_log(self._now_task, event.content)   #发送日志
        if event.tool_calls:    # 如果非空
            # 只取工具名和工具的提交消息。
            # 尝试获取工具的日志方法
            tool_calls = []
            for call in event.tool_calls:
                log_func = self._tools_manager.get_log_func_by_name(call["name"])
                if log_func:
                    content = f"调用了工具:{call["name"]},调用详情:{log_func(**call["args"])}"
                else:
                    content = f"调用了工具 :{call['name']}"  # 没有日志方法就只会显示名字，不利于大模型阅读，不建议这么做，最好还是写一个对应的日志工具
                tool_calls.append(content)
                self._post_log(self._now_task, str(content))
            self._now_messages.append("\n".join(tool_calls))
            # self._sent_log_later(self._agent_now_task,"\n".join(tool_calls),wait=wait)

    def work_state_report(self,event:AskForWorkStateReport):
        """用于向GUI回信报告当前工作状态"""
        model = self._provider_router.route()
        system_prompt = """
        你是一个日志汇报员，你负责根据后台agent的工作日志给前台agent汇报其咨询的工作进展详情。
        你应该直接生成回答的具体内容，且简洁干练，切中问题要点。
        如果前台问你“当前进度到哪儿了”或者让你“汇报最近进展”，则不用观察工具调用信息，直接根据agent输出的计划内容和最后一轮的工作进度来回答。
        """
        request = f"目前全部后台工作日志：\n{"\n".join(self._now_messages)}" + f"前台咨询内容:{event.content}"
        result = model.invoke([SystemMessage(system_prompt),ChatMessage(content= request,role="前台Agent")])

        logger.debug(f"工作日志报告输出：{result}")

        #投递回信
        self._core_loop.post(WorkStateReport(result.content))

    def when_run_app(self, event:Event):
        self._running = True #更新运行状态
        #启动自动投递线程
        threading.Thread(target=self._log_poster_cycle, daemon=True).start()

