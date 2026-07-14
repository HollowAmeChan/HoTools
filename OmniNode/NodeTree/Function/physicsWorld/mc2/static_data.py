"""Source-aligned MC2 N0 proxy and baseline data contracts.

This module validates already-built static arrays. It deliberately does not
implement selection mapping, proxy construction, baseline construction, or a
solver. Native packing is explicit and keeps source semantics separate from
Unity's internal packed containers.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from .names import MC2_SETUP_TYPES


MC2_STATIC_SCHEMA_VERSION = 1


def _signature(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _finite(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} cannot contain NaN/Inf")
    return number


def _values_or_empty(values):
    return () if values is None else values


def _vectors(values, width: int, name: str, *, count: int | None = None) -> tuple:
    result = []
    for index, value in enumerate(_values_or_empty(values)):
        try:
            components = tuple(value)
        except TypeError as exc:
            raise TypeError(f"{name}[{index}] must be a {width}D vector") from exc
        if len(components) != width:
            raise ValueError(f"{name}[{index}] must contain {width} values")
        result.append(tuple(_finite(item, f"{name}[{index}]") for item in components))
    if count is not None and len(result) != count:
        raise ValueError(f"{name} length must be {count}, got {len(result)}")
    return tuple(result)


def _baseline_quaternions(values, name: str, *, count: int, active_indices) -> tuple:
    result = _vectors(values, 4, name, count=count)
    active = set(active_indices)
    for index, value in enumerate(result):
        length_squared = sum(component * component for component in value)
        if index in active:
            if abs(length_squared - 1.0) > 1.0e-4:
                raise ValueError(f"{name}[{index}] must be a unit xyzw quaternion")
        elif length_squared > 1.0e-12:
            raise ValueError(
                f"{name}[{index}] must be zero outside baseline_data"
            )
    return result


def _integers(values, name: str, *, count: int | None = None) -> tuple[int, ...]:
    result = []
    for index, value in enumerate(_values_or_empty(values)):
        if isinstance(value, bool):
            raise TypeError(f"{name}[{index}] must be an integer")
        try:
            integer = int(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"{name}[{index}] must be an integer") from exc
        if integer != value:
            raise ValueError(f"{name}[{index}] must be an exact integer")
        result.append(integer)
    if count is not None and len(result) != count:
        raise ValueError(f"{name} length must be {count}, got {len(result)}")
    return tuple(result)


def _records(values, width: int, name: str) -> tuple[tuple[int, ...], ...]:
    result = []
    for index, value in enumerate(_values_or_empty(values)):
        try:
            record = tuple(value)
        except TypeError as exc:
            raise TypeError(f"{name}[{index}] must be an int{width} record") from exc
        if len(record) != width:
            raise ValueError(f"{name}[{index}] must contain {width} indices")
        result.append(_integers(record, f"{name}[{index}]", count=width))
    return tuple(result)


def _validate_vertex_indices(records, vertex_count: int, name: str) -> None:
    for record_index, record in enumerate(records):
        for component in record:
            if not 0 <= component < vertex_count:
                raise ValueError(f"{name}[{record_index}] index {component} is out of range")


def _normalize_edges(values, vertex_count: int) -> tuple[tuple[int, int], ...]:
    result = []
    seen = set()
    for index, record in enumerate(_records(values, 2, "edges")):
        first, second = record
        if first == second:
            raise ValueError(f"edges[{index}] cannot be a self edge")
        edge = (first, second) if first < second else (second, first)
        if edge in seen:
            raise ValueError(f"edges contains duplicate canonical edge {edge}")
        seen.add(edge)
        result.append(edge)
    normalized = tuple(sorted(result))
    _validate_vertex_indices(normalized, vertex_count, "edges")
    return normalized


def _normalize_triangles(values, vertex_count: int) -> tuple[tuple[int, int, int], ...]:
    result = []
    seen = set()
    for index, triangle in enumerate(_records(values, 3, "triangles")):
        if len(set(triangle)) != 3:
            raise ValueError(f"triangles[{index}] is degenerate")
        canonical = tuple(sorted(triangle))
        if canonical in seen:
            raise ValueError(f"triangles contains duplicate triangle {canonical}")
        seen.add(canonical)
        result.append(triangle)
    normalized = tuple(result)
    _validate_vertex_indices(normalized, vertex_count, "triangles")
    return normalized


def _normalize_ranges(values, name: str, data_length: int, *, count: int | None = None) -> tuple:
    ranges = _records(values, 2, name)
    if count is not None and len(ranges) != count:
        raise ValueError(f"{name} length must be {count}, got {len(ranges)}")
    cursor = 0
    for index, (start, length) in enumerate(ranges):
        if start != cursor or length < 0:
            raise ValueError(f"{name}[{index}] must form a dense non-negative range")
        cursor += length
    if cursor != data_length:
        raise ValueError(f"{name} covers {cursor} records, expected {data_length}")
    return ranges


def _readonly_array(values, dtype, shape: tuple[int, ...]) -> np.ndarray:
    array = np.ascontiguousarray(values, dtype=dtype).reshape(shape)
    array.flags.writeable = False
    return array


@dataclass(frozen=True)
class MC2ProxyStaticSpec:
    task_id: str
    setup_type: str
    vertex_identities: tuple[str, ...]
    local_positions: tuple[tuple[float, float, float], ...]
    local_normals: tuple[tuple[float, float, float], ...]
    local_tangents: tuple[tuple[float, float, float], ...]
    uvs: tuple[tuple[float, float], ...]
    vertex_attributes: tuple[int, ...]
    edges: tuple[tuple[int, int], ...]
    triangles: tuple[tuple[int, int, int], ...]
    proxy_signature: str
    schema_version: int = MC2_STATIC_SCHEMA_VERSION

    @property
    def vertex_count(self) -> int:
        return len(self.vertex_identities)

    def __post_init__(self) -> None:
        if self.schema_version != MC2_STATIC_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 proxy static schema")
        if self.setup_type not in MC2_SETUP_TYPES:
            raise ValueError(f"unknown MC2 setup_type: {self.setup_type!r}")
        if not self.task_id:
            raise ValueError("task_id cannot be empty")
        count = self.vertex_count
        if count == 0:
            raise ValueError("MC2 proxy must contain at least one vertex")
        if len(set(self.vertex_identities)) != count or any(not value for value in self.vertex_identities):
            raise ValueError("vertex_identities must be non-empty and unique")
        tuple_fields = (
            self.vertex_identities,
            self.local_positions,
            self.local_normals,
            self.local_tangents,
            self.uvs,
            self.vertex_attributes,
            self.edges,
            self.triangles,
        )
        if any(not isinstance(values, tuple) for values in tuple_fields):
            raise TypeError("MC2 proxy static arrays must be immutable tuples")
        per_vertex = tuple_fields[1:6]
        if any(len(values) != count for values in per_vertex):
            raise ValueError("MC2 proxy per-vertex array lengths do not match")
        normalized_vectors = (
            _vectors(self.local_positions, 3, "local_positions", count=count),
            _vectors(self.local_normals, 3, "local_normals", count=count),
            _vectors(self.local_tangents, 3, "local_tangents", count=count),
            _vectors(self.uvs, 2, "uvs", count=count),
        )
        if normalized_vectors != tuple_fields[1:5]:
            raise TypeError("MC2 proxy vector records must be immutable tuples")
        attributes = _integers(
            self.vertex_attributes,
            "vertex_attributes",
            count=count,
        )
        if any(not 0 <= value <= 0xFF for value in attributes):
            raise ValueError("vertex_attributes must fit uint8")
        if self.edges != _normalize_edges(self.edges, count):
            raise ValueError("edges must be canonical and sorted")
        if self.triangles != _normalize_triangles(self.triangles, count):
            raise TypeError("triangle records must be immutable tuples")
        expected = _signature(self.signature_payload())
        if self.proxy_signature != expected:
            raise ValueError("proxy_signature does not match proxy static payload")

    def signature_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "setup_type": self.setup_type,
            "vertex_identities": self.vertex_identities,
            "local_positions": self.local_positions,
            "local_normals": self.local_normals,
            "local_tangents": self.local_tangents,
            "uvs": self.uvs,
            "vertex_attributes": self.vertex_attributes,
            "edges": self.edges,
            "triangles": self.triangles,
        }

    def debug_dict(self, *, include_arrays: bool = False) -> dict:
        result = {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "setup_type": self.setup_type,
            "vertex_count": self.vertex_count,
            "edge_count": len(self.edges),
            "triangle_count": len(self.triangles),
            "proxy_signature": self.proxy_signature,
        }
        if include_arrays:
            result.update(self.signature_payload())
        return result


def make_mc2_proxy_static_spec(
    *,
    task_id: object,
    setup_type: object,
    vertex_identities,
    local_positions,
    local_normals,
    local_tangents,
    uvs,
    vertex_attributes,
    edges,
    triangles,
) -> MC2ProxyStaticSpec:
    identities = tuple(str(value or "") for value in _values_or_empty(vertex_identities))
    count = len(identities)
    setup = str(setup_type or "").strip().lower()
    payload = {
        "schema_version": MC2_STATIC_SCHEMA_VERSION,
        "task_id": str(task_id or ""),
        "setup_type": setup,
        "vertex_identities": identities,
        "local_positions": _vectors(local_positions, 3, "local_positions", count=count),
        "local_normals": _vectors(local_normals, 3, "local_normals", count=count),
        "local_tangents": _vectors(local_tangents, 3, "local_tangents", count=count),
        "uvs": _vectors(uvs, 2, "uvs", count=count),
        "vertex_attributes": _integers(
            vertex_attributes,
            "vertex_attributes",
            count=count,
        ),
        "edges": _normalize_edges(edges, count),
        "triangles": _normalize_triangles(triangles, count),
    }
    for index, attribute in enumerate(payload["vertex_attributes"]):
        if not 0 <= attribute <= 0xFF:
            raise ValueError(f"vertex_attributes[{index}] must fit uint8")
    return MC2ProxyStaticSpec(**payload, proxy_signature=_signature(payload))


def _unit_quaternions(values, name: str, *, count: int) -> tuple:
    result = _vectors(values, 4, name, count=count)
    for index, value in enumerate(result):
        length_squared = sum(component * component for component in value)
        if abs(length_squared - 1.0) > 1.0e-4:
            raise ValueError(f"{name}[{index}] must be a unit xyzw quaternion")
    return result


@dataclass(frozen=True)
class MC2ProxyFinalizerStaticSpec:
    proxy_signature: str
    vertex_count: int
    vertex_to_vertex_ranges: tuple[tuple[int, int], ...]
    vertex_to_vertex_data: tuple[int, ...]
    vertex_to_triangle_records: tuple[tuple[tuple[int, int], ...], ...]
    vertex_bind_pose_positions: tuple[tuple[float, float, float], ...]
    vertex_bind_pose_rotations: tuple[tuple[float, float, float, float], ...]
    finalizer_signature: str
    schema_version: int = MC2_STATIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MC2_STATIC_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 proxy finalizer static schema")
        if not self.proxy_signature:
            raise ValueError("proxy_signature cannot be empty")
        if self.vertex_count <= 0:
            raise ValueError("vertex_count must be positive")
        tuple_fields = (
            self.vertex_to_vertex_ranges,
            self.vertex_to_vertex_data,
            self.vertex_to_triangle_records,
            self.vertex_bind_pose_positions,
            self.vertex_bind_pose_rotations,
        )
        if any(not isinstance(values, tuple) for values in tuple_fields):
            raise TypeError("MC2 proxy finalizer arrays must be immutable tuples")
        neighbor_data = _integers(self.vertex_to_vertex_data, "vertex_to_vertex_data")
        _validate_vertex_indices((neighbor_data,), self.vertex_count, "vertex_to_vertex_data")
        neighbor_ranges = _normalize_ranges(
            self.vertex_to_vertex_ranges,
            "vertex_to_vertex_ranges",
            len(neighbor_data),
            count=self.vertex_count,
        )
        if neighbor_ranges != self.vertex_to_vertex_ranges:
            raise TypeError("vertex adjacency ranges must be immutable tuples")
        for vertex, (start, length) in enumerate(neighbor_ranges):
            neighbors = neighbor_data[start:start + length]
            if vertex in neighbors or len(set(neighbors)) != len(neighbors):
                raise ValueError("vertex adjacency cannot contain self or duplicate neighbors")
        if len(self.vertex_to_triangle_records) != self.vertex_count:
            raise ValueError("vertex_to_triangle_records length must match vertex_count")
        for vertex, values in enumerate(self.vertex_to_triangle_records):
            if not isinstance(values, tuple):
                raise TypeError("vertex-to-triangle rows must be immutable tuples")
            records = _records(values, 2, f"vertex_to_triangle_records[{vertex}]")
            if records != values:
                raise TypeError("vertex-to-triangle records must be immutable tuples")
            if len(records) > 7:
                raise ValueError("MC2 vertex_to_triangle_records supports at most 7 triangles per vertex")
            if any(not 0 <= flip <= 0x3 or triangle_index < 0 for flip, triangle_index in records):
                raise ValueError("vertex-to-triangle record is outside the packed source contract")
        if self.vertex_bind_pose_positions != _vectors(
            self.vertex_bind_pose_positions,
            3,
            "vertex_bind_pose_positions",
            count=self.vertex_count,
        ):
            raise TypeError("vertex bind pose positions must be immutable tuples")
        if self.vertex_bind_pose_rotations != _unit_quaternions(
            self.vertex_bind_pose_rotations,
            "vertex_bind_pose_rotations",
            count=self.vertex_count,
        ):
            raise TypeError("vertex bind pose rotations must be immutable tuples")
        expected = _signature(self.signature_payload())
        if self.finalizer_signature != expected:
            raise ValueError("finalizer_signature does not match proxy finalizer payload")

    def signature_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "proxy_signature": self.proxy_signature,
            "vertex_count": self.vertex_count,
            "vertex_to_vertex_ranges": self.vertex_to_vertex_ranges,
            "vertex_to_vertex_data": self.vertex_to_vertex_data,
            "vertex_to_triangle_records": self.vertex_to_triangle_records,
            "vertex_bind_pose_positions": self.vertex_bind_pose_positions,
            "vertex_bind_pose_rotations": self.vertex_bind_pose_rotations,
        }

    def debug_dict(self, *, include_arrays: bool = False) -> dict:
        result = {
            "schema_version": self.schema_version,
            "vertex_count": self.vertex_count,
            "proxy_signature": self.proxy_signature,
            "finalizer_signature": self.finalizer_signature,
        }
        if include_arrays:
            result.update(self.signature_payload())
        return result


def make_mc2_proxy_finalizer_static_spec(
    *,
    proxy: MC2ProxyStaticSpec,
    vertex_to_vertex_ranges,
    vertex_to_vertex_data,
    vertex_to_triangle_records,
    vertex_bind_pose_positions,
    vertex_bind_pose_rotations,
) -> MC2ProxyFinalizerStaticSpec:
    if not isinstance(proxy, MC2ProxyStaticSpec):
        raise TypeError("proxy must be MC2ProxyStaticSpec")
    count = proxy.vertex_count
    neighbor_data = _integers(vertex_to_vertex_data, "vertex_to_vertex_data")
    _validate_vertex_indices((neighbor_data,), count, "vertex_to_vertex_data")
    neighbor_ranges = _normalize_ranges(
        vertex_to_vertex_ranges,
        "vertex_to_vertex_ranges",
        len(neighbor_data),
        count=count,
    )
    observed_relations = set()
    for vertex, (start, length) in enumerate(neighbor_ranges):
        neighbors = neighbor_data[start:start + length]
        if len(set(neighbors)) != len(neighbors):
            raise ValueError(f"vertex_to_vertex_data contains duplicate neighbor for vertex {vertex}")
        for neighbor in neighbors:
            if neighbor == vertex:
                raise ValueError("vertex_to_vertex_data cannot contain self adjacency")
            observed_relations.add((vertex, neighbor))
    expected_relations = {
        relation
        for first, second in proxy.edges
        for relation in ((first, second), (second, first))
    }
    if observed_relations != expected_relations:
        raise ValueError("vertex adjacency must cover exactly the finalized proxy edges")

    triangle_rows = []
    for vertex, values in enumerate(_values_or_empty(vertex_to_triangle_records)):
        records = _records(values, 2, f"vertex_to_triangle_records[{vertex}]")
        if len(records) > 7:
            raise ValueError("MC2 vertex_to_triangle_records supports at most 7 triangles per vertex")
        seen = set()
        for flip, triangle_index in records:
            if not 0 <= flip <= 0x3:
                raise ValueError("vertex-to-triangle flip flag must fit the source 2-bit contract")
            if not 0 <= triangle_index < len(proxy.triangles):
                raise ValueError("vertex-to-triangle triangle index is out of range")
            if triangle_index in seen:
                raise ValueError("vertex-to-triangle records cannot repeat a triangle")
            if vertex not in proxy.triangles[triangle_index]:
                raise ValueError("vertex-to-triangle record does not reference an incident triangle")
            seen.add(triangle_index)
        triangle_rows.append(records)
    if len(triangle_rows) != count:
        raise ValueError("vertex_to_triangle_records length must match vertex_count")

    payload = {
        "schema_version": MC2_STATIC_SCHEMA_VERSION,
        "proxy_signature": proxy.proxy_signature,
        "vertex_count": count,
        "vertex_to_vertex_ranges": neighbor_ranges,
        "vertex_to_vertex_data": neighbor_data,
        "vertex_to_triangle_records": tuple(triangle_rows),
        "vertex_bind_pose_positions": _vectors(
            vertex_bind_pose_positions,
            3,
            "vertex_bind_pose_positions",
            count=count,
        ),
        "vertex_bind_pose_rotations": _unit_quaternions(
            vertex_bind_pose_rotations,
            "vertex_bind_pose_rotations",
            count=count,
        ),
    }
    return MC2ProxyFinalizerStaticSpec(
        **payload,
        finalizer_signature=_signature(payload),
    )


@dataclass(frozen=True)
class MC2BaselineStaticSpec:
    proxy_signature: str
    vertex_count: int
    parent_indices: tuple[int, ...]
    child_ranges: tuple[tuple[int, int], ...]
    child_data: tuple[int, ...]
    baseline_flags: tuple[int, ...]
    baseline_ranges: tuple[tuple[int, int], ...]
    baseline_data: tuple[int, ...]
    root_indices: tuple[int, ...]
    depths: tuple[float, ...]
    vertex_local_positions: tuple[tuple[float, float, float], ...]
    vertex_local_rotations: tuple[tuple[float, float, float, float], ...]
    baseline_signature: str
    schema_version: int = MC2_STATIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MC2_STATIC_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 baseline static schema")
        if self.vertex_count <= 0:
            raise ValueError("vertex_count must be positive")
        tuple_fields = (
            self.parent_indices,
            self.child_ranges,
            self.child_data,
            self.baseline_flags,
            self.baseline_ranges,
            self.baseline_data,
            self.root_indices,
            self.depths,
            self.vertex_local_positions,
            self.vertex_local_rotations,
        )
        if any(not isinstance(values, tuple) for values in tuple_fields):
            raise TypeError("MC2 baseline static arrays must be immutable tuples")
        _validate_baseline_contract(self)
        expected = _signature(self.signature_payload())
        if self.baseline_signature != expected:
            raise ValueError("baseline_signature does not match baseline static payload")

    def signature_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "proxy_signature": self.proxy_signature,
            "vertex_count": self.vertex_count,
            "parent_indices": self.parent_indices,
            "child_ranges": self.child_ranges,
            "child_data": self.child_data,
            "baseline_flags": self.baseline_flags,
            "baseline_ranges": self.baseline_ranges,
            "baseline_data": self.baseline_data,
            "root_indices": self.root_indices,
            "depths": self.depths,
            "vertex_local_positions": self.vertex_local_positions,
            "vertex_local_rotations": self.vertex_local_rotations,
        }

    def debug_dict(self, *, include_arrays: bool = False) -> dict:
        result = {
            "schema_version": self.schema_version,
            "vertex_count": self.vertex_count,
            "baseline_count": len(self.baseline_ranges),
            "root_count": sum(1 for value in self.parent_indices if value < 0),
            "proxy_signature": self.proxy_signature,
            "baseline_signature": self.baseline_signature,
        }
        if include_arrays:
            result.update(self.signature_payload())
        return result


def _validate_parent_tree(parents: tuple[int, ...]) -> None:
    count = len(parents)
    for index, parent in enumerate(parents):
        if parent < -1 or parent >= count or parent == index:
            raise ValueError(f"parent_indices[{index}] is invalid")
    states = [0] * count
    for start in range(count):
        if states[start] == 2:
            continue
        path = []
        current = start
        while current >= 0 and states[current] == 0:
            states[current] = 1
            path.append(current)
            current = parents[current]
        if current >= 0 and states[current] == 1:
            raise ValueError("parent_indices contains a cycle")
        for index in path:
            states[index] = 2


def _validate_baseline_contract(spec: MC2BaselineStaticSpec) -> None:
    count = spec.vertex_count
    parents = _integers(spec.parent_indices, "parent_indices", count=count)
    _validate_parent_tree(parents)
    children = _integers(spec.child_data, "child_data")
    _validate_vertex_indices((children,), count, "child_data")
    child_ranges = _normalize_ranges(
        spec.child_ranges,
        "child_ranges",
        len(children),
        count=count,
    )
    if spec.child_ranges != child_ranges:
        raise TypeError("child range records must be immutable tuples")
    observed_children = []
    for parent, (start, length) in enumerate(child_ranges):
        for child in children[start:start + length]:
            if parents[child] != parent:
                raise ValueError(
                    f"child_data relation {parent}->{child} disagrees with parent_indices"
                )
            observed_children.append(child)
    expected_children = [
        index for index, parent in enumerate(parents) if parent >= 0
    ]
    if sorted(observed_children) != expected_children:
        raise ValueError("child ranges must contain every non-root vertex exactly once")

    line_data = _integers(spec.baseline_data, "baseline_data")
    _validate_vertex_indices((line_data,), count, "baseline_data")
    if len(set(line_data)) != len(line_data):
        raise ValueError("baseline_data must contain unique vertex indices")
    line_ranges = _normalize_ranges(
        spec.baseline_ranges,
        "baseline_ranges",
        len(line_data),
    )
    if spec.baseline_ranges != line_ranges:
        raise TypeError("baseline range records must be immutable tuples")
    flags = _integers(
        spec.baseline_flags,
        "baseline_flags",
        count=len(line_ranges),
    )
    if any(not 0 <= value <= 0xFF for value in flags):
        raise ValueError("baseline_flags must fit uint8")

    roots = _integers(spec.root_indices, "root_indices", count=count)
    if any(value < -1 or value >= count for value in roots):
        raise ValueError("root_indices contains an invalid vertex index")
    depths = _vectors(((value,) for value in spec.depths), 1, "depths", count=count)
    if any(value[0] < 0.0 or value[0] > 1.0 for value in depths):
        raise ValueError("depths must contain one normalized value per vertex")
    local_positions = _vectors(
        spec.vertex_local_positions,
        3,
        "vertex_local_positions",
        count=count,
    )
    local_rotations = _baseline_quaternions(
        spec.vertex_local_rotations,
        "vertex_local_rotations",
        count=count,
        active_indices=line_data,
    )
    if spec.vertex_local_positions != local_positions:
        raise TypeError("vertex local position records must be immutable tuples")
    if spec.vertex_local_rotations != local_rotations:
        raise TypeError("vertex local rotation records must be immutable tuples")


def make_mc2_baseline_static_spec(
    *,
    proxy_signature: object,
    vertex_count: object,
    parent_indices,
    child_ranges,
    child_data,
    baseline_flags,
    baseline_ranges,
    baseline_data,
    root_indices,
    depths,
    vertex_local_positions,
    vertex_local_rotations,
) -> MC2BaselineStaticSpec:
    if isinstance(vertex_count, bool):
        raise TypeError("vertex_count must be an integer")
    count = int(vertex_count)
    if count != vertex_count:
        raise ValueError("vertex_count must be an exact integer")
    parents = _integers(parent_indices, "parent_indices", count=count)
    _validate_parent_tree(parents)
    children = _integers(child_data, "child_data")
    _validate_vertex_indices((children,), count, "child_data")
    child_range_values = _normalize_ranges(child_ranges, "child_ranges", len(children), count=count)
    observed_children = []
    for parent, (start, length) in enumerate(child_range_values):
        for child in children[start:start + length]:
            if parents[child] != parent:
                raise ValueError(f"child_data relation {parent}->{child} disagrees with parent_indices")
            observed_children.append(child)
    expected_children = [index for index, parent in enumerate(parents) if parent >= 0]
    if sorted(observed_children) != expected_children:
        raise ValueError("child ranges must contain every non-root vertex exactly once")

    line_data = _integers(baseline_data, "baseline_data")
    _validate_vertex_indices((line_data,), count, "baseline_data")
    if len(set(line_data)) != len(line_data):
        raise ValueError("baseline_data must contain unique vertex indices")
    line_ranges = _normalize_ranges(baseline_ranges, "baseline_ranges", len(line_data))
    flags = _integers(baseline_flags, "baseline_flags", count=len(line_ranges))
    if any(not 0 <= value <= 0xFF for value in flags):
        raise ValueError("baseline_flags must fit uint8")

    roots = _integers(root_indices, "root_indices", count=count)
    if any(value < -1 or value >= count for value in roots):
        raise ValueError("root_indices contains an invalid vertex index")
    depth_values = tuple(_finite(value, "depths") for value in _values_or_empty(depths))
    if len(depth_values) != count or any(value < 0.0 or value > 1.0 for value in depth_values):
        raise ValueError("depths must contain one normalized value per vertex")

    payload = {
        "schema_version": MC2_STATIC_SCHEMA_VERSION,
        "proxy_signature": str(proxy_signature or ""),
        "vertex_count": count,
        "parent_indices": parents,
        "child_ranges": child_range_values,
        "child_data": children,
        "baseline_flags": flags,
        "baseline_ranges": line_ranges,
        "baseline_data": line_data,
        "root_indices": roots,
        "depths": depth_values,
        "vertex_local_positions": _vectors(vertex_local_positions, 3, "vertex_local_positions", count=count),
        "vertex_local_rotations": _baseline_quaternions(
            vertex_local_rotations,
            "vertex_local_rotations",
            count=count,
            active_indices=line_data,
        ),
    }
    if not payload["proxy_signature"]:
        raise ValueError("proxy_signature cannot be empty")
    return MC2BaselineStaticSpec(**payload, baseline_signature=_signature(payload))


def pack_mc2_proxy_static(spec: MC2ProxyStaticSpec) -> dict[str, np.ndarray]:
    if not isinstance(spec, MC2ProxyStaticSpec):
        raise TypeError("spec must be MC2ProxyStaticSpec")
    count = spec.vertex_count
    return {
        "local_positions": _readonly_array(spec.local_positions, np.float32, (count, 3)),
        "local_normals": _readonly_array(spec.local_normals, np.float32, (count, 3)),
        "local_tangents": _readonly_array(spec.local_tangents, np.float32, (count, 3)),
        "uvs": _readonly_array(spec.uvs, np.float32, (count, 2)),
        "vertex_attributes": _readonly_array(
            spec.vertex_attributes,
            np.uint8,
            (count,),
        ),
        "edges": _readonly_array(spec.edges, np.int32, (len(spec.edges), 2)),
        "triangles": _readonly_array(spec.triangles, np.int32, (len(spec.triangles), 3)),
    }


def pack_mc2_proxy_finalizer_static(
    spec: MC2ProxyFinalizerStaticSpec,
) -> dict[str, np.ndarray]:
    if not isinstance(spec, MC2ProxyFinalizerStaticSpec):
        raise TypeError("spec must be MC2ProxyFinalizerStaticSpec")
    triangle_ranges = []
    triangle_data = []
    for records in spec.vertex_to_triangle_records:
        triangle_ranges.append((len(triangle_data), len(records)))
        triangle_data.extend(records)
    count = spec.vertex_count
    return {
        "vertex_to_vertex_ranges": _readonly_array(
            spec.vertex_to_vertex_ranges,
            np.int32,
            (count, 2),
        ),
        "vertex_to_vertex_data": _readonly_array(
            spec.vertex_to_vertex_data,
            np.int32,
            (len(spec.vertex_to_vertex_data),),
        ),
        "vertex_to_triangle_ranges": _readonly_array(
            triangle_ranges,
            np.int32,
            (count, 2),
        ),
        "vertex_to_triangle_data": _readonly_array(
            triangle_data,
            np.int32,
            (len(triangle_data), 2),
        ),
        "vertex_bind_pose_positions": _readonly_array(
            spec.vertex_bind_pose_positions,
            np.float32,
            (count, 3),
        ),
        "vertex_bind_pose_rotations": _readonly_array(
            spec.vertex_bind_pose_rotations,
            np.float32,
            (count, 4),
        ),
    }


def pack_mc2_baseline_static(spec: MC2BaselineStaticSpec) -> dict[str, np.ndarray]:
    if not isinstance(spec, MC2BaselineStaticSpec):
        raise TypeError("spec must be MC2BaselineStaticSpec")
    count = spec.vertex_count
    return {
        "parent_indices": _readonly_array(spec.parent_indices, np.int32, (count,)),
        "child_ranges": _readonly_array(spec.child_ranges, np.int32, (count, 2)),
        "child_data": _readonly_array(spec.child_data, np.int32, (len(spec.child_data),)),
        "baseline_flags": _readonly_array(spec.baseline_flags, np.uint8, (len(spec.baseline_flags),)),
        "baseline_ranges": _readonly_array(spec.baseline_ranges, np.int32, (len(spec.baseline_ranges), 2)),
        "baseline_data": _readonly_array(spec.baseline_data, np.int32, (len(spec.baseline_data),)),
        "root_indices": _readonly_array(spec.root_indices, np.int32, (count,)),
        "depths": _readonly_array(spec.depths, np.float32, (count,)),
        "vertex_local_positions": _readonly_array(spec.vertex_local_positions, np.float32, (count, 3)),
        "vertex_local_rotations": _readonly_array(spec.vertex_local_rotations, np.float32, (count, 4)),
    }


__all__ = [
    "MC2BaselineStaticSpec",
    "MC2ProxyFinalizerStaticSpec",
    "MC2ProxyStaticSpec",
    "MC2_STATIC_SCHEMA_VERSION",
    "make_mc2_baseline_static_spec",
    "make_mc2_proxy_finalizer_static_spec",
    "make_mc2_proxy_static_spec",
    "pack_mc2_baseline_static",
    "pack_mc2_proxy_finalizer_static",
    "pack_mc2_proxy_static",
]
