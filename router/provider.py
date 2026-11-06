from collections.abc import Callable
from setting import SettingStore
from langchain.chat_models import init_chat_model
from langchain_ollama import ChatOllama

from router.provider_setting import ProviderSetting, ModelProvider


# 命名空间
_namespace = "model_router"
# 取消订阅函数
_unsubscribe: Callable | None = None    # 未来会有人用到吧...大概？


# ------ 路由器声明 ------

class LLMRouter:
    """这是LLM路由器，根据设置来返回不同的 model实例

    - 创建实例时传入的 Setting对象为初始参数
    - 调用者通过本函数的.route来获取当前 model实例
    - 后续可以调用 .reload(setting)以重新更改本路由器的值（如回调函数中）
    """
    def __init__(self, setting_store: SettingStore):
        global _namespace, _unsubscribe
        #向store注册ModelSetting类
        setting_store.register(_namespace, ProviderSetting)
        setting = setting_store.get(_namespace)
        #订阅配置变化事件
        _unsubscribe = setting_store.subscribe(_namespace, self.reload)

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

    def get_default(self):
        return self._default_model

    def route(self):
        """获取 model实例"""
        return self._model

"""现在也不用担心这个LLMRouter在哪儿保存被谁拿到了，拼装的时候Container会解决www"""

# def get_llm_router():
#     global _llm_router
#     """获取本模块的 router实例"""
#     if _llm_router is None:
#         raise Exception("初始化未进行或失败，无法获取配置：_llm_router is None")
#     return _llm_router
