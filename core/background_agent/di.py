from di_container import DIContainer

from core.background_agent.Core import BackgroundAgentModule
from core.background_agent.Agent import BackgroundAgent
from core.background_agent.log_store import LogStore
from core.background_agent.graphs_manager import GraphBlockManager,GraphTaskManager

def background_module_init (c:DIContainer):
    """前置：CoreBusRouter, CoreLoop, LLMRouter, ToolsManager, Background_Bus, Background_Loop"""
    graph_task_manager = GraphTaskManager()
    graph_block_manager = GraphBlockManager()
    # ------ 这里会完成一些图块和任务的注册 ------
    # *现在还没有图块（*

    core_bus_router = c.resolve("CoreBusRouter")
    core_loop = c.resolve("CoreLoop")
    local_bus = c.resolve("Background_Bus")
    local_loop = c.resolve("Background_Loop")
    llm_router = c.resolve("LLMRouter")
    tools_manager = c.resolve("ToolsManager")

    agent = BackgroundAgent(
        local_bus = local_bus,
        local_loop = local_loop,
        provider_router=llm_router,
        tools_manager=tools_manager,
        graph_block_manager=graph_block_manager,
        graph_task_manager=graph_task_manager)

    log_store = LogStore(
        core_bus_router=core_bus_router,
        core_loop=core_loop,
        local_bus=local_bus,
        local_loop=local_loop,
        provider_router=llm_router,
        tools_manager=tools_manager,
    )

    module = BackgroundAgentModule(
        core_bus_router=core_bus_router,
        core_loop=core_loop,
        local_bus=local_bus,
        local_loop=local_loop,
        agent=agent,            #this module
        log_store=log_store,    #this module

    )
    return module