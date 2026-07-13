"""Source-aligned Center static, frame-pose, and persistent reset contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from .mesh_baseline import MC2_VERTEX_MOVE
from .static_data import MC2ProxyStaticSpec
from .setups.mesh_cloth.final_proxy import mc2_world_rotation_xyzw


IDENTITY_QUATERNION = (0.0, 0.0, 0.0, 1.0)


def _f32(value) -> np.float32:
    result = np.float32(value)
    if not np.isfinite(result):
        raise ValueError("Center value cannot contain NaN/Inf")
    return result


def _vector(values, width: int, name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if len(result) != width or not all(math.isfinite(value) for value in result):
        raise ValueError(f"{name} must contain {width} finite values")
    return result


def _normalize3(values, name: str) -> tuple[float, float, float]:
    value = _vector(values, 3, name)
    length = math.sqrt(sum(component * component for component in value))
    if length <= 1.0e-8:
        raise ValueError(f"{name} must be non-zero")
    return tuple(component / length for component in value)


def _unit_quaternion(values, name: str) -> tuple[float, float, float, float]:
    value = _vector(values, 4, name)
    length = math.sqrt(sum(component * component for component in value))
    if length <= 1.0e-8:
        raise ValueError(f"{name} must be non-zero")
    return tuple(component / length for component in value)


def _require_unit_quaternion(values, name: str) -> tuple[float, float, float, float]:
    value = _vector(values, 4, name)
    length = math.sqrt(sum(component * component for component in value))
    if not math.isclose(length, 1.0, rel_tol=1.0e-5, abs_tol=1.0e-6):
        raise ValueError(f"{name} must be a unit quaternion")
    return value


def _quaternion_multiply(left, right):
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )


def _quaternion_inverse(value):
    x, y, z, w = value
    return (-x, -y, -z, w)


def _rotate(value, vector):
    q = _unit_quaternion(value, "quaternion")
    vx, vy, vz = vector
    rotated = _quaternion_multiply(
        _quaternion_multiply(q, (vx, vy, vz, 0.0)),
        _quaternion_inverse(q),
    )
    return rotated[:3]


def _signature(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class MC2CenterStaticSpec:
    task_id: str
    proxy_signature: str
    fixed_indices: tuple[int, ...]
    local_center_position: tuple[float, float, float]
    initial_local_gravity_direction: tuple[float, float, float]
    center_static_signature: str
    schema_version: int = 0

    def debug_dict(self) -> dict:
        return {
            "fixed_indices": self.fixed_indices,
            "local_center_position": self.local_center_position,
            "initial_local_gravity_direction": self.initial_local_gravity_direction,
            "center_static_signature": self.center_static_signature,
        }


def build_mc2_center_static(
    proxy: MC2ProxyStaticSpec,
    *,
    vertex_bind_pose_rotations,
    world_gravity_direction,
) -> MC2CenterStaticSpec:
    if not isinstance(proxy, MC2ProxyStaticSpec):
        raise TypeError("proxy must be MC2ProxyStaticSpec")
    bind_rotations = tuple(
        _unit_quaternion(value, f"vertex_bind_pose_rotations[{index}]")
        for index, value in enumerate(vertex_bind_pose_rotations)
    )
    if len(bind_rotations) != proxy.vertex_count:
        raise ValueError("vertex bind rotation count mismatch")

    neighbors = [set() for _ in range(proxy.vertex_count)]
    for first, second in proxy.edges:
        neighbors[first].add(second)
        neighbors[second].add(first)
    fixed = []
    for index, attribute in enumerate(proxy.vertex_attributes):
        if attribute & MC2_VERTEX_MOVE:
            continue
        adjacent = neighbors[index]
        if adjacent and all(not (proxy.vertex_attributes[item] & MC2_VERTEX_MOVE) for item in adjacent):
            continue
        fixed.append(index)

    if fixed:
        center = tuple(
            sum(proxy.local_positions[index][axis] for index in fixed) / len(fixed)
            for axis in range(3)
        )
        normal_sum = np.zeros(3, dtype=np.float64)
        tangent_sum = np.zeros(3, dtype=np.float64)
        for index in fixed:
            local_rotation = mc2_world_rotation_xyzw(
                proxy.local_normals[index], proxy.local_tangents[index]
            )
            corrected = _unit_quaternion(
                _quaternion_multiply(local_rotation, bind_rotations[index]),
                "corrected center rotation",
            )
            normal_sum += _rotate(corrected, (0.0, 1.0, 0.0))
            tangent_sum += _rotate(corrected, (0.0, 0.0, 1.0))
        center_rotation = mc2_world_rotation_xyzw(
            _normalize3(normal_sum, "center normal"),
            _normalize3(tangent_sum, "center tangent"),
        )
        gravity = _rotate(
            _quaternion_inverse(center_rotation),
            _normalize3(world_gravity_direction, "world_gravity_direction"),
        )
    else:
        center = (0.0, 0.0, 0.0)
        gravity = (0.0, -1.0, 0.0)

    payload = {
        "schema_version": 0,
        "task_id": proxy.task_id,
        "proxy_signature": proxy.proxy_signature,
        "fixed_indices": fixed,
        "local_center_position": center,
        "initial_local_gravity_direction": gravity,
    }
    return MC2CenterStaticSpec(
        task_id=proxy.task_id,
        proxy_signature=proxy.proxy_signature,
        fixed_indices=tuple(fixed),
        local_center_position=tuple(float(value) for value in center),
        initial_local_gravity_direction=tuple(float(value) for value in gravity),
        center_static_signature=_signature(payload),
    )


def pack_mc2_center_static(spec: MC2CenterStaticSpec) -> dict[str, np.ndarray]:
    if not isinstance(spec, MC2CenterStaticSpec):
        raise TypeError("spec must be MC2CenterStaticSpec")
    arrays = {
        "fixed_indices": np.ascontiguousarray(spec.fixed_indices, dtype=np.int32),
        "local_center_position": np.ascontiguousarray(spec.local_center_position, dtype=np.float32),
        "initial_local_gravity_direction": np.ascontiguousarray(
            spec.initial_local_gravity_direction, dtype=np.float32
        ),
    }
    for value in arrays.values():
        value.setflags(write=False)
    return arrays


@dataclass(frozen=True)
class MC2CenterFramePoseSpec:
    frame: int
    generation: int
    component_identity: str
    component_world_position: tuple[float, float, float]
    component_world_rotation_xyzw: tuple[float, float, float, float]
    component_world_scale: tuple[float, float, float]
    anchor_identity: str = ""
    anchor_world_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    anchor_world_rotation_xyzw: tuple[float, float, float, float] = IDENTITY_QUATERNION

    def __post_init__(self) -> None:
        if not self.component_identity:
            raise ValueError("Center frame requires stable component identity")
        _vector(self.component_world_position, 3, "component_world_position")
        _require_unit_quaternion(self.component_world_rotation_xyzw, "component_world_rotation_xyzw")
        _vector(self.component_world_scale, 3, "component_world_scale")
        _vector(self.anchor_world_position, 3, "anchor_world_position")
        _require_unit_quaternion(self.anchor_world_rotation_xyzw, "anchor_world_rotation_xyzw")


@dataclass
class MC2CenterPersistentState:
    center_static_signature: str
    initialized: bool = False
    reset_count: int = 0
    old_component_world_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    old_component_world_rotation_xyzw: tuple[float, float, float, float] = IDENTITY_QUATERNION
    old_component_world_scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    old_frame_world_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    old_frame_world_rotation_xyzw: tuple[float, float, float, float] = IDENTITY_QUATERNION
    old_world_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    old_world_rotation_xyzw: tuple[float, float, float, float] = IDENTITY_QUATERNION
    smoothing_velocity: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def reset(self, frame_pose: MC2CenterFramePoseSpec, center_position, center_rotation_xyzw) -> None:
        if not isinstance(frame_pose, MC2CenterFramePoseSpec):
            raise TypeError("frame_pose must be MC2CenterFramePoseSpec")
        center_position = _vector(center_position, 3, "center_position")
        center_rotation = _unit_quaternion(center_rotation_xyzw, "center_rotation_xyzw")
        self.old_component_world_position = tuple(frame_pose.component_world_position)
        self.old_component_world_rotation_xyzw = _unit_quaternion(
            frame_pose.component_world_rotation_xyzw, "component_world_rotation_xyzw"
        )
        self.old_component_world_scale = tuple(frame_pose.component_world_scale)
        self.old_frame_world_position = center_position
        self.old_frame_world_rotation_xyzw = center_rotation
        self.old_world_position = center_position
        self.old_world_rotation_xyzw = center_rotation
        self.smoothing_velocity = (0.0, 0.0, 0.0)
        self.reset_count += 1
        self.initialized = True


@dataclass(frozen=True)
class MC2CenterStepInputSpec:
    simulation_delta_time: float
    frame_interpolation: float
    old_frame_world_position: tuple[float, float, float]
    frame_world_position: tuple[float, float, float]
    old_frame_world_rotation_xyzw: tuple[float, float, float, float]
    frame_world_rotation_xyzw: tuple[float, float, float, float]
    old_frame_world_scale: tuple[float, float, float]
    frame_world_scale: tuple[float, float, float]
    old_world_position: tuple[float, float, float]
    old_world_rotation_xyzw: tuple[float, float, float, float]
    initial_scale: tuple[float, float, float]
    negative_scale_direction: tuple[float, float, float]
    velocity_weight: float
    distance_weight: float = 1.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.simulation_delta_time) or self.simulation_delta_time <= 0.0:
            raise ValueError("simulation_delta_time must be finite and positive")
        if not 0.0 <= self.frame_interpolation <= 1.0:
            raise ValueError("frame_interpolation must be in 0..1")
        for name in (
            "old_frame_world_position", "frame_world_position",
            "old_frame_world_scale", "frame_world_scale",
            "old_world_position", "initial_scale", "negative_scale_direction",
        ):
            _vector(getattr(self, name), 3, name)
        for name in ("old_frame_world_rotation_xyzw", "frame_world_rotation_xyzw", "old_world_rotation_xyzw"):
            _require_unit_quaternion(getattr(self, name), name)
        if any(abs(value) <= 1.0e-8 for value in self.initial_scale):
            raise ValueError("initial_scale cannot contain zero")
        if any(float(value) not in (-1.0, 1.0) for value in self.negative_scale_direction):
            raise ValueError("negative_scale_direction must contain only -1 or 1")
        if not 0.0 <= self.velocity_weight <= 1.0 or not 0.0 <= self.distance_weight <= 1.0:
            raise ValueError("Center weights must be in 0..1")


@dataclass(frozen=True)
class MC2CenterStepResult:
    frame_interpolation: float
    now_world_position: tuple[float, float, float]
    now_world_rotation_xyzw: tuple[float, float, float, float]
    step_vector: tuple[float, float, float]
    step_rotation_xyzw: tuple[float, float, float, float]
    step_move_inertia_ratio: float
    step_rotation_inertia_ratio: float
    inertia_vector: tuple[float, float, float]
    inertia_rotation_xyzw: tuple[float, float, float, float]
    angular_velocity: float
    rotation_axis: tuple[float, float, float]
    scale_ratio: float
    gravity_dot: float
    gravity_ratio: float
    velocity_weight: float
    blend_weight: float


def _f32_vector(values, width: int, name: str) -> np.ndarray:
    result = np.asarray(values, dtype=np.float32)
    if result.shape != (width,) or not np.isfinite(result).all():
        raise ValueError(f"{name} must contain {width} finite values")
    return result


def _normalize_quaternion_f32(value: np.ndarray) -> np.ndarray:
    length = _f32(np.linalg.norm(value))
    if length <= _f32(1.0e-8):
        raise ValueError("Center quaternion cannot be zero")
    return np.asarray(value / length, dtype=np.float32)


def _quaternion_slerp_f32(first: np.ndarray, second: np.ndarray, ratio) -> np.ndarray:
    ratio = _f32(ratio)
    target = second.copy()
    cosine = _f32(np.dot(first, target))
    if cosine < 0.0:
        target = -target
        cosine = -cosine
    if cosine > _f32(0.9995):
        return _normalize_quaternion_f32(first + (target - first) * ratio)
    angle = _f32(np.arccos(np.clip(cosine, -1.0, 1.0)))
    sine = _f32(np.sin(angle))
    first_weight = _f32(np.sin((_f32(1.0) - ratio) * angle) / sine)
    second_weight = _f32(np.sin(ratio * angle) / sine)
    return _normalize_quaternion_f32(first * first_weight + target * second_weight)


def _quaternion_multiply_f32(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return np.asarray((
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    ), dtype=np.float32)


def _rotate_f32(rotation: np.ndarray, vector: np.ndarray) -> np.ndarray:
    xyz = rotation[:3]
    twice_cross = _f32(2.0) * np.cross(xyz, vector)
    return np.asarray(
        vector + rotation[3] * twice_cross + np.cross(xyz, twice_cross),
        dtype=np.float32,
    )


def evaluate_mc2_center_step(
    step: MC2CenterStepInputSpec,
    runtime_parameters,
    *,
    initial_local_gravity_direction,
) -> MC2CenterStepResult:
    from .runtime_parameters import MC2_RUNTIME_FLOAT_FIELDS, MC2RuntimeParametersV0

    if not isinstance(step, MC2CenterStepInputSpec):
        raise TypeError("step must be MC2CenterStepInputSpec")
    if not isinstance(runtime_parameters, MC2RuntimeParametersV0):
        raise TypeError("runtime_parameters must be MC2RuntimeParametersV0")
    parameter = dict(zip(MC2_RUNTIME_FLOAT_FIELDS, runtime_parameters.float_values))
    dt = _f32(step.simulation_delta_time)
    ratio = _f32(step.frame_interpolation)
    old_position = _f32_vector(step.old_frame_world_position, 3, "old_frame_world_position")
    frame_position = _f32_vector(step.frame_world_position, 3, "frame_world_position")
    now_position = old_position + (frame_position - old_position) * ratio
    old_rotation = _f32_vector(step.old_frame_world_rotation_xyzw, 4, "old_frame_world_rotation_xyzw")
    frame_rotation = _f32_vector(step.frame_world_rotation_xyzw, 4, "frame_world_rotation_xyzw")
    now_rotation = _quaternion_slerp_f32(old_rotation, frame_rotation, ratio)
    previous_position = _f32_vector(step.old_world_position, 3, "old_world_position")
    previous_rotation = _f32_vector(step.old_world_rotation_xyzw, 4, "old_world_rotation_xyzw")
    step_vector = np.asarray(now_position - previous_position, dtype=np.float32)
    inverse_previous = np.asarray(
        (-previous_rotation[0], -previous_rotation[1], -previous_rotation[2], previous_rotation[3]),
        dtype=np.float32,
    )
    step_rotation = _normalize_quaternion_f32(
        _quaternion_multiply_f32(now_rotation, inverse_previous)
    )
    cosine = np.clip(abs(_f32(np.dot(previous_rotation, now_rotation))), 0.0, 1.0)
    step_angle = _f32(2.0) * _f32(np.arccos(cosine))

    move_inertia = _f32(1.0) - _f32(parameter["local_inertia"])
    local_vector = step_vector * (_f32(1.0) - move_inertia)
    local_speed = _f32(np.linalg.norm(local_vector)) / dt
    movement_limit = _f32(parameter["local_movement_speed_limit"])
    if local_speed > movement_limit and movement_limit >= 0.0:
        limit_ratio = movement_limit / local_speed
        move_inertia = _f32(1.0) + (move_inertia - _f32(1.0)) * limit_ratio

    rotation_inertia = _f32(1.0) - _f32(parameter["local_inertia"])
    local_angle_speed = _f32(np.degrees(step_angle * (_f32(1.0) - rotation_inertia) / dt))
    rotation_limit = _f32(parameter["local_rotation_speed_limit"])
    if local_angle_speed > rotation_limit and rotation_limit >= 0.0:
        limit_ratio = rotation_limit / local_angle_speed
        rotation_inertia = _f32(1.0) + (rotation_inertia - _f32(1.0)) * limit_ratio

    inertia_vector = np.asarray(step_vector * move_inertia, dtype=np.float32)
    identity = np.asarray(IDENTITY_QUATERNION, dtype=np.float32)
    inertia_rotation = _quaternion_slerp_f32(identity, step_rotation, rotation_inertia)
    angular_velocity = step_angle / dt
    if angular_velocity > _f32(1.0e-8):
        axis_length = _f32(np.linalg.norm(step_rotation[:3]))
        rotation_axis = (
            np.asarray(step_rotation[:3] / axis_length, dtype=np.float32)
            if axis_length > _f32(1.0e-8)
            else np.zeros(3, dtype=np.float32)
        )
    else:
        rotation_axis = np.zeros(3, dtype=np.float32)

    old_scale = _f32_vector(step.old_frame_world_scale, 3, "old_frame_world_scale")
    frame_scale = _f32_vector(step.frame_world_scale, 3, "frame_world_scale")
    world_scale = old_scale + (frame_scale - old_scale) * ratio
    initial_scale = _f32_vector(step.initial_scale, 3, "initial_scale")
    scale_ratio = max(
        _f32(np.linalg.norm(world_scale)) / _f32(np.linalg.norm(initial_scale)),
        _f32(1.0e-6),
    )

    initial_gravity = _f32_vector(
        initial_local_gravity_direction, 3, "initial_local_gravity_direction"
    )
    initial_gravity[1] *= _f32(step.negative_scale_direction[1])
    world_falloff = _rotate_f32(now_rotation, initial_gravity)
    world_gravity = np.asarray(
        (parameter["gravity_direction_x"], parameter["gravity_direction_y"], parameter["gravity_direction_z"]),
        dtype=np.float32,
    )
    gravity_dot = _f32(1.0)
    if _f32(np.dot(world_gravity, world_gravity)) > _f32(1.0e-8):
        gravity_dot = np.clip(
            _f32(np.dot(world_falloff, world_gravity)) * _f32(0.5) + _f32(0.5),
            _f32(0.0),
            _f32(1.0),
        )
    gravity_ratio = _f32(1.0)
    gravity = _f32(parameter["gravity"])
    gravity_falloff = _f32(parameter["gravity_falloff"])
    if gravity > _f32(1.0e-6) and gravity_falloff > _f32(1.0e-6):
        minimum = np.clip(_f32(1.0) - gravity_falloff, _f32(0.0), _f32(1.0))
        falloff = np.clip(_f32(1.0) - gravity_dot, _f32(0.0), _f32(1.0))
        gravity_ratio = minimum + (_f32(1.0) - minimum) * falloff

    velocity_weight = _f32(step.velocity_weight)
    if velocity_weight < _f32(1.0):
        stabilization = _f32(parameter["stabilization_time_after_reset"])
        added = dt / stabilization if stabilization > _f32(1.0e-6) else _f32(1.0)
        velocity_weight = np.clip(velocity_weight + added, _f32(0.0), _f32(1.0))
    blend_weight = np.clip(
        velocity_weight * _f32(parameter["blend_weight"]) * _f32(step.distance_weight),
        _f32(0.0),
        _f32(1.0),
    )

    vector = lambda value: tuple(float(item) for item in value)
    return MC2CenterStepResult(
        frame_interpolation=float(ratio),
        now_world_position=vector(now_position),
        now_world_rotation_xyzw=vector(now_rotation),
        step_vector=vector(step_vector),
        step_rotation_xyzw=vector(step_rotation),
        step_move_inertia_ratio=float(move_inertia),
        step_rotation_inertia_ratio=float(rotation_inertia),
        inertia_vector=vector(inertia_vector),
        inertia_rotation_xyzw=vector(inertia_rotation),
        angular_velocity=float(angular_velocity),
        rotation_axis=vector(rotation_axis),
        scale_ratio=float(scale_ratio),
        gravity_dot=float(gravity_dot),
        gravity_ratio=float(gravity_ratio),
        velocity_weight=float(velocity_weight),
        blend_weight=float(blend_weight),
    )


__all__ = [
    "MC2CenterFramePoseSpec",
    "MC2CenterPersistentState",
    "MC2CenterStepInputSpec",
    "MC2CenterStepResult",
    "MC2CenterStaticSpec",
    "build_mc2_center_static",
    "evaluate_mc2_center_step",
    "pack_mc2_center_static",
]
