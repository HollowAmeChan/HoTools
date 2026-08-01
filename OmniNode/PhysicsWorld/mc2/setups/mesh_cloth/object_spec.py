"""MeshCloth 对象 authoring：真实 Blender Object 与显式属性分离。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from ...source_identity import mc2_source_token
from ....simple_cloth.schema import SIMPLE_CLOTH_RNA_FIELDS


MC2_MESH_EXPLICIT_PROPERTY_FIELDS = tuple(
    str(field["name"])
    for field in SIMPLE_CLOTH_RNA_FIELDS
    if str(field["name"]) != "enabled"
)


def _schema_defaults() -> dict[str, object]:
    return {
        str(field["name"]): (field.get("kwargs") or {}).get("default")
        for field in SIMPLE_CLOTH_RNA_FIELDS
        if str(field["name"]) in MC2_MESH_EXPLICIT_PROPERTY_FIELDS
    }


def _pointer_token(value):
    return None if value is None else mc2_source_token(value)


def _signature(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MC2MeshExplicitPropertiesSpec:
    """完整替代 Object 面板的 MeshCloth 显式属性。"""

    mc2_base_pose_proxy: object = None
    radius_vertex_group: str = ""
    pin_enabled: bool = False
    pin_vertex_group: str = ""
    primary_collision_group: int = 1
    collided_by_groups: int = 0

    def __post_init__(self) -> None:
        base_pose = self.mc2_base_pose_proxy
        if base_pose is not None and getattr(base_pose, "type", None) != "MESH":
            raise TypeError("MeshCloth BasePose 只接受 Mesh Object 或 None")
        object.__setattr__(
            self, "radius_vertex_group", str(self.radius_vertex_group or "")
        )
        if type(self.pin_enabled) is not bool:
            raise TypeError("MeshCloth pin_enabled 必须是 bool")
        object.__setattr__(
            self, "pin_vertex_group", str(self.pin_vertex_group or "")
        )
        group = int(self.primary_collision_group)
        if not 1 <= group <= 16:
            raise ValueError("MeshCloth primary_collision_group 必须位于 1..16")
        object.__setattr__(self, "primary_collision_group", group)
        mask = int(self.collided_by_groups)
        if not 0 <= mask <= 0xFFFF:
            raise ValueError("MeshCloth collided_by_groups 必须是 16-bit mask")
        object.__setattr__(self, "collided_by_groups", mask)

    @property
    def self_group_bit(self) -> int:
        return 1 << (self.primary_collision_group - 1)

    @property
    def self_collision_groups(self) -> int:
        return self.collided_by_groups | self.self_group_bit

    @property
    def signature(self) -> str:
        return _signature(self.debug_dict())

    def debug_dict(self) -> dict:
        return {
            "mc2_base_pose_proxy": _pointer_token(self.mc2_base_pose_proxy),
            "radius_vertex_group": self.radius_vertex_group,
            "pin_enabled": self.pin_enabled,
            "pin_vertex_group": self.pin_vertex_group,
            "primary_collision_group": self.primary_collision_group,
            "collided_by_groups": self.collided_by_groups,
        }


@dataclass(frozen=True)
class MC2MeshObjectSpec:
    """一个真实 Mesh Object 及其已解析的完整显式属性。"""

    source_object: object
    explicit_properties: MC2MeshExplicitPropertiesSpec
    property_origin: str

    def __post_init__(self) -> None:
        if getattr(self.source_object, "type", None) != "MESH":
            raise TypeError("MC2 MeshCloth对象只接受 Mesh Object")
        if not isinstance(
            self.explicit_properties, MC2MeshExplicitPropertiesSpec
        ):
            raise TypeError(
                "MC2 MeshCloth对象需要 MC2MeshExplicitPropertiesSpec"
            )
        origin = str(self.property_origin or "").strip().lower()
        if origin not in {"panel", "socket"}:
            raise ValueError("MeshCloth property_origin 必须是 panel 或 socket")
        object.__setattr__(self, "property_origin", origin)

    @property
    def source_identity(self) -> str:
        return _signature(mc2_source_token(self.source_object))

    @property
    def signature(self) -> str:
        return _signature({
            "source": mc2_source_token(self.source_object),
            "explicit_properties": self.explicit_properties.debug_dict(),
        })

    def debug_dict(self) -> dict:
        return {
            "source": mc2_source_token(self.source_object),
            "source_identity": self.source_identity,
            "property_origin": self.property_origin,
            "explicit_properties": self.explicit_properties.debug_dict(),
            "signature": self.signature,
        }


def make_mc2_mesh_explicit_properties(**values) -> MC2MeshExplicitPropertiesSpec:
    defaults = _schema_defaults()
    unknown = sorted(set(values) - set(MC2_MESH_EXPLICIT_PROPERTY_FIELDS))
    if unknown:
        raise TypeError(f"未知 MeshCloth 显式属性: {unknown!r}")
    defaults.update(values)
    return MC2MeshExplicitPropertiesSpec(**defaults)


def read_mc2_mesh_panel_object(source_object) -> MC2MeshObjectSpec:
    """读取已启用的面板属性；参与开关不进入对象值合同。"""

    if getattr(source_object, "type", None) != "MESH":
        raise TypeError("MC2 MeshCloth对象只接受 Mesh Object")
    properties = getattr(source_object, "hotools_mesh_collision", None)
    if properties is None:
        raise ValueError("Mesh Object 没有注册 hotools_mesh_collision 属性")
    if not bool(getattr(properties, "enabled", False)):
        raise ValueError("Mesh Object 没有启用简单布料")
    values = {
        name: getattr(properties, name)
        for name in MC2_MESH_EXPLICIT_PROPERTY_FIELDS
    }
    return MC2MeshObjectSpec(
        source_object=source_object,
        explicit_properties=make_mc2_mesh_explicit_properties(**values),
        property_origin="panel",
    )


def make_mc2_mesh_custom_object(
    source_object,
    **values,
) -> MC2MeshObjectSpec:
    """使用完整 socket/default 值构造对象，绝不读取 MeshCloth 面板。"""

    return MC2MeshObjectSpec(
        source_object=source_object,
        explicit_properties=make_mc2_mesh_explicit_properties(**values),
        property_origin="socket",
    )


def _flatten_mesh_objects(values) -> tuple[object, ...]:
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


def read_mc2_mesh_panel_objects(values) -> tuple[MC2MeshObjectSpec, ...]:
    result = []
    for source in _flatten_mesh_objects(values):
        if getattr(source, "type", None) != "MESH":
            raise TypeError("MC2 MeshCloth对象只接受 Mesh Object")
        properties = getattr(source, "hotools_mesh_collision", None)
        if properties is None:
            raise ValueError("Mesh Object 没有注册 hotools_mesh_collision 属性")
        if bool(getattr(properties, "enabled", False)):
            result.append(read_mc2_mesh_panel_object(source))
    return tuple(result)


def make_mc2_mesh_custom_objects(
    values,
    **properties,
) -> tuple[MC2MeshObjectSpec, ...]:
    return tuple(
        make_mc2_mesh_custom_object(source, **properties)
        for source in _flatten_mesh_objects(values)
    )


__all__ = [
    "MC2_MESH_EXPLICIT_PROPERTY_FIELDS",
    "MC2MeshExplicitPropertiesSpec",
    "MC2MeshObjectSpec",
    "make_mc2_mesh_custom_object",
    "make_mc2_mesh_custom_objects",
    "make_mc2_mesh_explicit_properties",
    "read_mc2_mesh_panel_object",
    "read_mc2_mesh_panel_objects",
]
