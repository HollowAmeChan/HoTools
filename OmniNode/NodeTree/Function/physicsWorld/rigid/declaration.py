"""刚体/Jolt 解算器声明。"""

from __future__ import annotations

from .capabilities import RIGID_CAPABILITIES, RIGID_UPDATE_FREQUENCY_TABLE
from .debug import RIGID_DEBUG_DRAW_MODES
from .names import (
    JOLT_STEP_WRITER_ID,
    RIGID_BACKEND_RESOURCE_KEY,
    RIGID_BODY_COMMANDS_CHANNEL,
    RIGID_BODY_REGISTER_WRITER_ID,
    RIGID_BODY_SLOT_KIND,
    RIGID_CONSTRAINT_REGISTER_WRITER_ID,
    RIGID_CONTACT_EVENT_CHANNEL,
    RIGID_CONSTRAINT_STATE_CHANNEL,
    RIGID_CONSTRAINT_SLOT_KIND,
    RIGID_GENERATED_CONSTRAINT_OBJECT_TAG,
    RIGID_JOLT_WORLD_SETTING_OBJECT_TAG,
    RIGID_MATERIAL_PRESET_OBJECT_TAG,
    RIGID_QUERY_RESULT_CHANNEL,
    RIGID_QUERY_WRITER_ID,
    RIGID_RAGDOLL_PROXY_OBJECT_TAG,
    RIGID_SOLVER_ID,
    RIGID_SENSOR_EVENT_CHANNEL,
    RIGID_SOLVER_STATS_CHANNEL,
    RIGID_TRANSFORM_CHANNEL,
)


RIGID_SOLVER_DECLARATION = {
    "solver_id": RIGID_SOLVER_ID,
    "slot_kind": [RIGID_BODY_SLOT_KIND, RIGID_CONSTRAINT_SLOT_KIND],
    "stage": "Jolt 刚体纵向切片",
    "native_strategy": "Jolt 后端 + Python 世界胶水层",
    "nodes": [
        "刚体模拟步",
        "刚体结果-读取状态",
        "刚体约束结果-读取状态",
        "Jolt刚体可视化调试",
        "刚体查询-RayCast",
        "刚体世界-Jolt设置属性",
        "刚体世界-Jolt设置注册",
        "刚体生成约束属性",
        "刚体生成约束注册",
        "刚体命令-设置速度",
        "刚体命令-施加力",
        "刚体命令-施加冲量",
        "刚体命令-重力倍率",
        "刚体命令-材质响应",
        "刚体命令-运动质量",
        "刚体命令-激活状态",
    ],
    "planned_nodes": [
        "刚体查询-ShapeCast",
        "刚体隐式材质预设注册",
        "刚体Ragdoll代理注册",
    ],
    "writers": [
        RIGID_BODY_REGISTER_WRITER_ID,
        RIGID_CONSTRAINT_REGISTER_WRITER_ID,
        JOLT_STEP_WRITER_ID,
        RIGID_QUERY_WRITER_ID,
    ],
    "consumes": [
        "PhysicsWorldCache.frame_context",
        "来自解算器槽位的 RigidBodySpec",
        "来自解算器槽位的 ConstraintSpec",
        f'world.implicit_objects["{RIGID_JOLT_WORLD_SETTING_OBJECT_TAG}"]',
        f'world.implicit_objects["{RIGID_GENERATED_CONSTRAINT_OBJECT_TAG}"]',
        f'world.exchange["{RIGID_BODY_COMMANDS_CHANNEL}"]',
    ],
    "produces": [
        f'world.result_streams["{RIGID_TRANSFORM_CHANNEL}"]',
        f'world.result_streams["{RIGID_CONSTRAINT_STATE_CHANNEL}"]',
        f'world.result_streams["{RIGID_CONTACT_EVENT_CHANNEL}"]',
        f'world.result_streams["{RIGID_SENSOR_EVENT_CHANNEL}"]',
        f'world.result_streams["{RIGID_QUERY_RESULT_CHANNEL}"]',
        f'world.result_streams["{RIGID_SOLVER_STATS_CHANNEL}"]',
    ],
    "persistent_state": [
        f'world.backend_resources["{RIGID_BACKEND_RESOURCE_KEY}"]',
        "slot.data.spec",
        "slot.data._jolt_generation",
        "slot.data._jolt_kinematic_pose_dirty",
        "constraint slot.data._jolt_broken / _jolt_breaking_impulse",
    ],
    "dirty_keys": [
        "world.generation",
        "frame_context.restart_required",
        "RigidBodySpec.signature",
        "ConstraintSpec.signature",
        f'world.implicit_objects["{RIGID_JOLT_WORLD_SETTING_OBJECT_TAG}"].signature',
        f'world.implicit_objects["{RIGID_GENERATED_CONSTRAINT_OBJECT_TAG}"].signature',
        f'world.exchange["{RIGID_BODY_COMMANDS_CHANNEL}"]',
    ],
    "same_frame_policy": "同步待处理变化或重发缓存变换，不重复推进时间",
    "update_policy": {
        "body_spec": "generation 或签名变化时同步到 Jolt",
        "constraint_spec": "generation 或签名变化时同步到 Jolt",
        "breakable_constraint": "每次真实 Jolt step 后按 lambda_max_abs 与冲量阈值判定；same-frame 不重复判定",
        "contact_events": "native callback 只缓存数值快照；每次真实 step 发布，same-frame 重发上一快照",
        "queries": "节点执行时查询当前 Jolt world，不推进时间；native handle 在 adapter 内转换为 slot_id",
        "kinematic_pose": "同帧请求时只更新运动学姿态，不推进时间",
        "jolt_world_settings": "按隐式对象签名同步到 Jolt 适配器",
        "commands": "按代次/帧令牌单次消费",
        "same_frame": "没有待同步变化时重发缓存变换，不推进时间",
    },
    "capabilities": RIGID_CAPABILITIES,
    "update_frequency_table": RIGID_UPDATE_FREQUENCY_TABLE,
    "implicit_objects": {
        "consumes": [
            RIGID_JOLT_WORLD_SETTING_OBJECT_TAG,
            RIGID_GENERATED_CONSTRAINT_OBJECT_TAG,
        ],
        "planned": [
            RIGID_MATERIAL_PRESET_OBJECT_TAG,
            RIGID_RAGDOLL_PROXY_OBJECT_TAG,
        ],
        "entry_kind": "刚体生成对象或 Jolt 世界设置",
        "producer_nodes": ["刚体世界-Jolt设置注册", "刚体生成约束注册"],
        "planned_producer_nodes": ["刚体隐式材质预设注册", "刚体Ragdoll代理注册"],
        "update_policy": "按标签 / stable_id / 签名懒更新",
        "conflict_policy": "相同标签和 stable_id 时后写覆盖先写",
    },
    "writeback": {
        "owner": "physicsWorld.writeback",
        "target": "Object.delta_transform",
        "solver_inline_writeback": False,
        "update_tag_owner": "writeback.apply",
    },
    "export": {
        "result_channels": [
            RIGID_TRANSFORM_CHANNEL,
            RIGID_CONSTRAINT_STATE_CHANNEL,
            RIGID_CONTACT_EVENT_CHANNEL,
            RIGID_SENSOR_EVENT_CHANNEL,
            RIGID_QUERY_RESULT_CHANNEL,
            RIGID_SOLVER_STATS_CHANNEL,
        ],
        "supports_bake": False,
    },
    "legacy_policy": "只支持新物理世界路径，不提供旧实现兼容层",
}


RIGID_JOLT_CAPABILITY_BACKLOG = [
    {
        "capability": "接触监听",
        "status": "已接",
        "boundary": "原生事件快照写入 world.result_streams/exchange；回调内不访问 Blender",
    },
    {
        "capability": "查询 API",
        "status": "部分接入：RayCast closest hit",
        "boundary": "函数节点发布普通查询结果；ShapeCast/overlap 仍计划中",
    },
    {
        "capability": "约束 lambda 与断裂策略",
        "status": "已接",
        "boundary": "由适配器读回结果；断裂策略负责禁用或移除命令",
    },
    {
        "capability": "约束语义调试绘制",
        "status": "已接八种显式类型；运行时 frame readback 待接",
        "boundary": "当前 frame/limit 使用 adapter 实际消费的 ConstraintSpec，current value/lambda 使用 result stream；后续 native readback 当前 A/B world frame",
    },
    {
        "capability": "高级约束类型",
        "status": "SwingTwist 已接限制、摩擦与双 motor；SixDOF 已接基础六轴模式，逐轴 motor/friction 待接；Path/Gear/RackAndPinion/Pulley 计划中",
        "boundary": "每种类型同时补 spec、binding、result、专用 renderer、用户文档和测试",
    },
    {
        "capability": "高级形状",
        "status": "计划中",
        "boundary": "先定义 HoTools 规格；Jolt 形状句柄继续保持后端私有",
    },
]


def rigid_declaration_debug_dict() -> dict:
    return {
        "declaration": dict(RIGID_SOLVER_DECLARATION),
        "capability_ids": list(RIGID_CAPABILITIES.keys()),
        "debug_draw_modes": dict(RIGID_DEBUG_DRAW_MODES),
        "update_frequency_count": len(RIGID_UPDATE_FREQUENCY_TABLE),
        "jolt_capability_backlog": [dict(item) for item in RIGID_JOLT_CAPABILITY_BACKLOG],
    }
