from langchain_core.tools import StructuredTool
from typing import Callable
from pydantic import BaseModel
import inspect


class ToolsManager:
    def __init__(self):
        self._registry:dict[str,StructuredTool] = {}
        self._log_typer:dict[str,Callable|None] = {} # 给工具函数提供的自定义日志显示方法，可以用这个方法来进行自定义日志显示内容，也可以设置为None，默认
        self._tool_sets:dict[str,list[str]] = {}

    def _signature_without_return(self,func: Callable):
        """获取函数的签名（不含return），会用于比较函数头上定义的参数列表是否一致"""
        signature = inspect.signature(func)
        return signature.replace(return_annotation=inspect.Signature.empty)  # return注解都改为“无默认返回值”

    def register(self, name: str, tool_func: Callable, description: str,args_schema = None, log_func: Callable|None = None):
        #名字去重
        if name in self._registry:
            raise ValueError(f"工具名{name}已被注册")
        # 检查log方法签名是否与tool_func一致
        if log_func :
            if self._signature_without_return(tool_func) != self._signature_without_return(log_func):
                raise ValueError(f"工具名{name}的日志方法签名与工具方法形参签名不一致")



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
        new_tool = StructuredTool.from_function(**kwargs)   # 创建tool

        self._registry[name] = new_tool
        self._log_typer[name] = log_func

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

    def get_log_func_by_name(self, name: str):
        log_func = self._log_typer.get(name)
        if log_func is None: raise ValueError(f"工具名 {name} 未注册")
        return log_func

    def get_tools(self):
        return list(self._registry.values())

    def get_tool_set(self, set_name: str) -> list:
        name_set = self._tool_sets.get(set_name)
        if name_set is None:raise ValueError(f"工具集名 {set_name} 未注册")
        tools = map(self.get_tool_by_name, name_set)
        return list(tools)

    def get_tool_set_by_list(self,set_names: list[str]) -> list:
        name_set = set()    # 用集合去重
        for set_name in set_names:
            _ = self._tool_sets.get(set_name)
            if _ is None: raise ValueError(f"工具集名 {set_name} 未注册")
            name_set.update(_)
        tools = map(self.get_tool_by_name, name_set)
        return list(tools)
