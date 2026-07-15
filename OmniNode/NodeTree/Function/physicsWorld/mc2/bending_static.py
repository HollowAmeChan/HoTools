"""Source-aligned MC2 TriangleBendingConstraint static contract and builder."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from ..utils.math3d import (
    normalize_vector_squared_f32,
    transform_points_columns_f32 as _transform_positions,
)
from .static_data import MC2ProxyStaticSpec


MC2_BENDING_STATIC_SCHEMA_VERSION = 1
MC2_BENDING_MAX_INDEX = 0xFFFF
MC2_BENDING_MAX_ANGLE_DEGREES = 120.0
MC2_VOLUME_MIN_ANGLE_DEGREES = 90.0
MC2_VOLUME_MAX_ANGLE_DEGREES = 179.0
MC2_VOLUME_MARKER = 100

_IDENTITY_COLUMNS = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def _signature(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
    if not math.isfinite(number) or abs(number) > float(np.finfo(np.float32).max):
        raise ValueError(f"{name} must fit finite float32")
    result = float(np.float32(number))
    if not math.isfinite(result):
        raise ValueError(f"{name} cannot become NaN/Inf after float32 conversion")
    return 0.0 if result == 0.0 else result


def _matrix_columns(values) -> tuple[tuple[float, float, float, float], ...]:
    source = _IDENTITY_COLUMNS if values is None else values
    try:
        columns = tuple(tuple(column) for column in source)
    except TypeError as exc:
        raise TypeError("initial_local_to_world_columns must be a 4x4 matrix") from exc
    if len(columns) != 4 or any(len(column) != 4 for column in columns):
        raise ValueError("initial_local_to_world_columns must be a 4x4 matrix")
    return tuple(
        tuple(
            _float32(value, f"initial_local_to_world_columns[{column_index}][{row_index}]")
            for row_index, value in enumerate(column)
        )
        for column_index, column in enumerate(columns)
    )


def _readonly_array(values, dtype, shape: tuple[int, ...]) -> np.ndarray:
    array = np.ascontiguousarray(values, dtype=dtype).reshape(shape)
    array.flags.writeable = False
    return array


def _is_move(attribute: int) -> bool:
    return bool(attribute & 0x02)


def _is_invalid(attribute: int) -> bool:
    return not bool(attribute & 0x03)


def _triangle_edges(triangle: tuple[int, int, int]):
    def edge(first: int, second: int):
        return (first, second) if first < second else (second, first)

    return (
        edge(triangle[0], triangle[1]),
        edge(triangle[1], triangle[2]),
        edge(triangle[2], triangle[0]),
    )


def _edge_to_triangles(triangles) -> dict[tuple[int, int], list[int]]:
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


def _normalize(vector: np.ndarray, name: str) -> np.ndarray:
    return normalize_vector_squared_f32(
        vector,
        error_message=f"{name} is degenerate",
    )


def _angle_and_sign(positions: np.ndarray, quad: tuple[int, int, int, int]):
    p0, p1, p2, p3 = (positions[index] for index in quad)
    normal0 = _normalize(
        np.cross(p2 - p0, p3 - p0).astype(np.float32),
        "TriangleBending first triangle",
    )
    normal1 = _normalize(
        np.cross(p3 - p1, p2 - p1).astype(np.float32),
        "TriangleBending second triangle",
    )
    cosine = np.float32(np.clip(np.dot(normal0, normal1), -1.0, 1.0))
    angle = np.float32(np.arccos(cosine))
    direction = np.float32(
        np.dot(
            np.cross(normal0, normal1).astype(np.float32),
            p3 - p2,
        )
    )
    return angle, (-1 if direction < np.float32(0.0) else 1)


def _signed_volume(world_positions: np.ndarray, quad) -> float:
    p0, p1, p2, p3 = (world_positions[index] for index in quad)
    cross = np.cross(p1 - p0, p2 - p0).astype(np.float32)
    six_volume = np.float32(np.dot(cross, p3 - p0))
    return float(
        np.float32(
            np.float32(six_volume / np.float32(6.0)) * np.float32(1000.0)
        )
    )


@dataclass(frozen=True)
class MC2BendingStaticSpec:
    proxy_signature: str
    vertex_count: int
    initial_local_to_world_columns: tuple[tuple[float, float, float, float], ...]
    bending_quads: tuple[tuple[int, int, int, int], ...]
    bending_rest_angle_or_volume: tuple[float, ...]
    bending_sign_or_volume: tuple[int, ...]
    bending_signature: str
    schema_version: int = MC2_BENDING_STATIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MC2_BENDING_STATIC_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 Bending static schema")
        if not self.proxy_signature:
            raise ValueError("proxy_signature is required")
        if not 0 < self.vertex_count <= MC2_BENDING_MAX_INDEX + 1:
            raise ValueError("vertex_count exceeds MC2 ushort domain")
        if self.initial_local_to_world_columns != _matrix_columns(
            self.initial_local_to_world_columns
        ):
            raise TypeError("initial transform must be immutable float32 columns")
        arrays = (
            self.bending_quads,
            self.bending_rest_angle_or_volume,
            self.bending_sign_or_volume,
        )
        if any(not isinstance(values, tuple) for values in arrays):
            raise TypeError("MC2 Bending static arrays must be immutable tuples")
        if len({len(values) for values in arrays}) != 1:
            raise ValueError("MC2 Bending static arrays must have equal length")
        for record_index, quad in enumerate(self.bending_quads):
            if not isinstance(quad, tuple) or len(quad) != 4:
                raise TypeError(f"bending_quads[{record_index}] must be an immutable int4")
            if len(set(quad)) != 4:
                raise ValueError(f"bending_quads[{record_index}] must contain four roles")
            for vertex in quad:
                if isinstance(vertex, bool) or not isinstance(vertex, int):
                    raise TypeError(f"bending_quads[{record_index}] must contain integers")
                if not 0 <= vertex < self.vertex_count or vertex > MC2_BENDING_MAX_INDEX:
                    raise ValueError(f"bending_quads[{record_index}] index is out of range")
        for index, rest in enumerate(self.bending_rest_angle_or_volume):
            if not math.isfinite(rest):
                raise ValueError(f"bending_rest_angle_or_volume[{index}] must be finite")
        if any(value not in (-1, 1, MC2_VOLUME_MARKER) for value in self.bending_sign_or_volume):
            raise ValueError("bending_sign_or_volume only accepts -1, 1, or 100")
        if self.bending_signature != _signature(self.signature_payload()):
            raise ValueError("bending_signature does not match Bending static payload")

    @property
    def record_count(self) -> int:
        return len(self.bending_quads)

    def signature_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "proxy_signature": self.proxy_signature,
            "vertex_count": self.vertex_count,
            "initial_local_to_world_columns": self.initial_local_to_world_columns,
            "bending_quads": self.bending_quads,
            "bending_rest_angle_or_volume": self.bending_rest_angle_or_volume,
            "bending_sign_or_volume": self.bending_sign_or_volume,
        }

    def debug_dict(self, *, include_arrays: bool = False) -> dict:
        result = {
            "schema_version": self.schema_version,
            "vertex_count": self.vertex_count,
            "record_count": self.record_count,
            "bending_signature": self.bending_signature,
        }
        if include_arrays:
            result.update(self.signature_payload())
        return result


def make_mc2_bending_static_spec(
    *,
    proxy_signature,
    vertex_count,
    initial_local_to_world_columns=None,
    bending_quads=(),
    bending_rest_angle_or_volume=(),
    bending_sign_or_volume=(),
) -> MC2BendingStaticSpec:
    count = _exact_int(vertex_count, "vertex_count")
    quads = tuple(
        tuple(_exact_int(value, f"bending_quads[{index}]") for value in quad)
        for index, quad in enumerate(bending_quads)
    )
    rests = tuple(
        _float32(value, f"bending_rest_angle_or_volume[{index}]")
        for index, value in enumerate(bending_rest_angle_or_volume)
    )
    markers = tuple(
        _exact_int(value, f"bending_sign_or_volume[{index}]")
        for index, value in enumerate(bending_sign_or_volume)
    )
    payload = {
        "schema_version": MC2_BENDING_STATIC_SCHEMA_VERSION,
        "proxy_signature": str(proxy_signature or ""),
        "vertex_count": count,
        "initial_local_to_world_columns": _matrix_columns(
            initial_local_to_world_columns
        ),
        "bending_quads": quads,
        "bending_rest_angle_or_volume": rests,
        "bending_sign_or_volume": markers,
    }
    return MC2BendingStaticSpec(
        **payload,
        bending_signature=_signature(payload),
    )


def build_mc2_bending_static(
    proxy: MC2ProxyStaticSpec,
    *,
    initial_local_to_world_columns=None,
) -> MC2BendingStaticSpec | None:
    if not isinstance(proxy, MC2ProxyStaticSpec):
        raise TypeError("proxy must be MC2ProxyStaticSpec")
    if proxy.vertex_count > MC2_BENDING_MAX_INDEX + 1:
        raise ValueError("MC2 Bending supports at most 65536 proxy vertices")
    if not proxy.edges or not proxy.triangles:
        return None

    columns = _matrix_columns(initial_local_to_world_columns)
    positions = np.asarray(proxy.local_positions, dtype=np.float32)
    world_positions = _transform_positions(positions, columns)
    edge_triangles = _edge_to_triangles(proxy.triangles)
    attributes = proxy.vertex_attributes
    quads = []
    rests = []
    markers = []
    volume_keys: set[tuple[int, int, int, int]] = set()

    for edge in proxy.edges:
        # NativeParallelMultiHashMap returns the latest insertion first for the
        # fixed source baseline used by the Tier A raw-order fixtures.
        triangle_indices = tuple(reversed(edge_triangles.get(edge, ())))
        for first_offset, first_index in enumerate(triangle_indices[:-1]):
            first_triangle = proxy.triangles[first_index]
            first_opposite = _opposite_vertex(first_triangle, edge)
            for second_index in triangle_indices[first_offset + 1:]:
                second_triangle = proxy.triangles[second_index]
                second_opposite = _opposite_vertex(second_triangle, edge)
                quad = (first_opposite, second_opposite, edge[0], edge[1])
                quad_attributes = tuple(attributes[index] for index in quad)
                if not any(_is_move(value) for value in quad_attributes):
                    continue
                if any(_is_invalid(value) for value in quad_attributes):
                    continue

                angle, sign = _angle_and_sign(positions, quad)
                angle_degrees = math.degrees(float(abs(angle)))
                if angle_degrees < MC2_BENDING_MAX_ANGLE_DEGREES:
                    quads.append(quad)
                    rests.append(float(angle))
                    markers.append(sign)

                volume_key = tuple(sorted(quad))
                if (
                    MC2_VOLUME_MIN_ANGLE_DEGREES
                    <= angle_degrees
                    <= MC2_VOLUME_MAX_ANGLE_DEGREES
                    and volume_key not in volume_keys
                ):
                    volume_keys.add(volume_key)
                    quads.append(quad)
                    rests.append(_signed_volume(world_positions, quad))
                    markers.append(MC2_VOLUME_MARKER)

    return make_mc2_bending_static_spec(
        proxy_signature=proxy.proxy_signature,
        vertex_count=proxy.vertex_count,
        initial_local_to_world_columns=columns,
        bending_quads=quads,
        bending_rest_angle_or_volume=rests,
        bending_sign_or_volume=markers,
    )


def pack_mc2_bending_static(spec: MC2BendingStaticSpec) -> dict[str, np.ndarray]:
    if not isinstance(spec, MC2BendingStaticSpec):
        raise TypeError("spec must be MC2BendingStaticSpec")
    count = spec.record_count
    return {
        "bending_quads": _readonly_array(spec.bending_quads, np.int32, (count, 4)),
        "bending_rest_angle_or_volume": _readonly_array(
            spec.bending_rest_angle_or_volume,
            np.float32,
            (count,),
        ),
        "bending_sign_or_volume": _readonly_array(
            spec.bending_sign_or_volume,
            np.int8,
            (count,),
        ),
    }


__all__ = [
    "MC2_BENDING_STATIC_SCHEMA_VERSION",
    "MC2BendingStaticSpec",
    "build_mc2_bending_static",
    "make_mc2_bending_static_spec",
    "pack_mc2_bending_static",
]
