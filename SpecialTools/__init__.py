from . import compositor_node_ir, geometry_node_ir, material_node_ir, object_scene_ir


MODULES = (
    material_node_ir,
    object_scene_ir,
    geometry_node_ir,
    compositor_node_ir,
)


def register():
    for module in MODULES:
        module.register()


def unregister():
    for module in reversed(MODULES):
        module.unregister()
