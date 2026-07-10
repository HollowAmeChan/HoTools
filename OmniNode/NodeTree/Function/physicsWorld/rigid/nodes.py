"""
physicsWorld.rigid.nodes — 刚体 domain 节点定义（Phase 5）

刚体和约束 spec 由 physicsWorldBegin 自动从 scope 收集。
physicsRigidSolver 节点只执行 Jolt 模拟步，写回由下游物理写回节点统一处理。
"""

import bpy
import mathutils

from ....FunctionNodeCore import omni
from ... import _Color
from .names import (
    RIGID_BODY_COMMANDS_CHANNEL,
    RIGID_BODY_SLOT_KIND,
    RIGID_CONSTRAINT_SLOT_KIND,
)
from ..types import PhysicsWorldCache
from .debug_draw import update_rigid_debug_draw_store
from .implicit_objects import (
    DEFAULT_RIGID_JOLT_MAX_BODIES,
    DEFAULT_RIGID_JOLT_MAX_BODY_PAIRS,
    DEFAULT_RIGID_JOLT_MAX_CONTACT_CONSTRAINTS,
    make_rigid_generated_constraint_properties,
    make_rigid_jolt_world_setting_properties,
    register_rigid_generated_constraint_objects,
    register_rigid_jolt_world_setting_objects,
)
from .results import get_rigid_constraint_state_result, get_rigid_transform_result
from .queries import perform_rigid_ray_cast
from .solver import step_rigid_bodies
from .specs import build_constraint_spec, build_rigid_body_spec


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
    producer: str = "physicsRigidCommand",
    **payload,
) -> tuple[object, object]:
    if not isinstance(world, PhysicsWorldCache):
        return world, None

    spec = build_rigid_body_spec(target)
    if spec is None:
        return world, None
    slot = world.solver_slots.get(spec.slot_id)
    if slot is None or slot.kind != RIGID_BODY_SLOT_KIND:
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
    return world, world.publish_exchange(item)


def _rigid_result_for_target(world: object, target: bpy.types.Object) -> dict | None:
    if not isinstance(world, PhysicsWorldCache):
        return None
    spec = build_rigid_body_spec(target)
    if spec is None:
        return None
    slot = world.solver_slots.get(spec.slot_id)
    if slot is None or slot.kind != RIGID_BODY_SLOT_KIND:
        return None
    fc = getattr(world, "frame_context", None)
    frame = int(getattr(fc, "frame", 0) or 0)
    return get_rigid_transform_result(
        world,
        slot_id=spec.slot_id,
        frame=frame,
        generation=world.generation,
    )


def _rigid_constraint_result_for_target(
    world: object,
    target: bpy.types.Object,
) -> dict | None:
    if not isinstance(world, PhysicsWorldCache):
        return None
    spec = build_constraint_spec(target)
    if spec is None:
        return None
    slot = world.solver_slots.get(spec.slot_id)
    if slot is None or slot.kind != RIGID_CONSTRAINT_SLOT_KIND:
        return None
    fc = getattr(world, "frame_context", None)
    frame = int(getattr(fc, "frame", 0) or 0)
    return get_rigid_constraint_state_result(
        world,
        slot_id=spec.slot_id,
        frame=frame,
        generation=world.generation,
    )


def _rotation_euler_from_wxyz(value) -> mathutils.Vector:
    try:
        quat = mathutils.Quaternion((
            float(value[0]), float(value[1]), float(value[2]), float(value[3])
        ))
        euler = quat.to_euler("XYZ")
        return mathutils.Vector((float(euler.x), float(euler.y), float(euler.z)))
    except Exception:
        return mathutils.Vector((0.0, 0.0, 0.0))


@omni(
    enable=True,
    always_run=True,   # 物理解算器，每个新帧必须推进 Jolt state
    bl_label="刚体模拟步",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界"],
    _OUTPUT_NAME=["物理世界", "刚体数量", "耗时ms"],
    omni_description="""
    执行 Jolt 刚体模拟步，刚体与约束状态分别发布到
    world.result_streams["rigid_transform"] 和 ["rigid_constraint_state"]。

    刚体/约束 spec 已由"物理世界-帧开始"自动收集，无需手动注册节点。

    执行流程：
    1. 获取或创建 JoltAdapter（首帧编译 hotools_jolt 模块未找到时节点静默跳过）。
    2. 首帧或 generation 变化时把 spec 同步到 Jolt（add_body / add_constraint）。
    3. KINEMATIC 刚体每帧跟随 Blender 动画位置。
    4. 新帧执行 Jolt step（dt 和 substeps 来自物理世界帧上下文）。
    5. DYNAMIC 刚体写回由下游"物理写回"节点统一写入 Object.delta_*。

    hotools_jolt 未编译时透传 world，输出 (world, 0, 0.0)，不报错。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidSolver(
    world: object,
) -> tuple[object, int, float]:
    body_count, step_ms = step_rigid_bodies(world, True)
    return world, body_count, float(step_ms)


@omni(
    enable=True,
    always_run=True,
    bl_label="刚体结果-读取状态",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "目标刚体"],
    _OUTPUT_NAME=["物理世界", "命中", "位置", "旋转", "线速度", "角速度", "激活", "睡眠", "结果"],
    omni_description="""
    从 world result stream 读取目标刚体当前状态。

    该节点不访问 Jolt adapter、native handle 或 slot 私有 transform，只消费
    world.result_streams 中的 rigid_transform。应放在"刚体模拟步"之后；
    若本帧还没有结果，命中为 False，其余输出为默认值。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidReadState(
    world: object,
    target: bpy.types.Object,
) -> tuple[object, bool, mathutils.Vector, mathutils.Vector, mathutils.Vector, mathutils.Vector, bool, bool, object]:
    result = _rigid_result_for_target(world, target)
    if result is None:
        zero = mathutils.Vector((0.0, 0.0, 0.0))
        return world, False, zero.copy(), zero.copy(), zero.copy(), zero.copy(), False, False, None

    position = mathutils.Vector(_vec3(result.get("position")))
    rotation = _rotation_euler_from_wxyz(result.get("rotation_wxyz", (1.0, 0.0, 0.0, 0.0)))
    linear_velocity = mathutils.Vector(_vec3(result.get("linear_velocity")))
    angular_velocity = mathutils.Vector(_vec3(result.get("angular_velocity")))
    return (
        world,
        True,
        position,
        rotation,
        linear_velocity,
        angular_velocity,
        bool(result.get("active", False)),
        bool(result.get("sleeping", False)),
        result,
    )


@omni(
    enable=True,
    always_run=True,
    bl_label="刚体约束结果-读取状态",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "约束对象"],
    _OUTPUT_NAME=[
        "物理世界", "命中", "启用", "约束类型", "当前值类型", "当前值",
        "位置Lambda", "旋转Lambda", "限制Lambda", "Motor Lambda", "最大Lambda", "已断裂", "结果",
    ],
    omni_description="""
    从 rigid_constraint_state result stream 读取显式 Empty 约束当前状态。

    当前值对 Hinge 是角度、Slider 是位置、Distance 是锚点距离；lambda
    来自上一物理步，可用于调试和后续断裂策略。节点不访问 Jolt handle。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidConstraintReadState(
    world: object,
    target: bpy.types.Object,
) -> tuple[object, bool, bool, str, str, float, mathutils.Vector, mathutils.Vector, float, float, float, bool, object]:
    result = _rigid_constraint_result_for_target(world, target)
    if result is None:
        zero = mathutils.Vector((0.0, 0.0, 0.0))
        return world, False, False, "", "none", 0.0, zero.copy(), zero.copy(), 0.0, 0.0, 0.0, False, None

    return (
        world,
        True,
        bool(result.get("enabled", False)),
        str(result.get("constraint_type", "")),
        str(result.get("current_value_kind", "none")),
        float(result.get("current_value", 0.0) or 0.0),
        mathutils.Vector(_vec3(result.get("lambda_position"))),
        mathutils.Vector(_vec3(result.get("lambda_rotation"))),
        float(result.get("lambda_limit", 0.0) or 0.0),
        float(result.get("lambda_motor", 0.0) or 0.0),
        float(result.get("lambda_max_abs", 0.0) or 0.0),
        bool(result.get("broken", False)),
        result,
    )


@omni(
    enable=True,
    always_run=True,
    bl_label="Jolt刚体可视化调试",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "显示刚体", "显示约束", "显示问题", "显示接触", "显示传感器"],
    _OUTPUT_NAME=["物理世界"],
    omni_description="""
    刚体/Jolt 自有可视化调试节点。

    本节点从 rigid solver slot 与 result stream 采样纯线段快照，绘制刚体形状、
    生成约束、约束问题、接触点/法线和传感器事件。绘制语义归 rigid/Jolt
    domain 持有，不再走物理世界通用 debug draw。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidJoltDebugDraw(
    world: object,
    show_bodies: bool = True,
    show_constraints: bool = True,
    show_problems: bool = True,
    show_contacts: bool = True,
    show_sensors: bool = True,
) -> object:
    update_rigid_debug_draw_store(
        str(id(world)),
        world,
        True,
        bool(show_bodies),
        bool(show_constraints),
        bool(show_problems),
        bool(show_contacts),
        bool(show_sensors),
    )
    return world


@omni(
    enable=True,
    always_run=True,
    bl_label="刚体查询-RayCast",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "起点", "方向", "最大距离", "包含传感器", "忽略对象"],
    input_init={
        "origin": {"default_value": mathutils.Vector((0.0, 0.0, 0.0))},
        "direction": {"default_value": mathutils.Vector((0.0, 0.0, -1.0))},
        "max_distance": {"default_value": 100.0, "min_value": 0.0},
    },
    _OUTPUT_NAME=["物理世界", "命中", "命中对象", "位置", "法线", "距离", "比例", "传感器", "结果"],
    omni_description="""
    查询当前 Jolt 刚体世界中的最近射线命中。方向会归一化，最大距离决定线段长度。

    节点应放在"刚体模拟步"之后。可选择忽略一个刚体对象，并决定 sensor 是否参与
    命中。结果会发布到 rigid_query_result，且不包含 Jolt body handle。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidRayCast(
    world: object,
    origin: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    direction: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    max_distance: float = 100.0,
    include_sensors: bool = True,
    ignore_object: bpy.types.Object = None,
) -> tuple[object, bool, bpy.types.Object, mathutils.Vector, mathutils.Vector, float, float, bool, object]:
    result, hit_object = perform_rigid_ray_cast(
        world,
        origin=_vec3(origin),
        direction=_vec3(direction, (0.0, 0.0, -1.0)),
        max_distance=float(max_distance),
        include_sensors=bool(include_sensors),
        ignore_object=ignore_object,
    )
    return (
        world,
        bool(result.get("hit", False)),
        hit_object,
        mathutils.Vector(_vec3(result.get("position"))),
        mathutils.Vector(_vec3(result.get("normal"))),
        float(result.get("distance", 0.0) or 0.0),
        float(result.get("fraction", 1.0) or 0.0),
        bool(result.get("is_sensor", False)),
        result,
    )


@omni(
    enable=True,
    bl_label="刚体世界-Jolt设置属性",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["重力", "最大刚体数", "最大刚体对", "最大接触约束", "来源ID", "优先级"],
    input_init={
        "gravity": {"default_value": mathutils.Vector((0.0, 0.0, -9.81))},
        "max_bodies": {"default_value": DEFAULT_RIGID_JOLT_MAX_BODIES, "min_value": 1, "max_value": 1000000},
        "max_body_pairs": {"default_value": DEFAULT_RIGID_JOLT_MAX_BODY_PAIRS, "min_value": 1, "max_value": 4000000},
        "max_contact_constraints": {"default_value": DEFAULT_RIGID_JOLT_MAX_CONTACT_CONSTRAINTS, "min_value": 1, "max_value": 2000000},
        "priority": {"min_value": -255, "max_value": 255},
    },
    _OUTPUT_NAME=["Jolt刚体世界设置属性"],
    omni_description="""
    构造 Jolt 刚体世界级设置对象。当前落地项是 Jolt 刚体世界 gravity 和容量上限；
    对象本身不访问 Jolt，
    需要交给“刚体世界-Jolt设置注册”写入 world.implicit_objects。
    """,
)
def physicsRigidJoltWorldSettingsProperties(
    gravity: mathutils.Vector = mathutils.Vector((0.0, 0.0, -9.81)),
    max_bodies: int = DEFAULT_RIGID_JOLT_MAX_BODIES,
    max_body_pairs: int = DEFAULT_RIGID_JOLT_MAX_BODY_PAIRS,
    max_contact_constraints: int = DEFAULT_RIGID_JOLT_MAX_CONTACT_CONSTRAINTS,
    source_id: str = "default",
    priority: int = 0,
) -> list[object]:
    return make_rigid_jolt_world_setting_properties(
        gravity=_vec3(gravity, (0.0, 0.0, -9.81)),
        max_bodies=int(max_bodies),
        max_body_pairs=int(max_body_pairs),
        max_contact_constraints=int(max_contact_constraints),
        enabled=True,
        source_id=str(source_id or "default"),
        priority=int(priority),
    )


@omni(
    enable=True,
    bl_label="刚体世界-Jolt设置注册",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "Jolt刚体世界设置属性"],
    _OUTPUT_NAME=["物理世界", "对象数量", "变更数量", "版本"],
    omni_description="""
    把 Jolt 刚体世界级设置注册到 PhysicsWorldCache.implicit_objects。
    刚体模拟步会在同步 body/constraint 前读取 tag rigid_jolt.world_setting，并把 gravity 热更新到 Jolt adapter。
    容量上限是 JoltWorld 构造期参数；签名变化会触发 Jolt adapter 重建并重新同步刚体/约束。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidJoltWorldSettingsRegister(
    world: object,
    world_setting_properties: list[object],
) -> tuple[object, int, int, int]:
    if not isinstance(world, PhysicsWorldCache):
        return world, 0, 0, 0
    count, dirty_count, version = register_rigid_jolt_world_setting_objects(
        world,
        world_setting_properties,
        enabled=True,
    )
    return world, int(count), int(dirty_count), int(version)


@omni(
    enable=True,
    bl_label="刚体生成约束属性",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "目标A", "目标B", "锚点对象", "约束类型", "禁用连接碰撞", "来源ID",
        "优先级", "速度步数", "位置步数", "启用限制",
        "角度最小", "角度最大", "线性最小", "线性最大", "锥角",
        "摆动边界", "法向摆动半角", "平面摆动半角", "扭转最小", "扭转最大",
        "摆动Motor", "扭转Motor", "Motor频率", "Motor阻尼", "Motor扭矩限制",
        "摆动扭转目标角速度", "摆动扭转目标姿态",
        "SixDOF摆动边界",
        "平移X模式", "平移X最小", "平移X最大", "平移X摩擦力",
        "平移Y模式", "平移Y最小", "平移Y最大", "平移Y摩擦力",
        "平移Z模式", "平移Z最小", "平移Z最大", "平移Z摩擦力",
        "旋转X模式", "旋转X最小", "旋转X最大", "旋转X摩擦力矩",
        "旋转Y模式", "旋转Y最小", "旋转Y最大", "旋转Y摩擦力矩",
        "旋转Z模式", "旋转Z最小", "旋转Z最大", "旋转Z摩擦力矩",
        "距离最小", "距离最大", "可断裂", "断裂冲量阈值", "锚点对象A", "锚点对象B",
    ],
    input_init={
        "constraint_type": {"default_value": "FIXED"},
        "swing_type": {"default_value": "CONE"},
        "swing_motor_state": {"default_value": "OFF"},
        "twist_motor_state": {"default_value": "OFF"},
        "six_dof_swing_type": {"default_value": "PYRAMID"},
        "six_dof_translation_x_mode": {"default_value": "FIXED"},
        "six_dof_translation_y_mode": {"default_value": "FIXED"},
        "six_dof_translation_z_mode": {"default_value": "FIXED"},
        "six_dof_rotation_x_mode": {"default_value": "FIXED"},
        "six_dof_rotation_y_mode": {"default_value": "FIXED"},
        "six_dof_rotation_z_mode": {"default_value": "FIXED"},
        "constraint_priority": {"min_value": 0, "max_value": 255},
        "solver_velocity_steps": {"min_value": 0, "max_value": 255},
        "solver_position_steps": {"min_value": 0, "max_value": 255},
        "angular_limit_min": {"min_value": -3.141592653589793, "max_value": 0.0},
        "angular_limit_max": {"min_value": 0.0, "max_value": 3.141592653589793},
        "cone_half_angle": {"min_value": 0.0, "max_value": 3.141592653589793},
        "swing_normal_half_angle": {"min_value": 0.0, "max_value": 3.141592653589793},
        "swing_plane_half_angle": {"min_value": 0.0, "max_value": 3.141592653589793},
        "twist_min_angle": {"min_value": -3.141592653589793, "max_value": 3.141592653589793},
        "twist_max_angle": {"min_value": -3.141592653589793, "max_value": 3.141592653589793},
        "motor_frequency": {"min_value": 0.0},
        "motor_damping": {"min_value": 0.0},
        "motor_torque_limit": {"min_value": 0.0},
        "six_dof_rotation_x_min": {"min_value": -3.141592653589793, "max_value": 3.141592653589793},
        "six_dof_rotation_x_max": {"min_value": -3.141592653589793, "max_value": 3.141592653589793},
        "six_dof_rotation_y_min": {"min_value": -3.141592653589793, "max_value": 3.141592653589793},
        "six_dof_rotation_y_max": {"min_value": -3.141592653589793, "max_value": 3.141592653589793},
        "six_dof_rotation_z_min": {"min_value": -3.141592653589793, "max_value": 3.141592653589793},
        "six_dof_rotation_z_max": {"min_value": -3.141592653589793, "max_value": 3.141592653589793},
        "six_dof_translation_x_friction": {"min_value": 0.0},
        "six_dof_translation_y_friction": {"min_value": 0.0},
        "six_dof_translation_z_friction": {"min_value": 0.0},
        "six_dof_rotation_x_friction": {"min_value": 0.0},
        "six_dof_rotation_y_friction": {"min_value": 0.0},
        "six_dof_rotation_z_friction": {"min_value": 0.0},
    },
    _OUTPUT_NAME=["生成约束属性"],
    omni_description="""
    构造可注册到物理世界的刚体生成约束属性。

    本节点不创建 Empty、不写 solver slot、不访问 Jolt。约束类型使用
    FIXED / HINGE / SLIDER / CONE / POINT / DISTANCE / SWING_TWIST / SIX_DOF。锚点对象为空时，锚点位置取
    目标 A/B 的中点，旋转取目标 A 的 world rotation。锚点对象 A/B 可选，
    用于覆盖各自独立的世界 anchor frame。
    """,
)
def physicsRigidGeneratedConstraintProperties(
    target_a: bpy.types.Object,
    target_b: bpy.types.Object = None,
    anchor_object: bpy.types.Object = None,
    constraint_type: str = "FIXED",
    disable_collisions: bool = True,
    source_id: str = "",
    constraint_priority: int = 0,
    solver_velocity_steps: int = 0,
    solver_position_steps: int = 0,
    limit_enabled: bool = False,
    angular_limit_min: float = -3.141592653589793,
    angular_limit_max: float = 3.141592653589793,
    linear_limit_min: float = -1.0,
    linear_limit_max: float = 1.0,
    cone_half_angle: float = 0.0,
    swing_type: str = "CONE",
    swing_normal_half_angle: float = 0.7853981633974483,
    swing_plane_half_angle: float = 0.7853981633974483,
    twist_min_angle: float = -0.7853981633974483,
    twist_max_angle: float = 0.7853981633974483,
    swing_motor_state: str = "OFF",
    twist_motor_state: str = "OFF",
    motor_frequency: float = 2.0,
    motor_damping: float = 1.0,
    motor_torque_limit: float = 0.0,
    swing_twist_target_angular_velocity=(0.0, 0.0, 0.0),
    swing_twist_target_rotation=(0.0, 0.0, 0.0),
    six_dof_swing_type: str = "PYRAMID",
    six_dof_translation_x_mode: str = "FIXED",
    six_dof_translation_x_min: float = -1.0,
    six_dof_translation_x_max: float = 1.0,
    six_dof_translation_x_friction: float = 0.0,
    six_dof_translation_y_mode: str = "FIXED",
    six_dof_translation_y_min: float = -1.0,
    six_dof_translation_y_max: float = 1.0,
    six_dof_translation_y_friction: float = 0.0,
    six_dof_translation_z_mode: str = "FIXED",
    six_dof_translation_z_min: float = -1.0,
    six_dof_translation_z_max: float = 1.0,
    six_dof_translation_z_friction: float = 0.0,
    six_dof_rotation_x_mode: str = "FIXED",
    six_dof_rotation_x_min: float = -0.7853981633974483,
    six_dof_rotation_x_max: float = 0.7853981633974483,
    six_dof_rotation_x_friction: float = 0.0,
    six_dof_rotation_y_mode: str = "FIXED",
    six_dof_rotation_y_min: float = -0.7853981633974483,
    six_dof_rotation_y_max: float = 0.7853981633974483,
    six_dof_rotation_y_friction: float = 0.0,
    six_dof_rotation_z_mode: str = "FIXED",
    six_dof_rotation_z_min: float = -0.7853981633974483,
    six_dof_rotation_z_max: float = 0.7853981633974483,
    six_dof_rotation_z_friction: float = 0.0,
    distance_min: float = 0.0,
    distance_max: float = 1.0,
    breakable: bool = False,
    breaking_threshold: float = 1000.0,
    anchor_object_a: bpy.types.Object = None,
    anchor_object_b: bpy.types.Object = None,
) -> list[object]:
    return make_rigid_generated_constraint_properties(
        target_a=target_a,
        target_b=target_b,
        anchor_object=anchor_object,
        constraint_type=constraint_type,
        enabled=True,
        disable_collisions=bool(disable_collisions),
        source_id=str(source_id or ""),
        constraint_priority=int(constraint_priority),
        solver_velocity_steps=int(solver_velocity_steps),
        solver_position_steps=int(solver_position_steps),
        limit_enabled=bool(limit_enabled),
        angular_limit_min=float(angular_limit_min),
        angular_limit_max=float(angular_limit_max),
        linear_limit_min=float(linear_limit_min),
        linear_limit_max=float(linear_limit_max),
        cone_half_angle=float(cone_half_angle),
        swing_type=str(swing_type or "CONE"),
        swing_normal_half_angle=float(swing_normal_half_angle),
        swing_plane_half_angle=float(swing_plane_half_angle),
        twist_min_angle=float(twist_min_angle),
        twist_max_angle=float(twist_max_angle),
        swing_motor_state=str(swing_motor_state or "OFF"),
        twist_motor_state=str(twist_motor_state or "OFF"),
        motor_frequency=float(motor_frequency),
        motor_damping=float(motor_damping),
        motor_torque_limit=float(motor_torque_limit),
        swing_twist_target_angular_velocity=swing_twist_target_angular_velocity,
        swing_twist_target_rotation=swing_twist_target_rotation,
        six_dof_axis_modes=(
            str(six_dof_translation_x_mode or "FIXED"),
            str(six_dof_translation_y_mode or "FIXED"),
            str(six_dof_translation_z_mode or "FIXED"),
            str(six_dof_rotation_x_mode or "FIXED"),
            str(six_dof_rotation_y_mode or "FIXED"),
            str(six_dof_rotation_z_mode or "FIXED"),
        ),
        six_dof_limit_min=(
            float(six_dof_translation_x_min), float(six_dof_translation_y_min),
            float(six_dof_translation_z_min), float(six_dof_rotation_x_min),
            float(six_dof_rotation_y_min), float(six_dof_rotation_z_min),
        ),
        six_dof_limit_max=(
            float(six_dof_translation_x_max), float(six_dof_translation_y_max),
            float(six_dof_translation_z_max), float(six_dof_rotation_x_max),
            float(six_dof_rotation_y_max), float(six_dof_rotation_z_max),
        ),
        six_dof_swing_type=str(six_dof_swing_type or "PYRAMID"),
        six_dof_max_friction=(
            float(six_dof_translation_x_friction), float(six_dof_translation_y_friction),
            float(six_dof_translation_z_friction), float(six_dof_rotation_x_friction),
            float(six_dof_rotation_y_friction), float(six_dof_rotation_z_friction),
        ),
        distance_min=float(distance_min),
        distance_max=float(distance_max),
        breakable=bool(breakable),
        breaking_threshold=float(breaking_threshold),
        anchor_object_a=anchor_object_a,
        anchor_object_b=anchor_object_b,
    )


@omni(
    enable=True,
    bl_label="刚体生成约束注册",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "生成约束属性"],
    _OUTPUT_NAME=["物理世界", "对象数量", "变更数量", "版本"],
    omni_description="""
    把刚体生成约束注册到 PhysicsWorldCache.implicit_objects。

    注册结果使用 tag rigid.generated_constraint；刚体模拟步会在 prepare 阶段
    读取它们并转成普通 ConstraintSpec slot。相同来源/目标的约束按内部
    stable_id 更新，不会因为节点重复执行而无限累积。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidGeneratedConstraintRegister(
    world: object,
    generated_constraint_properties: list[object],
) -> tuple[object, int, int, int]:
    if not isinstance(world, PhysicsWorldCache):
        return world, 0, 0, 0
    count, dirty_count, version = register_rigid_generated_constraint_objects(
        world,
        generated_constraint_properties,
        enabled=True,
    )
    return world, int(count), int(dirty_count), int(version)


@omni(
    enable=True,
    always_run=True,
    bl_label="刚体命令-设置速度",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "目标刚体", "线速度", "角速度"],
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体速度命令。

    节点只写入 world.exchange 的 rigid_body_commands item，不直接访问 Jolt handle。
    将本节点放在"刚体模拟步"之前，solver 会在本帧同步 body 后应用速度。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidSetVelocity(
    world: object,
    target: bpy.types.Object,
    linear_velocity: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    angular_velocity: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
) -> tuple[object, object]:
    return _publish_rigid_body_command(
        world,
        target,
        "set_velocity",
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
    _INPUT_NAME=["物理世界", "目标刚体", "力", "扭矩"],
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体 force / torque 命令。

    这是持续力；节点运行时每帧都会发布一次。需要脉冲式效果时请使用"刚体命令-施加冲量"。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidAddForce(
    world: object,
    target: bpy.types.Object,
    force: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    torque: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
) -> tuple[object, object]:
    return _publish_rigid_body_command(
        world,
        target,
        "add_force",
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
    _INPUT_NAME=["物理世界", "目标刚体", "冲量", "角冲量"],
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体 impulse / angular impulse 命令。

    这是瞬时冲量；节点如果持续运行，就会每帧发布一次。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidAddImpulse(
    world: object,
    target: bpy.types.Object,
    impulse: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    angular_impulse: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
) -> tuple[object, object]:
    return _publish_rigid_body_command(
        world,
        target,
        "add_impulse",
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
    _INPUT_NAME=["物理世界", "目标刚体", "重力倍率"],
    input_init={"gravity_factor": {"min_value": -10.0, "max_value": 10.0}},
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体重力倍率命令。

    该命令用于运行中改变单个刚体受到的重力强度，不修改 HoTools 持久化属性。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidSetGravityFactor(
    world: object,
    target: bpy.types.Object,
    gravity_factor: float = 1.0,
) -> tuple[object, object]:
    return _publish_rigid_body_command(
        world,
        target,
        "set_gravity_factor",
        producer="physicsRigidSetGravityFactor",
        gravity_factor=float(gravity_factor),
    )


@omni(
    enable=True,
    always_run=True,
    bl_label="刚体命令-材质响应",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "目标刚体", "摩擦", "弹性"],
    input_init={
        "friction": {"min_value": 0.0, "max_value": 1.0},
        "restitution": {"min_value": 0.0, "max_value": 1.0},
    },
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体材质响应命令。

    当前覆盖 friction / restitution。它是运行中命令，不修改 HoTools 持久化属性。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidSetMaterialResponse(
    world: object,
    target: bpy.types.Object,
    friction: float = 0.5,
    restitution: float = 0.0,
) -> tuple[object, object]:
    friction = max(0.0, min(1.0, float(friction)))
    restitution = max(0.0, min(1.0, float(restitution)))
    return _publish_rigid_body_command(
        world,
        target,
        "set_material_response",
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
    _INPUT_NAME=["物理世界", "目标刚体", "运动质量"],
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体运动质量命令。

    motion_quality 使用 DISCRETE 或 LINEAR_CAST；LINEAR_CAST 对高速刚体启用连续碰撞检测。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidSetMotionQuality(
    world: object,
    target: bpy.types.Object,
    motion_quality: str = "DISCRETE",
) -> tuple[object, object]:
    quality = str(motion_quality or "DISCRETE").strip().upper()
    if quality not in {"DISCRETE", "LINEAR_CAST"}:
        quality = "DISCRETE"
    return _publish_rigid_body_command(
        world,
        target,
        "set_motion_quality",
        producer="physicsRigidSetMotionQuality",
        motion_quality=quality,
    )


@omni(
    enable=True,
    always_run=True,
    bl_label="刚体命令-激活状态",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "目标刚体", "激活"],
    _OUTPUT_NAME=["物理世界", "命令"],
    omni_description="""
    向当前物理世界发布刚体激活状态命令。

    可用于唤醒 sleeping body，或显式切换 active 状态。
    """,
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsRigidSetActive(
    world: object,
    target: bpy.types.Object,
    active: bool = True,
) -> tuple[object, object]:
    return _publish_rigid_body_command(
        world,
        target,
        "set_active",
        producer="physicsRigidSetActive",
        active=bool(active),
    )
