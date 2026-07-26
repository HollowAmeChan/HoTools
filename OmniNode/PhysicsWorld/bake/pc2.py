"""Incremental PC2 mesh cache backend for Physics World Bake."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import re
import struct
import uuid

import bpy
import numpy as np

from ..names import PC2_CACHE_MODIFIER_NAME
from ..types import PhysicsWorldCache
from ..writeback_commands import iter_gn_offset_writebacks
from .session import (
    MANIFEST_SCHEMA,
    TARGET_UUID_KEY,
    read_manifest,
    resolve_cache_root,
    safe_prefix,
    write_manifest,
)


PC2_SIGNATURE = b"POINTCACHE2\0"
PC2_VERSION = 1
PC2_HEADER = struct.Struct("<12siiffi")
PC2_MODIFIER_NAME = PC2_CACHE_MODIFIER_NAME
_MODIFIER_OWNER_KEY = "hotools_physics_bake_owner"
_MODIFIER_TARGET_KEY = "hotools_physics_bake_target"
_MODIFIER_OWNER = "physicsWorld.bake.pc2"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SESSION_KEYS = (
    "bones",
    "boundary_frame",
    "boundary_baseline_revision",
    "boundary_baseline",
    "last_clear",
    "finalize",
)

_last_status = "PC2 尚未记录"


@dataclass(frozen=True)
class PC2Header:
    version: int
    vertex_count: int
    start_frame: float
    sample_rate: float
    sample_count: int


def _safe_object_name(name: str) -> str:
    value = _SAFE_NAME_RE.sub("_", str(name or "").strip()).strip("._")
    return value or "Mesh"


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


def current_mesh_targets(world: object) -> tuple[object, ...]:
    if not isinstance(world, PhysicsWorldCache):
        return ()
    frame = int(getattr(world.frame_context, "frame", 0) or 0)
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


def _ensure_target_ids(objects) -> dict[str, object]:
    resolved = {}
    for obj in objects:
        target_id = str(obj.get(TARGET_UUID_KEY, "") or "").strip()
        if not target_id or target_id in resolved:
            target_id = uuid.uuid4().hex
            obj[TARGET_UUID_KEY] = target_id
        resolved[target_id] = obj
    return resolved


def _object_for_target(target_id: str, record: dict | None = None):
    name = str((record or {}).get("object_name") or "")
    obj = bpy.data.objects.get(name)
    if (
        obj is not None
        and obj.type == "MESH"
        and str(obj.get(TARGET_UUID_KEY, "") or "") == target_id
    ):
        return obj
    for candidate in bpy.data.objects:
        if (
            candidate.type == "MESH"
            and str(candidate.get(TARGET_UUID_KEY, "") or "") == target_id
        ):
            return candidate
    return None


def objects_from_manifest(manifest: dict | None) -> dict[str, object]:
    if not isinstance(manifest, dict):
        return {}
    result = {}
    for target_id, record in (manifest.get("targets") or {}).items():
        if not isinstance(record, dict):
            continue
        obj = _object_for_target(str(target_id), record)
        if obj is not None:
            result[str(target_id)] = obj
    return result


def _modifier_is_owned(modifier, target_id: str) -> bool:
    obj = getattr(modifier, "id_data", None)
    return bool(
        modifier is not None
        and modifier.type == "MESH_CACHE"
        and obj is not None
        and obj.get(_MODIFIER_OWNER_KEY) == _MODIFIER_OWNER
        and obj.get(_MODIFIER_TARGET_KEY) == target_id
    )


def ensure_pc2_modifier(obj, target_id: str, filepath: Path, frame_start: int):
    modifier = obj.modifiers.get(PC2_MODIFIER_NAME)
    if modifier is not None and not _modifier_is_owned(modifier, target_id):
        raise RuntimeError(f"{obj.name} 已有同名但不属于本 Bake Session 的修改器")
    if modifier is None:
        modifier = obj.modifiers.new(PC2_MODIFIER_NAME, "MESH_CACHE")
    obj[_MODIFIER_OWNER_KEY] = _MODIFIER_OWNER
    obj[_MODIFIER_TARGET_KEY] = target_id
    modifier.cache_format = "PC2"
    modifier.filepath = str(filepath)
    modifier.frame_start = float(frame_start)
    modifier.frame_scale = 1.0
    modifier.interpolation = "LINEAR"
    modifier.deform_mode = "OVERWRITE"
    modifier.factor = 1.0
    # PC2 stores Blender object-local XYZ directly. POS_Y/POS_Z is Blender's
    # identity axis mapping for Mesh Cache; POS_X would rotate X/Y on playback.
    modifier.forward_axis = "POS_Y"
    modifier.up_axis = "POS_Z"
    modifier.flip_axis = (False, False, False)
    index = obj.modifiers.find(modifier.name)
    if index != len(obj.modifiers) - 1:
        obj.modifiers.move(index, len(obj.modifiers) - 1)
    return modifier


def set_pc2_playback_enabled(obj, target_id: str, enabled: bool) -> bool:
    modifier = obj.modifiers.get(PC2_MODIFIER_NAME)
    if not _modifier_is_owned(modifier, target_id):
        return False
    modifier.show_viewport = bool(enabled)
    modifier.show_render = bool(enabled)
    obj.update_tag()
    return True


def remove_pc2_modifier(obj, target_id: str) -> bool:
    modifier = obj.modifiers.get(PC2_MODIFIER_NAME)
    if not _modifier_is_owned(modifier, target_id):
        return False
    obj.modifiers.remove(modifier)
    if obj.get(_MODIFIER_TARGET_KEY) == target_id:
        obj.pop(_MODIFIER_OWNER_KEY, None)
        obj.pop(_MODIFIER_TARGET_KEY, None)
    obj.update_tag()
    return True


def read_pc2_header(path: Path) -> PC2Header:
    with path.open("rb") as stream:
        payload = stream.read(PC2_HEADER.size)
    if len(payload) != PC2_HEADER.size:
        raise ValueError(f"PC2 header 不完整：{path}")
    signature, version, vertex_count, start, rate, count = PC2_HEADER.unpack(payload)
    if signature != PC2_SIGNATURE or int(version) != PC2_VERSION:
        raise ValueError(f"PC2 header 无效：{path}")
    return PC2Header(int(version), int(vertex_count), float(start), float(rate), int(count))


def _write_header(stream, vertex_count: int, start_frame: int, sample_count: int) -> None:
    stream.seek(0)
    stream.write(PC2_HEADER.pack(
        PC2_SIGNATURE,
        PC2_VERSION,
        int(vertex_count),
        float(start_frame),
        1.0,
        int(sample_count),
    ))


def _normalize_positions(positions) -> np.ndarray:
    values = np.asarray(positions, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("PC2 positions 必须是 float32[N,3]")
    if not np.isfinite(values).all():
        raise ValueError("PC2 positions 包含 NaN 或 Inf")
    return np.ascontiguousarray(values, dtype="<f4")


def write_pc2_sample(path: Path, positions, start_frame: int, frame: int) -> int:
    values = _normalize_positions(positions)
    sample_index = int(frame) - int(start_frame)
    if sample_index < 0:
        raise ValueError("PC2 sample 早于开始帧")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        if sample_index != 0:
            raise ValueError(f"PC2 不能跳过开始帧直接写第 {frame} 帧")
        with path.open("w+b") as stream:
            _write_header(stream, len(values), start_frame, 1)
            stream.seek(PC2_HEADER.size)
            stream.write(values.tobytes(order="C"))
        return 1

    header = read_pc2_header(path)
    if header.vertex_count != len(values):
        raise ValueError("PC2 顶点数量发生变化")
    if abs(header.start_frame - float(start_frame)) > 1.0e-6 or header.sample_rate != 1.0:
        raise ValueError("PC2 帧映射与当前 Session 不一致")
    if sample_index > header.sample_count:
        raise ValueError(f"PC2 不允许产生帧缺口：当前 sample={header.sample_count}，请求={sample_index}")
    new_count = max(header.sample_count, sample_index + 1)
    stride = header.vertex_count * 12
    with path.open("r+b") as stream:
        stream.seek(PC2_HEADER.size + sample_index * stride)
        stream.write(values.tobytes(order="C"))
        if new_count != header.sample_count:
            _write_header(stream, header.vertex_count, start_frame, new_count)
    return new_count


def truncate_pc2(path: Path, sample_count: int) -> bool:
    if not path.is_file():
        return False
    header = read_pc2_header(path)
    count = max(0, min(int(sample_count), header.sample_count))
    size = PC2_HEADER.size + count * header.vertex_count * 12
    with path.open("r+b") as stream:
        stream.truncate(size)
        _write_header(stream, header.vertex_count, int(round(header.start_frame)), count)
    return count != header.sample_count


def _evaluated_positions(obj) -> np.ndarray:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        values = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", values)
        return values.reshape((-1, 3)).copy()
    finally:
        evaluated.to_mesh_clear()


def _new_manifest(root: Path, prefix: str, frame_start: int, frame_end: int) -> dict:
    previous = read_manifest(root, prefix)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "backend": "PC2",
        "status": "RECORDING",
        "blend_file": str(bpy.data.filepath or ""),
        "scene": str(bpy.context.scene.name),
        "prefix": prefix,
        "frame_start": int(frame_start),
        "frame_end": int(frame_end),
        "targets": {},
    }
    if isinstance(previous, dict):
        for key in _SESSION_KEYS:
            if key in previous:
                manifest[key] = previous[key]
    return manifest


def _read_pc2_manifest(root: Path, prefix: str, frame_start: int, frame_end: int) -> dict:
    manifest = read_manifest(root, prefix)
    if not isinstance(manifest, dict) or manifest.get("backend") != "PC2":
        return _new_manifest(root, prefix, frame_start, frame_end)
    if (
        int(manifest.get("frame_start", frame_start)) != int(frame_start)
        or int(manifest.get("frame_end", frame_end)) != int(frame_end)
    ):
        raise ValueError("现有 PC2 Session 帧范围不同，请先用 Clear 删除或失效缓存")
    return manifest


def _write_pc2_manifest(root: Path, prefix: str, manifest: dict) -> None:
    current = read_manifest(root, prefix)
    if isinstance(current, dict):
        for key in _SESSION_KEYS:
            if key in current:
                manifest[key] = current[key]
    write_manifest(root, prefix, manifest)


def _target_path(root: Path, prefix: str, obj, target_id: str) -> Path:
    return root / f"{prefix}_{_safe_object_name(obj.name)}_{target_id[:8]}.pc2"


def _owned_path(root: Path, value: str) -> Path | None:
    if not value:
        return None
    path = Path(value).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _record_complete(record: dict, frame_start: int, frame_end: int) -> bool:
    expected = list(range(int(frame_start), int(frame_end) + 1))
    return sorted(set(int(frame) for frame in record.get("written_frames") or ())) == expected


def request_geometry_bake(
    world: object,
    cache_directory: str,
    prefix: str,
    frame_start: int,
    frame_end: int,
    use_cache_after_bake: bool,
) -> tuple[int, str]:
    global _last_status
    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world 不是 PhysicsWorldCache")
    if bool(getattr(world.frame_context, "same_frame", False)):
        return 0, "同帧重复求值，跳过 PC2"
    frame = int(getattr(world.frame_context, "frame", bpy.context.scene.frame_current) or 0)
    start = int(frame_start)
    end = int(frame_end)
    if end < start:
        raise ValueError("物理烘焙结束帧不能小于开始帧")
    if frame < start or frame > end:
        return 0, f"当前帧 {frame} 不在 PC2 范围 {start}..{end}"
    root = resolve_cache_root(cache_directory)
    prefix = safe_prefix(prefix)
    objects = current_mesh_targets(world)
    if not objects:
        return 0, "当前帧没有 Mesh 写回目标"
    by_id = _ensure_target_ids(objects)
    manifest = _read_pc2_manifest(root, prefix, start, end)
    existing_ids = set((manifest.get("targets") or {}).keys())
    if existing_ids and existing_ids != set(by_id):
        missing = sorted(existing_ids - set(by_id))
        added = sorted(set(by_id) - existing_ids)
        raise ValueError(
            "PC2 Session 的真实 Mesh 目标集合发生变化；"
            f"缺少={missing or '无'}，新增={added or '无'}"
        )

    samples = {}
    for target_id, obj in sorted(by_id.items()):
        existing = (manifest.get("targets") or {}).get(target_id) or {}
        if existing and int(existing.get("vertex_count", -1)) < 0:
            raise ValueError(f"PC2 target manifest 无效：{obj.name}")
        set_pc2_playback_enabled(obj, target_id, False)
        samples[target_id] = (obj, _evaluated_positions(obj))

    records = manifest.setdefault("targets", {})
    for target_id, (obj, positions) in samples.items():
        record = records.get(target_id)
        if record is None:
            if frame != start:
                raise ValueError(f"新 PC2 target {obj.name} 必须从开始帧 {start} 写入")
            path = _target_path(root, prefix, obj, target_id)
            record = {
                "object_name": obj.name,
                "file": str(path.resolve()),
                "vertex_count": int(len(positions)),
                "written_frames": [],
                "status": "RECORDING",
            }
            records[target_id] = record
        else:
            path = _owned_path(root, str(record.get("file") or ""))
            suffix = f"_{target_id[:8]}.pc2"
            if (
                path is None
                or not path.name.startswith(f"{prefix}_")
                or not path.name.endswith(suffix)
            ):
                raise ValueError(f"PC2 target 路径 ownership 无效：{obj.name}")
            record["object_name"] = obj.name
        if int(record.get("vertex_count", -1)) != len(positions):
            raise ValueError(f"PC2 target 顶点数量发生变化：{obj.name}")

    write_jobs = [
        (target_id, Path(records[target_id]["file"]), positions)
        for target_id, (_obj, positions) in sorted(samples.items())
    ]

    def write_job(job):
        target_id, path, positions = job
        return target_id, write_pc2_sample(path, positions, start, frame)

    if len(write_jobs) > 1:
        with ThreadPoolExecutor(max_workers=min(8, len(write_jobs))) as executor:
            written_counts = dict(executor.map(write_job, write_jobs))
    else:
        written_counts = dict(map(write_job, write_jobs))

    for target_id, (obj, _positions) in samples.items():
        record = records[target_id]
        path = Path(record["file"])
        frames = sorted(set(int(value) for value in record.get("written_frames") or ()) | {frame})
        record["written_frames"] = frames
        record["frame_start"] = frames[0]
        record["frame_end"] = frames[-1]
        record["sample_count"] = written_counts[target_id]
        record["byte_size"] = path.stat().st_size
        record["status"] = "COMPLETE" if _record_complete(record, start, end) else "RECORDING"
        modifier = ensure_pc2_modifier(obj, target_id, path, start)
        modifier.show_viewport = False
        modifier.show_render = False

    complete = bool(records) and all(
        isinstance(record, dict) and record.get("status") == "COMPLETE"
        for record in records.values()
    )
    manifest["status"] = "COMPLETE" if complete else "RECORDING"
    manifest["last_recorded_frame"] = frame
    _write_pc2_manifest(root, prefix, manifest)
    for target_id, record in records.items():
        obj = _object_for_target(str(target_id), record)
        if obj is not None:
            set_pc2_playback_enabled(
                obj,
                str(target_id),
                bool(use_cache_after_bake and complete),
            )
    _last_status = (
        f"PC2 完成：{len(samples)} 个 Mesh"
        if complete
        else f"PC2 已写第 {frame} 帧：{len(samples)} 个 Mesh"
    )
    return len(samples), _last_status


def set_session_cache_playback(
    world: object,
    cache_directory: str,
    prefix: str,
    enabled: bool,
) -> tuple[int, str]:
    root = resolve_cache_root(cache_directory)
    prefix = safe_prefix(prefix)
    manifest = read_manifest(root, prefix)
    objects = objects_from_manifest(manifest)
    for obj in current_mesh_targets(world):
        target_id = str(obj.get(TARGET_UUID_KEY, "") or "")
        if target_id:
            objects[target_id] = obj
    if bool(enabled):
        if not manifest or manifest.get("backend") != "PC2" or manifest.get("status") != "COMPLETE":
            return 0, "PC2 尚未完成，保持实时模式"
        prepared = []
        for target_id, record in (manifest.get("targets") or {}).items():
            obj = objects.get(str(target_id))
            path = _owned_path(root, str(record.get("file") or ""))
            if (
                obj is None
                or path is None
                or not path.is_file()
                or record.get("status") != "COMPLETE"
            ):
                for other_id, other_obj in objects.items():
                    set_pc2_playback_enabled(other_obj, other_id, False)
                return 0, "PC2 目标或文件缺失，保持实时模式"
            header = read_pc2_header(path)
            expected_count = int(manifest["frame_end"]) - int(manifest["frame_start"]) + 1
            if (
                header.vertex_count != int(record.get("vertex_count", -1))
                or header.sample_count != expected_count
                or abs(header.start_frame - float(manifest["frame_start"])) > 1.0e-6
                or header.sample_rate != 1.0
            ):
                for other_id, other_obj in objects.items():
                    set_pc2_playback_enabled(other_obj, other_id, False)
                return 0, "PC2 header 校验失败，保持实时模式"
            prepared.append((str(target_id), obj, path))
        for target_id, obj, path in prepared:
            ensure_pc2_modifier(obj, target_id, path, int(manifest["frame_start"]))
        enabled_count = 0
        for target_id, obj, _path in prepared:
            enabled_count += int(set_pc2_playback_enabled(obj, str(target_id), True))
        return enabled_count, f"正在使用 {enabled_count} 个 PC2 Mesh 缓存"

    disabled = 0
    for target_id, obj in objects.items():
        disabled += int(set_pc2_playback_enabled(obj, str(target_id), False))
    return disabled, f"实时模式；保留 {disabled} 个 PC2 Mesh 缓存"


def geometry_bake_status() -> str:
    return _last_status


def geometry_bake_is_active() -> bool:
    return False


def geometry_bake_should_record_actions() -> bool:
    return True


def geometry_bake_target_count() -> int:
    return 0


def cancel_pending_geometry_bake() -> bool:
    return False


def rearm_geometry_bake_trigger() -> None:
    return None


def run_pending_geometry_bake() -> bool:
    return False


def shutdown_geometry_bake_runtime() -> None:
    global _last_status
    _last_status = "PC2 尚未记录"


def reset_geometry_bake_runtime_for_tests() -> None:
    shutdown_geometry_bake_runtime()


__all__ = [
    "PC2_HEADER",
    "PC2_MODIFIER_NAME",
    "cancel_pending_geometry_bake",
    "current_mesh_targets",
    "ensure_pc2_modifier",
    "geometry_bake_is_active",
    "geometry_bake_should_record_actions",
    "geometry_bake_status",
    "geometry_bake_target_count",
    "objects_from_manifest",
    "read_pc2_header",
    "rearm_geometry_bake_trigger",
    "remove_pc2_modifier",
    "request_geometry_bake",
    "reset_geometry_bake_runtime_for_tests",
    "resolve_cache_root",
    "run_pending_geometry_bake",
    "set_pc2_playback_enabled",
    "set_session_cache_playback",
    "shutdown_geometry_bake_runtime",
    "truncate_pc2",
    "write_pc2_sample",
]
