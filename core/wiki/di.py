from di_container import DIContainer
from core.wiki.manager import WikiManager

def wiki_manager_init(c: DIContainer):
    manager = WikiManager(
        core_bus_router=c.resolve("CoreBusRouter"),
        core_loop=c.resolve("CoreLoop"),
        local_bus=c.resolve("Wiki_Bus"),
        local_loop=c.resolve("Wiki_Loop"),
        setting_store= c.resolve("SettingStore"),
        tools_manager= c.resolve("ToolsManager"),)
    return manager
