"""FieldSnapshot 的公共单点与批量空气速度采样器。"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Iterable

import numpy as np

from .diagnostics import FieldDiagnosticV0
from .names import (
    FIELD_INVALID_SPEC,
    FIELD_OUT_OF_SCOPE,
    FIELD_PREVIEW_ONLY,
    FIELD_STATUS_ACTIVE,
    FIELD_STATUS_INVALID,
    FIELD_STATUS_PREVIEW_ONLY,
    FIELD_STATUS_RESERVED,
    FIELD_UNSUPPORTED_SOURCE,
)
from .specs import FieldScopeV0, FieldSnapshotV0
from .volume import (
    coerce_positions_world_v0,
    sample_volume_weight_reference_v0,
    sample_volume_weights_v0,
    wind_direction_world_v0,
)
from .wind import sample_wind_raw_reference_v0, sample_wind_raw_v0


def _canonical_json_bytes_v0(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _signature_with_binary_v0(schema: str, metadata, payload: bytes) -> str:
    """以长度分帧组合结构元数据和精确二进制内容，避免拼接歧义。"""
    schema_bytes = str(schema).encode("ascii")
    metadata_bytes = _canonical_json_bytes_v0(metadata)
    digest = hashlib.sha256()
    for part in (schema_bytes, metadata_bytes, payload):
        digest.update(len(part).to_bytes(8, "little", signed=False))
        digest.update(part)
    return digest.hexdigest()[:16]


def _normalized_context_id_v0(value) -> str:
    return str(value or "").strip()


def _normalized_selected_field_ids_v0(
    values: Iterable[str] | None,
) -> tuple[str, ...] | None:
    if values is None:
        return None
    if isinstance(values, str):
        values = (values,)
    return tuple(sorted({
        item
        for value in values
        if (item := str(value or "").strip())
    }))


def _request_signature_v0(
    *,
    snapshot_signature: str,
    positions_world_f64: np.ndarray,
    sample_time_seconds: float,
    consumer_id: str,
    object_id: str,
    collection_ids: tuple[str, ...],
    collision_groups: tuple[int, ...],
    include_preview: bool,
    selected_field_ids: tuple[str, ...] | None,
) -> str:
    # 公共 sampler 的位置契约统一为 little-endian、C 连续的 float64 [N, 3]。
    positions = np.ascontiguousarray(positions_world_f64, dtype=np.dtype("<f8"))
    metadata = {
        "snapshot_signature": str(snapshot_signature),
        "sample_time_seconds_hex": float(sample_time_seconds).hex(),
        "positions_dtype": "<f8",
        "positions_shape": tuple(int(value) for value in positions.shape),
        "consumer_id": consumer_id,
        "object_id": object_id,
        "collection_ids": collection_ids,
        "collision_groups": collision_groups,
        "include_preview": bool(include_preview),
        # None 表示全部 Field，空 tuple 表示不选择任何 Field，二者不能合并。
        "selected_field_ids": selected_field_ids,
    }
    return _signature_with_binary_v0(
        "field_sample_request_v0",
        metadata,
        positions.tobytes(order="C"),
    )


@dataclass(frozen=True, slots=True)
class FieldSampleStatsV0:
    """一次公共采样调用的确定性统计。"""

    position_count: int
    considered_field_count: int
    sampled_field_count: int
    culled_field_count: int
    uniform_field_count: int
    turbulent_field_count: int

    def debug_dict(self) -> dict:
        return {
            "position_count": self.position_count,
            "considered_field_count": self.considered_field_count,
            "sampled_field_count": self.sampled_field_count,
            "culled_field_count": self.culled_field_count,
            "uniform_field_count": self.uniform_field_count,
            "turbulent_field_count": self.turbulent_field_count,
        }


@dataclass(frozen=True, slots=True)
class FieldSampleBatchV0:
    """只读的参考采样结果；它不是承诺复用 buffer 的 native 热路径 ABI。"""

    values_world_f32: np.ndarray
    snapshot_signature: str
    sample_time_seconds: float
    request_signature: str
    sampled_field_ids: tuple[str, ...] = ()
    diagnostics: tuple[FieldDiagnosticV0, ...] = ()
    stats: FieldSampleStatsV0 = field(
        default_factory=lambda: FieldSampleStatsV0(0, 0, 0, 0, 0, 0)
    )
    sample_signature: str = field(init=False)

    def __post_init__(self) -> None:
        values = np.asarray(self.values_world_f32, dtype=np.float32)
        if values.ndim != 2 or values.shape[1] != 3:
            raise ValueError("values_world_f32 必须是 [N, 3]")
        if not np.all(np.isfinite(values)):
            raise ValueError("values_world_f32 只能包含有限浮点数")
        frozen = np.ascontiguousarray(values, dtype=np.float32).copy()
        frozen.setflags(write=False)
        object.__setattr__(self, "values_world_f32", frozen)
        object.__setattr__(self, "snapshot_signature", str(self.snapshot_signature))
        object.__setattr__(
            self,
            "sample_time_seconds",
            float(self.sample_time_seconds),
        )
        request_signature = str(self.request_signature or "").strip().lower()
        if len(request_signature) != 16 or any(
            value not in "0123456789abcdef" for value in request_signature
        ):
            raise ValueError("request_signature 必须是 16 位小写十六进制签名")
        object.__setattr__(self, "request_signature", request_signature)
        object.__setattr__(
            self,
            "sampled_field_ids",
            tuple(str(value) for value in self.sampled_field_ids),
        )
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if not isinstance(self.stats, FieldSampleStatsV0):
            raise TypeError("stats 必须是 FieldSampleStatsV0")
        result_values = np.ascontiguousarray(frozen, dtype=np.dtype("<f4"))
        signature_metadata = {
            "request_signature": request_signature,
            "values_dtype": "<f4",
            "values_shape": tuple(int(value) for value in result_values.shape),
            "sampled_field_ids": self.sampled_field_ids,
            "diagnostics": tuple(item.debug_dict() for item in self.diagnostics),
            "stats": self.stats.debug_dict(),
        }
        object.__setattr__(
            self,
            "sample_signature",
            _signature_with_binary_v0(
                "field_sample_batch_v0",
                signature_metadata,
                result_values.tobytes(order="C"),
            ),
        )

    def debug_dict(self) -> dict:
        return {
            "schema": "field_sample_batch_v0",
            "snapshot_signature": self.snapshot_signature,
            "sample_time_seconds": self.sample_time_seconds,
            "request_signature": self.request_signature,
            "sample_signature": self.sample_signature,
            "shape": tuple(self.values_world_f32.shape),
            "sampled_field_ids": self.sampled_field_ids,
            "diagnostics": tuple(item.debug_dict() for item in self.diagnostics),
            "stats": self.stats.debug_dict(),
        }


@dataclass(frozen=True, slots=True)
class FieldPointSampleV0:
    """单点便利结果；数值来自同一批量采样路径。"""

    value_world_mps: tuple[float, float, float]
    snapshot_signature: str
    sample_time_seconds: float
    request_signature: str
    sample_signature: str
    sampled_field_ids: tuple[str, ...]
    diagnostics: tuple[FieldDiagnosticV0, ...]
    stats: FieldSampleStatsV0


def _normalized_time(snapshot: FieldSnapshotV0, sample_time_seconds) -> float:
    value = (
        snapshot.sample_time_seconds
        if sample_time_seconds is None
        else sample_time_seconds
    )
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("sample_time_seconds 必须是有限浮点数") from None
    if not math.isfinite(result) or result < 0.0:
        raise ValueError("sample_time_seconds 必须是非负有限浮点数")
    return result


def sample_air_velocity_v0(
    snapshot: FieldSnapshotV0,
    positions_world,
    *,
    sample_time_seconds: float | None = None,
    consumer_id: str | None = None,
    object_id: str | None = None,
    collection_ids: Iterable[str] = (),
    collision_groups: Iterable[int] = (),
    include_preview: bool = False,
    selected_field_ids: Iterable[str] | None = None,
) -> FieldSampleBatchV0:
    """按固定顺序叠加 ``air_velocity``，不读取 Blender 状态或墙钟。"""
    if not isinstance(snapshot, FieldSnapshotV0):
        raise TypeError("snapshot 必须是 FieldSnapshotV0")
    positions, _ = coerce_positions_world_v0(positions_world)
    sample_time = _normalized_time(snapshot, sample_time_seconds)
    request_scope = FieldScopeV0(
        collection_ids=collection_ids,
        collision_groups=collision_groups,
    )
    normalized_consumer_id = _normalized_context_id_v0(consumer_id)
    normalized_object_id = _normalized_context_id_v0(object_id)
    normalized_include_preview = bool(include_preview)
    normalized_selected_ids = _normalized_selected_field_ids_v0(selected_field_ids)
    selected = (
        None if normalized_selected_ids is None else set(normalized_selected_ids)
    )
    request_signature = _request_signature_v0(
        snapshot_signature=snapshot.signature,
        positions_world_f64=positions,
        sample_time_seconds=sample_time,
        consumer_id=normalized_consumer_id,
        object_id=normalized_object_id,
        collection_ids=request_scope.collection_ids,
        collision_groups=request_scope.collision_groups,
        include_preview=normalized_include_preview,
        selected_field_ids=normalized_selected_ids,
    )
    values = np.zeros((positions.shape[0], 3), dtype=np.float64)
    diagnostics: list[FieldDiagnosticV0] = []
    sampled_ids: list[str] = []
    considered = 0
    sampled = 0
    culled = 0
    uniform = 0
    turbulent = 0

    for item in snapshot.fields:
        if selected is not None and item.field_id not in selected:
            continue
        considered += 1
        if not item.enabled:
            culled += 1
            continue
        if item.status == FIELD_STATUS_PREVIEW_ONLY and not normalized_include_preview:
            culled += 1
            diagnostics.append(FieldDiagnosticV0(
                FIELD_PREVIEW_ONLY,
                "Field 尚无已声明 consumer，仅允许显式预览采样",
                field_id=item.field_id,
                severity="INFO",
            ))
            continue
        if item.status == FIELD_STATUS_RESERVED:
            culled += 1
            diagnostics.append(FieldDiagnosticV0(
                FIELD_UNSUPPORTED_SOURCE,
                "Field generator 目前只是保留能力，尚无数值实现",
                field_id=item.field_id,
                severity="WARNING",
            ))
            continue
        if item.status == FIELD_STATUS_INVALID:
            culled += 1
            diagnostics.append(FieldDiagnosticV0(
                FIELD_INVALID_SPEC,
                "Field 已被 resolver 标记为无效",
                field_id=item.field_id,
            ))
            continue
        if item.status != FIELD_STATUS_ACTIVE and item.status != FIELD_STATUS_PREVIEW_ONLY:
            culled += 1
            continue
        if not item.scope.allows(
            consumer_id=normalized_consumer_id,
            object_id=normalized_object_id,
            collection_ids=request_scope.collection_ids,
            collision_groups=request_scope.collision_groups,
        ):
            culled += 1
            diagnostics.append(FieldDiagnosticV0(
                FIELD_OUT_OF_SCOPE,
                "采样请求不在 Field 的显式作用域内",
                field_id=item.field_id,
                severity="INFO",
            ))
            continue

        try:
            weights = sample_volume_weights_v0(item.volume, positions)
            if not np.any(weights > 0.0):
                culled += 1
                continue
            raw = sample_wind_raw_v0(
                item.wind,
                wind_direction_world_v0(item.volume),
                positions,
                sample_time,
            )
            contribution = (
                raw.astype(np.float64)
                * weights.astype(np.float64)[:, np.newaxis]
                * item.blend_weight
            )
            if not np.all(np.isfinite(contribution)):
                raise ValueError("Field 采样产生了非有限数值")
        except (TypeError, ValueError, ArithmeticError, np.linalg.LinAlgError) as exc:
            culled += 1
            diagnostics.append(FieldDiagnosticV0(
                FIELD_INVALID_SPEC,
                f"Field 采样失败：{exc}",
                field_id=item.field_id,
            ))
            continue

        values += contribution
        sampled += 1
        sampled_ids.append(item.field_id)
        if item.wind.turbulence == 0.0:
            uniform += 1
        else:
            turbulent += 1

    stats = FieldSampleStatsV0(
        position_count=positions.shape[0],
        considered_field_count=considered,
        sampled_field_count=sampled,
        culled_field_count=culled,
        uniform_field_count=uniform,
        turbulent_field_count=turbulent,
    )
    return FieldSampleBatchV0(
        np.ascontiguousarray(values, dtype=np.float32),
        snapshot_signature=snapshot.signature,
        sample_time_seconds=sample_time,
        request_signature=request_signature,
        sampled_field_ids=tuple(sampled_ids),
        diagnostics=tuple(diagnostics),
        stats=stats,
    )


def sample_air_velocity_at_v0(
    snapshot: FieldSnapshotV0,
    position_world,
    **kwargs,
) -> FieldPointSampleV0:
    """调用批量路径采样一个世界空间位置。"""
    batch = sample_air_velocity_v0(snapshot, position_world, **kwargs)
    return FieldPointSampleV0(
        value_world_mps=tuple(float(value) for value in batch.values_world_f32[0]),
        snapshot_signature=batch.snapshot_signature,
        sample_time_seconds=batch.sample_time_seconds,
        request_signature=batch.request_signature,
        sample_signature=batch.sample_signature,
        sampled_field_ids=batch.sampled_field_ids,
        diagnostics=batch.diagnostics,
        stats=batch.stats,
    )


def sample_air_velocity_reference_at_v0(
    snapshot: FieldSnapshotV0,
    position_world,
    *,
    sample_time_seconds: float | None = None,
    consumer_id: str | None = None,
    object_id: str | None = None,
    collection_ids: Iterable[str] = (),
    collision_groups: Iterable[int] = (),
    include_preview: bool = False,
    selected_field_ids: Iterable[str] | None = None,
) -> tuple[float, float, float]:
    """完整的标量参考路径，独立计算 Volume、Wind 与 Field 合成。"""
    if not isinstance(snapshot, FieldSnapshotV0):
        raise TypeError("snapshot 必须是 FieldSnapshotV0")
    position_values, scalar = coerce_positions_world_v0(position_world)
    if not scalar:
        raise ValueError("position_world 必须是单个 [3] 位置")
    position = tuple(float(value) for value in position_values[0])
    sample_time = _normalized_time(snapshot, sample_time_seconds)
    request_scope = FieldScopeV0(
        collection_ids=collection_ids,
        collision_groups=collision_groups,
    )
    normalized_consumer_id = _normalized_context_id_v0(consumer_id)
    normalized_object_id = _normalized_context_id_v0(object_id)
    normalized_include_preview = bool(include_preview)
    normalized_selected_ids = _normalized_selected_field_ids_v0(selected_field_ids)
    selected = (
        None if normalized_selected_ids is None else set(normalized_selected_ids)
    )
    result = [0.0, 0.0, 0.0]
    for item in snapshot.fields:
        if selected is not None and item.field_id not in selected:
            continue
        if not item.enabled:
            continue
        if item.status == FIELD_STATUS_PREVIEW_ONLY and not normalized_include_preview:
            continue
        if item.status not in {FIELD_STATUS_ACTIVE, FIELD_STATUS_PREVIEW_ONLY}:
            continue
        if not item.scope.allows(
            consumer_id=normalized_consumer_id,
            object_id=normalized_object_id,
            collection_ids=request_scope.collection_ids,
            collision_groups=request_scope.collision_groups,
        ):
            continue
        weight = sample_volume_weight_reference_v0(item.volume, position)
        if weight == 0.0:
            continue
        raw = sample_wind_raw_reference_v0(
            item.wind,
            wind_direction_world_v0(item.volume),
            position,
            sample_time,
        )
        for channel in range(3):
            result[channel] += raw[channel] * weight * item.blend_weight
    return tuple(result)


__all__ = [
    "FieldPointSampleV0",
    "FieldSampleBatchV0",
    "FieldSampleStatsV0",
    "sample_air_velocity_at_v0",
    "sample_air_velocity_reference_at_v0",
    "sample_air_velocity_v0",
]
