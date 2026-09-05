from . import bake_smoothnormal, panel, properties


MODULES = (properties, bake_smoothnormal, panel)


def register():
    for module in MODULES:
        module.register()


def unregister():
    for module in reversed(MODULES):
        module.unregister()
