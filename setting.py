import logging
from pathlib import Path
from typing import Callable, Protocol,runtime_checkable
import json

@runtime_checkable
#@dataclass(frozen=True)
class SettingSection(Protocol):
    """
    Setting类约束：
    一定要是冻结数据类 @dataclass(frozen=True)

    至少包含
       @classmethod
     - from_dict(raw: dict) -> "Setting"
        从字典格式创建实例
     - to_dict() -> dict
        把当前类的所有字段转化成明文字典，
        必须保证每一个字典的值都是明文，否则用改函数写入的配置文件无法手动修改
        如手动修改枚举类字段的值为字符串

    """
    @classmethod
    def from_dict(cls, raw: dict) -> "SettingSection":
        ...
    def to_dict(self) -> dict:
        ...

class SettingStore:
    """
    设置Store

    - 负责托管和分发设置实例，保证全局设置实例唯一，在设置发生变动时通知所有订阅者，并自动进行设置的本地化保存和读取。
    - 只要提供（注册）设置类即可使用
    """
    def __init__(self, path: Path):
        """唯一的传入的参数Path应为配置文件的保存路径"""
        # path
        self._path: Path = path
        # 用名找到对应类(方便调用from_dict)
        self._sections: dict[str, type] ={}
        # 用名找到对应实例
        self._current: dict[str, object] ={}
        # 监听器列表 (名, 回调函数)
        self._listeners: list[tuple[str, Callable]] = []
        # raw (json 读进来的原始字典)
        self._raw: dict[str,dict] = self._read_raw()

    @staticmethod
    def _verify_dict(v):
        """工具函数，如果传入的v不是dict就返回一个空字典"""
        return v if isinstance(v, dict) else {}

    # ----- 服务逻辑 ----- #

    def register(self, namespace: str, section_cls: type[SettingSection]) -> None:
        """将自定义Setting类注册到商店中"""
        #查重
        if namespace in self._sections:
            raise ValueError(f"命名空间 {namespace!r} 已被注册过")

        #注册设置类
        self._sections[namespace] = section_cls

        #从raw创建实例
        raw = self._verify_dict(self._raw.get(namespace))
        self._current[namespace] = section_cls.from_dict(raw)

    def subscribe(self, namespace: str, call_back: Callable[[SettingSection],None]) -> Callable:
        """
        订阅某个设置 （namespace）的最新更新，
        每次设置值发生变化将会触发回调函数（call_back）。

        Ps：回调函数需要直接负责重新修改应用值，不要只负责通知
        """
        listener = (namespace, call_back)
        # 加入监听器列表
        self._listeners.append(listener)
        # 取消订阅的函数
        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
        return unsubscribe

    def _notify(self, namespace: str, section: object) -> None:
        """通知所有订阅了namespace的回调函数"""
        for ns, call_back in list(self._listeners):
            if namespace == ns:
                try: call_back(section)
                except Exception:
                    logging.exception(f"回调函数调用时错误。namespace:{namespace}\n")


    # ----- 查询和修改 -----

    def get(self, namespace: str):
        """获取namespace对应的设置实例"""
        if namespace not in self._sections:
            raise KeyError(f"{namespace}不是被注册过的命名空间！")
        return self._current[namespace]

    def update(self, namespace: str, patch: dict) -> None:
        """
        给namespace对应的的设置进行修改
        修改的新内容以字典的形式传入，必须是明文字典，适配 from_dict(raw)方法

        修改完成后当前线程将会逐一通知所有的订阅者
        """
        if namespace not in self._sections:
            raise KeyError(f"{namespace}不是被注册过的命名空间！")
        # 组织新的设置字典 (一切修改都在内存中完成，最后保存时再进具体文件)
        #顺带验证raw是否满足{namespace:dict,}的格式
        old_raw = self._verify_dict(self._raw.get(namespace))

        new_raw = {**old_raw, **patch}
        new_setting = self._sections[namespace].from_dict(new_raw)
        # 更新新对象
        self._current[namespace] = new_setting
        # 保存进raw (保持一致性)
        self._raw[namespace] = new_setting.to_dict()
        # 写回存储
        self._write()
        # 使用回调通知修改
        self._notify(namespace,new_setting)

    # ----- 持久化逻辑 ----- #

    def _read_raw(self) -> dict:
        """读取本地的配置文件(json读取)，返回一个字典"""
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        #错误处理
        except FileNotFoundError:
            # 应在此处为用户做出提示，如日志报错
            logging.warning("配置文件不存在，正在使用默认设置")
            return {}
        except (json.JSONDecodeError, OSError):
            logging.warning("配置文件损坏，请及时备份源文件，以免丢失。当前正在使用默认设置")
            return {}

        if not isinstance(raw, dict):
            return {}
        # 为什么不再在这里返回setting实例了呢？
        # 因为要创建实例一定需要来自对应类的from_dict，
        # 而读取这一步时，对应的类还没有完成注册，
        # 即我们无法法得到所需的from_dict()。
        return raw


    def _write(self) -> None:
        """把内存中的配置信息写入到本地文件"""
        # 检查存在性并新建文件（.tmp）
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")  # settings.tmp
        tmp.write_text(
            json.dumps(self._raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)


