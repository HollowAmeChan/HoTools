"""Physics World Bone Action bake backend."""

from __future__ import annotations

import bpy

from ..types import PhysicsWorldCache
from ..writeback_commands import iter_bone_transform_writebacks
from .session import (
    MANIFEST_SCHEMA,
    TARGET_UUID_KEY,
    read_manifest,
    resolve_cache_root,
    safe_prefix,
    write_manifest,
)


_ACTION_OWNER_KEY = "hotools_physics_bake_owner"
_ACTION_TARGET_KEY = "hotools_physics_bake_target"
_ACTION_PREFIX_KEY = "hotools_physics_bake_prefix"
_ACTION_SOURCE_KEY = "hotools_physics_bake_source_action"
_ACTION_OWNER = "physicsWorld.bake.bones"


def _find_armature(armature_ptr: int, data_ptr: int):
    armature_ptr = int(armature_ptr or 0)
    data_ptr = int(data_ptr or 0)
    for obj in bpy.data.objects:
        if obj.type != "ARMATURE" or obj.data is None:
            continue
        try:
            if int(obj.as_pointer()) != armature_ptr:
                continue
            if data_ptr and int(obj.data.as_pointer()) != data_ptr:
                continue
            return obj
        except ReferenceError:
            continue
    return None


def _ensure_armature_target_id(armature) -> str:
    target_id = str(armature.get(TARGET_UUID_KEY, "") or "").strip()
    if not target_id:
        import uuid

        target_id = uuid.uuid4().hex
        armature[TARGET_UUID_KEY] = target_id
    return target_id


def _is_owned_action(action, target_id: str, prefix: str) -> bool:
    return bool(
        action is not None
        and action.get(_ACTION_OWNER_KEY) == _ACTION_OWNER
        and action.get(_ACTION_TARGET_KEY) == target_id
        and action.get(_ACTION_PREFIX_KEY) == prefix
    )


def _find_owned_action(target_id: str, prefix: str):
    for action in bpy.data.actions:
        if _is_owned_action(action, target_id, prefix):
            return action
    return None


def _ensure_bake_action(armature, prefix: str):
    target_id = _ensure_armature_target_id(armature)
    animation_data = armature.animation_data_create()
    current = animation_data.action
    if _is_owned_action(current, target_id, prefix):
        return current, target_id

    owned = _find_owned_action(target_id, prefix)
    if owned is None:
        source = current
        if source is not None:
            owned = source.copy()
            source_name = source.name
        else:
            owned = bpy.data.actions.new(f"{prefix}_{armature.name}_PhysicsBake")
            source_name = ""
        owned.name = f"{prefix}_{armature.name}_PhysicsBake_{target_id[:8]}"
        owned[_ACTION_OWNER_KEY] = _ACTION_OWNER
        owned[_ACTION_TARGET_KEY] = target_id
        owned[_ACTION_PREFIX_KEY] = prefix
        owned[_ACTION_SOURCE_KEY] = source_name
    animation_data.action = owned
    return owned, target_id


def _rotation_data_path(pose_bone) -> str:
    if pose_bone.rotation_mode == "QUATERNION":
        return "rotation_quaternion"
    if pose_bone.rotation_mode == "AXIS_ANGLE":
        return "rotation_axis_angle"
    return "rotation_euler"


def _key_pose_bone(pose_bone, frame: int) -> bool:
    inserted = False
    for data_path in ("location", _rotation_data_path(pose_bone), "scale"):
        inserted = bool(pose_bone.keyframe_insert(data_path=data_path, frame=frame)) or inserted
    return inserted


def _bone_targets(world: PhysicsWorldCache) -> tuple[tuple[object, str], ...]:
    frame_context = world.frame_context
    frame = int(getattr(frame_context, "frame", 0) or 0)
    generation = int(getattr(world, "generation", 0) or 0)
    targets = {}
    for item in iter_bone_transform_writebacks(
        world,
        frame=frame,
        generation=generation,
        expand_batches=True,
    ):
        armature = _find_armature(
            item.get("armature_ptr", 0),
            item.get("armature_data_ptr", 0),
        )
        bone_name = str(item.get("bone_name") or "")
        pose_bone = getattr(getattr(armature, "pose", None), "bones", {}).get(bone_name)
        if armature is None or pose_bone is None:
            continue
        targets[(int(armature.as_pointer()), bone_name)] = (armature, bone_name)
    return tuple(targets[key] for key in sorted(targets))


def _update_bone_manifest(
    cache_directory: str,
    prefix: str,
    frame: int,
    action_records: dict[str, dict],
) -> None:
    root = resolve_cache_root(cache_directory)
    prefix = safe_prefix(prefix)
    manifest = read_manifest(root, prefix) or {
        "schema": MANIFEST_SCHEMA,
        "status": "BONES_ONLY",
        "blend_file": str(bpy.data.filepath or ""),
        "scene": str(getattr(bpy.context.scene, "name", "")),
        "prefix": prefix,
        "targets": {},
    }
    bones = manifest.setdefault("bones", {"status": "ACTIVE", "actions": {}})
    bones["status"] = "ACTIVE"
    actions = bones.setdefault("actions", {})
    for target_id, record in action_records.items():
        existing = actions.get(target_id) or {}
        bone_names = sorted(set(existing.get("bone_names") or ()) | set(record["bone_names"]))
        actions[target_id] = {
            **existing,
            **record,
            "bone_names": bone_names,
            "frame_start": min(int(existing.get("frame_start", frame)), frame),
            "frame_end": max(int(existing.get("frame_end", frame)), frame),
        }
    write_manifest(root, prefix, manifest)


def bake_bone_transforms(
    world: object,
    cache_directory: str,
    prefix: str,
    enabled: bool = True,
) -> tuple[int, int, str]:
    """Key only the PoseBones represented by current Physics World results."""
    if not bool(enabled):
        return 0, 0, "Bone Bake 已关闭"
    if not isinstance(world, PhysicsWorldCache):
        return 0, 0, "world 不是 PhysicsWorldCache"
    frame_context = world.frame_context
    if bool(getattr(frame_context, "same_frame", False)):
        return 0, 0, "同帧重复求值，跳过 Bone Bake"
    frame = int(getattr(frame_context, "frame", 0) or 0)
    prefix = safe_prefix(prefix)
    targets = _bone_targets(world)
    if not targets:
        return 0, 0, "当前帧没有 Bone 写回目标"

    grouped = {}
    for armature, bone_name in targets:
        grouped.setdefault(armature, []).append(bone_name)

    inserted = 0
    action_records = {}
    for armature, bone_names in grouped.items():
        action, target_id = _ensure_bake_action(armature, prefix)
        keyed_names = []
        for bone_name in sorted(set(bone_names)):
            pose_bone = armature.pose.bones.get(bone_name)
            if pose_bone is not None and _key_pose_bone(pose_bone, frame):
                inserted += 1
                keyed_names.append(bone_name)
        if keyed_names:
            action_records[target_id] = {
                "armature_name": armature.name,
                "action_name": action.name,
                "source_action_name": str(action.get(_ACTION_SOURCE_KEY, "") or ""),
                "bone_names": keyed_names,
            }
    if action_records:
        _update_bone_manifest(cache_directory, prefix, frame, action_records)
    return inserted, len(action_records), f"Bone Bake：{inserted} 根骨，{len(action_records)} 个 Action"


__all__ = ["bake_bone_transforms"]
