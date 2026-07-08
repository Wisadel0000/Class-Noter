#导包
import abc
import threading

#------------------------
#初始化
class Event(metaclass=abc.ABCMeta):
    pass

class Run(Event):
    pass
class RunNoter(Event):
    pass
class ASRInit(Event):
    pass
class NoteStart(Event):
    pass
def run_noter():
    BUS.emit(ASRInit)
    BUS.emit(NoteStart)

class EventBus:
    def __init__(self):
        self._handlers ={}   #事件注册表(事件名->[回调函数列表])
        self._lock = threading.Lock()   #线程锁

    def on(self,event:Event,handler):
        with self._lock:
            self._handlers.setdefault(event.__name__, []).append(handler)

    def off(self, event:Event, handler):
        with self._lock:
            self._handlers.get(event.__name__, []).remove(handler)

    def emit(self,event:Event,**kwargs):
        for handler in  self._handlers.get(event.__name__, []):
            handler(**kwargs)

    def on_async(self, event: Event, handler):
        def wrapper(**kwargs):
            threading.Thread(target=handler, kwargs=kwargs, daemon=True).start()
        with self._lock:
            self._handlers.setdefault(event.__name__, []).append(wrapper)

    def once(self,event:Event,handler):
        def wrapper(**kwargs):
            handler(**kwargs)
            self.off(event, wrapper)
        self.on(event,wrapper)

    def emit_async(self,event:Event,**kwargs):
        threading.Thread(target=self.emit, args=(event,), kwargs=kwargs, daemon=True).start()

#------------------------
#逻辑部分

BUS = EventBus()