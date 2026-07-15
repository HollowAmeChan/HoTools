"""由三种 MC2 setup topology 构建统一粒子初始状态。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from ..utils.math3d import (
    cross3_tuple as _cross,
    dot3_tuple as _dot,
    matrix4_tuple,
    matrix4_tuple_from_flat as _matrix_from_flat,
    matrix4_tuple_multiply as _matrix_multiply,
    normalize3_tuple as _normalize,
    quaternion_from_axes_xyzw_tuple as _quaternion_from_axes,
    quaternion_from_matrix4_xyzw_tuple as _quaternion_from_matrix,
    transform_direction_matrix4_tuple as _transform_direction,
    transform_point_matrix4_tuple as _transform_point,
)

from .specs import MC2TaskSpec
from .topology import MC2TopologySpec, _thaw


def _signature(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _matrix4(value) -> tuple[tuple[float, ...], ...]:
    return matrix4_tuple(
        value,
        finite_message="MC2 initial state 矩阵不能包含 NaN/Inf",
    )


def _mesh_vertex_quaternion(matrix, normal) -> tuple[float, float, float, float]:
    local_up = _normalize(normal)
    reference = (0.0, 0.0, 1.0) if abs(_dot(local_up, (0.0, 0.0, 1.0))) < 0.95 else (1.0, 0.0, 0.0)
    local_right = _normalize(_cross(local_up, reference))
    local_forward = _normalize(_cross(local_right, local_up))
    world_up = _transform_direction(matrix, local_up)
    world_right = _transform_direction(matrix, local_right)
    world_forward = _normalize(_cross(world_right, world_up))
    world_right = _normalize(_cross(world_up, world_forward))
    return _quaternion_from_axes(world_right, world_up, world_forward)


def _source_matrix(source):
    if isinstance(source, dict):
        source = source.get("armature") or source.get("object") or source.get("proxy_obj")
    elif isinstance(source, tuple) and len(source) == 2:
        source = source[0]
    return _matrix4(getattr(source, "matrix_world", None))


@dataclass(frozen=True)
class MC2InitialStateSpec:
    task_id: str
    setup_type: str
    topology_signature: str
    particle_count: int
    rest_positions: tuple[tuple[float, float, float], ...]
    rest_rotations: tuple[tuple[float, float, float, float], ...]
    parent_indices: tuple[int, ...]
    depths: tuple[float, ...]
    fixed_mask: tuple[bool, ...]
    source_indices: tuple[int, ...]
    source_local_indices: tuple[int, ...]
    initial_state_signature: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        arrays = (
            self.rest_positions,
            self.rest_rotations,
            self.parent_indices,
            self.depths,
            self.fixed_mask,
            self.source_indices,
            self.source_local_indices,
        )
        if any(len(array) != self.particle_count for array in arrays):
            raise ValueError("MC2InitialStateSpec 数组长度不一致")

    def debug_dict(self, *, include_arrays: bool = False) -> dict:
        result = {
            "task_id": self.task_id,
            "setup_type": self.setup_type,
            "topology_signature": self.topology_signature,
            "particle_count": self.particle_count,
            "fixed_count": sum(1 for value in self.fixed_mask if value),
            "root_count": sum(1 for value in self.parent_indices if value < 0),
            "initial_state_signature": self.initial_state_signature,
            "schema_version": self.schema_version,
        }
        if include_arrays:
            result.update({
                "rest_positions": self.rest_positions,
                "rest_rotations": self.rest_rotations,
                "parent_indices": self.parent_indices,
                "depths": self.depths,
                "fixed_mask": self.fixed_mask,
                "source_indices": self.source_indices,
                "source_local_indices": self.source_local_indices,
            })
        return result


def _make_initial_state(
    task: MC2TaskSpec,
    topology: MC2TopologySpec,
    *,
    positions,
    rotations,
    parent_indices,
    depths,
    fixed_mask,
    source_indices,
    source_local_indices,
) -> MC2InitialStateSpec:
    payload = {
        "schema_version": 1,
        "task_id": task.task_id,
        "setup_type": task.setup_type,
        "topology_signature": topology.topology_signature,
        "rest_positions": positions,
        "rest_rotations": rotations,
        "parent_indices": parent_indices,
        "depths": depths,
        "fixed_mask": fixed_mask,
        "source_indices": source_indices,
        "source_local_indices": source_local_indices,
    }
    return MC2InitialStateSpec(
        task_id=task.task_id,
        setup_type=task.setup_type,
        topology_signature=topology.topology_signature,
        particle_count=len(positions),
        rest_positions=tuple(positions),
        rest_rotations=tuple(rotations),
        parent_indices=tuple(int(value) for value in parent_indices),
        depths=tuple(float(value) for value in depths),
        fixed_mask=tuple(bool(value) for value in fixed_mask),
        source_indices=tuple(int(value) for value in source_indices),
        source_local_indices=tuple(int(value) for value in source_local_indices),
        initial_state_signature=_signature(payload),
    )


def build_mc2_mesh_initial_state(
    task: MC2TaskSpec,
    topology: MC2TopologySpec,
) -> MC2InitialStateSpec:
    positions = []
    rotations = []
    source_indices = []
    source_local_indices = []
    for source_topology in topology.sources:
        payload = _thaw(source_topology.payload)
        matrix = _source_matrix(task.sources[source_topology.source_index])
        local_positions = payload.get("positions", ())
        local_normals = payload.get("normals", ())
        for local_index, local_position in enumerate(local_positions):
            positions.append(_transform_point(matrix, local_position))
            normal = local_normals[local_index] if local_index < len(local_normals) else (0.0, 1.0, 0.0)
            rotations.append(_mesh_vertex_quaternion(matrix, normal))
            source_indices.append(source_topology.source_index)
            source_local_indices.append(local_index)
    count = len(positions)
    return _make_initial_state(
        task,
        topology,
        positions=positions,
        rotations=rotations,
        parent_indices=(-1,) * count,
        depths=(0.0,) * count,
        fixed_mask=(False,) * count,
        source_indices=source_indices,
        source_local_indices=source_local_indices,
    )


def _normalized_depths(parent_indices: list[int]) -> tuple[float, ...]:
    raw_depths = []
    for index, parent in enumerate(parent_indices):
        depth = 0
        visited = {index}
        while parent >= 0 and parent not in visited:
            visited.add(parent)
            depth += 1
            parent = parent_indices[parent]
        raw_depths.append(depth)
    maximum = max(raw_depths, default=0)
    if maximum <= 0:
        return tuple(0.0 for _ in raw_depths)
    return tuple(depth / maximum for depth in raw_depths)


def build_mc2_bone_initial_state(
    task: MC2TaskSpec,
    topology: MC2TopologySpec,
) -> MC2InitialStateSpec:
    positions = []
    rotations = []
    parent_indices: list[int] = []
    fixed_mask = []
    source_indices = []
    source_local_indices = []
    particle_offset = 0
    for source_topology in topology.sources:
        payload = _thaw(source_topology.payload)
        source = task.sources[source_topology.source_index]
        armature_matrix = _source_matrix(source)
        records = payload.get("bones", ())
        for local_index, record in enumerate(records):
            bone_matrix = _matrix_from_flat(record.get("matrix_local"))
            world_matrix = _matrix_multiply(armature_matrix, bone_matrix)
            positions.append(_transform_point(armature_matrix, record.get("head", (0.0, 0.0, 0.0))))
            rotations.append(_quaternion_from_matrix(world_matrix))
            parent_value = record.get("parent_index", -1)
            local_parent = -1 if parent_value is None else int(parent_value)
            parent_indices.append(particle_offset + local_parent if local_parent >= 0 else -1)
            fixed_mask.append(local_parent < 0)
            source_indices.append(source_topology.source_index)
            source_local_indices.append(local_index)
        particle_offset += len(records)
    depths = _normalized_depths(parent_indices)
    return _make_initial_state(
        task,
        topology,
        positions=positions,
        rotations=rotations,
        parent_indices=parent_indices,
        depths=depths,
        fixed_mask=fixed_mask,
        source_indices=source_indices,
        source_local_indices=source_local_indices,
    )


def build_mc2_initial_state(
    task: MC2TaskSpec,
    topology: MC2TopologySpec,
) -> MC2InitialStateSpec:
    if not isinstance(task, MC2TaskSpec):
        raise TypeError("task 必须是 MC2TaskSpec")
    if not isinstance(topology, MC2TopologySpec):
        raise TypeError("topology 必须是 MC2TopologySpec")
    if task.task_id != topology.task_id:
        raise ValueError("task 与 topology 不匹配")
    from .setups import get_mc2_setup_adapter

    return get_mc2_setup_adapter(task.setup_type).build_initial_state(task, topology)


__all__ = [
    "MC2InitialStateSpec",
    "build_mc2_bone_initial_state",
    "build_mc2_initial_state",
    "build_mc2_mesh_initial_state",
]
