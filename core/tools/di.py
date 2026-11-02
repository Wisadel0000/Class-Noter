from di_container import DIContainer

from core.tools.ToolsManager import ToolsManager
import core.tools.file_tools as ft


def tools_manager_init(c: DIContainer):
    """组装工具管理器，顺手初始化注册一些无模块工具"""
    tools_manager = ToolsManager()
    # file_tools
    for name,call_able,description in ft.tool_set:
        tools_manager.register(name,call_able,description)
    tools_manager.tool_set_register("noting_tools", [tool[0] for tool in ft.tool_set])
    # default
    tools_manager.tool_set_register("default",[])
    return tools_manager