import os
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class Setting:
    # 基本配置项定义

    # from_dict, 从字典创建Settings，如果是空字典（每个字段在核对时都返回None，即不对default对象进行修改）就用默认值
    @classmethod
    def from_dict(cls, raw: dict) -> "Setting":
        default = cls()     # 新建对象以拉取默认值
        if not isinstance(raw, dict):
            return default

        # 111
        xxx = raw.get("")
        if not isinstance(xxx, str):
            xxx = default.xxx

        # 组装
        return cls(
            xxx=xxx,
        )

    # to_dict
    def to_dict(self) -> dict:
        # asdict()
        a = asdict(self)
        return a