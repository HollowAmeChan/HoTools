"""Physics World 共享 Object/Bone collision capability schema。"""

from __future__ import annotations

from .groups import ALL_COLLISION_GROUPS_MASK, COLLISION_GROUP_COUNT
from .names import BONE_COLLISION_OVERRIDE_OBJECT_TAG


BONE_COLLISION_CAPABILITY_ID = "bone_collision"
OBJECT_COLLISION_CAPABILITY_ID = "object_collision"


BONE_COLLISION_CAPABILITY = {
    "capability_id": BONE_COLLISION_CAPABILITY_ID,
    "display_name": "骨骼碰撞",
    "semantic_owner": "physicsWorld.collision 共享能力",
    "explicit_storage": "Bone.hotools_collision",
    "identity_input": "_OmniBone 骨骼 socket 值；内部解析 armature 与 bone name",
    "supported_interfaces": {
        "explicit_property": {
            "storage": "Bone.hotools_collision",
            "status": "由 physicsWorld.collision 声明并注册",
        },
        "implicit_override_object": {
            "tag": BONE_COLLISION_OVERRIDE_OBJECT_TAG,
            "status": "已实现最小注册与 resolver 覆盖",
            "input": "_OmniBone 骨骼 socket；armature 与 bone name 从 socket 值解析",
            "stable_id": (
                f"{BONE_COLLISION_OVERRIDE_OBJECT_TAG}:"
                "{armature_ptr}:{armature_data_ptr}:{bone_name}"
            ),
            "conflict_policy": "same_tag_and_stable_id_last_writer_wins",
        },
    },
    "fields": [
        {
            "name": "pin",
            "type": "bool",
            "default": False,
            "explicit_property": "Bone.hotools_collision.pin",
            "rna": {
                "name": "Pin",
                "description": "固定这根骨骼，让物理解算保持当前姿态；链 root 由骨链输入决定并始终视为 Pin",
            },
            "update_policy": "restart_only",
        },
        {
            "name": "collision_type",
            "type": "enum",
            "values": ["NONE", "SPHERE", "CAPSULE"],
            "default": "NONE",
            "explicit_property": "Bone.hotools_collision.collision_type",
            "rna": {
                "name": "碰撞体",
                "description": "这根骨骼携带的物理碰撞体类型",
                "items": [
                    ("NONE", "无", "不作为物理碰撞体"),
                    ("SPHERE", "球体", "以骨骼局部偏移为中心的球形碰撞体"),
                    ("CAPSULE", "胶囊", "沿骨骼局部 Y 轴延伸的胶囊碰撞体"),
                ],
            },
            "update_policy": "live_native_hit_and_external_collider_arrays",
        },
        {
            "name": "radius",
            "type": "float",
            "default": 0.05,
            "explicit_property": "Bone.hotools_collision.radius",
            "rna": {
                "name": "半径",
                "description": "碰撞体半径，使用 Blender 单位",
                "min": 0.0,
                "soft_max": 1.0,
            },
            "update_policy": "dirty_only_or_restart_only",
        },
        {
            "name": "length",
            "type": "float",
            "default": 0.2,
            "explicit_property": "Bone.hotools_collision.length",
            "rna": {
                "name": "长度",
                "description": "胶囊中段长度，球体类型会忽略这个参数",
                "min": 0.0,
                "soft_max": 2.0,
            },
            "update_policy": "live_external_collider_arrays",
        },
        {
            "name": "offset",
            "type": "float3",
            "default": (0.0, 0.0, 0.0),
            "explicit_property": "Bone.hotools_collision.offset",
            "rna": {
                "name": "中心偏移",
                "description": "碰撞体中心相对骨骼局部空间的偏移",
                "size": 3,
                "subtype": "XYZ",
            },
            "update_policy": "live_external_collider_arrays",
        },
        {
            "name": "primary_collision_group",
            "type": "int",
            "default": 1,
            "explicit_property": "Bone.hotools_collision.primary_collision_group",
            "rna": {
                "name": "主碰撞组",
                "description": "这根碰撞体所属的主碰撞组，叠加显示颜色由它决定",
                "min": 1,
                "max": COLLISION_GROUP_COUNT,
            },
            "update_policy": "live_external_collider_arrays",
        },
        {
            "name": "collided_by_groups",
            "type": "bitmask",
            "default": 0,
            "explicit_property": "Bone.hotools_collision.collided_by_groups",
            "rna": {
                "name": "被碰撞组",
                "description": "允许哪些主碰撞组碰撞到这根碰撞体的位掩码",
                "min": 0,
                "max": ALL_COLLISION_GROUPS_MASK,
            },
            "update_policy": "dirty_only_or_restart_only",
        },
    ],
}


OBJECT_COLLISION_CAPABILITY = {
    "capability_id": OBJECT_COLLISION_CAPABILITY_ID,
    "display_name": "物体简单碰撞",
    "semantic_owner": "physicsWorld.collision 共享能力",
    "explicit_storage": "Object.hotools_object_collision",
    "fields": [
        {
            "name": "enabled",
            "type": "bool",
            "default": False,
            "rna": {
                "name": "启用",
                "description": "将此对象识别为简单碰撞体",
            },
        },
        {
            "name": "collision_type",
            "type": "enum",
            "values": ["NONE", "SPHERE", "CAPSULE", "PLANE", "BOX"],
            "default": "NONE",
            "rna": {
                "name": "碰撞体",
                "description": "这个Object携带的简单碰撞体类型",
                "items": [
                    ("NONE", "无", "不作为简单碰撞体"),
                    ("SPHERE", "球体", "以Object局部偏移为中心的球形碰撞体"),
                    ("CAPSULE", "胶囊", "沿Object局部Y轴延伸的胶囊碰撞体"),
                    ("PLANE", "平面", "以Object局部XY平面为无限碰撞平面；运行时必须用Object.matrix_world求世界原点、切线和法线"),
                    ("BOX", "长方体", "以Object局部偏移为中心、按局部XYZ长度定义的有向长方体；运行时必须用Object.matrix_world求世界角点"),
                ],
            },
        },
        {
            "name": "radius",
            "type": "float",
            "default": 0.05,
            "rna": {
                "name": "半径",
                "description": "球体和胶囊半径，使用Blender单位；平面类型不把它作为真实碰撞厚度",
                "min": 0.0,
                "soft_max": 1.0,
            },
        },
        {
            "name": "length",
            "type": "float",
            "default": 1.0,
            "rna": {
                "name": "长度",
                "description": "胶囊中段长度；平面类型把它作为叠加层方片的预览尺寸，不改变无限平面的物理语义",
                "min": 0.0,
                "soft_max": 10.0,
            },
        },
        {
            "name": "offset",
            "type": "float3",
            "default": (0.0, 0.0, 0.0),
            "rna": {
                "name": "局部偏移",
                "description": "球体/胶囊/长方体中心或平面原点相对Object局部空间的偏移",
                "size": 3,
                "subtype": "XYZ",
            },
        },
        {
            "name": "box_size",
            "type": "float3",
            "default": (1.0, 1.0, 1.0),
            "rna": {
                "name": "XYZ长度",
                "description": "长方体在Object局部X/Y/Z方向上的全尺寸；实际世界尺寸和方向必须通过Object.matrix_world解析",
                "size": 3,
                "subtype": "XYZ",
                "min": 0.0,
                "soft_max": 10.0,
            },
        },
        {
            "name": "primary_collision_group",
            "type": "int",
            "default": 1,
            "rna": {
                "name": "主碰撞组",
                "description": "这个简单碰撞体所属的主碰撞组，叠加显示颜色由它决定",
                "min": 1,
                "max": COLLISION_GROUP_COUNT,
            },
        },
    ],
}


COLLISION_CAPABILITIES = {
    BONE_COLLISION_CAPABILITY_ID: BONE_COLLISION_CAPABILITY,
    OBJECT_COLLISION_CAPABILITY_ID: OBJECT_COLLISION_CAPABILITY,
}


def bone_collision_capability_fields() -> tuple[dict, ...]:
    return tuple(dict(field) for field in BONE_COLLISION_CAPABILITY.get("fields", ()))


def bone_collision_capability_field_names() -> tuple[str, ...]:
    return tuple(
        str(field.get("name") or "")
        for field in BONE_COLLISION_CAPABILITY.get("fields", ())
        if field.get("name")
    )


def _rna_properties(property_group):
    rna = getattr(property_group, "bl_rna", property_group)
    return getattr(rna, "properties", None)


def _rna_property_get(properties, name: str):
    if properties is None:
        return None
    getter = getattr(properties, "get", None)
    if callable(getter):
        return getter(name)
    try:
        return properties[name]
    except Exception:
        pass
    try:
        return next(item for item in properties if getattr(item, "identifier", None) == name)
    except Exception:
        return None


def _enum_identifiers(prop) -> tuple[str, ...]:
    items = getattr(prop, "enum_items", None)
    if items is None:
        return ()
    try:
        values = items.values() if callable(getattr(items, "values", None)) else items
        return tuple(str(item.identifier) for item in values)
    except Exception:
        return ()


def _rna_default(prop, typ: str):
    if typ == "float3":
        default_array = getattr(prop, "default_array", None)
        if default_array is not None:
            return tuple(float(item) for item in default_array)
    return getattr(prop, "default", None)


def _defaults_match(expected, actual, typ: str) -> bool:
    if typ == "bool":
        return bool(actual) is bool(expected)
    if typ in {"int", "bitmask"}:
        return int(actual) == int(expected)
    if typ == "float":
        return abs(float(actual) - float(expected)) <= 1.0e-8
    if typ == "float3":
        return actual is not None and tuple(float(item) for item in actual) == tuple(float(item) for item in expected)
    if typ == "enum":
        return str(actual) == str(expected)
    return actual == expected


def audit_collision_property_group(capability: dict, property_group) -> list[str]:
    properties = _rna_properties(property_group)
    issues: list[str] = []
    for field in capability.get("fields", ()):
        name = str(field.get("name") or "")
        if not name:
            continue
        prop = _rna_property_get(properties, name)
        if prop is None:
            issues.append(f"missing explicit property: {name}")
            continue
        typ = str(field.get("type") or "")
        expected_default = field.get("default")
        actual_default = _rna_default(prop, typ)
        if not _defaults_match(expected_default, actual_default, typ):
            issues.append(
                f"default mismatch for {name}: capability={expected_default!r} rna={actual_default!r}"
            )
        if typ == "enum":
            expected_values = tuple(str(item) for item in field.get("values", ()))
            actual_values = _enum_identifiers(prop)
            if actual_values != expected_values:
                issues.append(
                    f"enum mismatch for {name}: capability={expected_values!r} rna={actual_values!r}"
                )
    return issues


def audit_bone_collision_property_group(property_group) -> list[str]:
    return audit_collision_property_group(BONE_COLLISION_CAPABILITY, property_group)


def audit_object_collision_property_group(property_group) -> list[str]:
    return audit_collision_property_group(OBJECT_COLLISION_CAPABILITY, property_group)


__all__ = [
    "BONE_COLLISION_CAPABILITY",
    "BONE_COLLISION_CAPABILITY_ID",
    "COLLISION_CAPABILITIES",
    "OBJECT_COLLISION_CAPABILITY",
    "OBJECT_COLLISION_CAPABILITY_ID",
    "audit_bone_collision_property_group",
    "audit_collision_property_group",
    "audit_object_collision_property_group",
    "bone_collision_capability_field_names",
    "bone_collision_capability_fields",
]
