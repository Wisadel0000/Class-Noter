from typing import Callable,Any

class DIContainer:
    """依赖注入容器，用于自动解析依赖顺序以完成自动初始化，创建好的对象会保存在本容器的注册表中
    - 使用依赖注入容器时，请保证需的依赖都通过本容器获取，以便解析
    - 生命周期规则：transient(每次使用时都创建新的对象)、singleton(创建一个对象并保存在容器中，每次使用时都返回这个对象)
    """
    def __init__(self):
        self._registry: dict[str, tuple[Callable[["DIContainer"],Any], str]] = {}  # 键 -> (工厂:callable,生命周期:str)
        self._singletons = {} # 键 -> 对象

    def register(self, key:str, factory:Callable[["DIContainer"],Any], life_cycle:str= "transient"):
        """注册一个键对应的工厂方法进容器
        :param key: 键
        :param factory: 工厂方法（参数只接收一个Container对象）
        :param life_cycle: 生命周期（"transient"/"singleton"）
        """
        #合法性检查
        if key in self._registry.keys():
            raise KeyError(f"容器键 {key!r} 已经被注册")
        if life_cycle not in ("transient", "singleton"):
            raise ValueError(f"无效的生命周期: {life_cycle!r}")
        self._registry[key] = (factory,life_cycle)

    def register_instance(self,key:str, instance):
        """使用已有的实例注册DI容器，此注册方式生命周期一定为singleton(单例)
        :param key: 键
        :param instance 全局单例对象
        """
        # 合法性检查
        if key in self._registry.keys():
            raise KeyError(f"容器键 {key!r} 已经被注册")
        self._registry[key] = (lambda c: instance, "singleton")
        self._singletons[key] = instance

    def resolve(self,key:str):
        # 已经创建过的单例直接返回
        if key in self._singletons:
            return self._singletons[key]
        # 没保存过的话检察有没有注册工厂
        if key not in self._registry.keys():
            raise KeyError(f"键 {key!r} 未在容器中注册")
        # 调用工厂
        factory, life_cycle = self._registry[key]
        instance = factory(self)

        # 把单例的实例保存起来
        if life_cycle == "singleton":
            self._singletons[key] = instance
        elif life_cycle == "transient":
            pass

        return instance