"""MC2 对公共 Field ``air_velocity`` 通道的纯 Python 采样桥。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral
from typing import Iterable

import numpy as np

from ..field.diagnostics import FieldDiagnosticV0
from ..field.sampling import sample_air_velocity_v0
from ..field.specs import FieldScopeV0, FieldSnapshotV0
from .names import MC2_SOLVER_ID


MC2_FIELD_SAMPLE_PACKET_ABI_VERSION = 0


def _strict_nonnegative_int_v0(name: str, value) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} 必须是非负整数")
    result = int(value)
    if result < 0:
        raise ValueError(f"{name} 必须是非负整数")
    return result


def _finite_nonnegative_float_v0(name: str, value) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{name} 必须是非负有限浮点数")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise TypeError(f"{name} 必须是非负有限浮点数") from None
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{name} 必须是非负有限浮点数")
    return result


def _normalized_request_signatures_v0(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    result = tuple(str(value or "").strip().lower() for value in values)
    for value in result:
        if len(value) != 16 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError("request_signatures 只能包含 16 位小写十六进制签名")
    return result


@dataclass(frozen=True, slots=True)
class MC2FieldSamplePacketV0:
    """一次 MC2 子步使用的逻辑粒子顺序空气速度包。"""

    abi_version: int
    field_snapshot_signature: str
    sample_time_seconds: float
    particle_count: int
    air_velocity_world_f32: np.ndarray
    diagnostics: tuple[FieldDiagnosticV0, ...] = ()
    request_signatures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        abi_version = _strict_nonnegative_int_v0("abi_version", self.abi_version)
        if abi_version != MC2_FIELD_SAMPLE_PACKET_ABI_VERSION:
            raise ValueError(
                "MC2 Field sample packet 只支持 abi_version=0"
            )
        signature = self.field_snapshot_signature
        if not isinstance(signature, str) or not signature.strip():
            raise ValueError("field_snapshot_signature 不能为空")
        signature = signature.strip()
        sample_time = _finite_nonnegative_float_v0(
            "sample_time_seconds", self.sample_time_seconds
        )
        particle_count = _strict_nonnegative_int_v0(
            "particle_count", self.particle_count
        )

        values = self.air_velocity_world_f32
        if not isinstance(values, np.ndarray):
            raise TypeError("air_velocity_world_f32 必须是 numpy.ndarray")
        if values.dtype != np.dtype(np.float32):
            raise TypeError("air_velocity_world_f32 必须是 float32")
        expected_shape = (particle_count, 3)
        if values.shape != expected_shape:
            raise ValueError(
                "air_velocity_world_f32 必须是 "
                f"float32[{particle_count}, 3]，实际为 {values.shape}"
            )
        if not values.flags.c_contiguous:
            raise ValueError("air_velocity_world_f32 必须是 C contiguous")
        if not np.all(np.isfinite(values)):
            raise ValueError("air_velocity_world_f32 只能包含有限浮点数")

        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(item, FieldDiagnosticV0) for item in diagnostics):
            raise TypeError("diagnostics 只能包含 FieldDiagnosticV0")
        request_signatures = _normalized_request_signatures_v0(
            self.request_signatures
        )
        frozen_values = values.copy(order="C")
        frozen_values.setflags(write=False)

        object.__setattr__(self, "abi_version", abi_version)
        object.__setattr__(self, "field_snapshot_signature", signature)
        object.__setattr__(self, "sample_time_seconds", sample_time)
        object.__setattr__(self, "particle_count", particle_count)
        object.__setattr__(self, "air_velocity_world_f32", frozen_values)
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "request_signatures", request_signatures)


def _readonly_particle_indices_v0(values) -> np.ndarray:
    try:
        source = np.asarray(values)
    except (TypeError, ValueError, OverflowError):
        raise TypeError("particle_indices 必须是一维整数数组") from None
    if source.ndim != 1 or source.dtype.kind not in "iu":
        raise TypeError("particle_indices 必须是一维整数数组")
    if source.dtype.kind == "u" and source.size:
        if int(source.max()) > np.iinfo(np.int64).max:
            raise ValueError("particle_indices 超出 int64 范围")
    result = np.asarray(source, dtype=np.int64)
    if np.any(result < 0):
        raise ValueError("particle_indices 不能包含负索引")
    if result.size != np.unique(result).size:
        raise ValueError("单个 consumer partition 不能包含重复粒子索引")
    result = np.ascontiguousarray(np.sort(result), dtype=np.int64).copy()
    result.setflags(write=False)
    return result


@dataclass(frozen=True, slots=True)
class MC2FieldConsumerPartitionV0:
    """一组共享 Field 作用域上下文的 MC2 逻辑粒子索引。"""

    particle_indices: np.ndarray
    object_id: str = ""
    collection_ids: tuple[str, ...] = ()
    collision_groups: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        indices = _readonly_particle_indices_v0(self.particle_indices)
        object_id = str(self.object_id or "").strip()
        scope = FieldScopeV0(
            collection_ids=self.collection_ids,
            collision_groups=self.collision_groups,
        )
        object.__setattr__(self, "particle_indices", indices)
        object.__setattr__(self, "object_id", object_id)
        object.__setattr__(self, "collection_ids", scope.collection_ids)
        object.__setattr__(self, "collision_groups", scope.collision_groups)


def _positions_world_v0(positions_world) -> np.ndarray:
    try:
        values = np.asarray(positions_world, dtype=np.float64)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("positions_world 必须能转换为有限浮点数组") from None
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("positions_world 必须是 [N, 3]")
    if not np.all(np.isfinite(values)):
        raise ValueError("positions_world 只能包含有限浮点数")
    return np.ascontiguousarray(values, dtype=np.float64)


def _consumer_partitions_v0(values) -> tuple[MC2FieldConsumerPartitionV0, ...]:
    try:
        result = tuple(values)
    except TypeError:
        raise TypeError(
            "consumer_partitions 必须是 MC2FieldConsumerPartitionV0 可迭代对象"
        ) from None
    if any(not isinstance(item, MC2FieldConsumerPartitionV0) for item in result):
        raise TypeError(
            "consumer_partitions 只能包含 MC2FieldConsumerPartitionV0"
        )
    return tuple(sorted(
        result,
        key=lambda item: (
            tuple(int(value) for value in item.particle_indices),
            item.object_id,
            item.collection_ids,
            item.collision_groups,
        ),
    ))


def build_mc2_field_sample_packet_v0(
    snapshot: FieldSnapshotV0,
    positions_world,
    sample_time_seconds,
    consumer_partitions=(),
) -> MC2FieldSamplePacketV0:
    """按 MC2 logical index 采样 Field，并冻结为子步输入包。"""
    if not isinstance(snapshot, FieldSnapshotV0):
        raise TypeError("snapshot 必须是 FieldSnapshotV0")
    positions = _positions_world_v0(positions_world)
    sample_time = _finite_nonnegative_float_v0(
        "sample_time_seconds", sample_time_seconds
    )
    particle_count = int(positions.shape[0])
    partitions = _consumer_partitions_v0(consumer_partitions)

    if not partitions:
        batch = sample_air_velocity_v0(
            snapshot,
            positions,
            sample_time_seconds=sample_time,
            consumer_id=MC2_SOLVER_ID,
        )
        values = batch.values_world_f32
        diagnostics = batch.diagnostics
        request_signatures = (batch.request_signature,)
    else:
        owners = np.full(particle_count, -1, dtype=np.int64)
        for partition_index, partition in enumerate(partitions):
            indices = partition.particle_indices
            if indices.size and int(indices[-1]) >= particle_count:
                raise ValueError("consumer partition 粒子索引超出 positions_world")
            if np.any(owners[indices] != -1):
                raise ValueError("consumer partitions 的粒子索引不能重叠")
            owners[indices] = partition_index
        if np.any(owners == -1):
            raise ValueError("consumer partitions 必须完整覆盖全部逻辑粒子")

        values = np.zeros((particle_count, 3), dtype=np.float32)
        diagnostics_list: list[FieldDiagnosticV0] = []
        request_signature_list: list[str] = []
        for partition in partitions:
            indices = partition.particle_indices
            batch = sample_air_velocity_v0(
                snapshot,
                positions[indices],
                sample_time_seconds=sample_time,
                consumer_id=MC2_SOLVER_ID,
                object_id=partition.object_id,
                collection_ids=partition.collection_ids,
                collision_groups=partition.collision_groups,
            )
            values[indices] = batch.values_world_f32
            diagnostics_list.extend(batch.diagnostics)
            request_signature_list.append(batch.request_signature)
        diagnostics = tuple(diagnostics_list)
        request_signatures = tuple(request_signature_list)

    return MC2FieldSamplePacketV0(
        abi_version=MC2_FIELD_SAMPLE_PACKET_ABI_VERSION,
        field_snapshot_signature=snapshot.signature,
        sample_time_seconds=sample_time,
        particle_count=particle_count,
        air_velocity_world_f32=values,
        diagnostics=diagnostics,
        request_signatures=request_signatures,
    )


__all__ = [
    "MC2_FIELD_SAMPLE_PACKET_ABI_VERSION",
    "MC2FieldConsumerPartitionV0",
    "MC2FieldSamplePacketV0",
    "build_mc2_field_sample_packet_v0",
]
