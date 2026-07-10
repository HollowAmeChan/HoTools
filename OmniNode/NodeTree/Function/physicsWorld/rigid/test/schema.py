"""Rigid/Jolt 语义测试使用的严格 fixture 协议。

这里有意只使用 Python 标准库，使同一份 fixture 能在独立 CPython 与
Blender 内置 Python 中运行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


class FixtureError(ValueError):
    """fixture 存在歧义或非法内容时抛出。"""


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FixtureError(f"{path} must be an object")
    return value


def _sequence(value: Any, path: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise FixtureError(f"{path} must be an array")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FixtureError(f"{path} has unknown fields: {', '.join(unknown)}")


def _number(value: Any, path: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FixtureError(f"{path} must be a finite number") from exc
    if not math.isfinite(result):
        raise FixtureError(f"{path} must be finite")
    return result


def _integer(value: Any, path: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool):
        raise FixtureError(f"{path} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise FixtureError(f"{path} must be an integer") from exc
    if float(result) != _number(value, path):
        raise FixtureError(f"{path} must be an integer")
    if minimum is not None and result < minimum:
        raise FixtureError(f"{path} must be >= {minimum}")
    return result


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureError(f"{path} must be a non-empty string")
    return value.strip()


def _vec(value: Any, size: int, path: str) -> tuple[float, ...]:
    values = _sequence(value, path)
    if len(values) != size:
        raise FixtureError(f"{path} must contain {size} numbers")
    return tuple(_number(item, f"{path}[{index}]") for index, item in enumerate(values))


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise FixtureError(f"{path} must be boolean")
    return value


@dataclass(frozen=True)
class WorldSpec:
    gravity: tuple[float, float, float] = (0.0, 0.0, -9.81)
    dt: float = 1.0 / 60.0
    substeps: int = 1
    frames: int = 1
    max_bodies: int = 64
    max_body_pairs: int = 256
    max_contact_constraints: int = 128

    @classmethod
    def from_data(cls, value: Any, path: str = "world") -> "WorldSpec":
        data = _mapping(value, path)
        _reject_unknown(data, {
            "gravity", "dt", "substeps", "frames", "max_bodies",
            "max_body_pairs", "max_contact_constraints",
        }, path)
        result = cls(
            gravity=_vec(data.get("gravity", (0.0, 0.0, -9.81)), 3, f"{path}.gravity"),
            dt=_number(data.get("dt", 1.0 / 60.0), f"{path}.dt"),
            substeps=_integer(data.get("substeps", 1), f"{path}.substeps", minimum=1),
            frames=_integer(data.get("frames", 1), f"{path}.frames", minimum=0),
            max_bodies=_integer(data.get("max_bodies", 64), f"{path}.max_bodies", minimum=1),
            max_body_pairs=_integer(data.get("max_body_pairs", 256), f"{path}.max_body_pairs", minimum=1),
            max_contact_constraints=_integer(
                data.get("max_contact_constraints", 128),
                f"{path}.max_contact_constraints", minimum=1,
            ),
        )
        if result.dt <= 0.0:
            raise FixtureError(f"{path}.dt must be > 0")
        if result.substeps > 64:
            raise FixtureError(f"{path}.substeps must be <= 64")
        return result


@dataclass(frozen=True)
class ShapeSpec:
    type: str = "SPHERE"
    radius: float = 0.5
    half_height: float = 0.5
    half_extents: tuple[float, float, float] = (0.5, 0.5, 0.5)
    plane_half_extent: float = 10.0
    top_radius: float = 0.5
    bottom_radius: float = 0.3
    convex_radius: float = 0.05
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_wxyz: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)

    @classmethod
    def from_data(cls, value: Any, path: str) -> "ShapeSpec":
        data = _mapping(value, path)
        _reject_unknown(data, {
            "type", "radius", "half_height", "half_extents", "plane_half_extent",
            "top_radius", "bottom_radius", "convex_radius", "offset", "rotation_wxyz",
        }, path)
        shape_type = _string(data.get("type", "SPHERE"), f"{path}.type").upper()
        supported = {
            "SPHERE", "BOX", "CAPSULE", "CYLINDER", "TAPERED_CAPSULE",
            "TAPERED_CYLINDER", "PLANE",
        }
        if shape_type not in supported:
            raise FixtureError(f"{path}.type is unsupported: {shape_type}")
        result = cls(
            type=shape_type,
            radius=_number(data.get("radius", 0.5), f"{path}.radius"),
            half_height=_number(data.get("half_height", 0.5), f"{path}.half_height"),
            half_extents=_vec(data.get("half_extents", (0.5, 0.5, 0.5)), 3, f"{path}.half_extents"),
            plane_half_extent=_number(data.get("plane_half_extent", 10.0), f"{path}.plane_half_extent"),
            top_radius=_number(data.get("top_radius", 0.5), f"{path}.top_radius"),
            bottom_radius=_number(data.get("bottom_radius", 0.3), f"{path}.bottom_radius"),
            convex_radius=_number(data.get("convex_radius", 0.05), f"{path}.convex_radius"),
            offset=_vec(data.get("offset", (0.0, 0.0, 0.0)), 3, f"{path}.offset"),
            rotation_wxyz=_vec(
                data.get("rotation_wxyz", (1.0, 0.0, 0.0, 0.0)), 4,
                f"{path}.rotation_wxyz",
            ),
        )
        positive = {
            "radius": result.radius,
            "half_height": result.half_height,
            "plane_half_extent": result.plane_half_extent,
            "top_radius": result.top_radius,
            "bottom_radius": result.bottom_radius,
        }
        for name, number in positive.items():
            if number <= 0.0:
                raise FixtureError(f"{path}.{name} must be > 0")
        if any(number <= 0.0 for number in result.half_extents):
            raise FixtureError(f"{path}.half_extents values must be > 0")
        if result.convex_radius < 0.0:
            raise FixtureError(f"{path}.convex_radius must be >= 0")
        if sum(component * component for component in result.rotation_wxyz) <= 1.0e-20:
            raise FixtureError(f"{path}.rotation_wxyz cannot be zero")
        return result


@dataclass(frozen=True)
class BodySpec:
    id: str
    type: str
    shape: ShapeSpec
    position: tuple[float, float, float]
    rotation_wxyz: tuple[float, float, float, float]
    mass: float
    friction: float
    restitution: float
    collision_group: int
    collided_by_groups: int
    linear_velocity: tuple[float, float, float]
    angular_velocity: tuple[float, float, float]
    linear_damping: float
    angular_damping: float
    gravity_factor: float
    allow_sleeping: bool
    motion_quality: str
    max_linear_velocity: float
    max_angular_velocity: float
    is_sensor: bool
    allowed_dofs: int
    collide_kinematic_vs_non_dynamic: bool

    @classmethod
    def from_data(cls, value: Any, path: str) -> "BodySpec":
        data = _mapping(value, path)
        _reject_unknown(data, {
            "id", "type", "shape", "position", "rotation_wxyz", "mass", "friction",
            "restitution", "collision_group", "collided_by_groups", "linear_velocity",
            "angular_velocity", "linear_damping", "angular_damping", "gravity_factor",
            "allow_sleeping", "motion_quality", "max_linear_velocity",
            "max_angular_velocity", "is_sensor", "allowed_dofs",
            "collide_kinematic_vs_non_dynamic",
        }, path)
        body_type = _string(data.get("type", "DYNAMIC"), f"{path}.type").upper()
        if body_type not in {"STATIC", "DYNAMIC", "KINEMATIC"}:
            raise FixtureError(f"{path}.type is unsupported: {body_type}")
        motion_quality = _string(
            data.get("motion_quality", "DISCRETE"), f"{path}.motion_quality",
        ).upper()
        if motion_quality not in {"DISCRETE", "LINEAR_CAST"}:
            raise FixtureError(f"{path}.motion_quality is unsupported: {motion_quality}")
        result = cls(
            id=_string(data.get("id"), f"{path}.id"),
            type=body_type,
            shape=ShapeSpec.from_data(data.get("shape", {"type": "SPHERE"}), f"{path}.shape"),
            position=_vec(data.get("position", (0.0, 0.0, 0.0)), 3, f"{path}.position"),
            rotation_wxyz=_vec(
                data.get("rotation_wxyz", (1.0, 0.0, 0.0, 0.0)), 4,
                f"{path}.rotation_wxyz",
            ),
            mass=_number(data.get("mass", 1.0), f"{path}.mass"),
            friction=_number(data.get("friction", 0.5), f"{path}.friction"),
            restitution=_number(data.get("restitution", 0.0), f"{path}.restitution"),
            collision_group=_integer(data.get("collision_group", 1), f"{path}.collision_group", minimum=1),
            collided_by_groups=_integer(
                data.get("collided_by_groups", 0xFFFF), f"{path}.collided_by_groups", minimum=0,
            ),
            linear_velocity=_vec(
                data.get("linear_velocity", (0.0, 0.0, 0.0)), 3,
                f"{path}.linear_velocity",
            ),
            angular_velocity=_vec(
                data.get("angular_velocity", (0.0, 0.0, 0.0)), 3,
                f"{path}.angular_velocity",
            ),
            linear_damping=_number(data.get("linear_damping", 0.05), f"{path}.linear_damping"),
            angular_damping=_number(data.get("angular_damping", 0.05), f"{path}.angular_damping"),
            gravity_factor=_number(data.get("gravity_factor", 1.0), f"{path}.gravity_factor"),
            allow_sleeping=_bool(data.get("allow_sleeping", True), f"{path}.allow_sleeping"),
            motion_quality=motion_quality,
            max_linear_velocity=_number(
                data.get("max_linear_velocity", 500.0), f"{path}.max_linear_velocity",
            ),
            max_angular_velocity=_number(
                data.get("max_angular_velocity", 47.1239), f"{path}.max_angular_velocity",
            ),
            is_sensor=_bool(data.get("is_sensor", False), f"{path}.is_sensor"),
            allowed_dofs=_integer(data.get("allowed_dofs", 0x3F), f"{path}.allowed_dofs", minimum=0),
            collide_kinematic_vs_non_dynamic=_bool(
                data.get("collide_kinematic_vs_non_dynamic", False),
                f"{path}.collide_kinematic_vs_non_dynamic",
            ),
        )
        if result.mass <= 0.0:
            raise FixtureError(f"{path}.mass must be > 0")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", result.id) is None:
            raise FixtureError(
                f"{path}.id may contain only ASCII letters, digits, dot, underscore and dash"
            )
        if result.id == "WORLD":
            raise FixtureError(f"{path}.id uses reserved id WORLD")
        if result.friction < 0.0:
            raise FixtureError(f"{path}.friction must be >= 0")
        if not 0.0 <= result.restitution <= 1.0:
            raise FixtureError(f"{path}.restitution must be in [0, 1]")
        if result.linear_damping < 0.0 or result.angular_damping < 0.0:
            raise FixtureError(f"{path} damping values must be >= 0")
        if result.max_linear_velocity <= 0.0 or result.max_angular_velocity <= 0.0:
            raise FixtureError(f"{path} max velocities must be > 0")
        if not 1 <= result.collision_group <= 16:
            raise FixtureError(f"{path}.collision_group must be in [1, 16]")
        if not 0 <= result.collided_by_groups <= 0xFFFF:
            raise FixtureError(f"{path}.collided_by_groups must fit 16 bits")
        if not 0 <= result.allowed_dofs <= 0x3F:
            raise FixtureError(f"{path}.allowed_dofs must fit 6 bits")
        if sum(component * component for component in result.rotation_wxyz) <= 1.0e-20:
            raise FixtureError(f"{path}.rotation_wxyz cannot be zero")
        return result


@dataclass(frozen=True)
class ConstraintSpec:
    """一条可直接映射到 JoltWorld.add_constraint 的约束描述。"""

    id: str
    type: str
    body_a: str
    body_b: str
    anchor_position: tuple[float, float, float]
    anchor_rotation_wxyz: tuple[float, float, float, float]
    use_separate_anchor_frames: bool
    anchor_position_a: tuple[float, float, float]
    anchor_rotation_wxyz_a: tuple[float, float, float, float]
    anchor_position_b: tuple[float, float, float]
    anchor_rotation_wxyz_b: tuple[float, float, float, float]
    priority: int
    solver_velocity_steps: int
    solver_position_steps: int
    draw_size: float
    limit_enabled: bool
    angular_limit_min: float
    angular_limit_max: float
    linear_limit_min: float
    linear_limit_max: float
    limit_spring_frequency: float
    limit_spring_damping: float
    max_friction_torque: float
    max_friction_force: float
    motor_state: str
    motor_frequency: float
    motor_damping: float
    motor_force_limit: float
    motor_torque_limit: float
    motor_target_angular_velocity: float
    motor_target_angle: float
    motor_target_velocity: float
    motor_target_position: float
    cone_half_angle: float
    disable_collisions: bool
    distance_min: float
    distance_max: float

    @classmethod
    def from_data(cls, value: Any, path: str) -> "ConstraintSpec":
        data = _mapping(value, path)
        _reject_unknown(data, {
            "id", "type", "body_a", "body_b", "anchor_position",
            "anchor_rotation_wxyz", "use_separate_anchor_frames",
            "anchor_position_a", "anchor_rotation_wxyz_a", "anchor_position_b",
            "anchor_rotation_wxyz_b", "priority", "solver_velocity_steps",
            "solver_position_steps", "draw_size", "limit_enabled",
            "angular_limit_min", "angular_limit_max", "linear_limit_min",
            "linear_limit_max", "limit_spring_frequency", "limit_spring_damping",
            "max_friction_torque", "max_friction_force", "motor_state",
            "motor_frequency", "motor_damping", "motor_force_limit",
            "motor_torque_limit", "motor_target_angular_velocity",
            "motor_target_angle", "motor_target_velocity", "motor_target_position",
            "cone_half_angle", "disable_collisions", "distance_min", "distance_max",
        }, path)
        constraint_type = _string(data.get("type"), f"{path}.type").upper()
        if constraint_type not in {"FIXED", "POINT", "DISTANCE", "HINGE", "SLIDER", "CONE"}:
            raise FixtureError(f"{path}.type is unsupported: {constraint_type}")
        body_a = _string(data.get("body_a"), f"{path}.body_a")
        body_b = _string(data.get("body_b"), f"{path}.body_b")
        if body_a == "WORLD" and body_b == "WORLD":
            raise FixtureError(f"{path} cannot connect WORLD to WORLD")
        shared_position = _vec(
            data.get("anchor_position", (0.0, 0.0, 0.0)), 3,
            f"{path}.anchor_position",
        )
        shared_rotation = _vec(
            data.get("anchor_rotation_wxyz", (1.0, 0.0, 0.0, 0.0)), 4,
            f"{path}.anchor_rotation_wxyz",
        )
        use_separate = _bool(
            data.get("use_separate_anchor_frames", False),
            f"{path}.use_separate_anchor_frames",
        )
        result = cls(
            id=_string(data.get("id"), f"{path}.id"),
            type=constraint_type,
            body_a=body_a,
            body_b=body_b,
            anchor_position=shared_position,
            anchor_rotation_wxyz=shared_rotation,
            use_separate_anchor_frames=use_separate,
            anchor_position_a=_vec(
                data.get("anchor_position_a", shared_position), 3,
                f"{path}.anchor_position_a",
            ),
            anchor_rotation_wxyz_a=_vec(
                data.get("anchor_rotation_wxyz_a", shared_rotation), 4,
                f"{path}.anchor_rotation_wxyz_a",
            ),
            anchor_position_b=_vec(
                data.get("anchor_position_b", shared_position), 3,
                f"{path}.anchor_position_b",
            ),
            anchor_rotation_wxyz_b=_vec(
                data.get("anchor_rotation_wxyz_b", shared_rotation), 4,
                f"{path}.anchor_rotation_wxyz_b",
            ),
            priority=_integer(data.get("priority", 0), f"{path}.priority", minimum=0),
            solver_velocity_steps=_integer(
                data.get("solver_velocity_steps", 0), f"{path}.solver_velocity_steps", minimum=0,
            ),
            solver_position_steps=_integer(
                data.get("solver_position_steps", 0), f"{path}.solver_position_steps", minimum=0,
            ),
            draw_size=_number(data.get("draw_size", 1.0), f"{path}.draw_size"),
            limit_enabled=_bool(data.get("limit_enabled", False), f"{path}.limit_enabled"),
            angular_limit_min=_number(
                data.get("angular_limit_min", -math.pi), f"{path}.angular_limit_min",
            ),
            angular_limit_max=_number(
                data.get("angular_limit_max", math.pi), f"{path}.angular_limit_max",
            ),
            linear_limit_min=_number(
                data.get("linear_limit_min", -1.0), f"{path}.linear_limit_min",
            ),
            linear_limit_max=_number(
                data.get("linear_limit_max", 1.0), f"{path}.linear_limit_max",
            ),
            limit_spring_frequency=_number(
                data.get("limit_spring_frequency", 0.0), f"{path}.limit_spring_frequency",
            ),
            limit_spring_damping=_number(
                data.get("limit_spring_damping", 0.0), f"{path}.limit_spring_damping",
            ),
            max_friction_torque=_number(
                data.get("max_friction_torque", 0.0), f"{path}.max_friction_torque",
            ),
            max_friction_force=_number(
                data.get("max_friction_force", 0.0), f"{path}.max_friction_force",
            ),
            motor_state=_string(data.get("motor_state", "OFF"), f"{path}.motor_state").upper(),
            motor_frequency=_number(data.get("motor_frequency", 2.0), f"{path}.motor_frequency"),
            motor_damping=_number(data.get("motor_damping", 1.0), f"{path}.motor_damping"),
            motor_force_limit=_number(
                data.get("motor_force_limit", 0.0), f"{path}.motor_force_limit",
            ),
            motor_torque_limit=_number(
                data.get("motor_torque_limit", 0.0), f"{path}.motor_torque_limit",
            ),
            motor_target_angular_velocity=_number(
                data.get("motor_target_angular_velocity", 0.0),
                f"{path}.motor_target_angular_velocity",
            ),
            motor_target_angle=_number(
                data.get("motor_target_angle", 0.0), f"{path}.motor_target_angle",
            ),
            motor_target_velocity=_number(
                data.get("motor_target_velocity", 0.0), f"{path}.motor_target_velocity",
            ),
            motor_target_position=_number(
                data.get("motor_target_position", 0.0), f"{path}.motor_target_position",
            ),
            cone_half_angle=_number(
                data.get("cone_half_angle", 0.0), f"{path}.cone_half_angle",
            ),
            disable_collisions=_bool(
                data.get("disable_collisions", False), f"{path}.disable_collisions",
            ),
            distance_min=_number(data.get("distance_min", 0.0), f"{path}.distance_min"),
            distance_max=_number(data.get("distance_max", 1.0), f"{path}.distance_max"),
        )
        for name in (
            "limit_spring_frequency", "limit_spring_damping", "max_friction_torque",
            "max_friction_force", "motor_frequency", "motor_damping",
            "motor_force_limit", "motor_torque_limit", "cone_half_angle",
            "distance_min", "distance_max",
        ):
            if getattr(result, name) < 0.0:
                raise FixtureError(f"{path}.{name} must be >= 0")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", result.id) is None:
            raise FixtureError(
                f"{path}.id may contain only ASCII letters, digits, dot, underscore and dash"
            )
        if result.draw_size < 0.0:
            raise FixtureError(f"{path}.draw_size must be >= 0")
        if result.motor_state not in {"OFF", "VELOCITY", "POSITION"}:
            raise FixtureError(f"{path}.motor_state is unsupported: {result.motor_state}")
        if result.solver_velocity_steps > 255 or result.solver_position_steps > 255:
            raise FixtureError(f"{path} solver step overrides must be <= 255")
        for name, quat in (
            ("anchor_rotation_wxyz", result.anchor_rotation_wxyz),
            ("anchor_rotation_wxyz_a", result.anchor_rotation_wxyz_a),
            ("anchor_rotation_wxyz_b", result.anchor_rotation_wxyz_b),
        ):
            if sum(component * component for component in quat) <= 1.0e-20:
                raise FixtureError(f"{path}.{name} cannot be zero")
        return result


@dataclass(frozen=True)
class TimelineEvent:
    frame: int
    phase: str
    op: str
    body: str = ""
    values: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_data(cls, value: Any, path: str) -> "TimelineEvent":
        data = _mapping(value, path)
        _reject_unknown(data, {
            "frame", "phase", "op", "body", "linear_velocity", "angular_velocity",
            "impulse", "angular_impulse", "force", "torque", "gravity_factor",
            "active", "gravity",
        }, path)
        frame = _integer(data.get("frame"), f"{path}.frame", minimum=1)
        phase = _string(data.get("phase", "pre_step"), f"{path}.phase")
        if phase not in {"pre_step", "post_step"}:
            raise FixtureError(f"{path}.phase must be pre_step or post_step")
        op = _string(data.get("op"), f"{path}.op")
        supported = {
            "set_velocity", "add_impulse", "add_force", "set_gravity_factor",
            "activate", "set_world_gravity",
        }
        if op not in supported:
            raise FixtureError(f"{path}.op is unsupported: {op}")
        body = str(data.get("body", ""))
        if op != "set_world_gravity" and not body:
            raise FixtureError(f"{path}.body is required for {op}")
        values: dict[str, Any] = {}
        vector_fields = {
            "linear_velocity", "angular_velocity", "impulse", "angular_impulse",
            "force", "torque", "gravity",
        }
        for name in vector_fields:
            if name in data:
                values[name] = _vec(data[name], 3, f"{path}.{name}")
        if "gravity_factor" in data:
            values["gravity_factor"] = _number(data["gravity_factor"], f"{path}.gravity_factor")
        if "active" in data:
            values["active"] = _bool(data["active"], f"{path}.active")
        return cls(frame=frame, phase=phase, op=op, body=body, values=values)


@dataclass(frozen=True)
class AssertionSpec:
    kind: str
    parameters: Mapping[str, Any]

    @classmethod
    def from_data(cls, value: Any, path: str) -> "AssertionSpec":
        data = dict(_mapping(value, path))
        kind = _string(data.pop("kind", None), f"{path}.kind")
        supported = {
            "finite_all", "semi_implicit_free_fall", "constant_linear_motion",
            "impulse_delta_velocity", "body_state_near", "constraint_state_schema",
            "fixed_relative_transform", "point_anchor_coincidence", "distance_range",
            "distance_converges_to_range", "rotation_changed_min",
            "constraint_anchor_coincidence", "rotation_axis_only",
            "linear_axis_only", "cone_swing_limit",
            "constraint_value_in_range", "constraint_value_near",
        }
        if kind not in supported:
            raise FixtureError(f"{path}.kind is unsupported: {kind}")
        allowed_parameters = {
            "finite_all": set(),
            "semi_implicit_free_fall": {
                "body", "position_abs", "velocity_abs", "rel",
            },
            "constant_linear_motion": {
                "body", "position_abs", "velocity_abs", "rel",
            },
            "impulse_delta_velocity": {
                "body", "frame", "impulse", "velocity_abs", "rel",
            },
            "body_state_near": {
                "body", "frame", "position", "linear_velocity", "angular_velocity",
                "active", "sleeping", "abs", "rel",
            },
            "constraint_state_schema": {
                "constraint", "type", "current_value_kind", "enabled",
            },
            "fixed_relative_transform": {
                "constraint", "position_abs", "rotation_abs", "start_frame",
            },
            "point_anchor_coincidence": {
                "constraint", "distance_abs", "start_frame",
            },
            "distance_range": {
                "constraint", "minimum", "maximum", "distance_abs", "start_frame",
            },
            "distance_converges_to_range": {
                "constraint", "minimum", "maximum", "final_abs", "monotonic_abs",
            },
            "rotation_changed_min": {
                "body", "frame", "angle_min",
            },
            "constraint_anchor_coincidence": {
                "constraint", "distance_abs", "start_frame",
            },
            "rotation_axis_only": {
                "body", "frame", "axis", "off_axis_abs", "angle_min",
            },
            "linear_axis_only": {
                "body", "frame", "axis", "off_axis_abs", "displacement_min",
                "rotation_abs",
            },
            "cone_swing_limit": {
                "constraint", "angle_abs", "swing_min", "start_frame",
            },
            "constraint_value_in_range": {
                "constraint", "minimum", "maximum", "value_abs", "start_frame",
            },
            "constraint_value_near": {
                "constraint", "frame", "expected", "value_abs",
                "current_value_kind",
            },
        }
        _reject_unknown(data, allowed_parameters[kind], path)
        return cls(kind=kind, parameters=data)


@dataclass(frozen=True)
class Fixture:
    schema: str
    id: str
    title: str
    source: str
    tags: tuple[str, ...]
    world: WorldSpec
    bodies: tuple[BodySpec, ...]
    constraints: tuple[ConstraintSpec, ...]
    timeline: tuple[TimelineEvent, ...]
    sample_frames: tuple[int, ...]
    assertions: tuple[AssertionSpec, ...]
    path: Path
    content_hash: str

    @property
    def bodies_by_id(self) -> dict[str, BodySpec]:
        return {body.id: body for body in self.bodies}

    @property
    def constraints_by_id(self) -> dict[str, ConstraintSpec]:
        return {constraint.id: constraint for constraint in self.constraints}


def load_fixture(path: str | Path) -> Fixture:
    fixture_path = Path(path).resolve()
    try:
        raw = fixture_path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FixtureError(f"cannot read fixture {fixture_path}: {exc}") from exc
    data = _mapping(value, "fixture")
    _reject_unknown(data, {
        "schema", "id", "title", "source", "tags", "world", "bodies",
        "constraints", "timeline", "sample_frames", "assertions",
    }, "fixture")
    schema = _string(data.get("schema"), "fixture.schema")
    if schema != "hotools_jolt_fixture_v1":
        raise FixtureError(f"unsupported fixture schema: {schema}")
    fixture_id = _string(data.get("id"), "fixture.id")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", fixture_id) is None:
        raise FixtureError(
            "fixture.id may contain only ASCII letters, digits, dot, underscore and dash"
        )
    bodies = tuple(
        BodySpec.from_data(item, f"fixture.bodies[{index}]")
        for index, item in enumerate(_sequence(data.get("bodies", []), "fixture.bodies"))
    )
    if not bodies:
        raise FixtureError("fixture.bodies cannot be empty")
    body_ids = [body.id for body in bodies]
    if len(body_ids) != len(set(body_ids)):
        raise FixtureError("fixture.bodies contains duplicate ids")
    world = WorldSpec.from_data(data.get("world", {}))
    timeline = tuple(
        TimelineEvent.from_data(item, f"fixture.timeline[{index}]")
        for index, item in enumerate(_sequence(data.get("timeline", []), "fixture.timeline"))
    )
    for event in timeline:
        if event.frame > world.frames:
            raise FixtureError(
                f"timeline event at frame {event.frame} exceeds world.frames={world.frames}"
            )
        if event.body and event.body not in set(body_ids):
            raise FixtureError(f"timeline event references unknown body: {event.body}")
    sample_frames = tuple(
        _integer(item, f"fixture.sample_frames[{index}]", minimum=0)
        for index, item in enumerate(
            _sequence(data.get("sample_frames", [0, world.frames]), "fixture.sample_frames")
        )
    )
    if not sample_frames:
        raise FixtureError("fixture.sample_frames cannot be empty")
    if tuple(sorted(set(sample_frames))) != sample_frames:
        raise FixtureError("fixture.sample_frames must be sorted and unique")
    if sample_frames[0] != 0:
        raise FixtureError("fixture.sample_frames must include frame 0")
    if sample_frames[-1] > world.frames:
        raise FixtureError("fixture.sample_frames exceeds world.frames")
    assertions = tuple(
        AssertionSpec.from_data(item, f"fixture.assertions[{index}]")
        for index, item in enumerate(
            _sequence(data.get("assertions", []), "fixture.assertions")
        )
    )
    if not assertions:
        raise FixtureError("fixture.assertions cannot be empty")
    constraints = tuple(
        ConstraintSpec.from_data(item, f"fixture.constraints[{index}]")
        for index, item in enumerate(
            _sequence(data.get("constraints", []), "fixture.constraints")
        )
    )
    constraint_ids = [constraint.id for constraint in constraints]
    if len(constraint_ids) != len(set(constraint_ids)):
        raise FixtureError("fixture.constraints contains duplicate ids")
    known_body_refs = set(body_ids) | {"WORLD"}
    for constraint in constraints:
        if constraint.body_a not in known_body_refs:
            raise FixtureError(
                f"constraint {constraint.id} references unknown body_a: {constraint.body_a}"
            )
        if constraint.body_b not in known_body_refs:
            raise FixtureError(
                f"constraint {constraint.id} references unknown body_b: {constraint.body_b}"
            )
    tags = tuple(
        _string(item, f"fixture.tags[{index}]")
        for index, item in enumerate(_sequence(data.get("tags", []), "fixture.tags"))
    )
    return Fixture(
        schema=schema,
        id=fixture_id,
        title=_string(data.get("title", fixture_id), "fixture.title"),
        source=_string(data.get("source"), "fixture.source"),
        tags=tags,
        world=world,
        bodies=bodies,
        constraints=constraints,
        timeline=timeline,
        sample_frames=sample_frames,
        assertions=assertions,
        path=fixture_path,
        content_hash=hashlib.sha256(raw).hexdigest(),
    )


def discover_fixtures(root: str | Path) -> list[Path]:
    fixture_root = Path(root)
    if not fixture_root.is_dir():
        raise FixtureError(f"fixture root does not exist: {fixture_root}")
    return sorted(path.resolve() for path in fixture_root.rglob("*.json"))
