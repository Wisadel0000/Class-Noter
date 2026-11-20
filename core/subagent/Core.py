"""
用线程池管理多个subagent消费者/调用进程。

# 在此之前，先去给事件loop加上事件回信机制
"""

import threading
from queue import Queue
from concurrent.futures import ThreadPoolExecutor
from event.event_core import Bus,Loop,Router
from event.events import CreateSubAgentTask, SubAgentResult, AppClose
from core.subagent.SubTask import SubTask
from core.subagent.SubAgents import SubAgents


class SubAgentModule:
    def __init__(self,  core_bus_router:Router, core_loop:Loop, local_bus:Bus, local_loop:Loop, sub_agent:SubAgents): # 这一根25；
        self._core_loop = core_loop
        self._local_bus = local_bus
        self._local_loop = local_loop
        self._subagents = sub_agent

        self._agent_pool = ThreadPoolExecutor(max_workers=10)   # 默认线程池数上限10，后续接入设置
        self._waited_task_ids:list[str] = []
        self._lock = threading.Lock()

        # ------ 订阅回调 ------
        self._local_bus.subscribe(CreateSubAgentTask,self.add_new_subtask)

        # ------ 订阅核心总线事件 ------
        core_bus_router.subscribe(CreateSubAgentTask,self._local_loop)

    def _invoke_and_reply(self, request_id:str ,task: SubTask):
        result = self._subagents.invoke(task)
        with self._lock:
            self._waited_task_ids.remove(request_id)
        data = {"result":result,"app_close":False}
        self._core_loop.post(SubAgentResult(request_id,data))

    def add_new_subtask(self, event: CreateSubAgentTask):
        with self._lock:
            self._waited_task_ids.append(event.request_id)  #关闭时会用到，给所有没运行完的任务提前进行回复
        task = SubTask(task_describe=event.task_describe,
                       attachment_content=event.attachment_content,)
        self._agent_pool.submit(self._invoke_and_post_reply, request_id=event.request_id,task=task)

    def stop_run(self,event:AppClose):
        self._agent_pool.shutdown()
        with self._lock:
            for request_id in self._waited_task_ids:
                self._core_loop.post(SubAgentResult(request_id,{"result":None,"app_close":True}))