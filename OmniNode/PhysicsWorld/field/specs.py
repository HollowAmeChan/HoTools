"""不可变且不依赖 Blender 的 Field 创作值与快照契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Iterable

import numpy as np

from ..collision.groups import COLLISION_GROUP_COUNT
from .diagnostics import FieldDiagnosticV0

from .names import (
    AIR_VELOCITY_CHANNEL_ID,
    BOX_ATTENUATION_POLICY_V0,
    FIELD_ABI_VERSION,
    FIELD_STATUSES,
    FIELD_STATUS_PREVIEW_ONLY,
    FIELD_TYPE_WIND,
    FIELD_TYPES_V0,
    SPHERE_ATTENUATION_POLICY_V0,
    VOLUME_ATTENUATION_POLICY_VERSION,
    VOLUME_SHAPES_V0,
    VOLUME_SHAPE_BOX,
    VOLUME_SHAPE_SPHERE,
    WIND_GENERATOR_ID,
    WIND_NOISE_ALGORITHM_VERSION,
)


IDENTITY_MATRIX4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def _stable_signature(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _finite_float(
    name: str,
    value: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} 必须是有限浮点数") from None
    if not math.isfinite(result):
        raise ValueError(f"{name} 必须是有限浮点数")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} 必须 >= {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} 必须 <= {maximum}")
    return result


def _strict_int(
    name: str,
    value: Any,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是整数")
    try:
        result = int(value)
        if float(value) != float(result):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} 必须是整数") from None
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} 必须 >= {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} 必须 <= {maximum}")
    return result


def _string_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = (values,)
    normalized = []
    seen = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return tuple(sorted(normalized))


def _matrix4(value: Any) -> tuple[tuple[float, float, float, float], ...]:
    try:
        rows = tuple(tuple(float(component) for component in row) for row in value)
    except (TypeError, ValueError):
        raise ValueError("world_transform 必须是有限 4x4 matrix") from None
    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        raise ValueError("world_transform 必须是有限 4x4 matrix")
    if not all(math.isfinite(component) for row in rows for component in row):
        raise ValueError("world_transform 必须是有限 4x4 matrix")
    matrix = np.asarray(rows, dtype=np.float64)
    if not np.allclose(
        matrix[3],
        np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float64),
        rtol=0.0,
        atol=1.0e-8,
    ):
        raise ValueError("world_transform 必须是 affine 4x4 matrix")
    return rows[:3] + ((0.0, 0.0, 0.0, 1.0),)


def _validated_transform(
    shape: str,
    world_transform,
) -> tuple[
    tuple[tuple[float, float, float, float], ...],
    tuple[float, float, float],
]:
    rows = _matrix4(world_transform)
    linear = np.asarray(rows, dtype=np.float64)[:3, :3]
    scales = np.linalg.norm(linear, axis=0)
    if np.any(scales <= 1.0e-8):
        raise ValueError("Field Volume transform 不能包含零 scale")
    axes = linear / scales[np.newaxis, :]
    if not np.allclose(
        axes.T @ axes,
        np.eye(3, dtype=np.float64),
        rtol=1.0e-5,
        atol=1.0e-6,
    ):
        raise ValueError("Field Volume transform 不支持 shear")
    if not math.isclose(
        float(np.linalg.det(axes)),
        1.0,
        rel_tol=1.0e-5,
        abs_tol=1.0e-6,
    ):
        raise ValueError("Field Volume transform 不支持 reflection")
    if shape == VOLUME_SHAPE_SPHERE and not np.allclose(
        scales,
        np.full(3, scales[0], dtype=np.float64),
        rtol=1.0e-5,
        atol=1.0e-6,
    ):
        raise ValueError("SPHERE Field Volume 不支持非均匀 scale")
    return rows, tuple(float(value) for value in scales)


@dataclass(frozen=True, slots=True)
class FieldScopeV0:
    solver_ids: tuple[str, ...] = ()
    collection_ids: tuple[str, ...] = ()
    include_ids: tuple[str, ...] = ()
    exclude_ids: tuple[str, ...] = ()
    collision_groups: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        groups = tuple(
            _strict_int(
                "collision_group",
                value,
                minimum=1,
                maximum=COLLISION_GROUP_COUNT,
            )
            for value in self.collision_groups
        )
        object.__setattr__(self, "solver_ids", _string_tuple(self.solver_ids))
        object.__setattr__(self, "collection_ids", _string_tuple(self.collection_ids))
        object.__setattr__(self, "include_ids", _string_tuple(self.include_ids))
        object.__setattr__(self, "exclude_ids", _string_tuple(self.exclude_ids))
        object.__setattr__(self, "collision_groups", tuple(sorted(set(groups))))

    def allows_consumer(self, consumer_id: str | None) -> bool:
        if not self.solver_ids:
            return True
        return str(consumer_id or "").strip() in self.solver_ids

    def allows(
        self,
        *,
        consumer_id: str | None = None,
        object_id: str | None = None,
        collection_ids: Iterable[Any] = (),
        collision_groups: Iterable[Any] = (),
    ) -> bool:
        """判断一次采样请求是否落在该 Field 的显式作用域内。"""
        if not self.allows_consumer(consumer_id):
            return False

        normalized_object_id = str(object_id or "").strip()
        if self.include_ids and normalized_object_id not in self.include_ids:
            return False
        if normalized_object_id and normalized_object_id in self.exclude_ids:
            return False

        requested_collections = set(_string_tuple(collection_ids))
        if self.collection_ids and not requested_collections.intersection(
            self.collection_ids
        ):
            return False

        requested_groups = {
            _strict_int(
                "collision_group",
                value,
                minimum=1,
                maximum=COLLISION_GROUP_COUNT,
            )
            for value in collision_groups
        }
        if self.collision_groups and not requested_groups.intersection(
            self.collision_groups
        ):
            return False
        return True

    def signature_payload(self) -> dict:
        return {
            "solver_ids": self.solver_ids,
            "collection_ids": self.collection_ids,
            "include_ids": self.include_ids,
            "exclude_ids": self.exclude_ids,
            "collision_groups": self.collision_groups,
        }


@dataclass(frozen=True, slots=True)
class VolumeSpecV0:
    shape: str = VOLUME_SHAPE_SPHERE
    world_transform: tuple[tuple[float, float, float, float], ...] = IDENTITY_MATRIX4
    attenuation_policy_version: int = VOLUME_ATTENUATION_POLICY_VERSION
    world_scale: tuple[float, float, float] = field(init=False)
    world_to_local: tuple[tuple[float, float, float, float], ...] = field(init=False)
    attenuation_policy_id: str = field(init=False)
    config_signature: str = field(init=False)
    value_signature: str = field(init=False)
    signature: str = field(init=False)

    def __post_init__(self) -> None:
        shape = str(self.shape or "").strip().upper()
        if shape not in VOLUME_SHAPES_V0:
            raise ValueError(f"Field Volume V0 不支持 shape: {shape!r}")
        policy_version = _strict_int(
            "attenuation_policy_version",
            self.attenuation_policy_version,
            minimum=0,
            maximum=VOLUME_ATTENUATION_POLICY_VERSION,
        )
        rows, scales = _validated_transform(shape, self.world_transform)
        inverse = tuple(
            tuple(float(component) for component in row)
            for row in np.linalg.inv(np.asarray(rows, dtype=np.float64))
        )
        policy_id = (
            SPHERE_ATTENUATION_POLICY_V0
            if shape == VOLUME_SHAPE_SPHERE
            else BOX_ATTENUATION_POLICY_V0
        )
        config_signature = _stable_signature({
            "shape": shape,
            "attenuation_policy_id": policy_id,
            "attenuation_policy_version": policy_version,
        })
        value_signature = _stable_signature({"world_transform": rows})
        object.__setattr__(self, "shape", shape)
        object.__setattr__(self, "world_transform", rows)
        object.__setattr__(self, "attenuation_policy_version", policy_version)
        object.__setattr__(self, "world_scale", scales)
        object.__setattr__(self, "world_to_local", inverse)
        object.__setattr__(self, "attenuation_policy_id", policy_id)
        object.__setattr__(self, "config_signature", config_signature)
        object.__setattr__(self, "value_signature", value_signature)
        object.__setattr__(self, "signature", _stable_signature({
            "config": config_signature,
            "value": value_signature,
        }))

    def debug_dict(self) -> dict:
        return {
            "schema": "field_volume_v0",
            "shape": self.shape,
            "world_transform": self.world_transform,
            "world_scale": self.world_scale,
            "world_to_local": self.world_to_local,
            "attenuation_policy_id": self.attenuation_policy_id,
            "attenuation_policy_version": self.attenuation_policy_version,
            "config_signature": self.config_signature,
            "value_signature": self.value_signature,
            "signature": self.signature,
        }


@dataclass(frozen=True, slots=True)
class WindPayloadV0:
    speed_mps: float = 1.0
    turbulence: float = 0.0
    spatial_scale_m: float = 1.0
    temporal_frequency_hz: float = 0.5
    octaves: int = 3
    lacunarity: float = 2.0
    gain: float = 0.5
    seed_u32: int = 0
    noise_algorithm_version: int = WIND_NOISE_ALGORITHM_VERSION
    config_signature: str = field(init=False)
    value_signature: str = field(init=False)
    signature: str = field(init=False)

    def __post_init__(self) -> None:
        speed = _finite_float("speed_mps", self.speed_mps, minimum=0.0)
        turbulence = _finite_float(
            "turbulence", self.turbulence, minimum=0.0, maximum=1.0
        )
        spatial_scale = _finite_float(
            "spatial_scale_m", self.spatial_scale_m, minimum=1.0e-6
        )
        temporal_frequency = _finite_float(
            "temporal_frequency_hz",
            self.temporal_frequency_hz,
            minimum=0.0,
        )
        octaves = _strict_int("octaves", self.octaves, minimum=1, maximum=8)
        lacunarity = _finite_float(
            "lacunarity", self.lacunarity, minimum=1.0, maximum=8.0
        )
        gain = _finite_float("gain", self.gain, minimum=0.0, maximum=1.0)
        seed = _strict_int("seed_u32", self.seed_u32, minimum=0, maximum=0xFFFFFFFF)
        algorithm = _strict_int(
            "noise_algorithm_version",
            self.noise_algorithm_version,
            minimum=0,
            maximum=WIND_NOISE_ALGORITHM_VERSION,
        )
        value_payload = {
            "speed_mps": speed,
            "turbulence": turbulence,
            "spatial_scale_m": spatial_scale,
            "temporal_frequency_hz": temporal_frequency,
            "octaves": octaves,
            "lacunarity": lacunarity,
            "gain": gain,
            "seed_u32": seed,
        }
        for name, value in value_payload.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "noise_algorithm_version", algorithm)
        config_signature = _stable_signature({
            "generator_id": WIND_GENERATOR_ID,
            "noise_algorithm_version": algorithm,
        })
        value_signature = _stable_signature(value_payload)
        object.__setattr__(self, "config_signature", config_signature)
        object.__setattr__(self, "value_signature", value_signature)
        object.__setattr__(self, "signature", _stable_signature({
            "config": config_signature,
            "value": value_signature,
        }))

    def debug_dict(self) -> dict:
        return {
            "schema": "field_wind_payload_v0",
            "speed_mps": self.speed_mps,
            "turbulence": self.turbulence,
            "spatial_scale_m": self.spatial_scale_m,
            "temporal_frequency_hz": self.temporal_frequency_hz,
            "octaves": self.octaves,
            "lacunarity": self.lacunarity,
            "gain": self.gain,
            "seed_u32": self.seed_u32,
            "noise_algorithm_version": self.noise_algorithm_version,
            "config_signature": self.config_signature,
            "value_signature": self.value_signature,
            "signature": self.signature,
        }


@dataclass(frozen=True, slots=True)
class FieldSpecV0:
    field_id: str
    source_id: str
    volume: VolumeSpecV0 = field(default_factory=VolumeSpecV0)
    wind: WindPayloadV0 = field(default_factory=WindPayloadV0)
    scope: FieldScopeV0 = field(default_factory=FieldScopeV0)
    enabled: bool = True
    status: str = FIELD_STATUS_PREVIEW_ONLY
    blend_weight: float = 1.0
    priority: int = 0
    abi_version: int = FIELD_ABI_VERSION
    field_type: str = FIELD_TYPE_WIND
    channel_id: str = field(init=False)
    generator_id: str = field(init=False)
    config_signature: str = field(init=False)
    value_signature: str = field(init=False)
    signature: str = field(init=False)

    def __post_init__(self) -> None:
        field_id = str(self.field_id or "").strip()
        source_id = str(self.source_id or "").strip()
        if not field_id:
            raise ValueError("field_id 不能为空")
        if not source_id:
            raise ValueError("source_id 不能为空")
        field_type = str(self.field_type or "").strip().upper()
        if field_type not in FIELD_TYPES_V0:
            raise ValueError(f"不支持的 Field 类型: {field_type!r}")
        if field_type != FIELD_TYPE_WIND:
            raise ValueError(f"Field 类型 {field_type!r} 尚未实现")
        if not isinstance(self.volume, VolumeSpecV0):
            raise TypeError("volume 必须是 VolumeSpecV0")
        if not isinstance(self.wind, WindPayloadV0):
            raise TypeError("wind 必须是 WindPayloadV0")
        if not isinstance(self.scope, FieldScopeV0):
            raise TypeError("scope 必须是 FieldScopeV0")
        status = str(self.status or "").strip().upper()
        if status not in FIELD_STATUSES:
            raise ValueError(f"不支持的 Field status: {status!r}")
        blend_weight = _finite_float(
            "blend_weight", self.blend_weight, minimum=0.0
        )
        priority = _strict_int(
            "priority", self.priority, minimum=-(2**31), maximum=2**31 - 1
        )
        abi_version = _strict_int(
            "abi_version",
            self.abi_version,
            minimum=FIELD_ABI_VERSION,
            maximum=FIELD_ABI_VERSION,
        )
        config_signature = _stable_signature({
            "abi_version": abi_version,
            "field_id": field_id,
            "source_id": source_id,
            "field_type": field_type,
            "channel_id": AIR_VELOCITY_CHANNEL_ID,
            "generator_id": WIND_GENERATOR_ID,
            "volume": self.volume.config_signature,
            "wind": self.wind.config_signature,
            "scope": self.scope.signature_payload(),
            "priority": priority,
        })
        value_signature = _stable_signature({
            "enabled": bool(self.enabled),
            "status": status,
            "blend_weight": blend_weight,
            "volume": self.volume.value_signature,
            "wind": self.wind.value_signature,
        })
        object.__setattr__(self, "field_id", field_id)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "field_type", field_type)
        object.__setattr__(self, "channel_id", AIR_VELOCITY_CHANNEL_ID)
        object.__setattr__(self, "generator_id", WIND_GENERATOR_ID)
        object.__setattr__(self, "blend_weight", blend_weight)
        object.__setattr__(self, "priority", priority)
        object.__setattr__(self, "abi_version", abi_version)
        object.__setattr__(self, "config_signature", config_signature)
        object.__setattr__(self, "value_signature", value_signature)
        object.__setattr__(self, "signature", _stable_signature({
            "config": config_signature,
            "value": value_signature,
        }))

    def debug_dict(self) -> dict:
        return {
            "schema": "field_spec_v0",
            "abi_version": self.abi_version,
            "field_id": self.field_id,
            "source_id": self.source_id,
            "enabled": self.enabled,
            "status": self.status,
            "field_type": self.field_type,
            "channel_id": self.channel_id,
            "generator_id": self.generator_id,
            "blend_weight": self.blend_weight,
            "priority": self.priority,
            "scope": self.scope.signature_payload(),
            "volume": self.volume.debug_dict(),
            "wind": self.wind.debug_dict(),
            "config_signature": self.config_signature,
            "value_signature": self.value_signature,
            "signature": self.signature,
        }


@dataclass(frozen=True, slots=True)
class FieldSnapshotV0:
    fields: tuple[FieldSpecV0, ...]
    generation: int = 0
    frame: int = 0
    sample_time_seconds: float = 0.0
    diagnostics: tuple[FieldDiagnosticV0, ...] = ()
    noise_algorithm_versions: tuple[int, ...] = field(init=False)
    attenuation_policy_versions: tuple[int, ...] = field(init=False)
    config_signature: str = field(init=False)
    value_signature: str = field(init=False)
    signature: str = field(init=False)

    def __post_init__(self) -> None:
        values = tuple(self.fields)
        if any(not isinstance(item, FieldSpecV0) for item in values):
            raise TypeError("FieldSnapshotV0.fields 只能包含 FieldSpecV0")
        ordered = tuple(sorted(values, key=lambda item: (item.priority, item.field_id)))
        ids = tuple(item.field_id for item in ordered)
        if len(ids) != len(set(ids)):
            raise ValueError("FieldSnapshotV0 不允许重复 field_id")
        snapshot_diagnostics = tuple(self.diagnostics)
        if any(
            not isinstance(item, FieldDiagnosticV0)
            for item in snapshot_diagnostics
        ):
            raise TypeError("FieldSnapshotV0.diagnostics 只能包含 FieldDiagnosticV0")
        generation = _strict_int("generation", self.generation, minimum=0)
        frame = _strict_int("frame", self.frame)
        sample_time = _finite_float(
            "sample_time_seconds", self.sample_time_seconds, minimum=0.0
        )
        config_signature = _stable_signature({
            "abi_version": FIELD_ABI_VERSION,
            "fields": tuple(item.config_signature for item in ordered),
        })
        value_signature = _stable_signature({
            "fields": tuple(item.value_signature for item in ordered),
        })
        object.__setattr__(self, "fields", ordered)
        object.__setattr__(self, "generation", generation)
        object.__setattr__(self, "frame", frame)
        object.__setattr__(self, "sample_time_seconds", sample_time)
        object.__setattr__(self, "diagnostics", snapshot_diagnostics)
        object.__setattr__(
            self,
            "noise_algorithm_versions",
            tuple(sorted({item.wind.noise_algorithm_version for item in ordered})),
        )
        object.__setattr__(
            self,
            "attenuation_policy_versions",
            tuple(sorted({
                item.volume.attenuation_policy_version for item in ordered
            })),
        )
        object.__setattr__(self, "config_signature", config_signature)
        object.__setattr__(self, "value_signature", value_signature)
        object.__setattr__(self, "signature", _stable_signature({
            "abi_version": FIELD_ABI_VERSION,
            "generation": generation,
            "frame": frame,
            "sample_time_seconds": sample_time,
            "config": config_signature,
            "value": value_signature,
        }))

    def debug_dict(self) -> dict:
        return {
            "schema": "field_snapshot_v0",
            "generation": self.generation,
            "frame": self.frame,
            "sample_time_seconds": self.sample_time_seconds,
            "field_count": len(self.fields),
            "field_ids": tuple(item.field_id for item in self.fields),
            "noise_algorithm_versions": self.noise_algorithm_versions,
            "attenuation_policy_versions": self.attenuation_policy_versions,
            "diagnostics": tuple(item.debug_dict() for item in self.diagnostics),
            "config_signature": self.config_signature,
            "value_signature": self.value_signature,
            "signature": self.signature,
        }


def build_field_snapshot_v0(
    fields,
    *,
    generation: int = 0,
    frame: int = 0,
    sample_time_seconds: float = 0.0,
    diagnostics=(),
) -> FieldSnapshotV0:
    if fields is None:
        values = ()
    elif isinstance(fields, FieldSpecV0):
        values = (fields,)
    else:
        values = tuple(fields)
    return FieldSnapshotV0(
        values,
        generation=generation,
        frame=frame,
        sample_time_seconds=sample_time_seconds,
        diagnostics=tuple(diagnostics or ()),
    )


__all__ = [
    "FieldScopeV0",
    "FieldSnapshotV0",
    "FieldSpecV0",
    "IDENTITY_MATRIX4",
    "VolumeSpecV0",
    "WindPayloadV0",
    "build_field_snapshot_v0",
]
