"""统一物理世界公开名称常量。"""

from __future__ import annotations

from importlib import import_module

# solver id、result channel、exchange channel、backend resource key、slot kind
# 和 world.implicit_objects tag 都集中在这里，避免跨模块识别名称写散后错位。


# ---- SpringBone VRM -----------------------------------------------------
#
# 兼容惰性重导出。SpringBone 的名称权威定义位于 spring_vrm/names.py。
_SPRING_VRM_COMPAT_NAMES = {
    "BONE_COLLISION_OVERRIDE_OBJECT_TAG",
    "SPRING_VRM_CHAIN_OBJECT_TAG",
    "SPRING_VRM_POSE_CHANNEL",
    "SPRING_VRM_SLOT_KIND",
    "SPRING_VRM_SOLVER_ID",
    "SPRING_VRM_STATS_CHANNEL",
    "SPRING_VRM_STEP_WRITER_ID",
}


def __getattr__(name: str):
    if name in _SPRING_VRM_COMPAT_NAMES:
        module = import_module(".spring_vrm.names", __package__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(name)


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

# 刚体生成/批处理节点写入 world.implicit_objects 的全局 tag。
#
# rigid.generated_constraint 已由刚体 solver 消费；其它 tag 仍只在声明里占位，
# 避免后续命名分叉。
RIGID_GENERATED_CONSTRAINT_OBJECT_TAG = "rigid.generated_constraint"
RIGID_JOLT_WORLD_SETTING_OBJECT_TAG = "rigid_jolt.world_setting"
RIGID_MATERIAL_PRESET_OBJECT_TAG = "rigid.material_preset"
RIGID_RAGDOLL_PROXY_OBJECT_TAG = "rigid.ragdoll_proxy"


# ---- Collider native ABI -----------------------------------------------

COLLIDER_TYPE_SPHERE = 0
COLLIDER_TYPE_CAPSULE = 1
COLLIDER_TYPE_PLANE = 2
COLLIDER_TYPE_BOX = 3
