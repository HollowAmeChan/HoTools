"""Physics World MC2 solver 注册清单。

公开行为属于显式子模块；包根不重导出 solver API。
"""


COMPONENT_MODULE = {
    "component_id": "mc2",
    "kind": "solver_adapter",
    "depends_on": ("collision",),
    "capabilities": ".setups.mesh_cloth.capabilities:MESH_CLOTH_CAPABILITIES",
    "blender_properties": ".setups.mesh_cloth.properties:MESH_CLOTH_BLENDER_PROPERTIES",
}


SOLVER_MODULE = {
    "domain": "mc2",
    "solver_id": "mc2",
    "menu_name": "MC2",
    "declaration": ".declaration:MC2_SOLVER_DECLARATION",
    "nodes": (".nodes",),
    "capabilities": ".capabilities:MC2_CAPABILITIES",
    "debug_draw_modes": ".debug:MC2_DEBUG_DRAW_MODES",
    "blender_lifecycle": ".source_observation_blender",
    "world_dispose_handlers": (
        ".debug_draw:dispose_mc2_debug_draw_for_world",
    ),
}


__all__ = ["COMPONENT_MODULE", "SOLVER_MODULE"]
