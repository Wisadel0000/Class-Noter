#子agent模板的保存
#子agent的构建（模板创建）
#子agent的实例化 *生命周期控制*
from langchain.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict, Annotated

import _legacy.model as model_router

""" Subagent 在创建模板时，必须只专注于完成一件任务，操作一个对象"""

model = model_router.model

_base_prompt = """
如果发现你的任务职责与你收到的任务内容不符，请发送日志并直接终止本次任务。
"""

# 关键消息状态的定义
class SubMessageState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    base_prompt: str
    task_prompt: str # 任务需求的基本概括
    operation_manual: str # 操作手册（基本规则、特使情况应对方式）
    task_intelligence: str # 本轮任务的相关基本信息（我觉得最好是json或class这种基本的字典式类型，先用str吧）

# 工具的构建

#开始节点
def start_node(state: dict):
    pass # 后续自定义逻辑
    return state
#LLM节点
def llm_node(state: dict):
    base_prompt = state["base_prompt"]
    task_prompt = state["task_prompt"]
    operation_manual = state["operation_manual"]

    task_intelligence = state["task_intelligence"]

    # 提示词拼装
    prompt =("你的身份：\n" + task_prompt
             + "\n任务规则：\n" + operation_manual
             + "\n基本原则：\n" + base_prompt)

    #工具列表构建
    pass



    return state #TODO
#工具节点
#条件边
#终止节点