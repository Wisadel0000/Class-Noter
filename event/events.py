from dataclasses import dataclass
from event.event_core import Event

@dataclass
class NotingStart(Event):
    """开始做笔记"""
    pass

@dataclass
class NotingStop(Event):
    """停止做笔记
    这个事件应使ASR立即停止录音，BackgroundAgent在完成工作后延迟停止
    """
    pass

@dataclass
class AppStart(Event):
    pass

@dataclass
class UserMessage(Event):
    content: str
    pass

@dataclass
class TaskMessage(Event):
    content: str
    pass

@dataclass
class MessageToUser(Event):
    content: str
    pass

@dataclass
class RequestReporterData(Event):
    """请求转述模块的新数据"""
    request_id:str  #与回复消息的id对应

@dataclass
class ReporterResult(Event):
    request_id: str
    data: str