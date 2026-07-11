"""Source-aligned MC2 DistanceConstraint static contract and builder."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from .static_data import MC2BaselineStaticSpec, MC2ProxyStaticSpec


MC2_DISTANCE_STATIC_SCHEMA_VERSION = 1
MC2_VERTEX_FIXED = 0x01
MC2_VERTEX_MOVE = 0x02
MC2_DISTANCE_EPSILON = np.float32(1.0e-8)
MC2_SHEAR_NORMAL_DOT = np.float32(0.9396926)
MC2_SHEAR_LENGTH_RATIO = np.float32(0.3)
MC2_DISTANCE_MAX_RANGE_COUNT = 0xFFF
MC2_DISTANCE_MAX_RANGE_START = 0xFFFFF
MC2_DISTANCE_MAX_TARGET = 0xFFFF


def _signature(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _readonly_array(values, dtype, shape: tuple[int, ...]) -> np.ndarray:
    array = np.ascontiguousarray(values, dtype=dtype).reshape(shape)
    array.flags.writeable = False
    return array


def _exact_int(value, name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be an integer") from exc
    if result != value:
        raise ValueError(f"{name} must be an exact integer")
    return result


def _float32(value, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} cannot be NaN/Inf")
    if abs(number) > float(np.finfo(np.float32).max):
        raise ValueError(f"{name} exceeds finite float32 range")
    result = float(np.float32(number))
    if not math.isfinite(result):
        raise ValueError(f"{name} cannot become NaN/Inf after float32 conversion")
    return 0.0 if result == 0.0 else result


def _is_move(attribute: int) -> bool:
    return bool(attribute & MC2_VERTEX_MOVE)


def _is_invalid(attribute: int) -> bool:
    return not bool(attribute & (MC2_VERTEX_FIXED | MC2_VERTEX_MOVE))


def _canonical_edge(first: int, second: int) -> tuple[int, int]:
    return (first, second) if first < second else (second, first)


def _validate_ordered_adjacency(
    proxy: MC2ProxyStaticSpec,
    ranges,
    data,
) -> tuple[tuple[tuple[int, int], ...], tuple[int, ...]]:
    try:
        frozen_ranges = tuple(
            tuple(_exact_int(value, f"vertex_to_vertex_ranges[{index}]") for value in record)
            for index, record in enumerate(ranges)
        )
        frozen_data = tuple(
            _exact_int(value, f"vertex_to_vertex_data[{index}]")
            for index, value in enumerate(data)
        )
    except (TypeError, ValueError) as exc:
        raise TypeError("vertex adjacency must contain exact integers") from exc
    if len(frozen_ranges) != proxy.vertex_count:
        raise ValueError("vertex_to_vertex_ranges length must equal vertex_count")
    edge_set = set(proxy.edges)
    cursor = 0
    directed = set()
    for vertex, record in enumerate(frozen_ranges):
        if len(record) != 2:
            raise ValueError(f"vertex_to_vertex_ranges[{vertex}] must contain 2 values")
        start, count = record
        if start != cursor or count < 0:
            raise ValueError("vertex_to_vertex_ranges must form dense non-negative ranges")
        if count > MC2_DISTANCE_MAX_RANGE_COUNT:
            raise ValueError("vertex adjacency count exceeds MC2 12-bit source limit")
        if start > MC2_DISTANCE_MAX_RANGE_START:
            raise ValueError("vertex adjacency start exceeds MC2 20-bit source limit")
        targets = frozen_data[start:start + count]
        if len(targets) != count:
            raise ValueError("vertex_to_vertex_ranges exceed vertex_to_vertex_data")
        if len(set(targets)) != count:
            raise ValueError(f"vertex {vertex} adjacency contains duplicate targets")
        for target in targets:
            if not 0 <= target < proxy.vertex_count:
                raise ValueError(f"vertex adjacency target {target} is out of range")
            if target > MC2_DISTANCE_MAX_TARGET:
                raise ValueError("vertex adjacency target exceeds MC2 ushort source limit")
            if target == vertex:
                raise ValueError("vertex adjacency cannot contain self edges")
            if _canonical_edge(vertex, target) not in edge_set:
                raise ValueError("vertex adjacency contains an edge absent from final proxy")
            directed.add((vertex, target))
        cursor += count
    if cursor != len(frozen_data):
        raise ValueError("vertex adjacency ranges do not cover all data")
    if any((target, source) not in directed for source, target in directed):
        raise ValueError("final proxy vertex adjacency must be bidirectional")
    return frozen_ranges, frozen_data


def _triangle_edges(triangle: tuple[int, int, int]):
    return (
        _canonical_edge(triangle[0], triangle[1]),
        _canonical_edge(triangle[1], triangle[2]),
        _canonical_edge(triangle[2], triangle[0]),
    )


def _edge_to_triangles(triangles):
    result: dict[tuple[int, int], list[int]] = {}
    for triangle_index, triangle in enumerate(triangles):
        for edge in _triangle_edges(triangle):
            result.setdefault(edge, []).append(triangle_index)
    return result


def _opposite_vertex(triangle, edge: tuple[int, int]) -> int:
    for vertex in triangle:
        if vertex not in edge:
            return vertex
    raise ValueError("triangle has no opposite vertex for edge")


def _triangle_normal(positions: np.ndarray, triangle, edge: tuple[int, int]) -> np.ndarray:
    opposite = _opposite_vertex(triangle, edge)
    normal = np.cross(
        positions[edge[1]] - positions[edge[0]],
        positions[opposite] - positions[edge[0]],
    ).astype(np.float32)
    length = np.float32(np.linalg.norm(normal))
    if length < MC2_DISTANCE_EPSILON:
        return np.zeros(3, dtype=np.float32)
    return (normal / length).astype(np.float32)


@dataclass(frozen=True)
class MC2DistanceStaticSpec:
    proxy_signature: str
    baseline_signature: str
    vertex_count: int
    distance_ranges: tuple[tuple[int, int], ...]
    distance_targets: tuple[int, ...]
    distance_rest_signed: tuple[float, ...]
    distance_signature: str
    schema_version: int = MC2_DISTANCE_STATIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MC2_DISTANCE_STATIC_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 Distance static schema")
        if not self.proxy_signature or not self.baseline_signature:
            raise ValueError("proxy_signature and baseline_signature are required")
        if not 0 < self.vertex_count <= MC2_DISTANCE_MAX_TARGET + 1:
            raise ValueError("vertex_count exceeds MC2 ushort target domain")
        if not isinstance(self.distance_ranges, tuple):
            raise TypeError("distance_ranges must be an immutable tuple")
        if not isinstance(self.distance_targets, tuple):
            raise TypeError("distance_targets must be an immutable tuple")
        if not isinstance(self.distance_rest_signed, tuple):
            raise TypeError("distance_rest_signed must be an immutable tuple")
        if len(self.distance_ranges) != self.vertex_count:
            raise ValueError("distance_ranges length must equal vertex_count")
        if len(self.distance_targets) != len(self.distance_rest_signed):
            raise ValueError("Distance target/rest arrays must have equal length")
        cursor = 0
        for index, record in enumerate(self.distance_ranges):
            if not isinstance(record, tuple) or len(record) != 2:
                raise TypeError(f"distance_ranges[{index}] must be an immutable int2")
            start, count = record
            if any(isinstance(value, bool) or not isinstance(value, int) for value in record):
                raise TypeError(f"distance_ranges[{index}] must contain integers")
            if start != cursor or count < 0:
                raise ValueError("distance_ranges must form dense non-negative ranges")
            if count > MC2_DISTANCE_MAX_RANGE_COUNT:
                raise ValueError("Distance range count exceeds MC2 12-bit source limit")
            if start > MC2_DISTANCE_MAX_RANGE_START:
                raise ValueError("Distance range start exceeds MC2 20-bit source limit")
            cursor += count
        if cursor != len(self.distance_targets):
            raise ValueError("distance_ranges do not cover Distance data arrays")
        for index, target in enumerate(self.distance_targets):
            if isinstance(target, bool) or not isinstance(target, int):
                raise TypeError(f"distance_targets[{index}] must be an integer")
            if not 0 <= target < self.vertex_count:
                raise ValueError(f"distance_targets[{index}] is out of range")
            if target > MC2_DISTANCE_MAX_TARGET:
                raise ValueError("Distance target exceeds MC2 ushort source limit")
        for index, rest in enumerate(self.distance_rest_signed):
            if not math.isfinite(rest):
                raise ValueError(f"distance_rest_signed[{index}] cannot be NaN/Inf")
            if rest == 0.0 and math.copysign(1.0, rest) < 0.0:
                raise ValueError("Distance zero rest must use source +0.0 encoding")
        if self.distance_signature != _signature(self.signature_payload()):
            raise ValueError("distance_signature does not match Distance static payload")

    def signature_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "proxy_signature": self.proxy_signature,
            "baseline_signature": self.baseline_signature,
            "vertex_count": self.vertex_count,
            "distance_ranges": self.distance_ranges,
            "distance_targets": self.distance_targets,
            "distance_rest_signed": self.distance_rest_signed,
        }

    def debug_dict(self, *, include_arrays: bool = False) -> dict:
        result = {
            "schema_version": self.schema_version,
            "vertex_count": self.vertex_count,
            "record_count": len(self.distance_targets),
            "distance_signature": self.distance_signature,
        }
        if include_arrays:
            result.update(self.signature_payload())
        return result


def make_mc2_distance_static_spec(
    *,
    proxy_signature,
    baseline_signature,
    vertex_count,
    distance_ranges,
    distance_targets,
    distance_rest_signed,
) -> MC2DistanceStaticSpec:
    count = _exact_int(vertex_count, "vertex_count")
    ranges = tuple(
        tuple(_exact_int(value, f"distance_ranges[{index}]") for value in record)
        for index, record in enumerate(distance_ranges)
    )
    targets = tuple(
        _exact_int(value, f"distance_targets[{index}]")
        for index, value in enumerate(distance_targets)
    )
    rests = tuple(
        _float32(value, f"distance_rest_signed[{index}]")
        for index, value in enumerate(distance_rest_signed)
    )
    payload = {
        "schema_version": MC2_DISTANCE_STATIC_SCHEMA_VERSION,
        "proxy_signature": str(proxy_signature or ""),
        "baseline_signature": str(baseline_signature or ""),
        "vertex_count": count,
        "distance_ranges": ranges,
        "distance_targets": targets,
        "distance_rest_signed": rests,
    }
    return MC2DistanceStaticSpec(
        **payload,
        distance_signature=_signature(payload),
    )


def build_mc2_distance_static(
    proxy: MC2ProxyStaticSpec,
    baseline: MC2BaselineStaticSpec,
    *,
    vertex_to_vertex_ranges,
    vertex_to_vertex_data,
) -> MC2DistanceStaticSpec:
    if not isinstance(proxy, MC2ProxyStaticSpec):
        raise TypeError("proxy must be MC2ProxyStaticSpec")
    if not isinstance(baseline, MC2BaselineStaticSpec):
        raise TypeError("baseline must be MC2BaselineStaticSpec")
    if baseline.proxy_signature != proxy.proxy_signature:
        raise ValueError("baseline must be derived from the provided final proxy")
    if baseline.vertex_count != proxy.vertex_count:
        raise ValueError("baseline vertex_count must equal proxy vertex_count")
    if proxy.vertex_count > MC2_DISTANCE_MAX_TARGET + 1:
        raise ValueError("MC2 Distance supports at most 65536 proxy vertices")
    parents = baseline.parent_indices
    adjacency_ranges, adjacency_data = _validate_ordered_adjacency(
        proxy,
        vertex_to_vertex_ranges,
        vertex_to_vertex_data,
    )
    attributes = proxy.vertex_attributes
    vertical = [[] for _ in range(proxy.vertex_count)]
    ordinary_horizontal = [[] for _ in range(proxy.vertex_count)]
    shear_insertions = [[] for _ in range(proxy.vertex_count)]
    connected: set[tuple[int, int]] = set()

    for vertex, (start, count) in enumerate(adjacency_ranges):
        attribute = attributes[vertex]
        parent = parents[vertex]
        for target in adjacency_data[start:start + count]:
            target_attribute = attributes[target]
            if not _is_move(attribute) and not _is_move(target_attribute):
                continue
            if _is_invalid(attribute) or _is_invalid(target_attribute):
                continue
            if target == parent or vertex == parents[target]:
                vertical[vertex].append(target)
            else:
                ordinary_horizontal[vertex].append(target)
            connected.add(_canonical_edge(vertex, target))

    positions = np.asarray(proxy.local_positions, dtype=np.float32)
    edge_triangles = _edge_to_triangles(proxy.triangles)
    for edge in proxy.edges:
        triangle_indices = edge_triangles.get(edge, ())
        if len(triangle_indices) < 2:
            continue
        shared_length = np.float32(np.linalg.norm(positions[edge[0]] - positions[edge[1]]))
        if shared_length < MC2_DISTANCE_EPSILON:
            continue
        for first_offset, first_index in enumerate(triangle_indices[:-1]):
            first_triangle = proxy.triangles[first_index]
            first_opposite = _opposite_vertex(first_triangle, edge)
            first_normal = _triangle_normal(positions, first_triangle, edge)
            for second_index in triangle_indices[first_offset + 1:]:
                second_triangle = proxy.triangles[second_index]
                second_opposite = _opposite_vertex(second_triangle, edge)
                if (
                    not _is_move(attributes[first_opposite])
                    and not _is_move(attributes[second_opposite])
                ):
                    continue
                second_normal = _triangle_normal(positions, second_triangle, edge)
                normal_dot = np.float32(abs(np.dot(first_normal, second_normal)))
                if normal_dot < MC2_SHEAR_NORMAL_DOT:
                    continue
                opposite_length = np.float32(
                    np.linalg.norm(positions[first_opposite] - positions[second_opposite])
                )
                ratio = np.float32(abs(opposite_length / shared_length - np.float32(1.0)))
                if ratio > MC2_SHEAR_LENGTH_RATIO:
                    continue
                candidate = _canonical_edge(first_opposite, second_opposite)
                if candidate in connected:
                    continue
                connected.add(candidate)
                shear_insertions[first_opposite].append(second_opposite)
                shear_insertions[second_opposite].append(first_opposite)

    ranges = []
    targets = []
    rests = []
    for vertex in range(proxy.vertex_count):
        start = len(targets)
        ordered_vertical = vertical[vertex]
        ordered_horizontal = list(reversed(shear_insertions[vertex]))
        ordered_horizontal.extend(ordinary_horizontal[vertex])
        for target in ordered_vertical:
            distance = np.float32(np.linalg.norm(positions[vertex] - positions[target]))
            targets.append(target)
            rests.append(0.0 if distance < MC2_DISTANCE_EPSILON else float(distance))
        for target in ordered_horizontal:
            distance = np.float32(np.linalg.norm(positions[vertex] - positions[target]))
            targets.append(target)
            rests.append(0.0 if distance < MC2_DISTANCE_EPSILON else -float(distance))
        ranges.append((start, len(targets) - start))

    return make_mc2_distance_static_spec(
        proxy_signature=proxy.proxy_signature,
        baseline_signature=baseline.baseline_signature,
        vertex_count=proxy.vertex_count,
        distance_ranges=ranges,
        distance_targets=targets,
        distance_rest_signed=rests,
    )


def pack_mc2_distance_static(spec: MC2DistanceStaticSpec) -> dict[str, np.ndarray]:
    if not isinstance(spec, MC2DistanceStaticSpec):
        raise TypeError("spec must be MC2DistanceStaticSpec")
    return {
        "distance_ranges": _readonly_array(
            spec.distance_ranges,
            np.int32,
            (spec.vertex_count, 2),
        ),
        "distance_targets": _readonly_array(
            spec.distance_targets,
            np.int32,
            (len(spec.distance_targets),),
        ),
        "distance_rest_signed": _readonly_array(
            spec.distance_rest_signed,
            np.float32,
            (len(spec.distance_rest_signed),),
        ),
    }


__all__ = [
    "MC2_DISTANCE_STATIC_SCHEMA_VERSION",
    "MC2DistanceStaticSpec",
    "build_mc2_distance_static",
    "make_mc2_distance_static_spec",
    "pack_mc2_distance_static",
]
