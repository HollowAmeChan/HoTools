"""Source-aligned Bone Line proxy rotation and transform output contract."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np


MC2_VERTEX_FIXED = 0x01
MC2_VERTEX_MOVE = 0x02
MC2_VERTEX_ZERO_DISTANCE = 0x20
IDENTITY_QUATERNION = (0.0, 0.0, 0.0, 1.0)


def _signature(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _array(values, shape, name: str, dtype=np.float32) -> np.ndarray:
    result = np.ascontiguousarray(values, dtype=dtype)
    if result.shape != shape:
        raise ValueError(f"{name} must have shape {shape}")
    if np.issubdtype(result.dtype, np.floating) and not np.all(np.isfinite(result)):
        raise ValueError(f"{name} cannot contain NaN/Inf")
    return result


def _normalize_vector(value: np.ndarray) -> np.ndarray:
    length = np.float32(np.linalg.norm(value))
    if length <= np.float32(0.0):
        raise ValueError("cannot normalize a zero vector")
    return np.asarray(value / length, dtype=np.float32)


def _normalize_quaternion(value: np.ndarray) -> np.ndarray:
    length = np.float32(np.linalg.norm(value))
    if length <= np.float32(0.0):
        raise ValueError("cannot normalize a zero quaternion")
    return np.asarray(value / length, dtype=np.float32)


def _quaternion_multiply(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lx, ly, lz, lw = (np.float32(value) for value in left)
    rx, ry, rz, rw = (np.float32(value) for value in right)
    return np.asarray((
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    ), dtype=np.float32)


def _quaternion_inverse(value: np.ndarray) -> np.ndarray:
    result = np.asarray((-value[0], -value[1], -value[2], value[3]), dtype=np.float32)
    return _normalize_quaternion(result)


def _rotate(rotation: np.ndarray, vector: np.ndarray) -> np.ndarray:
    q = _normalize_quaternion(rotation)
    pure = np.asarray((vector[0], vector[1], vector[2], 0.0), dtype=np.float32)
    return _quaternion_multiply(
        _quaternion_multiply(q, pure), _quaternion_inverse(q)
    )[:3]


def _slerp(first: np.ndarray, second: np.ndarray, ratio) -> np.ndarray:
    ratio = np.float32(ratio)
    first = _normalize_quaternion(first)
    target = _normalize_quaternion(second)
    dot = np.float32(np.dot(first, target))
    if dot < np.float32(0.0):
        target = -target
        dot = -dot
    dot = np.clip(dot, np.float32(-1.0), np.float32(1.0))
    if dot > np.float32(0.9995):
        return _normalize_quaternion(first + (target - first) * ratio)
    theta = np.float32(np.arccos(dot))
    sin_theta = np.float32(np.sin(theta))
    first_weight = np.float32(np.sin((np.float32(1.0) - ratio) * theta) / sin_theta)
    second_weight = np.float32(np.sin(ratio * theta) / sin_theta)
    return _normalize_quaternion(first * first_weight + target * second_weight)


def _from_to_rotation(first: np.ndarray, second: np.ndarray, ratio=1.0) -> np.ndarray:
    first = _normalize_vector(first)
    second = _normalize_vector(second)
    cosine = np.clip(np.float32(np.dot(first, second)), np.float32(-1.0), np.float32(1.0))
    angle = np.float32(np.arccos(cosine))
    axis = np.asarray(np.cross(first, second), dtype=np.float32)
    if abs(np.float32(1.0) + cosine) < np.float32(1.0e-6):
        angle = np.float32(math.pi)
        if first[0] > first[1] and first[0] > first[2]:
            axis = np.asarray(np.cross(first, (0.0, 1.0, 0.0)), dtype=np.float32)
        else:
            axis = np.asarray(np.cross(first, (1.0, 0.0, 0.0)), dtype=np.float32)
    elif abs(np.float32(1.0) - cosine) < np.float32(1.0e-6):
        return np.asarray(IDENTITY_QUATERNION, dtype=np.float32)
    axis = _normalize_vector(axis)
    half_angle = np.float32(angle * np.float32(ratio) * np.float32(0.5))
    sine = np.float32(np.sin(half_angle))
    return _normalize_quaternion(np.asarray((
        axis[0] * sine,
        axis[1] * sine,
        axis[2] * sine,
        np.float32(np.cos(half_angle)),
    ), dtype=np.float32))


def _is_zero_distance(value: np.ndarray) -> bool:
    return np.float32(np.linalg.norm(value)) < np.float32(1.0e-8)


@dataclass(frozen=True)
class MC2BoneLineRotationResult:
    proxy_rotations: tuple[tuple[float, float, float, float], ...]
    world_positions: tuple[tuple[float, float, float], ...]
    world_rotations: tuple[tuple[float, float, float, float], ...]
    local_positions: tuple[tuple[float, float, float], ...]
    local_rotations: tuple[tuple[float, float, float, float], ...]
    result_signature: str
    schema_version: int = 0

    def debug_dict(self) -> dict:
        return {
            "proxy_rotations": self.proxy_rotations,
            "world_positions": self.world_positions,
            "world_rotations": self.world_rotations,
            "local_positions": self.local_positions,
            "local_rotations": self.local_rotations,
            "result_signature": self.result_signature,
            "schema_version": self.schema_version,
        }


def evaluate_mc2_bone_line_rotation(
    *,
    attributes,
    positions,
    rotations,
    base_positions,
    base_rotations,
    vertex_local_positions,
    vertex_local_rotations,
    vertex_to_transform_rotations,
    parent_indices,
    transform_scales,
    transform_local_positions,
    transform_local_rotations,
    child_ranges,
    child_data,
    baseline_data,
    rotational_interpolation,
    root_rotation,
    animation_pose_ratio,
    blend_weight,
) -> MC2BoneLineRotationResult:
    """Evaluate the positive-scale, no-triangle Bone Line post path."""

    count = len(positions)
    attrs = _array(attributes, (count,), "attributes", np.uint8)
    work_positions = _array(positions, (count, 3), "positions").copy()
    work_rotations = _array(rotations, (count, 4), "rotations").copy()
    base_positions = _array(base_positions, (count, 3), "base_positions")
    base_rotations = _array(base_rotations, (count, 4), "base_rotations")
    local_positions = _array(
        vertex_local_positions, (count, 3), "vertex_local_positions"
    )
    local_rotations = _array(
        vertex_local_rotations, (count, 4), "vertex_local_rotations"
    )
    vertex_to_transform = _array(
        vertex_to_transform_rotations,
        (count, 4),
        "vertex_to_transform_rotations",
    )
    parents = _array(parent_indices, (count,), "parent_indices", np.int32)
    scales = _array(transform_scales, (count, 3), "transform_scales")
    output_local_positions = _array(
        transform_local_positions,
        (count, 3),
        "transform_local_positions",
    ).copy()
    output_local_rotations = _array(
        transform_local_rotations,
        (count, 4),
        "transform_local_rotations",
    ).copy()
    ranges = _array(child_ranges, (count, 2), "child_ranges", np.int32)
    children = np.ascontiguousarray(child_data, dtype=np.int32)
    baseline = np.ascontiguousarray(baseline_data, dtype=np.int32)
    if any(value < 0 or value >= count for value in parents if value >= 0):
        raise ValueError("parent index out of range")
    if any(value < 0 or value >= count for value in children):
        raise ValueError("child index out of range")
    if any(value < 0 or value >= count for value in baseline):
        raise ValueError("baseline index out of range")
    if any(start < 0 or amount < 0 or start + amount > len(children) for start, amount in ranges):
        raise ValueError("child range out of bounds")
    if np.any(np.abs(scales) <= np.float32(1.0e-8)):
        raise ValueError("transform scale cannot contain zero")
    average_rate = np.float32(rotational_interpolation)
    root_rate = np.float32(root_rotation)
    animation_ratio = np.float32(animation_pose_ratio)
    blend = np.float32(blend_weight)
    for value, name in (
        (average_rate, "rotational_interpolation"),
        (root_rate, "root_rotation"),
        (animation_ratio, "animation_pose_ratio"),
        (blend, "blend_weight"),
    ):
        if not np.isfinite(value) or value < 0.0 or value > 1.0:
            raise ValueError(f"{name} must be in 0..1")

    for index in baseline:
        index = int(index)
        position = work_positions[index]
        rotation = _normalize_quaternion(work_rotations[index])
        attribute = int(attrs[index])
        child_start, child_count = (int(value) for value in ranges[index])
        base_position = base_positions[index]
        base_rotation = _normalize_quaternion(base_rotations[index])
        inverse_base_rotation = _quaternion_inverse(base_rotation)
        if child_count > 0 and attribute & (MC2_VERTEX_FIXED | MC2_VERTEX_MOVE):
            original_sum = np.zeros(3, dtype=np.float32)
            current_sum = np.zeros(3, dtype=np.float32)
            for child_offset in range(child_count):
                child = int(children[child_start + child_offset])
                child_attribute = int(attrs[child])
                zero_distance = bool(child_attribute & MC2_VERTEX_ZERO_DISTANCE)
                child_base_local_position = _rotate(
                    inverse_base_rotation,
                    base_positions[child] - base_position,
                )
                child_base_local_rotation = _quaternion_multiply(
                    inverse_base_rotation,
                    _normalize_quaternion(base_rotations[child]),
                )
                child_local_position = np.asarray(
                    local_positions[child]
                    + (child_base_local_position - local_positions[child]) * animation_ratio,
                    dtype=np.float32,
                )
                child_local_rotation = _slerp(
                    local_rotations[child],
                    child_base_local_rotation,
                    animation_ratio,
                )
                original_vector = (
                    np.zeros(3, dtype=np.float32)
                    if zero_distance
                    else _rotate(rotation, child_local_position)
                )
                original_sum += original_vector
                if child_attribute & MC2_VERTEX_MOVE:
                    current_vector = work_positions[child] - position
                    current_sum += current_vector
                    child_rotation = _quaternion_multiply(rotation, child_local_rotation)
                    if not zero_distance:
                        child_rotation = _quaternion_multiply(
                            _from_to_rotation(original_vector, current_vector),
                            child_rotation,
                        )
                    work_rotations[child] = _normalize_quaternion(child_rotation)
                else:
                    current_sum += original_vector
            ratio = average_rate if attribute & MC2_VERTEX_MOVE else root_rate
            adjustment = (
                np.asarray(IDENTITY_QUATERNION, dtype=np.float32)
                if _is_zero_distance(original_sum) or _is_zero_distance(current_sum)
                else _from_to_rotation(original_sum, current_sum, ratio)
            )
            rotation = _quaternion_multiply(adjustment, rotation)
        work_rotations[index] = _slerp(base_rotation, rotation, blend)

    world_positions = work_positions.copy()
    world_rotations = np.empty_like(work_rotations)
    for index in range(count):
        world_rotations[index] = _normalize_quaternion(
            _quaternion_multiply(work_rotations[index], vertex_to_transform[index])
        )
    for index, parent in enumerate(parents):
        parent = int(parent)
        if parent < 0 or not (int(attrs[index]) & MC2_VERTEX_MOVE):
            continue
        inverse_parent = _quaternion_inverse(world_rotations[parent])
        output_local_positions[index] = (
            _rotate(inverse_parent, world_positions[index] - world_positions[parent])
            / scales[parent]
        )
        output_local_rotations[index] = _normalize_quaternion(
            _quaternion_multiply(inverse_parent, world_rotations[index])
        )

    payload = {
        "schema_version": 0,
        "proxy_rotations": work_rotations.tolist(),
        "world_positions": world_positions.tolist(),
        "world_rotations": world_rotations.tolist(),
        "local_positions": output_local_positions.tolist(),
        "local_rotations": output_local_rotations.tolist(),
    }
    return MC2BoneLineRotationResult(
        proxy_rotations=tuple(tuple(float(value) for value in row) for row in work_rotations),
        world_positions=tuple(tuple(float(value) for value in row) for row in world_positions),
        world_rotations=tuple(tuple(float(value) for value in row) for row in world_rotations),
        local_positions=tuple(tuple(float(value) for value in row) for row in output_local_positions),
        local_rotations=tuple(tuple(float(value) for value in row) for row in output_local_rotations),
        result_signature=_signature(payload),
    )


__all__ = [
    "MC2BoneLineRotationResult",
    "evaluate_mc2_bone_line_rotation",
]
