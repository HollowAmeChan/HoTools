"""Physics World 共享碰撞 capability。"""

from __future__ import annotations

from importlib import import_module


COMPONENT_MODULE = {
    "component_id": "collision",
    "kind": "core",
    "depends_on": (),
    "capabilities": ".capabilities:COLLISION_CAPABILITIES",
    "blender_properties": ".properties:COLLISION_BLENDER_PROPERTIES",
}


_EXPORTS = {
    "ALL_COLLISION_GROUPS_MASK": ".groups",
    "BONE_COLLISION_CAPABILITY": ".capabilities",
    "BONE_COLLISION_CAPABILITY_ID": ".capabilities",
    "BONE_COLLISION_OVERRIDE_OBJECT_TAG": ".names",
    "COLLISION_GROUP_COLORS": ".groups",
    "COLLISION_GROUP_COUNT": ".groups",
    "COLLISION_CAPABILITIES": ".capabilities",
    "COLLISION_BLENDER_PROPERTIES": ".properties",
    "OBJECT_COLLISION_CAPABILITY": ".capabilities",
    "OBJECT_COLLISION_CAPABILITY_ID": ".capabilities",
    "PG_Hotools_BoneCollision": ".properties",
    "PG_Hotools_ObjectCollision": ".properties",
    "audit_bone_collision_property_group": ".capabilities",
    "audit_object_collision_property_group": ".capabilities",
    "bone_collision_capability_field_names": ".capabilities",
    "bone_collision_capability_fields": ".capabilities",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = sorted(_EXPORTS)
