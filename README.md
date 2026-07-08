# ClassNoter v0.01

一个基于 ASR + LLM 的课堂笔记助手，将实时转为结构化笔记。

## 功能

- **实时语音转写** — 基于 FunASR + Paraformer-zh 模型，语音模块在本地运行
- **智能笔记整理** — 通过 LLM Agent（LangChain/LangGraph）将语音内容整理为结构化笔记
- **对话式交互** — 前台 Agent 支持多轮对话，可随时调整笔记内容
- **Flet 图形界面** — 简洁的桌面应用界面

## 快速开始

1. 安装依赖：

```bash
uv sync
```

2. 在 `.env` 中配置 LLM：

```env
LLM_BASE_URL=your_base_url
LLM_API_KEY=your_api_key
LLM_MODEL=your_modle
NOTE_ROOT_PATH=./note_dir #(默认笔记保存目录)
```

3. 运行：

```bash
python main.py
```

> ASR 模型（Paraformer-zh / CT-Punc）首次运行时会自动下载到 `asr_models/` 目录。

## 技术栈

- **ASR**: FunASR, Paraformer, ONNX Runtime
- **LLM**: LangChain, LangGraph, OpenAI API
- **UI**: Flet
- **Python**: >= 3.12

## 项目结构

```
ClassNoter/
├── main.py                      # 主入口
├── config.py                    # 配置管理
├── eventbus.py                  # 事件总线（解耦模块通信）
├── asr.py                       # 语音识别模块
├── model_background_agent.py    # 后台笔记整理 Agent
├── model_front_agent.py         # 前台对话 Agent
├── windows.py                   # 界面逻辑
├── Gui.py                       # GUI 组件
├── file_tools.py                # 文件工具
├── test/                        # 测试
└── pyproject.toml               # 项目配置
```
