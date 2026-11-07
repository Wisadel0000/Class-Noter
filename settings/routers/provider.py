from langchain.chat_models import init_chat_model
from langchain_ollama import ChatOllama

from settings.setting_store import SettingStore
from settings.provider_setting import ProviderSetting, ModelProvider

# ------ 路由器声明 ------

class ProviderRouter:
    """这是LLM路由器，根据设置来返回不同的 model实例

    - 创建实例时传入的 Setting对象为初始参数
    - 调用者通过本函数的.route来获取当前 model实例
    - 后续可以调用 .reload(setting)以重新更改本路由器的值（如回调函数中）
    """
    def __init__(self, setting_store: SettingStore):
        #订阅配置变化事件
        setting_store.subscribe("provider_setting", self.reload)
        setting = setting_store.get("provider_setting")
        self._model = self._load_llm(setting)
        self._default_model = self._load_default(setting)

    def _load_llm(self,setting):
        """使用 setting初始化 _model的取值"""
        if setting.model_provider == ModelProvider.web_api:
            return init_chat_model(model_provider="openai",
                                   model=setting.web_model,
                                   api_key=setting.web_api_key,
                                   base_url=setting.web_base_url,
                                   temperature=0,
                                   timeout=60, max_retries=2)
        elif setting.model_provider == ModelProvider.ollama:
            return ChatOllama(model=setting.ollama_model, temperature=0, reasoning=False,client_kwargs={"timeout": 60})
        else:
            raise ValueError("配置值异常：未知的提供商")
            #理论上不可能触发这个，除非运行时有外部什么地方强行访问修改了._model，因为配置在启动时如果出现非法值会自动回落

    def _load_default(self, setting: ProviderSetting):
        if setting.default_model_provider == ModelProvider.web_api:
            return init_chat_model(model_provider="openai",
                                   model=setting.default_model,
                                   api_key=setting.default_api_key,
                                   base_url=setting.default_base_url,
                                   temperature=0,
                                   timeout=60, max_retries=2)
        elif setting.default_model_provider == ModelProvider.ollama:
            return ChatOllama(model=setting.default_ollama_model, temperature=0, reasoning=False,client_kwargs={"timeout": 60})
        else:
            raise ValueError("配置值异常：未知的提供商")

    def reload(self, new_setting:ProviderSetting): #作为回调
        """根据传入 Setting重新加载 route"""
        self._model = self._load_llm(new_setting)
        self._default_model = self._load_default(new_setting)

    def get_default_model(self):
        return self._default_model

    def model_route(self):
        """获取 model实例"""
        return self._model
