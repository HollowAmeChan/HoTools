"""由三种 MC2 setup topology 构建统一粒子初始状态。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

from .specs import MC2TaskSpec
from .topology import MC2TopologySpec, _thaw


IDENTITY_QUATERNION = (0.0, 0.0, 0.0, 1.0)
IDENTITY_MATRIX = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def _signature(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _matrix4(value) -> tuple[tuple[float, ...], ...]:
    if value is None:
        return IDENTITY_MATRIX
    try:
        rows = tuple(tuple(float(component) for component in row) for row in value)
    except (TypeError, ValueError):
        return IDENTITY_MATRIX
    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        return IDENTITY_MATRIX
    if not all(math.isfinite(component) for row in rows for component in row):
        raise ValueError("MC2 initial state 矩阵不能包含 NaN/Inf")
    return rows


def _matrix_from_flat(value) -> tuple[tuple[float, ...], ...]:
    values = tuple(float(component) for component in (value or ()))
    if len(values) != 16:
        return IDENTITY_MATRIX
    return tuple(tuple(values[row * 4 + column] for column in range(4)) for row in range(4))


def _matrix_multiply(left, right):
    return tuple(
        tuple(
            sum(left[row][index] * right[index][column] for index in range(4))
            for column in range(4)
        )
        for row in range(4)
    )


def _transform_point(matrix, point) -> tuple[float, float, float]:
    x, y, z = (float(component) for component in point)
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + matrix[0][3],
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + matrix[1][3],
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + matrix[2][3],
    )


def _transform_direction(matrix, direction) -> tuple[float, float, float]:
    x, y, z = (float(component) for component in direction)
    return _normalize((
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z,
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z,
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z,
    ))


def _dot(left, right) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right))


def _cross(left, right) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _normalize(value) -> tuple[float, float, float]:
    vector = tuple(float(component) for component in value)
    length = math.sqrt(_dot(vector, vector))
    if length <= 1.0e-8:
        return (0.0, 1.0, 0.0)
    return tuple(component / length for component in vector)


def _quaternion_from_axes(right, up, forward) -> tuple[float, float, float, float]:
    # Rotation matrix columns are the local X/Y/Z axes in world space.
    m00, m01, m02 = right[0], up[0], forward[0]
    m10, m11, m12 = right[1], up[1], forward[1]
    m20, m21, m22 = right[2], up[2], forward[2]
    trace = m00 + m11 + m22
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (m21 - m12) / scale
        y = (m02 - m20) / scale
        z = (m10 - m01) / scale
    elif m00 > m11 and m00 > m22:
        scale = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w = (m21 - m12) / scale
        x = 0.25 * scale
        y = (m01 + m10) / scale
        z = (m02 + m20) / scale
    elif m11 > m22:
        scale = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w = (m02 - m20) / scale
        x = (m01 + m10) / scale
        y = 0.25 * scale
        z = (m12 + m21) / scale
    else:
        scale = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w = (m10 - m01) / scale
        x = (m02 + m20) / scale
        y = (m12 + m21) / scale
        z = 0.25 * scale
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if length <= 1.0e-8:
        return IDENTITY_QUATERNION
    return (x / length, y / length, z / length, w / length)


def _quaternion_from_matrix(matrix) -> tuple[float, float, float, float]:
    right = _normalize((matrix[0][0], matrix[1][0], matrix[2][0]))
    up_hint = _normalize((matrix[0][1], matrix[1][1], matrix[2][1]))
    forward = _normalize(_cross(right, up_hint))
    up = _normalize(_cross(forward, right))
    return _quaternion_from_axes(right, up, forward)


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
