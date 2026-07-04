"""MC2 Mesh/Bone 共用 baseline 数据构建。

baseline 是 MC2 在 MeshCloth 和 BoneCloth 之间共用的父子参考链。MeshCloth 从固定点和
mesh 邻接关系生成这条链；BoneCloth 后续可以直接从骨骼 Transform 父子关系生成同一套数组。
"""

from collections import deque

import numpy as np

from .constants import MC2_ATTR_MOVE, MC2SystemConstants


def _empty_i() -> np.ndarray:
    return np.empty(0, dtype=np.int32)


def _identity_quaternions(count: int) -> np.ndarray:
    values = np.zeros((int(count), 4), dtype=np.float32)
    if count > 0:
        values[:, 3] = 1.0
    return np.ascontiguousarray(values, dtype=np.float32)


def _safe_normal(vector: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length > MC2SystemConstants.EPSILON:
        return np.asarray(vector / length, dtype=np.float32)
    fallback_length = float(np.linalg.norm(fallback))
    if fallback_length > MC2SystemConstants.EPSILON:
        return np.asarray(fallback / fallback_length, dtype=np.float32)
    return np.asarray((0.0, 0.0, 1.0), dtype=np.float32)


def _perpendicular(vector: np.ndarray) -> np.ndarray:
    axis = np.asarray((1.0, 0.0, 0.0), dtype=np.float32)
    if abs(float(np.dot(_safe_normal(vector, axis), axis))) > 0.85:
        axis = np.asarray((0.0, 1.0, 0.0), dtype=np.float32)
    return _safe_normal(np.cross(vector, axis), np.asarray((0.0, 0.0, 1.0), dtype=np.float32))


def _quat_normalize(quat: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(quat))
    if length <= MC2SystemConstants.EPSILON:
        return np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    return np.asarray(quat / length, dtype=np.float32)


def _quat_from_matrix(matrix: np.ndarray) -> np.ndarray:
    m = np.asarray(matrix, dtype=np.float32)
    trace = float(m[0, 0] + m[1, 1] + m[2, 2])
    if trace > 0.0:
        s = float(np.sqrt(trace + 1.0) * 2.0)
        return _quat_normalize(
            np.asarray(
                (
                    (m[2, 1] - m[1, 2]) / s,
                    (m[0, 2] - m[2, 0]) / s,
                    (m[1, 0] - m[0, 1]) / s,
                    0.25 * s,
                ),
                dtype=np.float32,
            )
        )
    if m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = float(np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0)
        return _quat_normalize(
            np.asarray(
                (
                    0.25 * s,
                    (m[0, 1] + m[1, 0]) / s,
                    (m[0, 2] + m[2, 0]) / s,
                    (m[2, 1] - m[1, 2]) / s,
                ),
                dtype=np.float32,
            )
        )
    if m[1, 1] > m[2, 2]:
        s = float(np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0)
        return _quat_normalize(
            np.asarray(
                (
                    (m[0, 1] + m[1, 0]) / s,
                    0.25 * s,
                    (m[1, 2] + m[2, 1]) / s,
                    (m[0, 2] - m[2, 0]) / s,
                ),
                dtype=np.float32,
            )
        )
    s = float(np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0)
    return _quat_normalize(
        np.asarray(
            (
                (m[0, 2] + m[2, 0]) / s,
                (m[1, 2] + m[2, 1]) / s,
                0.25 * s,
                (m[1, 0] - m[0, 1]) / s,
            ),
            dtype=np.float32,
        )
    )


def quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ax, ay, az, aw = (float(a[0]), float(a[1]), float(a[2]), float(a[3]))
    bx, by, bz, bw = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
    return _quat_normalize(
        np.asarray(
            (
                aw * bx + ax * bw + ay * bz - az * by,
                aw * by - ax * bz + ay * bw + az * bx,
                aw * bz + ax * by - ay * bx + az * bw,
                aw * bw - ax * bx - ay * by - az * bz,
            ),
            dtype=np.float32,
        )
    )


def quat_inverse(quat: np.ndarray) -> np.ndarray:
    q = _quat_normalize(np.asarray(quat, dtype=np.float32))
    return np.asarray((-q[0], -q[1], -q[2], q[3]), dtype=np.float32)


def quat_rotate(quat: np.ndarray, vector: np.ndarray) -> np.ndarray:
    q = _quat_normalize(np.asarray(quat, dtype=np.float32))
    v = np.asarray(vector, dtype=np.float32)
    qv = q[:3]
    uv = np.cross(qv, v)
    uuv = np.cross(qv, uv)
    return np.ascontiguousarray(v + 2.0 * (q[3] * uv + uuv), dtype=np.float32)


def _slerp(a: np.ndarray, b: np.ndarray, ratio: float) -> np.ndarray:
    t = max(0.0, min(1.0, float(ratio)))
    qa = _quat_normalize(np.asarray(a, dtype=np.float32))
    qb = _quat_normalize(np.asarray(b, dtype=np.float32))
    dot = float(np.dot(qa, qb))
    if dot < 0.0:
        qb = -qb
        dot = -dot
    if dot > 0.9995:
        return _quat_normalize(qa + (qb - qa) * t)
    theta0 = float(np.arccos(max(-1.0, min(1.0, dot))))
    theta = theta0 * t
    sin_theta = float(np.sin(theta))
    sin_theta0 = float(np.sin(theta0))
    s0 = float(np.cos(theta) - dot * sin_theta / sin_theta0)
    s1 = float(sin_theta / sin_theta0)
    return _quat_normalize((s0 * qa) + (s1 * qb))


def _frame_rotation(forward: np.ndarray, normal: np.ndarray) -> np.ndarray:
    z_axis = _safe_normal(forward, normal)
    up_hint = _safe_normal(normal, np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
    x_axis = np.cross(up_hint, z_axis)
    if float(np.linalg.norm(x_axis)) <= MC2SystemConstants.EPSILON:
        x_axis = _perpendicular(z_axis)
    else:
        x_axis = _safe_normal(x_axis, np.asarray((1.0, 0.0, 0.0), dtype=np.float32))
    y_axis = _safe_normal(np.cross(z_axis, x_axis), up_hint)
    matrix = np.asarray(
        (
            (x_axis[0], y_axis[0], z_axis[0]),
            (x_axis[1], y_axis[1], z_axis[1]),
            (x_axis[2], y_axis[2], z_axis[2]),
        ),
        dtype=np.float32,
    )
    return _quat_from_matrix(matrix)


def _build_adjacency(vertex_count: int, edges: np.ndarray) -> list[list[int]]:
    adjacency = [[] for _ in range(int(vertex_count))]
    for edge in np.ascontiguousarray(edges, dtype=np.int32):
        i = int(edge[0])
        j = int(edge[1])
        if i < 0 or j < 0 or i >= vertex_count or j >= vertex_count or i == j:
            continue
        adjacency[i].append(j)
        adjacency[j].append(i)
    return adjacency


def _select_parent(
    vertex_index: int,
    adjacency: list[list[int]],
    positions: np.ndarray,
    attributes: np.ndarray,
    parents: np.ndarray,
    mark: np.ndarray,
) -> int:
    pos = positions[vertex_index]
    best_cost = None
    best_index = -1
    for neighbor in adjacency[vertex_index]:
        if int(mark[neighbor]) == 0:
            continue
        neighbor_pos = positions[neighbor]
        if (int(attributes[neighbor]) & MC2_ATTR_MOVE) == 0:
            cost = float(np.linalg.norm(pos - neighbor_pos))
        else:
            parent_index = int(parents[neighbor])
            if parent_index < 0:
                continue
            v1 = neighbor_pos - pos
            v2 = positions[parent_index] - neighbor_pos
            len1 = float(np.linalg.norm(v1))
            len2 = float(np.linalg.norm(v2))
            if len1 <= MC2SystemConstants.EPSILON or len2 <= MC2SystemConstants.EPSILON:
                cost = 0.0
            else:
                dot = max(-1.0, min(1.0, float(np.dot(v1 / len1, v2 / len2))))
                cost = float(np.arccos(dot))
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_index = int(neighbor)
    return best_index


def _child_lists(vertex_count: int, parents: np.ndarray) -> list[list[int]]:
    children = [[] for _ in range(int(vertex_count))]
    for child_index, parent_index in enumerate(np.ascontiguousarray(parents, dtype=np.int32)):
        parent = int(parent_index)
        if 0 <= parent < vertex_count:
            children[parent].append(int(child_index))
    return children


def _build_mesh_parent_indices(
    edges: np.ndarray,
    rest_positions: np.ndarray,
    attributes: np.ndarray,
) -> np.ndarray:
    vertex_count = int(len(rest_positions))
    parents = np.full(vertex_count, -1, dtype=np.int32)
    if vertex_count == 0:
        return parents

    adjacency = _build_adjacency(vertex_count, edges)
    fixed_roots = [int(i) for i in np.nonzero((attributes & MC2_ATTR_MOVE) == 0)[0]]
    if not fixed_roots:
        return np.ascontiguousarray(parents, dtype=np.int32)

    mark = np.zeros(vertex_count, dtype=np.uint8)
    frontier = list(fixed_roots)
    for root in frontier:
        mark[root] = 2

    while frontier:
        candidates = set()
        for vertex_index in frontier:
            for neighbor in adjacency[vertex_index]:
                if int(mark[neighbor]) != 0:
                    continue
                if (int(attributes[neighbor]) & MC2_ATTR_MOVE) == 0:
                    continue
                candidates.add(int(neighbor))
        if not candidates:
            break

        next_frontier = []
        for vertex_index in sorted(candidates):
            parent_index = _select_parent(vertex_index, adjacency, rest_positions, attributes, parents, mark)
            if parent_index < 0:
                continue
            parents[vertex_index] = int(parent_index)
            mark[vertex_index] = 1
            next_frontier.append(vertex_index)

        for vertex_index in next_frontier:
            mark[vertex_index] = 2
        frontier = next_frontier

    return np.ascontiguousarray(parents, dtype=np.int32)


def _baseline_chains(
    attributes: np.ndarray,
    parents: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    vertex_count = int(len(attributes))
    children = _child_lists(vertex_count, parents)
    starts = []
    counts = []
    data = []
    flags = []
    roots = [int(i) for i in np.nonzero((attributes & MC2_ATTR_MOVE) == 0)[0]]
    for root in roots:
        if not children[root]:
            continue
        start = len(data)
        count = 0
        stack = [root]
        while stack:
            vertex_index = int(stack.pop())
            data.append(vertex_index)
            count += 1
            for child in reversed(children[vertex_index]):
                stack.append(int(child))
        starts.append(start)
        counts.append(count)
        flags.append(0)
    return (
        np.ascontiguousarray(np.asarray(starts, dtype=np.int32), dtype=np.int32),
        np.ascontiguousarray(np.asarray(counts, dtype=np.int32), dtype=np.int32),
        np.ascontiguousarray(np.asarray(data, dtype=np.int32), dtype=np.int32),
        np.ascontiguousarray(np.asarray(flags, dtype=np.uint8), dtype=np.uint8),
    )


def _depth_and_roots(
    positions: np.ndarray,
    attributes: np.ndarray,
    parents: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    vertex_count = int(len(positions))
    depths = np.ones(vertex_count, dtype=np.float32)
    roots = np.full(vertex_count, -1, dtype=np.int32)
    root_lengths = np.zeros(vertex_count, dtype=np.float32)
    fixed = (attributes & MC2_ATTR_MOVE) == 0
    depths[fixed] = 0.0
    roots[fixed] = np.nonzero(fixed)[0].astype(np.int32)

    for vertex_index in range(vertex_count):
        if not bool(int(attributes[vertex_index]) & MC2_ATTR_MOVE):
            continue
        length = 0.0
        current = int(vertex_index)
        visited = set()
        root_index = -1
        while True:
            parent = int(parents[current])
            if parent < 0 or parent >= vertex_count or parent in visited:
                break
            visited.add(current)
            length += float(np.linalg.norm(positions[current] - positions[parent]))
            root_index = parent
            if not bool(int(attributes[parent]) & MC2_ATTR_MOVE):
                break
            current = parent
        roots[vertex_index] = int(root_index)
        root_lengths[vertex_index] = float(length)

    reached = (roots >= 0) & ((attributes & MC2_ATTR_MOVE) != 0)
    max_length = float(np.max(root_lengths[reached])) if bool(np.any(reached)) else 0.0
    if max_length > MC2SystemConstants.EPSILON:
        depths[reached] = np.clip(root_lengths[reached] / max_length, 0.0, 1.0)
    return (
        np.ascontiguousarray(depths, dtype=np.float32),
        np.ascontiguousarray(roots, dtype=np.int32),
        np.ascontiguousarray(root_lengths, dtype=np.float32),
    )


def _base_rotations(
    positions: np.ndarray,
    normals: np.ndarray,
    parents: np.ndarray,
) -> np.ndarray:
    vertex_count = int(len(positions))
    rotations = _identity_quaternions(vertex_count)
    children = _child_lists(vertex_count, parents)
    for vertex_index in range(vertex_count):
        if children[vertex_index]:
            forward = np.zeros(3, dtype=np.float32)
            for child in children[vertex_index]:
                forward += positions[int(child)] - positions[vertex_index]
        else:
            parent = int(parents[vertex_index])
            forward = (
                positions[vertex_index] - positions[parent]
                if 0 <= parent < vertex_count
                else normals[vertex_index]
            )
        rotations[vertex_index] = _frame_rotation(forward, normals[vertex_index])
    return np.ascontiguousarray(rotations, dtype=np.float32)


def base_rotations_from_pose(
    positions: np.ndarray,
    normals: np.ndarray,
    parents: np.ndarray,
) -> np.ndarray:
    return _base_rotations(positions, normals, parents)


def _local_pose(
    positions: np.ndarray,
    base_rotations: np.ndarray,
    parents: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    vertex_count = int(len(positions))
    local_positions = np.zeros((vertex_count, 3), dtype=np.float32)
    local_rotations = _identity_quaternions(vertex_count)
    for vertex_index in range(vertex_count):
        parent = int(parents[vertex_index])
        if parent < 0 or parent >= vertex_count:
            continue
        inverse_parent = quat_inverse(base_rotations[parent])
        local_positions[vertex_index] = quat_rotate(inverse_parent, positions[vertex_index] - positions[parent])
        local_rotations[vertex_index] = quat_mul(inverse_parent, base_rotations[vertex_index])
    return (
        np.ascontiguousarray(local_positions, dtype=np.float32),
        np.ascontiguousarray(local_rotations, dtype=np.float32),
    )


def update_step_basic_pose(
    base_positions: np.ndarray,
    base_rotations: np.ndarray,
    parents: np.ndarray,
    baseline_start: np.ndarray,
    baseline_count: np.ndarray,
    baseline_data: np.ndarray,
    vertex_local_positions: np.ndarray,
    vertex_local_rotations: np.ndarray,
    animation_pose_ratio: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    step_positions = np.ascontiguousarray(base_positions, dtype=np.float32).copy()
    step_rotations = np.ascontiguousarray(base_rotations, dtype=np.float32).copy()
    ratio = max(0.0, min(1.0, float(animation_pose_ratio)))
    if ratio > 0.99 or len(baseline_data) == 0:
        return step_positions, step_rotations

    for line_index in range(len(baseline_start)):
        start = int(baseline_start[line_index])
        count = int(baseline_count[line_index])
        for data_offset in range(count):
            data_index = start + data_offset
            if data_index < 0 or data_index >= len(baseline_data):
                continue
            vertex_index = int(baseline_data[data_index])
            if vertex_index < 0 or vertex_index >= len(step_positions):
                continue
            parent = int(parents[vertex_index])
            if 0 <= parent < len(step_positions):
                parent_pos = step_positions[parent]
                parent_rot = step_rotations[parent]
                step_positions[vertex_index] = parent_pos + quat_rotate(
                    parent_rot,
                    vertex_local_positions[vertex_index],
                )
                step_rotations[vertex_index] = quat_mul(parent_rot, vertex_local_rotations[vertex_index])
        if ratio > MC2SystemConstants.EPSILON:
            for data_offset in range(count):
                data_index = start + data_offset
                if data_index < 0 or data_index >= len(baseline_data):
                    continue
                vertex_index = int(baseline_data[data_index])
                step_positions[vertex_index] = (
                    step_positions[vertex_index] * (1.0 - ratio)
                    + base_positions[vertex_index] * ratio
                )
                step_rotations[vertex_index] = _slerp(
                    step_rotations[vertex_index],
                    base_rotations[vertex_index],
                    ratio,
                )
    return (
        np.ascontiguousarray(step_positions, dtype=np.float32),
        np.ascontiguousarray(step_rotations, dtype=np.float32),
    )


def build_mesh_baseline(
    edges: np.ndarray,
    rest_positions: np.ndarray,
    rest_normals: np.ndarray,
    attributes: np.ndarray,
) -> dict:
    vertex_count = int(len(rest_positions))
    positions = np.ascontiguousarray(rest_positions, dtype=np.float32)
    normals = np.ascontiguousarray(rest_normals, dtype=np.float32)
    if normals.shape != positions.shape:
        normals = np.zeros_like(positions, dtype=np.float32)
        if vertex_count > 0:
            normals[:, 2] = 1.0
    attr = np.ascontiguousarray(attributes, dtype=np.uint8)

    parent_indices = _build_mesh_parent_indices(edges, positions, attr)
    baseline_start, baseline_count, baseline_data, baseline_flags = _baseline_chains(attr, parent_indices)
    depths, root_indices, root_rest_lengths = _depth_and_roots(positions, attr, parent_indices)
    base_rotations = _base_rotations(positions, normals, parent_indices)
    vertex_local_positions, vertex_local_rotations = _local_pose(positions, base_rotations, parent_indices)
    step_basic_positions, step_basic_rotations = update_step_basic_pose(
        positions,
        base_rotations,
        parent_indices,
        baseline_start,
        baseline_count,
        baseline_data,
        vertex_local_positions,
        vertex_local_rotations,
    )

    return {
        "baseline_start": baseline_start,
        "baseline_count": baseline_count,
        "baseline_data": baseline_data,
        "baseline_flags": baseline_flags,
        "parent_indices": parent_indices,
        "depths": depths,
        "root_indices": root_indices,
        "root_rest_lengths": root_rest_lengths,
        "base_rotations": base_rotations,
        "vertex_local_positions": vertex_local_positions,
        "vertex_local_rotations": vertex_local_rotations,
        "step_basic_positions": step_basic_positions,
        "step_basic_rotations": step_basic_rotations,
    }
