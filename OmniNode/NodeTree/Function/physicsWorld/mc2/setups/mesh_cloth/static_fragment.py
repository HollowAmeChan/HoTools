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

    @property
    def final_proxy(self):
        return self.baseline.final_proxy

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
    )


__all__ = ["MC2MeshStaticFragmentV1", "build_mc2_mesh_static_fragment"]
