"""SpringBone 骨骼碰撞字段 resolver。

统一解析"骨骼碰撞字段值是什么"，解析优先级：
  1. implicit override 对象（bone_collision.override）—— 计划中，当前为空实现
  2. 旧显式属性 Bone.hotools_collision —— 当前唯一真实来源
  3. capability 默认值（BONE_COLLISION_CAPABILITY.fields）

本模块只负责"字段值是什么"，不做几何缩放、matrix_scale_radius、clamp 或
collider 数组打包——那些留在 native.py 的解算侧。这样等 override 隐式对象
节点落地时，只需补第 1 层，native 消费端和默认值来源都不用改。

参见 capabilities.py 的 BONE_COLLISION_CAPABILITY 与 ARCHITECTURE.md §7.3
（同一语义只能有一个真值来源）。
"""

from __future__ import annotations

from collections import namedtuple

from .capabilities import BONE_COLLISION_CAPABILITY


# 从能力表读默认值，避免 resolver 里重抄一份 magic number。
_CAP_FIELD_DEFAULTS = {
    str(field.get("name") or ""): field.get("default")
    for field in BONE_COLLISION_CAPABILITY.get("fields", ())
    if field.get("name")
}


def _default(name: str, fallback):
    value = _CAP_FIELD_DEFAULTS.get(name, fallback)
    return value if value is not None else fallback


BoneCollisionProfile = namedtuple(
    "BoneCollisionProfile",
    (
        "pin",
        "collision_type",
        "radius",
        "length",
        "offset",
        "primary_collision_group",
        "collided_by_groups",
        "source",
    ),
)


def _default_profile() -> BoneCollisionProfile:
    """没有任何来源命中时的能力默认值 profile。"""
    return BoneCollisionProfile(
        pin=bool(_default("pin", False)),
        collision_type=str(_default("collision_type", "NONE")),
        radius=float(_default("radius", 0.05)),
        length=float(_default("length", 0.2)),
        offset=tuple(_default("offset", (0.0, 0.0, 0.0))),
        primary_collision_group=int(_default("primary_collision_group", 1)),
        collided_by_groups=int(_default("collided_by_groups", 0)),
        source="default",
    )


def _profile_from_legacy_props(props) -> BoneCollisionProfile:
    """从旧显式属性 Bone.hotools_collision 读字段值。

    props 已确认非空。缺失字段回退到能力默认值，保证与旧直读的 getattr
    默认值语义一致。
    """
    base = _default_profile()
    offset = getattr(props, "offset", None)
    return BoneCollisionProfile(
        pin=bool(getattr(props, "pin", base.pin)),
        collision_type=str(getattr(props, "collision_type", base.collision_type) or "NONE"),
        radius=float(getattr(props, "radius", base.radius) or 0.0),
        length=float(getattr(props, "length", base.length) or 0.0),
        offset=tuple(offset) if offset is not None else base.offset,
        primary_collision_group=int(getattr(props, "primary_collision_group", base.primary_collision_group) or 0),
        collided_by_groups=int(getattr(props, "collided_by_groups", base.collided_by_groups) or 0),
        source="legacy_property",
    )


def _resolve_override_profile(armature, bone_name: str):
    """implicit override 层解析入口（bone_collision.override）。

    override 隐式对象节点尚未实现，当前恒返回 None，走 legacy + default。
    override 节点落地后只需在这里按 stable_id 命中 world.implicit_objects
    并返回 source="override" 的 profile，native 消费端无需改动。
    """
    return None


def _legacy_bone_collision_props(armature, bone_name: str):
    """取 Bone.hotools_collision（可能为 None）。"""
    name = str(bone_name or "")
    if not name:
        return None
    bones = getattr(getattr(armature, "data", None), "bones", None)
    bone = bones.get(name) if bones is not None else None
    if bone is None:
        return None
    return getattr(bone, "hotools_collision", None)


def resolve_bone_collision_fields(armature, bone_name: str) -> BoneCollisionProfile:
    """解析单根骨骼的碰撞字段值。

    优先级：override 隐式对象 > 旧 Bone.hotools_collision > capability 默认值。
    只返回原始字段值，几何缩放 / clamp / collider 打包由调用方（native）负责。
    """
    override = _resolve_override_profile(armature, bone_name)
    if override is not None:
        return override

    props = _legacy_bone_collision_props(armature, bone_name)
    if props is not None:
        return _profile_from_legacy_props(props)

    return _default_profile()


def resolve_bone_pin(armature, bone_name: str) -> bool:
    """解析单根骨骼的 pin 标记（不含 root 硬 pin 逻辑，那属于解算侧）。"""
    return bool(resolve_bone_collision_fields(armature, bone_name).pin)
