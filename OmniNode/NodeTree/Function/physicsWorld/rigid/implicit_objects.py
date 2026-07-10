"""刚体 domain 的隐式物理对象注册与 solver slot 同步。"""

from __future__ import annotations

import math
import mathutils
import bpy

from .names import (
    RIGID_BACKEND_RESOURCE_KEY,
    RIGID_CONSTRAINT_SLOT_KIND,
    RIGID_GENERATED_CONSTRAINT_OBJECT_TAG,
    RIGID_JOLT_WORLD_SETTING_OBJECT_TAG,
)
from ..types import PhysicsWorldCache
from ..utils.ids import as_pointer, data_pointer, stable_short_hash
from .debug import install_rigid_slot_debug_snapshot
from .declaration import RIGID_SOLVER_DECLARATION
from .specs import ConstraintSpec


RIGID_GENERATED_CONSTRAINT_REGISTER_PRODUCER = "physicsRigidGeneratedConstraintRegister"
RIGID_JOLT_WORLD_SETTING_REGISTER_PRODUCER = "physicsRigidJoltWorldSettingsRegister"
GENERATED_CONSTRAINT_SLOT_PREFIX = "constraint.generated:"
DEFAULT_RIGID_GRAVITY = (0.0, 0.0, -9.81)
DEFAULT_RIGID_JOLT_MAX_BODIES = 1024
DEFAULT_RIGID_JOLT_MAX_BODY_PAIRS = DEFAULT_RIGID_JOLT_MAX_BODIES * 4
DEFAULT_RIGID_JOLT_MAX_CONTACT_CONSTRAINTS = DEFAULT_RIGID_JOLT_MAX_BODIES * 2
DEFAULT_RIGID_JOLT_WORLD_SETTING_SIGNATURE = "default"
_PI = 3.141592653589793


def _flatten(values) -> list:
    result = []
    stack = list(values) if isinstance(values, (list, tuple)) else (
        [values] if values is not None else []
    )
    while stack:
        item = stack.pop(0)
        if isinstance(item, (list, tuple)):
            stack[0:0] = list(item)
        else:
            result.append(item)
    return result


def _float3(value, fallback=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except Exception:
        return tuple(float(v) for v in fallback)


def _finite_float3(value, fallback=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    result = _float3(value, fallback)
    if not all(math.isfinite(v) for v in result):
        return tuple(float(v) for v in fallback)
    return result


def _positive_int(value, fallback: int, low: int = 1, high: int = 1_000_000) -> int:
    try:
        number = int(value)
    except Exception:
        number = int(fallback)
    if number < low:
        number = int(fallback)
    return max(low, min(high, number))


def _jolt_capacity_tuple(
    max_bodies: int = DEFAULT_RIGID_JOLT_MAX_BODIES,
    max_body_pairs: int = DEFAULT_RIGID_JOLT_MAX_BODY_PAIRS,
    max_contact_constraints: int = DEFAULT_RIGID_JOLT_MAX_CONTACT_CONSTRAINTS,
) -> tuple[int, int, int]:
    bodies = _positive_int(max_bodies, DEFAULT_RIGID_JOLT_MAX_BODIES)
    # Keep <= 0 as a compatibility fallback for older node graphs that used
    # zero to mean "derive from max_bodies"; public defaults use real values.
    pairs = _positive_int(max_body_pairs, bodies * 4)
    contacts = _positive_int(max_contact_constraints, bodies * 2)
    return bodies, pairs, contacts


def _float4(value, fallback=(1.0, 0.0, 0.0, 0.0)) -> tuple[float, float, float, float]:
    try:
        return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    except Exception:
        return tuple(float(v) for v in fallback)


def _float6(value, fallback) -> tuple[float, float, float, float, float, float]:
    try:
        if len(value) != 6:
            raise ValueError
        return tuple(float(value[index]) for index in range(6))
    except Exception:
        return tuple(float(v) for v in fallback)


def _normalize_six_dof_arrays(modes, minimum, maximum):
    """规范化 SixDOF 六轴模式与范围，旋转轴限制在正负 π。"""
    raw_modes = tuple(modes) if isinstance(modes, (list, tuple)) and len(modes) == 6 else ("FIXED",) * 6
    normalized_modes = []
    normalized_minimum = []
    normalized_maximum = []
    minimum = _float6(minimum, (-1.0, -1.0, -1.0, -_PI * 0.25, -_PI * 0.25, -_PI * 0.25))
    maximum = _float6(maximum, (1.0, 1.0, 1.0, _PI * 0.25, _PI * 0.25, _PI * 0.25))
    for index in range(6):
        mode = str(raw_modes[index] or "FIXED").upper()
        if mode not in {"FREE", "FIXED", "LIMITED"}:
            mode = "FIXED"
        low = minimum[index]
        high = maximum[index]
        if index >= 3:
            low = _clamp(low, -_PI, _PI)
            high = _clamp(high, -_PI, _PI)
        low, high = _ordered_pair(low, high)
        if low == high:
            if index >= 3 and high >= _PI:
                low = high - 1.0e-4
            else:
                high = low + 1.0e-4
        normalized_modes.append(mode)
        normalized_minimum.append(low)
        normalized_maximum.append(high)
    return tuple(normalized_modes), tuple(normalized_minimum), tuple(normalized_maximum)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _ordered_pair(a: float, b: float) -> tuple[float, float]:
    return (a, b) if a <= b else (b, a)


def _world_transform_wxyz(obj) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    try:
        loc, rot, _scale = obj.matrix_world.decompose()
        return (
            (float(loc.x), float(loc.y), float(loc.z)),
            (float(rot.w), float(rot.x), float(rot.y), float(rot.z)),
        )
    except Exception:
        return ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))


def _rotation_wxyz_from_euler(value) -> tuple[float, float, float, float]:
    try:
        q = mathutils.Euler(_float3(value), "XYZ").to_quaternion()
        return (float(q.w), float(q.x), float(q.y), float(q.z))
    except Exception:
        return (1.0, 0.0, 0.0, 0.0)


def _is_object(value) -> bool:
    return isinstance(value, bpy.types.Object)


def _midpoint_anchor(target_a, target_b) -> tuple[float, float, float]:
    positions = []
    for target in (target_a, target_b):
        if not _is_object(target):
            continue
        pos, _rot = _world_transform_wxyz(target)
        positions.append(pos)
    if not positions:
        return (0.0, 0.0, 0.0)
    count = float(len(positions))
    return (
        sum(pos[0] for pos in positions) / count,
        sum(pos[1] for pos in positions) / count,
        sum(pos[2] for pos in positions) / count,
    )


def _normalize_constraint_type(value) -> str:
    constraint_type = str(value or "FIXED").strip().upper()
    if constraint_type not in {
        "FIXED", "HINGE", "SLIDER", "CONE", "POINT", "DISTANCE", "SWING_TWIST",
        "SIX_DOF",
    }:
        return "FIXED"
    return constraint_type


def make_rigid_jolt_world_setting_properties(
    gravity: mathutils.Vector = mathutils.Vector(DEFAULT_RIGID_GRAVITY),
    enabled: bool = True,
    source_id: str = "default",
    priority: int = 0,
    max_bodies: int = DEFAULT_RIGID_JOLT_MAX_BODIES,
    max_body_pairs: int = DEFAULT_RIGID_JOLT_MAX_BODY_PAIRS,
    max_contact_constraints: int = DEFAULT_RIGID_JOLT_MAX_CONTACT_CONSTRAINTS,
) -> list[dict]:
    """构造一个可注册的 Jolt 刚体世界设置对象。"""
    bodies, pairs, contacts = _jolt_capacity_tuple(
        max_bodies,
        max_body_pairs,
        max_contact_constraints,
    )
    return [{
        "gravity": _finite_float3(gravity, DEFAULT_RIGID_GRAVITY),
        "max_bodies": bodies,
        "max_body_pairs": pairs,
        "max_contact_constraints": contacts,
        "enabled": bool(enabled),
        "source_id": str(source_id or "default"),
        "priority": int(priority),
    }]


def _copy_jolt_world_setting_object(item: dict) -> dict:
    bodies, pairs, contacts = _jolt_capacity_tuple(
        item.get("max_bodies", DEFAULT_RIGID_JOLT_MAX_BODIES),
        item.get("max_body_pairs", 0),
        item.get("max_contact_constraints", 0),
    )
    return {
        "gravity": _finite_float3(item.get("gravity", DEFAULT_RIGID_GRAVITY), DEFAULT_RIGID_GRAVITY),
        "max_bodies": bodies,
        "max_body_pairs": pairs,
        "max_contact_constraints": contacts,
        "enabled": bool(item.get("enabled", True)),
        "source_id": str(item.get("source_id", "default") or "default"),
        "priority": int(item.get("priority", 0) or 0),
    }


def normalize_rigid_jolt_world_setting_objects(world_setting_properties) -> list[dict]:
    objects: list[dict] = []
    for item in _flatten(world_setting_properties):
        if isinstance(item, dict):
            objects.append(_copy_jolt_world_setting_object(item))
    return objects


def rigid_jolt_world_setting_stable_id(item: dict) -> str:
    source_id = str(item.get("source_id", "default") or "default").strip() or "default"
    suffix = stable_short_hash([source_id], 16)
    return f"{RIGID_JOLT_WORLD_SETTING_OBJECT_TAG}:{suffix}"


def rigid_jolt_world_setting_signature(item: dict) -> str:
    payload = [
        str(item.get("source_id", "default") or "default"),
        int(item.get("priority", 0) or 0),
        "1" if bool(item.get("enabled", True)) else "0",
        ",".join(f"{v:.8g}" for v in _finite_float3(item.get("gravity", DEFAULT_RIGID_GRAVITY), DEFAULT_RIGID_GRAVITY)),
        int(item.get("max_bodies", DEFAULT_RIGID_JOLT_MAX_BODIES) or DEFAULT_RIGID_JOLT_MAX_BODIES),
        int(item.get("max_body_pairs", DEFAULT_RIGID_JOLT_MAX_BODY_PAIRS) or DEFAULT_RIGID_JOLT_MAX_BODY_PAIRS),
        int(item.get("max_contact_constraints", DEFAULT_RIGID_JOLT_MAX_CONTACT_CONSTRAINTS) or DEFAULT_RIGID_JOLT_MAX_CONTACT_CONSTRAINTS),
    ]
    return stable_short_hash(payload, 16)


def register_rigid_jolt_world_setting_objects(
    world: PhysicsWorldCache,
    world_setting_properties,
    enabled: bool = True,
    producer: str = RIGID_JOLT_WORLD_SETTING_REGISTER_PRODUCER,
) -> tuple[int, int, int]:
    """把 Jolt 刚体世界级设置注册为 world.implicit_objects。"""
    if not isinstance(world, PhysicsWorldCache):
        return 0, 0, 0

    objects = normalize_rigid_jolt_world_setting_objects(world_setting_properties)
    writer = str(producer or RIGID_JOLT_WORLD_SETTING_REGISTER_PRODUCER)
    dirty_count = 0
    version_max = 0

    world.acquire_write(writer)
    try:
        for item in objects:
            item["enabled"] = bool(enabled) and bool(item.get("enabled", True))
            stable_id = rigid_jolt_world_setting_stable_id(item)
            entry = world.append_implicit_object(
                tag=RIGID_JOLT_WORLD_SETTING_OBJECT_TAG,
                producer=writer,
                stable_id=stable_id,
                signature=rigid_jolt_world_setting_signature(item),
                enabled=bool(item.get("enabled", True)),
                schema=1,
                payload=item,
            )
            if isinstance(entry, dict):
                dirty_count += 1 if bool(entry.get("dirty", False)) else 0
                version_max = max(version_max, int(entry.get("version", 0) or 0))
    finally:
        world.release_write(writer)

    return len(objects), dirty_count, version_max


def _enabled_jolt_world_setting_entries(world: PhysicsWorldCache) -> list[dict]:
    if not isinstance(world, PhysicsWorldCache):
        return []
    return world.iter_implicit_objects(
        tag=RIGID_JOLT_WORLD_SETTING_OBJECT_TAG,
        enabled=True,
    )


def selected_rigid_jolt_world_setting(world: PhysicsWorldCache) -> dict | None:
    """返回当前生效的 Jolt 刚体世界设置；priority 高者胜，同优先级按 registry 顺序后者胜。"""
    candidates: list[tuple[int, int, int, dict, dict]] = []
    for index, entry in enumerate(_enabled_jolt_world_setting_entries(world)):
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        item = _copy_jolt_world_setting_object(payload)
        candidates.append((
            int(item.get("priority", 0) or 0),
            int(entry.get("last_seen_frame", 0) or 0),
            index,
            item,
            entry,
        ))
    if not candidates:
        return None

    _priority, _frame, _index, item, entry = sorted(candidates, key=lambda row: row[:3])[-1]
    return {
        "gravity": _finite_float3(item.get("gravity", DEFAULT_RIGID_GRAVITY), DEFAULT_RIGID_GRAVITY),
        "max_bodies": int(item.get("max_bodies", DEFAULT_RIGID_JOLT_MAX_BODIES) or DEFAULT_RIGID_JOLT_MAX_BODIES),
        "max_body_pairs": int(item.get("max_body_pairs", DEFAULT_RIGID_JOLT_MAX_BODY_PAIRS) or DEFAULT_RIGID_JOLT_MAX_BODY_PAIRS),
        "max_contact_constraints": int(item.get("max_contact_constraints", DEFAULT_RIGID_JOLT_MAX_CONTACT_CONSTRAINTS) or DEFAULT_RIGID_JOLT_MAX_CONTACT_CONSTRAINTS),
        "source_id": str(item.get("source_id", "default") or "default"),
        "priority": int(item.get("priority", 0) or 0),
        "stable_id": str(entry.get("stable_id") or rigid_jolt_world_setting_stable_id(item)),
        "signature": str(entry.get("signature") or rigid_jolt_world_setting_signature(item)),
        "version": int(entry.get("version", 0) or 0),
    }


def active_rigid_jolt_world_setting_signature(world: PhysicsWorldCache) -> tuple[str, tuple[float, float, float]]:
    selected = selected_rigid_jolt_world_setting(world)
    if selected is None:
        return DEFAULT_RIGID_JOLT_WORLD_SETTING_SIGNATURE, DEFAULT_RIGID_GRAVITY
    return str(selected.get("signature") or DEFAULT_RIGID_JOLT_WORLD_SETTING_SIGNATURE), _finite_float3(
        selected.get("gravity", DEFAULT_RIGID_GRAVITY),
        DEFAULT_RIGID_GRAVITY,
    )


def active_rigid_jolt_world_capacities(world: PhysicsWorldCache) -> tuple[int, int, int]:
    selected = selected_rigid_jolt_world_setting(world)
    if selected is None:
        return (
            DEFAULT_RIGID_JOLT_MAX_BODIES,
            DEFAULT_RIGID_JOLT_MAX_BODY_PAIRS,
            DEFAULT_RIGID_JOLT_MAX_CONTACT_CONSTRAINTS,
        )
    return _jolt_capacity_tuple(
        selected.get("max_bodies", DEFAULT_RIGID_JOLT_MAX_BODIES),
        selected.get("max_body_pairs", DEFAULT_RIGID_JOLT_MAX_BODY_PAIRS),
        selected.get("max_contact_constraints", DEFAULT_RIGID_JOLT_MAX_CONTACT_CONSTRAINTS),
    )


def has_pending_jolt_world_settings(world: PhysicsWorldCache, adapter=None) -> bool:
    """检查 Jolt 刚体世界级设置是否需要同步到 Jolt adapter。"""
    if not isinstance(world, PhysicsWorldCache):
        return False
    signature, gravity = active_rigid_jolt_world_setting_signature(world)
    adapter = adapter or world.backend_resources.get(RIGID_BACKEND_RESOURCE_KEY)
    if adapter is None:
        return signature != DEFAULT_RIGID_JOLT_WORLD_SETTING_SIGNATURE or gravity != DEFAULT_RIGID_GRAVITY
    return str(getattr(adapter, "_jolt_world_settings_signature", DEFAULT_RIGID_JOLT_WORLD_SETTING_SIGNATURE)) != signature


def sync_rigid_jolt_world_settings(world: PhysicsWorldCache, adapter) -> bool:
    """把当前 Jolt 刚体世界可热更新设置同步到 adapter；容量由 adapter 重建处理。"""
    if not isinstance(world, PhysicsWorldCache) or adapter is None:
        return False

    signature, gravity = active_rigid_jolt_world_setting_signature(world)
    if str(getattr(adapter, "_jolt_world_settings_signature", DEFAULT_RIGID_JOLT_WORLD_SETTING_SIGNATURE)) == signature:
        return False

    set_gravity = getattr(adapter, "set_gravity", None)
    if not callable(set_gravity):
        return False
    if not bool(set_gravity(gravity)):
        return False

    try:
        adapter._jolt_world_settings_signature = signature
        adapter.last_jolt_world_gravity = gravity
        world.set_runtime_cache("rigid_jolt_world_settings_signature", signature)
        world.set_runtime_cache("rigid_jolt_world_gravity", gravity)
    except Exception:
        pass
    return True


def make_rigid_generated_constraint_properties(
    target_a: bpy.types.Object,
    target_b: bpy.types.Object = None,
    anchor_object: bpy.types.Object = None,
    constraint_type: str = "FIXED",
    enabled: bool = True,
    disable_collisions: bool = True,
    source_id: str = "",
    constraint_priority: int = 0,
    solver_velocity_steps: int = 0,
    solver_position_steps: int = 0,
    limit_enabled: bool = False,
    angular_limit_min: float = -_PI,
    angular_limit_max: float = _PI,
    linear_limit_min: float = -1.0,
    linear_limit_max: float = 1.0,
    cone_half_angle: float = 0.0,
    swing_type: str = "CONE",
    swing_normal_half_angle: float = _PI * 0.25,
    swing_plane_half_angle: float = _PI * 0.25,
    twist_min_angle: float = -_PI * 0.25,
    twist_max_angle: float = _PI * 0.25,
    swing_motor_state: str = "OFF",
    twist_motor_state: str = "OFF",
    motor_frequency: float = 2.0,
    motor_damping: float = 1.0,
    motor_torque_limit: float = 0.0,
    swing_twist_target_angular_velocity=(0.0, 0.0, 0.0),
    swing_twist_target_rotation=(0.0, 0.0, 0.0),
    six_dof_axis_modes=("FIXED", "FIXED", "FIXED", "FIXED", "FIXED", "FIXED"),
    six_dof_limit_min=(-1.0, -1.0, -1.0, -_PI * 0.25, -_PI * 0.25, -_PI * 0.25),
    six_dof_limit_max=(1.0, 1.0, 1.0, _PI * 0.25, _PI * 0.25, _PI * 0.25),
    six_dof_swing_type: str = "PYRAMID",
    six_dof_max_friction=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    distance_min: float = 0.0,
    distance_max: float = 1.0,
    breakable: bool = False,
    breaking_threshold: float = 1000.0,
    anchor_object_a: bpy.types.Object = None,
    anchor_object_b: bpy.types.Object = None,
) -> list[dict]:
    """
    构造单个可注册的刚体生成约束属性。

    anchor_object 存在时使用它的 world transform；否则位置取 target_a/b
    的中点，旋转使用 target_a 的 world rotation 或 identity。
    """
    if not _is_object(target_a) and not _is_object(target_b):
        return []

    if _is_object(anchor_object):
        anchor_position, anchor_rotation_wxyz = _world_transform_wxyz(anchor_object)
    else:
        anchor_position = _midpoint_anchor(target_a, target_b)
        if _is_object(target_a):
            _pos, anchor_rotation_wxyz = _world_transform_wxyz(target_a)
        else:
            anchor_rotation_wxyz = (1.0, 0.0, 0.0, 0.0)

    anchor_mode = "SHARED_WORLD"
    anchor_position_a = anchor_position_b = anchor_position
    anchor_rotation_wxyz_a = anchor_rotation_wxyz_b = anchor_rotation_wxyz
    if _is_object(anchor_object_a):
        anchor_position_a, anchor_rotation_wxyz_a = _world_transform_wxyz(anchor_object_a)
        anchor_mode = "SEPARATE_WORLD"
    if _is_object(anchor_object_b):
        anchor_position_b, anchor_rotation_wxyz_b = _world_transform_wxyz(anchor_object_b)
        anchor_mode = "SEPARATE_WORLD"

    linear_min, linear_max = _ordered_pair(float(linear_limit_min), float(linear_limit_max))
    distance_min, distance_max = _ordered_pair(
        max(float(distance_min), 0.0),
        max(float(distance_max), 0.0),
    )
    normalized_swing_type = str(swing_type or "CONE").upper()
    if normalized_swing_type not in {"CONE", "PYRAMID"}:
        normalized_swing_type = "CONE"
    twist_min_angle, twist_max_angle = _ordered_pair(
        _clamp(float(twist_min_angle), -_PI, _PI),
        _clamp(float(twist_max_angle), -_PI, _PI),
    )
    normalized_swing_motor_state = str(swing_motor_state or "OFF").upper()
    normalized_twist_motor_state = str(twist_motor_state or "OFF").upper()
    if normalized_swing_motor_state not in {"OFF", "VELOCITY", "POSITION"}:
        normalized_swing_motor_state = "OFF"
    if normalized_twist_motor_state not in {"OFF", "VELOCITY", "POSITION"}:
        normalized_twist_motor_state = "OFF"
    six_dof_axis_modes, six_dof_limit_min, six_dof_limit_max = _normalize_six_dof_arrays(
        six_dof_axis_modes, six_dof_limit_min, six_dof_limit_max,
    )
    normalized_six_dof_swing_type = str(six_dof_swing_type or "PYRAMID").upper()
    if normalized_six_dof_swing_type not in {"CONE", "PYRAMID"}:
        normalized_six_dof_swing_type = "PYRAMID"
    six_dof_max_friction = tuple(max(value, 0.0) for value in _float6(
        six_dof_max_friction, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    ))

    return [{
        "target_a": target_a if _is_object(target_a) else None,
        "target_b": target_b if _is_object(target_b) else None,
        "anchor_object": anchor_object if _is_object(anchor_object) else None,
        "anchor_object_a": anchor_object_a if _is_object(anchor_object_a) else None,
        "anchor_object_b": anchor_object_b if _is_object(anchor_object_b) else None,
        "constraint_type": _normalize_constraint_type(constraint_type),
        "enabled": bool(enabled),
        "disable_collisions": bool(disable_collisions),
        "breakable": bool(breakable),
        "breaking_threshold": max(float(breaking_threshold), 0.0),
        "source_id": str(source_id or ""),
        "anchor_position": anchor_position,
        "anchor_rotation_wxyz": anchor_rotation_wxyz,
        "anchor_mode": anchor_mode,
        "anchor_position_a": anchor_position_a,
        "anchor_rotation_wxyz_a": anchor_rotation_wxyz_a,
        "anchor_position_b": anchor_position_b,
        "anchor_rotation_wxyz_b": anchor_rotation_wxyz_b,
        "constraint_priority": max(0, int(constraint_priority)),
        "solver_velocity_steps": _clamp(int(solver_velocity_steps), 0, 255),
        "solver_position_steps": _clamp(int(solver_position_steps), 0, 255),
        "draw_constraint_size": 1.0,
        "limit_enabled": bool(limit_enabled),
        "angular_limit_min": _clamp(float(angular_limit_min), -_PI, 0.0),
        "angular_limit_max": _clamp(float(angular_limit_max), 0.0, _PI),
        "linear_limit_min": linear_min,
        "linear_limit_max": linear_max,
        "limit_spring_frequency": 0.0,
        "limit_spring_damping": 0.0,
        "max_friction_torque": 0.0,
        "max_friction_force": 0.0,
        "motor_state": "OFF",
        "motor_frequency": max(float(motor_frequency), 0.0),
        "motor_damping": max(float(motor_damping), 0.0),
        "motor_force_limit": 0.0,
        "motor_torque_limit": max(float(motor_torque_limit), 0.0),
        "motor_target_angular_velocity": 0.0,
        "motor_target_angle": 0.0,
        "motor_target_velocity": 0.0,
        "motor_target_position": 0.0,
        "swing_motor_state": normalized_swing_motor_state,
        "twist_motor_state": normalized_twist_motor_state,
        "swing_twist_target_angular_velocity": _float3(swing_twist_target_angular_velocity),
        "swing_twist_target_orientation_wxyz": _rotation_wxyz_from_euler(
            swing_twist_target_rotation
        ),
        "six_dof_axis_modes": six_dof_axis_modes,
        "six_dof_limit_min": six_dof_limit_min,
        "six_dof_limit_max": six_dof_limit_max,
        "six_dof_swing_type": normalized_six_dof_swing_type,
        "six_dof_max_friction": six_dof_max_friction,
        "cone_half_angle": _clamp(float(cone_half_angle), 0.0, _PI),
        "swing_type": normalized_swing_type,
        "swing_normal_half_angle": _clamp(float(swing_normal_half_angle), 0.0, _PI),
        "swing_plane_half_angle": _clamp(float(swing_plane_half_angle), 0.0, _PI),
        "twist_min_angle": twist_min_angle,
        "twist_max_angle": twist_max_angle,
        "distance_min": distance_min,
        "distance_max": distance_max,
    }]


def _copy_generated_constraint_object(item: dict) -> dict:
    constraint_type = _normalize_constraint_type(item.get("constraint_type", "FIXED"))
    linear_min, linear_max = _ordered_pair(
        float(item.get("linear_limit_min", -1.0)),
        float(item.get("linear_limit_max", 1.0)),
    )
    distance_min, distance_max = _ordered_pair(
        max(float(item.get("distance_min", 0.0) or 0.0), 0.0),
        max(float(item.get("distance_max", 1.0) or 0.0), 0.0),
    )
    shared_position = _float3(item.get("anchor_position", (0.0, 0.0, 0.0)))
    shared_rotation = _float4(item.get(
        "anchor_rotation_wxyz",
        _rotation_wxyz_from_euler(item.get("anchor_rotation", (0.0, 0.0, 0.0))),
    ))
    anchor_mode = str(item.get("anchor_mode", "SHARED_WORLD") or "SHARED_WORLD")
    if anchor_mode not in {"SHARED_WORLD", "SEPARATE_WORLD"}:
        anchor_mode = "SHARED_WORLD"
    swing_type = str(item.get("swing_type", "CONE") or "CONE").upper()
    if swing_type not in {"CONE", "PYRAMID"}:
        swing_type = "CONE"
    twist_min_angle, twist_max_angle = _ordered_pair(
        _clamp(float(item.get("twist_min_angle", -_PI * 0.25)), -_PI, _PI),
        _clamp(float(item.get("twist_max_angle", _PI * 0.25)), -_PI, _PI),
    )
    swing_motor_state = str(item.get("swing_motor_state", "OFF") or "OFF").upper()
    twist_motor_state = str(item.get("twist_motor_state", "OFF") or "OFF").upper()
    if swing_motor_state not in {"OFF", "VELOCITY", "POSITION"}:
        swing_motor_state = "OFF"
    if twist_motor_state not in {"OFF", "VELOCITY", "POSITION"}:
        twist_motor_state = "OFF"
    six_dof_axis_modes, six_dof_limit_min, six_dof_limit_max = _normalize_six_dof_arrays(
        item.get("six_dof_axis_modes", ("FIXED",) * 6),
        item.get("six_dof_limit_min", (-1.0, -1.0, -1.0, -_PI * 0.25, -_PI * 0.25, -_PI * 0.25)),
        item.get("six_dof_limit_max", (1.0, 1.0, 1.0, _PI * 0.25, _PI * 0.25, _PI * 0.25)),
    )
    six_dof_swing_type = str(item.get("six_dof_swing_type", "PYRAMID") or "PYRAMID").upper()
    if six_dof_swing_type not in {"CONE", "PYRAMID"}:
        six_dof_swing_type = "PYRAMID"
    six_dof_max_friction = tuple(max(value, 0.0) for value in _float6(
        item.get("six_dof_max_friction", (0.0,) * 6), (0.0,) * 6,
    ))
    return {
        "target_a": item.get("target_a") if _is_object(item.get("target_a")) else None,
        "target_b": item.get("target_b") if _is_object(item.get("target_b")) else None,
        "anchor_object": item.get("anchor_object") if _is_object(item.get("anchor_object")) else None,
        "anchor_object_a": item.get("anchor_object_a") if _is_object(item.get("anchor_object_a")) else None,
        "anchor_object_b": item.get("anchor_object_b") if _is_object(item.get("anchor_object_b")) else None,
        "constraint_type": constraint_type,
        "enabled": bool(item.get("enabled", True)),
        "disable_collisions": bool(item.get("disable_collisions", True)),
        "breakable": bool(item.get("breakable", False)),
        "breaking_threshold": max(float(item.get("breaking_threshold", 1000.0) or 0.0), 0.0),
        "source_id": str(item.get("source_id", "") or ""),
        "anchor_position": shared_position,
        "anchor_rotation_wxyz": shared_rotation,
        "anchor_mode": anchor_mode,
        "anchor_position_a": _float3(item.get("anchor_position_a", shared_position)),
        "anchor_rotation_wxyz_a": _float4(item.get("anchor_rotation_wxyz_a", shared_rotation)),
        "anchor_position_b": _float3(item.get("anchor_position_b", shared_position)),
        "anchor_rotation_wxyz_b": _float4(item.get("anchor_rotation_wxyz_b", shared_rotation)),
        "constraint_priority": max(0, int(item.get("constraint_priority", 0) or 0)),
        "solver_velocity_steps": _clamp(int(item.get("solver_velocity_steps", 0) or 0), 0, 255),
        "solver_position_steps": _clamp(int(item.get("solver_position_steps", 0) or 0), 0, 255),
        "draw_constraint_size": max(float(item.get("draw_constraint_size", 1.0) or 1.0), 0.0),
        "limit_enabled": bool(item.get("limit_enabled", False)),
        "angular_limit_min": _clamp(float(item.get("angular_limit_min", -_PI)), -_PI, 0.0),
        "angular_limit_max": _clamp(float(item.get("angular_limit_max", _PI)), 0.0, _PI),
        "linear_limit_min": linear_min,
        "linear_limit_max": linear_max,
        "limit_spring_frequency": max(float(item.get("limit_spring_frequency", 0.0) or 0.0), 0.0),
        "limit_spring_damping": max(float(item.get("limit_spring_damping", 0.0) or 0.0), 0.0),
        "max_friction_torque": max(float(item.get("max_friction_torque", 0.0) or 0.0), 0.0),
        "max_friction_force": max(float(item.get("max_friction_force", 0.0) or 0.0), 0.0),
        "motor_state": str(item.get("motor_state", "OFF") or "OFF").strip().upper(),
        "motor_frequency": max(float(item.get("motor_frequency", 2.0) or 0.0), 0.0),
        "motor_damping": max(float(item.get("motor_damping", 1.0) or 0.0), 0.0),
        "motor_force_limit": max(float(item.get("motor_force_limit", 0.0) or 0.0), 0.0),
        "motor_torque_limit": max(float(item.get("motor_torque_limit", 0.0) or 0.0), 0.0),
        "motor_target_angular_velocity": float(item.get("motor_target_angular_velocity", 0.0) or 0.0),
        "motor_target_angle": float(item.get("motor_target_angle", 0.0) or 0.0),
        "motor_target_velocity": float(item.get("motor_target_velocity", 0.0) or 0.0),
        "motor_target_position": float(item.get("motor_target_position", 0.0) or 0.0),
        "swing_motor_state": swing_motor_state,
        "twist_motor_state": twist_motor_state,
        "swing_twist_target_angular_velocity": _float3(
            item.get("swing_twist_target_angular_velocity", (0.0, 0.0, 0.0))
        ),
        "swing_twist_target_orientation_wxyz": _float4(
            item.get("swing_twist_target_orientation_wxyz", (1.0, 0.0, 0.0, 0.0))
        ),
        "six_dof_axis_modes": six_dof_axis_modes,
        "six_dof_limit_min": six_dof_limit_min,
        "six_dof_limit_max": six_dof_limit_max,
        "six_dof_swing_type": six_dof_swing_type,
        "six_dof_max_friction": six_dof_max_friction,
        "cone_half_angle": _clamp(float(item.get("cone_half_angle", 0.0) or 0.0), 0.0, _PI),
        "swing_type": swing_type,
        "swing_normal_half_angle": _clamp(float(item.get("swing_normal_half_angle", _PI * 0.25)), 0.0, _PI),
        "swing_plane_half_angle": _clamp(float(item.get("swing_plane_half_angle", _PI * 0.25)), 0.0, _PI),
        "twist_min_angle": twist_min_angle,
        "twist_max_angle": twist_max_angle,
        "distance_min": distance_min,
        "distance_max": distance_max,
    }


def normalize_rigid_generated_constraint_objects(generated_constraint_properties) -> list[dict]:
    objects: list[dict] = []
    for item in _flatten(generated_constraint_properties):
        if not isinstance(item, dict):
            continue
        copied = _copy_generated_constraint_object(item)
        if _is_object(copied.get("target_a")) or _is_object(copied.get("target_b")):
            objects.append(copied)
    return objects


def _target_parts(obj) -> tuple[int, int]:
    return as_pointer(obj), data_pointer(obj)


def rigid_generated_constraint_stable_id(item: dict) -> str:
    target_a = item.get("target_a")
    target_b = item.get("target_b")
    a_ptr, a_data_ptr = _target_parts(target_a)
    b_ptr, b_data_ptr = _target_parts(target_b)
    source_id = str(item.get("source_id", "") or "").strip()
    if source_id:
        stable_parts = [source_id, a_ptr, a_data_ptr, b_ptr, b_data_ptr]
    else:
        stable_parts = [
            a_ptr,
            a_data_ptr,
            b_ptr,
            b_data_ptr,
            str(item.get("constraint_type", "FIXED") or "FIXED"),
        ]
    suffix = stable_short_hash(stable_parts, 16)
    return f"{RIGID_GENERATED_CONSTRAINT_OBJECT_TAG}:{suffix}"


def rigid_generated_constraint_slot_id_from_stable_id(stable_id: str) -> str:
    suffix = stable_short_hash([stable_id], 16)
    return f"{GENERATED_CONSTRAINT_SLOT_PREFIX}{suffix}"


def rigid_generated_constraint_signature(item: dict) -> str:
    target_a = item.get("target_a")
    target_b = item.get("target_b")
    anchor_object = item.get("anchor_object")
    anchor_object_a = item.get("anchor_object_a")
    anchor_object_b = item.get("anchor_object_b")
    a_ptr, a_data_ptr = _target_parts(target_a)
    b_ptr, b_data_ptr = _target_parts(target_b)
    anchor_ptr, anchor_data_ptr = _target_parts(anchor_object)
    anchor_a_ptr, anchor_a_data_ptr = _target_parts(anchor_object_a)
    anchor_b_ptr, anchor_b_data_ptr = _target_parts(anchor_object_b)
    payload = [
        a_ptr,
        a_data_ptr,
        b_ptr,
        b_data_ptr,
        anchor_ptr,
        anchor_data_ptr,
        anchor_a_ptr,
        anchor_a_data_ptr,
        anchor_b_ptr,
        anchor_b_data_ptr,
        str(item.get("constraint_type", "FIXED") or "FIXED"),
        "1" if bool(item.get("enabled", True)) else "0",
        "1" if bool(item.get("disable_collisions", True)) else "0",
        "1" if bool(item.get("breakable", False)) else "0",
        f"{float(item.get('breaking_threshold', 1000.0)):.8g}",
        ",".join(f"{v:.8g}" for v in _float3(item.get("anchor_position", (0.0, 0.0, 0.0)))),
        ",".join(f"{float(v):.8g}" for v in _float4(item.get("anchor_rotation_wxyz", (1.0, 0.0, 0.0, 0.0)))),
        str(item.get("anchor_mode", "SHARED_WORLD") or "SHARED_WORLD"),
        ",".join(f"{v:.8g}" for v in _float3(item.get("anchor_position_a", (0.0, 0.0, 0.0)))),
        ",".join(f"{float(v):.8g}" for v in _float4(item.get("anchor_rotation_wxyz_a", (1.0, 0.0, 0.0, 0.0)))),
        ",".join(f"{v:.8g}" for v in _float3(item.get("anchor_position_b", (0.0, 0.0, 0.0)))),
        ",".join(f"{float(v):.8g}" for v in _float4(item.get("anchor_rotation_wxyz_b", (1.0, 0.0, 0.0, 0.0)))),
        int(item.get("constraint_priority", 0) or 0),
        int(item.get("solver_velocity_steps", 0) or 0),
        int(item.get("solver_position_steps", 0) or 0),
        "1" if bool(item.get("limit_enabled", False)) else "0",
        f"{float(item.get('angular_limit_min', -_PI)):.8g}",
        f"{float(item.get('angular_limit_max', _PI)):.8g}",
        f"{float(item.get('linear_limit_min', -1.0)):.8g}",
        f"{float(item.get('linear_limit_max', 1.0)):.8g}",
        f"{float(item.get('cone_half_angle', 0.0)):.8g}",
        str(item.get("swing_type", "CONE") or "CONE"),
        f"{float(item.get('swing_normal_half_angle', _PI * 0.25)):.8g}",
        f"{float(item.get('swing_plane_half_angle', _PI * 0.25)):.8g}",
        f"{float(item.get('twist_min_angle', -_PI * 0.25)):.8g}",
        f"{float(item.get('twist_max_angle', _PI * 0.25)):.8g}",
        str(item.get("swing_motor_state", "OFF") or "OFF"),
        str(item.get("twist_motor_state", "OFF") or "OFF"),
        f"{float(item.get('motor_frequency', 2.0)):.8g}",
        f"{float(item.get('motor_damping', 1.0)):.8g}",
        f"{float(item.get('motor_torque_limit', 0.0)):.8g}",
        ",".join(f"{value:.8g}" for value in _float3(
            item.get("swing_twist_target_angular_velocity", (0.0, 0.0, 0.0))
        )),
        ",".join(f"{value:.8g}" for value in _float4(
            item.get("swing_twist_target_orientation_wxyz", (1.0, 0.0, 0.0, 0.0))
        )),
        ",".join(str(value) for value in item.get("six_dof_axis_modes", ("FIXED",) * 6)),
        ",".join(f"{value:.8g}" for value in _float6(
            item.get("six_dof_limit_min", (-1.0, -1.0, -1.0, -_PI * 0.25, -_PI * 0.25, -_PI * 0.25)),
            (-1.0, -1.0, -1.0, -_PI * 0.25, -_PI * 0.25, -_PI * 0.25),
        )),
        ",".join(f"{value:.8g}" for value in _float6(
            item.get("six_dof_limit_max", (1.0, 1.0, 1.0, _PI * 0.25, _PI * 0.25, _PI * 0.25)),
            (1.0, 1.0, 1.0, _PI * 0.25, _PI * 0.25, _PI * 0.25),
        )),
        str(item.get("six_dof_swing_type", "PYRAMID") or "PYRAMID"),
        ",".join(f"{value:.8g}" for value in _float6(
            item.get("six_dof_max_friction", (0.0,) * 6), (0.0,) * 6,
        )),
        f"{float(item.get('distance_min', 0.0)):.8g}",
        f"{float(item.get('distance_max', 1.0)):.8g}",
        str(item.get("source_id", "") or ""),
    ]
    return stable_short_hash(payload, 16)


def register_rigid_generated_constraint_objects(
    world: PhysicsWorldCache,
    generated_constraint_properties,
    enabled: bool = True,
    producer: str = RIGID_GENERATED_CONSTRAINT_REGISTER_PRODUCER,
) -> tuple[int, int, int]:
    """把生成约束属性注册为 world.implicit_objects。"""
    if not isinstance(world, PhysicsWorldCache):
        return 0, 0, 0

    objects = normalize_rigid_generated_constraint_objects(generated_constraint_properties)
    writer = str(producer or RIGID_GENERATED_CONSTRAINT_REGISTER_PRODUCER)
    dirty_count = 0
    version_max = 0

    world.acquire_write(writer)
    try:
        for item in objects:
            item["enabled"] = bool(enabled) and bool(item.get("enabled", True))
            stable_id = rigid_generated_constraint_stable_id(item)
            item["slot_id"] = rigid_generated_constraint_slot_id_from_stable_id(stable_id)
            entry = world.append_implicit_object(
                tag=RIGID_GENERATED_CONSTRAINT_OBJECT_TAG,
                producer=writer,
                stable_id=stable_id,
                signature=rigid_generated_constraint_signature(item),
                enabled=bool(item.get("enabled", True)),
                schema=1,
                payload=item,
            )
            if isinstance(entry, dict):
                dirty_count += 1 if bool(entry.get("dirty", False)) else 0
                version_max = max(version_max, int(entry.get("version", 0) or 0))
    finally:
        world.release_write(writer)

    return len(objects), dirty_count, version_max


def _enabled_generated_constraint_entries(world: PhysicsWorldCache) -> list[dict]:
    if not isinstance(world, PhysicsWorldCache):
        return []
    return world.iter_implicit_objects(
        tag=RIGID_GENERATED_CONSTRAINT_OBJECT_TAG,
        enabled=True,
    )


def _spec_from_entry(entry: dict) -> tuple[ConstraintSpec | None, str]:
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None, ""
    item = _copy_generated_constraint_object(payload)
    slot_id = str(payload.get("slot_id") or "").strip()
    if not slot_id:
        slot_id = rigid_generated_constraint_slot_id_from_stable_id(str(entry.get("stable_id") or ""))
    if not slot_id:
        return None, ""

    target_a = item.get("target_a")
    target_b = item.get("target_b")
    if not _is_object(target_a) and not _is_object(target_b):
        return None, ""

    spec = ConstraintSpec(
        empty_obj=None,
        empty_ptr=0,
        slot_id=slot_id,
        constraint_type=str(item.get("constraint_type", "FIXED") or "FIXED"),
        target_a=target_a,
        target_b=target_b,
        target_a_ptr=as_pointer(target_a),
        target_b_ptr=as_pointer(target_b),
        disable_collisions=bool(item.get("disable_collisions", True)),
        breakable=bool(item.get("breakable", False)),
        breaking_threshold=float(item.get("breaking_threshold", 1000.0) or 0.0),
        anchor_mode=str(item.get("anchor_mode", "SHARED_WORLD") or "SHARED_WORLD"),
        anchor_position=_float3(item.get("anchor_position", (0.0, 0.0, 0.0))),
        anchor_rotation_wxyz=_float4(item.get("anchor_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))),
        anchor_position_a=_float3(item.get("anchor_position_a", item.get("anchor_position", (0.0, 0.0, 0.0)))),
        anchor_rotation_wxyz_a=_float4(item.get("anchor_rotation_wxyz_a", item.get("anchor_rotation_wxyz", (1.0, 0.0, 0.0, 0.0)))),
        anchor_position_b=_float3(item.get("anchor_position_b", item.get("anchor_position", (0.0, 0.0, 0.0)))),
        anchor_rotation_wxyz_b=_float4(item.get("anchor_rotation_wxyz_b", item.get("anchor_rotation_wxyz", (1.0, 0.0, 0.0, 0.0)))),
        constraint_priority=int(item.get("constraint_priority", 0) or 0),
        solver_velocity_steps=int(item.get("solver_velocity_steps", 0) or 0),
        solver_position_steps=int(item.get("solver_position_steps", 0) or 0),
        draw_constraint_size=float(item.get("draw_constraint_size", 1.0) or 1.0),
        limit_enabled=bool(item.get("limit_enabled", False)),
        angular_limit_min=float(item.get("angular_limit_min", -_PI)),
        angular_limit_max=float(item.get("angular_limit_max", _PI)),
        linear_limit_min=float(item.get("linear_limit_min", -1.0)),
        linear_limit_max=float(item.get("linear_limit_max", 1.0)),
        limit_spring_frequency=float(item.get("limit_spring_frequency", 0.0) or 0.0),
        limit_spring_damping=float(item.get("limit_spring_damping", 0.0) or 0.0),
        max_friction_torque=float(item.get("max_friction_torque", 0.0) or 0.0),
        max_friction_force=float(item.get("max_friction_force", 0.0) or 0.0),
        motor_state=str(item.get("motor_state", "OFF") or "OFF"),
        motor_frequency=float(item.get("motor_frequency", 2.0) or 0.0),
        motor_damping=float(item.get("motor_damping", 1.0) or 0.0),
        motor_force_limit=float(item.get("motor_force_limit", 0.0) or 0.0),
        motor_torque_limit=float(item.get("motor_torque_limit", 0.0) or 0.0),
        motor_target_angular_velocity=float(item.get("motor_target_angular_velocity", 0.0) or 0.0),
        motor_target_angle=float(item.get("motor_target_angle", 0.0) or 0.0),
        motor_target_velocity=float(item.get("motor_target_velocity", 0.0) or 0.0),
        motor_target_position=float(item.get("motor_target_position", 0.0) or 0.0),
        swing_motor_state=str(item.get("swing_motor_state", "OFF") or "OFF"),
        twist_motor_state=str(item.get("twist_motor_state", "OFF") or "OFF"),
        swing_twist_target_angular_velocity=_float3(
            item.get("swing_twist_target_angular_velocity", (0.0, 0.0, 0.0))
        ),
        swing_twist_target_orientation_wxyz=_float4(
            item.get("swing_twist_target_orientation_wxyz", (1.0, 0.0, 0.0, 0.0))
        ),
        six_dof_axis_modes=tuple(item.get("six_dof_axis_modes", ("FIXED",) * 6)),
        six_dof_limit_min=_float6(
            item.get("six_dof_limit_min", (-1.0, -1.0, -1.0, -_PI * 0.25, -_PI * 0.25, -_PI * 0.25)),
            (-1.0, -1.0, -1.0, -_PI * 0.25, -_PI * 0.25, -_PI * 0.25),
        ),
        six_dof_limit_max=_float6(
            item.get("six_dof_limit_max", (1.0, 1.0, 1.0, _PI * 0.25, _PI * 0.25, _PI * 0.25)),
            (1.0, 1.0, 1.0, _PI * 0.25, _PI * 0.25, _PI * 0.25),
        ),
        six_dof_swing_type=str(item.get("six_dof_swing_type", "PYRAMID") or "PYRAMID"),
        six_dof_max_friction=_float6(
            item.get("six_dof_max_friction", (0.0,) * 6), (0.0,) * 6,
        ),
        cone_half_angle=float(item.get("cone_half_angle", 0.0) or 0.0),
        swing_type=str(item.get("swing_type", "CONE") or "CONE"),
        swing_normal_half_angle=float(item.get("swing_normal_half_angle", _PI * 0.25)),
        swing_plane_half_angle=float(item.get("swing_plane_half_angle", _PI * 0.25)),
        twist_min_angle=float(item.get("twist_min_angle", -_PI * 0.25)),
        twist_max_angle=float(item.get("twist_max_angle", _PI * 0.25)),
        distance_min=float(item.get("distance_min", 0.0) or 0.0),
        distance_max=float(item.get("distance_max", 1.0) or 0.0),
    )
    return spec, str(entry.get("signature") or rigid_generated_constraint_signature(item))


def active_generated_constraint_slot_ids(world: PhysicsWorldCache) -> set[str]:
    """返回 enabled rigid.generated_constraint 对应的 solver slot id。"""
    result: set[str] = set()
    for entry in _enabled_generated_constraint_entries(world):
        spec, _signature = _spec_from_entry(entry)
        if spec is not None:
            result.add(spec.slot_id)
    return result


def _is_generated_constraint_slot(slot_id: str, slot) -> bool:
    if not str(slot_id).startswith(GENERATED_CONSTRAINT_SLOT_PREFIX):
        return False
    return getattr(slot, "kind", None) == RIGID_CONSTRAINT_SLOT_KIND


def has_pending_generated_constraints(world: PhysicsWorldCache) -> bool:
    """检查隐式生成约束是否需要创建、重同步或删除 slot。"""
    if not isinstance(world, PhysicsWorldCache):
        return False

    active_ids: set[str] = set()
    for entry in _enabled_generated_constraint_entries(world):
        spec, signature = _spec_from_entry(entry)
        if spec is None:
            continue
        active_ids.add(spec.slot_id)
        slot = world.solver_slots.get(spec.slot_id)
        if slot is None or slot.kind != RIGID_CONSTRAINT_SLOT_KIND:
            return True
        if slot.data.get("_implicit_signature") != signature:
            return True
        if slot.data.get("spec") is None:
            return True

    for slot_id, slot in world.solver_slots.items():
        if _is_generated_constraint_slot(slot_id, slot) and slot_id not in active_ids:
            return True
    return False


def sync_generated_constraint_slots(world: PhysicsWorldCache, adapter=None) -> tuple[int, int]:
    """
    把 enabled rigid.generated_constraint 隐式对象同步到 solver slots。

    返回 (active_count, dirty_count)。dirty 表示 slot 新建、签名变化或
    旧生成 slot 被删除；调用方据此决定 Jolt 是否需要重同步。
    """
    if not isinstance(world, PhysicsWorldCache):
        return 0, 0

    active_ids: set[str] = set()
    active_count = 0
    dirty_count = 0

    for entry in _enabled_generated_constraint_entries(world):
        spec, signature = _spec_from_entry(entry)
        if spec is None:
            continue
        active_count += 1
        active_ids.add(spec.slot_id)

        slot = world.ensure_solver_slot(spec.slot_id, RIGID_CONSTRAINT_SLOT_KIND)
        if slot.world_generation != world.generation:
            slot.data.clear()
            slot.world_generation = world.generation

        previous_signature = slot.data.get("_implicit_signature")
        changed = previous_signature != signature
        if changed:
            dirty_count += 1
            slot.data.pop("_jolt_generation", None)

        slot.data["_implicit_generated_constraint"] = True
        slot.data["_implicit_signature"] = signature
        slot.data["_sync_signature"] = signature
        slot.data["spec"] = spec
        slot.data["declaration"] = RIGID_SOLVER_DECLARATION
        install_rigid_slot_debug_snapshot(slot, spec)

    stale_ids = [
        slot_id
        for slot_id, slot in list(world.solver_slots.items())
        if _is_generated_constraint_slot(slot_id, slot) and slot_id not in active_ids
    ]
    for slot_id in stale_ids:
        remove_constraint = getattr(adapter, "remove_constraint", None)
        if callable(remove_constraint):
            try:
                remove_constraint(slot_id)
            except Exception:
                pass
        slot = world.solver_slots.pop(slot_id, None)
        if slot is not None:
            try:
                slot.dispose("rigid_generated_constraint_prune")
            except Exception:
                pass
        dirty_count += 1

    if dirty_count:
        world.replace_required = True
    return active_count, dirty_count
