"""刚体/Jolt 解算器自有名称。"""

RIGID_SOLVER_ID = "rigid_jolt"
RIGID_BODY_SLOT_KIND = "rigid_body"
RIGID_CONSTRAINT_SLOT_KIND = "rigid_constraint"
RIGID_BACKEND_RESOURCE_KEY = "rigid_solver"
RIGID_TRANSFORM_CHANNEL = "rigid_transform"
RIGID_CONSTRAINT_STATE_CHANNEL = "rigid_constraint_state"
RIGID_SOLVER_STATS_CHANNEL = "rigid_solver_stats"
RIGID_BODY_COMMANDS_CHANNEL = "rigid_body_commands"

RIGID_BODY_REGISTER_WRITER_ID = "rigid_body_solver"
RIGID_CONSTRAINT_REGISTER_WRITER_ID = "constraint_solver"
JOLT_STEP_WRITER_ID = "jolt_step"

RIGID_GENERATED_CONSTRAINT_OBJECT_TAG = "rigid.generated_constraint"
RIGID_JOLT_WORLD_SETTING_OBJECT_TAG = "rigid_jolt.world_setting"
RIGID_MATERIAL_PRESET_OBJECT_TAG = "rigid.material_preset"
RIGID_RAGDOLL_PROXY_OBJECT_TAG = "rigid.ragdoll_proxy"

RIGID_DEBUG_DRAW_MODE = "rigid_jolt.debug"
