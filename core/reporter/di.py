from di_container import DIContainer

from core.reporter.Core import AsrModule

def reporter_module_init(c:DIContainer):
    return AsrModule(
        core_bus_router=c.resolve("CoreBusRouter"),
        core_loop=c.resolve("CoreLoop"),
        local_bus=c.resolve("Reporter_Bus"),
        local_loop=c.resolve("Reporter_Loop"),
    )