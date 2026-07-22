"""Build one host-owned MeshCloth static fragment from frozen capture POD."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ...bending_static import MC2BendingStaticSpec
from ...bending_static import build_mc2_bending_static
from ...center_state import MC2CenterStaticSpec
from ...center_state import build_mc2_center_static
from ...distance_static import MC2DistanceStaticSpec
from ...distance_static import build_mc2_distance_static
from ...domain_ir import MC2MeshPartitionStaticSnapshotV1
from ...mesh_baseline import MC2MeshBaselineBuildResult
from ...mesh_baseline import MC2_VERTEX_FIXED
from ...mesh_baseline import MC2_VERTEX_MOVE
from ...mesh_baseline import build_mc2_mesh_baseline
from ...native import native_module
from ...self_collision_static import MC2SelfCollisionStaticSpec
from ...self_collision_static import build_mc2_self_collision_static
from .final_proxy import MC2MeshFinalProxyBuildResult
from .final_proxy import build_mc2_final_proxy


@dataclass(frozen=True)
class MC2MeshStaticFragmentV1:
    snapshot_signature: str
    partition_id: str
    output_target_id: str
    finalizer: MC2MeshFinalProxyBuildResult
    baseline: MC2MeshBaselineBuildResult
    distance: MC2DistanceStaticSpec
    bending: MC2BendingStaticSpec | None
    center: MC2CenterStaticSpec
    self_collision: MC2SelfCollisionStaticSpec
    radius_multipliers: np.ndarray
    frame_triangles: np.ndarray
    frame_triangle_ranges: np.ndarray
    frame_triangle_records: np.ndarray
    frame_triangle_uvs: np.ndarray

    def __post_init__(self) -> None:
        if not self.snapshot_signature or not self.partition_id or not self.output_target_id:
            raise ValueError("Mesh static fragment identities cannot be empty")
        if not isinstance(self.finalizer, MC2MeshFinalProxyBuildResult):
            raise TypeError("finalizer must be MC2MeshFinalProxyBuildResult")
        if not isinstance(self.baseline, MC2MeshBaselineBuildResult):
            raise TypeError("baseline must be MC2MeshBaselineBuildResult")
        if not isinstance(self.distance, MC2DistanceStaticSpec):
            raise TypeError("distance must retain full host arrays")
        if self.bending is not None and not isinstance(self.bending, MC2BendingStaticSpec):
            raise TypeError("bending must retain full host arrays")
        if not isinstance(self.center, MC2CenterStaticSpec):
            raise TypeError("center must retain full host arrays")
        if not isinstance(self.self_collision, MC2SelfCollisionStaticSpec):
            raise TypeError("self_collision must retain full host arrays")
        proxy = self.final_proxy
        if self.baseline.final_proxy.proxy_signature != proxy.proxy_signature:
            raise ValueError("baseline and fragment proxy signatures must match")
        for value in (self.distance, self.center, self.self_collision):
            if value.proxy_signature != proxy.proxy_signature:
                raise ValueError("fragment producer signatures must match the final proxy")
        if self.bending is not None and self.bending.proxy_signature != proxy.proxy_signature:
            raise ValueError("Bending and fragment proxy signatures must match")
        if not isinstance(self.radius_multipliers, np.ndarray):
            raise TypeError("radius_multipliers must be a numpy.ndarray")
        if self.radius_multipliers.dtype != np.float32 or self.radius_multipliers.shape != (
            proxy.vertex_count,
        ):
            raise ValueError("radius_multipliers must be float32[V]")
        if self.radius_multipliers.flags.writeable or not self.radius_multipliers.flags.c_contiguous:
            raise ValueError("radius_multipliers must be contiguous and read-only")
        if (
            not isinstance(self.frame_triangles, np.ndarray)
            or self.frame_triangles.dtype != np.int32
            or self.frame_triangles.shape != (len(proxy.triangles), 3)
            or self.frame_triangles.flags.writeable
            or not self.frame_triangles.flags.c_contiguous
        ):
            raise ValueError(
                "frame_triangles must be contiguous read-only int32[T,3]: "
                f"dtype={getattr(self.frame_triangles, 'dtype', None)} "
                f"shape={getattr(self.frame_triangles, 'shape', None)} "
                f"expected={(len(proxy.triangles), 3)}"
            )
        if (
            not isinstance(self.frame_triangle_ranges, np.ndarray)
            or self.frame_triangle_ranges.dtype != np.int32
            or self.frame_triangle_ranges.shape != (proxy.vertex_count, 2)
            or self.frame_triangle_ranges.flags.writeable
            or not self.frame_triangle_ranges.flags.c_contiguous
        ):
            raise ValueError(
                "frame_triangle_ranges must be contiguous read-only int32[V,2]"
            )
        if (
            not isinstance(self.frame_triangle_records, np.ndarray)
            or self.frame_triangle_records.dtype != np.int32
            or self.frame_triangle_records.ndim != 2
            or self.frame_triangle_records.shape[1:] != (2,)
            or self.frame_triangle_records.flags.writeable
            or not self.frame_triangle_records.flags.c_contiguous
        ):
            raise ValueError(
                "frame_triangle_records must be contiguous read-only int32[R,2]"
            )
        if (
            not isinstance(self.frame_triangle_uvs, np.ndarray)
            or self.frame_triangle_uvs.dtype != np.float32
            or self.frame_triangle_uvs.shape != (len(proxy.triangles), 6)
            or self.frame_triangle_uvs.flags.writeable
            or not self.frame_triangle_uvs.flags.c_contiguous
        ):
            raise ValueError("frame_triangle_uvs must be contiguous read-only float32[T,6]")

    @property
    def final_proxy(self):
        return self.baseline.final_proxy

    @property
    def setup_type(self) -> str:
        return "mesh_cloth"

    @property
    def output_space_kind(self) -> str:
        return "mesh_object_local_offset"

    @property
    def source_elements(self) -> np.ndarray:
        values = []
        for identity in self.final_proxy.vertex_identities:
            prefix, marker, suffix = str(identity).rpartition("v")
            if not marker or not prefix.endswith(":") or not suffix.isdigit():
                raise ValueError(f"unsupported Mesh particle identity: {identity!r}")
            values.append(int(suffix))
        result = np.asarray(values, dtype=np.uint32)
        result.flags.writeable = False
        return result

    def debug_dict(self) -> dict:
        return {
            "snapshot_signature": self.snapshot_signature,
            "partition_id": self.partition_id,
            "output_target_id": self.output_target_id,
            "particle_count": self.final_proxy.vertex_count,
            "distance_record_count": self.distance.record_count,
            "bending_record_count": self.bending.record_count if self.bending else 0,
            "self_primitive_count": self.self_collision.primitive_count,
            "proxy_signature": self.final_proxy.proxy_signature,
            "baseline_signature": self.baseline.baseline.baseline_signature,
        }


def _mesh_uvs(snapshot: MC2MeshPartitionStaticSnapshotV1):
    vertex_count = snapshot.vertex_count
    triangle_count = len(snapshot.triangles)
    if triangle_count == 0:
        return np.zeros((vertex_count, 2), dtype=np.float64), np.empty(
            (0, 3, 2), dtype=np.float64
        )
    if not snapshot.has_uv:
        raise ValueError("MeshCloth triangle fragment requires captured UVs")
    values = np.zeros((vertex_count, 2), dtype=np.float64)
    vertices, first_indices = np.unique(snapshot.loop_vertices, return_index=True)
    values[vertices] = snapshot.loop_uvs[first_indices]
    return values, np.ascontiguousarray(
        snapshot.loop_uvs[snapshot.triangle_loops], dtype=np.float64
    )


def _fallback_tangents(normals: np.ndarray) -> np.ndarray:
    values = np.ascontiguousarray(normals, dtype=np.float64)
    tangents = np.empty(values.shape, dtype=np.float64)
    native_module().mc2_build_mesh_fallback_tangents_v0(values, tangents)
    return tangents


def _final_frame_triangle_uvs(
    original_triangles: np.ndarray,
    final_triangles,
    triangle_uvs: np.ndarray,
) -> np.ndarray:
    result = np.empty((len(original_triangles), 3, 2), dtype=np.float32)
    for triangle_index, (original, final) in enumerate(
        zip(original_triangles, final_triangles)
    ):
        corner_uvs = {
            int(vertex): triangle_uvs[triangle_index, corner]
            for corner, vertex in enumerate(original)
        }
        if len(corner_uvs) != 3 or any(int(vertex) not in corner_uvs for vertex in final):
            raise ValueError("final proxy changed triangle membership")
        for corner, vertex in enumerate(final):
            result[triangle_index, corner] = corner_uvs[int(vertex)]
    result = np.ascontiguousarray(result.reshape((-1, 6)), dtype=np.float32)
    result.flags.writeable = False
    return result


def _frame_triangle_adjacency(finalizer) -> tuple[np.ndarray, np.ndarray]:
    ranges = getattr(finalizer, "vertex_to_triangle_ranges", None)
    data = getattr(finalizer, "vertex_to_triangle_data", None)
    if ranges is not None and data is not None:
        return (
            np.ascontiguousarray(ranges, dtype=np.int32).reshape((-1, 2)),
            np.ascontiguousarray(data, dtype=np.int32).reshape((-1, 2)),
        )
    nested = tuple(finalizer.vertex_to_triangle_records)
    dense_ranges = np.empty((len(nested), 2), dtype=np.int32)
    dense_records = []
    cursor = 0
    for vertex, records in enumerate(nested):
        records = tuple(records)
        dense_ranges[vertex] = (cursor, len(records))
        dense_records.extend(records)
        cursor += len(records)
    return dense_ranges, np.ascontiguousarray(
        dense_records, dtype=np.int32
    ).reshape((-1, 2))


def _vertex_attributes(snapshot: MC2MeshPartitionStaticSnapshotV1) -> tuple[int, ...]:
    if not snapshot.pin_present:
        return (MC2_VERTEX_MOVE,) * snapshot.vertex_count
    return tuple(
        MC2_VERTEX_FIXED if float(weight) > 0.0 else MC2_VERTEX_MOVE
        for weight in snapshot.pin_weights
    )


def _matrix_columns(matrix: np.ndarray) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(float(matrix[row, column]) for row in range(4))
        for column in range(4)
    )


def build_mc2_mesh_static_fragment(
    snapshot: MC2MeshPartitionStaticSnapshotV1,
    *,
    world_gravity_direction=(0.0, -1.0, 0.0),
) -> MC2MeshStaticFragmentV1:
    """Run existing Tier A producers without allocating a solver context."""

    if not isinstance(snapshot, MC2MeshPartitionStaticSnapshotV1):
        raise TypeError("snapshot must be MC2MeshPartitionStaticSnapshotV1")
    uvs, triangle_uvs = _mesh_uvs(snapshot)
    finalizer = build_mc2_final_proxy(
        task_id=snapshot.partition_id,
        setup_type="mesh_cloth",
        vertex_identities=tuple(
            f"mesh:v{int(source_id)}"
            for source_id in snapshot.source_element_ids
        ),
        local_positions=snapshot.local_positions,
        local_normals=snapshot.local_normals,
        local_tangents=_fallback_tangents(snapshot.local_normals),
        uvs=uvs,
        vertex_attributes=_vertex_attributes(snapshot),
        lines=snapshot.edges,
        triangles=snapshot.triangles,
        triangle_uvs=triangle_uvs,
    )
    baseline = build_mc2_mesh_baseline(finalizer.proxy)
    distance = build_mc2_distance_static(
        baseline.final_proxy,
        baseline.baseline,
        vertex_to_vertex_ranges=finalizer.vertex_to_vertex_ranges,
        vertex_to_vertex_data=finalizer.vertex_to_vertex_data,
    )
    bending = build_mc2_bending_static(
        baseline.final_proxy,
        initial_local_to_world_columns=_matrix_columns(snapshot.source_bind_matrix),
    )
    center = build_mc2_center_static(
        baseline.final_proxy,
        vertex_bind_pose_rotations=finalizer.vertex_bind_pose_rotations,
        world_gravity_direction=world_gravity_direction,
    )
    self_collision = build_mc2_self_collision_static(
        baseline.final_proxy,
        baseline.baseline.depths,
    )
    radius = np.array(snapshot.radius_multipliers, dtype=np.float32, order="C", copy=True)
    radius.setflags(write=False)
    frame_triangles = np.ascontiguousarray(
        finalizer.proxy.triangles, dtype=np.int32
    ).reshape((-1, 3))
    frame_triangle_ranges, frame_triangle_records = _frame_triangle_adjacency(
        finalizer.finalizer
    )
    for value in (frame_triangles, frame_triangle_ranges, frame_triangle_records):
        value.flags.writeable = False
    frame_triangle_uvs = _final_frame_triangle_uvs(
        snapshot.triangles,
        finalizer.proxy.triangles,
        triangle_uvs,
    )
    return MC2MeshStaticFragmentV1(
        snapshot_signature=snapshot.static_signature,
        partition_id=snapshot.partition_id,
        output_target_id=snapshot.output_target_id,
        finalizer=finalizer,
        baseline=baseline,
        distance=distance,
        bending=bending,
        center=center,
        self_collision=self_collision,
        radius_multipliers=radius,
        frame_triangles=frame_triangles,
        frame_triangle_ranges=frame_triangle_ranges,
        frame_triangle_records=frame_triangle_records,
        frame_triangle_uvs=frame_triangle_uvs,
    )


__all__ = ["MC2MeshStaticFragmentV1", "build_mc2_mesh_static_fragment"]
