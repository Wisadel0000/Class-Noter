import os
from abc import ABCMeta
from itertools import count
from queue import PriorityQueue
from time import sleep
from typing import Callable, Literal

from langchain.chat_models import init_chat_model
from langchain.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool
from langchain_core.messages import RemoveMessage
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages, REMOVE_ALL_MESSAGES
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import TypedDict, Annotated

import asr
import file_tools as ttools


agent_log_counter = 0

# 日志工具
@tool
def log_operation(action_type: str, file_path: str, description: str):
    """
    记录对笔记库的操作日志
    action_type: 进行了什么操作（创建/删除/修改/移动）
    file_path: 对什么文件进行了操作
    description: 本次操作内容的描述
    """

    global agent_log_counter
    log_file = 'agent.log'
    dir_name, file_name = os.path.split(file_path)

    # 确保日志文件所在目录存在
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    agent_log_counter += 1

    # 格式化日志行
    log_line = f"log-{agent_log_counter}：在\"{dir_name}\"中{action_type}了\"{file_name}\"，{description}\n"

    # 追加写入文件（使用 utf-8 编码）
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(log_line)
    print("[agent日志更新] ", log_line)

    return "已创建日志"

#消息任务发送（供前台FrontAgent使用）
@tool
def set_custom_task(task_message:str):
    """用于给后台的笔记Agent发送自然语言描述的命令"""
    task = MessageTask(task_message)
    TaskManager.append_task(task)

# 默认工具列表
default_tools = [log_operation]
default_tools_by_name = {tool.name: tool for tool in default_tools}

model = init_chat_model(model_provider="openai", model=os.getenv("LLM_MODEL"), api_key=os.getenv("LLM_API_KEY"),
                        base_url=os.getenv("LLM_BASE_URL"), temperature=0, )


# 定义Agent的消息state    (以类型注解的形式)
class MessageState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    last_note: str  # legacy
    past_note: str  # legacy
    now_task: str
    agent_prompt: str
    work_message: str
    llm_calls: int


class Task(metaclass=ABCMeta):
    task_name: str
    task_priority = 3  # 优先级从1到5，默认3
    route_before_agent: str
    route_after_agent: str


class FunctionTask(Task):
    handler: list[Callable]


class AgentTask(Task):
    task_prompt: str
    task_message: str
    tools: list[Callable]


class MultiTask(Task):
    handler: list[Callable]
    task_prompt: str
    task_message: str
    tools: list[Callable]


class TaskManager:
    task_list = PriorityQueue()
    counter = count()

    @classmethod
    def append_task(cls, task: Task):
        # task的合法性检查
        if not (task.task_name and task.route_before_agent and task.route_after_agent):
            raise ValueError("任务名，Agent前路由和Agent后路由不能为空！")

        cls.task_list.put((task.task_priority, next(cls.counter), task))

    @classmethod
    def get_task(cls):
        task = cls.task_list.get()[2]
        return task


class NotingTask(AgentTask):
    task_name = "noting"
    # self.task_priority 默认值3
    route_before_agent = "agent_legacy"
    route_after_agent = "ender"
    task_prompt = ""
    task_message = f"""这是一句空占位消息，请回复“本轮回复结束”\n"""
    tools = [ttools.move_md_file, ttools.read_md_file, ttools.create_directory, ttools.create_md_file,
             ttools.delete_directory, ttools.delete_md_file, ttools.list_all_directories, ttools.list_directory,
             ttools.move_directory, ttools.overwrite_md_file, ttools.rename_directory, ttools.rename_md_file, ]

    def __init__(self):
        ...


class MessageTask(AgentTask):
    task_name = "message"
    route_before_agent = "agent_node"
    route_after_agent = "ender"
    tools = [ttools.move_md_file, ttools.read_md_file, ttools.create_directory, ttools.create_md_file,
             ttools.delete_directory, ttools.delete_md_file, ttools.list_all_directories, ttools.list_directory,
             ttools.move_directory, ttools.overwrite_md_file, ttools.rename_directory, ttools.rename_md_file, ]
    task_prompt = "你是一个乐于助人的助手"  # TODO: 没实现

    def __init__(self, task_message: str, ):  # type: ignore
        if task_message in [None, ""]:
            raise ValueError("Mission messages cannot be empty")
        self.task_message = task_message


class GraphBlock(metaclass=ABCMeta):
    """
    图块：自定义的LangGraph子图，用于拼接在Agent工作图上
    图块中至少有一个入节点和一个出边，且保证图内连通。
    图块中若有model_with_tool，请在类内自行组建
    """
    graph_name: str
    in_node: tuple[str, Callable]
    """图块的进入节点"""
    out_edge: tuple[str, list[str], Callable,]
    """图块的出边[图内节点,图外节点列表,条件边判断函数]"""
    self_node: list[tuple[str, Callable]] = []
    """图块内节点(不包括出节点)"""
    self_edges: list[tuple[str, str]] = []
    """图块内边(不包括出边)"""  # 先这么写吧，之后再改成默认第0个边/节点特殊边/节点


class AgentLegacy(GraphBlock):
    graph_name = "agent_legacy"

    _tools = [ttools.move_md_file, ttools.read_md_file, ttools.create_directory, ttools.create_md_file,
              ttools.delete_directory, ttools.delete_md_file, ttools.list_all_directories, ttools.list_directory,
              ttools.move_directory, ttools.overwrite_md_file, ttools.rename_directory,
              ttools.rename_md_file, ] + default_tools
    _tools_by_name = {tool.name: tool for tool in _tools}

    # 嵌入工具的模型实例
    _model_with_tools = model.bind_tools(_tools)

    # 拉取&摘要节点
    @staticmethod
    def digester(state: dict):
        """
        知识提取
        """
        system_prompt = """你的任务是根据用户发送的课堂语音转写文字，提取老师讲到的所有知识点。请直接输出提取结果，不要输出其他内容。

    要求：
    - 你可以对原文内容进行理解、归纳和概括，但不得添加原文中未提及的任何背景知识、定义或补充说明。
    - 语音识别可能存在错别字（如将“弗朗西斯科”误识别为“菲斯科西里洛”），请结合上下文修正明显的专有名词错误。（不用标注原文）
    - 如果某段信息包含多个要点，请使用 Markdown 分点或分层标题输出，保持逻辑层次。
    - 如果有，请尽量保留原文中的因果关系和论证过程，避免只抽取结论。

    如果文本中没有有效知识点，请输出“本轮无知识点”。"""
        # 拉取新ASR转述
        text = asr.get_new_text()
        print("[Agent已拉取文本]：", text)
        # 把last覆盖进past，记录新的last
        _last_note = state["last_note"]
        _past_note = "...\n" + _last_note
        # 调用模型获取last
        _last_note = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=text), ]).content
        print("[摘要输出]：", _last_note)
        # return更新状态
        return {"last_note": _last_note, "past_note": _past_note, "llm_calls": state.get('llm_calls', 0) + 1, }

    @staticmethod
    def noter(state: dict):
        """"
        笔记节点
        """
        system_prompt = """你是一个高度自主的“个人笔记库管理员”。你的核心任务是维护一个**结构清晰、无冗余、知识互相贯通**的本地 Markdown 笔记库。

    你会周期性收到两部分信息：
    1. **本次新增知识点**：一段文本，里面包含了一个或多个课堂上刚刚讲过的知识点（可能混杂不同领域）。
    2. **历史操作日志**：你过去每次整理笔记时留下的操作摘要，形如：
       “第2134次笔记任务：牛顿第一定律和热力学理论概况相关任务  
        log-1: 在"./物理学/经典力学/"中创建了 牛顿第一定律.md，整理了起源、发展和应用。  
        log-2: 在"./物理学/经典力学/"中修改了 牛顿.md，在生平主要成果中加入了牛顿第一定律相关的描述。  
        log-3: 在"./物理学/热力学/"中创建了 热力学概况.md，……”  

    你可以参考历史日志，了解自己曾经整理过哪些文件、放在什么路径、文件之间有什么关联，从而做出更聪明的决策。

    系统已经为你配备了完整的文件管理工具（具体参数定义已内置，请严格使用下面列出的函数名进行调用）。你**一次只能调用一个工具函数**，每次调用后会收到该工具的返回结果，然后继续下一步决策。

    你可调用的工具函数：
    - **list_directory** – 列出某目录下的所有文件和子文件夹（返回路径名及类型）。
    - **list_all_directories** – 递归展示整个笔记库的目录树。
    - **read_md_file** – 读取指定 .md 文件的全文内容。
    - **create_md_file** – 新建 .md 文件，可同时写入内容。
    - **overwrite_md_file** – 用新内容覆盖已有 .md 文件（若不存在则创建）。
    - **delete_md_file** – 删除指定 .md 文件。
    - **move_md_file** – 移动或重命名 .md 文件。
    - **rename_md_file** – 重命名 .md 文件（留在原目录）。
    - **create_directory** – 创建文件夹（自动创建父目录）。
    - **delete_directory** – 删除空文件夹（请确保为空后才能调用）。
    - **move_directory** – 移动或重命名文件夹。
    - **rename_directory** – 重命名文件夹。
    - **log_operation** – 记录操作日志，参数包括 `action_type`（操作类型）、`file_path`（操作的文件或文件夹路径）、`description`（中文描述做了什么及原因）。

    **所有文件路径请使用以 "./" 开头的、相对于笔记根目录的相对路径**（例如 `./数学/勾股定理.md`）。你可以根据知识领域自由创建多级文件夹结构。

    ## 你的核心决策原则

    ### 1. 拆分知识点
    先仔细阅读“本次新增知识点”，识别出其中包含的每一个独立的知识主题（例如“勾股定理”“三角函数”“万有引力定律”）。如果有多个主题，要对每个主题分别执行后续决策。

    ### 2. 查找已有相关条目
    对于每一个知识主题，你都需要：
    - 通过 `list_directory` 和 `read_md_file` 探查笔记库中是否已经存在与之相同、相近或属于其父概念的文件。
    - 检查历史日志中是否提及过该主题或相近主题的操作（日志会告诉你相关文件的可能位置和名称）。

    ### 3. 严格忠于原始材料，禁止臆造信息 （新增强制原则）
    **你的一切修改都必须基于以下两个信息源，不得自行编造或扩写：**
    - **本次新增知识点**中明确给出的句子、定义、解释、示例等。
    - **笔记库中已有文件**的实际内容。

    具体规则：
    - 如果新增知识点对某个概念给出了详细的解释，你可以在创建或更新词条时引用、归纳这些解释，但**不能添加上下文未出现的额外事实**。
    - 如果新增知识点**仅仅提及了某个术语的名字，而没有任何一句说明**，你可以：
      - **创建占位词条**：新建一个以该术语命名的 `.md` 文件，内容仅写入 `# 术语名` 和 `*该词条暂无详细解释，待后续补充。*` 这样的标记，然后通过 `log_operation` 记录。  
      - **或选择不创建该词条**：如果它并非本次新增知识点的核心，也可以暂不创建，待将来有实际解释时再处理。
    - **禁止**：在没有任何原始材料支撑的情况下，靠你自己的常识去编写该术语的定义、原理、应用等内容。即使你认为那个术语的含义是“常识”，也必须克制，只使用提供给你的文字。
    - 进行“跨文件关联与补充”（见下条）时，也只能使用笔记库中已有文件内实际记载的内容或新增知识点中明确陈述的信息，**不能杜撰联系或补全事实**。

    ### 4. 判定操作类型
    根据探查结果，按以下优先级决定操作：

    **a. 强相关已存在文件 → 更新已有文件**
    - 若已有文件的名字与该知识主题完全一致，或该主题明确是已有文件所描述概念的子集/延伸，则应**覆写或追加**已有文件，而不是新建文件。
    - 例如：已有“三角函数.md”，新知识点是“三角函数的应用”，你应该去更新“三角函数.md”。
    - 更新时，只将新增知识点中**明确给出的、适合该文件主题的内容**加入，不要自行扩写。

    **b. 有父级概念文件 → 归入父文件并添加内部小节**
    - 如果已有某个文件是该知识主题的上位概念（如“物理学.md”之于“牛顿第一定律”），你可以将新知识点作为一个小节整合进该父文件，而不是单独建文件。
    - 如果父文件内容过于庞大，也可以新建子文件，但必须在父文件中留下指向子文件的链接或提及，保持知识网的联系。

    **c. 完全无相关 → 创建新词条（按原则3处理）**
    - 若确定库中没有直接相关文件，则创建一个新的 `.md` 文件，用该知识主题作为文件名。**文件内容严格按原则3执行**：有详细解释则整理之，仅有名词则写入占位标记。同时判断是否需要放入某个已有文件夹下，或新建一个领域文件夹进行分类。

    ### 5. 跨文件关联与补充（严格基于已有信息）
    每当你**新建或更新了一个词条文件后**，你都必须主动思考：“笔记库中还有哪些文件可能与这个知识点产生联系？我可以为它们补充什么？”

    典型行动：
    - 利用 `list_directory`、`list_all_directories` 和 `read_md_file` 扫描你认为可能相关目录下的文件，或者根据历史日志回忆起以往创建过的相关文件。
    - 在那些相关文件中添加一小节，说明与本知识点的关系，或补充由本知识点带来的新见解。
    - **所有补充都必须来自笔记库中已有文件的实际内容或本次新增知识点中的明确陈述**，不得自己编造关联或补全知识。
    - 例如：你刚刚整理完“勾股定理.md”（已从新增知识点中获得了定义和应用案例），然后想起库里还有“圆的函数表达式.md”，你应当打开后者，看是否需要添加“与勾股定理的几何联系”相关内容——但这份联系必须基于已存在于两处的信息，而非你自己想象的推导。

    ### 6. 碎片文件合并
    如果在对某个主题的搜索过程中，你发现笔记库中存在**多个文件共同描述同一大知识点的不同分点**（如“番茄工作法的定义.md”、“番茄工作法的起源.md”、“番茄工作法的优点.md”），你必须：
    - 读取所有这些文件的内容。
    - 创建一个整合后的大文件（如“番茄工作法.md”），将原有各文件的内容组织成不同的章节。
    - 用 `overwrite_md_file`（或 `create_md_file`）创建/更新整合文件后，调用 `delete_md_file` 删除原先那些零散的分点文件。
    - 如果零散文件分别放在不同目录，整合后请放到一个最能代表该大主题的文件夹下。
    - 整合过程只做组织整理，**不得添加任何未出现在原始文件中的信息**。

    ### 7. 层级化管理
    - 对属于同一大学科或领域的文件，使用文件夹进行归类（例如“数学/几何/”、“物理学/力学/”、“效率方法/”）。
    - 如果新知识点导致你需要创建一门全新的领域分支，就新建一个文件夹。
    - 移动文件来优化目录结构也是你的职责，例如将散落在根目录下的文件归入合适的子文件夹。

    ### 8. 利用历史日志进行智能联想
    历史日志是你最宝贵的线索来源：
    - 当拿到一个新知识点时，快速浏览历史日志，看看是否提到过类似的主题或相关文件路径。
    - 日志可能会提醒你：“很久以前我创建过‘牛顿.md’，里面可能已经有部分第一定律的内容”，从而避免重复建文件。
    - 日志还能帮助你发现潜在的跨文件补充机会：比如日志显示曾修改过“物理学简史.md”加入热力学内容，那么现在新整理的“熵”概念也应当考虑去更新“物理学简史.md”——前提是新增知识点中确实给出了熵的相关描述或该文件已包含相关信息。

    ### 9. 实时记录操作日志（极重要）
    **每次你调用 `create_md_file`、`overwrite_md_file`、`delete_md_file`、`delete_directory`、`move_md_file`、`rename_md_file`、`move_directory`、`rename_directory` 等任何修改性操作后，都必须立即调用 `log_operation` 工具，如实记录你刚刚完成的操作。**
    - `action_type` 必须准确反映你刚才的修改类型（如 “创建”、“删除”、“修改”、“移动”等）。
    - `file_path` 写清你操作的文件或文件夹路径（与刚才修改工具调用的路径保持一致）。
    - `description` 中用自然语言详细解释这次操作的内容和意图（例如 “创建了勾股定理.md，整理了定义、证明和历史应用”）。
    - 即使是批量操作中的一小步，也要逐条记录，不能遗漏。
    - 这样生成的日志，会在未来的任务中作为“历史操作日志”反馈给你，帮助你做出更聪明的关联决策。

    ## 你的工作流程（每一次被调用时）
    1. **分析**：阅读“本次新增知识点”和历史日志，列出所有独立知识主题。区分哪些主题有实质描述，哪些仅被提及名字。
    2. **探查**：针对每个主题，使用工具探查笔记库当前状态（如 `list_directory`、`read_md_file`）。
    3. **规划**：在脑海中形成一个修改计划（新建/更新/合并/移动/补充），严格遵循“只能使用给定信息”的原则。
    4. **执行与观察**：调用一个工具，根据返回结果更新你对笔记库状态的认知。  
       **如果刚刚执行的是一个修改性操作（增、删、改、移），则立即调用 `log_operation` 记录日志，然后再进行下一步。**
    5. **循环**：重复步骤2-4，持续决策，直到你确认：
       - 所有新知识点都已恰当融入笔记库；
       - 所有必要的跨文件补充和合并都已完成；
       - 目录结构已合理；
       - 没有任何多余或过时的文件需要清理；
       - 所有修改操作均已通过 `log_operation` 记录完毕。
    6. **结束**：当你认为笔记库已经完美吸收了本次新知识，没有任何需要再增、删、改、移的操作时，请直接输出 **“任务完成”** 这四个字，不再调用任何工具。

    ## 示例推演（特别注意占位词条的处理）
    假设现有笔记库为空。

    本次新增知识点字符串：
    “今天我们简要介绍了自然语言处理（NLP）的核心任务，包括分词、词性标注和命名实体识别。机器翻译是 NLP 的重要应用之一。另外，老师还随口提到了大语言模型和机器客服。”

    你应该这样做：
    1. 拆分主题：
       - “自然语言处理（NLP）”及其子任务“分词”“词性标注”“命名实体识别”——有详细解释。
       - “机器翻译”——被提及为重要应用，但未给任何具体描述。
       - “大语言模型”“机器客服”——仅被提到名称，无解释。
    2. 创建 NLP 相关词条：
       - 探查库中无相关文件，创建 `./自然语言处理/NLP.md`，内容基于原文整理核心任务部分。
       - **立即记录日志**。
       - 对于分词、词性标注、命名实体识别，由于它们是 NLP 的子任务，可以在 `NLP.md` 中分别为它们创建小节，而不是单独建文件。所有内容严格来自原文。
    3. 处理“机器翻译”：
       - 原文并未给出任何解释，仅说是应用。按照原则3，你可以：
         - 方案A：在 `NLP.md` 的应用部分简单列出“机器翻译”，但不做展开。  
         - 方案B：创建一个 `./自然语言处理/机器翻译.md`，内容写入 `# 机器翻译` 和 `*该词条暂无详细解释，待后续补充。*`（占位词条）。  
       - 此处选择方案A更合理，因为信息太少。若选择新建占位词条，也必须立刻 `log_operation` 记录。
    4. 处理“大语言模型”和“机器客服”：
       - 同样只有名字，无解释。可以分别为它们创建占位词条（放在合适的文件夹，如 `./自然语言处理/大语言模型.md` 和 `./自然语言处理/机器客服.md`），内容均为“暂无详细解释”。
       - **禁止**根据自己的知识去编写“大语言模型是基于 Transformer 的…”等内容。
       - 创建后立即记录日志。
    5. 检查无其他修改，输出“任务完成”。

    ## 特别提醒
    - 你每步只能调用一个工具函数，并耐心等待返回结果，再决定下一步。
    - 你必须基于工具返回的实际文件内容和目录结构来决策，不能凭空猜测。
    - 当对文件进行覆写（`overwrite_md_file`）时，务必先用 `read_md_file` 获取完整旧内容，然后在其基础上修改、追加，再写回，避免丢失原有信息。
    - 删除文件或文件夹前，请确认该操作是安全的、且确实不再需要其中的信息。
    - **日志记录是自动形成的闭环**：你今天的 `log_operation`，就是明天的历史操作日志。因此务必详细、准确，不要偷懒。
    - 如果一次新增知识点非常多，不要急着一次性做完所有事，可以分轮次逐步处理，但最终目标是把所有内容完全整理好。

    现在，请等待系统给你“本次新增知识点”和历史日志，然后开始你的笔记整理工作。"""
        log_content = ""
        if os.path.exists('agent.log'):
            with open('agent.log', 'r', encoding='utf-8') as f:
                log_content = f.read()

        # 过滤掉 RemoveMessage 等 LangChain 内部消息类型
        valid_messages = [m for m in state["messages"] if not isinstance(m, RemoveMessage)]

        return {"messages": [AgentLegacy._model_with_tools.invoke([SystemMessage(content=system_prompt), HumanMessage(
            content=f"""本次新知识点：{state["last_note"]}\n历史知识点：{state["past_note"]}\n历史操作日志：{log_content}""")] + valid_messages)],
                "llm_calls": state.get('llm_calls', 0) + 1, }

    # 工具节点：输入一个状态（字典），输出一个新包装好的消息列表
    @staticmethod
    def tool_node(state: dict):
        """执行AI所要求的工具函数"""
        result = []
        for tool_call in state["messages"][-1].tool_calls:
            tool = AgentLegacy._tools_by_name[tool_call["name"]]
            observation = tool.invoke(tool_call["args"])
            result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"], ))
        return {"messages": result}

    # 给条件边使用的判断函数：输入一个消息状态（上个节点的输出），输出一个枚举元素（下一个目标节点的名字）
    @staticmethod
    def should_continue(state: MessageState) -> Literal["tool_node", "ender"]:
        """"根据模型的传出信息判断是否结束思考-观察周期（如果 上轮LLM调用了工具，就把状态传给工具节点）"""

        # 取出最新的消息
        messages = state["messages"]
        last_message = messages[-1]

        # 观察大模型是否进行了工具调用 （tool_call 字段是否不为空）
        if last_message.tool_calls:
            return "tool_node"  # 进入tool_node节点
        else:
            return "ender"  # 进入END节点

    in_node = ("digester", digester)
    out_edge = ("noter", ["tool_node", "ender"], should_continue)
    self_node = [("noter", noter), ("tool_node", tool_node), ]
    self_edges = [("digester", ["noter"], None), ("tool_node", ["noter"], None)]


# 已注册的图块
block_registered = [AgentLegacy, ]
blocks_by_name = {block.graph_name: block for block in block_registered}
blocks_in_nodes_by_name = {block.graph_name: block.in_node[0] for block in block_registered} # 从图块名到入节点名的映射
# block_in_nodes = [block.in_node for block in block_registered]

# 已注册的事件
task_registered = [NotingTask, MessageTask, ]
tasks_by_name = {task.task_name: task for task in task_registered}
all_tools_by_name = {tool.name: tool for task in task_registered for tool in task.tools} | default_tools_by_name # TODO tool可能会重复
all_router_before_agent = [task.route_before_agent for task in task_registered]
all_router_after_agent = [task.route_after_agent for task in task_registered]
# 添加基础任务
TaskManager.append_task(NotingTask())

def r_map(address:str|list[str]) :
    """"route_mapper路由映射器，
    根据已注册的图块名把所有图块名映射到真正的入节点上"""
    if isinstance(address,str):
        return blocks_in_nodes_by_name.get(address,address)
    elif isinstance(address,list) and isinstance(address[0],str):
        return list(map(lambda _: blocks_in_nodes_by_name.get(_, _), address))


# ============ agent正式搭建 ============

class BackgroundAgent:
    _agent: CompiledStateGraph

    @staticmethod
    def task_router(state: dict):
        """任务路由器：清理笔记message上下文并根据计时准备进入下一轮整理"""
        print("新一轮整理程序已启动")
        task = TaskManager.get_task()

        if isinstance(task, NotingTask):
            TaskManager.append_task(task)
            sleep(30)  # TODO 临时计时器(等待Asr模块积累文本)

        if isinstance(task, FunctionTask):
            if task.handler:
                for handle in task.handler:
                    handle()
            return {"now_task": task.task_name}
        elif isinstance(task, AgentTask):
            return {"agent_prompt": task.task_prompt, "work_message": task.task_message, "now_task": task.task_name}
        elif isinstance(task, MultiTask):
            if task.handler:
                for handle in task.handler:
                    handle()
            return {"agent_prompt": task.task_prompt, "work_message": task.task_message, "now_task": task.task_name}
        else:
            raise TypeError("无法被识别的任务类型")

    # agent节点
    @staticmethod
    def agent_node(state: dict):
        """"
        agent “观察-执行”循环节点————观察节点
        """
        # 提示词获取
        system_prompt = state["agent_prompt"]
        human_msg = state["work_message"]
        # 工具列表获取
        task = tasks_by_name[state["now_task"]]
        _tools = task.tools + default_tools
        # 工具嵌入
        _model_with_tools = model.bind_tools(_tools)
        # 过滤掉 RemoveMessage 等 LangChain 内部消息类型
        valid_messages = [m for m in state["messages"] if not isinstance(m, RemoveMessage)]
        return {"messages": [_model_with_tools.invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=human_msg)] + valid_messages)],
            "llm_calls": state.get('llm_calls', 0) + 1, }

    # 工具节点：输入一个状态（字典），输出一个新包装好的消息列表
    @staticmethod
    def agent_tool(state: dict):
        """
        agent “观察-执行”循环节点————执行节点
        :param state:
        :return:
        """
        result = []
        for tool_call in state["messages"][-1].tool_calls:
            tool = all_tools_by_name[tool_call["name"]]
            observation = tool.invoke(tool_call["args"])
            result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"], ))
        return {"messages": result}

    @staticmethod
    def ender(state: dict):
        """用于处理事件结束后的逻辑，比如清理message上下文"""

        # task = tasks_by_name[state["now_task"]]
        #
        # if isinstance(task, NotingTask):
        #     TaskManager.append_task(task)
        #     sleep(30)  # TODO 临时计时器(等待Asr模块积累文本)

        messages_to_remove = [RemoveMessage(id=REMOVE_ALL_MESSAGES)]
        return {"messages": messages_to_remove}

    @staticmethod
    def router_before_agent(state: MessageState) -> str:
        task_name = state["now_task"]
        task = tasks_by_name[task_name]
        if issubclass(task, FunctionTask):
            return "ender"
        else:
            return r_map(task.route_before_agent)

    # agent内部循环条件
    @staticmethod
    def router_after_agent(state: MessageState) -> str:

        # 取出最新的消息
        messages = state["messages"]
        last_message = messages[-1]

        # 观察大模型是否进行了工具调用 （tool_call 字段是否不为空）
        if last_message.tool_calls:
            return "agent_tool"  # 进入agent_tool节点

        task_name = state["now_task"]
        task = tasks_by_name[task_name]
        return r_map(task.route_after_agent)

    @classmethod
    def compile(cls):
        # 状态图实例
        _blue_map = StateGraph(MessageState)
        # 节点加入
        _blue_map.add_node("task_router", cls.task_router)
        _blue_map.add_node("agent_node", cls.agent_node)
        _blue_map.add_node("agent_tool", cls.agent_tool)
        _blue_map.add_node("ender", cls.ender)
        # 自定义子图内节点
        _ls_node = [i for graph in block_registered for i in (graph.self_node + [graph.in_node])]
        for node in _ls_node:
            _blue_map.add_node(*node)
        # 边加入
        _blue_map.add_edge(START, "task_router")
        _blue_map.add_conditional_edges("task_router", cls.router_before_agent,
                                        list(set( r_map(all_router_before_agent + ["agent_node", ])))
                                        )
        _blue_map.add_conditional_edges("agent_node", cls.router_after_agent,
                                        list(set(r_map(all_router_after_agent + ["agent_tool","ender" ])))
                                        )
        _blue_map.add_edge("agent_tool", "agent_node")
        _blue_map.add_edge("ender", "task_router")
        # 自定义子图内边
        _ls_edge = [i for graph in block_registered for i in (graph.self_edges + [graph.out_edge])]
        for edge in _ls_edge:
            if edge[2]:  # 如果是条件边
                _blue_map.add_conditional_edges(edge[0], edge[2], r_map(edge[1]))
            else:
                _blue_map.add_edge(edge[0], r_map(edge[1][0]))

        # 编译
        cls._agent = _blue_map.compile()

    @classmethod
    def run(cls):
        if not cls._agent:
            raise ValueError("agent不存在，应先进行编译agent_builder.compile()")

        cls._agent.invoke({"messages": [],
                           "last_note": "",
                           "past_note": "",
                           "now_task": "",
                           "agent_prompt": "",
                           "work_message": "",
                           "llm_calls": 0})  # agent转起来


# ========================

def run_agent():
    BackgroundAgent.compile()
    BackgroundAgent.run()  # agent转起来


if __name__ == '__main__':
    run_agent()
