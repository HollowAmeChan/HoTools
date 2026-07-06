"""统一物理世界公开名称常量。"""

# solver id、result channel、exchange channel、backend resource key、slot kind 和
# world.implicit_objects tag 都集中在这里，避免跨模块识别名称写散后错位。

# ---- SpringBone VRM -----------------------------------------------------

SPRING_VRM_SOLVER_ID = "spring_vrm"
SPRING_VRM_STEP_WRITER_ID = "spring_vrm_step"
SPRING_VRM_SLOT_KIND = "spring_vrm"
SPRING_VRM_POSE_CHANNEL = "spring_vrm_pose"
SPRING_VRM_STATS_CHANNEL = "spring_vrm_stats"
SPRING_VRM_CHAIN_OBJECT_TAG = "spring_vrm.chain"


# ---- Rigid / Jolt -------------------------------------------------------

RIGID_SOLVER_ID = "rigid_jolt"
RIGID_BODY_SLOT_KIND = "rigid_body"
RIGID_CONSTRAINT_SLOT_KIND = "rigid_constraint"
RIGID_BACKEND_RESOURCE_KEY = "rigid_solver"
RIGID_TRANSFORM_CHANNEL = "rigid_transform"
RIGID_SOLVER_STATS_CHANNEL = "rigid_solver_stats"
RIGID_BODY_COMMANDS_CHANNEL = "rigid_body_commands"

RIGID_BODY_REGISTER_WRITER_ID = "rigid_body_solver"
RIGID_CONSTRAINT_REGISTER_WRITER_ID = "constraint_solver"
JOLT_STEP_WRITER_ID = "jolt_step"
