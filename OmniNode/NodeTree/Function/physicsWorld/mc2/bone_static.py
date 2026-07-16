"""Source-aligned Bone Line ``ConvertProxyMesh`` static bundle.

The bundle composes the shared finalized proxy, shared finalizer arrays, and
shared baseline schema with the two Bone-only rotation arrays.  Transform
selection and Blender pose extraction remain outside this pure data layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import math

import numpy as np

from ..utils.math3d import (
    normalize_vector_f64,
    orientation_xyzw_f64,
    quaternion_conjugate_f64,
    quaternion_multiply_f64,
)
from .mesh_baseline import MC2MeshBaselineNativeData, _replace_proxy_attributes
from .names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from .setups.mesh_cloth.final_proxy import (
    MC2MeshFinalizerNativeData,
    MC2MeshProxyNativeData,
    build_mc2_final_proxy,
)
from .static_data import MC2BaselineStaticSpec
from .static_data import MC2ProxyFinalizerStaticSpec
from .static_data import MC2ProxyStaticSpec
from .static_data import MC2_STATIC_SCHEMA_VERSION
from .static_data import mc2_baseline_content_signature
from .static_data import mc2_proxy_finalizer_content_signature
from .static_data import make_mc2_baseline_static_spec
from .static_data import make_mc2_proxy_finalizer_static_spec
from .static_data import pack_mc2_baseline_static
from .static_data import pack_mc2_proxy_finalizer_static
from .static_data import pack_mc2_proxy_static


MC2_NORMAL_ALIGNMENT_NONE = 0
MC2_NORMAL_ALIGNMENT_TRANSFORM = 2
MC2_NORMAL_ADJUSTMENT_EPSILON = 1.0e-6


def mc2_bone_static_content_signature(
    *,
    proxy_signature,
    finalizer_signature,
    baseline_signature,
    normal_adjustment_rotations,
    vertex_to_transform_rotations,
) -> str:
    digest = hashlib.sha256(b"mc2_bone_static_v4\0")
    for value in (proxy_signature, finalizer_signature, baseline_signature):
        digest.update(str(value or "").encode("ascii"))
    digest.update(
        np.ascontiguousarray(normal_adjustment_rotations, dtype=np.float64).tobytes()
    )
    digest.update(
        np.ascontiguousarray(vertex_to_transform_rotations, dtype=np.float64).tobytes()
    )
    return digest.hexdigest()


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


def _build_native_transform_baseline(proxy, parents, roots, *, produce_owned=False) -> dict:
    count = len(parents)
    child_ranges = np.empty((count, 2), dtype=np.int32)
    child_data = np.empty(count, dtype=np.int32)
    baseline_flags = np.empty(count, dtype=np.uint8)
    baseline_ranges = np.empty((count, 2), dtype=np.int32)
    baseline_data = np.empty(count, dtype=np.int32)
    final_attributes = np.empty(count, dtype=np.uint8)
    pose_roots = np.empty(count, dtype=np.int32)
    depths = np.empty(count, dtype=np.float64)
    local_positions = np.empty((count, 3), dtype=np.float64)
    local_rotations = np.empty((count, 4), dtype=np.float64)
    from .native import native_module

    counts = native_module().mc2_build_bone_transform_baseline_derived_v0(
        np.ascontiguousarray(proxy.local_positions, dtype=np.float64),
        np.ascontiguousarray(proxy.local_normals, dtype=np.float64),
        np.ascontiguousarray(proxy.local_tangents, dtype=np.float64),
        np.ascontiguousarray(proxy.vertex_attributes, dtype=np.uint8),
        np.ascontiguousarray(parents, dtype=np.int32),
        np.ascontiguousarray(roots, dtype=np.int32),
        child_ranges,
        child_data,
        baseline_flags,
        baseline_ranges,
        baseline_data,
        final_attributes,
        pose_roots,
        depths,
        local_positions,
        local_rotations,
        bool(produce_owned),
    )
    child_count = int(counts["child_count"])
    baseline_count = int(counts["baseline_count"])
    baseline_data_count = int(counts["baseline_data_count"])
    if produce_owned:
        result = {
            "parents": np.ascontiguousarray(parents, dtype=np.int32),
            "child_ranges": child_ranges,
            "child_data": child_data[:child_count],
            "baseline_flags": baseline_flags[:baseline_count],
            "baseline_ranges": baseline_ranges[:baseline_count],
            "baseline_data": baseline_data[:baseline_data_count],
            "attributes": final_attributes,
            "roots": pose_roots,
            "depths": depths,
            "local_positions": local_positions,
            "local_rotations": local_rotations,
        }
        result["native_registration"] = {
            "parents": counts["baseline_parents"],
            "child_ranges": counts["baseline_child_ranges"],
            "child_data": counts["baseline_child_data"],
            "baseline_flags": counts["baseline_flags"],
            "baseline_ranges": counts["baseline_ranges"],
            "baseline_data": counts["baseline_data"],
            "roots": counts["baseline_roots"],
            "depths": counts["baseline_depths"],
            "local_positions": counts["baseline_local_positions"],
            "local_rotations": counts["baseline_local_rotations"],
            "owners": (
                counts["_baseline_parents_owner"],
                counts["_baseline_child_ranges_owner"],
                counts["_baseline_child_data_owner"],
                counts["_baseline_flags_owner"],
                counts["_baseline_ranges_owner"],
                counts["_baseline_data_owner"],
                counts["_baseline_roots_owner"],
                counts["_baseline_depths_owner"],
                counts["_baseline_local_positions_owner"],
                counts["_baseline_local_rotations_owner"],
            ),
        }
        return result
    return {
        "child_ranges": tuple(tuple(int(value) for value in row) for row in child_ranges),
        "child_data": tuple(int(value) for value in child_data[:child_count]),
        "baseline_flags": tuple(int(value) for value in baseline_flags[:baseline_count]),
        "baseline_ranges": tuple(
            tuple(int(value) for value in row)
            for row in baseline_ranges[:baseline_count]
        ),
        "baseline_data": tuple(int(value) for value in baseline_data[:baseline_data_count]),
        "attributes": tuple(int(value) for value in final_attributes),
        "roots": tuple(int(value) for value in pose_roots),
        "depths": tuple(float(value) for value in depths),
        "local_positions": _tuple_vectors(local_positions),
        "local_rotations": _tuple_vectors(local_rotations),
    }


def _normal_adjustment(
    positions: np.ndarray,
    normals: np.ndarray,
    tangents: np.ndarray,
    *,
    mode: int,
    center,
    return_arrays: bool = False,
):
    count = len(positions)
    final_normals = np.array(normals, dtype=np.float64, copy=True)
    final_tangents = np.array(tangents, dtype=np.float64, copy=True)
    rotations = np.tile(np.asarray((0.0, 0.0, 0.0, 1.0)), (count, 1))
    if mode == MC2_NORMAL_ALIGNMENT_NONE:
        return (
            final_normals,
            final_tangents,
            rotations if return_arrays else _tuple_vectors(rotations),
        )
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
    return (
        final_normals,
        final_tangents,
        rotations if return_arrays else _tuple_vectors(rotations),
    )


@dataclass(frozen=True)
class MC2BoneStaticSpec:
    proxy: MC2ProxyStaticSpec
    finalizer: MC2ProxyFinalizerStaticSpec
    baseline: MC2BaselineStaticSpec
    normal_adjustment_rotations: tuple[tuple[float, float, float, float], ...]
    vertex_to_transform_rotations: tuple[tuple[float, float, float, float], ...]
    static_signature: str
    baseline_native_registration: dict | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    proxy_native_registration: dict | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    bone_native_registration: dict | None = field(
        default=None,
        repr=False,
        compare=False,
    )
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
        if self.static_signature != mc2_bone_static_content_signature(
            proxy_signature=self.proxy.proxy_signature,
            finalizer_signature=self.finalizer.finalizer_signature,
            baseline_signature=self.baseline.baseline_signature,
            normal_adjustment_rotations=self.normal_adjustment_rotations,
            vertex_to_transform_rotations=self.vertex_to_transform_rotations,
        ):
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


@dataclass(frozen=True)
class MC2BoneNativeData:
    proxy: MC2MeshProxyNativeData
    finalizer: MC2MeshFinalizerNativeData
    baseline: MC2MeshBaselineNativeData
    normal_adjustment_rotations: np.ndarray
    vertex_to_transform_rotations: np.ndarray
    static_signature: str
    baseline_native_registration: dict
    proxy_native_registration: dict
    bone_native_registration: dict
    schema_version: int = MC2_STATIC_SCHEMA_VERSION
    native_owned: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != MC2_STATIC_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 Bone native data schema")
        if self.proxy.setup_type not in (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING):
            raise ValueError("Bone native data requires a Bone setup proxy")
        if self.finalizer.proxy_signature != self.proxy.proxy_signature:
            raise ValueError("Bone native finalizer signature mismatch")
        if self.baseline.proxy_signature != self.proxy.proxy_signature:
            raise ValueError("Bone native baseline signature mismatch")
        expected = mc2_bone_static_content_signature(
            proxy_signature=self.proxy.proxy_signature,
            finalizer_signature=self.finalizer.finalizer_signature,
            baseline_signature=self.baseline.baseline_signature,
            normal_adjustment_rotations=self.normal_adjustment_rotations,
            vertex_to_transform_rotations=self.vertex_to_transform_rotations,
        )
        if self.static_signature != expected:
            raise ValueError("Bone native static signature mismatch")


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
    native_context=None,
) -> MC2BoneStaticSpec | MC2BoneNativeData:
    staged = native_context is not None
    identities = tuple(str(value) for value in vertex_identities)
    count = len(identities)
    positions = np.ascontiguousarray(local_positions, dtype=np.float64)
    normals = np.ascontiguousarray(local_normals, dtype=np.float64)
    tangents = np.ascontiguousarray(local_tangents, dtype=np.float64)
    if positions.shape != (count, 3) or normals.shape != (count, 3) or tangents.shape != (count, 3):
        raise ValueError("Bone static position/normal/tangent arrays must have shape [vertex_count,3]")
    if not np.all(np.isfinite(positions)) or not np.all(np.isfinite(normals)) or not np.all(np.isfinite(tangents)):
        raise ValueError("Bone static vectors cannot contain NaN/Inf")
    if staged:
        parent_values = np.asarray(parent_indices)
        root_values = np.asarray(root_indices)
        parents = np.ascontiguousarray(parent_values, dtype=np.int32)
        roots = np.ascontiguousarray(root_values, dtype=np.int32)
        if (
            parent_values.dtype == np.bool_
            or root_values.dtype == np.bool_
            or parents.ndim != 1
            or roots.ndim != 1
            or parent_values.shape != parents.shape
            or root_values.shape != roots.shape
            or not np.array_equal(parent_values, parents)
            or not np.array_equal(root_values, roots)
        ):
            raise ValueError("parent_indices and root_indices must contain exact integers")
    else:
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
    if len(roots) == 0 or len(set(roots)) != len(roots):
        raise ValueError("root_indices must be non-empty and unique")
    if any(root < 0 or root >= count or parents[root] >= 0 for root in roots):
        raise ValueError("root_indices must reference parentless vertices")
    if set(roots) != {vertex for vertex, parent in enumerate(parents) if parent < 0}:
        raise ValueError("root_indices must cover every parentless vertex")
    if staged:
        transform_rotations = np.ascontiguousarray(
            transform_local_rotations,
            dtype=np.float64,
        )
        if transform_rotations.shape != (count, 4) or not np.all(
            np.isfinite(transform_rotations)
        ):
            raise ValueError("transform_local_rotations must have finite shape [vertex_count,4]")
        lengths_squared = np.einsum(
            "ij,ij->i",
            transform_rotations,
            transform_rotations,
        )
        if np.any(np.abs(lengths_squared - 1.0) > 1.0e-4):
            raise ValueError("transform_local_rotations must contain unit xyzw quaternions")
    else:
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
        return_arrays=staged,
    )
    raw = build_mc2_final_proxy(
        task_id=task_id,
        setup_type=setup_type,
        vertex_identities=identities,
        local_positions=positions if staged else _tuple_vectors(positions),
        local_normals=adjusted_normals if staged else _tuple_vectors(adjusted_normals),
        local_tangents=adjusted_tangents if staged else _tuple_vectors(adjusted_tangents),
        uvs=uvs,
        vertex_attributes=vertex_attributes,
        lines=lines,
        triangles=triangles,
        native_owner_kind="bone" if staged else "",
    )

    transform_baseline = _build_native_transform_baseline(
        raw.proxy,
        parents,
        roots,
        produce_owned=native_context is not None,
    )
    child_ranges = transform_baseline["child_ranges"]
    child_data = transform_baseline["child_data"]
    baseline_flags = transform_baseline["baseline_flags"]
    baseline_ranges = transform_baseline["baseline_ranges"]
    baseline_data = transform_baseline["baseline_data"]
    final_attributes = transform_baseline["attributes"]
    local_pose_positions = transform_baseline["local_positions"]
    local_pose_rotations = transform_baseline["local_rotations"]
    final_proxy = _replace_proxy_attributes(raw.proxy, final_attributes)
    if staged:
        finalizer = replace(
            raw.finalizer,
            proxy_signature=final_proxy.proxy_signature,
            finalizer_signature=mc2_proxy_finalizer_content_signature(
                proxy_signature=final_proxy.proxy_signature,
                vertex_count=count,
                vertex_to_vertex_ranges=raw.finalizer.vertex_to_vertex_ranges,
                vertex_to_vertex_data=raw.finalizer.vertex_to_vertex_data,
                vertex_to_triangle_ranges=raw.finalizer.vertex_to_triangle_ranges,
                vertex_to_triangle_data=raw.finalizer.vertex_to_triangle_data,
                vertex_bind_pose_positions=raw.finalizer.vertex_bind_pose_positions,
                vertex_bind_pose_rotations=raw.finalizer.vertex_bind_pose_rotations,
            ),
        )
        baseline = MC2MeshBaselineNativeData(
            proxy_signature=final_proxy.proxy_signature,
            vertex_count=count,
            parent_indices=transform_baseline["parents"],
            child_ranges=child_ranges,
            child_data=child_data,
            baseline_flags=baseline_flags,
            baseline_ranges=baseline_ranges,
            baseline_data=baseline_data,
            root_indices=transform_baseline["roots"],
            depths=transform_baseline["depths"],
            vertex_local_positions=local_pose_positions,
            vertex_local_rotations=local_pose_rotations,
            baseline_signature=mc2_baseline_content_signature(
                proxy_signature=final_proxy.proxy_signature,
                vertex_count=count,
                parent_indices=transform_baseline["parents"],
                child_ranges=child_ranges,
                child_data=child_data,
                baseline_flags=baseline_flags,
                baseline_ranges=baseline_ranges,
                baseline_data=baseline_data,
                root_indices=transform_baseline["roots"],
                depths=transform_baseline["depths"],
                vertex_local_positions=local_pose_positions,
                vertex_local_rotations=local_pose_rotations,
            ),
            native_registration=transform_baseline["native_registration"],
        )
    else:
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
            root_indices=transform_baseline["roots"],
            depths=transform_baseline["depths"],
            vertex_local_positions=local_pose_positions,
            vertex_local_rotations=local_pose_rotations,
        )

    to_transform_values = np.empty((count, 4), dtype=np.float64)
    from .native import native_module

    rotation_arguments = (
        np.ascontiguousarray(final_proxy.local_normals, dtype=np.float64),
        np.ascontiguousarray(final_proxy.local_tangents, dtype=np.float64),
        np.ascontiguousarray(transform_rotations, dtype=np.float64),
    )
    if native_context is None:
        native_module().mc2_build_bone_vertex_to_transform_rotations_v0(
            *rotation_arguments,
            to_transform_values,
        )
        bone_native_registration = None
    else:
        rotation_registration = native_module().mc2_build_bone_registration_rotations_v0(
            *rotation_arguments,
            np.ascontiguousarray(adjustment_rotations, dtype=np.float64),
            to_transform_values,
        )
        bone_native_registration = dict(raw.native_bone_registration or {})
        bone_native_registration.update({
            "normal_adjustment_rotations": rotation_registration[
                "normal_adjustment_rotations"
            ],
            "vertex_to_transform_rotations": rotation_registration[
                "vertex_to_transform_rotations"
            ],
            "owners": (
                *bone_native_registration.get("owners", ()),
                rotation_registration["_bone_adjustment_rotations_owner"],
                rotation_registration["_bone_transform_rotations_owner"],
            ),
        })
    to_transform = to_transform_values if staged else _tuple_vectors(to_transform_values)

    payload = {
        "schema_version": MC2_STATIC_SCHEMA_VERSION,
        "proxy_signature": final_proxy.proxy_signature,
        "finalizer_signature": finalizer.finalizer_signature,
        "baseline_signature": baseline.baseline_signature,
        "normal_adjustment_rotations": adjustment_rotations,
        "vertex_to_transform_rotations": to_transform,
    }
    static_signature = mc2_bone_static_content_signature(
        proxy_signature=payload["proxy_signature"],
        finalizer_signature=payload["finalizer_signature"],
        baseline_signature=payload["baseline_signature"],
        normal_adjustment_rotations=payload["normal_adjustment_rotations"],
        vertex_to_transform_rotations=payload["vertex_to_transform_rotations"],
    )
    if staged:
        return MC2BoneNativeData(
            proxy=final_proxy,
            finalizer=finalizer,
            baseline=baseline,
            normal_adjustment_rotations=adjustment_rotations,
            vertex_to_transform_rotations=to_transform,
            static_signature=static_signature,
            baseline_native_registration=transform_baseline["native_registration"],
            proxy_native_registration=raw.native_proxy_registration,
            bone_native_registration=bone_native_registration,
        )
    return MC2BoneStaticSpec(
        proxy=final_proxy,
        finalizer=finalizer,
        baseline=baseline,
        normal_adjustment_rotations=adjustment_rotations,
        vertex_to_transform_rotations=to_transform,
        static_signature=static_signature,
        baseline_native_registration=transform_baseline.get("native_registration"),
        proxy_native_registration=raw.native_proxy_registration,
        bone_native_registration=bone_native_registration,
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
    "MC2BoneNativeData",
    "MC2BoneStaticSpec",
    "MC2_NORMAL_ALIGNMENT_NONE",
    "MC2_NORMAL_ALIGNMENT_TRANSFORM",
    "build_mc2_bone_static",
    "pack_mc2_bone_registration_static",
    "pack_mc2_bone_static",
    "mc2_bone_static_content_signature",
]
