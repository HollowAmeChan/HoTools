"""Field channel 与可视化模式的纯数据注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .names import (
    AIR_VELOCITY_CHANNEL_ID,
    FIELD_STATUS_ACTIVE,
    FIELD_STATUS_PREVIEW_ONLY,
    FIELD_STATUS_RESERVED,
    WIND_GENERATOR_ID,
)


CHANNEL_RANK_VECTOR = "vector"
CHANNEL_RANK_SCALAR = "scalar"
CHANNEL_RANK_MATRIX = "matrix"
CHANNEL_RANKS_V0 = (
    CHANNEL_RANK_VECTOR,
    CHANNEL_RANK_SCALAR,
    CHANNEL_RANK_MATRIX,
)

VISUALIZATION_VECTOR_ARROWS = "vector_arrows"
VISUALIZATION_SCALAR_SAMPLES = "scalar_samples"
VISUALIZATION_SDF_ZERO_CROSSING = "sdf_zero_crossing"
VISUALIZATION_VOLUME_STATUS = "volume_status"
VISUALIZATION_MODES_V0 = (
    VISUALIZATION_VECTOR_ARROWS,
    VISUALIZATION_SCALAR_SAMPLES,
    VISUALIZATION_SDF_ZERO_CROSSING,
    VISUALIZATION_VOLUME_STATUS,
)
_VISUALIZATION_MODES_BY_RANK = MappingProxyType({
    CHANNEL_RANK_VECTOR: frozenset({
        VISUALIZATION_VECTOR_ARROWS,
        VISUALIZATION_VOLUME_STATUS,
    }),
    CHANNEL_RANK_SCALAR: frozenset({
        VISUALIZATION_SCALAR_SAMPLES,
        VISUALIZATION_SDF_ZERO_CROSSING,
        VISUALIZATION_VOLUME_STATUS,
    }),
    CHANNEL_RANK_MATRIX: frozenset({VISUALIZATION_VOLUME_STATUS}),
})


@dataclass(frozen=True, slots=True)
class FieldChannelDescriptorV0:
    channel_id: str
    display_name: str
    rank: str
    unit: str
    status: str
    visualization_mode: str
    sampler_id: str = ""
    semantic: str = ""

    def __post_init__(self) -> None:
        channel_id = str(self.channel_id or "").strip()
        display_name = str(self.display_name or "").strip()
        rank = str(self.rank or "").strip().lower()
        unit = str(self.unit or "").strip()
        status = str(self.status or "").strip().upper()
        visualization_mode = str(self.visualization_mode or "").strip()
        sampler_id = str(self.sampler_id or "").strip()
        semantic = str(self.semantic or "").strip()
        if not channel_id or not display_name:
            raise ValueError("Field channel 必须有稳定 ID 和显示名")
        if rank not in CHANNEL_RANKS_V0:
            raise ValueError(f"不支持的 Field channel rank：{rank!r}")
        if status not in {
            FIELD_STATUS_ACTIVE,
            FIELD_STATUS_PREVIEW_ONLY,
            FIELD_STATUS_RESERVED,
        }:
            raise ValueError(f"不支持的 Field channel status：{status!r}")
        if visualization_mode not in VISUALIZATION_MODES_V0:
            raise ValueError(
                f"不支持的 Field channel visualization：{visualization_mode!r}"
            )
        if visualization_mode not in _VISUALIZATION_MODES_BY_RANK[rank]:
            raise ValueError(
                f"Field channel rank {rank!r} 不能使用可视化模式 "
                f"{visualization_mode!r}"
            )
        if (
            status in {FIELD_STATUS_ACTIVE, FIELD_STATUS_PREVIEW_ONLY}
            and not sampler_id
        ):
            raise ValueError("active/preview_only channel 必须声明 sampler")
        if status == FIELD_STATUS_RESERVED and sampler_id:
            raise ValueError("reserved channel 不能伪装成已有 sampler")
        object.__setattr__(self, "channel_id", channel_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "rank", rank)
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "visualization_mode", visualization_mode)
        object.__setattr__(self, "sampler_id", sampler_id)
        object.__setattr__(self, "semantic", semantic)

    @property
    def values_ready(self) -> bool:
        return bool(self.sampler_id)

    def debug_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "display_name": self.display_name,
            "rank": self.rank,
            "unit": self.unit,
            "status": self.status,
            "visualization_mode": self.visualization_mode,
            "sampler_id": self.sampler_id,
            "semantic": self.semantic,
            "values_ready": self.values_ready,
        }


FIELD_CHANNELS_V0 = (
    FieldChannelDescriptorV0(
        channel_id=AIR_VELOCITY_CHANNEL_ID,
        display_name="空气速度",
        rank=CHANNEL_RANK_VECTOR,
        unit="m/s",
        status=FIELD_STATUS_PREVIEW_ONLY,
        visualization_mode=VISUALIZATION_VECTOR_ARROWS,
        sampler_id="sample_air_velocity_v0",
        semantic="风响应的空气速度输入",
    ),
    FieldChannelDescriptorV0(
        channel_id="acceleration",
        display_name="加速度",
        rank=CHANNEL_RANK_VECTOR,
        unit="m/s²",
        status=FIELD_STATUS_RESERVED,
        visualization_mode=VISUALIZATION_VECTOR_ARROWS,
        semantic="预留向量通道",
    ),
    FieldChannelDescriptorV0(
        channel_id="mask",
        display_name="遮罩",
        rank=CHANNEL_RANK_SCALAR,
        unit="0..1",
        status=FIELD_STATUS_RESERVED,
        visualization_mode=VISUALIZATION_SCALAR_SAMPLES,
        semantic="预留标量通道",
    ),
    FieldChannelDescriptorV0(
        channel_id="density",
        display_name="密度",
        rank=CHANNEL_RANK_SCALAR,
        unit="kg/m³",
        status=FIELD_STATUS_RESERVED,
        visualization_mode=VISUALIZATION_SCALAR_SAMPLES,
        semantic="预留标量通道",
    ),
    FieldChannelDescriptorV0(
        channel_id="temperature",
        display_name="温度",
        rank=CHANNEL_RANK_SCALAR,
        unit="K",
        status=FIELD_STATUS_RESERVED,
        visualization_mode=VISUALIZATION_SCALAR_SAMPLES,
        semantic="预留标量通道",
    ),
    FieldChannelDescriptorV0(
        channel_id="pressure",
        display_name="压力",
        rank=CHANNEL_RANK_SCALAR,
        unit="Pa",
        status=FIELD_STATUS_RESERVED,
        visualization_mode=VISUALIZATION_SCALAR_SAMPLES,
        semantic="预留标量通道",
    ),
    FieldChannelDescriptorV0(
        channel_id="sdf",
        display_name="有符号距离",
        rank=CHANNEL_RANK_SCALAR,
        unit="m",
        status=FIELD_STATUS_RESERVED,
        visualization_mode=VISUALIZATION_SDF_ZERO_CROSSING,
        semantic="有符号距离场",
    ),
    FieldChannelDescriptorV0(
        channel_id="normal",
        display_name="法线",
        rank=CHANNEL_RANK_VECTOR,
        unit="unitless",
        status=FIELD_STATUS_RESERVED,
        visualization_mode=VISUALIZATION_VECTOR_ARROWS,
        semantic="预留向量通道",
    ),
    FieldChannelDescriptorV0(
        channel_id="tensor",
        display_name="张量",
        rank=CHANNEL_RANK_MATRIX,
        unit="explicit",
        status=FIELD_STATUS_RESERVED,
        visualization_mode=VISUALIZATION_VOLUME_STATUS,
        semantic="预留矩阵通道",
    ),
)

FIELD_CHANNEL_REGISTRY_V0 = MappingProxyType({
    descriptor.channel_id: descriptor
    for descriptor in FIELD_CHANNELS_V0
})


def field_channel_descriptor_v0(channel_id: str) -> FieldChannelDescriptorV0:
    key = str(channel_id or "").strip()
    try:
        return FIELD_CHANNEL_REGISTRY_V0[key]
    except KeyError:
        raise ValueError(f"未知 Field channel：{channel_id!r}") from None


def field_channel_reports_v0() -> tuple[dict, ...]:
    return tuple(item.debug_dict() for item in FIELD_CHANNELS_V0)


__all__ = [
    "CHANNEL_RANK_MATRIX",
    "CHANNEL_RANK_SCALAR",
    "CHANNEL_RANK_VECTOR",
    "FIELD_CHANNELS_V0",
    "FIELD_CHANNEL_REGISTRY_V0",
    "FieldChannelDescriptorV0",
    "VISUALIZATION_SDF_ZERO_CROSSING",
    "VISUALIZATION_SCALAR_SAMPLES",
    "VISUALIZATION_VECTOR_ARROWS",
    "VISUALIZATION_VOLUME_STATUS",
    "field_channel_descriptor_v0",
    "field_channel_reports_v0",
]
