"""VRM SpringBone 隐式对象注册。"""

from __future__ import annotations

import bpy
import mathutils

from ....OmniNodeSocketMapping import _OmniBone
from ..names import SPRING_VRM_CHAIN_OBJECT_TAG
from ..types import PhysicsWorldCache
from ..utils.ids import as_pointer, data_pointer, stable_short_hash
from ..utils.values import float3
from .specs import normalize_spring_vrm_chain_properties


SPRING_VRM_OBJECT_REGISTER_PRODUCER = "physicsSpringVRMChainRegister"


def _resolve_bone_value(value) -> tuple[bpy.types.Object, str]:
    if not isinstance(value, dict):
        raise ValueError("bone input is empty or invalid")
    armature_obj = value.get("armature")
    bone_name = str(value.get("bone") or "").strip()
    if (
        not isinstance(armature_obj, bpy.types.Object)
        or armature_obj.type != "ARMATURE"
        or not bone_name
    ):
        raise ValueError("bone input is empty or invalid")
    if armature_obj.pose is None or armature_obj.pose.bones.get(bone_name) is None:
        raise ValueError(f"bone not found: {bone_name}")
    return armature_obj, bone_name


def _collect_bone_names(root_pose_bone) -> list[str]:
    names: list[str] = []

    def visit(pose_bone) -> None:
        names.append(pose_bone.name)
        for child in list(getattr(pose_bone, "children", []) or []):
            visit(child)

    visit(root_pose_bone)
    return names


def _chain_bone_names_from_root(armature_obj: bpy.types.Object, root_name: str) -> list[str]:
    root_pose_bone = armature_obj.pose.bones.get(root_name)
    if root_pose_bone is None:
        raise ValueError(f"bone not found: {root_name}")
    return _collect_bone_names(root_pose_bone)


def _chain_from_bone_names(
    armature_obj: bpy.types.Object,
    root_name: str,
    bone_names: list[str],
) -> dict:
    chain_bones: list[str] = []
    seen = set()
    for bone_name in bone_names:
        name = str(bone_name or "").strip()
        if not name or name in seen:
            continue
        if armature_obj.pose.bones.get(name) is None:
            continue
        seen.add(name)
        chain_bones.append(name)
    if root_name and root_name not in seen and armature_obj.pose.bones.get(root_name) is not None:
        chain_bones.insert(0, root_name)
    if not chain_bones:
        chain_bones = _chain_bone_names_from_root(armature_obj, root_name)
    return {
        "armature": armature_obj,
        "root_bone": str(root_name or ""),
        "bones": chain_bones,
    }


def _bone_is_descendant_or_self(armature_obj: bpy.types.Object, bone_name: str, root_name: str) -> bool:
    pose_bone = armature_obj.pose.bones.get(bone_name)
    while pose_bone is not None:
        if pose_bone.name == root_name:
            return True
        pose_bone = getattr(pose_bone, "parent", None)
    return False


def _chains_from_direct_bone_values(values: list[tuple[bpy.types.Object, str]]) -> list[dict]:
    if not values:
        return []

    groups: list[tuple[bpy.types.Object, list[str]]] = []
    group_index: dict[int, int] = {}
    for armature_obj, bone_name in values:
        key = int(armature_obj.as_pointer())
        if key not in group_index:
            group_index[key] = len(groups)
            groups.append((armature_obj, []))
        groups[group_index[key]][1].append(bone_name)

    result: list[dict] = []
    for armature_obj, bone_names in groups:
        ordered_names: list[str] = []
        seen = set()
        for bone_name in bone_names:
            if bone_name not in seen:
                seen.add(bone_name)
                ordered_names.append(bone_name)

        provided = set(ordered_names)
        has_parent_link = False
        for bone_name in ordered_names:
            pose_bone = armature_obj.pose.bones.get(bone_name)
            parent = getattr(pose_bone, "parent", None) if pose_bone is not None else None
            if parent is not None and parent.name in provided:
                has_parent_link = True
                break

        if not has_parent_link:
            for bone_name in ordered_names:
                result.append(_chain_from_bone_names(
                    armature_obj,
                    bone_name,
                    _chain_bone_names_from_root(armature_obj, bone_name),
                ))
            continue

        roots: list[str] = []
        for bone_name in ordered_names:
            pose_bone = armature_obj.pose.bones.get(bone_name)
            parent = getattr(pose_bone, "parent", None) if pose_bone is not None else None
            if parent is None or parent.name not in provided:
                roots.append(bone_name)
        if not roots and ordered_names:
            roots.append(ordered_names[0])

        for root_name in roots:
            chain_bones = [
                bone_name
                for bone_name in ordered_names
                if _bone_is_descendant_or_self(armature_obj, bone_name, root_name)
            ]
            result.append(_chain_from_bone_names(armature_obj, root_name, chain_bones))
    return result


def bone_chains_from_bone_values(values) -> list[dict]:
    result: list[dict] = []
    if values is None:
        return result

    bone_values: list[dict] = []
    stack = list(values) if isinstance(values, (list, tuple)) else [values]
    while stack:
        value = stack.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            stack[0:0] = list(value)
            continue
        _resolve_bone_value(value)
        bone_values.append(value)

    metadata_keys = set()
    direct_values: list[tuple[bpy.types.Object, str]] = []
    for value in bone_values:
        armature_obj, bone_name = _resolve_bone_value(value)
        collection_root = str(value.get("bone_collection_root") or "").strip()
        collection_value = value.get("bone_collection")
        if collection_root and isinstance(collection_value, list):
            collection_bones = [str(name).strip() for name in collection_value if str(name).strip()]
            if collection_bones:
                key = (int(armature_obj.as_pointer()), collection_root, tuple(collection_bones))
                if key not in metadata_keys:
                    metadata_keys.add(key)
                    result.append(_chain_from_bone_names(armature_obj, collection_root, collection_bones))
                continue
        direct_values.append((armature_obj, bone_name))

    result.extend(_chains_from_direct_bone_values(direct_values))
    return result


def make_spring_vrm_chain_properties(
    bone_chain: list[_OmniBone],
    enabled: bool = True,
    stiffness_force: float = 1.0,
    drag_force: float = 0.4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 0.0,
) -> list[dict]:
    bone_chains = bone_chains_from_bone_values(bone_chain)
    if not bone_chains:
        raise ValueError("root bone input is empty")

    gravity = mathutils.Vector(float3(gravity_dir, fallback=(0.0, 0.0, -1.0)))
    if gravity.length > 1.0e-8:
        gravity.normalize()

    return [
        {
            "armature": bone_chain_value["armature"],
            "root_bone": str(bone_chain_value.get("root_bone") or ""),
            "bones": list(bone_chain_value.get("bones") or []),
            "enabled": bool(enabled),
            "stiffness_force": max(float(stiffness_force), 0.0),
            "drag_force": max(0.0, min(1.0, float(drag_force))),
            "gravity_dir": tuple(float(v) for v in gravity),
            "gravity_power": max(float(gravity_power), 0.0),
        }
        for bone_chain_value in bone_chains
    ]


def _copy_chain_object(setting: dict) -> dict:
    bones = list(setting.get("bones") or ())
    return {
        "armature": setting.get("armature"),
        "root_bone": str(setting.get("root_bone") or ""),
        "bones": [str(name or "") for name in bones if str(name or "")],
        "enabled": bool(setting.get("enabled", True)),
        "stiffness_force": max(float(setting.get("stiffness_force", 1.0)), 0.0),
        "drag_force": max(0.0, min(1.0, float(setting.get("drag_force", 0.4)))),
        "gravity_dir": float3(setting.get("gravity_dir", (0.0, 0.0, -1.0)), fallback=(0.0, 0.0, -1.0)),
        "gravity_power": max(float(setting.get("gravity_power", 0.0)), 0.0),
    }


def normalize_spring_vrm_chain_objects(vrm_chain_properties) -> list[dict]:
    """把节点传入的 VRM 骨链属性整理成隐式对象 payload。"""
    return [_copy_chain_object(item) for item in normalize_spring_vrm_chain_properties(vrm_chain_properties)]


def spring_vrm_chain_object_signature(setting: dict) -> str:
    armature = setting.get("armature")
    payload = [
        str(as_pointer(armature)),
        str(data_pointer(armature)),
        str(setting.get("root_bone") or ""),
        ",".join(str(name or "") for name in (setting.get("bones") or ())),
        "1" if bool(setting.get("enabled", True)) else "0",
        f"{float(setting.get('stiffness_force', 1.0)):.8g}",
        f"{float(setting.get('drag_force', 0.4)):.8g}",
        ",".join(f"{value:.8g}" for value in float3(setting.get("gravity_dir", (0.0, 0.0, -1.0)))),
        f"{float(setting.get('gravity_power', 0.0)):.8g}",
    ]
    return stable_short_hash(payload, 16)


def spring_vrm_chain_object_stable_id(setting: dict) -> str:
    armature = setting.get("armature")
    bones_hash = stable_short_hash([str(name or "") for name in (setting.get("bones") or ())], 8)
    return (
        f"{SPRING_VRM_CHAIN_OBJECT_TAG}:"
        f"{as_pointer(armature)}:{data_pointer(armature)}:"
        f"{str(setting.get('root_bone') or '')}:{bones_hash}"
    )


def register_spring_vrm_chain_objects(
    world: PhysicsWorldCache,
    vrm_chain_properties,
    enabled: bool = True,
    producer: str = SPRING_VRM_OBJECT_REGISTER_PRODUCER,
) -> tuple[int, int, int]:
    """
    把 VRM 骨链属性注册为 world.implicit_objects。

    用户不需要提供 key；solver 直接按 tag 收集所有 VRM 骨链对象。
    """
    if not isinstance(world, PhysicsWorldCache):
        return 0, 0, 0

    objects = normalize_spring_vrm_chain_objects(vrm_chain_properties)
    writer = str(producer or SPRING_VRM_OBJECT_REGISTER_PRODUCER)
    dirty_count = 0
    version_max = 0

    world.acquire_write(writer)
    try:
        for item in objects:
            item["enabled"] = bool(enabled) and bool(item.get("enabled", True))
            entry = world.append_implicit_object(
                tag=SPRING_VRM_CHAIN_OBJECT_TAG,
                producer=writer,
                stable_id=spring_vrm_chain_object_stable_id(item),
                signature=spring_vrm_chain_object_signature(item),
                enabled=bool(item.get("enabled", True)),
                schema=1,
                payload=item,
            )
            if isinstance(entry, dict):
                dirty_count += 1 if bool(entry.get("dirty", False)) else 0
                version_max = max(version_max, int(entry.get("version", 0) or 0))
    finally:
        world.release_write(writer)

    return len(objects), dirty_count, version_max


def collect_spring_vrm_chain_objects(world: PhysicsWorldCache) -> list[dict]:
    """从 world.implicit_objects 读取启用的 VRM 骨链对象。"""
    if not isinstance(world, PhysicsWorldCache):
        return []

    result: list[dict] = []
    for entry in world.iter_implicit_objects(tag=SPRING_VRM_CHAIN_OBJECT_TAG, enabled=True):
        payload = entry.get("payload")
        if isinstance(payload, dict):
            result.append(payload)
    return result
