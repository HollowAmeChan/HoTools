"""Source Mesh authoring data 到 XPBD 静态数组与逐帧 reference frame。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import numpy as np

from .specs import MeshXpbdTaskSpec


_EPSILON = 1.0e-8


def _readonly(values, dtype, shape) -> np.ndarray:
    result = np.array(values, dtype=dtype, order="C", copy=True).reshape(shape)
    if not np.isfinite(result).all():
        raise ValueError("Mesh XPBD 静态数组不能包含 NaN 或 Inf")
    result.setflags(write=False)
    return result


def _collection_values(collection, attribute: str, width: int, dtype) -> np.ndarray:
    count = len(collection)
    result = np.empty((count, width), dtype=dtype)
    callback = getattr(collection, "foreach_get", None)
    if callable(callback) and count:
        callback(attribute, result.reshape(-1))
        return result
    for index, item in enumerate(collection):
        value = getattr(item, attribute)
        values = tuple(value) if width > 1 else (value,)
        if len(values) != width:
            raise ValueError(f"Mesh {attribute} 必须包含 {width} 个分量")
        result[index] = values
    return result


def _reference_local_positions(mesh) -> np.ndarray:
    shape_keys = getattr(mesh, "shape_keys", None)
    reference = getattr(shape_keys, "reference_key", None) if shape_keys is not None else None
    if reference is not None:
        collection = getattr(reference, "data", ())
    else:
        collection = getattr(mesh, "vertices", ())
    positions = _collection_values(collection, "co", 3, np.float32)
    if positions.shape[0] != len(getattr(mesh, "vertices", ())):
        raise ValueError("Basis/reference key 顶点数必须匹配 source Mesh")
    return positions


def _canonical_edges(mesh, particle_count: int) -> np.ndarray:
    edges = _collection_values(getattr(mesh, "edges", ()), "vertices", 2, np.int32)
    if edges.size == 0:
        return np.empty((0, 2), dtype=np.int32)
    if np.any(edges < 0) or np.any(edges >= particle_count) or np.any(edges[:, 0] == edges[:, 1]):
        raise ValueError("Mesh edge 包含非法顶点索引")
    edges = np.sort(edges, axis=1)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    edges = np.ascontiguousarray(edges[order], dtype=np.int32)
    if len(edges) > 1 and np.any(np.all(edges[1:] == edges[:-1], axis=1)):
        raise ValueError("Mesh edge 包含重复无向边")
    return edges


def _canonical_loop_triangles(mesh, particle_count: int) -> np.ndarray:
    callback = getattr(mesh, "calc_loop_triangles", None)
    if callable(callback):
        callback()
    triangles = _collection_values(
        getattr(mesh, "loop_triangles", ()), "vertices", 3, np.int32
    )
    if triangles.size == 0:
        return np.empty((0, 3), dtype=np.int32)
    if np.any(triangles < 0) or np.any(triangles >= particle_count):
        raise ValueError("Mesh loop triangle 包含非法顶点索引")
    if np.any(
        (triangles[:, 0] == triangles[:, 1])
        | (triangles[:, 1] == triangles[:, 2])
        | (triangles[:, 0] == triangles[:, 2])
    ):
        raise ValueError("Mesh loop triangle 不能退化为重复顶点")
    canonical = np.sort(triangles, axis=1)
    order = np.lexsort((canonical[:, 2], canonical[:, 1], canonical[:, 0]))
    canonical = np.ascontiguousarray(canonical[order], dtype=np.int32)
    if len(canonical) > 1 and np.any(np.all(canonical[1:] == canonical[:-1], axis=1)):
        raise ValueError("Mesh loop triangle 包含重复三角面")
    return canonical


def _bend_pairs(triangles: np.ndarray) -> tuple[np.ndarray, int]:
    edge_opposites: dict[tuple[int, int], set[int]] = {}
    for first, second, third in triangles.tolist():
        for a, b, opposite in (
            (first, second, third),
            (second, third, first),
            (third, first, second),
        ):
            edge = (a, b) if a < b else (b, a)
            edge_opposites.setdefault(edge, set()).add(opposite)

    pairs = set()
    non_manifold_edge_count = 0
    for opposites in edge_opposites.values():
        if len(opposites) > 2:
            non_manifold_edge_count += 1
            continue
        if len(opposites) != 2:
            continue
        first, second = sorted(opposites)
        if first != second:
            pairs.add((first, second))
    ordered = sorted(pairs)
    return np.asarray(ordered, dtype=np.int32).reshape((-1, 2)), non_manifold_edge_count


def _vertex_group_weights(source_object, group_name: str) -> np.ndarray:
    vertices = getattr(getattr(source_object, "data", None), "vertices", ())
    weights = np.zeros((len(vertices),), dtype=np.float32)
    name = str(group_name or "")
    if not name:
        weights.fill(1.0)
        return weights
    groups = getattr(source_object, "vertex_groups", None)
    group = groups.get(name) if groups is not None and hasattr(groups, "get") else None
    if group is None:
        raise ValueError(f"Mesh XPBD 顶点组不存在: {name}")
    group_index = int(getattr(group, "index", -1))
    if group_index < 0:
        raise ValueError(f"Mesh XPBD 顶点组索引无效: {name}")
    for vertex_index, vertex in enumerate(vertices):
        for membership in getattr(vertex, "groups", ()):
            if int(getattr(membership, "group", -1)) != group_index:
                continue
            weight = float(getattr(membership, "weight", 0.0))
            if not math.isfinite(weight) or weight < 0.0 or weight > 1.0:
                raise ValueError(f"Mesh XPBD 顶点组 {name} 包含非法权重")
            weights[vertex_index] = weight
            break
    return weights


def _static_arrays(spec: MeshXpbdTaskSpec, particle_count: int) -> tuple[np.ndarray, np.ndarray]:
    inverse_masses = np.ones((particle_count,), dtype=np.float32)
    if spec.pin_enabled:
        pin_weights = _vertex_group_weights(spec.source_object, spec.pin_vertex_group)
        inverse_masses[pin_weights > 0.0] = 0.0

    local_radii = np.zeros((particle_count,), dtype=np.float32)
    if spec.collision_enabled and spec.collision_radius > 0.0:
        radius_weights = _vertex_group_weights(spec.source_object, spec.radius_vertex_group)
        local_radii = np.ascontiguousarray(
            radius_weights * np.float32(spec.collision_radius), dtype=np.float32
        )
    return inverse_masses, local_radii


def _digest_arrays(label: str, arrays, extra=()) -> str:
    digest = hashlib.sha256()
    digest.update(label.encode("ascii"))
    for value in extra:
        digest.update(str(value).encode("utf-8"))
        digest.update(b"\0")
    for values in arrays:
        array = np.ascontiguousarray(values)
        digest.update(str(array.dtype).encode("ascii"))
        digest.update(np.asarray(array.shape, dtype=np.int64).tobytes())
        digest.update(array.tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class MeshXpbdTopology:
    source_object_ptr: int
    source_data_ptr: int
    particle_count: int
    rest_local_positions: np.ndarray
    stretch_indices: np.ndarray
    loop_triangles: np.ndarray
    bend_indices: np.ndarray
    inverse_masses: np.ndarray
    local_collision_radii: np.ndarray
    topology_signature: str
    static_signature: str
    non_manifold_bend_edge_count: int

    def debug_dict(self) -> dict:
        return {
            "schema": "mesh_xpbd_topology_v1",
            "source_object_ptr": self.source_object_ptr,
            "source_data_ptr": self.source_data_ptr,
            "particle_count": self.particle_count,
            "stretch_constraint_count": int(self.stretch_indices.shape[0]),
            "triangle_count": int(self.loop_triangles.shape[0]),
            "bend_constraint_count": int(self.bend_indices.shape[0]),
            "non_manifold_bend_edge_count": self.non_manifold_bend_edge_count,
            "topology_signature": self.topology_signature,
            "static_signature": self.static_signature,
        }


@dataclass(frozen=True)
class MeshXpbdReferenceFrame:
    matrix_world: np.ndarray
    inverse_linear: np.ndarray
    rest_world_positions: np.ndarray
    world_collision_radii: np.ndarray
    signature: str

    def local_offsets(self, world_positions) -> np.ndarray:
        positions = np.asarray(world_positions, dtype=np.float32)
        if positions.shape != self.rest_world_positions.shape or not np.isfinite(positions).all():
            raise ValueError("Mesh XPBD world positions 必须匹配 reference frame")
        world_offsets = positions - self.rest_world_positions
        return np.ascontiguousarray(world_offsets @ self.inverse_linear.T, dtype=np.float32)


def build_mesh_xpbd_topology(spec: MeshXpbdTaskSpec) -> MeshXpbdTopology:
    if not isinstance(spec, MeshXpbdTaskSpec):
        raise TypeError("build_mesh_xpbd_topology 需要 MeshXpbdTaskSpec")
    mesh = getattr(spec.source_object, "data", None)
    mesh_users = int(getattr(mesh, "users", 0) or 0)
    if mesh_users > 1:
        raise ValueError(
            "Mesh XPBD source Mesh 必须是 single-user；公共 GN offset 不能为共享 Mesh 数据保存对象级结果"
        )
    rest_positions = _reference_local_positions(mesh)
    particle_count = int(rest_positions.shape[0])
    if particle_count <= 0:
        raise ValueError("Mesh XPBD source Mesh 不能为空")
    edges = _canonical_edges(mesh, particle_count)
    triangles = _canonical_loop_triangles(mesh, particle_count)
    bend_indices, non_manifold_count = _bend_pairs(triangles)
    inverse_masses, local_radii = _static_arrays(spec, particle_count)

    rest_positions = _readonly(rest_positions, np.float32, (particle_count, 3))
    edges = _readonly(edges, np.int32, (-1, 2))
    triangles = _readonly(triangles, np.int32, (-1, 3))
    bend_indices = _readonly(bend_indices, np.int32, (-1, 2))
    inverse_masses = _readonly(inverse_masses, np.float32, (particle_count,))
    local_radii = _readonly(local_radii, np.float32, (particle_count,))
    topology_signature = _digest_arrays(
        "mesh_xpbd_topology_v1",
        (edges, triangles),
        (spec.source_object_ptr, spec.source_data_ptr),
    )
    static_signature = _digest_arrays(
        "mesh_xpbd_static_v1",
        (rest_positions, inverse_masses, local_radii),
        (topology_signature, spec.static_signature),
    )
    return MeshXpbdTopology(
        spec.source_object_ptr,
        spec.source_data_ptr,
        particle_count,
        rest_positions,
        edges,
        triangles,
        bend_indices,
        inverse_masses,
        local_radii,
        topology_signature,
        static_signature,
        non_manifold_count,
    )


def build_mesh_xpbd_reference_frame(
    topology: MeshXpbdTopology,
    source_object,
) -> MeshXpbdReferenceFrame:
    try:
        matrix = np.asarray(
            [[float(source_object.matrix_world[row][column]) for column in range(4)] for row in range(4)],
            dtype=np.float64,
        )
    except Exception:
        matrix = np.asarray(source_object.matrix_world, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError("Mesh XPBD matrix_world 必须是有限 4x4 matrix")
    linear = matrix[:3, :3]
    determinant = float(np.linalg.det(linear))
    if not math.isfinite(determinant) or abs(determinant) <= _EPSILON:
        raise ValueError("Mesh XPBD matrix_world 线性部分不可逆")
    inverse_linear = np.linalg.inv(linear)
    local_positions = np.asarray(topology.rest_local_positions, dtype=np.float64)
    rest_world = local_positions @ linear.T + matrix[:3, 3]
    axis_scales = np.linalg.norm(linear, axis=0)
    radius_scale = float(np.max(axis_scales))
    if not math.isfinite(radius_scale):
        raise ValueError("Mesh XPBD matrix_world 半径缩放无效")
    world_radii = np.asarray(topology.local_collision_radii, dtype=np.float64) * radius_scale
    matrix32 = _readonly(matrix, np.float32, (4, 4))
    inverse32 = _readonly(inverse_linear, np.float32, (3, 3))
    rest_world32 = _readonly(rest_world, np.float32, (topology.particle_count, 3))
    radii32 = _readonly(world_radii, np.float32, (topology.particle_count,))
    signature = _digest_arrays(
        "mesh_xpbd_reference_frame_v1",
        (matrix32, rest_world32, radii32),
        (topology.static_signature,),
    )
    return MeshXpbdReferenceFrame(
        matrix32,
        inverse32,
        rest_world32,
        radii32,
        signature,
    )
