"""
physicsWorld.rigid.specs — 刚体和约束的 spec 数据结构

spec 是 OmniNode 自己的物理语义表达，不依赖 Jolt 类型。
Jolt adapter（Phase 5）负责把 spec 映射到 Jolt BodyCreationSettings 等结构。

属性来源：bpy.types.Object.hotools_rigid_body 和 hotools_rigid_constraint
（PG_Hotools_RigidBody / PG_Hotools_RigidConstraint，由 PhysicsTools 注册），
由 HoTools 面板维护，节点图视为只读。

Phase 4 先只收集和调试，不要求 Jolt step 和写回。
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# RigidBodySpec
# ---------------------------------------------------------------------------

class RigidBodySpec:
    """
    单个刚体的 OmniNode 语义描述。

    使用 OmniNode 自己的字段名，不暴露 Jolt 内部概念。
    Jolt adapter 负责把这个 spec 映射到 BodyCreationSettings。
    """

    __slots__ = (
        "obj",
        "obj_ptr",
        "data_ptr",
        "slot_id",
        "world_position",
        "world_rotation_wxyz",
        "body_type",
        "mass",
        "friction",
        "restitution",
        "rigid_collision_group",
        "rigid_collides_with_groups",
        "shape_type",
        "shape_radius",
        "shape_half_height",
        "shape_half_extents",
        "shape_plane_half_extent",
        "shape_top_radius",
        "shape_bottom_radius",
        "shape_convex_radius",
        "shape_offset",
        "shape_rotation_wxyz",
        "linear_velocity",
        "angular_velocity",
        "linear_damping",
        "angular_damping",
        "gravity_factor",
        "allow_sleeping",
        "motion_quality",
        "max_linear_velocity",
        "max_angular_velocity",
        "is_sensor",
        "collide_kinematic_vs_non_dynamic",
        "allowed_dofs",
    )

    def __init__(
        self,
        obj,
        obj_ptr: int,
        data_ptr: int,
        world_position: tuple[float, float, float] = (0.0, 0.0, 0.0),
        world_rotation_wxyz: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
        body_type: str = "DYNAMIC",
        mass: float = 1.0,
        friction: float = 0.5,
        restitution: float = 0.0,
        rigid_collision_group: int = 1,
        rigid_collides_with_groups: int = 0xFFFF,
        shape_type: str = "SPHERE",
        shape_radius: float = 0.5,
        shape_half_height: float = 0.5,
        shape_half_extents: tuple[float, float, float] = (0.5, 0.5, 0.5),
        shape_plane_half_extent: float = 10.0,
        shape_top_radius: float = 0.5,
        shape_bottom_radius: float = 0.3,
        shape_convex_radius: float = 0.05,
        shape_offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
        shape_rotation_wxyz: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
        linear_velocity: tuple[float, float, float] = (0.0, 0.0, 0.0),
        angular_velocity: tuple[float, float, float] = (0.0, 0.0, 0.0),
        linear_damping: float = 0.05,
        angular_damping: float = 0.05,
        gravity_factor: float = 1.0,
        allow_sleeping: bool = True,
        motion_quality: str = "DISCRETE",
        max_linear_velocity: float = 500.0,
        max_angular_velocity: float = 47.1239,
        is_sensor: bool = False,
        collide_kinematic_vs_non_dynamic: bool = False,
        allowed_dofs: int = 0x3F,
    ) -> None:
        self.obj = obj
        self.obj_ptr: int = obj_ptr
        self.data_ptr: int = data_ptr
        self.slot_id: str = f"rigid:{obj_ptr}:{data_ptr}"
        self.world_position: tuple[float, float, float] = world_position
        self.world_rotation_wxyz: tuple[float, float, float, float] = world_rotation_wxyz
        self.body_type: str = body_type
        self.mass: float = mass
        self.friction: float = friction
        self.restitution: float = restitution
        self.rigid_collision_group: int = rigid_collision_group
        self.rigid_collides_with_groups: int = rigid_collides_with_groups
        self.shape_type: str = shape_type
        self.shape_radius: float = shape_radius
        self.shape_half_height: float = shape_half_height
        self.shape_half_extents: tuple[float, float, float] = shape_half_extents
        self.shape_plane_half_extent: float = shape_plane_half_extent
        self.shape_top_radius: float = shape_top_radius
        self.shape_bottom_radius: float = shape_bottom_radius
        self.shape_convex_radius: float = shape_convex_radius
        self.shape_offset: tuple[float, float, float] = shape_offset
        self.shape_rotation_wxyz: tuple[float, float, float, float] = shape_rotation_wxyz
        self.linear_velocity: tuple[float, float, float] = linear_velocity
        self.angular_velocity: tuple[float, float, float] = angular_velocity
        self.linear_damping: float = linear_damping
        self.angular_damping: float = angular_damping
        self.gravity_factor: float = gravity_factor
        self.allow_sleeping: bool = allow_sleeping
        self.motion_quality: str = motion_quality
        self.max_linear_velocity: float = max_linear_velocity
        self.max_angular_velocity: float = max_angular_velocity
        self.is_sensor: bool = is_sensor
        self.collide_kinematic_vs_non_dynamic: bool = collide_kinematic_vs_non_dynamic
        self.allowed_dofs: int = allowed_dofs

    def debug_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "world_position": self.world_position,
            "world_rotation_wxyz": self.world_rotation_wxyz,
            "body_type": self.body_type,
            "mass": self.mass,
            "friction": self.friction,
            "restitution": self.restitution,
            "rigid_collision_group": self.rigid_collision_group,
            "rigid_collides_with_groups": self.rigid_collides_with_groups,
            "shape_type": self.shape_type,
            "shape_radius": self.shape_radius,
            "shape_half_height": self.shape_half_height,
            "shape_half_extents": self.shape_half_extents,
            "shape_plane_half_extent": self.shape_plane_half_extent,
            "shape_top_radius": self.shape_top_radius,
            "shape_bottom_radius": self.shape_bottom_radius,
            "shape_convex_radius": self.shape_convex_radius,
            "shape_offset": self.shape_offset,
            "shape_rotation_wxyz": self.shape_rotation_wxyz,
            "linear_velocity": self.linear_velocity,
            "angular_velocity": self.angular_velocity,
            "linear_damping": self.linear_damping,
            "angular_damping": self.angular_damping,
            "gravity_factor": self.gravity_factor,
            "allow_sleeping": self.allow_sleeping,
            "motion_quality": self.motion_quality,
            "max_linear_velocity": self.max_linear_velocity,
            "max_angular_velocity": self.max_angular_velocity,
            "is_sensor": self.is_sensor,
            "collide_kinematic_vs_non_dynamic": self.collide_kinematic_vs_non_dynamic,
            "allowed_dofs": self.allowed_dofs,
        }


# ---------------------------------------------------------------------------
# ConstraintSpec
# ---------------------------------------------------------------------------

class ConstraintSpec:
    """
    单个约束的 OmniNode 语义描述。

    约束点载体为 Empty 对象：
      - Empty.matrix_world 表示约束 anchor frame（位置 + 旋转）
      - hotools_rigid_constraint PropertyGroup 表示约束类型和目标 A/B

    Jolt adapter 负责把 constraint_type 映射到 Jolt constraint 子类。
    Jolt ConstraintID 只保存在 runtime slot 中，不写回 Empty。
    """

    __slots__ = (
        "empty_obj",
        "empty_ptr",
        "slot_id",
        "constraint_type",
        "target_a",
        "target_b",
        "target_a_ptr",
        "target_b_ptr",
        "anchor_position",
        "anchor_rotation_wxyz",
        "constraint_priority",
        "solver_velocity_steps",
        "solver_position_steps",
        "draw_constraint_size",
        "limit_enabled",
        "angular_limit_min",
        "angular_limit_max",
        "linear_limit_min",
        "linear_limit_max",
        "limit_spring_frequency",
        "limit_spring_damping",
        "max_friction_torque",
        "max_friction_force",
        "motor_state",
        "motor_frequency",
        "motor_damping",
        "motor_force_limit",
        "motor_torque_limit",
        "motor_target_angular_velocity",
        "motor_target_angle",
        "motor_target_velocity",
        "motor_target_position",
        "cone_half_angle",
    )

    def __init__(
        self,
        empty_obj,
        empty_ptr: int,
        constraint_type: str = "FIXED",
        target_a=None,
        target_b=None,
        target_a_ptr: int = 0,
        target_b_ptr: int = 0,
        anchor_position: tuple[float, float, float] = (0.0, 0.0, 0.0),
        anchor_rotation_wxyz: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
        constraint_priority: int = 0,
        solver_velocity_steps: int = 0,
        solver_position_steps: int = 0,
        draw_constraint_size: float = 1.0,
        limit_enabled: bool = False,
        angular_limit_min: float = -3.141592653589793,
        angular_limit_max: float = 3.141592653589793,
        linear_limit_min: float = -1.0,
        linear_limit_max: float = 1.0,
        limit_spring_frequency: float = 0.0,
        limit_spring_damping: float = 0.0,
        max_friction_torque: float = 0.0,
        max_friction_force: float = 0.0,
        motor_state: str = "OFF",
        motor_frequency: float = 2.0,
        motor_damping: float = 1.0,
        motor_force_limit: float = 0.0,
        motor_torque_limit: float = 0.0,
        motor_target_angular_velocity: float = 0.0,
        motor_target_angle: float = 0.0,
        motor_target_velocity: float = 0.0,
        motor_target_position: float = 0.0,
        cone_half_angle: float = 0.0,
    ) -> None:
        self.empty_obj = empty_obj
        self.empty_ptr: int = empty_ptr
        self.slot_id: str = f"constraint:{empty_ptr}"
        self.constraint_type: str = constraint_type
        self.target_a = target_a   # bpy.types.Object 或 None（固定到世界）
        self.target_b = target_b   # bpy.types.Object 或 None
        self.target_a_ptr: int = int(target_a_ptr or 0)
        self.target_b_ptr: int = int(target_b_ptr or 0)
        self.anchor_position: tuple[float, float, float] = anchor_position
        self.anchor_rotation_wxyz: tuple[float, float, float, float] = anchor_rotation_wxyz
        self.constraint_priority: int = constraint_priority
        self.solver_velocity_steps: int = solver_velocity_steps
        self.solver_position_steps: int = solver_position_steps
        self.draw_constraint_size: float = draw_constraint_size
        self.limit_enabled: bool = limit_enabled
        self.angular_limit_min: float = angular_limit_min
        self.angular_limit_max: float = angular_limit_max
        self.linear_limit_min: float = linear_limit_min
        self.linear_limit_max: float = linear_limit_max
        self.limit_spring_frequency: float = limit_spring_frequency
        self.limit_spring_damping: float = limit_spring_damping
        self.max_friction_torque: float = max_friction_torque
        self.max_friction_force: float = max_friction_force
        self.motor_state: str = motor_state
        self.motor_frequency: float = motor_frequency
        self.motor_damping: float = motor_damping
        self.motor_force_limit: float = motor_force_limit
        self.motor_torque_limit: float = motor_torque_limit
        self.motor_target_angular_velocity: float = motor_target_angular_velocity
        self.motor_target_angle: float = motor_target_angle
        self.motor_target_velocity: float = motor_target_velocity
        self.motor_target_position: float = motor_target_position
        self.cone_half_angle: float = cone_half_angle

    def debug_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "constraint_type": self.constraint_type,
            "target_a": self.target_a.name if self.target_a is not None else None,
            "target_b": self.target_b.name if self.target_b is not None else None,
            "target_a_ptr": self.target_a_ptr,
            "target_b_ptr": self.target_b_ptr,
            "anchor_position": self.anchor_position,
            "anchor_rotation_wxyz": self.anchor_rotation_wxyz,
            "constraint_priority": self.constraint_priority,
            "solver_velocity_steps": self.solver_velocity_steps,
            "solver_position_steps": self.solver_position_steps,
            "draw_constraint_size": self.draw_constraint_size,
            "limit_enabled": self.limit_enabled,
            "angular_limit_min": self.angular_limit_min,
            "angular_limit_max": self.angular_limit_max,
            "linear_limit_min": self.linear_limit_min,
            "linear_limit_max": self.linear_limit_max,
            "limit_spring_frequency": self.limit_spring_frequency,
            "limit_spring_damping": self.limit_spring_damping,
            "max_friction_torque": self.max_friction_torque,
            "max_friction_force": self.max_friction_force,
            "motor_state": self.motor_state,
            "motor_frequency": self.motor_frequency,
            "motor_damping": self.motor_damping,
            "motor_force_limit": self.motor_force_limit,
            "motor_torque_limit": self.motor_torque_limit,
            "motor_target_angular_velocity": self.motor_target_angular_velocity,
            "motor_target_angle": self.motor_target_angle,
            "motor_target_velocity": self.motor_target_velocity,
            "motor_target_position": self.motor_target_position,
            "cone_half_angle": self.cone_half_angle,
        }


# ---------------------------------------------------------------------------
# 从 PropertyGroup 构造 spec
# ---------------------------------------------------------------------------

_PI = 3.141592653589793
_ALL_ALLOWED_DOFS = 0b111111
_DOF_TRANSLATION_X = 0b000001
_DOF_TRANSLATION_Y = 0b000010
_DOF_TRANSLATION_Z = 0b000100
_DOF_ROTATION_X = 0b001000
_DOF_ROTATION_Y = 0b010000
_DOF_ROTATION_Z = 0b100000


def _clamp(value, low, high):
    return max(low, min(high, value))


def _float3(value, default=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except Exception:
        return tuple(float(v) for v in default)


def _float4(value, default=(1.0, 0.0, 0.0, 0.0)) -> tuple[float, float, float, float]:
    try:
        return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    except Exception:
        return tuple(float(v) for v in default)


def _object_pointer(obj) -> int:
    if obj is None:
        return 0
    try:
        return int(obj.as_pointer())
    except Exception:
        return 0


def _object_data_pointer(obj) -> int:
    try:
        data = getattr(obj, "data", None)
        return int(data.as_pointer()) if data is not None else 0
    except Exception:
        return 0


def _world_transform_wxyz(obj) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    try:
        loc, rot, _scale = obj.matrix_world.decompose()
        return (
            (float(loc.x), float(loc.y), float(loc.z)),
            (float(rot.w), float(rot.x), float(rot.y), float(rot.z)),
        )
    except Exception:
        try:
            loc = getattr(obj, "location", (0.0, 0.0, 0.0))
            return (_float3(loc), (1.0, 0.0, 0.0, 0.0))
        except Exception:
            return ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))


def _rotation_wxyz_from_euler(value) -> tuple[float, float, float, float]:
    try:
        import mathutils
        q = mathutils.Euler(_float3(value), "XYZ").to_quaternion()
        return (float(q.w), float(q.x), float(q.y), float(q.z))
    except Exception:
        return (1.0, 0.0, 0.0, 0.0)


def _allowed_dofs_from_props(props) -> int:
    mask = 0
    if not bool(getattr(props, "lock_linear_x", False)):
        mask |= _DOF_TRANSLATION_X
    if not bool(getattr(props, "lock_linear_y", False)):
        mask |= _DOF_TRANSLATION_Y
    if not bool(getattr(props, "lock_linear_z", False)):
        mask |= _DOF_TRANSLATION_Z
    if not bool(getattr(props, "lock_angular_x", False)):
        mask |= _DOF_ROTATION_X
    if not bool(getattr(props, "lock_angular_y", False)):
        mask |= _DOF_ROTATION_Y
    if not bool(getattr(props, "lock_angular_z", False)):
        mask |= _DOF_ROTATION_Z
    return mask if mask != 0 else _ALL_ALLOWED_DOFS


def _ordered_pair(a: float, b: float) -> tuple[float, float]:
    return (a, b) if a <= b else (b, a)


def build_rigid_body_spec(obj) -> RigidBodySpec | None:
    """
    从 obj.hotools_rigid_body PropertyGroup 构造 RigidBodySpec。

    hotools_rigid_body.enabled=False 或属性不存在时返回 None（不参与刚体）。
    """
    if obj is None:
        return None

    props = getattr(obj, "hotools_rigid_body", None)
    if props is None or not bool(getattr(props, "enabled", False)):
        return None

    obj_ptr = _object_pointer(obj)
    if obj_ptr == 0:
        return None
    data_ptr = _object_data_pointer(obj)
    world_position, world_rotation_wxyz = _world_transform_wxyz(obj)

    body_type = str(getattr(props, "body_type", "DYNAMIC"))
    mass = max(float(getattr(props, "mass", 1.0)), 0.001)
    friction = max(0.0, min(1.0, float(getattr(props, "friction", 0.5))))
    restitution = max(0.0, min(1.0, float(getattr(props, "restitution", 0.0))))
    rigid_collision_group = max(1, min(16, int(getattr(props, "rigid_collision_group", 1))))
    rigid_collides_with_groups = max(0, min(0xFFFF, int(getattr(props, "rigid_collides_with_groups", 0xFFFF))))

    shape_type = str(getattr(props, "shape_type", "SPHERE"))
    if shape_type not in {
        "SPHERE",
        "CAPSULE",
        "CYLINDER",
        "TAPERED_CAPSULE",
        "TAPERED_CYLINDER",
        "PLANE",
        "BOX",
    }:
        shape_type = "SPHERE"
    if shape_type == "PLANE":
        body_type = "STATIC"
    shape_radius = max(float(getattr(props, "shape_radius", 0.5)), 0.001)
    shape_half_height = max(float(getattr(props, "shape_half_height", 0.5)), 0.001)
    shape_half_extents = tuple(max(v, 0.001) for v in _float3(getattr(props, "shape_half_extents", (0.5, 0.5, 0.5))))
    shape_plane_half_extent = max(float(getattr(props, "shape_plane_half_extent", 10.0)), 1.0)
    shape_top_radius = max(float(getattr(props, "shape_top_radius", 0.5)), 0.001)
    shape_bottom_radius = max(float(getattr(props, "shape_bottom_radius", 0.3)), 0.001)
    shape_convex_radius = max(float(getattr(props, "shape_convex_radius", 0.05)), 0.0)
    shape_offset = _float3(getattr(props, "shape_offset", (0.0, 0.0, 0.0)))
    shape_rotation_wxyz = _rotation_wxyz_from_euler(getattr(props, "shape_rotation", (0.0, 0.0, 0.0)))

    linear_velocity = _float3(getattr(props, "linear_velocity", (0.0, 0.0, 0.0)))
    angular_velocity = _float3(getattr(props, "angular_velocity", (0.0, 0.0, 0.0)))
    linear_damping = _clamp(float(getattr(props, "linear_damping", 0.05)), 0.0, 1.0)
    angular_damping = _clamp(float(getattr(props, "angular_damping", 0.05)), 0.0, 1.0)
    gravity_factor = float(getattr(props, "gravity_factor", 1.0))
    allow_sleeping = bool(getattr(props, "allow_sleeping", True))
    motion_quality = str(getattr(props, "motion_quality", "DISCRETE"))
    if motion_quality not in {"DISCRETE", "LINEAR_CAST"}:
        motion_quality = "DISCRETE"
    max_linear_velocity = max(float(getattr(props, "max_linear_velocity", 500.0)), 0.0)
    max_angular_velocity = max(float(getattr(props, "max_angular_velocity", 47.1239)), 0.0)
    is_sensor = bool(getattr(props, "is_sensor", False))
    collide_kinematic_vs_non_dynamic = bool(getattr(props, "collide_kinematic_vs_non_dynamic", False))
    allowed_dofs = _allowed_dofs_from_props(props)

    return RigidBodySpec(
        obj=obj,
        obj_ptr=obj_ptr,
        data_ptr=data_ptr,
        world_position=world_position,
        world_rotation_wxyz=world_rotation_wxyz,
        body_type=body_type,
        mass=mass,
        friction=friction,
        restitution=restitution,
        rigid_collision_group=rigid_collision_group,
        rigid_collides_with_groups=rigid_collides_with_groups,
        shape_type=shape_type,
        shape_radius=shape_radius,
        shape_half_height=shape_half_height,
        shape_half_extents=shape_half_extents,
        shape_plane_half_extent=shape_plane_half_extent,
        shape_top_radius=shape_top_radius,
        shape_bottom_radius=shape_bottom_radius,
        shape_convex_radius=shape_convex_radius,
        shape_offset=shape_offset,
        shape_rotation_wxyz=shape_rotation_wxyz,
        linear_velocity=linear_velocity,
        angular_velocity=angular_velocity,
        linear_damping=linear_damping,
        angular_damping=angular_damping,
        gravity_factor=gravity_factor,
        allow_sleeping=allow_sleeping,
        motion_quality=motion_quality,
        max_linear_velocity=max_linear_velocity,
        max_angular_velocity=max_angular_velocity,
        is_sensor=is_sensor,
        collide_kinematic_vs_non_dynamic=collide_kinematic_vs_non_dynamic,
        allowed_dofs=allowed_dofs,
    )


def build_constraint_spec(empty_obj) -> ConstraintSpec | None:
    """
    从 empty_obj.hotools_rigid_constraint PropertyGroup 构造 ConstraintSpec。

    hotools_rigid_constraint.enabled=False 或对象不是 EMPTY 时返回 None。
    """
    if empty_obj is None:
        return None

    try:
        if empty_obj.type != "EMPTY":
            return None
        empty_ptr = _object_pointer(empty_obj)
        if empty_ptr == 0:
            return None
    except Exception:
        return None

    props = getattr(empty_obj, "hotools_rigid_constraint", None)
    if props is None or not bool(getattr(props, "enabled", False)):
        return None

    constraint_type = str(getattr(props, "constraint_type", "FIXED"))
    if constraint_type not in {"FIXED", "HINGE", "SLIDER", "CONE", "POINT"}:
        constraint_type = "FIXED"
    target_a = getattr(props, "target_a", None)
    target_b = getattr(props, "target_b", None)
    target_a_ptr = _object_pointer(target_a)
    target_b_ptr = _object_pointer(target_b)
    anchor_position, anchor_rotation_wxyz = _world_transform_wxyz(empty_obj)

    constraint_priority = max(0, int(getattr(props, "constraint_priority", 0)))
    solver_velocity_steps = _clamp(int(getattr(props, "solver_velocity_steps", 0)), 0, 255)
    solver_position_steps = _clamp(int(getattr(props, "solver_position_steps", 0)), 0, 255)
    draw_constraint_size = max(float(getattr(props, "draw_constraint_size", 1.0)), 0.0)
    limit_enabled = bool(getattr(props, "limit_enabled", False))

    angular_limit_min = _clamp(float(getattr(props, "angular_limit_min", -_PI)), -_PI, 0.0)
    angular_limit_max = _clamp(float(getattr(props, "angular_limit_max", _PI)), 0.0, _PI)
    linear_limit_min, linear_limit_max = _ordered_pair(
        float(getattr(props, "linear_limit_min", -1.0)),
        float(getattr(props, "linear_limit_max", 1.0)),
    )
    limit_spring_frequency = max(float(getattr(props, "limit_spring_frequency", 0.0)), 0.0)
    limit_spring_damping = max(float(getattr(props, "limit_spring_damping", 0.0)), 0.0)

    max_friction_torque = max(float(getattr(props, "max_friction_torque", 0.0)), 0.0)
    max_friction_force = max(float(getattr(props, "max_friction_force", 0.0)), 0.0)
    motor_state = str(getattr(props, "motor_state", "OFF"))
    if motor_state not in {"OFF", "VELOCITY", "POSITION"}:
        motor_state = "OFF"
    motor_frequency = max(float(getattr(props, "motor_frequency", 2.0)), 0.0)
    motor_damping = max(float(getattr(props, "motor_damping", 1.0)), 0.0)
    motor_force_limit = max(float(getattr(props, "motor_force_limit", 0.0)), 0.0)
    motor_torque_limit = max(float(getattr(props, "motor_torque_limit", 0.0)), 0.0)
    motor_target_angular_velocity = float(getattr(props, "motor_target_angular_velocity", 0.0))
    motor_target_angle = float(getattr(props, "motor_target_angle", 0.0))
    motor_target_velocity = float(getattr(props, "motor_target_velocity", 0.0))
    motor_target_position = float(getattr(props, "motor_target_position", 0.0))
    cone_half_angle = _clamp(float(getattr(props, "cone_half_angle", 0.0)), 0.0, _PI)

    return ConstraintSpec(
        empty_obj=empty_obj,
        empty_ptr=empty_ptr,
        constraint_type=constraint_type,
        target_a=target_a,
        target_b=target_b,
        target_a_ptr=target_a_ptr,
        target_b_ptr=target_b_ptr,
        anchor_position=anchor_position,
        anchor_rotation_wxyz=anchor_rotation_wxyz,
        constraint_priority=constraint_priority,
        solver_velocity_steps=solver_velocity_steps,
        solver_position_steps=solver_position_steps,
        draw_constraint_size=draw_constraint_size,
        limit_enabled=limit_enabled,
        angular_limit_min=angular_limit_min,
        angular_limit_max=angular_limit_max,
        linear_limit_min=linear_limit_min,
        linear_limit_max=linear_limit_max,
        limit_spring_frequency=limit_spring_frequency,
        limit_spring_damping=limit_spring_damping,
        max_friction_torque=max_friction_torque,
        max_friction_force=max_friction_force,
        motor_state=motor_state,
        motor_frequency=motor_frequency,
        motor_damping=motor_damping,
        motor_force_limit=motor_force_limit,
        motor_torque_limit=motor_torque_limit,
        motor_target_angular_velocity=motor_target_angular_velocity,
        motor_target_angle=motor_target_angle,
        motor_target_velocity=motor_target_velocity,
        motor_target_position=motor_target_position,
        cone_half_angle=cone_half_angle,
    )
