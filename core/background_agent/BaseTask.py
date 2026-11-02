from abc import ABCMeta
from typing import Callable

# 我到底要不在这里导入event模块的东西？是不是耦合了？


class Task(metaclass=ABCMeta):
    """任务至少要包含的基本信息（用于限定格式的抽象类，不应被实例化）"""
    task_name: str  # 任务名
    task_priority = 3  # 优先级从1到5，默认3
    route_before_agent: str
    route_after_agent: str


class FunctionTask(Task):
    """函数类任务，此类任务仅执行提供的回调函数，然后即完成调用"""
    handler: list[Callable]


class AgentTask(Task):
    """代理类任务，此类任务在工作中需要使用到agent的工作能力 """
    task_prompt: str
    task_message: str
    tool_set_name: str


class MultiTask(Task):
    """复合类任务，同时属于函数和代理类任务"""
    handler: list[Callable]
    task_prompt: str
    task_message: str
    tool_set_name: str