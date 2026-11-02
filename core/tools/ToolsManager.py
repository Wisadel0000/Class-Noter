from langchain_core.tools import StructuredTool
from typing import Callable
from pydantic import BaseModel


class ToolsManager:
    def __init__(self):
        self._registry:dict[str,StructuredTool] = {}
        self._tool_sets:dict[str,list[str]] = {}

    def register(self, name: str, tool_func: Callable, description: str,args_schema = None):
        #名字去重
        if name in self._registry:
            raise ValueError(f"工具名{name}已被注册")

        #检测args_schema有没有被传入，没被传入则创建tool时不传入这个参数
        # 构建kwargs
        kwargs = {
            "func":tool_func,
            "name":name,
            "description":description,
        }
        # 如果没传入args_schema，则创建tool时不写这个参数
        if args_schema is not None:
            kwargs["args_schema"] = args_schema

        # 创建
        new_tool = StructuredTool.from_function(**kwargs)
        self._registry[name] = new_tool

        def unregister():
            self._registry.pop(name)

        return unregister

    def tool_set_register(self,set_name:str,tool_names:list[str]):
        #检测tool_name是否都为注册过的工具名
        for tool_name in tool_names:
            if tool_name not in self._registry:
                raise ValueError(f"工具名 {tool_name} 未注册")
        #注册
        self._tool_sets[set_name] = tool_names

    def get_tool_by_name(self, name: str):
        tool = self._registry.get(name)
        if tool is None: raise ValueError(f"工具名 {name} 未注册")
        return tool

    def get_tools(self):
        return list(self._registry.values())

    def get_tool_set(self, set_name: str) -> list:
        name_set = self._tool_sets.get(set_name)
        if name_set is None:raise ValueError(f"工具集名 {set_name} 未注册")
        tools = map(self.get_tool_by_name, name_set)
        return list(tools)
