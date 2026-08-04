"""Bone XPBD 任务规格与 dirty 边界。"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math

from .names import BONE_XPBD_SLOT_KIND
from .object_spec import BoneXpbdObjectSpec


def _signature(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _finite(name: str, value, minimum: float | None = None) -> float:
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        suffix = f"且 >= {minimum}" if minimum is not None else ""
        raise ValueError(f"{name} 必须是有限浮点数{suffix}")
    return result


def _int(name: str, value) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是整数")
    result = int(value)
    if float(value) != float(result):
        raise ValueError(f"{name} 必须是整数")
    return result


def _float3(name: str, value) -> tuple[float, float, float]:
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须是有限 float3") from None
    if len(result) != 3 or not all(math.isfinite(item) for item in result):
        raise ValueError(f"{name} 必须是有限 float3")
    return result


def make_bone_xpbd_slot_id(object_spec: BoneXpbdObjectSpec) -> str:
    return (
        f"{BONE_XPBD_SLOT_KIND}:{object_spec.armature_ptr}:"
        f"{object_spec.armature_data_ptr}:{object_spec.source_signature}"
    )


@dataclass(frozen=True, slots=True)
class BoneXpbdTaskSpec:
    object_spec: BoneXpbdObjectSpec
    enabled: bool = True
    tail_follow: bool = True
    weld_shared_endpoints: bool = True
    weld_tolerance: float = 1.0e-5
    collision_enabled: bool = False
    particle_radius: float = 0.05
    collided_by_groups: int = 0
    damping: float = 0.02
    stretch_compliance: float = 0.0
    bend_compliance: float = 0.0
    iterations: int = 16
    gravity_direction: tuple[float, float, float] = (0.0, 0.0, -1.0)
    gravity_power: float = 9.8
    slot_id: str = field(init=False)
    static_signature: str = field(init=False)
    parameter_signature: str = field(init=False)
    signature: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.object_spec, BoneXpbdObjectSpec):
            raise TypeError("Bone XPBD 任务需要 BoneXpbdObjectSpec")
        if type(self.enabled) is not bool or type(self.tail_follow) is not bool:
            raise TypeError("enabled/tail_follow 必须是 bool")
        if type(self.weld_shared_endpoints) is not bool:
            raise TypeError("weld_shared_endpoints 必须是 bool")
        tolerance = _finite("weld_tolerance", self.weld_tolerance, 0.0)
        radius = _finite("particle_radius", self.particle_radius, 0.0)
        damping = _finite("damping", self.damping, 0.0)
        if damping > 1.0:
            raise ValueError("damping 必须 <= 1.0")
        stretch = _finite("stretch_compliance", self.stretch_compliance, 0.0)
        bend = _finite("bend_compliance", self.bend_compliance, 0.0)
        gravity_power = _finite("gravity_power", self.gravity_power, 0.0)
        gravity_direction = _float3("gravity_direction", self.gravity_direction)
        iterations = _int("iterations", self.iterations)
        if not 0 <= iterations <= 64:
            raise ValueError("iterations 必须位于 [0, 64]")
        mask = _int("collided_by_groups", self.collided_by_groups)
        if not 0 <= mask <= 0xFFFF:
            raise ValueError("collided_by_groups 必须是 16-bit 掩码")
        static = _signature({
            "source": self.object_spec.source_signature,
            "weld_shared_endpoints": self.weld_shared_endpoints,
            "weld_tolerance": tolerance,
            "collision_enabled": bool(self.collision_enabled),
            "particle_radius": radius,
        })
        parameters = _signature({
            "enabled": self.enabled,
            "tail_follow": self.tail_follow,
            "collided_by_groups": mask,
            "damping": damping,
            "stretch_compliance": stretch,
            "bend_compliance": bend,
            "iterations": iterations,
            "gravity_direction": gravity_direction,
            "gravity_power": gravity_power,
        })
        object.__setattr__(self, "weld_tolerance", tolerance)
        object.__setattr__(self, "collision_enabled", bool(self.collision_enabled))
        object.__setattr__(self, "particle_radius", radius)
        object.__setattr__(self, "collided_by_groups", mask)
        object.__setattr__(self, "damping", damping)
        object.__setattr__(self, "stretch_compliance", stretch)
        object.__setattr__(self, "bend_compliance", bend)
        object.__setattr__(self, "iterations", iterations)
        object.__setattr__(self, "gravity_direction", gravity_direction)
        object.__setattr__(self, "gravity_power", gravity_power)
        object.__setattr__(self, "slot_id", make_bone_xpbd_slot_id(self.object_spec))
        object.__setattr__(self, "static_signature", static)
        object.__setattr__(self, "parameter_signature", parameters)
        object.__setattr__(self, "signature", _signature({"static": static, "parameters": parameters}))

    @property
    def armature(self):
        return self.object_spec.armature

    @property
    def bone_names(self) -> tuple[str, ...]:
        return self.object_spec.bone_names

    def debug_dict(self) -> dict:
        return {
            "schema": "bone_xpbd_task_v1",
            "slot_id": self.slot_id,
            "armature_name": self.object_spec.armature_name,
            "bone_names": self.bone_names,
            "enabled": self.enabled,
            "tail_follow": self.tail_follow,
            "weld_shared_endpoints": self.weld_shared_endpoints,
            "weld_tolerance": self.weld_tolerance,
            "collision_enabled": self.collision_enabled,
            "particle_radius": self.particle_radius,
            "collided_by_groups": self.collided_by_groups,
            "damping": self.damping,
            "stretch_compliance": self.stretch_compliance,
            "bend_compliance": self.bend_compliance,
            "iterations": self.iterations,
            "gravity_direction": self.gravity_direction,
            "gravity_power": self.gravity_power,
            "static_signature": self.static_signature,
            "parameter_signature": self.parameter_signature,
        }


def build_bone_xpbd_task_specs(values) -> tuple[BoneXpbdTaskSpec, ...]:
    pending = [values]
    result = []
    slot_ids = set()
    occupied_bones = set()
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
            continue
        if not isinstance(value, BoneXpbdTaskSpec):
            raise TypeError("Bone XPBD 模拟步只接受 BoneXpbdTaskSpec")
        if not value.enabled:
            result.append(value)
            continue
        if value.slot_id in slot_ids:
            raise ValueError(f"Bone XPBD task 重复: {value.slot_id}")
        for name in value.bone_names:
            key = (
                value.object_spec.armature_ptr,
                value.object_spec.armature_data_ptr,
                name,
            )
            if key in occupied_bones:
                raise ValueError(f"Bone XPBD task 重叠写回骨骼 {name!r}")
            occupied_bones.add(key)
        slot_ids.add(value.slot_id)
        result.append(value)
    return tuple(result)


__all__ = [
    "BoneXpbdTaskSpec",
    "build_bone_xpbd_task_specs",
    "make_bone_xpbd_slot_id",
]
