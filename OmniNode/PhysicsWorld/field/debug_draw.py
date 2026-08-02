"""Physics World 场运行态的冻结视口调试绘制。"""

from __future__ import annotations

import math

import bpy
import numpy as np

from ..types import PhysicsWorldCache
from ..utils.debug_draw import draw_line_batches, draw_point_batches
from .names import (
    AIR_VELOCITY_CHANNEL_ID,
    FIELD_NATIVE_RUNTIME_CACHE_KEY_V1,
    FIELD_SNAPSHOT_CACHE_KEY_V0,
    FIELD_STATUS_ACTIVE,
)
from .native import NativeFieldRuntimeV1
from .specs import FieldSnapshotV0
from .visualization import (
    _BOUND_COLOR,
    _FALLOFF_COLOR,
    _build_field_geometry_v0,
    build_field_channel_visualization_v0,
)


_FIELD_RUNTIME_DRAW_STORE: dict[str, dict] = {}
_FIELD_RUNTIME_DRAW_HANDLE = None
_MAX_SAMPLE_POINTS = 10000
_DEBUG_CONSUMER_ID = "physics_world_debug"


def _tag_view3d_redraw() -> None:
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in tuple(getattr(window_manager, "windows", ()) or ()):
        screen = getattr(window, "screen", None)
        for area in tuple(getattr(screen, "areas", ()) or ()):
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _draw_field_runtime_debug() -> None:
    for item in tuple(_FIELD_RUNTIME_DRAW_STORE.values()):
        draw_line_batches(item.get("line_batches", ()))
        draw_point_batches(item.get("point_batches", ()))


def _ensure_draw_handler() -> None:
    global _FIELD_RUNTIME_DRAW_HANDLE
    if _FIELD_RUNTIME_DRAW_HANDLE is not None:
        return
    try:
        _FIELD_RUNTIME_DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
            _draw_field_runtime_debug,
            (),
            "WINDOW",
            "POST_VIEW",
        )
    except Exception:
        _FIELD_RUNTIME_DRAW_HANDLE = None


def _remove_draw_handler() -> None:
    global _FIELD_RUNTIME_DRAW_HANDLE
    if _FIELD_RUNTIME_DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(
                _FIELD_RUNTIME_DRAW_HANDLE,
                "WINDOW",
            )
        except Exception:
            pass
    _FIELD_RUNTIME_DRAW_HANDLE = None


def clear_field_runtime_debug_draw_store(*, world_id: str | None = None) -> None:
    """清理指定 World 或全部冻结批次；store 为空时同步释放 handler。"""
    changed = False
    if world_id is not None:
        changed = _FIELD_RUNTIME_DRAW_STORE.pop(str(world_id), None) is not None
    elif _FIELD_RUNTIME_DRAW_STORE:
        _FIELD_RUNTIME_DRAW_STORE.clear()
        changed = True

    if not _FIELD_RUNTIME_DRAW_STORE:
        _remove_draw_handler()
    if changed:
        _tag_view3d_redraw()


def begin_field_runtime_debug_evaluation(world, _scope) -> None:
    """World Begin 先让旧视图失效；仍在求值的调试节点会立即重新发布。"""
    if isinstance(world, PhysicsWorldCache):
        clear_field_runtime_debug_draw_store(world_id=str(id(world)))


def _runtime_state(world: PhysicsWorldCache):
    """读取并严格校验同一次 World Begin 提交的快照与 native runtime。"""
    frame_context = getattr(world, "frame_context", None)
    if frame_context is None or not bool(getattr(frame_context, "initialized", False)):
        raise RuntimeError("物理世界尚未完成帧开始")

    snapshot = world.runtime_cache(FIELD_SNAPSHOT_CACHE_KEY_V0)
    runtime = world.runtime_cache(FIELD_NATIVE_RUNTIME_CACHE_KEY_V1)
    if not isinstance(snapshot, FieldSnapshotV0):
        raise RuntimeError("物理世界缺少 FieldSnapshotV0")
    if not isinstance(runtime, NativeFieldRuntimeV1) or not runtime.live:
        raise RuntimeError("物理世界缺少可用的 NativeFieldRuntimeV1")

    generation = int(world.generation)
    frame = int(frame_context.frame)
    sample_time = float(frame_context.sample_time_seconds)
    if int(frame_context.generation) != generation:
        raise RuntimeError("World 与 FrameContext generation 不一致")
    if snapshot.generation != generation:
        raise RuntimeError("Field 快照 generation 已过期")
    if snapshot.frame != frame:
        raise RuntimeError("Field 快照 frame 已过期")
    if snapshot.sample_time_seconds != sample_time:
        raise RuntimeError("Field 快照采样时间已过期")
    if runtime.snapshot_signature != snapshot.signature:
        raise RuntimeError("Field native runtime 与快照签名不一致")

    # inspect 是 native runtime 的身份真相；边界快照必须与它逐项一致。
    inspect = runtime.debug_snapshot()
    expected = {
        "generation": generation,
        "frame": frame,
        "sample_time_seconds": sample_time,
        "snapshot_signature": snapshot.signature,
    }
    for name, value in expected.items():
        if inspect.get(name) != value:
            raise RuntimeError(f"Field native inspect 的 {name} 与 World 不一致")
    if not bool(inspect.get("live", False)):
        raise RuntimeError("Field native inspect 报告 runtime 已释放")

    active_specs = tuple(
        spec
        for spec in snapshot.fields
        if spec.enabled and spec.status == FIELD_STATUS_ACTIVE
    )
    active_ids = tuple(spec.field_id for spec in active_specs)
    if int(inspect.get("field_count", -1)) != len(active_specs):
        raise RuntimeError("Field native inspect 的场数量与快照不一致")
    if tuple(inspect.get("field_ids", ())) != active_ids:
        raise RuntimeError("Field native inspect 的场标识与快照不一致")
    return frame_context, snapshot, runtime, inspect


def _finite_glyph_scale(value) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("箭头比例必须是有限数")
    return max(result, 0.0)


def _build_runtime_batches(
    snapshot: FieldSnapshotV0,
    runtime: NativeFieldRuntimeV1,
    *,
    sample_time_seconds: float,
    show_bounds: bool,
    show_air_velocity: bool,
    density: int,
    glyph_scale: float,
) -> tuple[tuple, dict]:
    bound_lines, falloff_lines, positions, _active_specs = _build_field_geometry_v0(
        snapshot,
        density=density,
        show_bounds=show_bounds,
        include_sample_positions=show_air_velocity,
        active_only=True,
    )
    truncated = len(positions) > _MAX_SAMPLE_POINTS
    if truncated:
        positions = np.ascontiguousarray(positions[:_MAX_SAMPLE_POINTS])

    vector_batches = ()
    sample_result = {
        "sample_time_seconds": sample_time_seconds,
        "sampled_field_count": 0,
        "participating_sample_count": 0,
        "scope_blocked_field_ids": (),
    }
    if show_air_velocity and len(positions):
        scoped_ids = tuple(
            spec.field_id
            for spec in snapshot.fields
            if (
                spec.enabled
                and spec.status == FIELD_STATUS_ACTIVE
                and (
                    spec.scope.solver_ids
                    or spec.scope.collection_ids
                    or spec.scope.include_ids
                    or spec.scope.exclude_ids
                    or spec.scope.collision_groups
                )
            )
        )
        if scoped_ids:
            # 该简洁节点没有对象/Collection/碰撞组输入，不能伪造 MC2 partition。
            sample_result["scope_blocked_field_ids"] = scoped_ids
        else:
            native_result = runtime.sample_air_velocity(
                positions,
                sample_time_seconds=sample_time_seconds,
                consumer_id=_DEBUG_CONSUMER_ID,
            )
            participation = np.asarray(native_result["participation"], dtype=np.uint8)
            participating = participation != 0
            values = np.asarray(native_result["air_velocity_world"], dtype=np.float32)
            channel = build_field_channel_visualization_v0(
                AIR_VELOCITY_CHANNEL_ID,
                positions[participating],
                values[participating],
                glyph_scale=glyph_scale,
            )
            vector_batches = tuple(channel.get("line_batches", ()))
            sample_result = {
                "sample_time_seconds": float(native_result["sample_time_seconds"]),
                "sampled_field_count": int(native_result["sampled_field_count"]),
                "participating_sample_count": int(np.count_nonzero(participating)),
                "scope_blocked_field_ids": (),
            }
            if sample_result["sample_time_seconds"] != sample_time_seconds:
                raise RuntimeError("Field native sample 返回了错误的 World 帧时间")

    line_batches = (
        (bound_lines, _BOUND_COLOR, 1.5),
        (falloff_lines, _FALLOFF_COLOR, 1.0),
        *vector_batches,
    )
    metadata = {
        "sample_count": int(len(positions)),
        "sample_truncated": bool(truncated),
        **sample_result,
    }
    return line_batches, metadata


def _status_text(inspect: dict, metadata: dict, *, show_bounds: bool, show_air: bool) -> str:
    sample_part = "空气速度=关"
    if show_air:
        blocked_ids = tuple(metadata.get("scope_blocked_field_ids", ()))
        if blocked_ids:
            sample_part = (
                f"空气速度=未绘制（{len(blocked_ids)}个场含高级过滤，"
                "缺少明确消费上下文）"
            )
        else:
            sample_part = (
                f"空气速度={metadata['participating_sample_count']}/"
                f"{metadata['sample_count']}点，命中场={metadata['sampled_field_count']}"
            )
            if metadata["sample_truncated"]:
                sample_part += "（已截断）"
    scope_note = (
        "；采样上下文=公共无过滤场"
        if show_air and not metadata.get("scope_blocked_field_ids")
        else ""
    )
    return (
        f"场运行态：frame={int(inspect['frame'])}，gen={int(inspect['generation'])}，"
        f"t={float(inspect['sample_time_seconds']):.6g}s（WORLD_FRAME_START），"
        f"native场={int(inspect['field_count'])}，"
        f"Volume边界={'开' if show_bounds else '关'}，{sample_part}{scope_note}"
    )


def update_field_runtime_debug_draw_store(
    world,
    *,
    show_bounds: bool = False,
    show_air_velocity: bool = False,
    density: int = 3,
    glyph_scale: float = 0.15,
) -> str:
    """更新该 World 的单实例冻结批次；两项均关闭时不读取任何 cache。"""
    if not isinstance(world, PhysicsWorldCache):
        return "场运行态调试：物理世界无效。"
    world_key = str(id(world))
    if not bool(show_bounds) and not bool(show_air_velocity):
        clear_field_runtime_debug_draw_store(world_id=world_key)
        return "场运行态调试未选择视图；不会读取缓存、采样或安装绘制处理器。"

    try:
        density_value = max(2, min(int(density), 7))
        glyph_scale_value = _finite_glyph_scale(glyph_scale)
        frame_context, snapshot, runtime, inspect = _runtime_state(world)
        line_batches, metadata = _build_runtime_batches(
            snapshot,
            runtime,
            sample_time_seconds=float(frame_context.sample_time_seconds),
            show_bounds=bool(show_bounds),
            show_air_velocity=bool(show_air_velocity),
            density=density_value,
            glyph_scale=glyph_scale_value,
        )
        status = _status_text(
            inspect,
            metadata,
            show_bounds=bool(show_bounds),
            show_air=bool(show_air_velocity),
        )
    except Exception as exc:
        clear_field_runtime_debug_draw_store(world_id=world_key)
        return f"场运行态调试不可用：{exc}"

    _FIELD_RUNTIME_DRAW_STORE[world_key] = {
        "world_id": world_key,
        "frame": int(frame_context.frame),
        "generation": int(world.generation),
        "snapshot_signature": snapshot.signature,
        "time_source": "WORLD_FRAME_START",
        "sample_time_seconds": float(frame_context.sample_time_seconds),
        "line_batches": tuple(line_batches),
        "point_batches": (),
        "native_inspect": dict(inspect),
        "metadata": dict(metadata),
        "status_text": status,
    }
    _ensure_draw_handler()
    _tag_view3d_redraw()
    return status


def field_runtime_debug_draw_store_snapshot(world_id: str) -> dict | None:
    """返回不含 native handle 所有权的轻量 store 摘要，供验收与诊断。"""
    item = _FIELD_RUNTIME_DRAW_STORE.get(str(world_id))
    if item is None:
        return None
    line_batches = tuple(item.get("line_batches", ()))
    return {
        "world_id": item["world_id"],
        "frame": item["frame"],
        "generation": item["generation"],
        "snapshot_signature": item["snapshot_signature"],
        "time_source": item["time_source"],
        "sample_time_seconds": item["sample_time_seconds"],
        "line_batch_count": len(line_batches),
        "line_vertex_count": sum(len(batch[0]) for batch in line_batches),
        "native_inspect": dict(item.get("native_inspect", {})),
        "metadata": dict(item.get("metadata", {})),
        "status_text": str(item.get("status_text") or ""),
    }


def dispose_field_runtime_debug_draw_for_world(world, _reason: str = "") -> None:
    clear_field_runtime_debug_draw_store(world_id=str(id(world)))


def shutdown_field_runtime_debug_draw() -> None:
    clear_field_runtime_debug_draw_store()
    _remove_draw_handler()


def register() -> None:
    shutdown_field_runtime_debug_draw()


def unregister() -> None:
    shutdown_field_runtime_debug_draw()


__all__ = [
    "begin_field_runtime_debug_evaluation",
    "clear_field_runtime_debug_draw_store",
    "dispose_field_runtime_debug_draw_for_world",
    "field_runtime_debug_draw_store_snapshot",
    "register",
    "shutdown_field_runtime_debug_draw",
    "unregister",
    "update_field_runtime_debug_draw_store",
]
