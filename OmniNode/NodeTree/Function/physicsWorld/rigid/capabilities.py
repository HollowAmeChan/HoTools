"""Rigid/Jolt 领域能力声明。

这些表由刚体解算器子模块持有。外部 UI 或属性存储可以适配它们，但解算器
契约不应由面板模块或 Jolt 枚举名来定义。
"""

from __future__ import annotations

from .names import (
    RIGID_BODY_COMMANDS_CHANNEL,
    RIGID_GENERATED_CONSTRAINT_OBJECT_TAG,
    RIGID_JOLT_WORLD_SETTING_OBJECT_TAG,
)


RIGID_BODY_CAPABILITY_ID = "rigid_body"
RIGID_CONSTRAINT_CAPABILITY_ID = "rigid_constraint"
RIGID_JOLT_WORLD_SETTING_CAPABILITY_ID = "rigid_jolt_world_setting"
RIGID_BODY_COMMAND_CAPABILITY_ID = "rigid_body_command"


RIGID_BODY_CAPABILITY = {
    "capability_id": RIGID_BODY_CAPABILITY_ID,
    "display_name": "刚体",
    "semantic_owner": "physicsWorld/rigid 解算器能力声明",
    "legacy_explicit_storage": "Object.hotools_rigid_body",
    "fields": [
        {"name": "enabled", "type": "bool", "default": False, "update_policy": "每帧收集规格"},
        {"name": "body_type", "type": "enum", "values": ["STATIC", "DYNAMIC", "KINEMATIC"], "default": "DYNAMIC", "update_policy": "规格签名"},
        {"name": "mass", "type": "float", "default": 1.0, "update_policy": "规格签名"},
        {"name": "friction", "type": "float", "default": 0.5, "update_policy": "运行时命令或规格签名"},
        {"name": "restitution", "type": "float", "default": 0.0, "update_policy": "运行时命令或规格签名"},
        {"name": "rigid_collision_group", "type": "int", "default": 1, "update_policy": "规格签名"},
        {"name": "rigid_collides_with_groups", "type": "bitmask", "default": 0, "update_policy": "规格签名"},
        {"name": "shape_type", "type": "enum", "update_policy": "规格签名"},
        {"name": "shape_offset", "type": "float3", "default": (0.0, 0.0, 0.0), "update_policy": "规格签名"},
        {"name": "shape_rotation", "type": "float3", "default": (0.0, 0.0, 0.0), "update_policy": "规格签名"},
        {"name": "linear_velocity", "type": "float3", "default": (0.0, 0.0, 0.0), "update_policy": "初始值或命令"},
        {"name": "angular_velocity", "type": "float3", "default": (0.0, 0.0, 0.0), "update_policy": "初始值或命令"},
        {"name": "linear_damping", "type": "float", "default": 0.05, "update_policy": "规格签名"},
        {"name": "angular_damping", "type": "float", "default": 0.05, "update_policy": "规格签名"},
        {"name": "gravity_factor", "type": "float", "default": 1.0, "update_policy": "运行时命令或规格签名"},
        {"name": "allow_sleeping", "type": "bool", "default": True, "update_policy": "规格签名"},
        {"name": "motion_quality", "type": "enum", "values": ["DISCRETE", "CCD"], "default": "DISCRETE", "update_policy": "运行时命令或规格签名"},
        {"name": "is_sensor", "type": "bool", "default": False, "update_policy": "规格签名"},
        {"name": "axis_locks", "type": "dof_mask", "default": "全部解锁", "update_policy": "规格签名"},
    ],
}


RIGID_CONSTRAINT_CAPABILITY = {
    "capability_id": RIGID_CONSTRAINT_CAPABILITY_ID,
    "display_name": "刚体约束",
    "semantic_owner": "physicsWorld/rigid 解算器能力声明",
    "legacy_explicit_storage": "Object.hotools_rigid_constraint",
    "implicit_object_tag": RIGID_GENERATED_CONSTRAINT_OBJECT_TAG,
    "fields": [
        {"name": "enabled", "type": "bool", "default": False, "update_policy": "每帧收集规格"},
        {"name": "constraint_type", "type": "enum", "values": ["FIXED", "HINGE", "SLIDER", "CONE", "POINT"], "update_policy": "规格签名"},
        {"name": "target_a", "type": "Object", "update_policy": "规格签名"},
        {"name": "target_b", "type": "Object", "update_policy": "规格签名"},
        {"name": "disable_collisions", "type": "bool", "default": False, "update_policy": "规格签名"},
        {"name": "solver_velocity_steps_override", "type": "int", "default": 0, "update_policy": "规格签名"},
        {"name": "solver_position_steps_override", "type": "int", "default": 0, "update_policy": "规格签名"},
        {"name": "limit", "type": "constraint_limit", "update_policy": "规格签名"},
        {"name": "spring", "type": "constraint_spring", "update_policy": "规格签名"},
        {"name": "motor", "type": "constraint_motor", "update_policy": "规格签名"},
    ],
}


RIGID_JOLT_WORLD_SETTING_CAPABILITY = {
    "capability_id": RIGID_JOLT_WORLD_SETTING_CAPABILITY_ID,
    "display_name": "Jolt 刚体世界设置",
    "semantic_owner": "physicsWorld/rigid 解算器能力声明",
    "implicit_object_tag": RIGID_JOLT_WORLD_SETTING_OBJECT_TAG,
    "fields": [
        {"name": "gravity", "type": "float3", "default": (0.0, 0.0, -9.81), "update_policy": "隐式对象签名"},
        {"name": "max_bodies", "type": "int", "default": 1024, "update_policy": "适配器重建"},
        {"name": "max_body_pairs", "type": "int", "default": 4096, "update_policy": "适配器重建"},
        {"name": "max_contact_constraints", "type": "int", "default": 2048, "update_policy": "适配器重建"},
    ],
}


RIGID_BODY_COMMAND_CAPABILITY = {
    "capability_id": RIGID_BODY_COMMAND_CAPABILITY_ID,
    "display_name": "刚体运行时命令",
    "semantic_owner": "physicsWorld/rigid 解算器交换通道能力声明",
    "exchange_channel": RIGID_BODY_COMMANDS_CHANNEL,
    "commands": [
        "设置速度",
        "施加力",
        "施加冲量",
        "设置重力倍率",
        "设置材质响应",
        "设置运动质量",
        "设置激活状态",
    ],
    "update_policy": "按代次/帧令牌单次消费",
}


RIGID_CAPABILITIES = {
    RIGID_BODY_CAPABILITY_ID: RIGID_BODY_CAPABILITY,
    RIGID_CONSTRAINT_CAPABILITY_ID: RIGID_CONSTRAINT_CAPABILITY,
    RIGID_JOLT_WORLD_SETTING_CAPABILITY_ID: RIGID_JOLT_WORLD_SETTING_CAPABILITY,
    RIGID_BODY_COMMAND_CAPABILITY_ID: RIGID_BODY_COMMAND_CAPABILITY,
}


RIGID_UPDATE_FREQUENCY_TABLE = [
    {"data": "帧号 / dt", "source": "PhysicsWorldCache.frame_context", "policy": "每帧更新"},
    {"data": "刚体规格", "source": "Object.hotools_rigid_body -> RigidBodySpec", "policy": "签名变化时更新"},
    {"data": "约束规格", "source": "Object.hotools_rigid_constraint / generated constraint -> ConstraintSpec", "policy": "签名变化时更新"},
    {"data": "Jolt 世界设置", "source": f'world.implicit_objects["{RIGID_JOLT_WORLD_SETTING_OBJECT_TAG}"]', "policy": "隐式对象签名变化时更新"},
    {"data": "运动学刚体变换", "source": "RigidBodySpec 世界变换快照", "policy": "每帧同步；同帧不推进时间"},
    {"data": "刚体运行时命令", "source": f'world.exchange["{RIGID_BODY_COMMANDS_CHANNEL}"]', "policy": "按代次/帧令牌单次消费"},
    {"data": "原生 Jolt 世界", "source": "world.backend_resources", "policy": "持续到 world dispose 或容量配置变化"},
    {"data": "刚体/约束句柄", "source": "解算器槽位私有状态", "policy": "持续到槽位被裁剪或签名变化"},
    {"data": "刚体变换结果", "source": "Jolt 适配器读回", "policy": "每次模拟步产生；同帧可重发缓存结果"},
]
