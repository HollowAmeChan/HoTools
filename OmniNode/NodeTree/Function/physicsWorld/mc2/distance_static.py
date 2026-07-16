"""Source-aligned MC2 DistanceConstraint static contract and builder."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import numpy as np

from .static_data import MC2BaselineStaticSpec, MC2ProxyStaticSpec


MC2_DISTANCE_STATIC_SCHEMA_VERSION = 1
MC2_DISTANCE_MAX_RANGE_COUNT = 0xFFF
MC2_DISTANCE_MAX_RANGE_START = 0xFFFFF
MC2_DISTANCE_MAX_TARGET = 0xFFFF


def _content_signature(
    *,
    proxy_signature,
    baseline_signature,
    vertex_count,
    distance_ranges,
    distance_targets,
    distance_rest_signed,
) -> str:
    record_count = np.asarray(distance_targets).size
    digest = hashlib.sha256(b"mc2_distance_static_v1\0")
    digest.update(str(proxy_signature or "").encode("ascii"))
    digest.update(str(baseline_signature or "").encode("ascii"))
    digest.update(np.asarray((vertex_count, record_count), dtype=np.int64).tobytes())
    for values, dtype in (
        (distance_ranges, np.int32),
        (distance_targets, np.int32),
        (distance_rest_signed, np.float32),
    ):
        digest.update(np.ascontiguousarray(values, dtype=dtype).tobytes())
    return digest.hexdigest()


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
        if self.distance_signature != _content_signature(
            proxy_signature=self.proxy_signature,
            baseline_signature=self.baseline_signature,
            vertex_count=self.vertex_count,
            distance_ranges=self.distance_ranges,
            distance_targets=self.distance_targets,
            distance_rest_signed=self.distance_rest_signed,
        ):
            raise ValueError("distance_signature does not match Distance static payload")

    @property
    def record_count(self) -> int:
        return len(self.distance_targets)

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
            "record_count": self.record_count,
            "distance_signature": self.distance_signature,
        }
        if include_arrays:
            result.update(self.signature_payload())
        return result


@dataclass(frozen=True)
class MC2DistanceStaticMetadata:
    proxy_signature: str
    baseline_signature: str
    vertex_count: int
    record_count: int
    distance_signature: str
    schema_version: int = MC2_DISTANCE_STATIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MC2_DISTANCE_STATIC_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 Distance static schema")
        if not self.proxy_signature or not self.baseline_signature or not self.distance_signature:
            raise ValueError("Distance signatures cannot be empty")
        if not 0 < self.vertex_count <= MC2_DISTANCE_MAX_TARGET + 1:
            raise ValueError("vertex_count exceeds MC2 ushort target domain")
        if self.record_count < 0:
            raise ValueError("Distance record_count cannot be negative")

    def debug_dict(self, *, include_arrays: bool = False) -> dict:
        if include_arrays:
            raise ValueError("native-owned Distance metadata has no host arrays")
        return {
            "schema_version": self.schema_version,
            "vertex_count": self.vertex_count,
            "record_count": self.record_count,
            "distance_signature": self.distance_signature,
            "native_owned": True,
        }


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
        distance_signature=_content_signature(
            proxy_signature=payload["proxy_signature"],
            baseline_signature=payload["baseline_signature"],
            vertex_count=payload["vertex_count"],
            distance_ranges=payload["distance_ranges"],
            distance_targets=payload["distance_targets"],
            distance_rest_signed=payload["distance_rest_signed"],
        ),
    )


def build_mc2_distance_static(
    proxy: MC2ProxyStaticSpec,
    baseline: MC2BaselineStaticSpec,
    *,
    vertex_to_vertex_ranges,
    vertex_to_vertex_data,
    native_context=None,
) -> MC2DistanceStaticSpec | MC2DistanceStaticMetadata:
    if not isinstance(proxy, MC2ProxyStaticSpec):
        raise TypeError("proxy must be MC2ProxyStaticSpec")
    if not isinstance(baseline, MC2BaselineStaticSpec) and not bool(
        getattr(baseline, "native_owned", False)
    ):
        raise TypeError("baseline must be an MC2 baseline static result")
    if baseline.proxy_signature != proxy.proxy_signature:
        raise ValueError("baseline must be derived from the provided final proxy")
    if baseline.vertex_count != proxy.vertex_count:
        raise ValueError("baseline vertex_count must equal proxy vertex_count")
    if proxy.vertex_count > MC2_DISTANCE_MAX_TARGET + 1:
        raise ValueError("MC2 Distance supports at most 65536 proxy vertices")
    from .native import native_module

    derived = native_module().mc2_build_distance_derived_v0(
        np.ascontiguousarray(proxy.local_positions, dtype=np.float64),
        np.ascontiguousarray(proxy.vertex_attributes, dtype=np.uint8),
        np.ascontiguousarray(baseline.parent_indices, dtype=np.int32),
        np.ascontiguousarray(proxy.edges, dtype=np.int32).reshape((-1, 2)),
        np.ascontiguousarray(proxy.triangles, dtype=np.int32).reshape((-1, 3)),
        np.ascontiguousarray(vertex_to_vertex_ranges, dtype=np.int32).reshape((-1, 2)),
        np.ascontiguousarray(vertex_to_vertex_data, dtype=np.int32),
    )
    if native_context is not None:
        metadata = MC2DistanceStaticMetadata(
            proxy_signature=proxy.proxy_signature,
            baseline_signature=baseline.baseline_signature,
            vertex_count=proxy.vertex_count,
            record_count=len(derived["distance_targets"]),
            distance_signature=_content_signature(
                proxy_signature=proxy.proxy_signature,
                baseline_signature=baseline.baseline_signature,
                vertex_count=proxy.vertex_count,
                distance_ranges=derived["distance_ranges"],
                distance_targets=derived["distance_targets"],
                distance_rest_signed=derived["distance_rest_signed"],
            ),
        )
        native_context.update_distance_derived(derived)
        return metadata

    return make_mc2_distance_static_spec(
        proxy_signature=proxy.proxy_signature,
        baseline_signature=baseline.baseline_signature,
        vertex_count=proxy.vertex_count,
        distance_ranges=derived["distance_ranges"],
        distance_targets=derived["distance_targets"],
        distance_rest_signed=derived["distance_rest_signed"],
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
    "MC2DistanceStaticMetadata",
    "MC2DistanceStaticSpec",
    "build_mc2_distance_static",
    "make_mc2_distance_static_spec",
    "pack_mc2_distance_static",
]
