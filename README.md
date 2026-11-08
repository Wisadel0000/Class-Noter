# ClassNoter

一个基于 ASR + LLM 的课堂笔记助手，实时将语音转为结构化笔记。

## 功能

- **实时课堂转写** — 基于 FunASR + Paraformer 模型，支持本地离线运行
- **智能笔记整理** — 通过 LLM Agent（LangChain/LangGraph）将语音内容整理为结构化笔记
- **对话式交互** — 前台 Agent 支持多轮对话，可随时命令Agent调整笔记内容
- **Flet 图形界面** — 简洁的桌面应用界面

## 快速开始

1. 安装依赖：

```bash
uv sync
```

2. 在 环境变量或`.env` 中配置API KEY：

```env
WEB_API_KEY="<你的大模型API_Key>"
DS_WEB_SEARCH_API_KEY="<deepseek API_key，用于联网搜索功能>"
DEFAULT_API_KEY="<备用的大模型API_Key>"
```

3. 构建程序（不完成这一步会导致程序内置的wiki浏览器无法工作）

```
flet build windows
```

此命令需要你的电脑安装过 "virtual studio C++ 工作负载(使用C++ 的桌面开发)"，否则无法正常构建

4. 运行：

```bash
python main.py
```

> ASR 模型（Paraformer / CT-Punc）首次运行时会自动下载到 `asr_models/` 目录。
>
> 本程序生成的笔记位于note/目录 下，其中raw为可读可明文编辑的wiki原文件，wiki为完成渲染的wiki页面文件。

## 技术栈

- **ASR**: FunASR（Paraformer-zh + fsmn-vad + ct-punc，本地离线）、ONNX Runtime、sounddevice
- **LLM**: LangChain + LangGraph；支持 OpenAI 兼容 API（DeepSeek 等）与本地 Ollama
- **UI**: Flet 桌面端，flet-webview-all 提供内置 wiki 浏览器
- **Wiki 引擎**: `wikiencoder`，自研纯文本 wiki 框架（解析 / 渲染 / 静态站点导出）
- **配置**: `SettingStore`（JSON 持久化 + 变更订阅）+ python-dotenv
- **环境**: uv、Python 3.12

## 项目结构

```
ClassNoter/
├── main.py                      # 程序入口
├── di_container.py              # 轻量依赖注入容器（singleton / transient）
├── Gui.py                       # Flet 界面（对话、工作日志、设置抽屉、内置 wiki 浏览器）
├── pyproject.toml               # 依赖与项目配置
├── setting.json                 # 运行时用户设置（缺失时用默认值，修改后自动写回）
│
├── event/                       # 事件层
│   ├── event_core.py            # Bus / Loop / Router，模块间解耦通信
│   └── events.py                # 全局事件定义
│
├── settings/                    # 配置层
│   ├── setting_store.py         # 配置读取、持久化与变更通知
│   ├── provider_setting.py      # 模型提供商配置
│   ├── wiki_settings.py         # wiki 相关配置
│   ├── routers/provider.py      # LLM 路由器（web_api / ollama）
│   └── di.py                    # 配置层装配
│
├── core/                        # 业务模块
│   ├── reporter/                # 课堂转述（录音 + ASR）
│   │   ├── Core.py
│   │   └── asr_models/          # 文本识别模型存放目录
│   ├── background_agent/        # 后台笔记 Agent 模块
│   │   ├── Core.py              # 任务调度核心逻辑
│   │   ├── Agent.py             # 工作Agent
│   │   ├── Tasks.py             # 任务定义（笔记任务等）
│   │   ├── BaseTask.py          # 基础任务类型（抽象）
│   │   ├── graphs_manager.py    # LangGraph 图块 / 图块相关任务管理
│   │   └── log_store.py         # 工作日志维护与推送
│   ├── front_agent/             # 前台 Agent 模块
│   ├── wiki/                    # wiki 业务层（页面 CRUD、校验、导出）
│   └── tools/                   # 工具管理器与通用工具（文件、联网搜索）
│
├── wikiencoder/                 # 自研纯文本 wiki 引擎
│   ├── parser.py / serializer.py / model.py   # 解析与逐字节无损序列化
│   ├── render/                  # HTML / Markdown 渲染
│   ├── export.py                # 静态站点导出
│   └── assets/                  # 语法文档与页面模板
│
└── note/                        # 程序产出位置
    ├── raw/                     # .wiki 源文件（明文）
    └── wiki/                    # 导出的静态 wiki 站点
```