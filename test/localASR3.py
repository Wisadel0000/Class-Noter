# demo.py
import sounddevice as sd
import numpy as np
from funasr import AutoModel

# --- 1. 加载模型 (首次运行会自动下载，大约几分钟) ---
print("正在加载模型，首次运行会从网上下载，请稍等...")
# 关键：这里不使用任何可能出错的参数，并且直接使用 'paraformer-zh' 这个稳定模型
# model = AutoModel(model="paraformer-zh", disable_update=True, device="cpu", batch_size_s=300)
model = AutoModel(model="../asr_models/paraformer-zh", disable_update=True, device="cpu", batch_size_s=300)
print("模型加载完成！")

# --- 2. 设置录音参数 ---
SAMPLE_RATE = 16000          # 16kHz
INTERVAL_SEC = 5            # 每2秒识别一次，实时性不错且句子相对完整

# --- 3. 开始简单的录音后识别循环 ---
print(f"开始监听，程序会每 {INTERVAL_SEC} 秒识别一次，按 Ctrl+C 退出。")
try:
    while True:
        # 录制一段音频 (当前2秒)
        audio = sd.rec(int(INTERVAL_SEC * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                       channels=1, dtype='float32')
        sd.wait()  # 等待录音完成
        audio = audio.flatten()  # 整理成模型需要的一维数组

        # 调用模型进行识别，关键参数 language="auto" 支持中英文混合识别
        res = model.generate(input=audio, language="auto", use_itn=True)
        if res and res[0]['text']:
            print(f"识别结果: {res[0]['text']}")
        else:
            print("[没有检测到语音]")

except KeyboardInterrupt:
    print("\n程序已退出。")
