"""Physics World 公共 Field native runtime 的 Python 所有权边界。"""

from __future__ import annotations

import numpy as np

from ....Utils.optional_dependencies import import_native_module

from .names import (
    FIELD_STATUS_ACTIVE,
    FIELD_TYPE_WIND,
    VOLUME_SHAPE_BOX,
    VOLUME_SHAPE_SPHERE,
)
from .specs import FieldSnapshotV0


FIELD_NATIVE_RUNTIME_ABI_VERSION = 1
_FIELD_TYPE_CODES = {FIELD_TYPE_WIND: 0}
_VOLUME_SHAPE_CODES = {
    VOLUME_SHAPE_SPHERE: 0,
    VOLUME_SHAPE_BOX: 1,
}
_REQUIRED_SYMBOLS = (
    "field_runtime_v1_create",
    "field_runtime_v1_update_frame",
    "field_runtime_v1_sample_air_velocity",
    "field_runtime_v1_inspect",
    "field_runtime_v1_dispose",
)
_NATIVE_MODULE = None


def native_module():
    global _NATIVE_MODULE
    if _NATIVE_MODULE is None:
        _NATIVE_MODULE = import_native_module("hotools_native")
    missing = tuple(
        name for name in _REQUIRED_SYMBOLS
        if not callable(getattr(_NATIVE_MODULE, name, None))
    )
    if missing:
        raise RuntimeError(
            "hotools_native 缺少 Field runtime API：" + ", ".join(missing)
        )
    return _NATIVE_MODULE


def _readonly_array(values, dtype) -> np.ndarray:
    result = np.ascontiguousarray(values, dtype=dtype)
    result.flags.writeable = False
    return result


def _scope_group_mask(groups) -> int:
    mask = 0
    for group in groups:
        mask |= 1 << (int(group) - 1)
    return mask


def _runtime_payload(snapshot: FieldSnapshotV0) -> tuple:
    fields = tuple(
        item for item in snapshot.fields
        if item.enabled and item.status == FIELD_STATUS_ACTIVE
    )
    count = len(fields)
    world_to_local = np.empty((count, 4, 4), dtype=np.float64)
    directions = np.empty((count, 3), dtype=np.float64)
    wind_values = np.empty((count, 7), dtype=np.float64)
    for index, item in enumerate(fields):
        world_to_local[index] = np.asarray(
            item.volume.world_to_local, dtype=np.float64
        )
        linear = np.asarray(item.volume.world_transform, dtype=np.float64)[:3, :3]
        direction = linear[:, 2]
        direction /= np.linalg.norm(direction)
        directions[index] = direction
        wind_values[index] = (
            item.wind.speed_mps,
            item.wind.turbulence,
            item.wind.spatial_scale_m,
            item.wind.temporal_frequency_hz,
            item.wind.lacunarity,
            item.wind.gain,
            item.blend_weight,
        )

    return (
        tuple(item.field_id for item in fields),
        _readonly_array(
            [_FIELD_TYPE_CODES[item.field_type] for item in fields], np.int32
        ),
        _readonly_array(
            [_VOLUME_SHAPE_CODES[item.volume.shape] for item in fields], np.int32
        ),
        _readonly_array(world_to_local, np.float64),
        _readonly_array(directions, np.float64),
        _readonly_array(wind_values, np.float64),
        _readonly_array([item.wind.octaves for item in fields], np.uint32),
        _readonly_array([item.wind.seed_u32 for item in fields], np.uint32),
        tuple(item.scope.solver_ids for item in fields),
        tuple(item.scope.collection_ids for item in fields),
        tuple(item.scope.include_ids for item in fields),
        tuple(item.scope.exclude_ids for item in fields),
        _readonly_array(
            [_scope_group_mask(item.scope.collision_groups) for item in fields],
            np.uint32,
        ),
    )


class NativeFieldRuntimeV1:
    """持有一个公共 Field runtime handle；禁止把 live bpy 对象传入 native。"""

    def __init__(self, module, handle: int, snapshot: FieldSnapshotV0) -> None:
        self._module = module
        self._handle = int(handle)
        self._config_signature = snapshot.config_signature
        self._value_signature = snapshot.value_signature
        self._snapshot_signature = snapshot.signature
        self._generation = int(snapshot.generation)
        self._frame = int(snapshot.frame)
        self._sample_time_seconds = float(snapshot.sample_time_seconds)
        if self._handle <= 0:
            raise RuntimeError("Field native runtime 返回了无效 handle")

    @classmethod
    def create(cls, snapshot: FieldSnapshotV0, *, module=None):
        if not isinstance(snapshot, FieldSnapshotV0):
            raise TypeError("snapshot 必须是 FieldSnapshotV0")
        module = native_module() if module is None else module
        payload = _runtime_payload(snapshot)
        handle = module.field_runtime_v1_create(
            FIELD_NATIVE_RUNTIME_ABI_VERSION,
            snapshot.signature,
            snapshot.config_signature,
            snapshot.value_signature,
            int(snapshot.generation),
            int(snapshot.frame),
            float(snapshot.sample_time_seconds),
            *payload,
        )
        return cls(module, int(handle), snapshot)

    @property
    def handle(self) -> int:
        if self._handle <= 0:
            raise RuntimeError("Field native runtime 已释放")
        return self._handle

    @property
    def snapshot_signature(self) -> str:
        return self._snapshot_signature

    @property
    def config_signature(self) -> str:
        return self._config_signature

    @property
    def value_signature(self) -> str:
        return self._value_signature

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def frame(self) -> int:
        return self._frame

    @property
    def sample_time_seconds(self) -> float:
        return self._sample_time_seconds

    @property
    def live(self) -> bool:
        return self._handle > 0

    def matches_values(self, snapshot: FieldSnapshotV0) -> bool:
        return (
            isinstance(snapshot, FieldSnapshotV0)
            and self.live
            and snapshot.config_signature == self._config_signature
            and snapshot.value_signature == self._value_signature
        )

    def update_frame(self, snapshot: FieldSnapshotV0) -> None:
        if not self.matches_values(snapshot):
            raise ValueError("Field runtime 只能热更新相同配置与数值的帧元数据")
        self._module.field_runtime_v1_update_frame(
            self.handle,
            snapshot.signature,
            int(snapshot.generation),
            int(snapshot.frame),
            float(snapshot.sample_time_seconds),
        )
        self._snapshot_signature = snapshot.signature
        self._generation = int(snapshot.generation)
        self._frame = int(snapshot.frame)
        self._sample_time_seconds = float(snapshot.sample_time_seconds)

    def sample_air_velocity(
        self,
        positions_world,
        *,
        sample_time_seconds: float | None = None,
        consumer_id: str = "",
        object_id: str = "",
        collection_ids=(),
        collision_groups=(),
    ) -> dict:
        positions = _readonly_array(positions_world, np.float64)
        if positions.ndim != 2 or positions.shape[1] != 3:
            raise ValueError("positions_world 必须是 [N,3]")
        sample_time = (
            self._sample_time_seconds
            if sample_time_seconds is None
            else float(sample_time_seconds)
        )
        result = self._module.field_runtime_v1_sample_air_velocity(
            self.handle,
            positions,
            sample_time,
            str(consumer_id or ""),
            str(object_id or ""),
            tuple(str(value) for value in collection_ids),
            _scope_group_mask(collision_groups),
        )
        values = np.asarray(result["air_velocity_world"], dtype=np.float32)
        participation = np.asarray(result["participation"], dtype=np.uint8)
        if values.shape != positions.shape or participation.shape != (len(positions),):
            raise RuntimeError("Field native runtime 返回了无效采样形状")
        values.flags.writeable = False
        participation.flags.writeable = False
        return {
            "air_velocity_world": values,
            "participation": participation,
            "sample_time_seconds": float(result["sample_time_seconds"]),
            "sampled_field_count": int(result["sampled_field_count"]),
        }

    def debug_snapshot(self) -> dict:
        result = dict(self._module.field_runtime_v1_inspect(self.handle))
        result["cache_owner"] = "NativeFieldRuntimeV1"
        return result

    def dispose(self, _reason: str = "") -> None:
        handle = self._handle
        self._handle = 0
        if handle <= 0:
            return
        self._module.field_runtime_v1_dispose(handle)

    def omni_cache_dispose(self, reason: str) -> None:
        self.dispose(reason)


__all__ = [
    "FIELD_NATIVE_RUNTIME_ABI_VERSION",
    "NativeFieldRuntimeV1",
    "native_module",
]
