"""Pure MeshCloth baseline builder for the final-proxy MC2 N0 contract.

The algorithm follows MagicaCloth2 2.18.1 ``CreateMeshBaseLine()``,
``CreateBaseLinePose()``, and ``CreateVertexRootAndDepth()``. Unity native hash
enumeration is not a stable public ordering contract, so equal-cost choices and
sibling output use the lowest final-proxy vertex index as the canonical tie
break. No Blender data or evaluated frame pose enters this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from ..utils.math3d import (
    normalize_vector_f64,
    orientation_xyzw_f64,
    quaternion_multiply_f64,
    rotate_vector_by_inverse_f64,
)
from .static_data import (
    MC2BaselineStaticSpec,
    MC2ProxyStaticSpec,
    make_mc2_baseline_static_spec,
    make_mc2_proxy_static_spec,
)


MC2_VERTEX_FIXED = 0x01
MC2_VERTEX_MOVE = 0x02
MC2_VERTEX_ZERO_DISTANCE = 0x20
MC2_VERTEX_TRIANGLE = 0x80
MC2_BASELINE_INCLUDE_LINE = 0x01
MC2_ZERO_DISTANCE_EPSILON = 1.0e-8


@dataclass(frozen=True)
class MC2MeshBaselineBuildResult:
    final_proxy: MC2ProxyStaticSpec
    baseline: MC2BaselineStaticSpec
    tie_break: str = "lowest_vertex_index"

    def __post_init__(self) -> None:
        if self.final_proxy.setup_type != "mesh_cloth":
            raise ValueError("Mesh baseline result requires a mesh_cloth proxy")
        if self.baseline.proxy_signature != self.final_proxy.proxy_signature:
            raise ValueError("baseline must reference the finalized proxy signature")
        if self.tie_break != "lowest_vertex_index":
            raise ValueError("unsupported Mesh baseline tie break")


def _is_fixed(attribute: int) -> bool:
    return bool(attribute & MC2_VERTEX_FIXED)


def _is_move(attribute: int) -> bool:
    return bool(attribute & MC2_VERTEX_MOVE)


def _is_invalid(attribute: int) -> bool:
    return not bool(attribute & (MC2_VERTEX_FIXED | MC2_VERTEX_MOVE))


def _distance(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.linalg.norm(first - second))


def _angle(first: np.ndarray, second: np.ndarray) -> float | None:
    first_length = float(np.linalg.norm(first))
    second_length = float(np.linalg.norm(second))
    denominator = first_length * second_length
    if denominator <= 0.0:
        return None
    cosine = float(np.dot(first, second)) / denominator
    return math.acos(max(-1.0, min(1.0, cosine)))


def _adjacency(proxy: MC2ProxyStaticSpec) -> tuple[tuple[int, ...], ...]:
    values = [set() for _ in range(proxy.vertex_count)]
    for first, second in proxy.edges:
        values[first].add(second)
        values[second].add(first)
    return tuple(tuple(sorted(neighbors)) for neighbors in values)


def _build_parent_and_children(
    positions: np.ndarray,
    attributes: tuple[int, ...],
    adjacency: tuple[tuple[int, ...], ...],
) -> tuple[tuple[int, ...], tuple[tuple[int, ...], ...]]:
    count = len(attributes)
    parents = [-1] * count
    children = [[] for _ in range(count)]
    fixed = [index for index, attribute in enumerate(attributes) if _is_fixed(attribute)]
    if not fixed:
        return tuple(parents), tuple(tuple() for _ in range(count))

    marks = [0] * count
    frontier = [(index, 0.0) for index in fixed]
    while frontier:
        for vertex, _frontier_distance in frontier:
            attribute = attributes[vertex]
            if not _is_move(attribute):
                continue

            best_parent = -1
            best_cost = -1.0
            for target in adjacency[vertex]:
                if marks[target] == 0:
                    continue
                if not _is_move(attributes[target]):
                    cost = _distance(positions[vertex], positions[target])
                else:
                    grandparent = parents[target]
                    if grandparent < 0:
                        continue
                    cost = _angle(
                        positions[target] - positions[vertex],
                        positions[grandparent] - positions[target],
                    )
                    if cost is None:
                        continue
                if best_parent < 0 or cost < best_cost:
                    best_parent = target
                    best_cost = cost

            if best_parent >= 0:
                parents[vertex] = best_parent
                marks[vertex] = 1

        for vertex, _frontier_distance in frontier:
            marks[vertex] = 2
            parent = parents[vertex]
            if parent >= 0:
                children[parent].append(vertex)

        candidate_distances: dict[int, float] = {}
        for vertex, _frontier_distance in frontier:
            for target in adjacency[vertex]:
                if _is_invalid(attributes[target]) or marks[target] != 0:
                    continue
                distance = _distance(positions[vertex], positions[target])
                previous = candidate_distances.get(target)
                if previous is None or distance < previous:
                    candidate_distances[target] = distance
        frontier = sorted(
            candidate_distances.items(),
            key=lambda item: (item[1], item[0]),
        )

    return (
        tuple(parents),
        tuple(tuple(sorted(vertex_children)) for vertex_children in children),
    )


def _dense_ranges(records: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, int], ...]:
    ranges = []
    cursor = 0
    for record in records:
        ranges.append((cursor, len(record)))
        cursor += len(record)
    return tuple(ranges)


def _flatten(records: tuple[tuple[int, ...], ...]) -> tuple[int, ...]:
    return tuple(value for record in records for value in record)


def _build_baselines(
    attributes: tuple[int, ...],
    children: tuple[tuple[int, ...], ...],
) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...], tuple[int, ...]]:
    flags = []
    ranges = []
    data = []
    for root, attribute in enumerate(attributes):
        if not _is_fixed(attribute) or not children[root]:
            continue
        start = len(data)
        line_flag = 0
        stack = [root]
        while stack:
            vertex = stack.pop()
            data.append(vertex)
            if not attributes[vertex] & MC2_VERTEX_TRIANGLE:
                line_flag |= MC2_BASELINE_INCLUDE_LINE
            stack.extend(reversed(children[vertex]))
        flags.append(line_flag)
        ranges.append((start, len(data) - start))
    return tuple(flags), tuple(ranges), tuple(data)


def _normalize(vector: np.ndarray, label: str) -> np.ndarray:
    return normalize_vector_f64(vector, name=label)


def _orientation_xyzw(normal, tangent, vertex: int) -> np.ndarray:
    return orientation_xyzw_f64(
        normal,
        tangent,
        tangent_name=f"local_tangents[{vertex}]",
        normal_name=f"local_normals[{vertex}]",
        right_name=f"normal/tangent basis[{vertex}]",
        quaternion_name="orientation quaternion",
    )


def _build_local_pose(
    proxy: MC2ProxyStaticSpec,
    parents: tuple[int, ...],
    baseline_data: tuple[int, ...],
) -> tuple[tuple[tuple[float, float, float], ...], tuple[tuple[float, float, float, float], ...], tuple[int, ...]]:
    count = proxy.vertex_count
    positions = np.asarray(proxy.local_positions, dtype=np.float64)
    local_positions = np.zeros((count, 3), dtype=np.float64)
    local_rotations = np.zeros((count, 4), dtype=np.float64)
    attributes = list(proxy.vertex_attributes)
    orientations: dict[int, np.ndarray] = {}

    for vertex in baseline_data:
        parent = parents[vertex]
        if parent < 0:
            local_rotations[vertex] = (0.0, 0.0, 0.0, 1.0)
            continue
        parent_rotation = orientations.get(parent)
        if parent_rotation is None:
            parent_rotation = _orientation_xyzw(
                proxy.local_normals[parent],
                proxy.local_tangents[parent],
                parent,
            )
            orientations[parent] = parent_rotation
        vertex_rotation = orientations.get(vertex)
        if vertex_rotation is None:
            vertex_rotation = _orientation_xyzw(
                proxy.local_normals[vertex],
                proxy.local_tangents[vertex],
                vertex,
            )
            orientations[vertex] = vertex_rotation
        local_position = rotate_vector_by_inverse_f64(
            parent_rotation,
            positions[vertex] - positions[parent],
        )
        inverse_parent = np.asarray(
            (-parent_rotation[0], -parent_rotation[1], -parent_rotation[2], parent_rotation[3]),
            dtype=np.float64,
        )
        local_rotation = _normalize(
            quaternion_multiply_f64(inverse_parent, vertex_rotation),
            f"vertex_local_rotations[{vertex}]",
        )
        local_positions[vertex] = local_position
        local_rotations[vertex] = local_rotation
        if float(np.linalg.norm(local_position)) < MC2_ZERO_DISTANCE_EPSILON:
            attributes[vertex] |= MC2_VERTEX_ZERO_DISTANCE

    return (
        tuple(tuple(float(value) for value in row) for row in local_positions),
        tuple(tuple(float(value) for value in row) for row in local_rotations),
        tuple(attributes),
    )


def _root_and_depth(
    positions: np.ndarray,
    attributes: tuple[int, ...],
    parents: tuple[int, ...],
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    roots = [-1] * len(attributes)
    lengths = [0.0] * len(attributes)
    max_length = 0.0
    for vertex, attribute in enumerate(attributes):
        if not _is_move(attribute):
            continue
        current = vertex
        parent = parents[current]
        while parent >= 0:
            lengths[vertex] += _distance(positions[current], positions[parent])
            roots[vertex] = parent
            if not _is_move(attributes[parent]):
                break
            current = parent
            parent = parents[current]
        max_length = max(max_length, lengths[vertex])
    if max_length <= MC2_ZERO_DISTANCE_EPSILON:
        return tuple(roots), tuple(0.0 for _ in attributes)
    return (
        tuple(roots),
        tuple(max(0.0, min(1.0, length / max_length)) for length in lengths),
    )


def _replace_proxy_attributes(
    proxy: MC2ProxyStaticSpec,
    attributes: tuple[int, ...],
) -> MC2ProxyStaticSpec:
    if attributes == proxy.vertex_attributes:
        return proxy
    return make_mc2_proxy_static_spec(
        task_id=proxy.task_id,
        setup_type=proxy.setup_type,
        vertex_identities=proxy.vertex_identities,
        local_positions=proxy.local_positions,
        local_normals=proxy.local_normals,
        local_tangents=proxy.local_tangents,
        uvs=proxy.uvs,
        vertex_attributes=attributes,
        edges=proxy.edges,
        triangles=proxy.triangles,
    )


def build_mc2_mesh_baseline(proxy: MC2ProxyStaticSpec) -> MC2MeshBaselineBuildResult:
    if not isinstance(proxy, MC2ProxyStaticSpec):
        raise TypeError("proxy must be MC2ProxyStaticSpec")
    if proxy.setup_type != "mesh_cloth":
        raise ValueError("Mesh baseline builder only accepts mesh_cloth")

    positions = np.asarray(proxy.local_positions, dtype=np.float64)
    adjacency = _adjacency(proxy)
    parents, children = _build_parent_and_children(
        positions,
        proxy.vertex_attributes,
        adjacency,
    )
    child_ranges = _dense_ranges(children)
    child_data = _flatten(children)
    baseline_flags, baseline_ranges, baseline_data = _build_baselines(
        proxy.vertex_attributes,
        children,
    )
    local_positions, local_rotations, attributes = _build_local_pose(
        proxy,
        parents,
        baseline_data,
    )
    final_proxy = _replace_proxy_attributes(proxy, attributes)
    roots, depths = _root_and_depth(positions, attributes, parents)
    baseline = make_mc2_baseline_static_spec(
        proxy_signature=final_proxy.proxy_signature,
        vertex_count=final_proxy.vertex_count,
        parent_indices=parents,
        child_ranges=child_ranges,
        child_data=child_data,
        baseline_flags=baseline_flags,
        baseline_ranges=baseline_ranges,
        baseline_data=baseline_data,
        root_indices=roots,
        depths=depths,
        vertex_local_positions=local_positions,
        vertex_local_rotations=local_rotations,
    )
    return MC2MeshBaselineBuildResult(final_proxy=final_proxy, baseline=baseline)


__all__ = [
    "MC2_BASELINE_INCLUDE_LINE",
    "MC2_VERTEX_FIXED",
    "MC2_VERTEX_MOVE",
    "MC2_VERTEX_TRIANGLE",
    "MC2_VERTEX_ZERO_DISTANCE",
    "MC2MeshBaselineBuildResult",
    "build_mc2_mesh_baseline",
]
