"""Blender N3 frame snapshots for the dual-object MC2 MeshCloth path."""

from __future__ import annotations

from dataclasses import dataclass

import bpy
from mathutils import Matrix
import numpy as np

from ...center_state import MC2CenterFramePoseSpec
from ...frame_state import MC2FrameInputSpec, make_mc2_frame_input
from .base_pose import validate_base_pose_proxy


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


def _decompose_component_transform(evaluated_source, source_matrix):
    position, rotation, decomposed_scale = source_matrix.decompose()
    local_scale = tuple(float(value) for value in evaluated_source.scale)
    parent = evaluated_source.parent
    while parent is not None:
        parent_scale = tuple(float(value) for value in parent.scale)
        if any(value < 0.0 for value in parent_scale):
            raise ValueError(
                "MC2 negative-scale Mesh source does not support negative scale "
                "inherited from a parent"
            )
        if any(abs(value) <= _NORMAL_EPSILON for value in parent_scale):
            raise ValueError("MC2 component parent scale cannot contain zero")
        parent = parent.parent
    if not any(value < 0.0 for value in local_scale):
        rotation.normalize()
        return position, rotation, decomposed_scale
    signed_scale = np.asarray(
        [
            (-1.0 if local < 0.0 else 1.0) * abs(float(world))
            for local, world in zip(local_scale, decomposed_scale)
        ],
        dtype=np.float64,
    )
    if np.any(np.abs(signed_scale) <= _NORMAL_EPSILON):
        raise ValueError("MC2 component scale cannot contain zero")
    linear = _matrix_to_numpy(source_matrix)[:3, :3].astype(np.float64)
    rotation_matrix = linear / signed_scale[np.newaxis, :]
    if not np.allclose(
        rotation_matrix.T @ rotation_matrix,
        np.eye(3),
        rtol=1.0e-5,
        atol=1.0e-6,
    ) or np.linalg.det(rotation_matrix) <= 0.0:
        raise ValueError(
            "MC2 negative-scale Mesh source world transform must be shear-free"
        )
    rotation = Matrix(rotation_matrix.tolist()).to_quaternion()
    rotation.normalize()
    return position, rotation, tuple(float(value) for value in signed_scale)


@dataclass(frozen=True)
class MC2MeshFrameSnapshot:
    source_object_ptr: int
    source_data_ptr: int
    base_pose_object_ptr: int
    frame: int
    generation: int
    mesh_topology_signature: str
    source_world_linear: np.ndarray
    component_world_position: tuple[float, float, float]
    component_world_rotation_xyzw: tuple[float, float, float, float]
    component_world_scale: tuple[float, float, float]
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
        linear = self.source_world_linear
        if positions.dtype != np.float32 or normals.dtype != np.float32:
            raise TypeError("Mesh frame snapshot数组必须是float32")
        if positions.ndim != 2 or positions.shape[1] != 3 or normals.shape != positions.shape:
            raise ValueError("Mesh frame snapshot必须是匹配的float32[N,3] positions/normals")
        if positions.flags.writeable or normals.flags.writeable:
            raise ValueError("Mesh frame snapshot数组必须只读")
        if linear.dtype != np.float32 or linear.shape != (3, 3) or linear.flags.writeable:
            raise ValueError("Mesh frame snapshot source_world_linear必须是只读float32[3,3]")
        if not np.isfinite(linear).all() or abs(float(np.linalg.det(linear))) <= 1.0e-12:
            raise ValueError("Mesh frame snapshot source_world_linear必须有限且可逆")
        if not np.isfinite(positions).all() or not np.isfinite(normals).all():
            raise ValueError("Mesh frame snapshot不能包含NaN/Inf")
        if len(self.component_world_position) != 3 or not np.isfinite(
            self.component_world_position
        ).all():
            raise ValueError("Mesh frame snapshot component position must be finite float3")
        if len(self.component_world_scale) != 3 or not np.isfinite(
            self.component_world_scale
        ).all():
            raise ValueError("Mesh frame snapshot component scale must be finite float3")
        if any(abs(value) <= _NORMAL_EPSILON for value in self.component_world_scale):
            raise ValueError("Mesh frame snapshot component scale cannot contain zero")
        rotation = np.asarray(self.component_world_rotation_xyzw, dtype=np.float64)
        if rotation.shape != (4,) or not np.isfinite(rotation).all() or not np.isclose(
            np.linalg.norm(rotation), 1.0, rtol=1.0e-5, atol=1.0e-6
        ):
            raise ValueError("Mesh frame snapshot component rotation must be a unit quaternion")


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
    evaluated_source = source_obj.evaluated_get(depsgraph)
    source_matrix = evaluated_source.matrix_world.copy()
    component_position, component_rotation, component_scale = (
        _decompose_component_transform(evaluated_source, source_matrix)
    )
    snapshot = MC2MeshFrameSnapshot(
        source_object_ptr=int(source_obj.as_pointer()),
        source_data_ptr=int(source_obj.data.as_pointer()),
        base_pose_object_ptr=int(base_obj.as_pointer()),
        frame=int(frame),
        generation=int(generation),
        mesh_topology_signature=signature,
        source_world_linear=_readonly_float3(
            _matrix_to_numpy(source_matrix)[:3, :3]
        ),
        component_world_position=tuple(float(value) for value in component_position),
        component_world_rotation_xyzw=(
            float(component_rotation.x),
            float(component_rotation.y),
            float(component_rotation.z),
            float(component_rotation.w),
        ),
        component_world_scale=tuple(float(value) for value in component_scale),
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
    coverage = getattr(finalizer, "every_vertex_has_triangle", None)
    if coverage is None:
        records = tuple(finalizer.vertex_to_triangle_records)
        coverage = len(records) == snapshot.vertex_count and all(records)
    if not coverage:
        raise ValueError("N3 Mesh frame orientation currently requires every vertex to belong to a triangle")

    return make_mc2_frame_input(
        task_id=final_proxy.task_id,
        topology_signature=topology_signature,
        frame=snapshot.frame,
        generation=snapshot.generation,
        world_positions=snapshot.animated_base_world_positions,
        world_rotations_xyzw=None,
        source_world_linear=snapshot.source_world_linear,
        center_frame_pose=MC2CenterFramePoseSpec(
            frame=snapshot.frame,
            generation=snapshot.generation,
            component_identity=f"object:{snapshot.source_object_ptr}",
            component_world_position=snapshot.component_world_position,
            component_world_rotation_xyzw=snapshot.component_world_rotation_xyzw,
            component_world_scale=snapshot.component_world_scale,
        ),
    )


def build_mc2_mesh_frame_input_for_task(
    world,
    task,
    topology,
    mesh_static,
    *,
    depsgraph=None,
) -> MC2FrameInputSpec:
    """Read the configured BasePose and build the active World's N3 snapshot."""
    sources = tuple(getattr(task, "sources", ()) or ())
    if getattr(task, "setup_type", None) != "mesh_cloth" or len(sources) != 1:
        raise ValueError("automatic MC2 Mesh frame input requires one mesh_cloth source")
    source_obj = sources[0]
    if getattr(source_obj, "type", None) != "MESH" or getattr(source_obj, "data", None) is None:
        raise ValueError("automatic MC2 Mesh frame input source is not a Mesh object")
    properties = getattr(source_obj, "hotools_mesh_collision", None)
    base_obj = getattr(properties, "mc2_base_pose_proxy", None) if properties is not None else None
    if base_obj is None:
        raise ValueError(
            "MC2 Mesh source has no BasePose proxy; create or assign mc2_base_pose_proxy first"
        )
    frame_context = getattr(world, "frame_context", None)
    frame = int(getattr(frame_context, "frame", 0) or 0)
    generation = int(
        getattr(frame_context, "generation", 0)
        or getattr(world, "generation", 0)
        or 0
    )
    if generation <= 0:
        raise ValueError("automatic MC2 Mesh frame input requires an active Physics World")
    expected_topology = str(getattr(mesh_static, "mesh_topology_signature", "") or "")
    if not expected_topology:
        raise ValueError("MC2 Mesh static bundle has no topology identity token")
    snapshot = read_base_pose_frame_snapshot(
        source_obj,
        base_obj,
        mesh_topology_signature=expected_topology,
        frame=frame,
        generation=generation,
        depsgraph=depsgraph,
        cache=getattr(world, "runtime_caches", None),
    )
    return build_mc2_mesh_frame_input(
        snapshot,
        mesh_static,
        topology_signature=str(getattr(topology, "topology_signature", "") or ""),
    )


__all__ = [
    "MC2MeshFrameSnapshot",
    "build_mc2_mesh_frame_input",
    "build_mc2_mesh_frame_input_for_task",
    "read_base_pose_frame_snapshot",
]
