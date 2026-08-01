"""Mesh XPBD 面板对象与 socket 自定义对象的不可变 authoring 合同。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


def _pointer(value) -> int:
    callback = getattr(value, "as_pointer", None)
    if not callable(callback):
        return 0
    try:
        return int(callback())
    except (TypeError, ValueError, ReferenceError):
        return 0


def _signature(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _collision_mask(value) -> int:
    if isinstance(value, bool):
        raise ValueError("collided_by_groups 必须是 16-bit 整数掩码")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("collided_by_groups 必须是 16-bit 整数掩码") from None
    try:
        if float(value) != float(result):
            raise ValueError("collided_by_groups 必须是 16-bit 整数掩码")
    except (TypeError, ValueError, OverflowError):
        raise ValueError("collided_by_groups 必须是 16-bit 整数掩码") from None
    if not 0 <= result <= 0xFFFF:
        raise ValueError("collided_by_groups 必须位于 [0, 65535]")
    return result


@dataclass(frozen=True, slots=True)
class MeshXpbdObjectPropertiesSpec:
    """XPBD 从通用 Mesh 面板或自定义 socket 实际消费的对象字段。"""

    radius_vertex_group: str = ""
    pin_enabled: bool = False
    pin_vertex_group: str = ""
    collided_by_groups: int = 0

    def __post_init__(self) -> None:
        if type(self.pin_enabled) is not bool:
            raise TypeError("pin_enabled 必须是 bool")
        object.__setattr__(
            self, "radius_vertex_group", str(self.radius_vertex_group or "")
        )
        object.__setattr__(
            self, "pin_vertex_group", str(self.pin_vertex_group or "")
        )
        object.__setattr__(
            self, "collided_by_groups", _collision_mask(self.collided_by_groups)
        )

    def debug_dict(self) -> dict:
        return {
            "radius_vertex_group": self.radius_vertex_group,
            "pin_enabled": self.pin_enabled,
            "pin_vertex_group": self.pin_vertex_group,
            "collided_by_groups": self.collided_by_groups,
        }


@dataclass(frozen=True, slots=True)
class MeshXpbdObjectSpec:
    """一个 Mesh 与已解析对象属性的快照，不携带 solver 参数。"""

    source_object: object
    properties: MeshXpbdObjectPropertiesSpec
    property_origin: str

    def __post_init__(self) -> None:
        if getattr(self.source_object, "type", None) != "MESH":
            raise TypeError("Mesh XPBD 对象只接受 Mesh Object")
        if not isinstance(self.properties, MeshXpbdObjectPropertiesSpec):
            raise TypeError("Mesh XPBD 对象需要 MeshXpbdObjectPropertiesSpec")
        origin = str(self.property_origin or "").strip().lower()
        if origin not in {"panel", "socket"}:
            raise ValueError("property_origin 必须是 panel 或 socket")
        object.__setattr__(self, "property_origin", origin)

    @property
    def signature(self) -> str:
        return _signature({
            "source_object_ptr": _pointer(self.source_object),
            "source_data_ptr": _pointer(getattr(self.source_object, "data", None)),
            "properties": self.properties.debug_dict(),
        })

    def debug_dict(self) -> dict:
        return {
            "schema": "mesh_xpbd_object_v1",
            "property_origin": self.property_origin,
            "source_name": str(
                getattr(self.source_object, "name_full", "")
                or getattr(self.source_object, "name", "")
                or ""
            ),
            "source_object_ptr": _pointer(self.source_object),
            "source_data_ptr": _pointer(getattr(self.source_object, "data", None)),
            "properties": self.properties.debug_dict(),
            "signature": self.signature,
        }


def _flatten_objects(values) -> tuple[object, ...]:
    pending = [values]
    result = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
            continue
        result.append(value)
    return tuple(result)


def read_mesh_xpbd_panel_object(source_object) -> MeshXpbdObjectSpec:
    """读取通用 Mesh 面板中 XPBD 声明消费的对象字段。"""

    if getattr(source_object, "type", None) != "MESH":
        raise TypeError("Mesh XPBD 对象只接受 Mesh Object")
    panel = getattr(source_object, "hotools_mesh_collision", None)
    if panel is None:
        raise ValueError("Mesh Object 没有注册 hotools_mesh_collision 属性")
    if not bool(getattr(panel, "enabled", False)):
        raise ValueError("Mesh Object 没有启用简单布料")
    return MeshXpbdObjectSpec(
        source_object=source_object,
        properties=MeshXpbdObjectPropertiesSpec(
            radius_vertex_group=getattr(panel, "radius_vertex_group"),
            pin_enabled=getattr(panel, "pin_enabled"),
            pin_vertex_group=getattr(panel, "pin_vertex_group"),
            collided_by_groups=getattr(panel, "collided_by_groups"),
        ),
        property_origin="panel",
    )


def read_mesh_xpbd_panel_objects(values) -> tuple[MeshXpbdObjectSpec, ...]:
    result = []
    for value in _flatten_objects(values):
        if getattr(value, "type", None) != "MESH":
            raise TypeError("Mesh XPBD 对象只接受 Mesh Object")
        panel = getattr(value, "hotools_mesh_collision", None)
        if panel is None:
            raise ValueError("Mesh Object 没有注册 hotools_mesh_collision 属性")
        if bool(getattr(panel, "enabled", False)):
            result.append(read_mesh_xpbd_panel_object(value))
    return tuple(result)


def make_mesh_xpbd_custom_object(
    source_object,
    *,
    radius_vertex_group: str = "",
    pin_enabled: bool = False,
    pin_vertex_group: str = "",
    collided_by_groups: int = 0,
) -> MeshXpbdObjectSpec:
    """只使用 socket 值创建对象；默认不接受任何外部碰撞组。"""

    return MeshXpbdObjectSpec(
        source_object=source_object,
        properties=MeshXpbdObjectPropertiesSpec(
            radius_vertex_group=radius_vertex_group,
            pin_enabled=pin_enabled,
            pin_vertex_group=pin_vertex_group,
            collided_by_groups=collided_by_groups,
        ),
        property_origin="socket",
    )


def make_mesh_xpbd_custom_objects(values, **properties) -> tuple[MeshXpbdObjectSpec, ...]:
    return tuple(
        make_mesh_xpbd_custom_object(value, **properties)
        for value in _flatten_objects(values)
    )


__all__ = [
    "MeshXpbdObjectPropertiesSpec",
    "MeshXpbdObjectSpec",
    "make_mesh_xpbd_custom_object",
    "make_mesh_xpbd_custom_objects",
    "read_mesh_xpbd_panel_object",
    "read_mesh_xpbd_panel_objects",
]
