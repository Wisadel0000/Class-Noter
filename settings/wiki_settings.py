import os
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class WikiSetting:
    # 基本配置项定义
    raw_path: str = "note/raw"
    out_path: str = "note/wiki"

    # from_dict, 从字典创建Settings，如果是空字典（每个字段在核对时都返回None，即不对default对象进行修改）就用默认值
    @classmethod
    def from_dict(cls, raw: dict) -> "WikiSetting":
        default = cls()     # 新建对象以拉取默认值
        if not isinstance(raw, dict):
            return default

        # root_path
        raw_path = raw.get("raw_path")
        if not isinstance(raw_path, str):
            raw_path = default.raw_path

        # out_path
        out_path = raw.get("out_path")
        if not isinstance(out_path, str):
            out_path = default.out_path

        # 组装
        return cls(
            raw_path=raw_path,
            out_path=out_path,
        )

    # to_dict
    def to_dict(self) -> dict:
        # asdict()
        a = asdict(self)
        return a