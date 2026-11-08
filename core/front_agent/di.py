from di_container import DIContainer

from core.front_agent.Core import FrontAgentModule

def front_module_init(c:DIContainer):
    return FrontAgentModule(
        core_bus_router=c.resolve("CoreBusRouter"),
        core_loop=c.resolve("CoreLoop"),
        local_bus=c.resolve("Front_Bus"),
        local_loop=c.resolve("Front_Loop"),
        provider_router=c.resolve("LLMRouter"),
        tools_manager=c.resolve("ToolsManager"),
    )