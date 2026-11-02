import os
from enum import Enum
from dataclasses import dataclass, asdict

# 枚举类型
class ModelProvider(Enum):
    web_api = "web_api"
    ollama = "ollama"
# 枚举类的集合
_model_provider_set = {m.value for m in ModelProvider} # 此乃集合推导式，创建的是set，不是dict

#设置类
@dataclass(frozen=True)
class ProviderSetting:
    # 基本配置项定义
    model_provider: ModelProvider = ModelProvider.web_api
    web_model:str = "deepseek-flash"
    web_api_key:str = os.getenv("WEB_API_KEY")
    web_base_url:str = "https://api.deepseek.com"

    ollama_model:str = "qwen3.5:9b"
    # 未来最好更新一个配置&保存多个提供商实例的功能，大概需要单独搞一个本地化功能罢，大概会写在LLMRouter里

    #如果默认（备用）提供商选择了ollama，就不使用apiKey，但是如果选择了web提供商的话还是需要保存一个apiKey的
    default_model_provider: ModelProvider = ModelProvider.web_api
    default_model:str = "deepseek-flash"
    default_base_url:str = "https://api.deepseek.com"
    default_api_key:str = os.getenv("DEFAULT_API_KEY")

    default_ollama_model:str = "qwen3.5:9b"

    # from_dict, 从字典创建Settings，如果是空字典（每个字段在核对时都返回None，即不对default对象进行修改）就用默认值
    @classmethod
    def from_dict(cls, raw: dict) -> "ProviderSetting":
        default = cls()     # 新建对象以拉取默认值
        if not isinstance(raw, dict):
            return default

        def in_ModelProvider(string:str):
            return True if string in _model_provider_set else False

        # model_provider
        model_provider_raw = raw.get("model_provider")
        # 如果获取到的不是字符串/字符串不是ModelProvider的合法枚举值
        if (not isinstance(model_provider_raw, str)
                or not in_ModelProvider(model_provider_raw)):
            model_provider = default.model_provider
        else:
            model_provider = ModelProvider(model_provider_raw)

        # web_model
        web_model = raw.get("web_model")    # 如果get到的不合法或者是None就改为default
        if not isinstance(web_model, str):
            web_model = default.web_model

        # web_api_key
        web_api_key = raw.get("web_api_key")    #后续原理同上
        if not isinstance(web_api_key, str):
            web_api_key = default.web_api_key

        # web_base_url
        web_base_url = raw.get("web_base_url")
        if not isinstance(web_base_url, str):
            web_base_url = default.web_base_url

        # ollama_model
        ollama_model = raw.get("ollama_model")
        if not isinstance(ollama_model, str):
            ollama_model = default.ollama_model

        # default_model_provider
        default_model_provider_raw = raw.get("default_model_provider")
        if (not isinstance(default_model_provider_raw, str)
                or not in_ModelProvider(default_model_provider_raw)):
            default_model_provider = default.default_model_provider
        else:
            default_model_provider = ModelProvider(default_model_provider_raw)

        # default_model
        default_model = raw.get("default_model")
        if not isinstance(default_model, str):
            default_model = default.default_model

        # default_api_key
        default_api_key = raw.get("default_api_key")
        if not isinstance(default_api_key, str):
            default_api_key = default.default_api_key

        # default_base_url
        default_base_url = raw.get("default_base_url")
        if not isinstance(default_base_url, str):
            default_base_url = default.default_base_url

        # default_ollama_model
        default_ollama_model = raw.get("default_ollama_model")
        if not isinstance(default_ollama_model, str):
            default_ollama_model = default.default_ollama_model

        # 组装
        return cls(
            model_provider=model_provider,
            web_model=web_model,
            web_api_key=web_api_key,
            web_base_url=web_base_url,
            ollama_model=ollama_model,
            default_model_provider=default_model_provider,
            default_model=default_model,
            default_api_key=default_api_key,
            default_base_url=default_base_url,
            default_ollama_model=default_ollama_model,
        )

    # to_dict
    def to_dict(self) -> dict:
        # asdict()
        a = asdict(self)
        # 对Enum类进行修正（把枚举变成字符串）
        a["model_provider"] = self.model_provider.value
        a["default_model_provider"] = self.default_model_provider.value
        return a
