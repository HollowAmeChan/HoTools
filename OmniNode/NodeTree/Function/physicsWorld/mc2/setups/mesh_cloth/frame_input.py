"""Blender N3 frame snapshots for the dual-object MC2 MeshCloth path."""

from __future__ import annotations

from dataclasses import dataclass

import bpy
import numpy as np

from ...frame_state import MC2FrameInputSpec, make_mc2_frame_input
from .base_pose import validate_base_pose_proxy
from .final_proxy import (
    _apply_vertex_triangle_normals,
    _orientation_xyzw,
    _triangle_normal,
    _triangle_tangent,
)


_FRAME_CACHE_PREFIX = "mc2_mesh_base_pose_frame"
_NORMAL_EPSILON = 1.0e-8


def _readonly_float3(values) -> np.ndarray:
    array = np.array(values, dtype=np.float32, order="C", copy=True).reshape((-1, 3))
    array.flags.writeable = False
    return array


def _matrix_to_numpy(matrix) -> np.ndarray:
    return np.asarray(
        [[float(matrix[row][column]) for column in range(4)] for row in range(4)],
        dtype=np.float32,
    )


@dataclass(frozen=True)
class MC2MeshFrameSnapshot:
    source_object_ptr: int
    source_data_ptr: int
    base_pose_object_ptr: int
    frame: int
    generation: int
    mesh_topology_signature: str
    animated_base_world_positions: np.ndarray
    animated_base_world_normals: np.ndarray

    @property
    def vertex_count(self) -> int:
        return int(self.animated_base_world_positions.shape[0])

    def __post_init__(self) -> None:
        if self.source_object_ptr <= 0 or self.source_data_ptr <= 0:
            raise ValueError("Mesh frame snapshot需要有效source identity")
        if self.base_pose_object_ptr <= 0:
            raise ValueError("Mesh frame snapshot需要有效BasePose identity")
        if not self.mesh_topology_signature:
            raise ValueError("Mesh frame snapshot需要Mesh topology identity signature")
        positions = self.animated_base_world_positions
        normals = self.animated_base_world_normals
        if positions.dtype != np.float32 or normals.dtype != np.float32:
            raise TypeError("Mesh frame snapshot数组必须是float32")
        if positions.ndim != 2 or positions.shape[1] != 3 or normals.shape != positions.shape:
            raise ValueError("Mesh frame snapshot必须是匹配的float32[N,3] positions/normals")
        if positions.flags.writeable or normals.flags.writeable:
            raise ValueError("Mesh frame snapshot数组必须只读")
        if not np.isfinite(positions).all() or not np.isfinite(normals).all():
            raise ValueError("Mesh frame snapshot不能包含NaN/Inf")


def _cache_key(
    source_obj: bpy.types.Object,
    base_obj: bpy.types.Object,
    frame: int,
    generation: int,
    mesh_topology_signature: str,
) -> tuple:
    return (
        _FRAME_CACHE_PREFIX,
        int(source_obj.as_pointer()),
        int(source_obj.data.as_pointer()),
        int(base_obj.as_pointer()),
        int(frame),
        int(generation),
        str(mesh_topology_signature),
    )


def _trim_cache(cache: dict, frame: int, generation: int) -> None:
    stale = []
    for key in cache:
        if not isinstance(key, tuple) or len(key) != 7 or key[0] != _FRAME_CACHE_PREFIX:
            continue
        if int(key[5]) != int(generation) or abs(int(key[4]) - int(frame)) > 3:
            stale.append(key)
    for key in stale:
        cache.pop(key, None)


def _read_evaluated_world_pose(
    base_obj: bpy.types.Object,
    depsgraph,
    expected_vertex_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    evaluated = base_obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    if mesh is None:
        raise ValueError(f"{base_obj.name} BasePose evaluated mesh读取失败")
    try:
        vertex_count = len(mesh.vertices)
        if vertex_count != expected_vertex_count:
            raise ValueError(
                "BasePose evaluated mesh改变了final-proxy顶点数量："
                f"expected={expected_vertex_count} actual={vertex_count}"
            )
        positions = np.empty(vertex_count * 3, dtype=np.float32)
        normals = np.empty(vertex_count * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", positions)
        mesh.vertices.foreach_get("normal", normals)
        positions = positions.reshape((vertex_count, 3))
        normals = normals.reshape((vertex_count, 3))
        matrix = _matrix_to_numpy(evaluated.matrix_world)
        world_positions = positions @ matrix[:3, :3].T + matrix[:3, 3]
        world_normals = normals @ matrix[:3, :3].T
        lengths = np.linalg.norm(world_normals, axis=1)
        valid = lengths > _NORMAL_EPSILON
        normalized_normals = np.zeros_like(world_normals, dtype=np.float32)
        normalized_normals[valid] = world_normals[valid] / lengths[valid, None]
        return _readonly_float3(world_positions), _readonly_float3(normalized_normals)
    finally:
        evaluated.to_mesh_clear()


def read_base_pose_frame_snapshot(
    source_obj: bpy.types.Object,
    base_obj: bpy.types.Object,
    *,
    mesh_topology_signature: str,
    frame: int,
    generation: int = 0,
    depsgraph=None,
    cache: dict | None = None,
) -> MC2MeshFrameSnapshot:
    signature = str(mesh_topology_signature or "")
    if not signature:
        raise ValueError("读取Mesh N3 frame前必须提供Mesh topology identity signature")
    validate_base_pose_proxy(source_obj, base_obj, signature)
    key = _cache_key(source_obj, base_obj, frame, generation, signature)
    if isinstance(cache, dict):
        cached = cache.get(key)
        if isinstance(cached, MC2MeshFrameSnapshot):
            return cached

    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    positions, normals = _read_evaluated_world_pose(
        base_obj,
        depsgraph,
        len(source_obj.data.vertices),
    )
    snapshot = MC2MeshFrameSnapshot(
        source_object_ptr=int(source_obj.as_pointer()),
        source_data_ptr=int(source_obj.data.as_pointer()),
        base_pose_object_ptr=int(base_obj.as_pointer()),
        frame=int(frame),
        generation=int(generation),
        mesh_topology_signature=signature,
        animated_base_world_positions=positions,
        animated_base_world_normals=normals,
    )
    if isinstance(cache, dict):
        cache[key] = snapshot
        _trim_cache(cache, frame, generation)
    return snapshot


def build_mc2_mesh_frame_input(
    snapshot: MC2MeshFrameSnapshot,
    mesh_static,
    *,
    topology_signature: str,
) -> MC2FrameInputSpec:
    """Build MC2 world pose using the frozen N0 triangle/UV orientation records."""
    if not isinstance(snapshot, MC2MeshFrameSnapshot):
        raise TypeError("snapshot must be MC2MeshFrameSnapshot")
    final_proxy = getattr(mesh_static, "final_proxy", None)
    finalizer = getattr(mesh_static, "finalizer", None)
    if final_proxy is None or finalizer is None:
        raise TypeError("mesh_static must be MC2MeshClothStaticBuildResult")
    if final_proxy.vertex_count != snapshot.vertex_count:
        raise ValueError("Mesh frame snapshot and static proxy vertex counts differ")
    topology_signature = str(topology_signature or "")
    if not topology_signature:
        raise ValueError("Mesh frame input requires the task topology signature")
    records = tuple(finalizer.vertex_to_triangle_records)
    if len(records) != snapshot.vertex_count or any(not value for value in records):
        raise ValueError("N3 Mesh frame orientation currently requires every vertex to belong to a triangle")

    positions = np.asarray(snapshot.animated_base_world_positions, dtype=np.float64)
    triangles = tuple(tuple(int(value) for value in triangle) for triangle in final_proxy.triangles)
    uvs = np.asarray(final_proxy.uvs, dtype=np.float64)
    triangle_normals = [_triangle_normal(positions, triangle) for triangle in triangles]
    triangle_tangents = [_triangle_tangent(positions, uvs, triangle) for triangle in triangles]
    normals, binormals = _apply_vertex_triangle_normals(
        snapshot.animated_base_world_normals,
        final_proxy.local_tangents,
        triangle_normals,
        triangle_tangents,
        records,
    )
    rotations = np.asarray(
        [_orientation_xyzw(normal, binormal) for normal, binormal in zip(normals, binormals)],
        dtype=np.float32,
    )
    return make_mc2_frame_input(
        task_id=final_proxy.task_id,
        topology_signature=topology_signature,
        frame=snapshot.frame,
        generation=snapshot.generation,
        world_positions=snapshot.animated_base_world_positions,
        world_rotations_xyzw=rotations,
    )


__all__ = [
    "MC2MeshFrameSnapshot",
    "build_mc2_mesh_frame_input",
    "read_base_pose_frame_snapshot",
]
