from pathlib import Path
from di_container import DIContainer

from settings.setting_store import SettingStore
from settings.provider_setting import ProviderSetting
from settings.wiki_settings import WikiSetting

def setting_store_init(c:DIContainer):
    """并初始化setting_store，同时注册所有setting，必须比所有模块先组装，否则后续模块将无法获取设置信息"""
    store = SettingStore(path=Path("setting.json"))
    # 设置类注册
    store.register(namespace="provider_setting", section_cls=ProviderSetting)
    store.register(namespace="wiki_setting", section_cls=WikiSetting)
    return store
