from di_container import DIContainer
from core.wiki.manager import WikiManager

def wiki_manager_init(c: DIContainer):
    manager = WikiManager(
        setting_store= c.resolve("SettingStore"),tools_manager= c.resolve("ToolsManager"),)
    return manager
