from dotenv import load_dotenv
load_dotenv()
# 加载环境（必须置于所有import之前）

from di_container import DIContainer

from pathlib import Path
import threading
from loguru import logger

from event.event_core import Bus,Loop,Router
from event.events import AppStart,AppClose
from settings.setting_store import SettingStore
from settings.routers.provider import ProviderRouter
from settings.di import setting_store_init
from core.tools.di import tools_manager_init
from core.wiki.di import wiki_manager_init
from core.background_agent.di import background_module_init
from core.front_agent.di import front_module_init
from core.reporter.di import reporter_module_init
from Gui import GuiModule


class App:
    def __init__(self, bus:Bus, loop:Loop, setting_store: SettingStore, gui: GuiModule, models_loops: list[Loop] , modules: list):
        self._core_bus = bus
        self._core_loop = loop
        self._core_loop_thread: threading.Thread|None = None
        self._setting_store = setting_store
        self._gui = gui
        self._models_loops = models_loops
        self._models_loops_threads = []
        self._modules = modules

    def _run_models_threading(self):
        for loop in self._models_loops:
            logger.debug(f"{loop}线程正在启动")
            thread = threading.Thread(target=loop.run, daemon=True)
            self._models_loops_threads.append(thread)   #持有线程
            thread.start()

    def stop(self):
        for loop in self._models_loops:
            loop.post(AppClose())   #不走转发以防核心总线延迟导致AppClose事件发生在self.STOP事件之后
            loop.stop()     #发送Loop停止事件（self.STOP）
        for thread in self._models_loops_threads:
            thread.join(timeout=10)   #等待线程结束
        self._core_loop.stop()
        self._core_loop_thread.join()
        logger.info("后台线程已结束")

    def start(self):
        self._run_models_threading()
        logger.info("各模块线程已启动")
        self._core_loop.post(AppStart())
        logger.info("启动事件已发送")
        # self._core_loop.run()
        # 气笑了flet只能run在主线程上，那岂不是只能委屈核心loop跑在守护线程上了？
        self._core_loop_thread = threading.Thread(target=self._core_loop.run, daemon=True)
        self._core_loop_thread.start()

        self._gui.set_exit_func(self.stop)  # 向Gui传入停止方法
        self._gui.gui_start()



def main():
    container = DIContainer()

    # 基础模块
    container.register("CoreBus", lambda c: Bus(),life_cycle="singleton")
    container.register("CoreLoop", lambda c: Loop(c.resolve("CoreBus")),life_cycle="singleton")
    container.register("CoreBusRouter", lambda c: Router(c.resolve("CoreBus")),life_cycle="singleton")

    # 设置层
    container.register("SettingStore",setting_store_init,life_cycle="singleton")
    container.register("LLMRouter", lambda c: ProviderRouter(c.resolve("SettingStore")), life_cycle="singleton")

    # ToolsManager
    container.register("ToolsManager",tools_manager_init,life_cycle="singleton")

    # WikiManager (这东西其实不算核心逻辑 ，只是提供工具，根本就没拼起来，所有我觉得应该算设置层
    container.register("WikiManager",wiki_manager_init,life_cycle="singleton")

    # FrontModule
    container.register("Front_Bus", lambda c: Bus(),life_cycle="singleton")
    container.register("Front_Loop", lambda c: Loop(c.resolve("Front_Bus")),life_cycle="singleton")
    container.register("Front_Module",front_module_init,life_cycle="singleton")

    # BackgroundModule
    container.register("Background_Bus", lambda c: Bus(),life_cycle="singleton")
    container.register("Background_Loop", lambda c: Loop(c.resolve("Background_Bus")),life_cycle="singleton")
    container.register("Background_Module",background_module_init,life_cycle="singleton")

    # Reporter
    container.register("Reporter_Bus", lambda c: Bus(), life_cycle="singleton")
    container.register("Reporter_Loop", lambda c: Loop(c.resolve("Reporter_Bus")), life_cycle="singleton")
    container.register("Reporter_Module", reporter_module_init, life_cycle="singleton")

    # Gui  （走个形式
    container.register("Gui_Bus", lambda c: Bus(), life_cycle="singleton")
    container.register("Gui_Loop", lambda c: Loop(c.resolve("Gui_Bus")), life_cycle="singleton")
    container.register("Gui_Module", lambda c: GuiModule(
        core_bus_router=c.resolve("CoreBusRouter"),
        core_loop=c.resolve("CoreLoop"),
        local_bus=c.resolve("Gui_Bus"),
        local_loop=c.resolve("Gui_Loop"),
        wiki_manager=c.resolve("WikiManager"),
    ), life_cycle="singleton")

    # App根对象
    container.register("app", lambda c: App(
        bus=c.resolve("CoreBus"),
        loop=c.resolve("CoreLoop"),
        setting_store=c.resolve("SettingStore"),
        gui=c.resolve("Gui_Module"),
        models_loops=[
                      c.resolve("Background_Loop"),
                      c.resolve("Front_Loop"),
                      c.resolve("Reporter_Loop"),
                      c.resolve("Gui_Loop"),
                      ],
        modules=[c.resolve("Background_Module"),
                 c.resolve("Front_Module"),
                 c.resolve("Reporter_Module"),
                 c.resolve("Gui_Module"),
                 c.resolve("ToolsManager"),
                 c.resolve("WikiManager"),
                 c.resolve("LLMRouter"),
                 ]
    ))

    logger.info("DI容器注册已完成")

    app = container.resolve("app")

    logger.info("应用启动")
    app.start()


if __name__ == "__main__":
    main()