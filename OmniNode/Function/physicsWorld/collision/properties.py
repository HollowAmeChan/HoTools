"""Physics World 共享 Object/Bone collision Blender RNA。"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty
from bpy.types import PropertyGroup

from .capabilities import BONE_COLLISION_CAPABILITY, OBJECT_COLLISION_CAPABILITY


def _field_property(field: dict):
    field_type = str(field.get("type") or "")
    metadata = dict(field.get("rna") or {})
    metadata["default"] = field.get("default")
    if field_type == "bool":
        return BoolProperty(**metadata)
    if field_type == "enum":
        metadata.setdefault("items", [
            (str(value), str(value), str(value))
            for value in field.get("values", ())
        ])
        return EnumProperty(**metadata)
    if field_type == "float":
        return FloatProperty(**metadata)
    if field_type == "float3":
        return FloatVectorProperty(**metadata)
    if field_type in {"int", "bitmask"}:
        return IntProperty(**metadata)
    raise ValueError(f"unsupported collision field type: {field_type}")


class PG_Hotools_BoneCollision(PropertyGroup):
    """Physics World 共享骨骼碰撞持久参数。"""


PG_Hotools_BoneCollision.__annotations__ = {
    str(field["name"]): _field_property(field)
    for field in BONE_COLLISION_CAPABILITY.get("fields", ())
    if field.get("name")
}


class PG_Hotools_ObjectCollision(PropertyGroup):
    """Physics World 共享 Object 简单碰撞持久参数。"""


PG_Hotools_ObjectCollision.__annotations__ = {
    str(field["name"]): _field_property(field)
    for field in OBJECT_COLLISION_CAPABILITY.get("fields", ())
    if field.get("name")
}


COLLISION_BLENDER_PROPERTIES = {
    "classes": (PG_Hotools_BoneCollision, PG_Hotools_ObjectCollision),
    "bindings": (
        {
            "owner": bpy.types.Bone,
            "name": "hotools_collision",
            "property": "pointer",
            "type": PG_Hotools_BoneCollision,
        },
        {
            "owner": bpy.types.Object,
            "name": "hotools_object_collision",
            "property": "pointer",
            "type": PG_Hotools_ObjectCollision,
        },
    ),
}


__all__ = [
    "COLLISION_BLENDER_PROPERTIES",
    "PG_Hotools_BoneCollision",
    "PG_Hotools_ObjectCollision",
]
