"""确定性的 WindV0 时空向量噪声与原始风速采样。"""

from __future__ import annotations

import math

import numpy as np

from .names import WIND_NOISE_ALGORITHM_VERSION
from .specs import WindPayloadV0
from .volume import coerce_positions_world_v0


_U64_MASK = np.uint64(0xFFFFFFFFFFFFFFFF)
_HASH_AXIS_SALTS = (
    np.uint64(0x9E3779B97F4A7C15),
    np.uint64(0xD1B54A32D192ED03),
    np.uint64(0x94D049BB133111EB),
    np.uint64(0x8538ECB5BD456EA3),
)
_HASH_CHANNEL_SALTS = (
    np.uint64(0xA24BAED4963EE407),
    np.uint64(0x9FB21C651E98DF25),
    np.uint64(0xC13FA9A902A6328F),
)
_OCTAVE_SEED_STEP = 0x9E3779B9
_INV_SQRT3 = 1.0 / math.sqrt(3.0)


def _mix_u64(values: np.ndarray) -> np.ndarray:
    """固定版 SplitMix64 finalizer；整数溢出是算法定义的一部分。"""
    values = np.asarray(values, dtype=np.uint64)
    with np.errstate(over="ignore"):
        values = (values ^ (values >> np.uint64(30))) * np.uint64(
            0xBF58476D1CE4E5B9
        )
        values = (values ^ (values >> np.uint64(27))) * np.uint64(
            0x94D049BB133111EB
        )
    return (values ^ (values >> np.uint64(31))) & _U64_MASK


def _mix_u64_scalar(value: int) -> int:
    value &= 0xFFFFFFFFFFFFFFFF
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return (value ^ (value >> 31)) & 0xFFFFFFFFFFFFFFFF


def _lattice_values_v0(
    coordinates_i64: np.ndarray,
    *,
    seed_u32: int,
    channel: int,
) -> np.ndarray:
    count = coordinates_i64.shape[0]
    seed = np.uint64(int(seed_u32) & 0xFFFFFFFF)
    state = np.full(count, seed ^ _HASH_CHANNEL_SALTS[channel], dtype=np.uint64)
    for axis, salt in enumerate(_HASH_AXIS_SALTS):
        coordinate_bits = np.ascontiguousarray(
            coordinates_i64[:, axis], dtype=np.int64
        ).view(np.uint64)
        with np.errstate(over="ignore"):
            salted_coordinates = coordinate_bits + salt
        state = _mix_u64(state ^ _mix_u64(salted_coordinates))
    mantissa = (state >> np.uint64(40)).astype(np.float64)
    return (mantissa * (2.0 / float(1 << 24)) - 1.0) * _INV_SQRT3


def _lattice_value_reference_v0(
    coordinates: tuple[int, int, int, int],
    *,
    seed_u32: int,
    channel: int,
) -> float:
    state = (int(seed_u32) & 0xFFFFFFFF) ^ int(_HASH_CHANNEL_SALTS[channel])
    for coordinate, salt in zip(coordinates, _HASH_AXIS_SALTS):
        coordinate_bits = int(coordinate) & 0xFFFFFFFFFFFFFFFF
        state = _mix_u64_scalar(
            state ^ _mix_u64_scalar(coordinate_bits + int(salt))
        )
    mantissa = state >> 40
    return (mantissa * (2.0 / float(1 << 24)) - 1.0) * _INV_SQRT3


def vector_value_noise4_reference_v0(
    coordinate_xyzt,
    *,
    seed_u32: int,
) -> tuple[float, float, float]:
    """不依赖 NumPy 批处理的标量参考实现，用于 ABI 差分验收。"""
    try:
        coordinate = tuple(float(value) for value in coordinate_xyzt)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("coordinate_xyzt 必须是有限 [4] 向量") from None
    if len(coordinate) != 4 or not all(math.isfinite(value) for value in coordinate):
        raise ValueError("coordinate_xyzt 必须是有限 [4] 向量")
    if not isinstance(seed_u32, (int, np.integer)) or isinstance(seed_u32, bool):
        raise ValueError("seed_u32 必须是 uint32 整数")
    if int(seed_u32) < 0 or int(seed_u32) > 0xFFFFFFFF:
        raise ValueError("seed_u32 必须位于 0..4294967295")
    base = tuple(math.floor(value) for value in coordinate)
    fraction = tuple(value - floor for value, floor in zip(coordinate, base))
    fade = tuple(
        value * value * value * (value * (value * 6.0 - 15.0) + 10.0)
        for value in fraction
    )
    result = [0.0, 0.0, 0.0]
    for corner in range(16):
        bits = tuple((corner >> axis) & 1 for axis in range(4))
        lattice = tuple(base[axis] + bits[axis] for axis in range(4))
        weight = math.prod(
            fade[axis] if bits[axis] else 1.0 - fade[axis]
            for axis in range(4)
        )
        for channel in range(3):
            result[channel] += weight * _lattice_value_reference_v0(
                lattice,
                seed_u32=int(seed_u32),
                channel=channel,
            )
    return tuple(result)


def vector_value_noise4_v0(
    coordinates_xyzt,
    *,
    seed_u32: int,
) -> np.ndarray:
    """采样 V0 四维三分量 value noise，结果范围约为 ``[-1, 1]``。"""
    try:
        coordinates = np.asarray(coordinates_xyzt, dtype=np.float64)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("coordinates_xyzt 必须能转换为有限浮点数组") from None
    scalar = coordinates.ndim == 1
    if scalar:
        if coordinates.shape != (4,):
            raise ValueError("单点 coordinates_xyzt 必须是 [4]")
        coordinates = coordinates.reshape(1, 4)
    elif coordinates.ndim != 2 or coordinates.shape[1] != 4:
        raise ValueError("批量 coordinates_xyzt 必须是 [N, 4]")
    if not np.all(np.isfinite(coordinates)):
        raise ValueError("coordinates_xyzt 只能包含有限浮点数")
    if not isinstance(seed_u32, (int, np.integer)) or isinstance(seed_u32, bool):
        raise ValueError("seed_u32 必须是 uint32 整数")
    if int(seed_u32) < 0 or int(seed_u32) > 0xFFFFFFFF:
        raise ValueError("seed_u32 必须位于 0..4294967295")

    floored = np.floor(coordinates)
    int64_limit = float(2**63 - 2)
    if np.any(floored < -int64_limit) or np.any(floored > int64_limit):
        raise ValueError("coordinates_xyzt 超出 WindV0 可寻址晶格范围")
    base = floored.astype(np.int64)
    fraction = coordinates - base
    fade = fraction**3 * (fraction * (fraction * 6.0 - 15.0) + 10.0)
    result = np.zeros((coordinates.shape[0], 3), dtype=np.float64)

    for corner in range(16):
        bits = np.asarray(
            tuple((corner >> axis) & 1 for axis in range(4)),
            dtype=np.int64,
        )
        lattice = base + bits
        weight = np.ones(coordinates.shape[0], dtype=np.float64)
        for axis in range(4):
            weight *= fade[:, axis] if bits[axis] else 1.0 - fade[:, axis]
        for channel in range(3):
            result[:, channel] += weight * _lattice_values_v0(
                lattice,
                seed_u32=int(seed_u32),
                channel=channel,
            )

    return np.ascontiguousarray(result, dtype=np.float64)


def sample_wind_raw_v0(
    payload: WindPayloadV0,
    direction_world,
    positions_world,
    sample_time_seconds: float,
) -> np.ndarray:
    """在应用 Volume 权重前采样 WindV0 的世界空间空气速度。"""
    if not isinstance(payload, WindPayloadV0):
        raise TypeError("payload 必须是 WindPayloadV0")
    if payload.noise_algorithm_version != WIND_NOISE_ALGORITHM_VERSION:
        raise ValueError(
            f"不支持的 Wind noise algorithm: {payload.noise_algorithm_version}"
        )
    positions, _ = coerce_positions_world_v0(positions_world)
    try:
        direction = np.asarray(direction_world, dtype=np.float64)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("direction_world 必须是有限 [3] 向量") from None
    if direction.shape != (3,) or not np.all(np.isfinite(direction)):
        raise ValueError("direction_world 必须是有限 [3] 向量")
    direction_length = float(np.linalg.norm(direction))
    if direction_length <= 1.0e-8:
        raise ValueError("direction_world 不能是零向量")
    direction = direction / direction_length
    try:
        sample_time = float(sample_time_seconds)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("sample_time_seconds 必须是有限浮点数") from None
    if not math.isfinite(sample_time) or sample_time < 0.0:
        raise ValueError("sample_time_seconds 必须是非负有限浮点数")

    base = np.broadcast_to(
        direction * payload.speed_mps,
        (positions.shape[0], 3),
    ).copy()
    if payload.turbulence == 0.0 or payload.speed_mps == 0.0:
        return np.ascontiguousarray(base, dtype=np.float32)

    turbulence_sum = np.zeros_like(base)
    amplitude = 1.0
    amplitude_sum = 0.0
    spatial_frequency = 1.0
    time_coordinate = sample_time * payload.temporal_frequency_hz
    for octave in range(payload.octaves):
        coordinates = np.empty((positions.shape[0], 4), dtype=np.float64)
        coordinates[:, :3] = (
            positions / payload.spatial_scale_m * spatial_frequency
        )
        coordinates[:, 3] = time_coordinate
        octave_seed = (
            payload.seed_u32 + octave * _OCTAVE_SEED_STEP
        ) & 0xFFFFFFFF
        turbulence_sum += amplitude * vector_value_noise4_v0(
            coordinates,
            seed_u32=octave_seed,
        )
        amplitude_sum += amplitude
        amplitude *= payload.gain
        spatial_frequency *= payload.lacunarity

    delta = (
        payload.speed_mps
        * payload.turbulence
        / amplitude_sum
        * turbulence_sum
    )
    return np.ascontiguousarray(base + delta, dtype=np.float32)


def sample_wind_raw_reference_v0(
    payload: WindPayloadV0,
    direction_world,
    position_world,
    sample_time_seconds: float,
) -> tuple[float, float, float]:
    """WindV0 完整单点参考实现，不调用批量 noise 路径。"""
    if not isinstance(payload, WindPayloadV0):
        raise TypeError("payload 必须是 WindPayloadV0")
    try:
        direction = tuple(float(value) for value in direction_world)
        position = tuple(float(value) for value in position_world)
        sample_time = float(sample_time_seconds)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("WindV0 单点输入必须是有限浮点值") from None
    if len(direction) != 3 or len(position) != 3:
        raise ValueError("direction_world 与 position_world 必须是 [3]")
    if not all(math.isfinite(value) for value in direction + position):
        raise ValueError("WindV0 单点输入必须是有限浮点值")
    if not math.isfinite(sample_time) or sample_time < 0.0:
        raise ValueError("sample_time_seconds 必须是非负有限浮点数")
    direction_length = math.sqrt(sum(value * value for value in direction))
    if direction_length <= 1.0e-8:
        raise ValueError("direction_world 不能是零向量")
    base = tuple(
        payload.speed_mps * value / direction_length for value in direction
    )
    if payload.turbulence == 0.0 or payload.speed_mps == 0.0:
        return base

    accumulated = [0.0, 0.0, 0.0]
    amplitude = 1.0
    amplitude_sum = 0.0
    spatial_frequency = 1.0
    time_coordinate = sample_time * payload.temporal_frequency_hz
    for octave in range(payload.octaves):
        coordinate = tuple(
            value / payload.spatial_scale_m * spatial_frequency
            for value in position
        ) + (time_coordinate,)
        octave_seed = (
            payload.seed_u32 + octave * _OCTAVE_SEED_STEP
        ) & 0xFFFFFFFF
        noise = vector_value_noise4_reference_v0(
            coordinate,
            seed_u32=octave_seed,
        )
        for channel in range(3):
            accumulated[channel] += amplitude * noise[channel]
        amplitude_sum += amplitude
        amplitude *= payload.gain
        spatial_frequency *= payload.lacunarity
    scale = payload.speed_mps * payload.turbulence / amplitude_sum
    return tuple(base[index] + scale * accumulated[index] for index in range(3))


__all__ = [
    "sample_wind_raw_v0",
    "sample_wind_raw_reference_v0",
    "vector_value_noise4_reference_v0",
    "vector_value_noise4_v0",
]
