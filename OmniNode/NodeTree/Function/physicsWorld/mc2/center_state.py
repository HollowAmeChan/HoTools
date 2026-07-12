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


__all__ = [
    "MC2CenterFramePoseSpec",
    "MC2CenterPersistentState",
    "MC2CenterStaticSpec",
    "build_mc2_center_static",
    "pack_mc2_center_static",
]
