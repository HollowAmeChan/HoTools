"""Bone XPBD 真实运行端点与约束的按需视口调试。"""

from __future__ import annotations

import bpy
import numpy as np

from ...types import PhysicsWorldCache
from ...utils.debug_draw import add_line, add_point, draw_line_batches, draw_point_batches
from .names import BONE_XPBD_DEBUG_REQUESTERS_KEY, BONE_XPBD_SLOT_KIND


_STORE: dict[str, dict] = {}
_DRAW_HANDLE = None


def _slots(world):
    return tuple(
        slot for slot in world.solver_slots.values()
        if slot.kind == BONE_XPBD_SLOT_KIND
    )


def _request(world, requester_id: str, enabled: bool) -> None:
    for slot in _slots(world):
        requesters = dict(slot.data.get(BONE_XPBD_DEBUG_REQUESTERS_KEY) or {})
        key = str(requester_id)
        if enabled:
            requesters[key] = True
        else:
            requesters.pop(key, None)
        if requesters:
            slot.data[BONE_XPBD_DEBUG_REQUESTERS_KEY] = requesters
        else:
            slot.data.pop(BONE_XPBD_DEBUG_REQUESTERS_KEY, None)
        slot.data["_debug_requested"] = bool(requesters)
        if not requesters:
            slot.data.pop("debug_capture", None)


def _array(capture, name, dtype, width=None):
    shape = (0,) if width is None else (0, width)
    values = capture.get(name)
    if values is None:
        return np.empty(shape, dtype=dtype)
    result = np.asarray(values, dtype=dtype)
    return result.reshape((-1,)) if width is None else result.reshape((-1, width))


def _build(world, *, show_particles, show_segments, show_bend, max_items):
    line_batches = []
    point_batches = []
    status = [
        f"Bone XPBD调试：frame={int(getattr(world.frame_context, 'frame', 0) or 0)}，任务={len(_slots(world))}"
    ]
    for slot in _slots(world):
        capture = slot.data.get("debug_capture")
        summary = slot.data.get("debug_summary") or {}
        name = str(slot.data.get("source_name") or slot.slot_id)
        if not isinstance(capture, dict):
            status.append(f"{name}：等待下一次 XPBD模拟步捕获。")
            continue
        positions = _array(capture, "world_positions", np.float32, 3)
        inverse_masses = _array(capture, "inverse_masses", np.float32)
        endpoints = _array(capture, "endpoint_particles", np.int32, 2)
        bends = _array(capture, "bend_indices", np.int32, 2)
        limit = max(1, min(int(max_items), 100000))
        if show_particles:
            fixed = []
            move = []
            for index, position in enumerate(positions[:limit]):
                add_point(
                    fixed if index < len(inverse_masses) and inverse_masses[index] <= 0.0 else move,
                    position,
                )
            if move:
                point_batches.append((tuple(move), (0.18, 0.92, 0.46, 0.95), 6.0))
            if fixed:
                point_batches.append((tuple(fixed), (1.0, 0.18, 0.12, 1.0), 9.0))
        if show_segments:
            lines = []
            for first, second in endpoints[:limit]:
                if 0 <= first < len(positions) and 0 <= second < len(positions):
                    add_line(lines, positions[first], positions[second])
            if lines:
                line_batches.append((tuple(lines), (0.15, 0.86, 1.0, 0.95), 2.0))
        if show_bend:
            lines = []
            for first, second in bends[:limit]:
                if 0 <= first < len(positions) and 0 <= second < len(positions):
                    add_line(lines, positions[first], positions[second])
            if lines:
                line_batches.append((tuple(lines), (0.82, 0.34, 1.0, 0.78), 1.2))
        fixed_count = int(np.count_nonzero(inverse_masses <= 0.0))
        status.append(
            f"{name}：{summary.get('decision', 'unknown')}，骨={len(endpoints)}，"
            f"粒子={len(positions)}，Fixed={fixed_count}，Tail吸附={'开' if summary.get('tail_follow') else '关'}"
        )
    return line_batches, point_batches, "\n".join(status)


def update_bone_xpbd_debug_draw_store(
    node_uid: str,
    world,
    *,
    show_particles: bool,
    show_segments: bool,
    show_bend: bool,
    max_items: int,
) -> str:
    key = str(node_uid)
    if not isinstance(world, PhysicsWorldCache):
        clear_bone_xpbd_debug_draw_store(node_uid=key)
        return "Bone XPBD调试：物理世界无效。"
    enabled = bool(show_particles or show_segments or show_bend)
    _request(world, key, enabled)
    if not enabled:
        clear_bone_xpbd_debug_draw_store(node_uid=key)
        return "Bone XPBD调试未选择视图。"
    line_batches, point_batches, status = _build(
        world,
        show_particles=show_particles,
        show_segments=show_segments,
        show_bend=show_bend,
        max_items=max_items,
    )
    _STORE[key] = {
        "world_id": str(id(world)),
        "line_batches": line_batches,
        "point_batches": point_batches,
        "status": status,
    }
    _ensure_handler()
    _tag_redraw()
    return status


def clear_bone_xpbd_debug_draw_store(node_uid=None, world_id=None) -> None:
    if node_uid is not None:
        _STORE.pop(str(node_uid), None)
    elif world_id is not None:
        owner = str(world_id)
        for key, item in list(_STORE.items()):
            if str(item.get("world_id")) == owner:
                _STORE.pop(key, None)
    else:
        _STORE.clear()
    if not _STORE:
        _remove_handler()
    _tag_redraw()


def dispose_bone_xpbd_debug_draw_for_world(world, _reason: str = "") -> None:
    clear_bone_xpbd_debug_draw_store(world_id=str(id(world)))


def _draw():
    for item in tuple(_STORE.values()):
        draw_line_batches(item.get("line_batches") or ())
        draw_point_batches(item.get("point_batches") or ())


def _ensure_handler() -> None:
    global _DRAW_HANDLE
    if _DRAW_HANDLE is None:
        try:
            _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
                _draw,
                (),
                "WINDOW",
                "POST_VIEW",
            )
        except Exception:
            _DRAW_HANDLE = None


def _remove_handler() -> None:
    global _DRAW_HANDLE
    if _DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE, "WINDOW")
        except Exception:
            pass
        _DRAW_HANDLE = None


def _tag_redraw() -> None:
    try:
        windows = bpy.context.window_manager.windows
    except Exception:
        windows = ()
    for window in windows:
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()) if screen is not None else ():
            if getattr(area, "type", "") == "VIEW_3D":
                try:
                    area.tag_redraw()
                except Exception:
                    pass


__all__ = [
    "clear_bone_xpbd_debug_draw_store",
    "dispose_bone_xpbd_debug_draw_for_world",
    "update_bone_xpbd_debug_draw_store",
]
