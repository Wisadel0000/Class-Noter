# 1.加载配置
import config   #TODO:升级为 环境值热更新
import eventbus as bus
import asr
import model_background_agent
from Gui import app_start
import threading


def init():

    #2.创建组件
    #3.订阅事件
    bus.BUS.on_async(bus.RunNoter, bus.run_noter)
    bus.BUS.on(bus.ASRInit, asr.init_asr_model)
    bus.BUS.on_async(bus.NoteStart, asr.run_asr)
    bus.BUS.on(bus.NoteStart, model_background_agent.run_agent)
    bus.BUS.on(bus.Run, app_start)

    # bus.BUS.on(bus.ASRInit, asr.init_asr_model)
    # bus.BUS.on_async(bus.NoteStart, asr.run_asr)
    # bus.BUS.on(bus.NoteStart, model_background_agent.run_agent)
    return

if __name__ == '__main__':
    init()
    bus.BUS.emit(bus.Run)

    # bus.BUS.emit(bus.ASRInit)
    # bus.BUS.emit(bus.NoteStart)
    # # 保持主线程存活，否则 daemon 线程会被立即杀死
    # try:
    #     threading.Event().wait()
    # except KeyboardInterrupt:
    #     print("\n程序已退出。")