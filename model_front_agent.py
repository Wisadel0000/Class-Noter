"""前台 Agent — 轻量级对话 Agent，维持多轮记忆，工具集包含 set_custom_task"""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

import os
from dotenv import load_dotenv

import model_background_agent

load_dotenv()

model = init_chat_model(model_provider="openai",
                        model=os.getenv("LLM_MODEL"),
                        api_key=os.getenv("LLM_API_KEY"),
                        base_url=os.getenv("LLM_BASE_URL"),
                        temperature=0.5,
                        timeout=10,
                        max_tokens=1000,
                        )

class FrontAgent:
    _agent = create_agent(
        model=model,
        tools=[model_background_agent.set_custom_task],
        system_prompt="""你是一个课堂助手，负责和用户探讨与学习相关的内容。
                      在后台有一个笔记agent负责根据课堂内容整理结构化的笔记文件库。
                      如果用户有对笔记进行修改的需求，你可以调用工具给后台笔记agent下达任务命令（用自然语言描述任务要求）。""",
        checkpointer=InMemorySaver()
    )

    _messages = []

    @classmethod
    def sent_message(cls,content:str):
        message = HumanMessage(content=content)
        cls._messages = cls._agent.invoke({"messages": [message]},
                                            config={"configurable": {"thread_id": "1"}},)
        return cls._messages["messages"][-1].content

if __name__ == '__main__':
    while True:
        message = input("请输入消息：")
        print(FrontAgent.sent_message(message))