"""SpringBone 骨骼碰撞字段 resolver。

统一解析"骨骼碰撞字段值是什么"，解析优先级：
  1. implicit override 对象（bone_collision.override）
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
from .names import BONE_COLLISION_OVERRIDE_OBJECT_TAG
from ..utils.ids import as_pointer, data_pointer


# 从能力表读默认值，避免 resolver 里重抄一份 magic number。
_CAP_FIELD_DEFAULTS = {
    str(field.get("name") or ""): field.get("default")
    for field in BONE_COLLISION_CAPABILITY.get("fields", ())
    if field.get("name")
}
_CAP_FIELD_META = {
    str(field.get("name") or ""): dict(field)
    for field in BONE_COLLISION_CAPABILITY.get("fields", ())
    if field.get("name")
}
_CAP_FIELD_NAMES = tuple(_CAP_FIELD_DEFAULTS)


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


def _coerce_bool(value, fallback: bool) -> bool:
    if value is None:
        return bool(fallback)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"0", "false", "no", "off"}:
            return False
        if text in {"1", "true", "yes", "on"}:
            return True
    return bool(value)


def _coerce_field(name: str, value, fallback):
    if value is None:
        return fallback
    typ = str(_CAP_FIELD_META.get(name, {}).get("type") or "")
    if typ == "bool":
        return _coerce_bool(value, fallback)
    if typ == "enum":
        text = str(value or "").strip().upper()
        values = {str(item) for item in _CAP_FIELD_META.get(name, {}).get("values", ())}
        if values and text not in values:
            return fallback
        return text
    if typ == "float":
        return float(value)
    if typ in {"int", "bitmask"}:
        return int(value)
    if typ == "float3":
        try:
            values = tuple(float(item) for item in value)
            if len(values) == 3:
                return values
        except Exception:
            return fallback
        return fallback
    return value


def _profile_from_field_mapping(fields: dict, base: BoneCollisionProfile, source: str) -> BoneCollisionProfile:
    values = {name: getattr(base, name) for name in _CAP_FIELD_NAMES}
    for name in _CAP_FIELD_NAMES:
        if name in fields:
            values[name] = _coerce_field(name, fields.get(name), values[name])
    return BoneCollisionProfile(
        pin=bool(values["pin"]),
        collision_type=str(values["collision_type"] or "NONE"),
        radius=float(values["radius"]),
        length=float(values["length"]),
        offset=tuple(values["offset"]),
        primary_collision_group=int(values["primary_collision_group"]),
        collided_by_groups=int(values["collided_by_groups"]),
        source=source,
    )


def _override_stable_id(armature, bone_name: str) -> str:
    return (
        f"{BONE_COLLISION_OVERRIDE_OBJECT_TAG}:"
        f"{as_pointer(armature)}:{data_pointer(armature)}:"
        f"{str(bone_name or '')}"
    )


def _resolve_override_profile(armature, bone_name: str, world=None, base: BoneCollisionProfile | None = None):
    """implicit override 层解析入口（bone_collision.override）。

    按 stable_id 命中 world.implicit_objects，并把 payload.fields 覆盖到
    legacy/default profile 上。未覆写字段继续沿用下一层来源。
    """
    if world is None or not hasattr(world, "iter_implicit_objects"):
        return None
    stable_id = _override_stable_id(armature, bone_name)
    base_profile = base if base is not None else _default_profile()

    for entry in world.iter_implicit_objects(tag=BONE_COLLISION_OVERRIDE_OBJECT_TAG, enabled=True):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("stable_id") or "") != stable_id:
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        fields = payload.get("fields")
        if not isinstance(fields, dict):
            fields = {name: payload.get(name) for name in _CAP_FIELD_NAMES if name in payload}
        if not fields:
            continue
        return _profile_from_field_mapping(fields, base_profile, "override")
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


def resolve_bone_collision_fields(armature, bone_name: str, world=None) -> BoneCollisionProfile:
    """解析单根骨骼的碰撞字段值。

    优先级：override 隐式对象 > 旧 Bone.hotools_collision > capability 默认值。
    只返回原始字段值，几何缩放 / clamp / collider 打包由调用方（native）负责。
    """
    props = _legacy_bone_collision_props(armature, bone_name)
    if props is not None:
        base = _profile_from_legacy_props(props)
    else:
        base = _default_profile()

    override = _resolve_override_profile(armature, bone_name, world=world, base=base)
    if override is not None:
        return override
    return base


def resolve_bone_pin(armature, bone_name: str, world=None) -> bool:
    """解析单根骨骼的 pin 标记（不含 root 硬 pin 逻辑，那属于解算侧）。"""
    return bool(resolve_bone_collision_fields(armature, bone_name, world=world).pin)
