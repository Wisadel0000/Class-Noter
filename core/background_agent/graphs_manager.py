import os
from abc import ABCMeta #metaclass=ABCMeta,
from typing import Callable, Literal, Protocol, runtime_checkable
from langchain.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages import RemoveMessage
from core.background_agent.BaseTask import Task


# 图块机制，图块中声明的节点和边会在agent编译的过程中被正确拼接进Graph中
@runtime_checkable
class GraphBlock(Protocol):
    """
    图块：自定义的LangGraph子图，用于拼接在Agent工作图上
    图块中至少有一个入节点和一个出边，且保证图内连通。
    图块中若有model_with_tool，请在类内自行组建
    """
    graph_name: str
    in_node: tuple[str, Callable]
    """图块的进入节点"""
    out_edge: tuple[str, list[str], Callable,]
    """图块的出边[图内节点,图外节点列表,条件边判断函数]"""
    self_nodes: list[tuple[str, Callable]] = []
    """图块内的节点(不包括出节点)"""
    self_edges: list[tuple[str, list[str], Callable|None ]] = []    #列表中每一项的格式：(开始节点名, [结束节点名列表], 边判断函数/None) 如果不是条件边，则将结束节点列表中的第一个元素视为有效元素
    """图块内的边(不包括出边)"""  # 先这么写吧，之后再改成默认第0个边/节点特殊边/节点

class GraphBlockManager:
    def __init__(self):
        self._blocks: dict[str, type[GraphBlock]] = {}

    def register(self, graph_block: type[GraphBlock]):
        if graph_block.graph_name in self._blocks:
            raise ValueError(f"图块名'{graph_block.graph_name}'已被注册")

        self._blocks[graph_block.graph_name] = graph_block

    def map_to_in_nodes(self, address:str|list[str]):
        """"route_mapper路由映射器，
            根据已注册的图块名把所有图块名映射到真正的入节点上"""
        def check(ad: str):
            block = self._blocks.get(ad)
            return block.in_node[0] if block else ad

        if isinstance(address, str):
            return check(address)
        elif isinstance(address, list):
            return list(map(check, address))

    def all_nodes(self):
        blocks = list(self._blocks.values())
        all_in_nodes = [_.in_node for _ in blocks]
        all_self_nodes = [_ for block in blocks for _ in block.self_nodes]
        return all_in_nodes + all_self_nodes

    def all_edges(self):
        blocks = list(self._blocks.values())
        all_self_edges = [_ for block in blocks for _ in block.self_edges]
        all_out_edges = [_.out_edge for _ in blocks]
        return all_self_edges + all_out_edges

class GraphTaskManager:
    def __init__(self):
        self._tasks: dict[str, type[Task]] = {}

    def register(self, task: type[Task]):
        self._tasks[task.task_name] = task

    def all_router_before_agent(self):
        tasks = list(self._tasks.values())
        return [i.route_before_agent for i in tasks]

    def all_router_after_agent(self):
        tasks = list(self._tasks.values())
        return [i.route_after_agent for i in tasks]