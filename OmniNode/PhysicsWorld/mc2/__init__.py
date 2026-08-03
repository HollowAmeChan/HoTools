"""Physics World MC2 solver 注册清单。

公开行为属于显式子模块；包根不重导出 solver API。
"""


SOLVER_MODULE = {
    "domain": "mc2",
    "solver_id": "mc2",
    "menu_name": "MC2",
    "declaration": ".declaration:MC2_SOLVER_DECLARATION",
    "nodes": (".nodes",),
    "capabilities": ".capabilities:MC2_CAPABILITIES",
    "debug_draw_modes": ".debug:MC2_DEBUG_DRAW_MODES",
    "scope_restart_handlers": (
        ".setups.bone_frame_input:clear_mc2_bone_frame_state",
    ),
    "world_replace_handlers": (
        ".setups.bone_frame_input:carry_mc2_bone_frame_state",
    ),
    "blender_lifecycle": ".source_observation_blender",
    "world_dispose_handlers": (
        ".debug_draw:dispose_mc2_debug_draw_for_world",
    ),
}


__all__ = ["SOLVER_MODULE"]
