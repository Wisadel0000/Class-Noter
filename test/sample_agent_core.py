from langchain.tools import tool
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
import os

load_dotenv()

model = init_chat_model(
    model_provider="openai",
    model = os.getenv("LLM_MODEL"),
    api_key = os.getenv("LLM_API_KEY"),
    base_url = os.getenv("LLM_BASE_URL"),
    temperature =  0 ,
)


@tool
def try_to_add_dict():
    """尝试创建一个文件"""
    print("agent正在尝试创建一个文件")
    return "你成功的创建了一个文件"


#工具列表
tools = [try_to_add_dict]
#工具名单构建
tools_by_name = {
    tool.name: tool for tool in tools
}
#将工具"镶进"模型（给模型暴露工具列表）
model_with_tools = model.bind_tools(tools)


#========================


from langchain.messages import AnyMessage
from typing_extensions import TypedDict,Annotated
import operator

#定义Agent的消息state    (以类型注解的形式)
class MessageState(TypedDict):
    messages : Annotated[list[AnyMessage], operator.add]
    llm_calls : int


#========================


from langchain.messages import SystemMessage

#大模型节点：输入一个状态（字典），输出一个包装了大模型新消息的状态更新补丁
def llm_call(state: dict):
    """"
    在 本节点 由 LLM 决定 Agent 是否要调用大模型
    """
    system_prompt = " 你是一个一个一个一个一个一个会员制作小助手，你的功能是帮用户创建文件。"

    return {
        "messages": [
            model_with_tools.invoke(
                [SystemMessage(content=system_prompt)] + state["messages"]
            )
        ],
        "llm_calls": state.get('llm_calls', 0) +1,
    }


#========================

from langchain.messages import ToolMessage

#工具节点：输入一个状态（字典），输出一个新包装好的消息列表
def tool_node(state: dict):
    """执行AI所要求的工具函数"""
    result = []
    for tool_call in state["messages"][-1].tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])
        result.append(
            ToolMessage(
                content = observation,
                tool_call_id  = tool_call["id"],
            )
        )
        return {"messages": result}


#========================


from typing import Literal
from langgraph.graph import END

#给条件边使用的判断函数：输入一个消息状态（上个节点的输出），输出一个枚举元素（下一个目标节点的名字）
def  should_continue(state: MessageState) -> Literal["tool_node", END]:
    """"根据模型的传出信息判断是否结束思考-观察周期（如果 上轮LLM调用了工具，就把状态传给工具节点）"""

    #取出最新的消息
    messages = state["messages"]
    last_message = messages[-1]

    #观察大模型是否进行了工具调用 （tool_call 字段是否不为空）
    if last_message.tool_calls:
        return "tool_node"  #进入tool_node节点
    else : return END       #进入END节点


#========================


from langgraph.graph import StateGraph, START

#开始超级拼装！
#创建构建器
agent_builder = StateGraph(MessageState)

#把节点都加入进去
agent_builder.add_node("llm_call", llm_call)
agent_builder.add_node("tool_node", tool_node)

#接下来把边也加进去

#连接 START 和 “llm_call”
agent_builder.add_edge(START,"llm_call")

#增加条件边（根据条件函数的判断结果决定状态要传给哪个节点）
agent_builder.add_conditional_edges(
    "llm_call",           #edge的起始点
    should_continue,             #判断函数
    ["tool_node", END]  #接下来的节点列表（对应判断函数的输出）
)
agent_builder.add_edge("tool_node", "llm_call")

#“编译”这个agent
agent = agent_builder.compile()


#========================
from langchain.messages import HumanMessage
A = input("输入消息：")
B = agent.invoke({"messages":[HumanMessage(A)]})
B["messages"][-1].pretty_print()

