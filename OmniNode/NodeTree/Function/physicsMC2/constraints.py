"""MeshCloth 的纯数组约束投影。

本模块不读取 Blender 对象，也不处理碰撞快照。C++ 后端应优先对齐这里的
distance、tether、motion 行为，再逐步替换 Python 调度层。
"""

import numpy as np

from . import params
from .constants import MC2SystemConstants


def project_neighbor_constraints(
    positions: np.ndarray,
    inv_masses: np.ndarray,
    starts: np.ndarray,
    counts: np.ndarray,
    neighbors: np.ndarray,
    rest_lengths: np.ndarray,
    stiffness: float,
) -> None:
    stiffness = max(0.0, min(1.0, float(stiffness)))
    if stiffness <= MC2SystemConstants.EPSILON or len(neighbors) == 0:
        return

    vertex_count = len(positions)
    for vertex_index in range(vertex_count):
        wi = float(inv_masses[vertex_index])
        if wi <= MC2SystemConstants.EPSILON:
            continue

        start = int(starts[vertex_index])
        count = int(counts[vertex_index])
        if count <= 0:
            continue

        add = np.zeros(3, dtype=np.float32)
        add_count = 0
        current = positions[vertex_index]
        for offset in range(count):
            data_index = start + offset
            neighbor_index = int(neighbors[data_index])
            rest = abs(float(rest_lengths[data_index]))
            wj = float(inv_masses[neighbor_index])
            wsum = wi + wj
            if wsum <= MC2SystemConstants.EPSILON:
                continue

            delta = positions[neighbor_index] - current
            distance = float(np.linalg.norm(delta))
            if distance <= MC2SystemConstants.EPSILON:
                continue

            normal = delta / distance
            correction = ((distance - rest) * stiffness / wsum) * wi * normal
            add += correction
            add_count += 1

        if add_count > 0:
            positions[vertex_index] = current + add / float(add_count)


def project_tether(
    positions: np.ndarray,
    inv_masses: np.ndarray,
    root_indices: np.ndarray,
    root_rest_lengths: np.ndarray,
    stiffness: float,
    compression: float,
    stretch: float,
) -> None:
    stiffness = max(0.0, min(1.0, float(stiffness)))
    if stiffness <= MC2SystemConstants.EPSILON:
        return

    compression_limit = 1.0 - max(0.0, min(1.0, float(compression)))
    stretch_limit = 1.0 + max(0.0, float(stretch))
    stiffness_width = max(float(MC2SystemConstants.TETHER_STIFFNESS_WIDTH), MC2SystemConstants.EPSILON)

    for vertex_index in range(len(positions)):
        if float(inv_masses[vertex_index]) <= MC2SystemConstants.EPSILON:
            continue
        root_index = int(root_indices[vertex_index])
        if root_index < 0:
            continue
        rest_length = float(root_rest_lengths[vertex_index])
        if rest_length <= MC2SystemConstants.EPSILON:
            continue

        delta = positions[root_index] - positions[vertex_index]
        distance = float(np.linalg.norm(delta))
        if distance <= MC2SystemConstants.EPSILON:
            continue

        ratio = distance / rest_length
        dist = 0.0
        solve_stiffness = 0.0
        if ratio < compression_limit:
            dist = distance - compression_limit * rest_length
            fade = max(0.0, min(1.0, (compression_limit - ratio) / stiffness_width))
            solve_stiffness = stiffness * MC2SystemConstants.TETHER_COMPRESSION_STIFFNESS * fade
        elif ratio > stretch_limit:
            dist = distance - stretch_limit * rest_length
            fade = max(0.0, min(1.0, (ratio - stretch_limit) / stiffness_width))
            solve_stiffness = stiffness * MC2SystemConstants.TETHER_STRETCH_STIFFNESS * fade

        if solve_stiffness <= MC2SystemConstants.EPSILON:
            continue

        positions[vertex_index] += (delta / distance) * (dist * solve_stiffness)


def project_motion_constraint(
    positions: np.ndarray,
    base_positions: np.ndarray,
    inv_masses: np.ndarray,
    depths: np.ndarray,
    max_distance_param: dict,
    motion_stiffness_param: dict,
    world_scale: float,
) -> None:
    motion_depths = np.clip(np.ascontiguousarray(depths, dtype=np.float32) ** 2, 0.0, 1.0)
    max_distances = params.sample_param(max_distance_param, motion_depths) * max(float(world_scale), 0.0)
    stiffness_values = np.clip(params.sample_param(motion_stiffness_param, motion_depths), 0.0, 1.0)
    if not bool(np.any(max_distances > MC2SystemConstants.EPSILON)):
        return
    if not bool(np.any(stiffness_values > MC2SystemConstants.EPSILON)):
        return

    for vertex_index in range(len(positions)):
        if float(inv_masses[vertex_index]) <= MC2SystemConstants.EPSILON:
            continue
        limit = float(max_distances[vertex_index])
        if limit <= MC2SystemConstants.EPSILON:
            continue
        stiffness = float(stiffness_values[vertex_index])
        if stiffness <= MC2SystemConstants.EPSILON:
            continue
        original_position = positions[vertex_index].copy()
        delta = original_position - base_positions[vertex_index]
        distance = float(np.linalg.norm(delta))
        if distance > limit and distance > MC2SystemConstants.EPSILON:
            constrained = base_positions[vertex_index] + (delta / distance) * limit
            positions[vertex_index] = original_position * (1.0 - stiffness) + constrained * stiffness
