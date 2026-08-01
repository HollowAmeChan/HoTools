"""Field Volume V0 的世界空间边界与临时权重采样。"""

from __future__ import annotations

import math

import numpy as np

from .names import VOLUME_SHAPE_BOX, VOLUME_SHAPE_SPHERE
from .specs import VolumeSpecV0


def coerce_positions_world_v0(positions_world) -> tuple[np.ndarray, bool]:
    """规范化世界空间位置；返回连续的 ``[N, 3]`` 数组和单点标记。"""
    try:
        values = np.asarray(positions_world, dtype=np.float64)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("positions_world 必须能转换为有限浮点数组") from None

    scalar = values.ndim == 1
    if scalar:
        if values.shape != (3,):
            raise ValueError("单点 positions_world 必须是 [3]")
        values = values.reshape(1, 3)
    elif values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("批量 positions_world 必须是 [N, 3]")
    if not np.all(np.isfinite(values)):
        raise ValueError("positions_world 只能包含有限浮点数")
    return np.ascontiguousarray(values, dtype=np.float64), scalar


def positions_to_volume_local_v0(
    volume: VolumeSpecV0,
    positions_world,
) -> tuple[np.ndarray, bool]:
    """把世界空间位置转换到单位球或单位盒的局部坐标。"""
    if not isinstance(volume, VolumeSpecV0):
        raise TypeError("volume 必须是 VolumeSpecV0")
    positions, scalar = coerce_positions_world_v0(positions_world)
    world_to_local = np.asarray(volume.world_to_local, dtype=np.float64)
    homogeneous = np.empty((positions.shape[0], 4), dtype=np.float64)
    homogeneous[:, :3] = positions
    homogeneous[:, 3] = 1.0
    local = homogeneous @ world_to_local.T
    return np.ascontiguousarray(local[:, :3]), scalar


def sample_volume_weights_v0(
    volume: VolumeSpecV0,
    positions_world,
) -> np.ndarray:
    """采样 V0 临时衰减：球形线性衰减，方形硬边界且无衰减。"""
    local, _ = positions_to_volume_local_v0(volume, positions_world)
    if volume.shape == VOLUME_SHAPE_SPHERE:
        radius = np.linalg.norm(local, axis=1)
        weights = np.clip(1.0 - radius, 0.0, 1.0)
    elif volume.shape == VOLUME_SHAPE_BOX:
        weights = np.all(np.abs(local) <= 1.0, axis=1).astype(
            np.float64
        )
    else:
        raise ValueError(f"不支持的 Field Volume shape: {volume.shape!r}")
    return np.ascontiguousarray(weights, dtype=np.float32)


def sample_volume_weight_v0(volume: VolumeSpecV0, position_world) -> float:
    """单点版本，语义与批量采样器完全一致。"""
    weights = sample_volume_weights_v0(volume, position_world)
    return float(weights[0])


def sample_volume_weight_reference_v0(
    volume: VolumeSpecV0,
    position_world,
) -> float:
    """不走 NumPy 批处理的标量参考实现，用于完整 sampler 差分测试。"""
    if not isinstance(volume, VolumeSpecV0):
        raise TypeError("volume 必须是 VolumeSpecV0")
    try:
        position = tuple(float(value) for value in position_world)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("position_world 必须是有限 [3] 向量") from None
    if len(position) != 3 or not all(math.isfinite(value) for value in position):
        raise ValueError("position_world 必须是有限 [3] 向量")
    local = tuple(
        sum(row[index] * position[index] for index in range(3)) + row[3]
        for row in volume.world_to_local[:3]
    )
    if volume.shape == VOLUME_SHAPE_SPHERE:
        radius = math.sqrt(sum(value * value for value in local))
        return min(max(1.0 - radius, 0.0), 1.0)
    if volume.shape == VOLUME_SHAPE_BOX:
        return 1.0 if all(abs(value) <= 1.0 for value in local) else 0.0
    raise ValueError(f"不支持的 Field Volume shape: {volume.shape!r}")


def wind_direction_world_v0(volume: VolumeSpecV0) -> np.ndarray:
    """读取 Volume transform 的 local +Z，去除 scale 后返回世界单位方向。"""
    if not isinstance(volume, VolumeSpecV0):
        raise TypeError("volume 必须是 VolumeSpecV0")
    linear = np.asarray(volume.world_transform, dtype=np.float64)[:3, :3]
    direction = linear[:, 2]
    length = float(np.linalg.norm(direction))
    if not np.isfinite(length) or length <= 1.0e-8:
        raise ValueError("Field transform 的 local +Z 方向无效")
    return np.ascontiguousarray(direction / length, dtype=np.float64)


__all__ = [
    "coerce_positions_world_v0",
    "positions_to_volume_local_v0",
    "sample_volume_weight_v0",
    "sample_volume_weight_reference_v0",
    "sample_volume_weights_v0",
    "wind_direction_world_v0",
]
