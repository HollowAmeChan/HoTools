"""SpringBone 领域能力声明。

骨骼碰撞是 solver/domain 能力，不是某一种外部属性存储格式。
显式 Blender RNA 与隐式覆写对象都由这张能力表生成/校验。Bone.hotools_collision
只是稳定的持久化存储名，不再表示 PhysicsTools 或旧 solver 对字段语义有所有权。
"""

from __future__ import annotations

from .names import BONE_COLLISION_OVERRIDE_OBJECT_TAG, SPRING_VRM_CHAIN_OBJECT_TAG


BONE_COLLISION_CAPABILITY_ID = "bone_collision"


BONE_COLLISION_CAPABILITY = {
    "capability_id": BONE_COLLISION_CAPABILITY_ID,
    "display_name": "骨骼碰撞",
    "semantic_owner": "physicsWorld solver 能力声明",
    "explicit_storage": "Bone.hotools_collision",
    "identity_input": "_OmniBone 骨骼 socket 值；内部解析 armature 与 bone name",
    "supported_interfaces": {
        "explicit_property": {
            "storage": "Bone.hotools_collision",
            "status": "由 SpringBone solver 声明、physicsWorld 统一注册",
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
            "consumer_note": "SpringBone 在状态重建时读取非 root 骨骼 pin。",
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
            "consumer_note": "控制自身 hit radius 是否启用，也控制该骨骼作为外部 sphere/capsule 是否进入 native collider arrays。",
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
            "consumer_note": "SpringBone 将该字段映射到 native hit_radii。",
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
            "consumer_note": "CAPSULE 外部骨骼碰撞体的局部轴向长度，进入 native segment_a/segment_b。",
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
            "consumer_note": "外部骨骼碰撞体的局部偏移，进入 native center/segment_a/segment_b。",
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
                "max": 16,
            },
            "update_policy": "live_external_collider_arrays",
            "consumer_note": "外部骨骼碰撞体所属组，进入 native collider_groups。",
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
                "max": 65535,
            },
            "update_policy": "dirty_only_or_restart_only",
            "consumer_note": "SpringBone 将该字段映射到 native collided_by_groups。",
        },
    ],
}


SPRING_VRM_CAPABILITIES = {
    BONE_COLLISION_CAPABILITY_ID: BONE_COLLISION_CAPABILITY,
}


# SpringBone 更新频率权威表。
#
# 这张表必须留在代码里，保证 solver 声明、debug 视图、未来节点生成器和迁移测试
# 审查的是同一份策略。设计文档只能镜像这张表，不能成为另一份事实源。
SPRING_VRM_UPDATE_FREQUENCY_TABLE = [
    {
        "data": "帧 / dt",
        "source": "PhysicsWorldCache.frame_context",
        "policy": "every_frame",
    },
    {
        "data": "骨链根骨骼 / 骨骼列表",
        "source": f'world.implicit_objects["{SPRING_VRM_CHAIN_OBJECT_TAG}"]',
        "policy": "implicit_object_dirty",
    },
    {
        "data": "刚度 / 阻尼 / 重力",
        "source": f'world.implicit_objects["{SPRING_VRM_CHAIN_OBJECT_TAG}"]',
        "policy": "implicit_object_dirty",
    },
    {
        "data": "姿态 head / tail / 父级目标姿态",
        "source": "PoseBone 每帧输入",
        "policy": "every_frame",
    },
    {
        "data": "当前尾端 / 上一帧尾端",
        "source": "slot.data.frame_state",
        "policy": "every_frame_mutate_in_place",
    },
    {
        "data": "初始轴向 / 旋转 / 缩放",
        "source": "slot.data.native_context 静态数组",
        "policy": "restart_only",
    },
    {
        "data": "父级索引 / 连接骨骼标记",
        "source": "骨架拓扑",
        "policy": "topology_dirty",
    },
    {
        "data": "bone_collision.pin",
        "source": BONE_COLLISION_CAPABILITY_ID,
        "policy": "restart_only",
    },
    {
        "data": "bone_collision.radius -> hit_radii",
        "source": BONE_COLLISION_CAPABILITY_ID,
        "policy": "dirty_only_or_restart_only",
    },
    {
        "data": "bone_collision.collided_by_groups",
        "source": BONE_COLLISION_CAPABILITY_ID,
        "policy": "dirty_only_or_restart_only",
    },
    {
        "data": "bone_collision.collision_type/length/offset/primary_collision_group",
        "source": BONE_COLLISION_CAPABILITY_ID,
        "policy": "override_version_or_world_collider_snapshot_frame",
    },
    {
        "data": "物体 / 骨骼碰撞体",
        "source": "PhysicsWorldCache.collider_snapshot",
        "policy": "every_frame_by_world_begin",
    },
    {
        "data": "碰撞体数组（SpringBone context API）",
        "source": "solver slot 懒构建碰撞体数组缓存",
        "policy": "lazy_on_access",
    },
    {
        "data": "写回计划 / basis foreach 缓冲区",
        "source": "slot.data.writeback_plan",
        "policy": "topology_dirty_or_restart_only_allocation",
    },
]

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
        for item in properties:
            if getattr(item, "identifier", None) == name:
                return item
    except Exception:
        pass
    return None


def _enum_identifiers(prop) -> tuple[str, ...]:
    items = getattr(prop, "enum_items", None)
    if items is None:
        return ()
    result = []
    try:
        iterator = items
        values = getattr(items, "values", None)
        if callable(values):
            iterator = values()
        for item in iterator:
            identifier = getattr(item, "identifier", None)
            if identifier is not None:
                result.append(str(identifier))
    except Exception:
        return ()
    return tuple(result)


def _rna_default(prop, typ: str):
    if typ == "float3":
        default_array = getattr(prop, "default_array", None)
        if default_array is not None:
            return tuple(float(item) for item in default_array)
        value = getattr(prop, "default", None)
        if value is not None:
            try:
                return tuple(float(item) for item in value)
            except Exception:
                return value
        return None
    return getattr(prop, "default", None)


def _defaults_match(expected, actual, typ: str) -> bool:
    if typ == "bool":
        return bool(actual) is bool(expected)
    if typ in {"int", "bitmask"}:
        return int(actual) == int(expected)
    if typ == "float":
        return abs(float(actual) - float(expected)) <= 1.0e-8
    if typ == "float3":
        if actual is None:
            return False
        return (
            len(tuple(actual)) == len(tuple(expected))
            and all(abs(float(a) - float(b)) <= 1.0e-8 for a, b in zip(actual, expected))
        )
    if typ == "enum":
        return str(actual) == str(expected)
    return actual == expected


def audit_bone_collision_property_group(property_group) -> list[str]:
    """Return drift issues between generated Bone.hotools_collision RNA and capability."""
    properties = _rna_properties(property_group)
    issues: list[str] = []
    for field in BONE_COLLISION_CAPABILITY.get("fields", ()):
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
                f"default mismatch for {name}: capability={expected_default!r} "
                f"rna={actual_default!r}"
            )

        if typ == "enum":
            expected_values = tuple(str(item) for item in field.get("values", ()))
            actual_values = _enum_identifiers(prop)
            if actual_values != expected_values:
                issues.append(
                    f"enum mismatch for {name}: capability={expected_values!r} "
                    f"rna={actual_values!r}"
                )
    return issues
