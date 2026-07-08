import os
os.environ["TQDM_DISABLE"] = "1"  # 关闭 ASR 识别进度条

import time
import threading
import numpy as np
import sounddevice as sd
from funasr import AutoModel

# ==================== 配置区 ====================

SAMPLE_RATE = 16000  # 模型要求的采样率 (16kHz)
INTERVAL_SEC = 5  # 每次录多长 (秒)
DEVICE_INDEX = 1  # 音频输入设备索引 (None=默认, 立体声混音则填55)
NUM_CHANNELS = 2  # 输入声道数 (麦克风=1, 立体声混音=2)

# 模型路径 — 相对于本脚本位置的本地模型目录
SCRIPT_DIR = os.path.dirname(__file__)
MODEL_PATH = os.path.join(SCRIPT_DIR, ".", "asr_models", "paraformer-zh")
PUNC_PATH = os.path.join(SCRIPT_DIR, ".", "asr_models", "ct-punc")


# ================================================

_lock = threading.Lock()
_text = ""
_text_total = ""

def get_new_text():
    global _text,_text_total
    with _lock:
        T = _text
        _text_total += T
        _text = ""
        return T

def load_model_with_vad():
    """
    加载模型时同时配置 VAD。
    加了 VAD 后，generate() 内部流程变成：
      原始音频 → [VAD 切分] → [ASR 逐段识别] → [合并结果]
          而不是原来的：`
      原始音频 → [ASR 整段识别]
    """
    print("正在加载模型 + VAD ...")
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
    print("模型加载完成！\n")
    return model


def demo_dual_thread(model):
    """
    双线程：录音不中断，ASR 并行处理
    录音线程独立循环，永远不丢音频。
    ASR 线程从队列取音频，积攒到足够量再做 VAD 识别。
    """
    import queue
    import threading

    global _text,_text_total

    print("ASR模块已启动")
    print("按 Ctrl+C 退出\n")

    q: queue.Queue = queue.Queue(maxsize=30)
    running = True

    # ---- 录音线程 ----
    def record_thread():
        while running:
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
            q.put(chunk)

    t = threading.Thread(target=record_thread, daemon=True)
    t.start()

    # ---- 主线程：ASR 处理 ----
    audio_buffer = np.array([], dtype=np.float32)
    processed_samples = 0
    ACCUM_SEC = 3  # 攒够 3 秒才跑一次 ASR

    try:
        while True:
            # 从队列取一块音频（等多久都等）
            chunk = q.get()
            audio_buffer = np.concatenate([audio_buffer, chunk])

            # 看看攒了多少未处理的音频
            new_audio = audio_buffer[processed_samples:]
            if len(new_audio) < SAMPLE_RATE * ACCUM_SEC:
                continue

            res = model.generate(
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

                if audio_duration - seg_end > 0.05: #换气检测灵敏度
                    with _lock:
                        _text += text
                    print(f"  [{time.strftime('%H:%M:%S')}] {text}")
                    consumed_total = max(consumed_total, int(seg_end * SAMPLE_RATE))

            if consumed_total > 0:
                processed_samples += consumed_total

    except KeyboardInterrupt:
        running = False
        print("\nASR已退出。")


def asr_record(context: str):
    with open("./ASR_RECORD.txt", 'a', encoding='utf-8') as f:
        f.write(context)




model: AutoModel

def init_asr_model():
    global model
    model= load_model_with_vad()


def run_asr():
    demo_dual_thread(model)

if __name__ == '__main__':
    init_asr_model()
    run_asr()
