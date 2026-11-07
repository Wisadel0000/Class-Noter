from di_container import DIContainer

from core.tools.ToolsManager import ToolsManager
from core.tools.web_search_tools import WebSearchTools


def tools_manager_init(c: DIContainer):
    """组装工具管理器，顺手初始化注册一些无模块工具"""
    tools_manager = ToolsManager()
    # 工具注册
    WebSearchTools(tools_manager=tools_manager,setting_store=c.resolve("SettingStore"))
    return tools_manager