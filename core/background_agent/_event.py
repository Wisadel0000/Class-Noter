from dataclasses import dataclass
from event.event_core import Event

@dataclass
class AgentLog(Event):
    content:str
    tool_calls:list[dict]

@dataclass
class TaskStartLog(Event):
    task_id:int
    task_name:str

@dataclass
class TaskOverLog(Event):
    task_id:int
    task_name:str
    # result_message:str    #最后一轮的message其实已经被打印过了，不用传（大概
