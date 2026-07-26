"""由 rigid.schema 生成 Rigid/Jolt Blender PropertyGroup 与稳定 binding。"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty
from bpy.types import PropertyGroup

from .schema import RIGID_BODY_RNA_FIELDS, RIGID_CONSTRAINT_RNA_FIELDS


_PROPERTY_FACTORIES = {
    "bool": BoolProperty,
    "enum": EnumProperty,
    "float": FloatProperty,
    "float_vector": FloatVectorProperty,
    "int": IntProperty,
    "pointer": PointerProperty,
}


def _field_property(field: dict):
    property_kind = str(field.get("property") or "")
    factory = _PROPERTY_FACTORIES.get(property_kind)
    if factory is None:
        raise ValueError(f"unsupported rigid RNA property kind: {property_kind}")
    kwargs = dict(field.get("kwargs") or {})
    pointer_type = kwargs.get("type")
    if property_kind == "pointer" and isinstance(pointer_type, str):
        resolved_type = getattr(bpy.types, pointer_type, None)
        if resolved_type is None:
            raise ValueError(f"unsupported rigid RNA pointer type: {pointer_type}")
        kwargs["type"] = resolved_type
    return factory(**kwargs)


class PG_Hotools_RigidBody(PropertyGroup):
    """Object 级 Rigid/Jolt 刚体持久配置。"""


PG_Hotools_RigidBody.__annotations__ = {
    str(field["name"]): _field_property(field)
    for field in RIGID_BODY_RNA_FIELDS
}


class PG_Hotools_RigidConstraint(PropertyGroup):
    """Object 级 Rigid/Jolt 约束持久配置。"""


PG_Hotools_RigidConstraint.__annotations__ = {
    str(field["name"]): _field_property(field)
    for field in RIGID_CONSTRAINT_RNA_FIELDS
}


RIGID_BLENDER_PROPERTIES = {
    "classes": (PG_Hotools_RigidBody, PG_Hotools_RigidConstraint),
    "bindings": (
        {
            "owner": bpy.types.Object,
            "name": "hotools_rigid_body",
            "property": "pointer",
            "type": PG_Hotools_RigidBody,
        },
        {
            "owner": bpy.types.Object,
            "name": "hotools_rigid_constraint",
            "property": "pointer",
            "type": PG_Hotools_RigidConstraint,
        },
    ),
}


__all__ = [
    "PG_Hotools_RigidBody",
    "PG_Hotools_RigidConstraint",
    "RIGID_BLENDER_PROPERTIES",
]
