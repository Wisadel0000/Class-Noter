
# from __future__ import annotations
import queue
import threading
import traceback
from collections import defaultdict
from typing import Any, Callable
from loguru import logger



class Event:
    pass

class _LoopStop(Event):  # 停止事件
    pass

# 方便使用的类型别名
Handler = Callable[[Event], None]

class Bus:
    """订阅表 + 同步分发。
    - Bus负责持有和维护订阅列表
    - 提供事件的订阅功能
    """

    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[Event], handler: Handler) -> Callable[[], None]:
        """把回调函数注册到特定的事件上
        - 返回一个函数用于取消订阅
        :param event_type: 事件类型
        :param handler: 回调函数
        """
        # TODO:最好加上线程锁
        self._handlers[event_type].append(handler)
        return lambda: self._handlers[event_type].remove(handler)  # 取消订阅

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

    # 任何线程都可以安全地投递事件
    def post(self, event: Event) -> None:
        """向Loop中投递一个事件"""
        self._queue.put(event)

    def register_stop_waiting_event(self,flag:threading.Event):
        self._wait_before_stop.append(flag)

    def stop(self) -> None:
        """用于停止Loop的运行"""
        self.post(self.STOP)

    def run(self) -> None:
        """Loop的核心逻辑：逐个发布队列中的事件"""
        logger.info(f"【Bus:{id(self.bus)}|Loop:{id(self)}】开始运行")
        self._running = True
        while self._running:
            event = self._queue.get()          # 阻塞等待（如果没拿到就等）
            if event is self.STOP:
                for flag in self._wait_before_stop:
                    if flag.wait(timeout=5):
                        continue
                    else:
                        logger.warning(f"【Bus:{id(self.bus)}|Loop:{id(self)}】关闭程序时出现超时未能结束的任务")
                self._running = False
                break
            self.bus.publish(event)

class Router:
    """事件路由器
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
