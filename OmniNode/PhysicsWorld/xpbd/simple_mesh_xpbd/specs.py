"""Mesh XPBD 节点输入到 Physics World task 的纯宿主合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any

from .names import MESH_XPBD_SLOT_KIND


def _pointer(value: Any) -> int:
    callback = getattr(value, "as_pointer", None)
    if not callable(callback):
        return 0
    try:
        return int(callback())
    except (TypeError, ValueError, ReferenceError):
        return 0


def _stable_signature(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _finite_float(name: str, value: Any, *, minimum: float | None = None) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} 必须是有限浮点数")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} 必须 >= {minimum}")
    return result


def _finite_float3(name: str, value: Any) -> tuple[float, float, float]:
    try:
        values = tuple(float(component) for component in value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须是 3 个有限浮点数") from None
    if len(values) != 3 or not all(math.isfinite(component) for component in values):
        raise ValueError(f"{name} 必须是 3 个有限浮点数")
    return values


def _strict_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是整数")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} 必须是整数") from None
    try:
        if float(value) != float(result):
            raise ValueError(f"{name} 必须是整数")
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} 必须是整数") from None
    return result


def make_mesh_xpbd_slot_id(source_object_ptr: int, source_data_ptr: int) -> str:
    object_ptr = int(source_object_ptr)
    data_ptr = int(source_data_ptr)
    if object_ptr <= 0 or data_ptr <= 0:
        raise ValueError("Mesh XPBD slot identity 必须包含有效 object/data pointer")
    return f"{MESH_XPBD_SLOT_KIND}:{object_ptr}:{data_ptr}"


@dataclass(frozen=True, slots=True)
class MeshXpbdTaskSpec:
    """一个源 Mesh 对应一个稳定 slot 的 authoring task。"""

    source_object: Any
    enabled: bool = True
    pin_enabled: bool = False
    pin_vertex_group: str = ""
    collision_enabled: bool = False
    collision_radius: float = 0.0
    radius_vertex_group: str = ""
    collided_by_groups: int = 0
    damping: float = 0.02
    stretch_compliance: float = 0.0
    bend_compliance: float = 0.001
    iterations: int = 6
    gravity_direction: tuple[float, float, float] = (0.0, 0.0, -1.0)
    gravity_power: float = 9.8
    source_object_ptr: int = field(init=False)
    source_data_ptr: int = field(init=False)
    source_name: str = field(init=False)
    slot_id: str = field(init=False)
    topology_identity: str = field(init=False)
    static_signature: str = field(init=False)
    parameter_signature: str = field(init=False)
    signature: str = field(init=False)

    def __post_init__(self) -> None:
        source = self.source_object
        if source is None or str(getattr(source, "type", "") or "") != "MESH":
            raise ValueError("MeshXpbdTaskSpec.source_object 必须是 MESH Object")
        data = getattr(source, "data", None)
        object_ptr = _pointer(source)
        data_ptr = _pointer(data)
        if object_ptr <= 0 or data_ptr <= 0:
            raise ValueError("MeshXpbdTaskSpec.source_object 必须有稳定 object/data identity")

        collision_radius = _finite_float(
            "collision_radius", self.collision_radius, minimum=0.0
        )
        damping = _finite_float("damping", self.damping, minimum=0.0)
        if damping > 1.0:
            raise ValueError("damping 必须 <= 1.0")
        stretch_compliance = _finite_float(
            "stretch_compliance", self.stretch_compliance, minimum=0.0
        )
        bend_compliance = _finite_float(
            "bend_compliance", self.bend_compliance, minimum=0.0
        )
        gravity_power = _finite_float(
            "gravity_power", self.gravity_power, minimum=0.0
        )
        gravity_direction = _finite_float3(
            "gravity_direction", self.gravity_direction
        )
        iterations = _strict_int("iterations", self.iterations)
        if iterations < 0 or iterations > 64:
            raise ValueError("iterations 必须位于 [0, 64]")
        collided_by_groups = _strict_int(
            "collided_by_groups", self.collided_by_groups
        )
        if collided_by_groups < 0 or collided_by_groups > 0xFFFF:
            raise ValueError("collided_by_groups 必须位于 Physics World 16 组掩码范围")

        source_name = str(
            getattr(source, "name_full", "") or getattr(source, "name", "") or ""
        )
        topology_identity = f"{object_ptr}:{data_ptr}"
        static_payload = {
            "topology_identity": topology_identity,
            "pin_enabled": bool(self.pin_enabled),
            "pin_vertex_group": str(self.pin_vertex_group or ""),
            "collision_enabled": bool(self.collision_enabled),
            "collision_radius": collision_radius,
            "radius_vertex_group": str(self.radius_vertex_group or ""),
        }
        parameter_payload = {
            "enabled": bool(self.enabled),
            "collided_by_groups": collided_by_groups,
            "damping": damping,
            "stretch_compliance": stretch_compliance,
            "bend_compliance": bend_compliance,
            "iterations": iterations,
            "gravity_direction": gravity_direction,
            "gravity_power": gravity_power,
        }
        static_signature = _stable_signature(static_payload)
        parameter_signature = _stable_signature(parameter_payload)

        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "pin_enabled", bool(self.pin_enabled))
        object.__setattr__(self, "pin_vertex_group", str(self.pin_vertex_group or ""))
        object.__setattr__(self, "collision_enabled", bool(self.collision_enabled))
        object.__setattr__(self, "collision_radius", collision_radius)
        object.__setattr__(self, "radius_vertex_group", str(self.radius_vertex_group or ""))
        object.__setattr__(self, "collided_by_groups", collided_by_groups)
        object.__setattr__(self, "damping", damping)
        object.__setattr__(self, "stretch_compliance", stretch_compliance)
        object.__setattr__(self, "bend_compliance", bend_compliance)
        object.__setattr__(self, "iterations", iterations)
        object.__setattr__(self, "gravity_direction", gravity_direction)
        object.__setattr__(self, "gravity_power", gravity_power)
        object.__setattr__(self, "source_object_ptr", object_ptr)
        object.__setattr__(self, "source_data_ptr", data_ptr)
        object.__setattr__(self, "source_name", source_name)
        object.__setattr__(self, "slot_id", make_mesh_xpbd_slot_id(object_ptr, data_ptr))
        object.__setattr__(self, "topology_identity", topology_identity)
        object.__setattr__(self, "static_signature", static_signature)
        object.__setattr__(self, "parameter_signature", parameter_signature)
        object.__setattr__(self, "signature", _stable_signature({
            "static": static_signature,
            "parameters": parameter_signature,
        }))

    def debug_dict(self) -> dict:
        return {
            "schema": "mesh_xpbd_task_v1",
            "slot_id": self.slot_id,
            "source_name": self.source_name,
            "source_object_ptr": self.source_object_ptr,
            "source_data_ptr": self.source_data_ptr,
            "topology_identity": self.topology_identity,
            "static_signature": self.static_signature,
            "parameter_signature": self.parameter_signature,
            "signature": self.signature,
            "enabled": self.enabled,
            "pin_enabled": self.pin_enabled,
            "pin_vertex_group": self.pin_vertex_group,
            "collision_enabled": self.collision_enabled,
            "collision_radius": self.collision_radius,
            "radius_vertex_group": self.radius_vertex_group,
            "collided_by_groups": self.collided_by_groups,
            "damping": self.damping,
            "stretch_compliance": self.stretch_compliance,
            "bend_compliance": self.bend_compliance,
            "iterations": self.iterations,
            "gravity_direction": self.gravity_direction,
            "gravity_power": self.gravity_power,
        }


def _flatten_task_values(values) -> list:
    pending = list(values) if isinstance(values, (list, tuple)) else [values]
    flattened = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
            continue
        flattened.append(value)
    return flattened


def build_mesh_xpbd_task_specs(values) -> tuple[MeshXpbdTaskSpec, ...]:
    specs = []
    slot_ids = set()
    for value in _flatten_task_values(values):
        if isinstance(value, MeshXpbdTaskSpec):
            spec = value
        elif isinstance(value, dict):
            spec = MeshXpbdTaskSpec(**value)
        else:
            raise TypeError("Mesh XPBD task 必须是 MeshXpbdTaskSpec 或参数字典")
        if spec.slot_id in slot_ids:
            raise ValueError(f"Mesh XPBD source 重复: {spec.slot_id}")
        slot_ids.add(spec.slot_id)
        specs.append(spec)
    return tuple(specs)
