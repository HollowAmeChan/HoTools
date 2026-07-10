"""由 MC2 MeshCloth setup schema 生成 MeshCollision PropertyGroup。"""

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup

from .schema import MESH_COLLISION_RNA_FIELDS


def _mesh_object_poll(_self, obj):
    return obj is not None and obj.type == "MESH"


_FACTORIES = {
    "bool": BoolProperty,
    "float": FloatProperty,
    "int": IntProperty,
    "pointer": PointerProperty,
    "string": StringProperty,
}


def _field_property(field: dict):
    kind = str(field.get("property") or "")
    factory = _FACTORIES[kind]
    kwargs = dict(field.get("kwargs") or {})
    if kind == "pointer" and isinstance(kwargs.get("type"), str):
        kwargs["type"] = getattr(bpy.types, kwargs["type"])
    if kwargs.get("poll") == "mesh_object":
        kwargs["poll"] = _mesh_object_poll
    return factory(**kwargs)


class PG_Hotools_MeshCollision(PropertyGroup):
    """Object 级 MeshCloth 持久配置。"""


PG_Hotools_MeshCollision.__annotations__ = {
    str(field["name"]): _field_property(field)
    for field in MESH_COLLISION_RNA_FIELDS
}


MESH_CLOTH_BLENDER_PROPERTIES = {
    "classes": (PG_Hotools_MeshCollision,),
    "bindings": ({
        "owner": bpy.types.Object,
        "name": "hotools_mesh_collision",
        "property": "pointer",
        "type": PG_Hotools_MeshCollision,
    },),
}


__all__ = ["MESH_CLOTH_BLENDER_PROPERTIES", "PG_Hotools_MeshCollision"]
