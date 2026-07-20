"""User-controlled cleanup for Physics World bake sessions."""

from __future__ import annotations

from pathlib import Path

import bpy

from ..gn_offset import clear_gn_local_offsets, get_gn_offset_bake_entry
from ..names import GN_CACHE_MODIFIER_NAME
from ..types import PhysicsWorldCache
from ..writeback import clear_all_deltas
from ..writeback_commands import (
    clear_bone_transform_writebacks,
    clear_gn_offset_writebacks,
)
from .bones import (
    _ACTION_OWNER_KEY,
    _ACTION_OWNER,
    _ACTION_PREFIX_KEY,
    _ACTION_SOURCE_KEY,
    _ACTION_TARGET_KEY,
    current_bone_targets,
)
from .mesh import cancel_pending_geometry_bake, current_mesh_targets
from .session import (
    MANIFEST_SCHEMA,
    TARGET_UUID_KEY,
    read_manifest,
    resolve_cache_root,
    safe_prefix,
    write_manifest,
)


ANIMATION_TRIGGER_FRAME_ONLY = 0
ANIMATION_FROM_CLEAR_FRAME = 1
ANIMATION_SESSION_ALL = 2
MESH_CACHE_KEEP = 0
MESH_CACHE_INVALIDATE_FROM_CLEAR_FRAME = 1
MESH_CACHE_DELETE_SESSION = 2
FINALIZE_KEEP = 0
FINALIZE_MARK_STALE = 1
FINALIZE_DELETE_SESSION = 2

_timeline_stop_requested = False


def _validate_policy(value, labels: tuple[str, ...], name: str) -> int:
    index = int(value)
    if index < 0 or index >= len(labels):
        raise ValueError(f"{name} 无效：{index}")
    return index


def _armature_for_record(target_id: str, record: dict):
    name = str(record.get("armature_name") or "")
    candidate = bpy.data.objects.get(name)
    if (
        candidate is not None
        and candidate.type == "ARMATURE"
        and str(candidate.get(TARGET_UUID_KEY, "") or "") == target_id
    ):
        return candidate
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE" and str(obj.get(TARGET_UUID_KEY, "") or "") == target_id:
            return obj
    return None


def _is_owned_action(action, target_id: str, prefix: str) -> bool:
    return bool(
        action is not None
        and action.get(_ACTION_OWNER_KEY) == _ACTION_OWNER
        and action.get(_ACTION_TARGET_KEY) == target_id
        and action.get(_ACTION_PREFIX_KEY) == prefix
    )


def _action_for_record(target_id: str, prefix: str, record: dict):
    action = bpy.data.actions.get(str(record.get("action_name") or ""))
    if _is_owned_action(action, target_id, prefix):
        return action
    for candidate in bpy.data.actions:
        if _is_owned_action(candidate, target_id, prefix):
            return candidate
    return None


def _assert_action_not_shared(action, armature) -> None:
    foreign_users = []
    for obj in bpy.data.objects:
        animation_data = getattr(obj, "animation_data", None)
        if animation_data is not None and animation_data.action == action and obj != armature:
            foreign_users.append(obj.name)
    if foreign_users:
        raise RuntimeError(
            f"专用 Bake Action {action.name} 被其他对象共享：{', '.join(foreign_users)}"
        )


def _bone_paths(bone_names) -> set[str]:
    paths = set()
    for bone_name in bone_names:
        base = f'pose.bones["{bone_name}"]'
        paths.update({
            f"{base}.location",
            f"{base}.rotation_euler",
            f"{base}.rotation_quaternion",
            f"{base}.rotation_axis_angle",
            f"{base}.scale",
        })
    return paths


def _remove_action_keys(action, paths: set[str], clear_frame: int, mode: int) -> int:
    removed = 0
    for curve in tuple(action.fcurves):
        if curve.data_path not in paths:
            continue
        remove_indices = []
        for index, point in enumerate(curve.keyframe_points):
            point_frame = float(point.co.x)
            should_remove = (
                abs(point_frame - clear_frame) <= 1.0e-4
                if mode == ANIMATION_TRIGGER_FRAME_ONLY
                else point_frame >= clear_frame - 1.0e-4
            )
            if should_remove:
                remove_indices.append(index)
        for index in reversed(remove_indices):
            curve.keyframe_points.remove(curve.keyframe_points[index], fast=True)
        removed += len(remove_indices)
        if curve.keyframe_points:
            curve.update()
        else:
            action.fcurves.remove(curve)
    return removed


def _clear_bone_actions(manifest: dict, prefix: str, clear_frame: int, mode: int):
    bones = manifest.setdefault("bones", {"status": "CLEARED", "actions": {}})
    actions = bones.setdefault("actions", {})
    removed = 0
    participants = {}
    resolved = []
    for target_id, record in tuple(actions.items()):
        if not isinstance(record, dict):
            continue
        armature = _armature_for_record(str(target_id), record)
        action = _action_for_record(str(target_id), prefix, record)
        bone_names = tuple(str(name) for name in record.get("bone_names") or ())
        if armature is not None:
            participants[armature] = set(bone_names)
        if action is not None:
            _assert_action_not_shared(action, armature)
        resolved.append((record, armature, action, bone_names))

    for record, armature, action, bone_names in resolved:
        if action is None:
            record["status"] = "CLEARED"
            continue
        paths = _bone_paths(bone_names)
        if mode == ANIMATION_SESSION_ALL:
            removed += sum(
                len(curve.keyframe_points)
                for curve in action.fcurves
                if curve.data_path in paths
            )
            source = bpy.data.actions.get(str(action.get(_ACTION_SOURCE_KEY, "") or ""))
            if armature is not None:
                animation_data = armature.animation_data_create()
                if animation_data.action == action:
                    animation_data.action = source
            bpy.data.actions.remove(action, do_unlink=True)
            record["action_name"] = ""
            record["status"] = "CLEARED"
        else:
            removed += _remove_action_keys(action, paths, clear_frame, mode)
            source = bpy.data.actions.get(str(action.get(_ACTION_SOURCE_KEY, "") or ""))
            if armature is not None:
                animation_data = armature.animation_data_create()
                if animation_data.action == action:
                    animation_data.action = source
            record["status"] = "PARTIAL"
            record["cleared_from_frame"] = clear_frame
    bones["status"] = "CLEARED" if mode == ANIMATION_SESSION_ALL else "PARTIAL"
    return removed, participants


def _merge_current_bones(participants: dict, world: PhysicsWorldCache) -> None:
    for armature, bone_name in current_bone_targets(world):
        participants.setdefault(armature, set()).add(bone_name)


def _capture_bone_baseline(participants: dict) -> dict:
    baseline = {}
    for armature, bone_names in participants.items():
        target_id = str(armature.get(TARGET_UUID_KEY, "") or "")
        if not target_id:
            continue
        values = {}
        for bone_name in sorted(bone_names):
            pose_bone = armature.pose.bones.get(bone_name)
            if pose_bone is None:
                continue
            values[bone_name] = [float(value) for row in pose_bone.matrix_basis for value in row]
        if values:
            baseline[target_id] = values
            armature.update_tag()
    return baseline


def _mesh_objects(manifest: dict, world: PhysicsWorldCache) -> dict[str, object]:
    result = {}
    wanted = manifest.get("targets") or {}
    for obj in bpy.data.objects:
        target_id = str(obj.get(TARGET_UUID_KEY, "") or "")
        if obj.type == "MESH" and target_id in wanted:
            result[target_id] = obj
    for obj in current_mesh_targets(world):
        target_id = str(obj.get(TARGET_UUID_KEY, "") or "")
        if target_id:
            result[target_id] = obj
    return result


def _disable_existing_cache(obj) -> None:
    modifier = obj.modifiers.get(GN_CACHE_MODIFIER_NAME)
    if modifier is not None and modifier.type == "NODES":
        modifier.show_viewport = False
        modifier.show_render = False
        obj.update_tag()


def _clear_mesh_cache(
    manifest: dict,
    world: PhysicsWorldCache,
    root: Path,
    clear_frame: int,
    policy: int,
) -> int:
    if policy == MESH_CACHE_KEEP:
        return 0
    objects = _mesh_objects(manifest, world)
    processed = 0
    for target_id, record in (manifest.get("targets") or {}).items():
        if not isinstance(record, dict):
            continue
        obj = objects.get(str(target_id))
        if policy == MESH_CACHE_INVALIDATE_FROM_CLEAR_FRAME:
            if (
                record.get("status") == "STALE"
                and int(record.get("stale_from_frame", clear_frame)) == clear_frame
            ):
                if obj is not None:
                    _disable_existing_cache(obj)
                continue
            record["status"] = "STALE"
            record["stale_from_frame"] = clear_frame
            if obj is not None:
                _disable_existing_cache(obj)
            processed += 1
            continue
        if obj is None:
            record["delete_error"] = "目标对象不存在，未删除磁盘缓存"
            continue
        if record.get("status") == "DELETED":
            _disable_existing_cache(obj)
            continue
        directory = _owned_path(root, str(record.get("directory") or ""))
        if directory is None:
            record["delete_error"] = "缓存目录不在 session 根目录内"
            continue
        modifier = obj.modifiers.get(GN_CACHE_MODIFIER_NAME)
        if modifier is None or modifier.type != "NODES":
            record["delete_error"] = "受管缓存修改器不存在"
            continue
        entry = get_gn_offset_bake_entry(modifier)
        entry_directory = _owned_path(
            root,
            bpy.path.abspath(str(getattr(entry, "directory", "") or "")),
        )
        if entry_directory != directory:
            record["delete_error"] = "修改器 Bake entry 与 manifest 目录不一致"
            continue
        result = bpy.ops.object.geometry_node_bake_delete_single(
            session_uid=int(obj.session_uid),
            modifier_name=modifier.name,
            bake_id=int(entry.bake_id),
        )
        if result != {"FINISHED"}:
            record["delete_error"] = f"Blender delete 返回 {sorted(result)}"
            continue
        _disable_existing_cache(obj)
        record.update({"status": "DELETED", "file_count": 0, "byte_size": 0})
        record.pop("delete_error", None)
        processed += 1
    if processed:
        manifest["status"] = (
            "STALE" if policy == MESH_CACHE_INVALIDATE_FROM_CLEAR_FRAME else "CLEARED"
        )
    return processed


def _owned_path(root: Path, value: str) -> Path | None:
    if not value:
        return None
    path = Path(value).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _clear_finalize(manifest: dict, root: Path, policy: int) -> int:
    finalize = manifest.get("finalize")
    if not isinstance(finalize, dict) or policy == FINALIZE_KEEP:
        return 0
    if policy == FINALIZE_MARK_STALE:
        if bool(finalize.get("stale", False)):
            return 0
        finalize["stale"] = True
        return 1
    removed = 0
    files = finalize.get("files") or ()
    if isinstance(files, str):
        files = (files,)
    values = [finalize.get("path"), *files]
    for value in values:
        path = _owned_path(root, str(value or ""))
        if path is not None and path.is_file():
            path.unlink()
            removed += 1
    finalize.update({"status": "DELETED", "stale": True})
    return removed


def _stop_timeline_timer():
    global _timeline_stop_requested
    _timeline_stop_requested = False
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in tuple(getattr(window_manager, "windows", ())):
        screen = getattr(window, "screen", None)
        if screen is None or not bool(getattr(screen, "is_animation_playing", False)):
            continue
        try:
            with bpy.context.temp_override(window=window, screen=screen):
                bpy.ops.screen.animation_cancel(restore_frame=False)
        except Exception:
            continue
    return None


def request_timeline_stop() -> None:
    global _timeline_stop_requested
    if _timeline_stop_requested:
        return
    _timeline_stop_requested = True
    if not bpy.app.timers.is_registered(_stop_timeline_timer):
        bpy.app.timers.register(_stop_timeline_timer, first_interval=0.0)


def shutdown_clear_runtime() -> None:
    global _timeline_stop_requested
    if bpy.app.timers.is_registered(_stop_timeline_timer):
        bpy.app.timers.unregister(_stop_timeline_timer)
    _timeline_stop_requested = False


def clear_physics_bake(
    world: object,
    cache_directory: str,
    prefix: str,
    clear_frame: int = 1,
    animation_clear_mode: int = ANIMATION_SESSION_ALL,
    mesh_cache_policy: int = MESH_CACHE_KEEP,
    finalize_cache_policy: int = FINALIZE_KEEP,
    clear_live_output: bool = True,
    pause_timeline: bool = True,
    enabled: bool = True,
) -> tuple[int, int, str]:
    if not bool(enabled):
        return 0, 0, "Clear Physics Bake 已禁用"
    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world 不是 PhysicsWorldCache")
    frame = int(bpy.context.scene.frame_current)
    clear_frame = int(clear_frame)
    if frame != clear_frame:
        return 0, 0, f"等待清理帧 {clear_frame}（当前 {frame}）"

    animation_mode = _validate_policy(
        animation_clear_mode,
        ("TRIGGER_FRAME_ONLY", "FROM_CLEAR_FRAME", "SESSION_ALL"),
        "动画清理模式",
    )
    mesh_policy = _validate_policy(
        mesh_cache_policy,
        ("KEEP", "INVALIDATE_FROM_CLEAR_FRAME", "DELETE_SESSION"),
        "Mesh 缓存策略",
    )
    finalize_policy = _validate_policy(
        finalize_cache_policy,
        ("KEEP", "MARK_STALE", "DELETE_SESSION"),
        "最终缓存策略",
    )
    root = resolve_cache_root(cache_directory)
    prefix = safe_prefix(prefix)
    manifest = read_manifest(root, prefix) or {
        "schema": MANIFEST_SCHEMA,
        "status": "CLEARED",
        "blend_file": str(bpy.data.filepath or ""),
        "scene": str(bpy.context.scene.name),
        "prefix": prefix,
        "targets": {},
    }

    cancel_pending_geometry_bake()
    removed_keys, participants = _clear_bone_actions(
        manifest, prefix, clear_frame, animation_mode
    )
    _merge_current_bones(participants, world)
    mesh_count = _clear_mesh_cache(manifest, world, root, clear_frame, mesh_policy)
    finalize_count = _clear_finalize(manifest, root, finalize_policy)

    if bool(clear_live_output):
        clear_all_deltas(world)
        for obj in current_mesh_targets(world):
            clear_gn_local_offsets(obj)
        clear_bone_transform_writebacks(world)
        clear_gn_offset_writebacks(world)

    baseline_bones = _capture_bone_baseline(participants)
    previous_baseline = (manifest.get("boundary_baseline") or {}).get("bones") or {}
    previous_clear = manifest.get("last_clear") or {}
    clear_signature = {
        "frame": clear_frame,
        "animation_clear_mode": animation_mode,
        "mesh_cache_policy": mesh_policy,
        "finalize_cache_policy": finalize_policy,
    }
    changed = bool(
        removed_keys
        or mesh_count
        or finalize_count
        or baseline_bones != previous_baseline
        or any(previous_clear.get(key) != value for key, value in clear_signature.items())
    )
    manifest["boundary_frame"] = clear_frame
    revision = int(manifest.get("boundary_baseline_revision", 0) or 0)
    manifest["boundary_baseline_revision"] = revision + 1 if changed else revision
    manifest["boundary_baseline"] = {"bones": baseline_bones}
    manifest["last_clear"] = {
        **clear_signature,
        "removed_keys": removed_keys,
    }
    write_manifest(root, prefix, manifest)
    if bool(pause_timeline):
        request_timeline_stop()
    return (
        removed_keys,
        mesh_count,
        f"Clear 完成：动画 {removed_keys}，Mesh {mesh_count}，最终文件 {finalize_count}",
    )


__all__ = [
    "ANIMATION_FROM_CLEAR_FRAME",
    "ANIMATION_SESSION_ALL",
    "ANIMATION_TRIGGER_FRAME_ONLY",
    "FINALIZE_DELETE_SESSION",
    "FINALIZE_KEEP",
    "FINALIZE_MARK_STALE",
    "MESH_CACHE_DELETE_SESSION",
    "MESH_CACHE_INVALIDATE_FROM_CLEAR_FRAME",
    "MESH_CACHE_KEEP",
    "clear_physics_bake",
    "request_timeline_stop",
    "shutdown_clear_runtime",
]
