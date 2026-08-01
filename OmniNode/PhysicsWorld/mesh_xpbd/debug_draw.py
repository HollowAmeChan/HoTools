"""Viewport visualization for frozen Mesh XPBD debug snapshots."""

from __future__ import annotations

import math

import bpy
import mathutils
import numpy as np

from ..types import PhysicsWorldCache
from ..utils.debug_draw import (
    add_arrow_lines,
    add_box_lines,
    add_capsule_lines,
    add_line,
    add_plane_lines,
    add_point,
    add_sphere_lines,
    draw_line_batches,
    draw_point_batches,
    draw_triangle_batches,
    vector3,
)
from .debug import request_mesh_xpbd_debug_capture
from .names import MESH_XPBD_SLOT_KIND


_COLORS = {
    "surface": (0.16, 0.55, 0.92, 0.18),
    "move": (0.20, 0.95, 0.42, 0.92),
    "fixed": (1.00, 0.18, 0.12, 1.00),
    "rest": (0.62, 0.66, 0.72, 0.44),
    "offset": (0.12, 0.90, 1.00, 0.92),
    "stretch_ok": (0.24, 0.88, 0.38, 0.62),
    "stretch_long": (1.00, 0.15, 0.08, 0.96),
    "stretch_short": (0.15, 0.42, 1.00, 0.96),
    "bend_ok": (0.70, 0.36, 1.00, 0.56),
    "bend_long": (1.00, 0.16, 0.66, 0.96),
    "bend_short": (0.48, 0.20, 1.00, 0.96),
    "normal": (1.00, 0.78, 0.12, 0.84),
    "gravity": (0.58, 1.00, 0.18, 0.96),
    "radius": (0.12, 0.90, 0.72, 0.42),
    "collider": (0.06, 0.58, 1.00, 0.76),
    "contact": (1.00, 0.80, 0.08, 1.00),
    "penetration": (1.00, 0.08, 0.04, 1.00),
}

_VIEW_KEYS = (
    "show_particles",
    "show_surface",
    "show_stretch",
    "show_bend",
    "show_offsets",
    "show_normals",
    "show_gravity",
    "show_radii",
    "show_colliders",
    "show_contacts",
)

_XPBD_DRAW_STORE: dict[str, dict] = {}
_XPBD_DRAW_HANDLE = None
_EPSILON = 1.0e-7


def _task_tokens(value) -> tuple[str, ...]:
    text = str(value or "").replace("\n", ",")
    return tuple(token.strip().lower() for token in text.split(",") if token.strip())


def _matching_slots(world: PhysicsWorldCache, filters: dict):
    tokens = filters["task_filter"]
    for slot in world.solver_slots.values():
        if slot.kind != MESH_XPBD_SLOT_KIND:
            continue
        source_name = str(slot.data.get("source_name") or "")
        identity = f"{source_name}\n{slot.slot_id}".lower()
        if tokens and not any(token in identity for token in tokens):
            continue
        yield slot


def _capture_array(capture: dict, name: str, dtype, width: int | None = None):
    values = capture.get(name)
    if values is None:
        shape = (0,) if width is None else (0, width)
        return np.empty(shape, dtype=dtype)
    array = np.asarray(values, dtype=dtype)
    return array.reshape((-1,)) if width is None else array.reshape((-1, width))


def _line_batch(batches, lines, color_name: str, width: float = 1.0):
    if lines:
        batches.append((tuple(lines), _COLORS[color_name], float(width)))


def _point_batch(batches, points, color_name: str, size: float):
    if points:
        batches.append((tuple(points), _COLORS[color_name], float(size)))


def _triangle_batch(batches, positions, triangles, limit: int):
    vertices = []
    indices = []
    for triangle in triangles[:limit]:
        if not all(0 <= int(index) < len(positions) for index in triangle):
            continue
        start = len(vertices)
        vertices.extend(tuple(float(value) for value in positions[int(index)]) for index in triangle)
        indices.append((start, start + 1, start + 2))
    if vertices:
        batches.append((tuple(vertices), tuple(indices), _COLORS["surface"]))


def _constraint_lines(positions, rest_positions, pairs, tolerance, limit):
    compressed = []
    normal = []
    stretched = []
    errors = []
    for pair in pairs[:limit]:
        first, second = (int(pair[0]), int(pair[1]))
        if min(first, second) < 0 or max(first, second) >= len(positions):
            continue
        rest_length = float(np.linalg.norm(rest_positions[second] - rest_positions[first]))
        if rest_length <= _EPSILON:
            continue
        current_length = float(np.linalg.norm(positions[second] - positions[first]))
        error = (current_length - rest_length) / rest_length
        errors.append(error)
        target = stretched if error > tolerance else compressed if error < -tolerance else normal
        add_line(target, positions[first], positions[second])
    return compressed, normal, stretched, errors


def _plane_axes(normal, scale: float):
    normal = vector3(normal)
    if normal.length <= _EPSILON:
        normal = mathutils.Vector((0.0, 0.0, 1.0))
    else:
        normal.normalize()
    reference = mathutils.Vector((0.0, 0.0, 1.0))
    if abs(normal.dot(reference)) > 0.9:
        reference = mathutils.Vector((1.0, 0.0, 0.0))
    axis_x = reference.cross(normal).normalized() * scale
    axis_y = normal.cross(axis_x).normalized() * scale
    return normal, axis_x, axis_y


def _box_axes(axis_x, axis_y, signed_half_z):
    x = vector3(axis_x)
    y = vector3(axis_y)
    cross = x.cross(y)
    if cross.length <= _EPSILON:
        return None
    z = cross.normalized() * float(signed_half_z)
    return x, y, z


def _append_collider_lines(lines, capture, limit: int, plane_scale: float):
    types = _capture_array(capture, "collider_types", np.int32)
    centers = _capture_array(capture, "collider_centers", np.float32, 3)
    segments_a = _capture_array(capture, "collider_segment_a", np.float32, 3)
    segments_b = _capture_array(capture, "collider_segment_b", np.float32, 3)
    radii = _capture_array(capture, "collider_radii", np.float32)
    count = min(len(types), len(centers), len(segments_a), len(segments_b), len(radii), limit)
    for index in range(count):
        collider_type = int(types[index])
        if collider_type == 0:
            add_sphere_lines(
                lines,
                centers[index],
                (1, 0, 0),
                (0, 1, 0),
                (0, 0, 1),
                max(float(radii[index]), 0.0),
            )
        elif collider_type == 1:
            add_capsule_lines(
                lines,
                segments_a[index],
                segments_b[index],
                max(float(radii[index]), 0.0),
            )
        elif collider_type == 2:
            normal, axis_x, axis_y = _plane_axes(segments_a[index], plane_scale)
            add_plane_lines(lines, centers[index], axis_x, axis_y, normal)
        elif collider_type == 3:
            axes = _box_axes(segments_a[index], segments_b[index], radii[index])
            if axes is not None:
                add_box_lines(lines, centers[index], *axes)


def _sphere_contact(position, particle_radius, center, collider_radius):
    delta = position - center
    distance = float(np.linalg.norm(delta))
    radius = max(float(particle_radius), 0.0) + max(float(collider_radius), 0.0)
    normal = delta / distance if distance > _EPSILON else np.asarray((0.0, 0.0, 1.0))
    return distance - radius, center + normal * max(float(collider_radius), 0.0), normal


def _capsule_contact(position, particle_radius, start, end, collider_radius):
    segment = end - start
    length_squared = float(np.dot(segment, segment))
    ratio = 0.0 if length_squared <= _EPSILON else float(
        np.clip(np.dot(position - start, segment) / length_squared, 0.0, 1.0)
    )
    return _sphere_contact(
        position,
        particle_radius,
        start + segment * ratio,
        collider_radius,
    )


def _plane_contact(position, particle_radius, center, normal):
    length = float(np.linalg.norm(normal))
    if length <= _EPSILON:
        return None
    normal = normal / length
    signed_distance = float(np.dot(position - center, normal))
    return signed_distance - max(float(particle_radius), 0.0), position - normal * signed_distance, normal


def _box_contact(position, particle_radius, center, axis_x, axis_y, signed_half_z):
    axes = _box_axes(axis_x, axis_y, signed_half_z)
    if axes is None:
        return None
    half_extents = np.asarray([vector3(axis).length for axis in axes], dtype=np.float64)
    if np.any(half_extents <= _EPSILON):
        return None
    unit_axes = np.asarray([tuple(vector3(axis).normalized()) for axis in axes], dtype=np.float64)
    local = unit_axes @ (position - center)
    clamped = np.clip(local, -half_extents, half_extents)
    closest = center + clamped @ unit_axes
    outside = position - closest
    outside_distance = float(np.linalg.norm(outside))
    particle_radius = max(float(particle_radius), 0.0)
    if outside_distance > _EPSILON:
        return outside_distance - particle_radius, closest, outside / outside_distance
    face_distances = half_extents - np.abs(local)
    axis_index = int(np.argmin(face_distances))
    sign = 1.0 if local[axis_index] >= 0.0 else -1.0
    normal = unit_axes[axis_index] * sign
    surface = position + normal * float(face_distances[axis_index])
    return -float(face_distances[axis_index]) - particle_radius, surface, normal


def _particle_contact(position, particle_radius, colliders, collider_index):
    types, centers, segments_a, segments_b, radii = colliders
    collider_type = int(types[collider_index])
    if collider_type == 0:
        return _sphere_contact(position, particle_radius, centers[collider_index], radii[collider_index])
    if collider_type == 1:
        return _capsule_contact(
            position,
            particle_radius,
            segments_a[collider_index],
            segments_b[collider_index],
            radii[collider_index],
        )
    if collider_type == 2:
        return _plane_contact(position, particle_radius, centers[collider_index], segments_a[collider_index])
    if collider_type == 3:
        return _box_contact(
            position,
            particle_radius,
            centers[collider_index],
            segments_a[collider_index],
            segments_b[collider_index],
            radii[collider_index],
        )
    return None


def _contact_records(positions, radii, capture, margin: float, limit: int):
    colliders = (
        _capture_array(capture, "collider_types", np.int32),
        _capture_array(capture, "collider_centers", np.float32, 3),
        _capture_array(capture, "collider_segment_a", np.float32, 3),
        _capture_array(capture, "collider_segment_b", np.float32, 3),
        _capture_array(capture, "collider_radii", np.float32),
    )
    collider_count = min(len(values) for values in colliders)
    records = []
    for particle_index, position in enumerate(positions[:limit]):
        particle_radius = float(radii[particle_index]) if particle_index < len(radii) else 0.0
        best = None
        for collider_index in range(collider_count):
            record = _particle_contact(position, particle_radius, colliders, collider_index)
            if record is None or record[0] > margin:
                continue
            if best is None or record[0] < best[0]:
                best = record
        if best is not None:
            records.append((particle_index, *best))
    return records


def _append_slot_batches(line_batches, point_batches, triangle_batches, slot, filters):
    capture = slot.data.get("debug_capture")
    if not isinstance(capture, dict):
        return
    positions = _capture_array(capture, "world_positions", np.float32, 3)
    rest = _capture_array(capture, "rest_world_positions", np.float32, 3)
    count = min(len(positions), len(rest))
    positions = positions[:count]
    rest = rest[:count]
    inverse_masses = _capture_array(capture, "inverse_masses", np.float32)[:count]
    radii = _capture_array(capture, "world_collision_radii", np.float32)[:count]
    limit = filters["max_items"]

    if filters["show_particles"]:
        fixed = []
        move = []
        for index, position in enumerate(positions[:limit]):
            add_point(fixed if index < len(inverse_masses) and inverse_masses[index] <= 0.0 else move, position)
        _point_batch(point_batches, move, "move", 5.0)
        _point_batch(point_batches, fixed, "fixed", 7.0)

    triangles = _capture_array(capture, "loop_triangles", np.int32, 3)
    if filters["show_surface"]:
        _triangle_batch(triangle_batches, positions, triangles, limit)

    tolerance = filters["constraint_tolerance"]
    if filters["show_stretch"]:
        pairs = _capture_array(capture, "stretch_indices", np.int32, 2)
        short, normal, long, _ = _constraint_lines(positions, rest, pairs, tolerance, limit)
        _line_batch(line_batches, normal, "stretch_ok", 1.0)
        _line_batch(line_batches, short, "stretch_short", 1.8)
        _line_batch(line_batches, long, "stretch_long", 1.8)

    if filters["show_bend"]:
        pairs = _capture_array(capture, "bend_indices", np.int32, 2)
        short, normal, long, _ = _constraint_lines(positions, rest, pairs, tolerance, limit)
        _line_batch(line_batches, normal, "bend_ok", 1.0)
        _line_batch(line_batches, short, "bend_short", 2.0)
        _line_batch(line_batches, long, "bend_long", 2.0)

    if filters["show_offsets"]:
        rest_points = []
        offset_lines = []
        for start, end in zip(rest[:limit], positions[:limit]):
            add_point(rest_points, start)
            delta = end - start
            if float(np.linalg.norm(delta)) > _EPSILON:
                add_arrow_lines(offset_lines, start, start + delta * filters["vector_scale"])
        _point_batch(point_batches, rest_points, "rest", 3.0)
        _line_batch(line_batches, offset_lines, "offset", 1.2)

    if filters["show_normals"]:
        normal_lines = []
        for triangle in triangles[:limit]:
            indices = [int(value) for value in triangle]
            if min(indices) < 0 or max(indices) >= len(positions):
                continue
            a, b, c = (positions[index] for index in indices)
            normal = np.cross(b - a, c - a)
            length = float(np.linalg.norm(normal))
            if length <= _EPSILON:
                continue
            center = (a + b + c) / 3.0
            add_arrow_lines(normal_lines, center, center + normal / length * filters["normal_scale"])
        _line_batch(line_batches, normal_lines, "normal", 1.0)

    if filters["show_gravity"] and len(positions):
        task = capture.get("task") or {}
        direction = np.asarray(task.get("gravity_direction", (0.0, 0.0, -1.0)), dtype=np.float32)
        length = float(np.linalg.norm(direction))
        power = max(float(task.get("gravity_power", 0.0) or 0.0), 0.0)
        if length > _EPSILON and power > 0.0:
            center = np.mean(positions, axis=0)
            gravity_lines = []
            add_arrow_lines(
                gravity_lines,
                center,
                center
                + direction / length
                * math.log1p(power)
                * 0.15
                * filters["vector_scale"],
            )
            _line_batch(line_batches, gravity_lines, "gravity", 1.6)

    if filters["show_radii"]:
        radius_lines = []
        for index, position in enumerate(positions[:limit]):
            radius = float(radii[index]) if index < len(radii) else 0.0
            if radius > _EPSILON:
                add_sphere_lines(radius_lines, position, (1, 0, 0), (0, 1, 0), (0, 0, 1), radius)
        _line_batch(line_batches, radius_lines, "radius", 1.0)

    if filters["show_colliders"]:
        collider_lines = []
        _append_collider_lines(collider_lines, capture, limit, filters["plane_scale"])
        _line_batch(line_batches, collider_lines, "collider", 1.4)

    if filters["show_contacts"]:
        contacts = []
        penetrations = []
        contact_points = []
        for particle_index, gap, surface, normal in _contact_records(
            positions, radii, capture, filters["contact_margin"], limit
        ):
            position = positions[particle_index]
            add_point(contact_points, surface)
            if gap < 0.0:
                add_arrow_lines(
                    penetrations,
                    position,
                    position + normal * (-gap) * filters["vector_scale"],
                )
            else:
                add_line(contacts, position, surface)
        _point_batch(point_batches, contact_points, "contact", 6.0)
        _line_batch(line_batches, contacts, "contact", 1.2)
        _line_batch(line_batches, penetrations, "penetration", 2.2)


def _constraint_error(capture, key: str):
    positions = _capture_array(capture, "world_positions", np.float32, 3)
    rest = _capture_array(capture, "rest_world_positions", np.float32, 3)
    pairs = _capture_array(capture, key, np.int32, 2)
    _, _, _, errors = _constraint_lines(positions, rest, pairs, 0.0, len(pairs))
    return max((abs(value) for value in errors), default=0.0)


def _build_status(world: PhysicsWorldCache, filters: dict) -> str:
    slots = list(_matching_slots(world, filters))
    lines = [
        f"XPBD调试：frame={int(getattr(world.frame_context, 'frame', 0) or 0)}，任务={len(slots)}"
    ]
    if not slots:
        lines.append("没有匹配的 XPBD 任务；先执行 XPBD 模拟步。")
        return "\n".join(lines)
    for slot in slots:
        capture = slot.data.get("debug_capture")
        summary = slot.data.get("debug_summary") or {}
        if not isinstance(capture, dict):
            lines.append(f"{slot.data.get('source_name') or slot.slot_id}：等待下一次 solver 捕获。")
            continue
        positions = _capture_array(capture, "world_positions", np.float32, 3)
        rest = _capture_array(capture, "rest_world_positions", np.float32, 3)
        inverse_masses = _capture_array(capture, "inverse_masses", np.float32)
        offset_count = min(len(positions), len(rest))
        offsets = positions[:offset_count] - rest[:offset_count]
        max_offset = float(np.max(np.linalg.norm(offsets, axis=1))) if offset_count else 0.0
        fixed_count = int(np.count_nonzero(inverse_masses <= 0.0))
        lines.append(
            f"{slot.data.get('source_name') or slot.slot_id}：{summary.get('decision', 'unknown')}，"
            f"粒子={len(positions)}，Pin={fixed_count}，碰撞体={len(_capture_array(capture, 'collider_types', np.int32))}，"
            f"最大偏移={max_offset:.6g}，Stretch误差={_constraint_error(capture, 'stretch_indices'):.3%}，"
            f"Bend误差={_constraint_error(capture, 'bend_indices'):.3%}"
        )
    return "\n".join(lines)


def _build_batches(world: PhysicsWorldCache, filters: dict):
    line_batches = []
    point_batches = []
    triangle_batches = []
    for slot in _matching_slots(world, filters):
        _append_slot_batches(
            line_batches,
            point_batches,
            triangle_batches,
            slot,
            filters,
        )
    return line_batches, point_batches, triangle_batches


def update_mesh_xpbd_debug_draw_store(
    node_uid: str,
    world,
    enabled: bool,
    **options,
) -> str:
    node_key = str(node_uid)
    if not enabled or not isinstance(world, PhysicsWorldCache):
        if isinstance(world, PhysicsWorldCache):
            request_mesh_xpbd_debug_capture(world, enabled=False)
        clear_mesh_xpbd_debug_draw_store(node_uid=node_key)
        return "XPBD调试未启用或物理世界无效。"

    filters = {
        name: bool(options.get(name, False))
        for name in _VIEW_KEYS
    }
    filters.update({
        "task_filter": _task_tokens(options.get("task_filter", "")),
        "max_items": max(1, min(int(options.get("max_items", 10000)), 100000)),
        "constraint_tolerance": max(float(options.get("constraint_tolerance", 0.01)), 0.0),
        "contact_margin": max(float(options.get("contact_margin", 0.002)), 0.0),
        "vector_scale": max(float(options.get("vector_scale", 1.0)), 0.0),
        "normal_scale": max(float(options.get("normal_scale", 0.05)), 0.0),
        "plane_scale": max(float(options.get("plane_scale", 1.0)), 0.001),
    })
    if not any(filters[name] for name in _VIEW_KEYS):
        request_mesh_xpbd_debug_capture(world, enabled=False)
        clear_mesh_xpbd_debug_draw_store(node_uid=node_key)
        return "XPBD调试未选择视图；不会请求快照或安装绘制处理器。"

    request_mesh_xpbd_debug_capture(world, enabled=True, filters=filters)
    line_batches, point_batches, triangle_batches = _build_batches(world, filters)
    status = _build_status(world, filters)
    _XPBD_DRAW_STORE[node_key] = {
        "world_id": str(id(world)),
        "frame": int(getattr(world.frame_context, "frame", 0) or 0),
        "line_batches": line_batches,
        "point_batches": point_batches,
        "triangle_batches": triangle_batches,
        "status_text": status,
    }
    _ensure_draw_handler()
    _tag_view3d_redraw()
    return status


def clear_mesh_xpbd_debug_draw_store(
    node_uid: str | None = None,
    world_id: str | None = None,
) -> None:
    if node_uid is not None:
        _XPBD_DRAW_STORE.pop(str(node_uid), None)
    elif world_id is not None:
        owner = str(world_id)
        for key, value in list(_XPBD_DRAW_STORE.items()):
            if str(value.get("world_id")) == owner:
                _XPBD_DRAW_STORE.pop(key, None)
    else:
        _XPBD_DRAW_STORE.clear()
    if not _XPBD_DRAW_STORE:
        _remove_draw_handler()
    _tag_view3d_redraw()


def dispose_mesh_xpbd_debug_draw_for_world(world, _reason: str = "") -> None:
    clear_mesh_xpbd_debug_draw_store(world_id=str(id(world)))


def mesh_xpbd_debug_draw_store_snapshot(node_uid: str) -> dict | None:
    item = _XPBD_DRAW_STORE.get(str(node_uid))
    if item is None:
        return None
    line_batches = item.get("line_batches") or ()
    point_batches = item.get("point_batches") or ()
    triangle_batches = item.get("triangle_batches") or ()
    return {
        "world_id": item["world_id"],
        "frame": item["frame"],
        "line_batch_count": len(line_batches),
        "point_batch_count": len(point_batches),
        "triangle_batch_count": len(triangle_batches),
        "line_vertex_count": sum(len(batch[0]) for batch in line_batches),
        "point_vertex_count": sum(len(batch[0]) for batch in point_batches),
        "triangle_count": sum(len(batch[1]) for batch in triangle_batches),
        "line_batch_colors": tuple(tuple(batch[1]) for batch in line_batches),
        "point_batch_colors": tuple(tuple(batch[1]) for batch in point_batches),
        "status_text": str(item.get("status_text") or ""),
    }


def _ensure_draw_handler():
    global _XPBD_DRAW_HANDLE
    if _XPBD_DRAW_HANDLE is None:
        try:
            _XPBD_DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
                _draw_mesh_xpbd_debug,
                (),
                "WINDOW",
                "POST_VIEW",
            )
        except Exception:
            _XPBD_DRAW_HANDLE = None


def _remove_draw_handler():
    global _XPBD_DRAW_HANDLE
    if _XPBD_DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_XPBD_DRAW_HANDLE, "WINDOW")
        except Exception:
            pass
        _XPBD_DRAW_HANDLE = None


def _draw_mesh_xpbd_debug():
    for item in list(_XPBD_DRAW_STORE.values()):
        draw_triangle_batches(item.get("triangle_batches") or ())
        draw_point_batches(item.get("point_batches") or ())
        draw_line_batches(item.get("line_batches") or ())


def _tag_view3d_redraw():
    try:
        windows = getattr(bpy.context.window_manager, "windows", ())
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
    "clear_mesh_xpbd_debug_draw_store",
    "dispose_mesh_xpbd_debug_draw_for_world",
    "mesh_xpbd_debug_draw_store_snapshot",
    "update_mesh_xpbd_debug_draw_store",
]
