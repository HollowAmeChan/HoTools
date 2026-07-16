"""MeshCloth final-proxy extraction and source-aligned finalization.

The public product contract keeps Blender vertex identity unchanged: no
reduction, no merge, no split, no remap. This module only converts that fixed
authoring mesh into the finalized MC2 proxy fields consumed by the existing N0
baseline builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from ....utils.math3d import (
    normalize_vector_f64,
    orientation_xyzw_f64,
)
from ...mesh_baseline import MC2_VERTEX_FIXED
from ...mesh_baseline import MC2_VERTEX_MOVE
from ...static_data import MC2ProxyStaticSpec
from ...static_data import MC2ProxyFinalizerStaticSpec
from ...static_data import make_mc2_proxy_finalizer_static_spec
from ...static_data import make_mc2_proxy_static_spec


UV_SEAM_TOLERANCE = 1.0e-6


@dataclass(frozen=True)
class MC2MeshFinalProxyBuildResult:
    proxy: MC2ProxyStaticSpec
    lines: tuple[tuple[int, int], ...]
    finalizer: (
        MC2ProxyFinalizerStaticSpec
        | MC2MeshFinalizerNativeData
        | MC2MeshFinalizerNativeMetadata
    )

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

    @property
    def every_vertex_has_triangle(self):
        value = getattr(self.finalizer, "every_vertex_has_triangle", None)
        if value is not None:
            return bool(value)
        return all(self.finalizer.vertex_to_triangle_records)

    def compact_native_finalizer(self):
        finalizer = self.finalizer
        if not isinstance(finalizer, MC2MeshFinalizerNativeData):
            return self
        return MC2MeshFinalProxyBuildResult(
            proxy=self.proxy,
            lines=self.lines,
            finalizer=finalizer.metadata(),
        )


@dataclass(frozen=True)
class MC2MeshFinalizerNativeMetadata:
    proxy_signature: str
    vertex_count: int
    neighbor_count: int
    triangle_record_count: int
    every_vertex_has_triangle: bool
    native_owned: bool = True


@dataclass(frozen=True)
class MC2MeshFinalizerNativeData:
    proxy_signature: str
    vertex_count: int
    vertex_to_vertex_ranges: np.ndarray
    vertex_to_vertex_data: np.ndarray
    vertex_to_triangle_ranges: np.ndarray
    vertex_to_triangle_data: np.ndarray
    vertex_bind_pose_positions: np.ndarray
    vertex_bind_pose_rotations: np.ndarray

    @property
    def every_vertex_has_triangle(self) -> bool:
        return bool(np.all(self.vertex_to_triangle_ranges[:, 1] > 0))

    def metadata(self) -> MC2MeshFinalizerNativeMetadata:
        return MC2MeshFinalizerNativeMetadata(
            proxy_signature=self.proxy_signature,
            vertex_count=self.vertex_count,
            neighbor_count=len(self.vertex_to_vertex_data),
            triangle_record_count=len(self.vertex_to_triangle_data),
            every_vertex_has_triangle=self.every_vertex_has_triangle,
        )


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


def _optimize_triangle_direction(
    positions: np.ndarray,
    triangles: tuple[tuple[int, int, int], ...],
) -> tuple[tuple[tuple[int, int, int], ...], list[np.ndarray]]:
    if not triangles:
        return triangles, []
    final_triangles = np.ascontiguousarray(triangles, dtype=np.int32)
    normals = np.empty((len(triangles), 3), dtype=np.float64)
    from ...native import native_module

    native_module().mc2_optimize_triangle_direction_v0(
        np.ascontiguousarray(positions, dtype=np.float64),
        final_triangles,
        normals,
    )
    return (
        tuple(tuple(int(value) for value in triangle) for triangle in final_triangles),
        [normals[index] for index in range(len(normals))],
    )


def _build_final_proxy_derived(
    positions: np.ndarray,
    normals: np.ndarray,
    tangents: np.ndarray,
    uvs: np.ndarray,
    attributes: list[int],
    triangles: tuple[tuple[int, int, int], ...],
    triangle_normals: list[np.ndarray],
    lines: tuple[tuple[int, int], ...],
    native_context=None,
):
    if any(not 0 <= value <= 0xFF for value in attributes):
        raise ValueError("vertex_attributes must fit uint8")
    vertex_count = len(positions)
    triangle_count = len(triangles)
    line_count = len(lines)
    normals = np.ascontiguousarray(normals, dtype=np.float64)
    tangents = np.ascontiguousarray(tangents, dtype=np.float64)
    attribute_values = np.ascontiguousarray(attributes, dtype=np.uint8)
    triangle_values = np.ascontiguousarray(triangles, dtype=np.int32).reshape((-1, 3))
    triangle_normal_values = np.ascontiguousarray(
        triangle_normals,
        dtype=np.float64,
    ).reshape((-1, 3))
    line_values = np.ascontiguousarray(lines, dtype=np.int32).reshape((-1, 2))
    out_edges = np.empty((triangle_count * 3 + line_count, 2), dtype=np.int32)
    out_neighbor_ranges = np.empty((vertex_count, 2), dtype=np.int32)
    out_neighbor_data = np.empty(triangle_count * 6 + line_count * 2, dtype=np.int32)
    out_triangle_ranges = np.empty((vertex_count, 2), dtype=np.int32)
    out_triangle_data = np.empty(
        (min(triangle_count * 3, vertex_count * 7), 2),
        dtype=np.int32,
    )
    bind_positions = np.empty((vertex_count, 3), dtype=np.float64)
    bind_rotations = np.empty((vertex_count, 4), dtype=np.float64)
    from ...native import native_module

    counts = native_module().mc2_build_mesh_final_proxy_derived_v0(
        np.ascontiguousarray(positions, dtype=np.float64),
        normals,
        tangents,
        np.ascontiguousarray(uvs, dtype=np.float64),
        attribute_values,
        triangle_values,
        triangle_normal_values,
        line_values,
        out_edges,
        out_neighbor_ranges,
        out_neighbor_data,
        out_triangle_ranges,
        out_triangle_data,
        bind_positions,
        bind_rotations,
    )
    edge_count = int(counts["edge_count"])
    neighbor_count = int(counts["neighbor_count"])
    triangle_record_count = int(counts["triangle_record_count"])
    triangle_data = out_triangle_data[:triangle_record_count]
    if native_context is not None:
        native_context.update_proxy_finalizer_derived(
            positions=positions,
            normals=normals,
            tangents=tangents,
            uvs=uvs,
            attributes=attribute_values,
            edges=out_edges[:edge_count],
            triangles=triangle_values,
            triangle_ranges=out_triangle_ranges,
            triangle_records=triangle_data,
            bind_rotations=bind_rotations,
        )
    if native_context is not None:
        return {
            "normals": normals,
            "tangents": tangents,
            "attributes": tuple(int(value) for value in attribute_values),
            "edges": tuple(
                tuple(int(value) for value in edge)
                for edge in out_edges[:edge_count]
            ),
            "native_finalizer": {
                "vertex_to_vertex_ranges": out_neighbor_ranges,
                "vertex_to_vertex_data": out_neighbor_data[:neighbor_count],
                "vertex_to_triangle_ranges": out_triangle_ranges,
                "vertex_to_triangle_data": triangle_data,
                "bind_positions": bind_positions,
                "bind_rotations": bind_rotations,
            },
        }
    vertex_to_triangle_records = tuple(
        tuple(
            tuple(int(value) for value in record)
            for record in triangle_data[start:start + count]
        )
        for start, count in out_triangle_ranges
    )
    return {
        "normals": normals,
        "tangents": tangents,
        "attributes": tuple(int(value) for value in attribute_values),
        "edges": tuple(
            tuple(int(value) for value in edge)
            for edge in out_edges[:edge_count]
        ),
        "vertex_to_vertex_ranges": tuple(
            tuple(int(value) for value in record)
            for record in out_neighbor_ranges
        ),
        "vertex_to_vertex_data": tuple(
            int(value) for value in out_neighbor_data[:neighbor_count]
        ),
        "vertex_to_triangle_records": vertex_to_triangle_records,
        "bind_positions": _tuple_vectors(bind_positions),
        "bind_rotations": _tuple_vectors(bind_rotations),
    }


def mc2_world_rotation_xyzw(normal, tangent) -> tuple[float, float, float, float]:
    """MC2 ``MathUtility.ToRotation(normal, tangent)`` in xyzw layout."""
    value = orientation_xyzw_f64(
        np.asarray(normal, dtype=np.float64),
        np.asarray(tangent, dtype=np.float64),
    )
    return tuple(float(component) for component in value)


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
    native_context=None,
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
    derived = _build_final_proxy_derived(
        positions,
        normals,
        tangents,
        uv_array,
        attributes,
        final_triangles,
        triangle_normals,
        line_records,
        native_context=native_context,
    )
    normals = derived["normals"]
    tangents = derived["tangents"]
    attributes = derived["attributes"]
    proxy = make_mc2_proxy_static_spec(
        task_id=task_id,
        setup_type=setup_type,
        vertex_identities=identities,
        local_positions=_tuple_vectors(positions),
        local_normals=_tuple_vectors(normals),
        local_tangents=_tuple_vectors(tangents),
        uvs=_tuple_vectors(uv_array),
        vertex_attributes=attributes,
        edges=derived["edges"],
        triangles=final_triangles,
    )
    native_finalizer = derived.get("native_finalizer")
    if native_finalizer is None:
        finalizer = make_mc2_proxy_finalizer_static_spec(
            proxy=proxy,
            vertex_to_vertex_ranges=derived["vertex_to_vertex_ranges"],
            vertex_to_vertex_data=derived["vertex_to_vertex_data"],
            vertex_to_triangle_records=derived["vertex_to_triangle_records"],
            vertex_bind_pose_positions=derived["bind_positions"],
            vertex_bind_pose_rotations=derived["bind_rotations"],
        )
    else:
        finalizer = MC2MeshFinalizerNativeData(
            proxy_signature=proxy.proxy_signature,
            vertex_count=proxy.vertex_count,
            vertex_to_vertex_ranges=native_finalizer["vertex_to_vertex_ranges"],
            vertex_to_vertex_data=native_finalizer["vertex_to_vertex_data"],
            vertex_to_triangle_ranges=native_finalizer["vertex_to_triangle_ranges"],
            vertex_to_triangle_data=native_finalizer["vertex_to_triangle_data"],
            vertex_bind_pose_positions=native_finalizer["bind_positions"],
            vertex_bind_pose_rotations=native_finalizer["bind_rotations"],
        )
    return MC2MeshFinalProxyBuildResult(
        proxy=proxy,
        lines=tuple(_canonical_edge(first, second) for first, second in line_records),
        finalizer=finalizer,
    )


def _fallback_tangent(normal: np.ndarray) -> np.ndarray:
    up = np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
    right = np.asarray((1.0, 0.0, 0.0), dtype=np.float64)
    if float(np.dot(normal, up)) < 0.9:
        return normalize_vector_f64(np.cross(normal, up), name="generated tangent")
    return normalize_vector_f64(np.cross(normal, right), name="generated tangent")


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
    loop_count = len(mesh.loops)
    loop_vertices = np.empty(loop_count, dtype=np.int32)
    loop_uvs = np.empty(loop_count * 2, dtype=np.float32)
    mesh.loops.foreach_get("vertex_index", loop_vertices)
    uv_layer.data.foreach_get("uv", loop_uvs)
    loop_uvs = loop_uvs.reshape((-1, 2))

    minimum = np.full((vertex_count, 2), np.inf, dtype=np.float32)
    maximum = np.full((vertex_count, 2), -np.inf, dtype=np.float32)
    np.minimum.at(minimum, loop_vertices, loop_uvs)
    np.maximum.at(maximum, loop_vertices, loop_uvs)
    invalid = np.flatnonzero(np.any(maximum - minimum > UV_SEAM_TOLERANCE, axis=1))
    if len(invalid):
        raise ValueError(
            f"Blender vertex {int(invalid[0])} has multiple loop UVs; split the proxy vertex"
        )

    values = np.zeros((vertex_count, 2), dtype=np.float32)
    vertices, first_indices = np.unique(loop_vertices, return_index=True)
    values[vertices] = loop_uvs[first_indices]
    return tuple(tuple(float(value) for value in row) for row in values)


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
    native_context=None,
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
        normal = normalize_vector_f64(
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
    return build_mc2_final_proxy(
        task_id=task_id,
        setup_type="mesh_cloth",
        vertex_identities=tuple(f"mesh:v{index}" for index in range(vertex_count)),
        local_positions=positions,
        local_normals=tuple(normals),
        local_tangents=tuple(tangents),
        uvs=uvs,
        vertex_attributes=attributes,
        lines=lines,
        triangles=triangles,
        native_context=native_context,
    )


__all__ = [
    "MC2MeshFinalProxyBuildResult",
    "MC2MeshFinalizerNativeData",
    "MC2MeshFinalizerNativeMetadata",
    "UV_SEAM_TOLERANCE",
    "build_blender_mesh_final_proxy",
    "build_mc2_final_proxy",
    "mc2_world_rotation_xyzw",
]
