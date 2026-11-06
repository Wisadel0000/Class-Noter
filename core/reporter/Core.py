import os

from loguru import logger

os.environ["TQDM_DISABLE"] = "1"  # 关闭 ASR 识别进度条
import time
import queue
import threading
import numpy as np
import sounddevice as sd
from funasr import AutoModel

import event.event_core as event
import event.events as events

# ==================== 配置区 ====================

SAMPLE_RATE = 16000  # 模型要求的采样率 (16kHz)
INTERVAL_SEC = 5  # 每次录多长 (秒)
DEVICE_INDEX = 12  # 音频输入设备索引 (None=默认, 立体声混音则填78)
NUM_CHANNELS = 2  # 输入声道数 (麦克风=1, 立体声混音=2)

# 模型路径 — 相对于本脚本位置的本地模型目录
SCRIPT_DIR = os.path.dirname(__file__)
MODEL_PATH = os.path.join(SCRIPT_DIR,  "asr_models", "paraformer-zh")
PUNC_PATH = os.path.join(SCRIPT_DIR, "asr_models", "ct-punc")

# ===============================================


class AsrModule:
    def __init__(self,core_bus_router:event.Router,core_loop:event.Loop,local_bus:event.Bus,local_loop:event.Loop):
        self._local_bus = local_bus
        self._local_loop = local_loop
        self._core_loop = core_loop

        self._is_running = False
        self._asr_idle = threading.Event()
        self._asr_idle.set() #默认升起
        self._lock = threading.Lock()
        self._text = ""
        self._text_total = ""  # 留档（以防万一用到了全部的）
        self.model: AutoModel | None = None

        # ------ 注册结束时等待事件 ------
        # self._local_loop.register_stop_waiting_event(self._asr_idle)    #不等待

        # ------ 注册回调函数 ------
        # 笔记事件的启动和停止
        self._local_bus.subscribe(events.AppStart, self.when_app_start)
        self._local_bus.subscribe(events.NotingStart, self.asr_start)
        self._local_bus.subscribe(events.NotingStop, self.asr_stop)
        self._local_bus.subscribe(events.AppClose, self.asr_stop)
        self._local_bus.subscribe(events.RequestReporterData, self.response_data_request)
        # ------ 订阅总线事件 ------
        # 笔记事件的启动和停止
        core_bus_router.subscribe(events.AppStart, self._local_loop)
        core_bus_router.subscribe(events.AppClose, self._local_loop)
        core_bus_router.subscribe(events.NotingStart, self._local_loop)
        core_bus_router.subscribe(events.NotingStop, self._local_loop)
        core_bus_router.subscribe(events.RequestReporterData, self._local_loop)

    def response_data_request(self, event: events.RequestReporterData):
        request_id = event.request_id
        data = self._get_new_text()
        # 回信
        self._core_loop.post(events.ReporterResult(request_id, data))

    def _get_new_text(self):
        with self._lock:
            T = self._text
            self._text_total += T
            self._text = ""
            return T

    def _load_model(self):
        """
        加载模型时同时配置 VAD。

        VAD会使generate()内部流程从：
        原始音频 → [ASR 整段识别]
        变成：
        原始音频 → [VAD 切分] → [ASR 逐段识别] → [合并结果]
        """
        logger.info("正在加载ASR模型和VAD模型，初次加载可能需要联网下载模型，请勿退出...")
        model = AutoModel(
            model=MODEL_PATH,
            disable_update=True,  # 不检查更新
            device="cpu",
            batch_size_s=300,  # 内部 batching 时长（单位：秒的毫秒数？不重要）
            vad_model="fsmn-vad",  # ★ 关键：启用 VAD！不传这个就没有断句
            vad_kwargs={
                "max_single_segment_time": 30000,  # 每个 VAD 段的最大长度 (ms)
                # 默认较短，设 30000(30秒) 避免长句被误切
            },
            punc_model=PUNC_PATH,
        )
        logger.info("模型加载完成！\n")
        return model

    def _load_model_and_report_already(self):
        """先加载模型，模型加载好了会向总线发送就绪事件，本函数用于将模型加载至于独立线程上"""
        self.model = self._load_model()
        self._core_loop.post(events.NotingAlready())

    def _asr_dual_thread(self):
        """
        ASR 线程从队列取音频，积攒到足够量再做 VAD 识别。
        双线程：录音不中断，ASR 并行处理
        线程1：持续的录音线程，将录制结果放入一个队列
        线程2：循环等待从队列中取音频段落，攒够量后做 VAD 识别
        （理论上保证不会丢失任何一秒音频，除非cpu太拉单轮识别用时超过30秒，超出30秒的音频就不得不丢掉了））
        """

        # 录音的结果会保存再这个队列中（采样点序列）

        if self.model is None:
            self._core_loop.post(events.NotingStop())
            logger.error("模型未能加载成功，无法启动转述模块，已停止任务")
            # 清理flag
            self._is_running = False
            self._asr_idle.set()
            return

        record_queue: queue.Queue = queue.Queue(maxsize=30)
        # ---- 录音线程 ----
        _is_recording = True    #运行标志，停止时使用该标准停止录音线程
        # 持续录音
        def record_thread_func():
            while _is_recording:
                chunk = sd.rec(
                    int(SAMPLE_RATE),
                    samplerate=SAMPLE_RATE,
                    channels=NUM_CHANNELS,
                    dtype="float32",
                    device=DEVICE_INDEX,
                )
                sd.wait()
                if NUM_CHANNELS > 1:
                    chunk = chunk.mean(axis=1)
                chunk = chunk.flatten()
                try:
                    record_queue.put(chunk,timeout=1)   #超时1秒就抛弃重算
                except queue.Full:
                    continue
        #启动线程
        record_thread = threading.Thread(target=record_thread_func, daemon=True)
        record_thread.start()

        # ---- 主线程：ASR轮询识别 ----
        # 采样点缓存区（保存未完成识别的部分）
        audio_buffer = np.array([], dtype=np.float32)
        processed_samples = 0
        ACCUM_SEC = 3  # 每轮ASR识别的间隔时间（秒）

        try:
            while self._is_running:
                # 从队列取一块音频
                try:
                    chunk = record_queue.get(timeout=1)     #等待结果继续
                except queue.Empty:
                    continue
                audio_buffer = np.concatenate([audio_buffer, chunk])

                # 看看攒了多少未处理的音频
                new_audio = audio_buffer[processed_samples:]
                if len(new_audio) < SAMPLE_RATE * ACCUM_SEC:
                    continue

                res = self.model.generate(
                    input=new_audio,
                    language="auto",
                    use_itn=True,
                    merge_vad=False,
                )

                if not res:
                    continue

                consumed_total = 0
                for seg in res:
                    if not seg.get("text", "").strip():
                        continue
                    text = seg["text"]
                    ts = seg.get("timestamp", [])
                    if not ts:
                        continue

                    seg_end = max(end for _, end in ts) / 1000
                    audio_duration = len(new_audio) / SAMPLE_RATE

                    if audio_duration - seg_end > 0.05:  # 换气检测灵敏度(已经是 sweet point 了
                        with self._lock:
                            self._text += text
                        print(f"  [{time.strftime('%H:%M:%S')}] {text}")
                        consumed_total = max(consumed_total, int(seg_end * SAMPLE_RATE))

                if consumed_total > 0:
                    processed_samples += consumed_total
        finally :
            _is_recording = False
            self._asr_idle.set()
            print(f"\nASR已结束工作。AsrModule.")

    def _asr_record(self, context: str):
        with open("./ASR_RECORD.txt", 'a', encoding='utf-8') as f:
            f.write(context)

    def when_app_start(self,_event:event.Event):
        # 在其他线程加载模型，以防卡住界面启动
        threading.Thread(target=self._load_model_and_report_already, daemon=True).start()

    def asr_start(self, _event: event.Event):
        if self._asr_idle.wait(timeout=10): #仅当上一个录音线程真正结束时创建新线程，等待超过10秒视为上一个录音线程没有收到终止或被阻止
            self._is_running = True
            self._asr_idle.clear()  # 取消闲置状态标志
            threading.Thread(target=self._asr_dual_thread, daemon=True).start()
            logger.info("ASR已启动")
        else:
            logger.warning(f"时间上重叠的Asr线程请求，已去重（我不知道怎么可能会出现这种情况，但如果这行日志真的出现在了终端里，你最好看看代码）")
            return  # 如果录音线程还在工作，且没有要结束的迹象，则返回,不应重复启动线程

    def asr_stop(self, _event: event.Event):
        self._is_running = False
        # 两个录音线程会自行停止