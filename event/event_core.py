
# from __future__ import annotations
import queue
import threading
import traceback
from collections import defaultdict
from typing import Any, Callable, overload
from loguru import logger

class LoopStopped(Exception):
    pass

class Event:
    pass

class ReplyEvent(Event):
    request_id:str
    data: Any

class RequestEvent(Event):
    request_id:str

class _LoopStop(Event):  # 停止事件
    pass

# 方便使用的类型别名
Handler = Callable[[Event], None]

_LOOP_RUN_CONTEXT = threading.local()   # 标记当前线程是不是某个 Loop 的 run() 线程

class Bus:
    """订阅表 + 同步分发。
    - Bus负责持有和维护订阅列表
    - 提供事件的订阅功能
    """

    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Handler]] = defaultdict(list)
        self._reply_events: list[type[ReplyEvent]] = []

    def subscribe(self, event_type: type[Event], handler: Handler) -> Callable[[], None]:
        """把回调函数注册到特定的事件上
        - 返回一个函数用于取消订阅
        :param event_type: 事件类型
        :param handler: 回调函数
        """
        # TODO:最好加上线程锁
        self._handlers[event_type].append(handler)
        return lambda: self._handlers[event_type].remove(handler)  # 取消订阅

    def subscribe_as_reply(self,event_type: type[ReplyEvent]):
        """只在接收端bus&loop上视为‘回信’事件，在未注册过的bus上视为普通事件，即只要总bus上没有对应的回调，就会正常转发。"""
        self._reply_events.append(event_type)
        return lambda: self._reply_events.remove(event_type)

    def is_reply_event(self,event):
        cls = type(event)
        return cls in self._reply_events

    def publish(self, event: Event) -> None:
        """向所有订阅者发布事件
        - 逐个回调所有订阅者
        :param event: 待发布的事件
        """
        # TODO:最好加上线程锁
        for cls in type(event).__mro__:
            handles = list(self._handlers.get(cls, ()))
            if cls not in [object,Event] and handles == []: logger.warning(f"【总线:{id(self)}】本轮事件{cls}的订阅者列表为空，请留意")
            for h in handles:
                try:
                    h(event)
                except Exception as e:
                    logger.error(f"【总线:{id(self)}】事件 {event} 处理失败：{e}")
                    traceback.print_exc()   # 一个 handler 出错不影响其他

class Loop:
    """事件队列 + 主循环。
    - Loop负责向Bus投递事件，并处理排队逻辑
    - 订阅表在Bus里，别找错类了，这里只负责投递
    """

    STOP = _LoopStop()

    def __init__(self, bus: Bus) -> None:
        self.bus = bus
        self._queue: queue.Queue[Event] = queue.Queue()
        self._running = False
        self._wait_before_stop: list[threading.Event] = []  # 一个列表用于保存所有在关闭时必须等待升起（等待某些逻辑完成）的旗帜
        self._lock = threading.Lock()
        self._mailbox: dict[str,dict] = {}    # 请求ID -> 回信数据{flag:threading.Event,data:dict}

    # 任何线程都可以安全地投递事件
    def post(self, event: Event) -> None:
        """向Loop中投递一个普通事件"""
        self._queue.put(event)

    def post_request(self,event:RequestEvent, aim_loop:"Loop"):
        """向Loop中投递一个请求事件
        # 请求-响应 机制
        # loop向总线询问每一个事件是被订阅为了‘回复’事件，如果是，则不发布而是在当前loop中完成数据接收等待需要的人来wait。
        """
        with self._lock:
            self._mailbox[event.request_id] = {"flag":threading.Event(),"data":None}
        aim_loop.post(event)
        logger.debug(f"【Bus:{id(self.bus)}|Loop:{id(self)}】成功投递了一个请求事件，request_id:{event.request_id}")

    def wait_reply(self,request_id:str,timeout:int=10,retry:int=14):
        """等待回复，然后return事件的data字典
        超时会报错
        """
        # 检查当前线程是不是运行再了某个事件Loop中，防止阻塞
        if getattr(_LOOP_RUN_CONTEXT, "active", False):
            raise RuntimeError(
                f"【Bus:{id(self.bus)}|Loop:{id(self)}】在事件循环线程里调用了 wait_reply，"
                f"占用总线等待回信可能造成死锁。请在独立工作线程中等待。request_id:{request_id}"
            )

        mail = self._mailbox[request_id]
        flag = mail.get("flag")
        for times in range(retry+1):  # 最多重试retry次(第一次不算重试)
            if flag.wait(timeout=timeout):  # 每次请求30秒
                # 不 用 等
                break
            if times < retry: logger.debug(f"【Bus:{id(self.bus)}|Loop:{id(self)}】本轮等待回信失败，正在重试（{times + 1}/{retry}）")
        else:
            # 没等到
            with self._lock:
                self._mailbox.pop(request_id, None)
            raise TimeoutError(f"【Bus:{id(self.bus)}|Loop:{id(self)}】内部总线等待超时。request_id:{request_id}")
        # 等到了
        with self._lock:
            self._mailbox.pop(request_id, None) #清理
            if mail.get("error"):
                raise LoopStopped(mail["error"])
            return mail.get("data")

    def _reply_response(self,event:ReplyEvent):
        """把接受到的回复装进对应的请求信箱"""
        logger.debug(f"【Bus:{id(self.bus)}|Loop:{id(self)}】响应了回复事件，request_id{event.request_id}")
        with self._lock:
            mail = self._mailbox.get(event.request_id)
            if mail and not mail["flag"].is_set():  # 如果信箱存在，且没有被回复过
                mail["data"] = event.data  # 保存回信数据
                mail["flag"].set()  # set旗帜，唤醒等待处的线程

    def register_stop_waiting_event(self,flag:threading.Event):
        self._wait_before_stop.append(flag)

    def stop(self) -> None:
        """用于停止Loop的运行"""
        self.post(self.STOP)

    def run(self) -> None:
        """Loop的核心逻辑：逐个发布队列中的事件"""
        _LOOP_RUN_CONTEXT.active = True  # Loop线程标记
        logger.info(f"【Bus:{id(self.bus)}|Loop:{id(self)}】开始运行")
        self._running = True
        try:
            while self._running:
                event = self._queue.get()  # 阻塞等待（如果没拿到就等）
                if event is self.STOP:
                    # 进入程序的停止逻辑
                    # 告知所有等待回信的线程不需要再等待了
                    with self._lock:
                        for mail in self._mailbox.values():
                            mail["error"] = "Loop 已停止"
                            mail["flag"].set()
                        self._mailbox.clear()
                    # 等待必须完成的代码逻辑结束
                    for flag in self._wait_before_stop:  # 等待必等项
                        if flag.wait(timeout=5):
                            continue
                        else:
                            logger.warning(f"【Bus:{id(self.bus)}|Loop:{id(self)}】关闭程序时出现超时未能结束的任务")
                    # 更新运行状态并退出while循环
                    self._running = False
                    break

                if self.bus.is_reply_event(event):
                    self._reply_response(event)  # 处理‘回复’
                else:
                    self.bus.publish(event)  # 触发注册的回调
        finally:
            _LOOP_RUN_CONTEXT.active = False  # Loop线程标记

class Router:
    """
    事件路由器
    负责辅助核心Loop转发事件到指定的模块级Loop中
    - 提供一个注册函数，用于指定特定事件的转发目标
    """
    def __init__(self,core_bus: Bus):
        self._routes : dict[type[Event], list[Loop]] = defaultdict(list)
        # 订阅
        core_bus.subscribe(Event, self.route)
        logger.info("Router:已将事件路由逻辑成功挂载到核心总线")

    def subscribe(self, event_type: type[Event], target_loop) -> Callable[[], None]:
        """ 订阅核心总线上的事件（原'注册路由表'）
        :param event_type: Loop要订阅的核心总线上的事件（待转发的事件类型）
        :param target_loop: 模块自己的Loop（需要转发到的目标Loop <实例>）
        :return 一个用于取消订阅（注册）的函数:
        """
        # TODO:最好加上线程锁
        self._routes[event_type].append(target_loop)
        return lambda: self._routes[event_type].remove(target_loop)

    def route(self, event: Event):
        """提供给核心Loop使用的'回调函数'
        - 使用时，本函数作为回调函数订阅Event这个基类，即可实现所有事件的转发
        """
        # TODO:最好加上线程锁
        #没写for cls in type(event).__mro___:等到程序真有这个需求再写
        for loop in self._routes.get(type(event), []):
            loop.post(event)
