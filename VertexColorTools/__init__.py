from . import bake_normal, ops_base, ops_templates, ops_utils, panel, properties, sync


MODULES = (
    properties,
    sync,
    ops_base,
    ops_templates,
    ops_utils,
    bake_normal,
    panel,
)


def register():
    for module in MODULES:
        module.register()


def unregister():
    for module in reversed(MODULES):
        module.unregister()
