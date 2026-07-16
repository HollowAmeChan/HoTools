"""Source-aligned Bone Line ``ConvertProxyMesh`` static bundle.

The bundle composes the shared finalized proxy, shared finalizer arrays, and
shared baseline schema with the two Bone-only rotation arrays.  Transform
selection and Blender pose extraction remain outside this pure data layer.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from ..utils.math3d import (
    normalize_vector_f64,
    orientation_xyzw_f64,
    quaternion_conjugate_f64,
    quaternion_multiply_f64,
)
from .mesh_baseline import MC2_BASELINE_INCLUDE_LINE
from .mesh_baseline import MC2_VERTEX_FIXED
from .mesh_baseline import MC2_VERTEX_MOVE
from .mesh_baseline import MC2_VERTEX_TRIANGLE
from .mesh_baseline import _build_native_baseline_pose_depth
from .mesh_baseline import _replace_proxy_attributes
from .names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from .setups.mesh_cloth.final_proxy import build_mc2_final_proxy
from .static_data import MC2BaselineStaticSpec
from .static_data import MC2ProxyFinalizerStaticSpec
from .static_data import MC2ProxyStaticSpec
from .static_data import MC2_STATIC_SCHEMA_VERSION
from .static_data import make_mc2_baseline_static_spec
from .static_data import make_mc2_proxy_finalizer_static_spec
from .static_data import pack_mc2_baseline_static
from .static_data import pack_mc2_proxy_finalizer_static
from .static_data import pack_mc2_proxy_static


MC2_NORMAL_ALIGNMENT_NONE = 0
MC2_NORMAL_ALIGNMENT_TRANSFORM = 2
MC2_NORMAL_ADJUSTMENT_EPSILON = 1.0e-6


def _signature(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _tuple_vectors(values: np.ndarray) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(component) for component in row) for row in values)


def _unit_quaternion_rows(values, *, name: str, count: int) -> tuple[tuple[float, ...], ...]:
    rows = []
    for index, value in enumerate(values):
        row = tuple(float(component) for component in value)
        if len(row) != 4 or not all(math.isfinite(component) for component in row):
            raise ValueError(f"{name}[{index}] must be a finite xyzw quaternion")
        length_squared = sum(component * component for component in row)
        if abs(length_squared - 1.0) > 1.0e-4:
            raise ValueError(f"{name}[{index}] must be a unit xyzw quaternion")
        rows.append(row)
    if len(rows) != count:
        raise ValueError(f"{name} length must match vertex_count")
    return tuple(rows)


def _dense_ranges(records: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, int], ...]:
    ranges = []
    cursor = 0
    for record in records:
        ranges.append((cursor, len(record)))
        cursor += len(record)
    return tuple(ranges)


def _flatten(records: tuple[tuple[int, ...], ...]) -> tuple[int, ...]:
    return tuple(value for record in records for value in record)


def _source_children(parents: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    children = [[] for _ in parents]
    for vertex, parent in enumerate(parents):
        if parent >= 0:
            children[parent].append(vertex)
    return tuple(tuple(reversed(values)) for values in children)


def _validate_parent_forest(parents: tuple[int, ...]) -> None:
    count = len(parents)
    for vertex, parent in enumerate(parents):
        if parent < -1 or parent >= count or parent == vertex:
            raise ValueError(f"parent_indices[{vertex}] is invalid")
    for start in range(count):
        visited = set()
        current = start
        while current >= 0:
            if current in visited:
                raise ValueError("parent_indices contains a cycle")
            visited.add(current)
            current = parents[current]


def _build_transform_baselines(
    attributes: tuple[int, ...],
    children: tuple[tuple[int, ...], ...],
    root_order: tuple[int, ...],
) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...], tuple[int, ...]]:
    flags = []
    ranges = []
    data = []
    for transform_root in root_order:
        root_stack = [transform_root]
        while root_stack:
            vertex = root_stack.pop()
            if not attributes[vertex] & MC2_VERTEX_FIXED:
                continue
            if not any(attributes[child] & MC2_VERTEX_MOVE for child in children[vertex]):
                root_stack.extend(
                    child
                    for child in children[vertex]
                    if attributes[child] & MC2_VERTEX_FIXED
                )
                continue

            start = len(data)
            line_flag = 0
            stack = [vertex]
            while stack:
                current = stack.pop()
                data.append(current)
                if not attributes[current] & MC2_VERTEX_TRIANGLE:
                    line_flag |= MC2_BASELINE_INCLUDE_LINE
                stack.extend(
                    child
                    for child in children[current]
                    if attributes[child] & MC2_VERTEX_MOVE
                )
            flags.append(line_flag)
            ranges.append((start, len(data) - start))
    return tuple(flags), tuple(ranges), tuple(data)


def _normal_adjustment(
    positions: np.ndarray,
    normals: np.ndarray,
    tangents: np.ndarray,
    *,
    mode: int,
    center,
) -> tuple[np.ndarray, np.ndarray, tuple[tuple[float, ...], ...]]:
    count = len(positions)
    final_normals = np.array(normals, dtype=np.float64, copy=True)
    final_tangents = np.array(tangents, dtype=np.float64, copy=True)
    rotations = np.tile(np.asarray((0.0, 0.0, 0.0, 1.0)), (count, 1))
    if mode == MC2_NORMAL_ALIGNMENT_NONE:
        return final_normals, final_tangents, _tuple_vectors(rotations)
    if mode != MC2_NORMAL_ALIGNMENT_TRANSFORM:
        raise ValueError("Bone static builder currently supports normal alignment None or Transform")
    center_value = np.asarray(tuple(center), dtype=np.float64)
    if center_value.shape != (3,) or not np.all(np.isfinite(center_value)):
        raise ValueError("normal_adjustment_center must be a finite float3")

    for vertex in range(count):
        direction = positions[vertex] - center_value
        length = float(np.linalg.norm(direction))
        if length < MC2_NORMAL_ADJUSTMENT_EPSILON:
            continue
        normal = direction / length
        source_normal = final_normals[vertex]
        tangent = final_tangents[vertex]
        source_rotation = orientation_xyzw_f64(source_normal, tangent)
        if float(np.dot(normal, tangent)) < 0.99:
            binormal = normalize_vector_f64(np.cross(normal, tangent), name="normal adjustment binormal")
            tangent = normalize_vector_f64(np.cross(binormal, normal), name="normal adjustment tangent")
        else:
            binormal = normalize_vector_f64(
                np.cross(source_normal, tangent),
                name="normal adjustment source binormal",
            )
            tangent = normalize_vector_f64(np.cross(binormal, normal), name="normal adjustment tangent")
        final_normals[vertex] = normal
        final_tangents[vertex] = tangent
        adjusted_rotation = orientation_xyzw_f64(normal, tangent)
        rotations[vertex] = normalize_vector_f64(
            quaternion_multiply_f64(
                quaternion_conjugate_f64(source_rotation),
                adjusted_rotation,
            ),
            name="normal adjustment rotation",
        )
    return final_normals, final_tangents, _tuple_vectors(rotations)


@dataclass(frozen=True)
class MC2BoneStaticSpec:
    proxy: MC2ProxyStaticSpec
    finalizer: MC2ProxyFinalizerStaticSpec
    baseline: MC2BaselineStaticSpec
    normal_adjustment_rotations: tuple[tuple[float, float, float, float], ...]
    vertex_to_transform_rotations: tuple[tuple[float, float, float, float], ...]
    static_signature: str
    schema_version: int = MC2_STATIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MC2_STATIC_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 Bone static schema")
        if self.proxy.setup_type not in (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING):
            raise ValueError("Bone static bundle requires a Bone setup proxy")
        if self.finalizer.proxy_signature != self.proxy.proxy_signature:
            raise ValueError("finalizer must reference the finalized Bone proxy")
        if self.baseline.proxy_signature != self.proxy.proxy_signature:
            raise ValueError("baseline must reference the finalized Bone proxy")
        if not isinstance(self.normal_adjustment_rotations, tuple) or not isinstance(
            self.vertex_to_transform_rotations,
            tuple,
        ):
            raise TypeError("Bone rotation arrays must be immutable tuples")
        if self.normal_adjustment_rotations != _unit_quaternion_rows(
            self.normal_adjustment_rotations,
            name="normal_adjustment_rotations",
            count=self.proxy.vertex_count,
        ):
            raise TypeError("normal_adjustment_rotations must contain immutable tuples")
        if self.vertex_to_transform_rotations != _unit_quaternion_rows(
            self.vertex_to_transform_rotations,
            name="vertex_to_transform_rotations",
            count=self.proxy.vertex_count,
        ):
            raise TypeError("vertex_to_transform_rotations must contain immutable tuples")
        if self.static_signature != _signature(self.signature_payload()):
            raise ValueError("static_signature does not match Bone static payload")

    def signature_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "proxy_signature": self.proxy.proxy_signature,
            "finalizer_signature": self.finalizer.finalizer_signature,
            "baseline_signature": self.baseline.baseline_signature,
            "normal_adjustment_rotations": self.normal_adjustment_rotations,
            "vertex_to_transform_rotations": self.vertex_to_transform_rotations,
        }


def build_mc2_bone_static(
    *,
    task_id: str,
    setup_type: str = MC2_SETUP_BONE_CLOTH,
    vertex_identities,
    local_positions,
    local_normals,
    local_tangents,
    uvs,
    vertex_attributes,
    parent_indices,
    root_indices,
    transform_local_rotations,
    lines=(),
    triangles=(),
    normal_alignment_mode: int = MC2_NORMAL_ALIGNMENT_NONE,
    normal_adjustment_center=(0.0, 0.0, 0.0),
) -> MC2BoneStaticSpec:
    identities = tuple(str(value) for value in vertex_identities)
    count = len(identities)
    positions = np.asarray(tuple(local_positions), dtype=np.float64)
    normals = np.asarray(tuple(local_normals), dtype=np.float64)
    tangents = np.asarray(tuple(local_tangents), dtype=np.float64)
    if positions.shape != (count, 3) or normals.shape != (count, 3) or tangents.shape != (count, 3):
        raise ValueError("Bone static position/normal/tangent arrays must have shape [vertex_count,3]")
    if not np.all(np.isfinite(positions)) or not np.all(np.isfinite(normals)) or not np.all(np.isfinite(tangents)):
        raise ValueError("Bone static vectors cannot contain NaN/Inf")
    parent_values = tuple(parent_indices)
    root_values = tuple(root_indices)
    if any(isinstance(value, bool) or int(value) != value for value in parent_values):
        raise ValueError("parent_indices must contain exact integers")
    if any(isinstance(value, bool) or int(value) != value for value in root_values):
        raise ValueError("root_indices must contain exact integers")
    parents = tuple(int(value) for value in parent_values)
    roots = tuple(int(value) for value in root_values)
    if len(parents) != count:
        raise ValueError("parent_indices length must match vertex_count")
    _validate_parent_forest(parents)
    if not roots or len(set(roots)) != len(roots):
        raise ValueError("root_indices must be non-empty and unique")
    if any(root < 0 or root >= count or parents[root] >= 0 for root in roots):
        raise ValueError("root_indices must reference parentless vertices")
    if set(roots) != {vertex for vertex, parent in enumerate(parents) if parent < 0}:
        raise ValueError("root_indices must cover every parentless vertex")
    transform_rotations = _unit_quaternion_rows(
        transform_local_rotations,
        name="transform_local_rotations",
        count=count,
    )

    adjusted_normals, adjusted_tangents, adjustment_rotations = _normal_adjustment(
        positions,
        normals,
        tangents,
        mode=int(normal_alignment_mode),
        center=normal_adjustment_center,
    )
    raw = build_mc2_final_proxy(
        task_id=task_id,
        setup_type=setup_type,
        vertex_identities=identities,
        local_positions=_tuple_vectors(positions),
        local_normals=_tuple_vectors(adjusted_normals),
        local_tangents=_tuple_vectors(adjusted_tangents),
        uvs=uvs,
        vertex_attributes=vertex_attributes,
        lines=lines,
        triangles=triangles,
    )

    children = _source_children(parents)
    child_ranges = _dense_ranges(children)
    child_data = _flatten(children)
    baseline_flags, baseline_ranges, baseline_data = _build_transform_baselines(
        raw.proxy.vertex_attributes,
        children,
        roots,
    )
    pose_depth = _build_native_baseline_pose_depth(
        raw.proxy,
        parents,
        baseline_data,
    )
    final_attributes = pose_depth["attributes"]
    local_pose_positions = pose_depth["local_positions"]
    local_pose_rotations = pose_depth["local_rotations"]
    final_proxy = _replace_proxy_attributes(raw.proxy, final_attributes)
    finalizer = make_mc2_proxy_finalizer_static_spec(
        proxy=final_proxy,
        vertex_to_vertex_ranges=raw.finalizer.vertex_to_vertex_ranges,
        vertex_to_vertex_data=raw.finalizer.vertex_to_vertex_data,
        vertex_to_triangle_records=raw.finalizer.vertex_to_triangle_records,
        vertex_bind_pose_positions=raw.finalizer.vertex_bind_pose_positions,
        vertex_bind_pose_rotations=raw.finalizer.vertex_bind_pose_rotations,
    )
    baseline = make_mc2_baseline_static_spec(
        proxy_signature=final_proxy.proxy_signature,
        vertex_count=count,
        parent_indices=parents,
        child_ranges=child_ranges,
        child_data=child_data,
        baseline_flags=baseline_flags,
        baseline_ranges=baseline_ranges,
        baseline_data=baseline_data,
        root_indices=pose_depth["roots"],
        depths=pose_depth["depths"],
        vertex_local_positions=local_pose_positions,
        vertex_local_rotations=local_pose_rotations,
    )

    to_transform_values = np.empty((count, 4), dtype=np.float64)
    from .native import native_module

    native_module().mc2_build_bone_vertex_to_transform_rotations_v0(
        np.ascontiguousarray(final_proxy.local_normals, dtype=np.float64),
        np.ascontiguousarray(final_proxy.local_tangents, dtype=np.float64),
        np.ascontiguousarray(transform_rotations, dtype=np.float64),
        to_transform_values,
    )
    to_transform = _tuple_vectors(to_transform_values)

    payload = {
        "schema_version": MC2_STATIC_SCHEMA_VERSION,
        "proxy_signature": final_proxy.proxy_signature,
        "finalizer_signature": finalizer.finalizer_signature,
        "baseline_signature": baseline.baseline_signature,
        "normal_adjustment_rotations": adjustment_rotations,
        "vertex_to_transform_rotations": to_transform,
    }
    return MC2BoneStaticSpec(
        proxy=final_proxy,
        finalizer=finalizer,
        baseline=baseline,
        normal_adjustment_rotations=adjustment_rotations,
        vertex_to_transform_rotations=to_transform,
        static_signature=_signature(payload),
    )


def pack_mc2_bone_static(spec: MC2BoneStaticSpec) -> dict[str, np.ndarray]:
    if not isinstance(spec, MC2BoneStaticSpec):
        raise TypeError("spec must be MC2BoneStaticSpec")
    packed = {}
    packed.update(pack_mc2_proxy_static(spec.proxy))
    packed.update(pack_mc2_baseline_static(spec.baseline))
    packed.update(pack_mc2_bone_registration_static(spec))
    return packed


def pack_mc2_bone_registration_static(
    spec: MC2BoneStaticSpec,
) -> dict[str, np.ndarray]:
    if not isinstance(spec, MC2BoneStaticSpec):
        raise TypeError("spec must be MC2BoneStaticSpec")
    packed = pack_mc2_proxy_finalizer_static(spec.finalizer)
    count = spec.proxy.vertex_count
    for name, values in (
        ("normal_adjustment_rotations", spec.normal_adjustment_rotations),
        ("vertex_to_transform_rotations", spec.vertex_to_transform_rotations),
    ):
        array = np.ascontiguousarray(values, dtype=np.float32).reshape((count, 4))
        array.flags.writeable = False
        packed[name] = array
    return packed


__all__ = [
    "MC2BoneStaticSpec",
    "MC2_NORMAL_ALIGNMENT_NONE",
    "MC2_NORMAL_ALIGNMENT_TRANSFORM",
    "build_mc2_bone_static",
    "pack_mc2_bone_registration_static",
    "pack_mc2_bone_static",
]
