from . import material_node_ir, object_scene_ir


MODULES = (
    material_node_ir,
    object_scene_ir,
)


def register():
    for module in MODULES:
        module.register()


def unregister():
    for module in reversed(MODULES):
        module.unregister()
