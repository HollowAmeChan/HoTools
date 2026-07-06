"""
physicsWorld.rigid.nodes — 刚体 domain 节点定义（Phase 5）

刚体和约束 spec 由 physicsWorldBegin 自动从 scope 收集。
physicsRigidSolver 节点只执行 Jolt 模拟步，写回由下游物理写回节点统一处理。
"""

import bpy
import mathutils

from ....FunctionNodeCore import omni
from ... import _Color
from ..types import PhysicsWorldCache
from .solver import RIGID_BODY_COMMANDS_CHANNEL, step_rigid_bodies
from .specs import build_rigid_body_spec


def _vec3(value, fallback=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    try:
        vec = mathutils.Vector(value)
    except Exception:
        return tuple(float(v) for v in fallback)
    if len(vec) == 0:
        return tuple(float(v) for v in fallback)
    if len(vec) == 1:
        return (float(vec[0]), float(fallback[1]), float(fallback[2]))
    if len(vec) == 2:
        return (float(vec[0]), float(vec[1]), float(fallback[2]))
    vec = vec.to_3d()
    return (float(vec.x), float(vec.y), float(vec.z))


def _publish_rigid_body_command(
    world: object,
    target: bpy.types.Object,
    command: str,
    enabled: bool = True,
    producer: str = "physicsRigidCommand",
    **payload,
) -> tuple[object, object]:
    if not bool(enabled) or not isinstance(world, PhysicsWorldCache):
        return world, None

    spec = build_rigid_body_spec(target)
    if spec is None:
        return world, None
    slot = world.solver_slots.get(spec.slot_id)
    if slot is None or slot.kind != "rigid_body":
        return world, None

    item = {
        "channel": RIGID_BODY_COMMANDS_CHANNEL,
        "producer": producer,
        "scope": "frame",
        "target_slot_id": spec.slot_id,
        "target_object": getattr(target, "name", ""),
        "command": str(command),
    }
    item.update(payload)
    publish = getattr(world, "publish_exchange", None)
    if callable(publish):
        return world, publish(item)
    return world, None


@omni(
    enable=True,
    always_run=True,   # 物理解算器，每个新帧必须推进 Jolt state
    bl_label="刚体模拟步",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "启用"],
    _OUTPUT_NAME=["物理世界", "刚体数量", "耗时ms"],
    omni_description="""
    执行 Jolt 刚体模拟步，结果保留在 rigid backend 中。

    刚体/约束 spec 已由"物理世界-帧开始"自动收集，无需手动注册节点。

    执行流程：
    1. 获取或创建 JoltAdapter（首帧编译 hotools_jolt 模块未找到时节点静默跳过）。
    2. 首帧或 generation 变化时把 spec 同步到 Jolt（add_body / add_constraint）。
    3. KINEMATIC 刚体每帧跟随 Blender 动画位置。
    4. 新帧执行 Jolt step（dt 和 substeps 来自物理世界帧上下文）。
    5. DYNAMIC 刚体写回由下游"物理写回"节点统一写入 Object.delta_*。

    hotools_jolt 未编译时透传 world，输出 (world, 0, 0.0)，不报错。
    """,
)
def physicsRigidSolver(
    world: object,
    enabled: bool = True,
) -> tuple[object, int, float]:
    body_count, step_ms = step_rigid_bodies(world, bool(enabled))
    return world, body_count, float(step_ms)


@omni(
    enable=True,
    always_run=True,
    bl_label="刚体命令-设置速度",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "目标刚体", "线速度", "角速度", "启用"],
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体速度命令。

    节点只写入 world.exchange 的 rigid_body_commands item，不直接访问 Jolt handle。
    将本节点放在"刚体模拟步"之前，solver 会在本帧同步 body 后应用速度。
    """,
)
def physicsRigidSetVelocity(
    world: object,
    target: bpy.types.Object,
    linear_velocity: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    angular_velocity: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    enabled: bool = True,
) -> tuple[object, object]:
    return _publish_rigid_body_command(
        world,
        target,
        "set_velocity",
        enabled,
        producer="physicsRigidSetVelocity",
        linear_velocity=_vec3(linear_velocity),
        angular_velocity=_vec3(angular_velocity),
    )


@omni(
    enable=True,
    always_run=True,
    bl_label="刚体命令-施加力",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "目标刚体", "力", "扭矩", "启用"],
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体 force / torque 命令。

    这是持续力；启用时每帧都会发布一次。需要脉冲式效果时请使用"刚体命令-施加冲量"。
    """,
)
def physicsRigidAddForce(
    world: object,
    target: bpy.types.Object,
    force: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    torque: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    enabled: bool = True,
) -> tuple[object, object]:
    return _publish_rigid_body_command(
        world,
        target,
        "add_force",
        enabled,
        producer="physicsRigidAddForce",
        force=_vec3(force),
        torque=_vec3(torque),
    )


@omni(
    enable=True,
    always_run=True,
    bl_label="刚体命令-施加冲量",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "目标刚体", "冲量", "角冲量", "启用"],
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体 impulse / angular impulse 命令。

    这是瞬时冲量；启用输入如果一直为 True，就会每帧发布一次。
    """,
)
def physicsRigidAddImpulse(
    world: object,
    target: bpy.types.Object,
    impulse: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    angular_impulse: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    enabled: bool = True,
) -> tuple[object, object]:
    return _publish_rigid_body_command(
        world,
        target,
        "add_impulse",
        enabled,
        producer="physicsRigidAddImpulse",
        impulse=_vec3(impulse),
        angular_impulse=_vec3(angular_impulse),
    )


@omni(
    enable=True,
    always_run=True,
    bl_label="刚体命令-重力倍率",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "目标刚体", "重力倍率", "启用"],
    input_init={"gravity_factor": {"min_value": -10.0, "max_value": 10.0}},
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体重力倍率命令。

    该命令用于运行中改变单个刚体受到的重力强度，不修改 HoTools 持久化属性。
    """,
)
def physicsRigidSetGravityFactor(
    world: object,
    target: bpy.types.Object,
    gravity_factor: float = 1.0,
    enabled: bool = True,
) -> tuple[object, object]:
    return _publish_rigid_body_command(
        world,
        target,
        "set_gravity_factor",
        enabled,
        producer="physicsRigidSetGravityFactor",
        gravity_factor=float(gravity_factor),
    )


@omni(
    enable=True,
    always_run=True,
    bl_label="刚体命令-材质响应",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "目标刚体", "摩擦", "弹性", "启用"],
    input_init={
        "friction": {"min_value": 0.0, "max_value": 1.0},
        "restitution": {"min_value": 0.0, "max_value": 1.0},
    },
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体材质响应命令。

    当前覆盖 friction / restitution。它是运行中命令，不修改 HoTools 持久化属性。
    """,
)
def physicsRigidSetMaterialResponse(
    world: object,
    target: bpy.types.Object,
    friction: float = 0.5,
    restitution: float = 0.0,
    enabled: bool = True,
) -> tuple[object, object]:
    friction = max(0.0, min(1.0, float(friction)))
    restitution = max(0.0, min(1.0, float(restitution)))
    return _publish_rigid_body_command(
        world,
        target,
        "set_material_response",
        enabled,
        producer="physicsRigidSetMaterialResponse",
        friction=friction,
        restitution=restitution,
    )


@omni(
    enable=True,
    always_run=True,
    bl_label="刚体命令-运动质量",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "目标刚体", "运动质量", "启用"],
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体运动质量命令。

    motion_quality 使用 DISCRETE 或 LINEAR_CAST；LINEAR_CAST 对高速刚体启用连续碰撞检测。
    """,
)
def physicsRigidSetMotionQuality(
    world: object,
    target: bpy.types.Object,
    motion_quality: str = "DISCRETE",
    enabled: bool = True,
) -> tuple[object, object]:
    quality = str(motion_quality or "DISCRETE").strip().upper()
    if quality not in {"DISCRETE", "LINEAR_CAST"}:
        quality = "DISCRETE"
    return _publish_rigid_body_command(
        world,
        target,
        "set_motion_quality",
        enabled,
        producer="physicsRigidSetMotionQuality",
        motion_quality=quality,
    )


@omni(
    enable=True,
    always_run=True,
    bl_label="刚体命令-激活状态",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "目标刚体", "激活", "启用"],
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体激活状态命令。

    可用于唤醒 sleeping body，或显式切换 active 状态。
    """,
)
def physicsRigidSetActive(
    world: object,
    target: bpy.types.Object,
    active: bool = True,
    enabled: bool = True,
) -> tuple[object, object]:
    return _publish_rigid_body_command(
        world,
        target,
        "set_active",
        enabled,
        producer="physicsRigidSetActive",
        active=bool(active),
    )
