"""MeshCloth final-proxy extraction and source-aligned finalization.

The public product contract keeps Blender vertex identity unchanged: no
reduction, no merge, no split, no remap. This module only converts that fixed
authoring mesh into the finalized MC2 proxy fields consumed by the existing N0
baseline builder.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np

from ...mesh_baseline import MC2_VERTEX_FIXED
from ...mesh_baseline import MC2_VERTEX_MOVE
from ...mesh_baseline import MC2_VERTEX_TRIANGLE
from ...static_data import MC2ProxyStaticSpec
from ...static_data import MC2ProxyFinalizerStaticSpec
from ...static_data import make_mc2_proxy_finalizer_static_spec
from ...static_data import make_mc2_proxy_static_spec


SAME_SURFACE_ANGLE_DEGREES = 80.0
UV_SEAM_TOLERANCE = 1.0e-6


@dataclass(frozen=True)
class MC2MeshFinalProxyBuildResult:
    proxy: MC2ProxyStaticSpec
    lines: tuple[tuple[int, int], ...]
    finalizer: MC2ProxyFinalizerStaticSpec

    @property
    def vertex_to_vertex_ranges(self):
        return self.finalizer.vertex_to_vertex_ranges

    @property
    def vertex_to_vertex_data(self):
        return self.finalizer.vertex_to_vertex_data

    @property
    def vertex_to_triangle_records(self):
        return self.finalizer.vertex_to_triangle_records

    @property
    def vertex_bind_pose_positions(self):
        return self.finalizer.vertex_bind_pose_positions

    @property
    def vertex_bind_pose_rotations(self):
        return self.finalizer.vertex_bind_pose_rotations


def _array(values, *, width: int, name: str) -> np.ndarray:
    array = np.asarray(tuple(values), dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != width:
        raise ValueError(f"{name} must have shape [N,{width}]")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} cannot contain NaN/Inf")
    return array


def _int_records(values, *, width: int, name: str) -> tuple[tuple[int, ...], ...]:
    records = []
    for index, value in enumerate(values or ()):
        record = tuple(int(item) for item in value)
        if len(record) != width:
            raise ValueError(f"{name}[{index}] must contain {width} indices")
        records.append(record)
    return tuple(records)


def _canonical_edge(first: int, second: int) -> tuple[int, int]:
    if first == second:
        raise ValueError("MC2 proxy edge cannot be a self edge")
    return (first, second) if first < second else (second, first)


def _normalize(vector: np.ndarray, *, name: str, zero_ok: bool = False) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length <= 1.0e-12 or not math.isfinite(length):
        if zero_ok:
            return np.zeros(3, dtype=np.float64)
        raise ValueError(f"{name} must be non-zero")
    return vector / length


def _triangle_normal(positions: np.ndarray, triangle: tuple[int, int, int]) -> np.ndarray:
    first, second, third = triangle
    return _normalize(
        np.cross(positions[second] - positions[first], positions[third] - positions[first]),
        name="triangle normal",
    )


def _triangle_tangent(
    positions: np.ndarray,
    uvs: np.ndarray,
    triangle: tuple[int, int, int],
) -> np.ndarray:
    first, second, third = triangle
    dist_ba = positions[second] - positions[first]
    dist_ca = positions[third] - positions[first]
    uv_ba = uvs[second] - uvs[first]
    uv_ca = uvs[third] - uvs[first]
    area = float(uv_ba[0] * uv_ca[1] - uv_ba[1] * uv_ca[0])
    if area == 0.0:
        area = 1.0
    tangent = -(
        np.asarray(
            (
                dist_ba[0] * uv_ca[1] + dist_ca[0] * -uv_ba[1],
                dist_ba[1] * uv_ca[1] + dist_ca[1] * -uv_ba[1],
                dist_ba[2] * uv_ca[1] + dist_ca[2] * -uv_ba[1],
            ),
            dtype=np.float64,
        )
        / area
    )
    return _normalize(tangent, name="triangle tangent", zero_ok=True)


def _flip_triangle(triangle: tuple[int, int, int]) -> tuple[int, int, int]:
    return (triangle[0], triangle[2], triangle[1])


def _remaining_vertex(triangle: tuple[int, int, int], edge: tuple[int, int]) -> int:
    for value in triangle:
        if value != edge[0] and value != edge[1]:
            return value
    raise ValueError("triangle does not contain a remaining vertex for edge")


def _angle(first: np.ndarray, second: np.ndarray) -> float:
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    if denominator <= 1.0e-12:
        raise ValueError("triangle angle vector must be non-zero")
    cosine = float(np.dot(first, second)) / denominator
    return math.acos(max(-1.0, min(1.0, cosine)))


def _two_triangle_angle(
    positions: np.ndarray,
    first: tuple[int, int, int],
    second: tuple[int, int, int],
    edge: tuple[int, int],
) -> float:
    first_rest = _remaining_vertex(first, edge)
    second_rest = _remaining_vertex(second, edge)
    va = positions[edge[1]] - positions[edge[0]]
    vb = positions[first_rest] - positions[edge[0]]
    vc = positions[second_rest] - positions[edge[0]]
    return math.degrees(_angle(np.cross(va, vb), np.cross(vc, va)))


def _two_triangle_open(
    positions: np.ndarray,
    second: tuple[int, int, int],
    edge: tuple[int, int],
    first_normal: np.ndarray,
) -> bool:
    second_rest = _remaining_vertex(second, edge)
    direction = _normalize(
        positions[second_rest] - positions[edge[0]],
        name="triangle open direction",
    )
    return float(np.dot(first_normal, direction)) <= 0.0


def _triangle_edges(triangle: tuple[int, int, int]) -> tuple[tuple[int, int], ...]:
    return (
        _canonical_edge(triangle[0], triangle[1]),
        _canonical_edge(triangle[1], triangle[2]),
        _canonical_edge(triangle[2], triangle[0]),
    )


def _edge_to_triangles(triangles: tuple[tuple[int, int, int], ...]) -> dict[tuple[int, int], list[int]]:
    result: dict[tuple[int, int], list[int]] = {}
    for index, triangle in enumerate(triangles):
        for edge in _triangle_edges(triangle):
            values = result.setdefault(edge, [])
            if index not in values:
                values.append(index)
    return result


def _optimize_triangle_direction(
    positions: np.ndarray,
    triangles: tuple[tuple[int, int, int], ...],
) -> tuple[tuple[tuple[int, int, int], ...], list[np.ndarray]]:
    if not triangles:
        return triangles, []
    final_triangles = [tuple(triangle) for triangle in triangles]
    normals = [_triangle_normal(positions, triangle) for triangle in final_triangles]
    edge_to_triangles = _edge_to_triangles(tuple(final_triangles))
    used: set[int] = set()
    start = 0
    while start < len(final_triangles):
        if start in used:
            start += 1
            continue
        used.add(start)
        queue = [start]
        layer = []
        open_count = 0
        close_count = 0
        while queue:
            tindex = queue.pop(0)
            normal = normals[tindex]
            triangle = final_triangles[tindex]
            layer.append(tindex)
            for edge in _triangle_edges(triangle):
                for other_index in edge_to_triangles.get(edge, ()):
                    if other_index in used:
                        continue
                    other = final_triangles[other_index]
                    other_normal = normals[other_index]
                    if (
                        _two_triangle_angle(positions, triangle, other, edge)
                        > SAME_SURFACE_ANGLE_DEGREES
                    ):
                        continue
                    if float(np.dot(normal, other_normal)) < 0.0:
                        other = _flip_triangle(other)
                        final_triangles[other_index] = other
                        other_normal = -other_normal
                        normals[other_index] = other_normal
                    if _two_triangle_open(positions, other, edge, normal):
                        open_count += 1
                    else:
                        close_count += 1
                    used.add(other_index)
                    queue.append(other_index)
        if close_count > open_count:
            for tindex in layer:
                final_triangles[tindex] = _flip_triangle(final_triangles[tindex])
                normals[tindex] = -normals[tindex]
    return tuple(final_triangles), normals


def _edge_union(
    triangles: tuple[tuple[int, int, int], ...],
    lines: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    edges = set()
    for triangle in triangles:
        edges.update(_triangle_edges(triangle))
    for first, second in lines:
        edges.add(_canonical_edge(first, second))
    return tuple(sorted(edges))


def _vertex_to_vertex(
    vertex_count: int,
    triangles: tuple[tuple[int, int, int], ...],
    lines: tuple[tuple[int, int], ...],
) -> tuple[tuple[tuple[int, int], ...], tuple[int, ...]]:
    adjacency = [[] for _ in range(vertex_count)]

    def unique_add(vertex: int, neighbor: int) -> None:
        values = adjacency[vertex]
        if neighbor not in values:
            values.append(neighbor)

    for first, second, third in triangles:
        unique_add(first, second)
        unique_add(first, third)
        unique_add(second, first)
        unique_add(second, third)
        unique_add(third, first)
        unique_add(third, second)
    for first, second in lines:
        unique_add(first, second)
        unique_add(second, first)
    ranges = []
    data = []
    for values in adjacency:
        start = len(data)
        data.extend(reversed(values))
        ranges.append((start, len(data) - start))
    return tuple(ranges), tuple(data)


def _create_vertex_to_triangles(
    vertex_count: int,
    triangles: tuple[tuple[int, int, int], ...],
) -> list[list[int]]:
    records = [[] for _ in range(vertex_count)]
    for triangle_index, triangle in enumerate(triangles):
        for vertex in triangle:
            if len(records[vertex]) < 7:
                records[vertex].append(triangle_index)
    return records


def _organize_vertex_to_triangles(
    attributes: list[int],
    triangle_normals: list[np.ndarray],
    triangle_tangents: list[np.ndarray],
    vertex_to_triangles: list[list[int]],
) -> tuple[tuple[tuple[int, int], ...], ...]:
    result = []
    for vertex, triangle_indices in enumerate(vertex_to_triangles):
        if not triangle_indices:
            result.append(tuple())
            continue
        attributes[vertex] |= MC2_VERTEX_TRIANGLE
        final_normal = sum((triangle_normals[index] for index in triangle_indices), start=np.zeros(3))
        final_tangent = sum((triangle_tangents[index] for index in triangle_indices), start=np.zeros(3))
        if float(np.linalg.norm(final_normal)) < 0.5:
            best_distance = -1.0
            best_normal = np.zeros(3)
            for base_index in triangle_indices:
                candidate = np.zeros(3)
                base_normal = triangle_normals[base_index]
                for other_index in triangle_indices:
                    if other_index == base_index:
                        continue
                    other = triangle_normals[other_index]
                    candidate += other if float(np.dot(base_normal, other)) >= 0.0 else -other
                distance = float(np.dot(candidate, candidate))
                if distance > best_distance:
                    best_distance = distance
                    best_normal = base_normal
            final_normal = best_normal
        else:
            final_normal = _normalize(final_normal, name="final vertex normal")
        if float(np.linalg.norm(final_tangent)) < 0.5:
            best_distance = -1.0
            best_tangent = np.zeros(3)
            for base_index in triangle_indices:
                candidate = np.zeros(3)
                base_tangent = triangle_tangents[base_index]
                for other_index in triangle_indices:
                    if other_index == base_index:
                        continue
                    other = triangle_tangents[other_index]
                    candidate += other if float(np.dot(base_tangent, other)) >= 0.0 else -other
                distance = float(np.dot(candidate, candidate))
                if distance > best_distance:
                    best_distance = distance
                    best_tangent = base_tangent
            final_tangent = best_tangent
        else:
            final_tangent = _normalize(final_tangent, name="final vertex tangent")
        records = []
        for triangle_index in triangle_indices:
            flip = 0
            if float(np.dot(final_normal, triangle_normals[triangle_index])) < 0.0:
                flip |= 0x1
            if float(np.dot(final_tangent, triangle_tangents[triangle_index])) < 0.0:
                flip |= 0x2
            records.append((flip, triangle_index))
        result.append(tuple(records))
    return tuple(result)


def _apply_vertex_triangle_normals(
    local_normals: np.ndarray,
    local_tangents: np.ndarray,
    triangle_normals: list[np.ndarray],
    triangle_tangents: list[np.ndarray],
    vertex_to_triangle_records: tuple[tuple[tuple[int, int], ...], ...],
) -> tuple[np.ndarray, np.ndarray]:
    normals = np.array(local_normals, dtype=np.float64, copy=True)
    tangents = np.array(local_tangents, dtype=np.float64, copy=True)
    for vertex, records in enumerate(vertex_to_triangle_records):
        if not records:
            continue
        normal = np.zeros(3)
        tangent = np.zeros(3)
        for flip, triangle_index in records:
            normal += triangle_normals[triangle_index] * (1.0 if not flip & 0x1 else -1.0)
            tangent += triangle_tangents[triangle_index] * (1.0 if not flip & 0x2 else -1.0)
        normal = _normalize(normal, name=f"local_normals[{vertex}]")
        binormal = _normalize(np.cross(normal, tangent), name=f"local_tangents[{vertex}]")
        normals[vertex] = normal
        tangents[vertex] = binormal
    return normals, tangents


def _matrix_to_quaternion_xyzw(matrix: np.ndarray) -> np.ndarray:
    m00, m01, m02 = (float(value) for value in matrix[0])
    m10, m11, m12 = (float(value) for value in matrix[1])
    m20, m21, m22 = (float(value) for value in matrix[2])
    trace = m00 + m11 + m22
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        quat = np.asarray(
            ((m21 - m12) / scale, (m02 - m20) / scale, (m10 - m01) / scale, 0.25 * scale),
            dtype=np.float64,
        )
    elif m00 > m11 and m00 > m22:
        scale = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        quat = np.asarray(
            (0.25 * scale, (m01 + m10) / scale, (m02 + m20) / scale, (m21 - m12) / scale),
            dtype=np.float64,
        )
    elif m11 > m22:
        scale = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        quat = np.asarray(
            ((m01 + m10) / scale, 0.25 * scale, (m12 + m21) / scale, (m02 - m20) / scale),
            dtype=np.float64,
        )
    else:
        scale = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        quat = np.asarray(
            ((m02 + m20) / scale, (m12 + m21) / scale, 0.25 * scale, (m10 - m01) / scale),
            dtype=np.float64,
        )
    return _normalize(quat, name="bind pose quaternion")


def _orientation_xyzw(normal: np.ndarray, tangent: np.ndarray) -> np.ndarray:
    forward = _normalize(np.asarray(tangent, dtype=np.float64), name="orientation tangent")
    up = _normalize(np.asarray(normal, dtype=np.float64), name="orientation normal")
    right = _normalize(np.cross(up, forward), name="orientation right")
    corrected_up = np.cross(forward, right)
    return _matrix_to_quaternion_xyzw(np.column_stack((right, corrected_up, forward)))


def mc2_world_rotation_xyzw(normal, tangent) -> tuple[float, float, float, float]:
    """MC2 ``MathUtility.ToRotation(normal, tangent)`` in xyzw layout."""
    value = _orientation_xyzw(
        np.asarray(normal, dtype=np.float64),
        np.asarray(tangent, dtype=np.float64),
    )
    return tuple(float(component) for component in value)


def _quaternion_inverse_xyzw(quaternion: np.ndarray) -> np.ndarray:
    return np.asarray(
        (-quaternion[0], -quaternion[1], -quaternion[2], quaternion[3]),
        dtype=np.float64,
    )


def _bind_pose(
    local_positions: np.ndarray,
    local_normals: np.ndarray,
    local_tangents: np.ndarray,
) -> tuple[tuple[tuple[float, float, float], ...], tuple[tuple[float, float, float, float], ...]]:
    positions = tuple(tuple(float(value) for value in -row) for row in local_positions)
    rotations = []
    for normal, tangent in zip(local_normals, local_tangents):
        rotations.append(tuple(float(value) for value in _quaternion_inverse_xyzw(_orientation_xyzw(normal, tangent))))
    return positions, tuple(rotations)


def _tuple_vectors(values: np.ndarray) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(component) for component in row) for row in values)


def _validate_indices(vertex_count: int, records: Iterable[tuple[int, ...]], name: str) -> None:
    for record_index, record in enumerate(records):
        for value in record:
            if not 0 <= value < vertex_count:
                raise ValueError(f"{name}[{record_index}] index {value} is out of range")


def build_mc2_final_proxy(
    *,
    task_id: str,
    setup_type: str,
    vertex_identities,
    local_positions,
    local_normals,
    local_tangents,
    uvs,
    vertex_attributes,
    lines=(),
    triangles=(),
) -> MC2MeshFinalProxyBuildResult:
    identities = tuple(str(value) for value in vertex_identities)
    vertex_count = len(identities)
    positions = _array(local_positions, width=3, name="local_positions")
    normals = _array(local_normals, width=3, name="local_normals")
    tangents = _array(local_tangents, width=3, name="local_tangents")
    uv_array = _array(uvs, width=2, name="uvs")
    if not (len(positions) == len(normals) == len(tangents) == len(uv_array) == vertex_count):
        raise ValueError("final proxy per-vertex arrays must share vertex_count")
    attributes = [int(value) for value in vertex_attributes]
    if len(attributes) != vertex_count:
        raise ValueError("vertex_attributes length must match vertex_count")
    line_records = _int_records(lines, width=2, name="lines")
    triangle_records = _int_records(triangles, width=3, name="triangles")
    _validate_indices(vertex_count, line_records, "lines")
    _validate_indices(vertex_count, triangle_records, "triangles")

    final_triangles, triangle_normals = _optimize_triangle_direction(positions, triangle_records)
    edges = _edge_union(final_triangles, line_records)
    vertex_to_vertex_ranges, vertex_to_vertex_data = _vertex_to_vertex(
        vertex_count,
        final_triangles,
        line_records,
    )
    if final_triangles:
        triangle_tangents = [
            _triangle_tangent(positions, uv_array, triangle)
            for triangle in final_triangles
        ]
        raw_vertex_to_triangles = _create_vertex_to_triangles(vertex_count, final_triangles)
        vertex_to_triangle_records = _organize_vertex_to_triangles(
            attributes,
            triangle_normals,
            triangle_tangents,
            raw_vertex_to_triangles,
        )
        normals, tangents = _apply_vertex_triangle_normals(
            normals,
            tangents,
            triangle_normals,
            triangle_tangents,
            vertex_to_triangle_records,
        )
    else:
        vertex_to_triangle_records = tuple(tuple() for _ in range(vertex_count))

    bind_positions, bind_rotations = _bind_pose(positions, normals, tangents)
    proxy = make_mc2_proxy_static_spec(
        task_id=task_id,
        setup_type=setup_type,
        vertex_identities=identities,
        local_positions=_tuple_vectors(positions),
        local_normals=_tuple_vectors(normals),
        local_tangents=_tuple_vectors(tangents),
        uvs=_tuple_vectors(uv_array),
        vertex_attributes=tuple(attributes),
        edges=edges,
        triangles=final_triangles,
    )
    finalizer = make_mc2_proxy_finalizer_static_spec(
        proxy=proxy,
        vertex_to_vertex_ranges=vertex_to_vertex_ranges,
        vertex_to_vertex_data=vertex_to_vertex_data,
        vertex_to_triangle_records=vertex_to_triangle_records,
        vertex_bind_pose_positions=bind_positions,
        vertex_bind_pose_rotations=bind_rotations,
    )
    return MC2MeshFinalProxyBuildResult(
        proxy=proxy,
        lines=tuple(_canonical_edge(first, second) for first, second in line_records),
        finalizer=finalizer,
    )


def build_mc2_mesh_final_proxy(
    *,
    task_id: str,
    vertex_identities,
    local_positions,
    local_normals,
    local_tangents,
    uvs,
    vertex_attributes,
    lines=(),
    triangles=(),
) -> MC2MeshFinalProxyBuildResult:
    return build_mc2_final_proxy(
        task_id=task_id,
        setup_type="mesh_cloth",
        vertex_identities=vertex_identities,
        local_positions=local_positions,
        local_normals=local_normals,
        local_tangents=local_tangents,
        uvs=uvs,
        vertex_attributes=vertex_attributes,
        lines=lines,
        triangles=triangles,
    )


def _fallback_tangent(normal: np.ndarray) -> np.ndarray:
    up = np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
    right = np.asarray((1.0, 0.0, 0.0), dtype=np.float64)
    if float(np.dot(normal, up)) < 0.9:
        return _normalize(np.cross(normal, up), name="generated tangent")
    return _normalize(np.cross(normal, right), name="generated tangent")


def _vertex_group_weights(obj, group_name: str, vertex_count: int) -> tuple[float, ...]:
    group = obj.vertex_groups.get(group_name)
    if group is None:
        raise ValueError(f"Pin vertex group does not exist: {group_name}")
    weights = [0.0] * vertex_count
    for vertex in obj.data.vertices:
        for assignment in vertex.groups:
            if assignment.group == group.index:
                weights[vertex.index] = float(assignment.weight)
                break
    return tuple(weights)


def _mesh_uvs(mesh, triangles: tuple[tuple[int, int, int], ...], *, uv_layer_name: str | None) -> tuple[tuple[float, float], ...]:
    vertex_count = len(mesh.vertices)
    if not triangles:
        return tuple((0.0, 0.0) for _ in range(vertex_count))
    uv_layer = None
    if uv_layer_name:
        uv_layer = mesh.uv_layers.get(uv_layer_name)
    else:
        uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise ValueError("MeshCloth triangle proxy requires a UV layer")
    values: list[tuple[float, float] | None] = [None] * vertex_count
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = int(mesh.loops[loop_index].vertex_index)
            uv = tuple(float(value) for value in uv_layer.data[loop_index].uv)
            current = values[vertex_index]
            if current is None:
                values[vertex_index] = uv
            elif (
                abs(current[0] - uv[0]) > UV_SEAM_TOLERANCE
                or abs(current[1] - uv[1]) > UV_SEAM_TOLERANCE
            ):
                raise ValueError(
                    f"Blender vertex {vertex_index} has multiple loop UVs; split the proxy vertex"
                )
    return tuple(value if value is not None else (0.0, 0.0) for value in values)


def _mesh_triangles(mesh) -> tuple[tuple[int, int, int], ...]:
    mesh.calc_loop_triangles()
    return tuple(tuple(int(value) for value in triangle.vertices) for triangle in mesh.loop_triangles)


def build_blender_mesh_final_proxy(
    obj,
    *,
    task_id: str,
    pin_enabled: bool = False,
    pin_vertex_group: str = "",
    uv_layer_name: str | None = None,
    expected_mesh_topology_signature: str | None = None,
) -> MC2MeshFinalProxyBuildResult:
    from .base_pose import mesh_topology_signature

    if obj is None or getattr(obj, "type", None) != "MESH" or obj.data is None:
        raise ValueError("MeshCloth final proxy target must be a Mesh object")
    if expected_mesh_topology_signature:
        actual = mesh_topology_signature(obj)
        if actual != expected_mesh_topology_signature:
            raise ValueError("Mesh topology signature does not match expected token")
    mesh = obj.data
    mesh.update()
    vertex_count = len(mesh.vertices)
    triangles = _mesh_triangles(mesh)
    uvs = _mesh_uvs(mesh, triangles, uv_layer_name=uv_layer_name)
    positions = tuple(tuple(float(component) for component in vertex.co) for vertex in mesh.vertices)
    normals = []
    tangents = []
    for vertex in mesh.vertices:
        normal = _normalize(
            np.asarray(tuple(float(component) for component in vertex.normal), dtype=np.float64),
            name=f"mesh.vertices[{vertex.index}].normal",
        )
        normals.append(tuple(float(value) for value in normal))
        tangents.append(tuple(float(value) for value in _fallback_tangent(normal)))
    if not pin_enabled:
        attributes = tuple(MC2_VERTEX_MOVE for _ in range(vertex_count))
    elif not pin_vertex_group:
        attributes = tuple(MC2_VERTEX_FIXED for _ in range(vertex_count))
    else:
        weights = _vertex_group_weights(obj, pin_vertex_group, vertex_count)
        attributes = tuple(
            MC2_VERTEX_FIXED if weight > 0.0 else MC2_VERTEX_MOVE
            for weight in weights
        )
    lines = tuple(tuple(int(value) for value in edge.vertices) for edge in mesh.edges)
    return build_mc2_mesh_final_proxy(
        task_id=task_id,
        vertex_identities=tuple(f"mesh:v{index}" for index in range(vertex_count)),
        local_positions=positions,
        local_normals=tuple(normals),
        local_tangents=tuple(tangents),
        uvs=uvs,
        vertex_attributes=attributes,
        lines=lines,
        triangles=triangles,
    )


__all__ = [
    "MC2MeshFinalProxyBuildResult",
    "SAME_SURFACE_ANGLE_DEGREES",
    "UV_SEAM_TOLERANCE",
    "build_blender_mesh_final_proxy",
    "build_mc2_final_proxy",
    "build_mc2_mesh_final_proxy",
    "mc2_world_rotation_xyzw",
]
