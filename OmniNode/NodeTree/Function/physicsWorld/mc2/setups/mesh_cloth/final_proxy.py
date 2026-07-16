"""MeshCloth final-proxy extraction and source-aligned finalization.

The public product contract keeps Blender vertex identity unchanged: no
reduction, no merge, no split, no remap. This module only converts that fixed
authoring mesh into the finalized MC2 proxy fields consumed by the existing N0
baseline builder.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

import numpy as np

from ....utils.math3d import orientation_xyzw_f64
from ...mesh_baseline import MC2_VERTEX_FIXED
from ...mesh_baseline import MC2_VERTEX_MOVE
from ...static_data import MC2ProxyStaticSpec
from ...static_data import MC2ProxyFinalizerStaticSpec
from ...static_data import make_mc2_proxy_finalizer_static_spec
from ...static_data import make_mc2_proxy_static_spec
from ...static_data import mc2_proxy_content_signature


UV_SEAM_TOLERANCE = 1.0e-6


@dataclass(frozen=True)
class MC2MeshFinalProxyBuildResult:
    proxy: MC2ProxyStaticSpec | MC2MeshProxyNativeData | MC2MeshProxyNativeMetadata
    lines: tuple[tuple[int, int], ...]
    finalizer: (
        MC2ProxyFinalizerStaticSpec
        | MC2MeshFinalizerNativeData
        | MC2MeshFinalizerNativeMetadata
    )
    mesh_topology_signature: str = ""

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

    def compact_native_finalizer(self, *, proxy_metadata=None):
        finalizer = self.finalizer
        proxy = self.proxy
        if not isinstance(finalizer, MC2MeshFinalizerNativeData) and not isinstance(
            proxy, MC2MeshProxyNativeData
        ):
            return self
        return MC2MeshFinalProxyBuildResult(
            proxy=(
                proxy_metadata
                if proxy_metadata is not None
                else proxy.metadata() if isinstance(proxy, MC2MeshProxyNativeData) else proxy
            ),
            lines=() if isinstance(proxy, MC2MeshProxyNativeData) else self.lines,
            finalizer=(
                finalizer.metadata()
                if isinstance(finalizer, MC2MeshFinalizerNativeData)
                else finalizer
            ),
            mesh_topology_signature=self.mesh_topology_signature,
        )


def _readonly_copy(values, dtype, width: int | None = None) -> np.ndarray:
    result = np.array(values, dtype=dtype, copy=True, order="C")
    if width is not None:
        result = result.reshape((-1, width))
    result.flags.writeable = False
    return result


@dataclass(frozen=True)
class MC2MeshProxyNativeMetadata:
    task_id: str
    setup_type: str
    vertex_identities: tuple[str, ...]
    vertex_attributes: np.ndarray
    edges: np.ndarray
    triangles: np.ndarray
    proxy_signature: str
    native_owned: bool = True

    @property
    def vertex_count(self) -> int:
        return len(self.vertex_identities)


@dataclass(frozen=True)
class MC2MeshProxyNativeData:
    task_id: str
    setup_type: str
    vertex_identities: tuple[str, ...]
    local_positions: np.ndarray
    local_normals: np.ndarray
    local_tangents: np.ndarray
    uvs: np.ndarray
    vertex_attributes: np.ndarray
    edges: np.ndarray
    triangles: np.ndarray
    proxy_signature: str
    native_registration: dict | None = None
    native_owned: bool = True

    @property
    def vertex_count(self) -> int:
        return len(self.vertex_identities)

    def with_vertex_attributes(self, values) -> MC2MeshProxyNativeData:
        attributes = np.ascontiguousarray(values, dtype=np.uint8)
        if attributes.shape != (self.vertex_count,):
            raise ValueError("vertex_attributes length must match vertex_count")
        return MC2MeshProxyNativeData(
            task_id=self.task_id,
            setup_type=self.setup_type,
            vertex_identities=self.vertex_identities,
            local_positions=self.local_positions,
            local_normals=self.local_normals,
            local_tangents=self.local_tangents,
            uvs=self.uvs,
            vertex_attributes=attributes,
            edges=self.edges,
            triangles=self.triangles,
            proxy_signature=mc2_proxy_content_signature(
                task_id=self.task_id,
                setup_type=self.setup_type,
                vertex_identities=self.vertex_identities,
                local_positions=self.local_positions,
                local_normals=self.local_normals,
                local_tangents=self.local_tangents,
                uvs=self.uvs,
                vertex_attributes=attributes,
                edges=self.edges,
                triangles=self.triangles,
            ),
            native_registration=self.native_registration,
        )

    def metadata(self) -> MC2MeshProxyNativeMetadata:
        return MC2MeshProxyNativeMetadata(
            task_id=self.task_id,
            setup_type=self.setup_type,
            vertex_identities=self.vertex_identities,
            vertex_attributes=_readonly_copy(self.vertex_attributes, np.uint8),
            edges=_readonly_copy(self.edges, np.int32, 2),
            triangles=_readonly_copy(self.triangles, np.int32, 3),
            proxy_signature=self.proxy_signature,
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
    native_frame_registration: dict | None = None

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
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != width:
        raise ValueError(f"{name} must have shape [N,{width}]")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} cannot contain NaN/Inf")
    return array


def _int_records(values, *, width: int, name: str) -> tuple[tuple[int, ...], ...]:
    records = []
    for index, value in enumerate(() if values is None else values):
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
    triangles,
    *,
    keep_arrays: bool = False,
):
    if len(triangles) == 0:
        return triangles, []
    final_triangles = np.ascontiguousarray(triangles, dtype=np.int32)
    normals = np.empty((len(triangles), 3), dtype=np.float64)
    from ...native import native_module

    native_module().mc2_optimize_triangle_direction_v0(
        np.ascontiguousarray(positions, dtype=np.float64),
        final_triangles,
        normals,
    )
    if keep_arrays:
        return final_triangles, normals
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
        native_context is not None,
    )
    edge_count = int(counts["edge_count"])
    neighbor_count = int(counts["neighbor_count"])
    triangle_record_count = int(counts["triangle_record_count"])
    triangle_data = out_triangle_data[:triangle_record_count]
    if native_context is not None:
        return {
            "normals": normals,
            "tangents": tangents,
            "attributes": attribute_values,
            "edges": out_edges[:edge_count],
            "native_registration": {
                "positions": counts["proxy_local_positions"],
                "normals": counts["proxy_local_normals"],
                "tangents": counts["proxy_local_tangents"],
                "uvs": counts["proxy_uvs"],
                "attributes": counts["proxy_attributes"],
                "edges": counts["proxy_edges"],
                "triangles": counts["proxy_triangles"],
                "owners": (
                    counts["_proxy_positions_owner"],
                    counts["_proxy_normals_owner"],
                    counts["_proxy_tangents_owner"],
                    counts["_proxy_uvs_owner"],
                    counts["_proxy_attributes_owner"],
                    counts["_proxy_edges_owner"],
                    counts["_proxy_triangles_owner"],
                ),
            },
            "native_finalizer": {
                "vertex_to_vertex_ranges": out_neighbor_ranges,
                "vertex_to_vertex_data": out_neighbor_data[:neighbor_count],
                "vertex_to_triangle_ranges": out_triangle_ranges,
                "vertex_to_triangle_data": triangle_data,
                "bind_positions": bind_positions,
                "bind_rotations": bind_rotations,
                "native_frame_registration": {
                    "triangle_ranges": counts["frame_triangle_ranges"],
                    "triangle_records": counts["frame_triangle_records"],
                    "bind_rotations": counts["frame_bind_rotations"],
                    "owners": (
                        counts["_frame_triangle_ranges_owner"],
                        counts["_frame_triangle_records_owner"],
                        counts["_frame_bind_rotations_owner"],
                    ),
                },
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


def _native_int_records(values, *, width: int, vertex_count: int, name: str) -> np.ndarray:
    records = np.ascontiguousarray(values, dtype=np.int32)
    if records.size == 0:
        return records.reshape((0, width))
    if records.ndim != 2 or records.shape[1] != width:
        raise ValueError(f"{name} must have shape [N,{width}]")
    if np.any(records < 0) or np.any(records >= vertex_count):
        raise ValueError(f"{name} contains an out-of-range vertex index")
    return records


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
    if native_context is None:
        line_records = _int_records(lines, width=2, name="lines")
        triangle_records = _int_records(triangles, width=3, name="triangles")
        _validate_indices(vertex_count, line_records, "lines")
        _validate_indices(vertex_count, triangle_records, "triangles")
    else:
        line_records = _native_int_records(
            lines,
            width=2,
            vertex_count=vertex_count,
            name="lines",
        )
        triangle_records = _native_int_records(
            triangles,
            width=3,
            vertex_count=vertex_count,
            name="triangles",
        )

    final_triangles, triangle_normals = _optimize_triangle_direction(
        positions,
        triangle_records,
        keep_arrays=native_context is not None,
    )
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
    if native_context is None:
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
    else:
        task_value = str(task_id or "")
        setup_value = str(setup_type or "").strip().lower()
        if not task_value:
            raise ValueError("task_id cannot be empty")
        if setup_value != "mesh_cloth":
            raise ValueError("staged Mesh proxy requires mesh_cloth setup_type")
        triangle_values = np.ascontiguousarray(final_triangles, dtype=np.int32).reshape((-1, 3))
        proxy = MC2MeshProxyNativeData(
            task_id=task_value,
            setup_type=setup_value,
            vertex_identities=identities,
            local_positions=positions,
            local_normals=normals,
            local_tangents=tangents,
            uvs=uv_array,
            vertex_attributes=derived["attributes"],
            edges=derived["edges"],
            triangles=triangle_values,
            proxy_signature=mc2_proxy_content_signature(
                task_id=task_value,
                setup_type=setup_value,
                vertex_identities=identities,
                local_positions=positions,
                local_normals=normals,
                local_tangents=tangents,
                uvs=uv_array,
                vertex_attributes=derived["attributes"],
                edges=derived["edges"],
                triangles=triangle_values,
            ),
            native_registration=derived["native_registration"],
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
            native_frame_registration=native_finalizer["native_frame_registration"],
        )
    return MC2MeshFinalProxyBuildResult(
        proxy=proxy,
        lines=(
            ()
            if native_context is not None
            else tuple(_canonical_edge(first, second) for first, second in line_records)
        ),
        finalizer=finalizer,
    )


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


def _mesh_uvs(
    mesh,
    triangles,
    *,
    uv_layer_name: str | None,
    raw_snapshot=None,
) -> tuple[tuple[float, float], ...]:
    vertex_count = len(mesh.vertices)
    if len(triangles) == 0:
        return tuple((0.0, 0.0) for _ in range(vertex_count))
    if raw_snapshot is not None:
        if not bool(raw_snapshot.has_uv):
            raise ValueError("MeshCloth triangle proxy requires a UV layer")
        loop_vertices = raw_snapshot.loop_vertices
        loop_uvs = raw_snapshot.loop_uvs
    else:
        uv_layer = mesh.uv_layers.get(uv_layer_name) if uv_layer_name else mesh.uv_layers.active
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
    raw_snapshot=None,
) -> MC2MeshFinalProxyBuildResult:
    from .base_pose import mesh_topology_signature

    if obj is None or getattr(obj, "type", None) != "MESH" or obj.data is None:
        raise ValueError("MeshCloth final proxy target must be a Mesh object")
    actual_mesh_topology_signature = mesh_topology_signature(obj)
    if (
        expected_mesh_topology_signature
        and actual_mesh_topology_signature != expected_mesh_topology_signature
    ):
        raise ValueError("Mesh topology signature does not match expected token")
    mesh = obj.data
    if raw_snapshot is not None and (
        int(getattr(raw_snapshot, "source_pointer", 0)) != int(obj.as_pointer())
        or int(getattr(raw_snapshot, "mesh_pointer", 0)) != int(mesh.as_pointer())
    ):
        raise ValueError("Mesh raw snapshot identity does not match the proxy object")
    mesh.update()
    vertex_count = len(mesh.vertices)
    triangles = raw_snapshot.triangles if raw_snapshot is not None else _mesh_triangles(mesh)
    uvs = _mesh_uvs(
        mesh,
        triangles,
        uv_layer_name=uv_layer_name,
        raw_snapshot=raw_snapshot,
    )
    positions = (
        np.ascontiguousarray(raw_snapshot.positions, dtype=np.float64)
        if raw_snapshot is not None
        else np.empty(vertex_count * 3, dtype=np.float64)
    )
    normals = (
        np.ascontiguousarray(raw_snapshot.normals, dtype=np.float64)
        if raw_snapshot is not None
        else np.empty(vertex_count * 3, dtype=np.float64)
    )
    tangents = np.empty(vertex_count * 3, dtype=np.float64)
    if raw_snapshot is None:
        mesh.vertices.foreach_get("co", positions)
        mesh.vertices.foreach_get("normal", normals)
    positions = positions.reshape((-1, 3))
    normals = normals.reshape((-1, 3))
    tangents = tangents.reshape((-1, 3))
    from ...native import native_module

    native_module().mc2_build_mesh_fallback_tangents_v0(normals, tangents)
    if not pin_enabled:
        attributes = tuple(MC2_VERTEX_MOVE for _ in range(vertex_count))
    elif not pin_vertex_group:
        attributes = tuple(MC2_VERTEX_FIXED for _ in range(vertex_count))
    else:
        weights = (
            tuple(float(value) for value in raw_snapshot.pin_weights)
            if raw_snapshot is not None
            else _vertex_group_weights(obj, pin_vertex_group, vertex_count)
        )
        attributes = tuple(
            MC2_VERTEX_FIXED if weight > 0.0 else MC2_VERTEX_MOVE
            for weight in weights
        )
    if raw_snapshot is not None:
        lines = raw_snapshot.edges
    else:
        lines = np.empty(len(mesh.edges) * 2, dtype=np.int32)
        mesh.edges.foreach_get("vertices", lines)
        lines = lines.reshape((-1, 2))
    return replace(
        build_mc2_final_proxy(
            task_id=task_id,
            setup_type="mesh_cloth",
            vertex_identities=tuple(f"mesh:v{index}" for index in range(vertex_count)),
            local_positions=positions,
            local_normals=normals,
            local_tangents=tangents,
            uvs=uvs,
            vertex_attributes=attributes,
            lines=lines,
            triangles=triangles,
            native_context=native_context,
        ),
        mesh_topology_signature=actual_mesh_topology_signature,
    )


__all__ = [
    "MC2MeshFinalProxyBuildResult",
    "MC2MeshFinalizerNativeData",
    "MC2MeshFinalizerNativeMetadata",
    "MC2MeshProxyNativeData",
    "MC2MeshProxyNativeMetadata",
    "UV_SEAM_TOLERANCE",
    "build_blender_mesh_final_proxy",
    "build_mc2_final_proxy",
    "mc2_world_rotation_xyzw",
]
