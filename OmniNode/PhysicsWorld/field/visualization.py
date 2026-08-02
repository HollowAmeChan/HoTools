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
    draw_point_batches,
)
from .channels import (
    VISUALIZATION_SDF_ZERO_CROSSING,
    field_channel_descriptor_v0,
    field_channel_reports_v0,
)
from .implicit_objects import stage_field_sources_v0
from .names import (
    AIR_VELOCITY_CHANNEL_ID,
    FIELD_MATRIX_VISUALIZATION_RESERVED,
    FIELD_RESERVED_CHANNEL,
    FIELD_STATUS_ACTIVE,
    VOLUME_SHAPE_BOX,
    VOLUME_SHAPE_SPHERE,
)
from .sampling import sample_air_velocity_v0
from .specs import build_field_snapshot_v0


_BOUND_COLOR = (0.12, 0.72, 0.92, 0.9)
_FALLOFF_COLOR = (0.18, 0.55, 0.72, 0.45)
_VECTOR_COLOR = (0.95, 0.62, 0.12, 0.95)
_DRAW_HANDLER = None
_DRAW_STORE: dict[int, dict] = {}
_DIRTY = True
_REFRESHING = False
_SCALAR_PALETTE = (
    (0.10, 0.28, 0.85, 0.88),
    (0.08, 0.62, 0.92, 0.88),
    (0.05, 0.78, 0.70, 0.88),
    (0.35, 0.82, 0.32, 0.88),
    (0.92, 0.86, 0.18, 0.88),
    (0.98, 0.56, 0.10, 0.88),
    (0.88, 0.20, 0.10, 0.88),
)
_SDF_NEGATIVE_COLOR = (0.12, 0.36, 0.95, 0.9)
_SDF_ZERO_COLOR = (1.0, 0.92, 0.12, 1.0)
_SDF_POSITIVE_COLOR = (0.92, 0.22, 0.12, 0.9)


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


def _author_static_time_seconds(_scene=None) -> float:
    """作者预览是静态注册视图，不跟随时间线或物理世界时间。"""
    return 0.0


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


def build_field_channel_visualization_v0(
    channel_id,
    positions_world,
    values_world=None,
    *,
    glyph_scale: float = 0.15,
    point_size: float = 6.0,
    scalar_range=None,
    sdf_zero_tolerance=None,
) -> dict:
    """为公共 channel 生成显式可视化批次，不为 reserved channel 伪造数值。"""
    descriptor = field_channel_descriptor_v0(channel_id)
    glyph_scale = float(glyph_scale)
    point_size = float(point_size)
    if not np.isfinite(glyph_scale) or glyph_scale < 0.0:
        raise ValueError("glyph_scale 必须是有限非负数")
    if not np.isfinite(point_size) or point_size <= 0.0:
        raise ValueError("point_size 必须是有限正数")
    positions = np.asarray(positions_world, dtype=np.float64)
    if positions.size == 0:
        positions = np.empty((0, 3), dtype=np.float64)
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("可视化位置必须是 [N,3]")
    if not np.all(np.isfinite(positions)):
        raise ValueError("可视化位置不能包含 NaN 或 Inf")

    result = {
        "channel_id": descriptor.channel_id,
        "rank": descriptor.rank,
        "status": descriptor.status,
        "visualization_mode": descriptor.visualization_mode,
        "sample_count": int(len(positions)),
        "line_batches": (),
        "point_batches": (),
        "values_supplied": values_world is not None,
        "diagnostics": (),
    }
    if values_world is None:
        if not descriptor.values_ready:
            result["diagnostics"] = (FIELD_RESERVED_CHANNEL,)
        return result

    values = np.asarray(values_world, dtype=np.float64)
    if descriptor.rank == "vector":
        if values.size == 0:
            values = np.empty((0, 3), dtype=np.float64)
        if values.shape != positions.shape:
            raise ValueError("vector channel 值必须是 [N,3]")
        if not np.all(np.isfinite(values)):
            raise ValueError("vector channel 值不能包含 NaN 或 Inf")
        lines = []
        for position, value in zip(positions, values):
            add_arrow_lines(
                lines,
                position,
                position + value * glyph_scale,
            )
        result["line_batches"] = ((tuple(lines), _VECTOR_COLOR, 1.5),)
        return result

    if descriptor.rank != "scalar":
        result["diagnostics"] = (FIELD_MATRIX_VISUALIZATION_RESERVED,)
        return result
    values = values.reshape(-1)
    if len(values) != len(positions):
        raise ValueError("scalar channel 值必须是 [N]")
    if not np.all(np.isfinite(values)):
        raise ValueError("scalar channel 值不能包含 NaN 或 Inf")

    points = []
    if descriptor.visualization_mode == VISUALIZATION_SDF_ZERO_CROSSING:
        max_abs = float(np.max(np.abs(values))) if len(values) else 0.0
        tolerance = (
            float(sdf_zero_tolerance)
            if sdf_zero_tolerance is not None
            else max(1.0e-6, max_abs * 0.02)
        )
        if not np.isfinite(tolerance) or tolerance < 0.0:
            raise ValueError("sdf_zero_tolerance 必须是有限非负数")
        negative = positions[values < -tolerance]
        zero = positions[np.abs(values) <= tolerance]
        positive = positions[values > tolerance]
        for subset, color in (
            (negative, _SDF_NEGATIVE_COLOR),
            (zero, _SDF_ZERO_COLOR),
            (positive, _SDF_POSITIVE_COLOR),
        ):
            points.append(
                (
                    tuple(tuple(float(v) for v in row) for row in subset),
                    color,
                    point_size,
                )
            )
    else:
        if scalar_range is None:
            low = float(np.min(values)) if len(values) else 0.0
            high = float(np.max(values)) if len(values) else 1.0
        else:
            low, high = (float(item) for item in scalar_range)
        if not np.isfinite(low) or not np.isfinite(high) or high < low:
            raise ValueError("scalar_range 必须是有限的 low<=high")
        if high <= low:
            high = low + 1.0
        normalized = np.clip((values - low) / (high - low), 0.0, 1.0)
        bin_count = len(_SCALAR_PALETTE)
        bin_ids = np.minimum((normalized * bin_count).astype(np.int64), bin_count - 1)
        for index, color in enumerate(_SCALAR_PALETTE):
            subset = positions[bin_ids == index]
            points.append(
                (
                    tuple(tuple(float(v) for v in row) for row in subset),
                    color,
                    point_size,
                )
            )
    result["point_batches"] = tuple(points)
    return result


def _build_field_geometry_v0(
    snapshot,
    *,
    density: int = 3,
    selected_field_ids=None,
    show_bounds: bool = True,
    include_sample_positions: bool = True,
    active_only: bool = False,
) -> tuple[tuple, tuple, np.ndarray, tuple]:
    """构造可冻结的 Volume 几何；不读取 Scene，也不执行任何 sampler。"""
    selected = (
        None
        if selected_field_ids is None
        else {str(value) for value in selected_field_ids}
    )
    visible_specs = tuple(
        spec
        for spec in snapshot.fields
        if selected is None or spec.field_id in selected
        if not active_only or (spec.enabled and spec.status == FIELD_STATUS_ACTIVE)
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
        if include_sample_positions:
            positions.extend(_world_lattice(spec, density))

    sampled_positions = _dedupe_positions(positions)
    return (
        tuple(bound_lines),
        tuple(falloff_lines),
        sampled_positions,
        visible_specs,
    )


def build_field_visualization_batches_v0(
    snapshot,
    *,
    density: int = 3,
    glyph_scale: float = 0.15,
    selected_field_ids=None,
    show_bounds: bool = True,
) -> tuple[tuple, ...]:
    """通过 Python 公共 sampler 构造作者侧静态预览批次。"""
    bound_lines, falloff_lines, sampled_positions, _visible_specs = (
        _build_field_geometry_v0(
            snapshot,
            density=density,
            selected_field_ids=selected_field_ids,
            show_bounds=show_bounds,
            include_sample_positions=True,
            active_only=False,
        )
    )
    selected = (
        None
        if selected_field_ids is None
        else {str(value) for value in selected_field_ids}
    )
    vector_lines = []
    if len(sampled_positions):
        batch = sample_air_velocity_v0(
            snapshot,
            sampled_positions,
            include_preview=True,
            selected_field_ids=None if selected is None else tuple(sorted(selected)),
        )
        channel_batches = build_field_channel_visualization_v0(
            AIR_VELOCITY_CHANNEL_ID,
            sampled_positions,
            batch.values_world_f32,
            glyph_scale=glyph_scale,
        )
        if channel_batches["line_batches"]:
            vector_lines = list(channel_batches["line_batches"][0][0])

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


def _scene_overlay_enabled(scene) -> bool:
    """RNA may be temporarily unreadable during add-on reload or file replacement."""
    if scene is None:
        return False
    try:
        return bool(getattr(scene, "ho_field_overlay_show", False))
    except Exception:
        return False


def _scenes_snapshot() -> tuple:
    try:
        return tuple(bpy.data.scenes)
    except Exception:
        return ()


def refresh_field_visualization(scene=None, depsgraph=None) -> dict:
    """在 draw callback 之外解析 Scene，并原子替换冻结绘制批次。"""
    global _DIRTY, _REFRESHING
    if _REFRESHING:
        return {}
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return {}
    key = _scene_key(scene)
    if not _scene_overlay_enabled(scene):
        _DRAW_STORE.pop(key, None)
        _DIRTY = False
        return {}

    _REFRESHING = True
    try:
        stage = stage_field_sources_v0(tuple(scene.objects), depsgraph=depsgraph)
        sample_time = _author_static_time_seconds(scene)
        snapshot = build_field_snapshot_v0(
            stage.specs,
            generation=0,
            frame=0,
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
            "point_batches": (),
            "snapshot_signature": snapshot.signature,
            "sample_time_seconds": sample_time,
            "time_source": "AUTHOR_STATIC",
            "field_ids": tuple(spec.field_id for spec in snapshot.fields),
            "channel_reports": field_channel_reports_v0(),
            "diagnostics": tuple(item.debug_dict() for item in snapshot.diagnostics),
        }
        _DRAW_STORE[key] = frozen
        _DIRTY = False
        return dict(frozen)
    except Exception as exc:
        _DRAW_STORE[key] = {
            "batches": (),
            "point_batches": (),
            "sample_time_seconds": 0.0,
            "time_source": "AUTHOR_STATIC",
            "channel_reports": field_channel_reports_v0(),
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
    if not _scene_overlay_enabled(scene):
        return
    frozen = _DRAW_STORE.get(_scene_key(scene), {})
    draw_line_batches(frozen.get("batches", ()))
    draw_point_batches(frozen.get("point_batches", ()))


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
    if any(_scene_overlay_enabled(scene) for scene in _scenes_snapshot()):
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
    if _scene_overlay_enabled(scene):
        mark_field_visualization_dirty()
        refresh_field_visualization(scene, depsgraph)


@persistent
def _field_file_state_change(_dummy=None) -> None:
    _DRAW_STORE.clear()
    mark_field_visualization_dirty()
    _sync_draw_handler()
    for scene in _scenes_snapshot():
        if _scene_overlay_enabled(scene):
            refresh_field_visualization(scene)


_HANDLERS = (
    (bpy.app.handlers.depsgraph_update_post, _field_depsgraph_update),
    (bpy.app.handlers.load_post, _field_file_state_change),
    (bpy.app.handlers.undo_post, _field_file_state_change),
    (bpy.app.handlers.redo_post, _field_file_state_change),
)


def register() -> None:
    for handlers, callback in _HANDLERS:
        if callback not in handlers:
            handlers.append(callback)
    _sync_draw_handler()
    for scene in _scenes_snapshot():
        if _scene_overlay_enabled(scene):
            refresh_field_visualization(scene)


def unregister() -> None:
    for handlers, callback in reversed(_HANDLERS):
        while callback in handlers:
            handlers.remove(callback)
    _DRAW_STORE.clear()
    _remove_draw_handler()


__all__ = [
    "build_field_visualization_batches_v0",
    "build_field_channel_visualization_v0",
    "field_overlay_update",
    "field_visualization_snapshot",
    "mark_field_visualization_dirty",
    "refresh_field_visualization",
    "register",
    "unregister",
]
