"""Source-aligned Bone Line proxy rotation and transform output contract."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import numpy as np

from ..utils.math3d import (
    look_rotation_f32 as _look_rotation,
    normalize_quaternion_f32 as _normalize_quaternion,
    normalize_vector_f32 as _normalize_vector,
    quaternion_from_to_f32 as _from_to_rotation,
    quaternion_inverse_f32 as _quaternion_inverse,
    quaternion_multiply_f32 as _quaternion_multiply,
    quaternion_slerp_f32 as _slerp,
    rotate_vector_f32 as _rotate,
)


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


def _is_zero_distance(value: np.ndarray) -> bool:
    return np.float32(np.linalg.norm(value)) < np.float32(1.0e-8)


def _triangle_tangent(positions: np.ndarray, uvs: np.ndarray) -> np.ndarray:
    distance_ba = positions[1] - positions[0]
    distance_ca = positions[2] - positions[0]
    uv_ba = uvs[1] - uvs[0]
    uv_ca = uvs[2] - uvs[0]
    area = np.float32(uv_ba[0] * uv_ca[1] - uv_ba[1] * uv_ca[0])
    if area == np.float32(0.0):
        area = np.float32(1.0)
    delta = np.float32(1.0) / area
    tangent = -np.asarray(
        distance_ba * uv_ca[1] + distance_ca * -uv_ba[1],
        dtype=np.float32,
    ) * delta
    length = np.float32(np.linalg.norm(tangent))
    return (
        np.zeros(3, dtype=np.float32)
        if length <= np.float32(0.0)
        else np.asarray(tangent / length, dtype=np.float32)
    )


def _write_world_local(
    *,
    attributes: np.ndarray,
    positions: np.ndarray,
    rotations: np.ndarray,
    vertex_to_transform: np.ndarray,
    parents: np.ndarray,
    scales: np.ndarray,
    initial_local_positions: np.ndarray,
    initial_local_rotations: np.ndarray,
):
    count = len(positions)
    world_positions = positions.copy()
    world_rotations = np.empty_like(rotations)
    for index in range(count):
        world_rotations[index] = _normalize_quaternion(
            _quaternion_multiply(rotations[index], vertex_to_transform[index])
        )
    local_positions = initial_local_positions.copy()
    local_rotations = initial_local_rotations.copy()
    for index, parent in enumerate(parents):
        parent = int(parent)
        if parent < 0 or not (int(attributes[index]) & MC2_VERTEX_MOVE):
            continue
        inverse_parent = _quaternion_inverse(world_rotations[parent])
        local_positions[index] = (
            _rotate(inverse_parent, world_positions[index] - world_positions[parent])
            / scales[parent]
        )
        local_rotations[index] = _normalize_quaternion(
            _quaternion_multiply(inverse_parent, world_rotations[index])
        )
    return world_positions, world_rotations, local_positions, local_rotations


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


@dataclass(frozen=True)
class MC2BoneTriangleRotationResult:
    triangle_normals: tuple[tuple[float, float, float], ...]
    triangle_tangents: tuple[tuple[float, float, float], ...]
    proxy_rotations: tuple[tuple[float, float, float, float], ...]
    world_positions: tuple[tuple[float, float, float], ...]
    world_rotations: tuple[tuple[float, float, float, float], ...]
    local_positions: tuple[tuple[float, float, float], ...]
    local_rotations: tuple[tuple[float, float, float, float], ...]
    result_signature: str
    schema_version: int = 0

    def debug_dict(self) -> dict:
        return dict(self.__dict__)


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

    (
        world_positions,
        world_rotations,
        output_local_positions,
        output_local_rotations,
    ) = _write_world_local(
        attributes=attrs,
        positions=work_positions,
        rotations=work_rotations,
        vertex_to_transform=vertex_to_transform,
        parents=parents,
        scales=scales,
        initial_local_positions=output_local_positions,
        initial_local_rotations=output_local_rotations,
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


def evaluate_mc2_bone_triangle_rotation(
    *,
    attributes,
    positions,
    rotations,
    triangles,
    uvs,
    vertex_to_triangle_records,
    normal_adjustment_rotations,
    vertex_to_transform_rotations,
    parent_indices,
    transform_scales,
    transform_local_positions,
    transform_local_rotations,
) -> MC2BoneTriangleRotationResult:
    """Evaluate positive-scale Triangle/Sum -> world -> local Bone output."""

    count = len(positions)
    attrs = _array(attributes, (count,), "attributes", np.uint8)
    work_positions = _array(positions, (count, 3), "positions")
    work_rotations = _array(rotations, (count, 4), "rotations").copy()
    triangle_array = np.ascontiguousarray(triangles, dtype=np.int32)
    if triangle_array.ndim != 2 or triangle_array.shape[1:] != (3,):
        raise ValueError("triangles must have shape (N,3)")
    if np.any(triangle_array < 0) or np.any(triangle_array >= count):
        raise ValueError("triangle index out of range")
    uv_array = _array(uvs, (count, 2), "uvs")
    adjustments = _array(
        normal_adjustment_rotations,
        (count, 4),
        "normal_adjustment_rotations",
    )
    vertex_to_transform = _array(
        vertex_to_transform_rotations,
        (count, 4),
        "vertex_to_transform_rotations",
    )
    parents = _array(parent_indices, (count,), "parent_indices", np.int32)
    scales = _array(transform_scales, (count, 3), "transform_scales")
    initial_local_positions = _array(
        transform_local_positions,
        (count, 3),
        "transform_local_positions",
    )
    initial_local_rotations = _array(
        transform_local_rotations,
        (count, 4),
        "transform_local_rotations",
    )
    if len(vertex_to_triangle_records) != count:
        raise ValueError("vertex_to_triangle_records length mismatch")
    if any(value < -1 or value >= count for value in parents):
        raise ValueError("parent index out of range")
    if np.any(np.abs(scales) <= np.float32(1.0e-8)):
        raise ValueError("transform scale cannot contain zero")

    triangle_normals = np.zeros((len(triangle_array), 3), dtype=np.float32)
    triangle_tangents = np.zeros((len(triangle_array), 3), dtype=np.float32)
    for triangle_index, triangle in enumerate(triangle_array):
        triangle_positions = work_positions[triangle]
        cross = np.asarray(
            np.cross(
                triangle_positions[1] - triangle_positions[0],
                triangle_positions[2] - triangle_positions[0],
            ),
            dtype=np.float32,
        )
        length = np.float32(np.linalg.norm(cross))
        if length > np.float32(1.0e-8):
            triangle_normals[triangle_index] = cross / length
        tangent = _triangle_tangent(triangle_positions, uv_array[triangle])
        if np.dot(tangent, tangent) > np.float32(0.0):
            triangle_tangents[triangle_index] = tangent

    for vertex, raw_records in enumerate(vertex_to_triangle_records):
        if not raw_records:
            continue
        normal = np.zeros(3, dtype=np.float32)
        tangent = np.zeros(3, dtype=np.float32)
        for raw_record in raw_records:
            if len(raw_record) != 2:
                raise ValueError("vertex-to-triangle record must be (flip, triangle)")
            flip, triangle_index = (int(value) for value in raw_record)
            if flip < 0 or flip > 0xFFF or triangle_index < 0 or triangle_index >= len(triangle_array):
                raise ValueError("vertex-to-triangle record out of range")
            normal += triangle_normals[triangle_index] * (-1 if flip & 0x1 else 1)
            tangent += triangle_tangents[triangle_index] * (-1 if flip & 0x2 else 1)
        normal_length = np.float32(np.linalg.norm(normal))
        tangent_length = np.float32(np.linalg.norm(tangent))
        if normal_length <= np.float32(1.0e-6) or tangent_length <= np.float32(1.0e-6):
            continue
        normal /= normal_length
        tangent /= tangent_length
        dot = np.float32(np.dot(normal, tangent))
        if dot == np.float32(1.0) or dot == np.float32(-1.0):
            continue
        binormal = _normalize_vector(np.asarray(np.cross(normal, tangent), dtype=np.float32))
        work_rotations[vertex] = _normalize_quaternion(
            _quaternion_multiply(
                _look_rotation(binormal, normal),
                adjustments[vertex],
            )
        )

    world_positions, world_rotations, local_positions, local_rotations = _write_world_local(
        attributes=attrs,
        positions=work_positions,
        rotations=work_rotations,
        vertex_to_transform=vertex_to_transform,
        parents=parents,
        scales=scales,
        initial_local_positions=initial_local_positions,
        initial_local_rotations=initial_local_rotations,
    )
    payload = {
        "schema_version": 0,
        "triangle_normals": triangle_normals.tolist(),
        "triangle_tangents": triangle_tangents.tolist(),
        "proxy_rotations": work_rotations.tolist(),
        "world_positions": world_positions.tolist(),
        "world_rotations": world_rotations.tolist(),
        "local_positions": local_positions.tolist(),
        "local_rotations": local_rotations.tolist(),
    }
    return MC2BoneTriangleRotationResult(
        triangle_normals=tuple(tuple(float(value) for value in row) for row in triangle_normals),
        triangle_tangents=tuple(tuple(float(value) for value in row) for row in triangle_tangents),
        proxy_rotations=tuple(tuple(float(value) for value in row) for row in work_rotations),
        world_positions=tuple(tuple(float(value) for value in row) for row in world_positions),
        world_rotations=tuple(tuple(float(value) for value in row) for row in world_rotations),
        local_positions=tuple(tuple(float(value) for value in row) for row in local_positions),
        local_rotations=tuple(tuple(float(value) for value in row) for row in local_rotations),
        result_signature=_signature(payload),
    )


__all__ = [
    "MC2BoneLineRotationResult",
    "MC2BoneTriangleRotationResult",
    "evaluate_mc2_bone_line_rotation",
    "evaluate_mc2_bone_triangle_rotation",
]
