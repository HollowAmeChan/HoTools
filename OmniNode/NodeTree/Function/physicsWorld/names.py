"""统一物理世界公开名称常量。"""

from __future__ import annotations

from importlib import import_module

# 解算器 id、结果通道、交换通道、后端资源 key、槽位类型
# 和 world.implicit_objects 标签都集中在这里，避免跨模块识别名称写散后错位。


# ---- 通用写回结果通道 ---------------------------------------------------
#
# 解算器只发布写回指令；Object/PoseBone/GN 属性的实际 Blender 写入统一由
# physicsWorld.writeback 执行。
RIGID_BODY_DELTA_CHANNEL = "rigid_body_delta"
BONE_TRANSFORM_CHANNEL = "bone_transform"
GN_ATTRIBUTE_CHANNEL = "gn_attribute"
GN_OFFSET_ATTRIBUTE_NAME = "hotools_physics_offset"
GN_OFFSET_MODIFIER_NAME = "HoTools 物理后置位移"
GN_OFFSET_NODE_GROUP_NAME = "HoTools_PhysicsOffset"
GN_OFFSET_WRITEBACK_TYPE = "mesh_vertex_offset"
GN_OFFSET_SPACE = "OBJECT_LOCAL"

# ---- SpringBone VRM -----------------------------------------------------
#
# 兼容惰性重导出。SpringBone 的名称权威定义位于 spring_vrm/names.py。
_COLLISION_COMPAT_NAMES = {
    "BONE_COLLISION_OVERRIDE_OBJECT_TAG",
}


_SPRING_VRM_COMPAT_NAMES = {
    "SPRING_VRM_POSE_CHANNEL",
    "SPRING_VRM_SLOT_KIND",
    "SPRING_VRM_SOLVER_ID",
    "SPRING_VRM_STATS_CHANNEL",
    "SPRING_VRM_STEP_WRITER_ID",
}


_RIGID_COMPAT_NAMES = {
    "JOLT_STEP_WRITER_ID",
    "RIGID_BACKEND_RESOURCE_KEY",
    "RIGID_BODY_COMMANDS_CHANNEL",
    "RIGID_BODY_REGISTER_WRITER_ID",
    "RIGID_BODY_SLOT_KIND",
    "RIGID_CONSTRAINT_REGISTER_WRITER_ID",
    "RIGID_CONSTRAINT_STATE_CHANNEL",
    "RIGID_CONTACT_EVENT_CHANNEL",
    "RIGID_CONSTRAINT_SLOT_KIND",
    "RIGID_DEBUG_DRAW_MODE",
    "RIGID_GENERATED_CONSTRAINT_OBJECT_TAG",
    "RIGID_JOLT_WORLD_SETTING_OBJECT_TAG",
    "RIGID_MATERIAL_PRESET_OBJECT_TAG",
    "RIGID_RAGDOLL_PROXY_OBJECT_TAG",
    "RIGID_SOLVER_ID",
    "RIGID_SOLVER_STATS_CHANNEL",
    "RIGID_SENSOR_EVENT_CHANNEL",
    "RIGID_QUERY_RESULT_CHANNEL",
    "RIGID_TRANSFORM_CHANNEL",
    "RIGID_QUERY_WRITER_ID",
}


def __getattr__(name: str):
    if name in _COLLISION_COMPAT_NAMES:
        module = import_module(".collision.names", __package__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in _SPRING_VRM_COMPAT_NAMES:
        module = import_module(".spring_vrm.names", __package__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in _RIGID_COMPAT_NAMES:
        module = import_module(".rigid.names", __package__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(name)


# ---- 刚体 / Jolt --------------------------------------------------------

# ---- 碰撞体原生 ABI -----------------------------------------------------

COLLIDER_TYPE_SPHERE = 0
COLLIDER_TYPE_CAPSULE = 1
COLLIDER_TYPE_PLANE = 2
COLLIDER_TYPE_BOX = 3
