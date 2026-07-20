"""Geometry Nodes mesh bake coordinator for the Physics Bake OmniNode."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid

import bpy

from ..gn_offset import (
    configure_gn_offset_disk_bake,
    get_gn_offset_bake_entry,
    set_gn_offset_cache_enabled,
)
from ..names import GN_CACHE_MODIFIER_NAME
from ..types import PhysicsWorldCache
from ..writeback_commands import iter_gn_offset_writebacks
from .session import (
    MANIFEST_SCHEMA as _MANIFEST_SCHEMA,
    TARGET_UUID_KEY as _TARGET_UUID_KEY,
    read_manifest as _read_manifest,
    resolve_cache_root,
    safe_prefix as _safe_prefix,
    write_manifest as _write_manifest,
)


@dataclass(frozen=True)
class GeometryBakeTarget:
    target_id: str
    object_name: str
    directory: str


@dataclass(frozen=True)
class GeometryBakeRequest:
    signature: tuple
    root_directory: str
    prefix: str
    frame_start: int
    frame_end: int
    use_cache_after_bake: bool
    targets: tuple[GeometryBakeTarget, ...]


_pending_request: GeometryBakeRequest | None = None
_active_request: GeometryBakeRequest | None = None
_active_target_index: int | None = None
_last_trigger_signature: tuple | None = None
_last_status = "未请求烘焙"


def _find_mesh_object(object_ptr: int, data_ptr: int):
    object_ptr = int(object_ptr or 0)
    data_ptr = int(data_ptr or 0)
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        try:
            if int(obj.as_pointer()) == object_ptr and int(obj.data.as_pointer()) == data_ptr:
                return obj
        except ReferenceError:
            continue
    return None


def _ensure_target_ids(objects) -> dict[str, object]:
    resolved = {}
    for obj in objects:
        target_id = str(obj.get(_TARGET_UUID_KEY, "") or "").strip()
        if not target_id or target_id in resolved:
            target_id = uuid.uuid4().hex
            obj[_TARGET_UUID_KEY] = target_id
        resolved[target_id] = obj
    return resolved


def current_mesh_targets(world: object) -> tuple[object, ...]:
    if not isinstance(world, PhysicsWorldCache):
        return ()
    frame_context = getattr(world, "frame_context", None)
    frame = int(getattr(frame_context, "frame", 0) or 0)
    generation = int(getattr(world, "generation", 0) or 0)
    objects = []
    seen = set()
    for item in iter_gn_offset_writebacks(world, frame=frame, generation=generation):
        obj = _find_mesh_object(item.get("object_ptr", 0), item.get("object_data_ptr", 0))
        if obj is None:
            continue
        pointer = int(obj.as_pointer())
        if pointer not in seen:
            seen.add(pointer)
            objects.append(obj)
    return tuple(objects)


def _objects_from_manifest(manifest: dict | None) -> dict[str, object]:
    if not isinstance(manifest, dict):
        return {}
    wanted = {
        str(target_id): data
        for target_id, data in (manifest.get("targets") or {}).items()
        if isinstance(data, dict)
    }
    found = {}
    for obj in bpy.data.objects:
        target_id = str(obj.get(_TARGET_UUID_KEY, "") or "")
        if target_id in wanted and obj.type == "MESH":
            found[target_id] = obj
    return found


def _target_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.rglob("*") if path.is_file())


def set_session_cache_playback(
    world: object,
    cache_directory: str,
    prefix: str,
    enabled: bool,
) -> tuple[int, str]:
    root = resolve_cache_root(cache_directory)
    safe_prefix = _safe_prefix(prefix)
    manifest = _read_manifest(root, safe_prefix)
    objects = _objects_from_manifest(manifest)
    current = current_mesh_targets(world)
    current_by_id = _ensure_target_ids(current) if current else {}
    objects.update(current_by_id)

    if bool(enabled):
        if not manifest or manifest.get("status") != "COMPLETE":
            return 0, "缓存尚未完成，保持实时模式"
        complete_targets = manifest.get("targets") or {}
        validated = []
        for target_id, record in complete_targets.items():
            obj = objects.get(target_id)
            directory = Path(str(record.get("directory") or ""))
            if (
                obj is None
                or record.get("status") != "COMPLETE"
                or not _target_files(directory)
            ):
                for candidate in objects.values():
                    modifier = candidate.modifiers.get(GN_CACHE_MODIFIER_NAME)
                    if modifier is not None and modifier.type == "NODES":
                        set_gn_offset_cache_enabled(candidate, False)
                return 0, "缓存目标或文件缺失，保持实时模式"
            validated.append(obj)
        for obj in validated:
            set_gn_offset_cache_enabled(obj, True)
        enabled_count = len(validated)
        return enabled_count, f"正在使用 {enabled_count} 个 Mesh 缓存"

    disabled_count = 0
    for obj in objects.values():
        modifier = obj.modifiers.get(GN_CACHE_MODIFIER_NAME)
        if modifier is None or modifier.type != "NODES":
            continue
        set_gn_offset_cache_enabled(obj, False)
        disabled_count += 1
    return disabled_count, f"实时模式；保留 {disabled_count} 个 Mesh 缓存"


def _build_request(
    world: object,
    cache_directory: str,
    prefix: str,
    frame_start: int,
    frame_end: int,
    use_cache_after_bake: bool,
) -> GeometryBakeRequest:
    if not bpy.data.filepath:
        raise ValueError("Geometry Nodes Bake 前必须先保存 .blend")
    start = int(frame_start)
    end = int(frame_end)
    if end < start:
        raise ValueError("物理烘焙结束帧不能小于开始帧")
    root = resolve_cache_root(cache_directory)
    safe_prefix = _safe_prefix(prefix)
    objects = current_mesh_targets(world)
    if not objects:
        raise ValueError("当前 Physics World 没有可烘焙的 Mesh 写回目标")
    by_id = _ensure_target_ids(objects)
    targets = tuple(
        GeometryBakeTarget(
            target_id=target_id,
            object_name=obj.name,
            directory=str((root / safe_prefix / target_id).resolve()),
        )
        for target_id, obj in sorted(by_id.items())
    )
    signature = (
        str(root),
        safe_prefix,
        start,
        end,
        tuple(target.target_id for target in targets),
    )
    return GeometryBakeRequest(
        signature=signature,
        root_directory=str(root),
        prefix=safe_prefix,
        frame_start=start,
        frame_end=end,
        use_cache_after_bake=bool(use_cache_after_bake),
        targets=targets,
    )


def _schedule_timer() -> None:
    if not bpy.app.timers.is_registered(_geometry_bake_timer):
        bpy.app.timers.register(_geometry_bake_timer, first_interval=0.0)


def request_geometry_bake(
    world: object,
    cache_directory: str,
    prefix: str,
    frame_start: int,
    frame_end: int,
    use_cache_after_bake: bool,
) -> tuple[int, str]:
    global _pending_request, _last_trigger_signature, _last_status
    request = _build_request(
        world,
        cache_directory,
        prefix,
        frame_start,
        frame_end,
        use_cache_after_bake,
    )
    if _active_request is not None:
        return len(_active_request.targets), "Mesh Bake 正在运行"
    if _pending_request is not None:
        return len(_pending_request.targets), "Mesh Bake 已排队"
    if request.signature == _last_trigger_signature:
        return len(request.targets), _last_status
    _pending_request = request
    _last_trigger_signature = request.signature
    _last_status = f"已排队 {len(request.targets)} 个 Mesh"
    _schedule_timer()
    return len(request.targets), _last_status


def rearm_geometry_bake_trigger() -> None:
    global _last_trigger_signature
    if _active_request is None and _pending_request is None:
        _last_trigger_signature = None


def cancel_pending_geometry_bake() -> bool:
    """Cancel a request queued earlier in the same tree evaluation."""
    global _pending_request, _last_trigger_signature, _last_status
    if _active_request is not None or _pending_request is None:
        return False
    if bpy.app.timers.is_registered(_geometry_bake_timer):
        bpy.app.timers.unregister(_geometry_bake_timer)
    _pending_request = None
    _last_trigger_signature = None
    _last_status = "Mesh Bake 排队已由 Clear 取消"
    return True


def geometry_bake_status() -> str:
    return str(_last_status)


def geometry_bake_is_active() -> bool:
    return _active_request is not None


def geometry_bake_should_record_actions() -> bool:
    """Record Action backends only during the first full timeline evaluation."""
    return _active_request is None or _active_target_index in (None, 0)


def geometry_bake_target_count() -> int:
    request = _active_request or _pending_request
    return len(request.targets) if request is not None else 0


def _manifest_for_request(request: GeometryBakeRequest) -> dict:
    return {
        "schema": _MANIFEST_SCHEMA,
        "status": "BAKING",
        "blend_file": str(bpy.data.filepath or ""),
        "scene": str(getattr(bpy.context.scene, "name", "")),
        "prefix": request.prefix,
        "frame_start": request.frame_start,
        "frame_end": request.frame_end,
        "targets": {
            target.target_id: {
                "object_name": target.object_name,
                "directory": target.directory,
                "status": "PENDING",
            }
            for target in request.targets
        },
    }


def _write_mesh_manifest(root: Path, prefix: str, manifest: dict) -> None:
    current = _read_manifest(root, prefix)
    if isinstance(current, dict):
        for key in (
            "bones",
            "boundary_frame",
            "boundary_baseline_revision",
            "boundary_baseline",
            "last_clear",
            "finalize",
        ):
            if key in current:
                manifest[key] = current[key]
    _write_manifest(root, prefix, manifest)


def _resolve_request_object(target: GeometryBakeTarget):
    obj = bpy.data.objects.get(target.object_name)
    if obj is not None and str(obj.get(_TARGET_UUID_KEY, "") or "") == target.target_id:
        return obj
    for candidate in bpy.data.objects:
        if str(candidate.get(_TARGET_UUID_KEY, "") or "") == target.target_id:
            return candidate
    return None


def run_pending_geometry_bake() -> bool:
    """Run one queued request synchronously. Intended for timer and tests."""
    global _pending_request, _active_request, _active_target_index, _last_status
    if _active_request is not None or _pending_request is None:
        return False
    request = _pending_request
    _pending_request = None
    _active_request = request
    _last_status = f"Mesh Bake 正在运行：{len(request.targets)} 个目标"
    root = Path(request.root_directory)
    manifest = _manifest_for_request(request)
    original_frame = int(bpy.context.scene.frame_current)
    original_active = bpy.context.view_layer.objects.active
    original_selected = tuple(bpy.context.selected_objects)
    completed = set()
    try:
        _write_mesh_manifest(root, request.prefix, manifest)
        for target_index, target in enumerate(request.targets):
            _active_target_index = target_index
            obj = _resolve_request_object(target)
            if obj is None or obj.type != "MESH":
                raise RuntimeError(f"Bake target 已失效：{target.object_name}")
            Path(target.directory).mkdir(parents=True, exist_ok=True)
            modifier, _entry = configure_gn_offset_disk_bake(
                obj,
                target.directory,
                request.frame_start,
                request.frame_end,
            )
            set_gn_offset_cache_enabled(obj, True)
            entry = get_gn_offset_bake_entry(modifier)
            result = bpy.ops.object.geometry_node_bake_single(
                session_uid=int(obj.session_uid),
                modifier_name=modifier.name,
                bake_id=int(entry.bake_id),
            )
            if result != {"FINISHED"}:
                raise RuntimeError(f"Blender Bake 失败：{obj.name} {sorted(result)}")
            files = _target_files(Path(target.directory))
            if not files:
                raise RuntimeError(f"Blender Bake 未生成磁盘文件：{obj.name}")
            completed.add(target.target_id)
            record = manifest["targets"][target.target_id]
            record["status"] = "COMPLETE"
            record["file_count"] = len(files)
            record["byte_size"] = sum(path.stat().st_size for path in files)
            _write_mesh_manifest(root, request.prefix, manifest)
        manifest["status"] = "COMPLETE"
        _write_mesh_manifest(root, request.prefix, manifest)
        _last_status = f"Mesh Bake 完成：{len(completed)} 个目标"
        return True
    except Exception as exc:
        manifest["status"] = "PARTIAL" if completed else "FAILED"
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        _last_status = f"Mesh Bake 失败：{exc}"
        try:
            _write_mesh_manifest(root, request.prefix, manifest)
        except Exception:
            pass
        return False
    finally:
        for target in request.targets:
            obj = _resolve_request_object(target)
            if obj is not None:
                use_cache = bool(
                    request.use_cache_after_bake
                    and target.target_id in completed
                    and manifest.get("status") == "COMPLETE"
                )
                try:
                    set_gn_offset_cache_enabled(obj, use_cache)
                except Exception:
                    pass
        try:
            bpy.context.scene.frame_set(original_frame)
            for obj in bpy.context.selected_objects:
                obj.select_set(False)
            for obj in original_selected:
                if obj.name in bpy.context.view_layer.objects:
                    obj.select_set(True)
            if original_active is not None and original_active.name in bpy.context.view_layer.objects:
                bpy.context.view_layer.objects.active = original_active
        finally:
            _active_target_index = None
            _active_request = None


def _geometry_bake_timer():
    run_pending_geometry_bake()
    return None


def shutdown_geometry_bake_runtime() -> None:
    global _pending_request, _active_request, _active_target_index
    global _last_trigger_signature, _last_status
    if bpy.app.timers.is_registered(_geometry_bake_timer):
        bpy.app.timers.unregister(_geometry_bake_timer)
    _pending_request = None
    _active_request = None
    _active_target_index = None
    _last_trigger_signature = None
    _last_status = "未请求烘焙"


def reset_geometry_bake_runtime_for_tests() -> None:
    shutdown_geometry_bake_runtime()


__all__ = [
    "cancel_pending_geometry_bake",
    "current_mesh_targets",
    "geometry_bake_is_active",
    "geometry_bake_should_record_actions",
    "geometry_bake_status",
    "geometry_bake_target_count",
    "rearm_geometry_bake_trigger",
    "request_geometry_bake",
    "reset_geometry_bake_runtime_for_tests",
    "resolve_cache_root",
    "run_pending_geometry_bake",
    "set_session_cache_playback",
    "shutdown_geometry_bake_runtime",
]
