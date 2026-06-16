"""MeshCloth 的网格读取与约束数组构建。

本模块只读取用户提供的低模代理 mesh，并生成求解器内部需要的数组。
它永远不负责减面、重拓扑、代理生成或高低模映射。
"""

from collections import deque

import bpy
import numpy as np

from . import math_utils
from .constants import (
    MC2_ATTR_FIXED,
    MC2_ATTR_MOTION,
    MC2_ATTR_MOVE,
    MC2_DISTANCE_TYPE_BEND_DISTANCE_APPROX,
    MC2_DISTANCE_TYPE_STRUCTURAL,
    MC2_SOLVER_VERSION,
    MC2SystemConstants,
)


def mesh_collision_props(obj: bpy.types.Object):
    return getattr(obj, "hotools_mesh_collision", None)


def vertex_group_weights(obj: bpy.types.Object, group_name: str) -> np.ndarray:
    weights = np.zeros(len(obj.data.vertices), dtype=np.float32)
    if not group_name:
        weights.fill(1.0)
        return weights

    vertex_group = obj.vertex_groups.get(group_name)
    if vertex_group is None:
        return weights

    group_index = int(vertex_group.index)
    for vertex in obj.data.vertices:
        for group in vertex.groups:
            if group.group == group_index:
                weights[vertex.index] = max(0.0, min(1.0, float(group.weight)))
                break
    return weights


def mesh_pin_config(obj: bpy.types.Object) -> tuple[bool, str]:
    props = mesh_collision_props(obj)
    if props is None or not bool(getattr(props, "pin_enabled", False)):
        return False, ""
    return True, str(getattr(props, "pin_vertex_group", "") or "")


def build_attributes(obj: bpy.types.Object) -> np.ndarray:
    vertex_count = len(obj.data.vertices)
    attributes = np.full(vertex_count, MC2_ATTR_MOVE | MC2_ATTR_MOTION, dtype=np.uint8)
    pin_enabled, pin_group_name = mesh_pin_config(obj)
    if not pin_enabled:
        return attributes

    if not pin_group_name:
        attributes.fill(MC2_ATTR_FIXED)
        return attributes

    weights = vertex_group_weights(obj, pin_group_name)
    fixed = weights > 0.0
    attributes[fixed] = MC2_ATTR_FIXED
    attributes[~fixed] = MC2_ATTR_MOVE | MC2_ATTR_MOTION
    return attributes


def build_collision_profile(obj: bpy.types.Object, fallback_radius: float) -> tuple[np.ndarray, int]:
    props = mesh_collision_props(obj)
    radii = np.zeros(len(obj.data.vertices), dtype=np.float32)
    fallback_radius = max(float(fallback_radius), 0.0)

    if props is not None and bool(getattr(props, "enabled", False)):
        radius = max(float(getattr(props, "radius", 0.0)), 0.0)
        if radius <= MC2SystemConstants.EPSILON:
            return radii, 0

        weights = vertex_group_weights(obj, str(getattr(props, "radius_vertex_group", "") or ""))
        radii = np.ascontiguousarray(weights * radius, dtype=np.float32)
        mask = math_utils.clamp_group_mask(getattr(props, "collided_by_groups", 0))
        return radii, mask

    if fallback_radius <= MC2SystemConstants.EPSILON:
        return radii, 0

    radii.fill(fallback_radius)
    return radii, 0xFFFF


def collision_radii_to_world(obj: bpy.types.Object, local_radii: np.ndarray) -> np.ndarray:
    scale = math_utils.matrix_scale_radius(obj.matrix_world)
    return np.ascontiguousarray(local_radii * scale, dtype=np.float32)


def mesh_connectivity_arrays(mesh: bpy.types.Mesh) -> tuple[np.ndarray, np.ndarray]:
    """只读取当前 mesh 连接关系；永远不修改、不减面、不重映射。"""
    edge_values = np.empty(len(mesh.edges) * 2, dtype=np.int32)
    if len(edge_values) > 0:
        mesh.edges.foreach_get("vertices", edge_values)
    edges = edge_values.reshape((len(mesh.edges), 2)) if len(mesh.edges) else np.empty((0, 2), dtype=np.int32)

    try:
        mesh.calc_loop_triangles()
    except Exception:
        pass

    triangles = []
    for triangle in mesh.loop_triangles:
        verts = tuple(int(v) for v in triangle.vertices)
        if len(verts) == 3:
            triangles.append(verts)
    triangle_array = (
        np.asarray(triangles, dtype=np.int32).reshape((-1, 3))
        if triangles
        else np.empty((0, 3), dtype=np.int32)
    )
    return np.ascontiguousarray(edges, dtype=np.int32), np.ascontiguousarray(triangle_array, dtype=np.int32)


def rest_local_normals(obj: bpy.types.Object) -> np.ndarray:
    mesh = obj.data
    vertex_count = len(mesh.vertices)
    if vertex_count == 0:
        return np.empty((0, 3), dtype=np.float32)

    try:
        mesh.calc_normals_split()
    except Exception:
        pass

    normals = np.zeros((vertex_count, 3), dtype=np.float32)
    counts = np.zeros(vertex_count, dtype=np.float32)
    try:
        for polygon in mesh.polygons:
            for loop_index in polygon.loop_indices:
                loop = mesh.loops[loop_index]
                vertex_index = int(loop.vertex_index)
                normal = loop.normal
                normals[vertex_index] += (float(normal.x), float(normal.y), float(normal.z))
                counts[vertex_index] += 1.0
    except Exception:
        for vertex in mesh.vertices:
            normal = vertex.normal
            normals[int(vertex.index)] = (float(normal.x), float(normal.y), float(normal.z))
            counts[int(vertex.index)] = 1.0

    fallback = np.asarray((0.0, 0.0, 1.0), dtype=np.float32)
    for vertex_index in range(vertex_count):
        if counts[vertex_index] > 0.0:
            normals[vertex_index] /= counts[vertex_index]
        length = float(np.linalg.norm(normals[vertex_index]))
        if length > MC2SystemConstants.EPSILON:
            normals[vertex_index] /= length
        else:
            normals[vertex_index] = fallback
    return np.ascontiguousarray(normals, dtype=np.float32)


def mesh_signature_key(obj: bpy.types.Object) -> tuple:
    mesh = obj.data
    edges, triangles = mesh_connectivity_arrays(mesh)
    return (
        int(obj.as_pointer()),
        int(mesh.as_pointer()),
        len(mesh.vertices),
        len(mesh.edges),
        len(mesh.polygons),
        math_utils.array_hash(edges),
        math_utils.array_hash(triangles),
    )


def config_key(
    obj: bpy.types.Object,
    shape_key_name: str,
    mesh_signature_key_value: tuple,
    collision_radius: float,
) -> tuple:
    pin_enabled, pin_group = mesh_pin_config(obj)
    pin_weights = vertex_group_weights(obj, pin_group) if pin_enabled and pin_group else np.empty(0, dtype=np.float32)
    props = mesh_collision_props(obj)
    collision_enabled = bool(props is not None and getattr(props, "enabled", False))
    radius_group = str(getattr(props, "radius_vertex_group", "") or "") if props is not None else ""
    radius_weights = vertex_group_weights(obj, radius_group) if radius_group else np.empty(0, dtype=np.float32)
    configured_radius = (
        float(getattr(props, "radius", 0.0))
        if collision_enabled
        else float(collision_radius)
    )
    configured_mask = (
        math_utils.clamp_group_mask(getattr(props, "collided_by_groups", 0))
        if collision_enabled
        else (0xFFFF if float(collision_radius) > MC2SystemConstants.EPSILON else 0)
    )
    return (
        MC2_SOLVER_VERSION,
        shape_key_name,
        mesh_signature_key_value,
        bool(pin_enabled),
        pin_group,
        math_utils.array_hash(pin_weights),
        collision_enabled,
        round(configured_radius, 8),
        radius_group,
        math_utils.array_hash(radius_weights),
        configured_mask,
    )


def build_edge_constraints(
    edges: np.ndarray,
    rest_positions: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if len(edges) == 0:
        empty_i = np.empty(0, dtype=np.int32)
        empty_f = np.empty(0, dtype=np.float32)
        return empty_i, empty_i.copy(), empty_f

    edge_i = np.ascontiguousarray(edges[:, 0], dtype=np.int32)
    edge_j = np.ascontiguousarray(edges[:, 1], dtype=np.int32)
    delta = rest_positions[edge_i] - rest_positions[edge_j]
    rest = np.ascontiguousarray(np.linalg.norm(delta, axis=1), dtype=np.float32)
    return edge_i, edge_j, rest


def build_bend_constraints(
    triangles: np.ndarray,
    rest_positions: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    edge_to_opposites = {}
    for triangle in triangles:
        a, b, c = (int(triangle[0]), int(triangle[1]), int(triangle[2]))
        for i, j, opposite in ((a, b, c), (b, c, a), (c, a, b)):
            key = (i, j) if i < j else (j, i)
            edge_to_opposites.setdefault(key, []).append(opposite)

    pairs = []
    triangle_pairs = []
    seen = set()
    for edge, opposites in edge_to_opposites.items():
        unique = []
        for vertex_index in opposites:
            if vertex_index not in unique:
                unique.append(vertex_index)
        if len(unique) < 2:
            continue
        i, j = unique[0], unique[1]
        key = (i, j) if i < j else (j, i)
        if i == j or key in seen:
            continue
        pairs.append((i, j))
        triangle_pairs.append((edge[0], edge[1], i, j))
        seen.add(key)

    if not pairs:
        empty_i = np.empty(0, dtype=np.int32)
        empty_f = np.empty(0, dtype=np.float32)
        return empty_i, empty_i.copy(), empty_f, np.empty((0, 4), dtype=np.int32)

    pair_array = np.asarray(pairs, dtype=np.int32)
    bend_i = np.ascontiguousarray(pair_array[:, 0], dtype=np.int32)
    bend_j = np.ascontiguousarray(pair_array[:, 1], dtype=np.int32)
    delta = rest_positions[bend_i] - rest_positions[bend_j]
    bend_rest = np.ascontiguousarray(np.linalg.norm(delta, axis=1), dtype=np.float32)
    return (
        bend_i,
        bend_j,
        bend_rest,
        np.ascontiguousarray(np.asarray(triangle_pairs, dtype=np.int32).reshape((-1, 4)), dtype=np.int32),
    )


def constraint_lengths(
    positions: np.ndarray,
    index_i: np.ndarray,
    index_j: np.ndarray,
) -> np.ndarray:
    if len(index_i) == 0:
        return np.empty(0, dtype=np.float32)
    delta = positions[index_i] - positions[index_j]
    return np.ascontiguousarray(np.linalg.norm(delta, axis=1), dtype=np.float32)


def constraint_types(count: int, constraint_type: int) -> np.ndarray:
    if count <= 0:
        return np.empty(0, dtype=np.int32)
    values = np.full(int(count), int(constraint_type), dtype=np.int32)
    return np.ascontiguousarray(values, dtype=np.int32)


def structural_constraint_types(index_i: np.ndarray) -> np.ndarray:
    return constraint_types(len(index_i), MC2_DISTANCE_TYPE_STRUCTURAL)


def bend_distance_constraint_types(index_i: np.ndarray) -> np.ndarray:
    return constraint_types(len(index_i), MC2_DISTANCE_TYPE_BEND_DISTANCE_APPROX)


def build_neighbor_table(
    vertex_count: int,
    index_i: np.ndarray,
    index_j: np.ndarray,
    rest_lengths: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    adjacency = [[] for _ in range(vertex_count)]
    for constraint_index in range(len(index_i)):
        i = int(index_i[constraint_index])
        j = int(index_j[constraint_index])
        rest = float(rest_lengths[constraint_index])
        if i < 0 or j < 0 or i >= vertex_count or j >= vertex_count or i == j:
            continue
        adjacency[i].append((j, rest))
        adjacency[j].append((i, rest))

    counts = np.asarray([len(items) for items in adjacency], dtype=np.int32)
    starts = np.zeros(vertex_count, dtype=np.int32)
    if vertex_count > 1:
        starts[1:] = np.cumsum(counts[:-1], dtype=np.int32)
    total = int(np.sum(counts))
    data = np.empty(total, dtype=np.int32)
    rests = np.empty(total, dtype=np.float32)
    cursor = 0
    for items in adjacency:
        for neighbor, rest in items:
            data[cursor] = int(neighbor)
            rests[cursor] = float(rest)
            cursor += 1
    return starts, counts, np.ascontiguousarray(data, dtype=np.int32), np.ascontiguousarray(rests, dtype=np.float32)


def build_adjacency(vertex_count: int, edges: np.ndarray) -> list[list[int]]:
    adjacency = [[] for _ in range(vertex_count)]
    for edge in edges:
        i = int(edge[0])
        j = int(edge[1])
        if i < 0 or j < 0 or i >= vertex_count or j >= vertex_count or i == j:
            continue
        adjacency[i].append(j)
        adjacency[j].append(i)
    return adjacency


def build_depth_and_roots(
    edges: np.ndarray,
    rest_positions: np.ndarray,
    attributes: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    vertex_count = len(rest_positions)
    adjacency = build_adjacency(vertex_count, edges)
    fixed = (attributes & MC2_ATTR_MOVE) == 0
    roots = np.full(vertex_count, -1, dtype=np.int32)
    parents = np.full(vertex_count, -1, dtype=np.int32)
    root_lengths = np.zeros(vertex_count, dtype=np.float32)
    distance_from_root = np.full(vertex_count, np.inf, dtype=np.float32)
    queue = deque()

    for index in np.nonzero(fixed)[0]:
        roots[index] = int(index)
        distance_from_root[index] = 0.0
        queue.append(int(index))

    while queue:
        current = queue.popleft()
        current_pos = rest_positions[current]
        for neighbor in adjacency[current]:
            segment = float(np.linalg.norm(rest_positions[neighbor] - current_pos))
            candidate = float(distance_from_root[current]) + segment
            if candidate + MC2SystemConstants.EPSILON >= float(distance_from_root[neighbor]):
                continue
            roots[neighbor] = roots[current] if roots[current] >= 0 else current
            parents[neighbor] = current
            distance_from_root[neighbor] = candidate
            queue.append(neighbor)

    finite = np.isfinite(distance_from_root)
    if bool(np.any(finite)):
        root_lengths[finite] = np.ascontiguousarray(distance_from_root[finite], dtype=np.float32)
    else:
        root_lengths.fill(0.0)

    move_reached = finite & ((attributes & MC2_ATTR_MOVE) != 0)
    max_length = float(np.max(root_lengths[move_reached])) if bool(np.any(move_reached)) else 0.0
    depths = np.ones(vertex_count, dtype=np.float32)
    if max_length > MC2SystemConstants.EPSILON:
        depths[finite] = np.clip(root_lengths[finite] / max_length, 0.0, 1.0)
        depths[fixed] = 0.0
    elif bool(np.any(fixed)):
        depths[fixed] = 0.0

    return (
        np.ascontiguousarray(depths, dtype=np.float32),
        np.ascontiguousarray(roots, dtype=np.int32),
        np.ascontiguousarray(parents, dtype=np.int32),
        np.ascontiguousarray(root_lengths, dtype=np.float32),
    )


def build_tether_rest_lengths(positions: np.ndarray, root_indices: np.ndarray) -> np.ndarray:
    lengths = np.zeros(len(positions), dtype=np.float32)
    for vertex_index in range(len(positions)):
        root_index = int(root_indices[vertex_index])
        if root_index < 0 or root_index >= len(positions):
            continue
        lengths[vertex_index] = float(np.linalg.norm(positions[vertex_index] - positions[root_index]))
    return np.ascontiguousarray(lengths, dtype=np.float32)
