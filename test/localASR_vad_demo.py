"""
VAD (Voice Activity Detection) 断句识别演示
==========================================
对比 localASR3.py — 那个版本是"录一段→认一整段"，
这个版本加入了 VAD 进行语音活动检测，实现"录一段→切出多个句子→逐句识别"。

VAD 的作用：
  1. 检测音频中哪些部分是有效人声，哪些是静音/噪音
  2. 将长音频按句子的边界切开（断句）
  3. 每个句子独立送入 ASR，结果更干净、更自然

依赖：funasr, sounddevice, numpy
"""

import os
import time
import numpy as np
import sounddevice as sd
from funasr import AutoModel

# ==================== 配置区 ====================

SAMPLE_RATE = 16000          # 模型要求的采样率 (16kHz)
INTERVAL_SEC = 5             # 每次录多长 (秒)
DEVICE_INDEX = 18          # 音频输入设备索引 (None=默认, 立体声混音则填55)
NUM_CHANNELS = 2             # 输入声道数 (麦克风=1, 立体声混音=2)

# 模型路径 — 相对于本脚本位置的本地模型目录
SCRIPT_DIR = os.path.dirname(__file__)
MODEL_PATH = os.path.join(SCRIPT_DIR, "..", "asr_models", "paraformer-zh")
PUNC_PATH = os.path.join(SCRIPT_DIR, "..", "asr_models", "ct-punc")

# ================================================


def load_model_with_vad():
    """
    加载模型时同时配置 VAD。

    对比 localASR3.py — 那里只传了 model 参数，没有 VAD。
    这里多了两行：
      vad_model="fsmn-vad"       — 指定 VAD 模型 (fsmn-vad 是 FunASR 内置的轻量 VAD)
      vad_kwargs={...}            — VAD 的参数配置

    加了 VAD 后，generate() 内部流程变成：
      原始音频 → [VAD 切分] → [ASR 逐段识别] → [合并结果]
          而不是原来的：
      原始音频 → [ASR 整段识别]
    """
    print("正在加载模型 + VAD ...")
    model = AutoModel(
        model=MODEL_PATH,
        disable_update=True,       # 不检查更新
        device="cpu",
        batch_size_s=300,          # 内部 batching 时长（单位：秒的毫秒数？不重要）
        vad_model="fsmn-vad",      # ★ 关键：启用 VAD！不传这个就没有断句
        vad_kwargs={
            "max_single_segment_time": 30000,  # 每个 VAD 段的最大长度 (ms)
                                               # 默认较短，设 30000(30秒) 避免长句被误切
        },
        punc_model=PUNC_PATH,
    )
    print("模型加载完成！\n")
    return model


def demo_fixed_interval_with_vad(model):
    """
    【方案一】固定间隔录音 + VAD 断句
    和 localASR3.py 同样的录音方式，但加入了 VAD。

    VAD 的作用在这尤其明显：
      5秒音频里可能只有 2秒在说话、3秒是安静。
      没有 VAD  → ASR 硬着头皮认整段，容易吐出幻觉文字
      有 VAD    → 只把有语音的片段送进 ASR，准确率高得多
    """
    print(f"【方案一】固定录音 ({INTERVAL_SEC}s) + VAD 断句")
    print("按 Ctrl+C 退出\n")

    try:
        while True:
            # ---- 录一段 ----
            audio = sd.rec(
                int(INTERVAL_SEC * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=NUM_CHANNELS,
                dtype="float32",
                device=DEVICE_INDEX,
            )
            sd.wait()
            if NUM_CHANNELS > 1:
                audio = audio.mean(axis=1)  # 多声道 → 单声道
            audio = audio.flatten()

            # ---- 识别（带 VAD） ----
            # ★ merge_vad=True 的作用：
            #   VAD 可能会把一个句子切得太碎（比如两个词之间的短暂停顿也被切开），
            #   merge_vad=True 会把时间上靠近的片段合并成一个完整的句子再识别。
            #   如果不传 merge_vad（或传 False），每个 VAD 片段独立识别输出，
            #   结果可能非常零碎。
            res = model.generate(
                input=audio,
                language="auto",
                use_itn=True,
                merge_vad=True,       # ★ 关键：合并 VAD 片段为完整句子
            )

            # ---- 处理结果 ----
            # ★ 有 VAD 时，res 里每个元素对应一个 VAD 切割后的语音段
            # 如果没有语音，res 可能为空列表 [{}]
            if res and res[0].get("text"):
                # res 可能是多个片段的列表，但 merge_vad=True 时通常只有一个
                for i, seg in enumerate(res):
                    if seg.get("text"):
                        # 时间戳信息（如果有的话）
                        ts = seg.get("timestamp", [])
                        ts_str = f" [{ts[0][0]:.1f}s-{ts[-1][1]:.1f}s]" if ts else ""
                        print(f"  句子{i+1}({ts_str}): {seg['text']}")
            else:
                print("  [无语音]")

    except KeyboardInterrupt:
        print("\n已退出。")


def demo_continuous_stream(model):
    """
    【方案二】流式录音 + VAD 实时断句
    更接近真实场景的做法：
      不固定录音长度，而是持续监听麦克风。
      每当 VAD 检测到一个完整的句子（用户停顿），就立即识别输出。
    效果：
      说话 → 停顿 → 立刻出结果 → 继续说 → 停顿 → 立刻出结果 ...

    注意：这个方案需要 AudioCallback 配合 VAD，
    但 FunASR 的 generate() 不是真正的流式接口。
    我们这里用"短间隔轮询"来模拟实时感。
    """
    print("\n【方案二】流式录音模拟 + VAD 实时断句")
    print("原理：每 1 秒检查一次，看 VAD 是否积累到完整句子")
    print("按 Ctrl+C 退出\n")

     # 累积音频的环形缓冲区（最多保持 30 秒）
    MAX_BUFFER_SEC = 30
    buffer_samples = MAX_BUFFER_SEC * SAMPLE_RATE
    audio_buffer = np.array([], dtype=np.float32)

    CHUNK_SEC = 1  # 每次追加 1 秒

    try:
        while True:
            # 追加 1 秒音频
            chunk = sd.rec(
            int(CHUNK_SEC * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=NUM_CHANNELS,
                dtype="float32",
                device=DEVICE_INDEX,
            )
            sd.wait()
            if NUM_CHANNELS > 1:
                chunk = chunk.mean(axis=1)
            chunk = chunk.flatten()

            audio_buffer = np.concatenate([audio_buffer, chunk])

            # 只保留最近 MAX_BUFFER_SEC 秒
            if len(audio_buffer) > buffer_samples:
                audio_buffer = audio_buffer[-buffer_samples:]

            # 用 VAD 识别当前累积的音频
            # ★ VAD 会自动找出音频中的语音片段，skip 掉静音部分
            res = model.generate(
                input=audio_buffer,
                language="auto",
                use_itn=True,
                merge_vad=True,
            )

            if res and res[0].get("text"):
                text = res[0]["text"]
                # 简单防重复：和上次输出不同才打印
                if not hasattr(demo_continuous_stream, "_last_text") or \
                   demo_continuous_stream._last_text != text:
                    demo_continuous_stream._last_text = text
                    print(f"  [{time.strftime('%H:%M:%S')}] {text}")
            else:
                # 静音时重置状态（避免把旧结果的尾巴拖到下次）
                if hasattr(demo_continuous_stream, "_last_text"):
                    del demo_continuous_stream._last_text

    except KeyboardInterrupt:
        print("\n已退出。")


def demo_sentence_complete(model):
    """
    【方案三】VAD 分段识别 → 完整句子才输出
    持续监听，每段音频按 VAD 切成分散的语音段。
    每个语音段如果尾端有静音（说明句子说完了），就输出并丢弃。
    """
    print("\n【方案三】VAD 分段 → 完整句子才输出")
    print("原理：积累音频 → 按 VAD 切段 → 尾端有静音才输出")
    print("按 Ctrl+C 退出\n")

    audio_buffer = np.array([], dtype=np.float32)
    processed_samples = 0

    try:
        while True:
            # 录 1 秒
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
            audio_buffer = np.concatenate([audio_buffer, chunk])

            # 只看未处理的新增部分
            new_audio = audio_buffer[processed_samples:]
            if len(new_audio) < SAMPLE_RATE * 0.5:
                continue

            # merge_vad=False → 每个 VAD 段独立返回
            res = model.generate(
                input=new_audio,
                language="auto",
                use_itn=True,
                merge_vad=False,
            )

            if not res:
                continue

            consumed_total = 0  # 本轮总共要丢弃的样本数

            for seg in res:
                if not seg.get("text", "").strip():
                    continue

                text = seg["text"]
                ts = seg.get("timestamp", [])
                if not ts:
                    continue

                # 该语音段最后一个字的结束时间（毫秒 → 秒）
                seg_end = max(end for _, end in ts) / 1000
                audio_duration = len(new_audio) / SAMPLE_RATE

                # 尾端有足够静音 → 句子完整了
                if audio_duration - seg_end > 0.7:
                    print(f"  [{time.strftime('%H:%M:%S')}] {text}")
                    # 这个段及之前的所有段都可丢弃
                    consumed_total = max(consumed_total, int(seg_end * SAMPLE_RATE))

            if consumed_total > 0:
                processed_samples += consumed_total

    except KeyboardInterrupt:
        print("\n已退出。")


def demo_dual_thread(model):
    """
    【方案四】双线程：录音不中断，ASR 并行处理
    录音线程独立循环，永远不丢音频。
    ASR 线程从队列取音频，积攒到足够量再做 VAD 识别。
    """
    import queue
    import threading

    print("\n【方案四】双线程录音 + 并行 ASR")
    print("原理：录音线程不停 → 队列 → ASR 线程攒够再识别")
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

                if audio_duration - seg_end > 0.7:
                    print(f"  [{time.strftime('%H:%M:%S')}] {text}")
                    consumed_total = max(consumed_total, int(seg_end * SAMPLE_RATE))

            if consumed_total > 0:
                processed_samples += consumed_total

    except KeyboardInterrupt:
        running = False
        print("\n已退出。")


def explain_vad_params():
    """
    VAD 核心参数说明
    ==================

    1. vad_model="fsmn-vad"
       FunASR 内置的 VAD 模型，全称 Feedforward Sequential Memory Network。
       很小很快，适合实时场景。

    2. max_single_segment_time (ms)
       VAD 允许每个语音片段的最大时长。
       默认值可能偏小（比如 10 秒），如果说话人一口气说 15 秒，
       会被强制切开 -> 句子不完整。
       调大到 30000 (30秒) 可以避免长句被误切。

    3. merge_vad=True (generate 时的参数)
       把 VAD 切出来的相邻片段合并后再送 ASR。
       不加的话，VAD 的一个停顿可能把"今天天气真好啊"切成
       ["今天", "天气真好啊"] 两段分别识别，结果可能不连贯。

    4. batch_size_s
       控制 ASR 的批处理时长。值越大，VAD 片段会攒更多再一起认
       （提高吞吐），但延迟会增加。实时场景用 300 足够。

    总结：
      有 VAD 的 ASR 就像先把一整页纸按句子剪开再逐句阅读，
      没有 VAD 就像不管三七二十一整页一起读，
      遇到空白和停顿的地方也硬读，容易读错。
    """
    pass


if __name__ == "__main__":
    model = load_model_with_vad()

    # 选择要运行的方案
    # 方案一：固定间隔（简单易懂，适合初学）
    # demo_fixed_interval_with_vad(model)

    # 方案二：流式（实时感更强，但更复杂）
    # demo_continuous_stream(model)

    # 方案三：VAD 完整句子识别 + 自动丢弃
    # demo_sentence_complete(model)

    # 方案四：双线程录音 + 并行 ASR
    demo_dual_thread(model)

    # 如果想看 VAD 参数的解释，运行这段：
    # explain_vad_params()