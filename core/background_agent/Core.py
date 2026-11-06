"""
我他妈再也不想看到这坨代码了，现在只有上帝才能看懂这玩意。
有的逻辑设计我甚至都没法解释成注释。
总之尽量别动某些代码行的顺序。
"""

from itertools import count
from queue import PriorityQueue
from loguru import logger
import threading
import uuid
import time

# TODO后面记得清理掉这行导入
from langchain.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage

from event.event_core import Bus,Loop,Router,Event
from event.events import AppStart, AppClose, NotingStart, NotingStop,TaskMessage, ReporterResult, RequestReporterData
from core.background_agent.BaseTask import Task, FunctionTask
from core.background_agent.Tasks import NotingTask, MessageTask
from core.background_agent.Agent import BackgroundAgent
from core.background_agent.log_store import LogStore
from core.wiki.read_wiki_rules import get_wiki_rule

class _STOP_LOOP(Task):
    task_name:str = "STOP_LOOP"
    pass


"""本模块的核心任务是维护后台agent任务循环"""
class BackgroundAgentModule:
    def __init__(self,core_bus_router:Router,core_loop:Loop,local_bus:Bus,local_loop:Loop, agent: BackgroundAgent, log_store:LogStore):
        self._core_loop = core_loop
        self._local_bus = local_bus
        self._local_loop = local_loop
        self._agent = agent
        self._log_store = log_store # 仅持有该模块，无相关逻辑

        self._STOP = _STOP_LOOP()   # 用于停止任务循环，防止queue.get()持续等待
        self._task_looping = False
        self._noting = False    # flag,用于标识是否维持笔记循环（在拿到一个noting任务的时候往任务循环里塞入一个新的noting任务）
        self._task_list = PriorityQueue()
        self._counter = count()  # 本字段用来保证优先级队列能够按任务创建顺序正常排序，不代表实际意义
        self._lock =  threading.Lock()
        self._loop_finish_event = threading.Event()

        # ↓运行时的值形如{114514:{"flag":threading.Event(),"data": "..."}}，转述模块的回信数据会保存在这里的data字段中，flag字段用于标识数据传回状态（已到达/未到达）
        self._reported_data: dict[str,dict] = {}    # 请求ID -> 回信数据
        self._notting_singleton_lock: list[int] = [0]   # 用来假装一个可以就地修改的int值，用于对笔记任务进行去重。初值必须为0（虽然是list但实际上只会用到第一个位置的值）

        # ------ 注册关闭时等待事件 ------
        self._local_loop.register_stop_waiting_event(self._loop_finish_event)

        # ------ 注册回调函数 ------
        self._local_bus.subscribe(AppStart,self.run)
        self._local_bus.subscribe(AppClose,self.stop)
        self._local_bus.subscribe(NotingStart,self.noting_start)
        self._local_bus.subscribe(NotingStop,self.noting_stop)
        self._local_bus.subscribe(TaskMessage,self.response_task_message)
        self._local_bus.subscribe(ReporterResult,self.response_report_result)   # 接收转述模块的回信

        # ------ 订阅总线事件 ------
        core_bus_router.subscribe(AppStart,self._local_loop)
        core_bus_router.subscribe(AppClose,self._local_loop)
        core_bus_router.subscribe(NotingStart,self._local_loop)
        core_bus_router.subscribe(NotingStop,self._local_loop)
        core_bus_router.subscribe(TaskMessage,self._local_loop)
        core_bus_router.subscribe(ReporterResult,self._local_loop)

    def _append_task(self, task: Task):
        if task is self._STOP:
            self._task_list.put((-114514, next(self._counter), task))   # STOP任务会被排在最前面
            return
        # task的合法性检查
        if not (task.task_name and task.route_before_agent and task.route_after_agent):
            raise ValueError("任务名，Agent前路由和Agent后路由不能为空！")
        self._task_list.put((task.task_priority, next(self._counter), task))

    def _append_task_before_second(self, task: Task, _time: float = 20.0, singleton_lock: list[int] = None):
        # singleton_lock这个list[int]参数第一位的初值必须为0，用于对持有相同锁对象的任务去重，出现重复的延时任务时只会真正运行最后一个启动的延时的任务。
        # 原理：用锁记录有几个正在进行的使用该锁的任务，每个延时任务会尝试给锁值-1，只有减到0的那一次会触发后续任务
        def _append_task():
            if singleton_lock:  # 如果传入了锁则进行去重判断
                with self._lock:
                    singleton_lock[0] -= 1
                    if singleton_lock[0] != 0:
                        logger.debug(f"存在重复的{task.task_name}任务,已去重")
                        return  # 减完不是零 -> 还有正在进行的延迟回调，本轮任务提前结束
            self._append_task(task)

        timer = threading.Timer(_time, _append_task)
        timer.daemon = True  # 必须在 start() 之前设置

        if singleton_lock:  #如果传入了锁
            with self._lock:
                singleton_lock[0] += 1
        timer.start()

    def response_task_message(self,event:TaskMessage):
        # 先创建一个task，然后再加入队列
        logger.debug(f"后台队列已收到任务，任务正文：{event.content}")
        task = MessageTask(task_message= event.content)
        self._append_task(task)

    def response_report_result(self,event:ReporterResult):
        with self._lock:
            box = self._reported_data.get(event.request_id)     # 拉取信箱对象
            if box and not box["flag"].is_set():    # 如果信箱已经被清理掉了（比如被超时中断）或者已经回过信了（怎么可能？）就不管这个回复
                box["data"] = event.data    # 保存回信数据
                box["flag"].set()           # set旗帜，唤醒等待处的线程

    def _task_init(self, task):
        """每次调用agent前使用,用来处理不同agent任务可能拥有的不同初始化逻辑
        - 比如拼装提示词什么的（
        """
        """笔记任务"""
        if isinstance(task, NotingTask):
            """
            # Noting任务特殊处理:
            # 需要自动创建下一次笔记任务
              如果_noting==True则在任务队列中加入一个新的NotingTask,
              否则不会再产生下一次NotingTask
            # 然后是每次需要在这里拉取隔壁转述模块的最新转述数据
            """
            if not self._noting: logger.info("最后一轮笔记整理开始")  # 至少告诉大家还有一轮正在进行的笔记任务（（

            # ------  拉取数据开始拼装提示词  ------
            # 初始化信箱参数
            message_id = uuid.uuid4().hex
            message_flag = threading.Event()
            box = {"flag": message_flag, "data": None}  #转述模块的回信数据会保存在这里的data字段中，flag字段用于标识数据传回状态（已到达/未到达）
            with self._lock:
                self._reported_data[message_id] = box
            #发出请求
            self._core_loop.post(RequestReporterData(message_id))
            logger.debug(f"已发出转述文本拉取请求,task_id:{id(task)}")

            #等待回信与重试（如果拉取出现超时，我觉得不应该让agent跑一个空提示词的任务，且极大概率会丢失一次转述，这一点对做笔记这种工作来说还挺致命的。但是又不能一直让这地方等待，因为如果在笔记模式结束的时候代码运行到这里又不反复检查noting的值的话可能后续其他类型的任务都会被卡住，所以设置15次重试。）
            for times in range(15): #最多重试等待15次
                if message_flag.wait(timeout=30):   # TODO如果后面发现总是超时可以改一改这个timeout
                    break
                if times < 14: logger.debug(f"本轮等待失败，正在重试（{times+1}/14）")
            # 没等到则会直接报错跳过后续逻辑
            else:
                if self._noting:    # 如果已经不再noting了就可以不用报错了，属于正常退出。
                    raise TimeoutError(f"数据拉取异常超时，笔记循环将被强行终止，请检查代码逻辑。task_id:{id(task)}")
            logger.debug(f"成功拉取数据,task_id:{id(task)}")

            # 把转述数据装进task
            new_report = box["data"]
            if new_report is None or new_report == "":
                logger.warning(f"本轮转述数据为空！,task_id:{id(task)}")
            logger.debug(f"本轮转述数据<task_id:{id(task)}>：\n{new_report}")

            # ------ 拼装提示词与人类消息 ------
            new_text = f"课堂原文：{new_report}\n\n"

            # 构建知识归纳列表
            llm_invoke = self._agent.get_llm_invoke()   #从Agent模块借用一下模型
            digester_prompt = """
            你的任务是根据用户发送的课堂语音转写文字，提取老师讲到的所有知识点。请直接输出提取结果，不要输出其他内容。
            
            要求：
            - 你可以对原文内容进行理解、归纳和概括，但不得添加原文中未提及的任何背景知识、定义或补充说明。
            - 语音识别可能存在错别字（如将“弗朗西斯科”误识别为“菲斯科西里洛”），请结合上下文修正明显的专有名词错误。（不用标注原文）
            - 如果某段信息包含多个要点，请使用 Markdown 分点或分层标题输出，保持逻辑层次。
            - 如果有，请尽量保留原文中的因果关系和论证过程，避免只抽取结论。
            - 如果有的概念只是被提及，请明确标注“该概念仅被提及，无具体解释”
            
            如果文本中没有有效知识点，请输出“本轮无知识点”。
            """
            new_knowledge = f"本轮课堂新增知识点：{llm_invoke([SystemMessage(content=digester_prompt), HumanMessage(content=new_text), ]).content}\n\n"
            logger.debug(f"本次知识摘要结果：{new_knowledge}")
            task.task_message = new_knowledge + new_text  # TODO当前的笔记任务提示词只包含最新一轮的转述数据

            # 拼接提示词
            wiki_rule = f"""\n
            ##wiki语法介绍：
            {get_wiki_rule()}\n\n
            """
            task.task_prompt = task.task_prompt + wiki_rule + "现在请等待用户发送“本轮新增知识点”和“课堂原文”，随后开始工作"

            # 清理信箱
            with self._lock:
                self._reported_data.pop(message_id, None) # None为设定的默认返回值，以防pop()在找不到key时抛出异常
            # 产生下一次笔记任务
            if self._noting:    # 如果还处于笔记模式则继续维持笔记循环
                self._append_task_before_second(NotingTask(), 30, self._notting_singleton_lock) # 新建对象是因为这里原本的task已带有init信息了（本行代码必须位于等待逻辑之后，因为等待失败的时候要强行中断笔记循环，所以得确认笔记能正常继续再生成新的任务）

    def noting_start(self, event:Event):
        logger.debug("后台Agent层已收到笔记开始事件")
        if self._noting: return  # 如果已经处于笔记模式则返回
        self._noting = True
        self._append_task_before_second(NotingTask(),30, self._notting_singleton_lock)# 把Noting任务加入任务队列

    def noting_stop(self, event:Event = None):
        self._noting = False

    def task_loop(self):
        self._task_looping = True
        while self._task_looping:
            task = self._task_list.get()[2]  # 阻塞等待（如果没拿到就等）
            logger.debug(f"任务管理器已获取新任务：{task}")

            if task is self._STOP:
                break   #停止Loop

            """如果是函数类任务则直接执行handler完事"""
            if isinstance(task, FunctionTask):
                if task.handler:
                    for handle in task.handler:
                        handle()
                continue # 跳过agent执行，直接进入下一次循环

            """调用agent"""
            try:
                self._task_init(task)
                self._agent.invoke(task)
            except TypeError as e:
                logger.warning(f"任务管理器执行时出现无法识别的任务：{e} \n已跳过本轮任务。请尽快自查代码逻辑")
            except TimeoutError as e:
                logger.warning(e)
                # 停止笔记循环
                self.noting_stop()
                # 清理信箱
                with self._lock:
                    self._reported_data.clear()
            except Exception as e:
                logger.error(f"任务管理器执行时出现意外错误：{e} \n请尽快自查代码逻辑")
                raise e # 日志记完了，抛出异常
        # loop结束后升起结束旗帜
        logger.info("后台任务Loop已结束")
        self._loop_finish_event.set()

    def stop(self,event:AppClose):
        self._append_task(self._STOP)
        self._task_looping = False
        self._agent.stop_working()  #掐断后台agent循环决策（仅对默认agent图有效，如果运行在自定义图块上则无效）

    def run(self,event:Event):
        task_loop_thread = threading.Thread(target=self.task_loop, daemon=True)
        task_loop_thread.start()