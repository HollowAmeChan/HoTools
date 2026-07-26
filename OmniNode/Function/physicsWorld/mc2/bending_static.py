"""Source-aligned MC2 TriangleBendingConstraint static contract and builder."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import numpy as np

from .static_data import MC2ProxyStaticSpec


MC2_BENDING_STATIC_SCHEMA_VERSION = 1
MC2_BENDING_MAX_INDEX = 0xFFFF
MC2_VOLUME_MARKER = 100

_IDENTITY_COLUMNS = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def _content_signature(
    *,
    proxy_signature,
    vertex_count,
    initial_local_to_world_columns,
    bending_quads,
    bending_rest_angle_or_volume,
    bending_sign_or_volume,
) -> str:
    digest = hashlib.sha256(b"mc2_bending_static_v1\0")
    digest.update(str(proxy_signature or "").encode("ascii"))
    digest.update(np.asarray((vertex_count,), dtype=np.int64).tobytes())
    digest.update(
        np.asarray((np.asarray(bending_rest_angle_or_volume).size,), dtype=np.int64).tobytes()
    )
    for values, dtype in (
        (initial_local_to_world_columns, np.float32),
        (bending_quads, np.int32),
        (bending_rest_angle_or_volume, np.float32),
        (bending_sign_or_volume, np.int8),
    ):
        digest.update(np.ascontiguousarray(values, dtype=dtype).tobytes())
    return digest.hexdigest()


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
        if self.bending_signature != _content_signature(
            proxy_signature=self.proxy_signature,
            vertex_count=self.vertex_count,
            initial_local_to_world_columns=self.initial_local_to_world_columns,
            bending_quads=self.bending_quads,
            bending_rest_angle_or_volume=self.bending_rest_angle_or_volume,
            bending_sign_or_volume=self.bending_sign_or_volume,
        ):
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
        bending_signature=_content_signature(
            proxy_signature=payload["proxy_signature"],
            vertex_count=payload["vertex_count"],
            initial_local_to_world_columns=payload["initial_local_to_world_columns"],
            bending_quads=payload["bending_quads"],
            bending_rest_angle_or_volume=payload["bending_rest_angle_or_volume"],
            bending_sign_or_volume=payload["bending_sign_or_volume"],
        ),
    )


def build_mc2_bending_static(
    proxy: MC2ProxyStaticSpec,
    *,
    initial_local_to_world_columns=None,
) -> MC2BendingStaticSpec | None:
    if not isinstance(proxy, MC2ProxyStaticSpec) and not bool(
        getattr(proxy, "native_owned", False)
    ):
        raise TypeError("proxy must be an MC2 proxy static result")
    if proxy.vertex_count > MC2_BENDING_MAX_INDEX + 1:
        raise ValueError("MC2 Bending supports at most 65536 proxy vertices")
    if len(proxy.edges) == 0 or len(proxy.triangles) == 0:
        return None

    columns = _matrix_columns(initial_local_to_world_columns)
    from .native import native_module

    derived = native_module().mc2_build_bending_derived(
        np.ascontiguousarray(proxy.local_positions, dtype=np.float32),
        np.ascontiguousarray(proxy.vertex_attributes, dtype=np.uint8),
        np.ascontiguousarray(proxy.edges, dtype=np.int32).reshape((-1, 2)),
        np.ascontiguousarray(proxy.triangles, dtype=np.int32).reshape((-1, 3)),
        np.ascontiguousarray(columns, dtype=np.float32),
    )
    return make_mc2_bending_static_spec(
        proxy_signature=proxy.proxy_signature,
        vertex_count=proxy.vertex_count,
        initial_local_to_world_columns=columns,
        bending_quads=derived["bending_quads"],
        bending_rest_angle_or_volume=derived["bending_rest_angle_or_volume"],
        bending_sign_or_volume=derived["bending_sign_or_volume"],
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
