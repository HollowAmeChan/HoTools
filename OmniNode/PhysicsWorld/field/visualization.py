"""Field 的冻结 viewport 可视化批次与 Blender handler 生命周期。"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent
import mathutils
import numpy as np

from ..utils.debug_draw import (
    add_arrow_lines,
    add_box_lines,
    add_sphere_lines,
    draw_line_batches,
)
from ..world_time import scene_timeline_time_seconds
from .implicit_objects import stage_field_sources_v0
from .names import VOLUME_SHAPE_BOX, VOLUME_SHAPE_SPHERE
from .sampling import sample_air_velocity_v0
from .specs import build_field_snapshot_v0


_BOUND_COLOR = (0.12, 0.72, 0.92, 0.9)
_FALLOFF_COLOR = (0.18, 0.55, 0.72, 0.45)
_VECTOR_COLOR = (0.95, 0.62, 0.12, 0.95)
_DRAW_HANDLER = None
_DRAW_STORE: dict[int, dict] = {}
_DIRTY = True
_REFRESHING = False


def _scene_key(scene) -> int:
    try:
        return int(scene.as_pointer())
    except Exception:
        return id(scene)


def _tag_view3d_redraw() -> None:
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in tuple(getattr(window_manager, "windows", ()) or ()):
        screen = getattr(window, "screen", None)
        for area in tuple(getattr(screen, "areas", ()) or ()):
            if area.type == "VIEW_3D":
                area.tag_redraw()


def mark_field_visualization_dirty() -> None:
    global _DIRTY
    _DIRTY = True
    _tag_view3d_redraw()


def _timeline_preview_time_seconds(scene) -> float:
    """仅用于无 World consumer 的确定性创作预览，不冒充 solver 时间。"""
    return scene_timeline_time_seconds(scene)


def _world_lattice(spec, density: int) -> np.ndarray:
    coordinates = np.linspace(-0.8, 0.8, max(2, int(density)), dtype=np.float64)
    local = np.asarray(
        [
            (x, y, z)
            for x in coordinates
            for y in coordinates
            for z in coordinates
            if spec.volume.shape == VOLUME_SHAPE_BOX
            or x * x + y * y + z * z <= 0.8 * 0.8 + 1.0e-12
        ],
        dtype=np.float64,
    )
    if local.size == 0:
        return np.empty((0, 3), dtype=np.float64)
    homogeneous = np.empty((local.shape[0], 4), dtype=np.float64)
    homogeneous[:, :3] = local
    homogeneous[:, 3] = 1.0
    matrix = np.asarray(spec.volume.world_transform, dtype=np.float64)
    return np.ascontiguousarray((homogeneous @ matrix.T)[:, :3])


def _dedupe_positions(values) -> np.ndarray:
    ordered = []
    seen = set()
    for value in values:
        key = tuple(round(float(component), 8) for component in value)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(tuple(float(component) for component in value))
    if not ordered:
        return np.empty((0, 3), dtype=np.float64)
    return np.asarray(ordered, dtype=np.float64)


def build_field_visualization_batches_v0(
    snapshot,
    *,
    density: int = 3,
    glyph_scale: float = 0.15,
    selected_field_ids=None,
    show_bounds: bool = True,
) -> tuple[tuple, ...]:
    """通过公共 sampler 构造只含纯 tuple 坐标的冻结绘制批次。"""
    selected = (
        None
        if selected_field_ids is None
        else {str(value) for value in selected_field_ids}
    )
    visible_specs = tuple(
        spec
        for spec in snapshot.fields
        if selected is None or spec.field_id in selected
    )
    bound_lines = []
    falloff_lines = []
    positions = []

    for spec in visible_specs:
        matrix = mathutils.Matrix(spec.volume.world_transform)
        center = matrix.translation
        axis_x = mathutils.Vector(matrix.col[0][:3])
        axis_y = mathutils.Vector(matrix.col[1][:3])
        axis_z = mathutils.Vector(matrix.col[2][:3])
        if show_bounds and spec.volume.shape == VOLUME_SHAPE_SPHERE:
            radius = float(spec.volume.world_scale[0])
            normalized_axes = tuple(axis.normalized() for axis in (axis_x, axis_y, axis_z))
            add_sphere_lines(bound_lines, center, *normalized_axes, radius)
            add_sphere_lines(falloff_lines, center, *normalized_axes, radius * 0.5)
        elif show_bounds and spec.volume.shape == VOLUME_SHAPE_BOX:
            add_box_lines(bound_lines, center, axis_x, axis_y, axis_z)
        positions.extend(_world_lattice(spec, density))

    sampled_positions = _dedupe_positions(positions)
    vector_lines = []
    if len(sampled_positions):
        batch = sample_air_velocity_v0(
            snapshot,
            sampled_positions,
            include_preview=True,
            selected_field_ids=None if selected is None else tuple(sorted(selected)),
        )
        scale = max(float(glyph_scale), 0.0)
        for position, value in zip(sampled_positions, batch.values_world_f32):
            end = position + np.asarray(value, dtype=np.float64) * scale
            add_arrow_lines(vector_lines, position, end)

    return (
        (tuple(bound_lines), _BOUND_COLOR, 1.5),
        (tuple(falloff_lines), _FALLOFF_COLOR, 1.0),
        (tuple(vector_lines), _VECTOR_COLOR, 1.5),
    )


def _active_field_id(scene) -> str:
    try:
        obj = bpy.context.view_layer.objects.active
        if obj is None or scene.objects.get(obj.name_full) != obj:
            return ""
        props = getattr(obj, "hotools_field", None)
        if props is None or not bool(props.enabled):
            return ""
        return str(props.field_id or "").strip().lower()
    except Exception:
        return ""


def refresh_field_visualization(scene=None, depsgraph=None) -> dict:
    """在 draw callback 之外解析 Scene，并原子替换冻结绘制批次。"""
    global _DIRTY, _REFRESHING
    if _REFRESHING:
        return {}
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return {}
    key = _scene_key(scene)
    if not bool(getattr(scene, "ho_field_overlay_show", False)):
        _DRAW_STORE.pop(key, None)
        _DIRTY = False
        return {}

    _REFRESHING = True
    try:
        stage = stage_field_sources_v0(tuple(scene.objects), depsgraph=depsgraph)
        sample_time = _timeline_preview_time_seconds(scene)
        snapshot = build_field_snapshot_v0(
            stage.specs,
            generation=0,
            frame=int(scene.frame_current),
            sample_time_seconds=sample_time,
            diagnostics=stage.diagnostics,
        )
        mode = str(getattr(scene, "ho_field_overlay_mode", "SELECTED") or "SELECTED")
        active_id = _active_field_id(scene)
        selected_ids = (active_id,) if mode == "SELECTED" and active_id else ()
        batches = build_field_visualization_batches_v0(
            snapshot,
            density=int(getattr(scene, "ho_field_overlay_density", 3) or 3),
            glyph_scale=float(getattr(scene, "ho_field_overlay_glyph_scale", 0.15) or 0.0),
            selected_field_ids=selected_ids if mode == "SELECTED" else None,
            show_bounds=bool(getattr(scene, "ho_field_overlay_show_bounds", True)),
        )
        frozen = {
            "batches": batches,
            "snapshot_signature": snapshot.signature,
            "sample_time_seconds": sample_time,
            "time_source": "TIMELINE_PREVIEW",
            "field_ids": tuple(spec.field_id for spec in snapshot.fields),
            "diagnostics": tuple(item.debug_dict() for item in snapshot.diagnostics),
        }
        _DRAW_STORE[key] = frozen
        _DIRTY = False
        return dict(frozen)
    except Exception as exc:
        _DRAW_STORE[key] = {
            "batches": (),
            "time_source": "TIMELINE_PREVIEW",
            "error": str(exc),
        }
        _DIRTY = False
        return dict(_DRAW_STORE[key])
    finally:
        _REFRESHING = False
        _tag_view3d_redraw()


def field_visualization_snapshot(scene=None) -> dict:
    scene = scene or getattr(bpy.context, "scene", None)
    return dict(_DRAW_STORE.get(_scene_key(scene), {})) if scene is not None else {}


def _draw_field_visualization() -> None:
    scene = getattr(bpy.context, "scene", None)
    if scene is None or not bool(getattr(scene, "ho_field_overlay_show", False)):
        return
    frozen = _DRAW_STORE.get(_scene_key(scene), {})
    draw_line_batches(frozen.get("batches", ()))


def _ensure_draw_handler() -> None:
    global _DRAW_HANDLER
    if _DRAW_HANDLER is None:
        _DRAW_HANDLER = bpy.types.SpaceView3D.draw_handler_add(
            _draw_field_visualization,
            (),
            "WINDOW",
            "POST_VIEW",
        )


def _remove_draw_handler() -> None:
    global _DRAW_HANDLER
    if _DRAW_HANDLER is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLER, "WINDOW")
        except Exception:
            pass
    _DRAW_HANDLER = None


def _sync_draw_handler() -> None:
    if any(bool(getattr(scene, "ho_field_overlay_show", False)) for scene in bpy.data.scenes):
        _ensure_draw_handler()
    else:
        _remove_draw_handler()


def field_overlay_update(_owner=None, context=None) -> None:
    mark_field_visualization_dirty()
    _sync_draw_handler()
    scene = getattr(context, "scene", None) if context is not None else None
    if scene is not None:
        try:
            depsgraph = context.evaluated_depsgraph_get()
        except Exception:
            depsgraph = None
        refresh_field_visualization(scene, depsgraph)


@persistent
def _field_depsgraph_update(scene, depsgraph) -> None:
    if bool(getattr(scene, "ho_field_overlay_show", False)):
        mark_field_visualization_dirty()
        refresh_field_visualization(scene, depsgraph)


@persistent
def _field_frame_change(scene, depsgraph=None) -> None:
    if bool(getattr(scene, "ho_field_overlay_show", False)):
        mark_field_visualization_dirty()
        refresh_field_visualization(scene, depsgraph)


@persistent
def _field_file_state_change(_dummy=None) -> None:
    _DRAW_STORE.clear()
    mark_field_visualization_dirty()
    _sync_draw_handler()
    for scene in tuple(bpy.data.scenes):
        if bool(getattr(scene, "ho_field_overlay_show", False)):
            refresh_field_visualization(scene)


_HANDLERS = (
    (bpy.app.handlers.depsgraph_update_post, _field_depsgraph_update),
    (bpy.app.handlers.frame_change_post, _field_frame_change),
    (bpy.app.handlers.load_post, _field_file_state_change),
    (bpy.app.handlers.undo_post, _field_file_state_change),
    (bpy.app.handlers.redo_post, _field_file_state_change),
)


def register() -> None:
    for handlers, callback in _HANDLERS:
        if callback not in handlers:
            handlers.append(callback)
    _sync_draw_handler()
    for scene in tuple(bpy.data.scenes):
        if bool(getattr(scene, "ho_field_overlay_show", False)):
            refresh_field_visualization(scene)


def unregister() -> None:
    for handlers, callback in reversed(_HANDLERS):
        while callback in handlers:
            handlers.remove(callback)
    _DRAW_STORE.clear()
    _remove_draw_handler()


__all__ = [
    "build_field_visualization_batches_v0",
    "field_overlay_update",
    "field_visualization_snapshot",
    "mark_field_visualization_dirty",
    "refresh_field_visualization",
    "register",
    "unregister",
]
