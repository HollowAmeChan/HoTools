"""Implicit MC2 viewport debug drawing from frozen solver snapshots only."""

from __future__ import annotations

import math

import bpy
import mathutils
import numpy as np

from ..types import PhysicsWorldCache
from ..utils.debug_draw import (
    add_arc_lines,
    add_arrow_lines,
    add_basis_lines,
    add_box_lines,
    add_box_triangles,
    add_circle_lines,
    add_line,
    add_plane_triangles,
    add_point,
    add_sphere_lines,
    add_sphere_triangles,
    add_tapered_capsule_triangles,
    draw_line_batches,
    draw_point_batches,
    draw_triangle_batches,
    vector3,
)
from .debug import normalize_mc2_task_filters, request_mc2_debug_capture
from .native_context import MC2_INTERACTION_RESOURCE_KEY, MC2NativeInteractionV0
from .names import MC2_SLOT_KIND


_COLORS = {
    "longitudinal": (0.58, 0.56, 0.48, 0.28),
    "lateral": (0.48, 0.60, 0.62, 0.26),
    "triangle": (0.38, 0.46, 0.54, 0.16),
    "edge_collision": (0.70, 0.20, 0.04, 0.58),
    "edge_collision_surface": (1.00, 0.30, 0.04, 0.32),
    "point_collision_surface": (0.10, 0.92, 0.32, 0.26),
    "collider_surface": (0.03, 0.58, 1.00, 0.42),
    "active_collider_surface": (1.00, 0.04, 0.02, 0.62),
    "active_point_contact_surface": (1.00, 0.16, 0.04, 0.42),
    "active_edge_contact_surface": (1.00, 0.22, 0.04, 0.36),
    "external_contact": (1.00, 0.08, 0.04, 0.30),
    "external_contact_point": (0.92, 0.96, 1.00, 1.00),
    "external_contact_new": (1.00, 0.88, 0.08, 1.00),
    "external_contact_lost": (0.58, 0.64, 0.70, 0.68),
    "external_contact_correction": (1.00, 0.84, 0.10, 1.00),
    "cross_task_contact": (1.00, 0.12, 0.04, 0.26),
    "contact_correction": (1.00, 0.84, 0.10, 1.00),
    "fixed": (0.95, 0.25, 0.20, 0.95),
    "move": (0.25, 0.95, 0.40, 0.85),
    "depth_fixed": (1.00, 0.18, 0.62, 1.00),
    "depth_unrooted": (0.72, 0.18, 1.00, 1.00),
    "depth_root_boundary": (0.92, 0.96, 1.00, 0.90),
    "depth_inversion": (1.00, 0.04, 0.03, 1.00),
    "depth_jump": (1.00, 0.42, 0.04, 0.98),
    "depth_zero_distance": (1.00, 0.96, 0.12, 1.00),
    "motion_base": (0.20, 0.70, 0.84, 0.58),
    "step_basic": (0.48, 0.58, 0.70, 0.30),
    "gravity": (0.45, 1.00, 0.30, 0.95),
    "gravity_raw": (0.70, 0.74, 0.80, 0.48),
    "velocity": (0.20, 0.92, 1.00, 0.92),
    "real_velocity": (1.00, 0.52, 0.18, 0.72),
    "velocity_delta": (1.00, 0.86, 0.16, 0.90),
    "velocity_clamped": (1.00, 0.06, 0.04, 1.00),
    "depth_selected_path": (0.82, 0.34, 1.00, 1.00),
    "distance_ok": (0.35, 0.95, 0.42, 0.72),
    "distance_stretch": (1.00, 0.18, 0.12, 0.95),
    "distance_compress": (0.20, 0.48, 1.00, 0.95),
    "distance_correction": (1.00, 0.08, 0.04, 1.00),
    "tether_guide": (0.46, 0.49, 0.54, 0.24),
    "tether_compress_near": (0.38, 0.68, 1.00, 0.78),
    "tether_compress_active": (0.08, 0.42, 1.00, 1.00),
    "tether_stretch_near": (1.00, 0.76, 0.26, 0.82),
    "tether_stretch_active": (1.00, 0.48, 0.04, 1.00),
    "bending": (0.70, 0.38, 1.00, 0.72),
    "bending_guide": (0.46, 0.40, 0.54, 0.22),
    "bending_volume": (0.20, 0.90, 0.82, 0.72),
    "bending_correction": (1.00, 0.08, 0.04, 1.00),
    "angle_target": (1.00, 0.32, 0.72, 0.95),
    "angle_limit": (1.00, 0.82, 0.20, 0.78),
    "angle_correction": (1.00, 0.08, 0.04, 1.00),
    "max_distance": (0.30, 0.75, 1.00, 0.36),
    "max_distance_range": (0.30, 0.75, 1.00, 0.24),
    "max_distance_active": (0.20, 0.70, 1.00, 0.88),
    "backstop": (1.00, 0.40, 0.22, 0.55),
    "backstop_range": (1.00, 0.40, 0.22, 0.28),
    "backstop_active": (1.00, 0.38, 0.16, 0.88),
    "motion_guide": (0.48, 0.48, 0.54, 0.22),
    "motion_correction": (1.00, 0.08, 0.04, 1.00),
    "center": (1.00, 0.92, 0.25, 0.95),
    "center_anchor": (0.10, 0.88, 1.00, 0.92),
    "center_old": (0.28, 0.52, 1.00, 0.78),
    "center_now": (1.00, 0.72, 0.12, 0.96),
    "shift": (1.00, 0.38, 0.08, 0.94),
    "center_step": (0.22, 0.78, 1.00, 0.92),
    "center_inertia": (0.72, 0.32, 1.00, 0.92),
    "center_raw": (0.72, 0.72, 0.72, 0.72),
    "center_anchor_shift": (0.20, 0.88, 0.62, 0.88),
    "center_smoothing": (0.96, 0.76, 0.20, 0.88),
    "center_world_shift": (0.24, 0.64, 1.00, 0.92),
    "center_limited": (1.00, 0.18, 0.12, 0.98),
    "teleport_threshold": (0.32, 0.70, 1.00, 0.32),
    "teleport_direction": (0.62, 0.84, 1.00, 0.48),
    "teleport_measure": (0.28, 0.95, 0.42, 0.94),
    "teleport_keep": (1.00, 0.78, 0.10, 1.00),
    "teleport_reset": (1.00, 0.08, 0.06, 1.00),
    "negative": (0.95, 0.20, 0.70, 0.95),
    "collider": (0.08, 0.58, 0.92, 0.72),
    "radius": (0.32, 0.92, 0.72, 0.38),
    "self_radius": (0.94, 0.52, 0.92, 0.42),
    "primitive": (0.75, 0.42, 0.98, 0.72),
    "grid": (0.45, 0.50, 0.58, 0.25),
    "candidate": (0.95, 0.72, 0.25, 0.35),
    "contact": (1.00, 0.15, 0.12, 0.28),
    "contact_new": (1.00, 0.68, 0.06, 0.94),
    "contact_lost": (0.48, 0.52, 0.58, 0.34),
    "disabled_contact": (0.55, 0.55, 0.60, 0.38),
    "intersection": (1.00, 0.05, 0.72, 1.00),
    "intersection_new": (1.00, 0.34, 0.88, 1.00),
    "intersection_lost": (0.54, 0.34, 0.56, 0.46),
    "output": (0.30, 1.00, 0.82, 0.85),
}

# Contact corrections are often sub-pixel at world scale; a fixed multiplier
# keeps their relative magnitude visible without normalizing short vectors.
_CONTACT_CORRECTION_DISPLAY_SCALE = 8.0

_DEPTH_COLORS = (
    (0.10, 0.28, 1.00, 0.96),
    (0.04, 0.52, 1.00, 0.96),
    (0.02, 0.78, 0.96, 0.96),
    (0.04, 0.92, 0.68, 0.96),
    (0.24, 0.96, 0.32, 0.96),
    (0.72, 0.96, 0.16, 0.96),
    (1.00, 0.86, 0.05, 0.96),
    (1.00, 0.62, 0.02, 0.96),
    (1.00, 0.30, 0.00, 1.00),
)
for _depth_index, _depth_color in enumerate(_DEPTH_COLORS):
    _COLORS[f"depth_{_depth_index}"] = _depth_color

_MC2_DRAW_STORE: dict[str, dict] = {}
_MC2_DRAW_HANDLE = None


def _values(value):
    return () if value is None else value


def update_mc2_debug_draw_store(
    node_uid: str,
    world,
    enabled: bool,
    *,
    show_topology: bool = False,
    show_attributes: bool = True,
    show_depth: bool = False,
    depth_particle_index: int = -1,
    show_motion: bool = False,
    show_center: bool = False,
    show_collision: bool = False,
    show_collision_contacts: bool = False,
    show_radii: bool = False,
    show_self_primitives: bool = False,
    show_self_grid: bool = False,
    show_self_candidates: bool = False,
    show_self_contacts: bool = True,
    show_output: bool = False,
    task_filter: str = "",
    max_items: int = 10000,
    show_step_basic: bool = False,
    show_gravity: bool = False,
    show_velocity: bool = False,
    show_distance: bool = False,
    show_tether: bool = False,
    show_bending: bool = False,
    show_motion_base: bool = False,
    show_angle_restoration: bool = False,
    show_angle_limit: bool = False,
    show_teleport_threshold: bool = False,
    show_teleport_status: bool = False,
) -> str:
    node_key = str(node_uid)
    if not enabled or not isinstance(world, PhysicsWorldCache):
        if isinstance(world, PhysicsWorldCache):
            request_mc2_debug_capture(world, filters={})
        clear_mc2_debug_draw_store(node_uid=node_key)
        return "MC2调试未启用或物理世界无效。"

    filters = {
        "show_topology": bool(show_topology),
        "show_attributes": bool(show_attributes),
        "show_depth": bool(show_depth),
        "depth_particle_index": max(-1, int(depth_particle_index)),
        "show_step_basic": bool(show_step_basic),
        "show_gravity": bool(show_gravity),
        "show_velocity": bool(show_velocity),
        "show_distance": bool(show_distance),
        "show_tether": bool(show_tether),
        "show_bending": bool(show_bending),
        "show_motion": bool(show_motion),
        "show_motion_base": bool(show_motion_base),
        "show_angle_restoration": bool(show_angle_restoration),
        "show_angle_limit": bool(show_angle_limit),
        "show_center": bool(show_center),
        "show_teleport_threshold": bool(show_teleport_threshold),
        "show_teleport_status": bool(show_teleport_status),
        "show_collision": bool(show_collision),
        "show_collision_contacts": bool(show_collision_contacts),
        "show_radii": bool(show_radii),
        "show_self_primitives": bool(show_self_primitives),
        "show_self_grid": bool(show_self_grid),
        "show_self_candidates": bool(show_self_candidates),
        "show_self_contacts": bool(show_self_contacts),
        "show_self": bool(
            show_self_primitives
            or show_self_grid
            or show_self_candidates
            or show_self_contacts
        ),
        "show_output": bool(show_output),
        "task_filter": normalize_mc2_task_filters(task_filter),
        "max_items": max(1, min(int(max_items), 100000)),
    }
    request_mc2_debug_capture(world, filters=filters)
    batches, point_batches, triangle_batches = _build_world_batches(world, filters)
    status_text = _build_world_status_text(world, filters)
    _MC2_DRAW_STORE[node_key] = {
        "world_id": str(id(world)),
        "frame": int(getattr(world.frame_context, "frame", 0) or 0),
        "batches": batches,
        "point_batches": point_batches,
        "triangle_batches": triangle_batches,
        "status_text": status_text,
    }
    _ensure_draw_handler()
    _tag_view3d_redraw()
    return status_text


def clear_mc2_debug_draw_store(
    node_uid: str | None = None,
    world_id: str | None = None,
) -> None:
    if node_uid is not None:
        _MC2_DRAW_STORE.pop(str(node_uid), None)
    elif world_id is not None:
        owner = str(world_id)
        for key, value in list(_MC2_DRAW_STORE.items()):
            if str(value.get("world_id")) == owner:
                _MC2_DRAW_STORE.pop(key, None)
    else:
        _MC2_DRAW_STORE.clear()
    if not _MC2_DRAW_STORE:
        _remove_draw_handler()
    _tag_view3d_redraw()


def mc2_debug_draw_store_snapshot(node_uid: str) -> dict | None:
    item = _MC2_DRAW_STORE.get(str(node_uid))
    if item is None:
        return None
    line_batches = item.get("batches") or ()
    point_batches = item.get("point_batches") or ()
    triangle_batches = item.get("triangle_batches") or ()
    flattened = [
        coordinate
        for specs in (line_batches, point_batches, triangle_batches)
        for batch in specs
        for point in batch[0]
        for coordinate in point
    ]
    return {
        "world_id": item["world_id"],
        "frame": item["frame"],
        "batch_count": len(line_batches) + len(point_batches) + len(triangle_batches),
        "line_vertex_count": sum(len(batch[0]) for batch in line_batches),
        "point_vertex_count": sum(len(batch[0]) for batch in point_batches),
        "triangle_vertex_count": sum(len(batch[0]) for batch in triangle_batches),
        "triangle_count": sum(len(batch[1]) for batch in triangle_batches),
        "line_batch_colors": tuple(tuple(batch[1]) for batch in line_batches),
        "point_batch_colors": tuple(tuple(batch[1]) for batch in point_batches),
        "triangle_batch_colors": tuple(tuple(batch[2]) for batch in triangle_batches),
        "status_text": str(item.get("status_text") or ""),
        "coordinate_checksum": round(
            sum((index + 1) * float(value) for index, value in enumerate(flattened)),
            6,
        ),
    }


def _matching_slot_snapshots(world: PhysicsWorldCache, filters: dict) -> list[dict]:
    task_filters = normalize_mc2_task_filters(filters.get("task_filter"))
    snapshots = []
    for slot in world.solver_slots.values():
        if slot.kind != MC2_SLOT_KIND:
            continue
        snapshot = slot.data.get("_debug_draw_snapshot")
        if not isinstance(snapshot, dict):
            continue
        task_id = str(snapshot.get("task_id") or "")
        if task_filters and not any(token in task_id for token in task_filters):
            continue
        snapshots.append(snapshot)
    return snapshots


def _constraint_state_counts(records: dict) -> tuple[int, int, int, int, int]:
    states = np.asarray(_values(records.get("states")), dtype=np.int8).reshape((-1,))
    return (
        len(states),
        int(np.count_nonzero(states == -1)),
        int(np.count_nonzero(states == 1)),
        int(np.count_nonzero(states == -2)),
        int(np.count_nonzero(states == 2)),
    )


def _constraint_status_line(
    label: str,
    records: dict,
    *,
    negative_label: str,
    positive_label: str,
) -> str:
    total, near_negative, near_positive, active_negative, active_positive = (
        _constraint_state_counts(records)
    )
    if not total:
        return f"{label}：等待下一次真实substep捕获。"
    active = active_negative + active_positive
    near = near_negative + near_positive
    status = "本步未触发" if active == 0 else "本步已触发"
    return (
        f"{label}：{status}；记录{total}，接近{near}"
        f"（{negative_label}{near_negative}/{positive_label}{near_positive}），"
        f"触发{active}（{negative_label}{active_negative}/{positive_label}{active_positive}）。"
    )


def _branch_constraint_status_line(
    label: str,
    records: dict,
    branches: tuple[tuple[int, str], ...],
) -> str:
    states = np.asarray(_values(records.get("states")), dtype=np.int8).reshape((-1,))
    branch_values = np.asarray(
        _values(records.get("branches")), dtype=np.int8
    ).reshape((-1,))
    count = min(len(states), len(branch_values))
    if not count:
        return f"{label}：等待下一次真实substep捕获。"
    parts = []
    active_total = 0
    near_total = 0
    for branch, branch_label in branches:
        selected = states[:count][branch_values[:count] == branch]
        active = int(np.count_nonzero(np.abs(selected) == 2))
        near = int(np.count_nonzero(np.abs(selected) == 1))
        active_total += active
        near_total += near
        parts.append(f"{branch_label}触发{active}/接近{near}")
    status = "本步未触发" if active_total == 0 else "本步已触发"
    return (
        f"{label}：{status}；记录{count}，触发{active_total}，"
        f"接近{near_total}；" + "，".join(parts) + "。"
    )


def _build_slot_status_lines(snapshot: dict, filters: dict) -> list[str]:
    lines = [
        f"[{snapshot.get('task_id') or '<unnamed>'}] "
        f"{snapshot.get('setup_type') or 'unknown'}，捕获帧{int(snapshot.get('frame', 0) or 0)}"
    ]
    topology = snapshot.get("topology") or {}
    parameters = snapshot.get("parameters") or {}
    records = snapshot.get("constraint_records") or {}
    native = snapshot.get("native") or {}
    if filters.get("show_topology"):
        vertices = np.asarray(_values(topology.get("vertex_attributes"))).reshape((-1,))
        edges = np.asarray(_values(topology.get("edges"))).reshape((-1, 2))
        triangles = np.asarray(_values(topology.get("triangles"))).reshape((-1, 3))
        lines.append(
            f"拓扑：粒子{len(vertices)}，边{len(edges)}，三角形{len(triangles)}；这是结构状态，不是触发数量。"
        )
    if filters.get("show_attributes"):
        attributes = np.asarray(
            _values(topology.get("vertex_attributes")), dtype=np.uint8
        ).reshape((-1,))
        move = int(np.count_nonzero((attributes & 0x02) != 0))
        fixed = len(attributes) - move
        lines.append(f"粒子属性：Fixed {fixed}，Move {move}。")
    if filters.get("show_depth"):
        attributes = np.asarray(
            _values(topology.get("vertex_attributes")), dtype=np.uint8
        ).reshape((-1,))
        roots = np.asarray(
            _values(topology.get("baseline_root_indices")), dtype=np.int32
        ).reshape((-1,))
        count = min(len(attributes), len(roots))
        unrooted = int(np.count_nonzero(
            ((attributes[:count] & 0x02) != 0) & (roots[:count] < 0)
        ))
        lines.append(
            f"深度：有效粒子{count}，无可达Fixed的Move {unrooted}；无根或红色逆序需要检查。"
        )
    if filters.get("show_gravity"):
        lines.append(
            "重力：原始强度"
            f"{float(parameters.get('gravity_strength', 0.0) or 0.0):.4g}，"
            "当前有效强度"
            f"{float(parameters.get('gravity_effective_strength', 0.0) or 0.0):.4g}。"
        )
    if filters.get("show_velocity"):
        dynamics = native.get("dynamics") or {}
        velocities = np.asarray(
            _values(dynamics.get("velocities")), dtype=np.float32
        ).reshape((-1, 3))
        speeds = np.linalg.norm(velocities, axis=1) if len(velocities) else np.empty(0)
        limit = float(parameters.get("particle_speed_limit", -1.0) or 0.0)
        clamped = int(np.count_nonzero(speeds >= max(limit - 1.0e-5, 0.0))) if limit >= 0 else 0
        lines.append(
            f"速度：粒子{len(speeds)}，命中粒子限速{clamped}，"
            f"最大保存速度{float(np.max(speeds)) if len(speeds) else 0.0:.4g}。"
        )
    if filters.get("show_distance"):
        lines.append(_constraint_status_line(
            "Distance", records.get("distance") or {},
            negative_label="压缩", positive_label="拉伸",
        ))
    if filters.get("show_tether"):
        line = _constraint_status_line(
            "Tether", records.get("tether") or {},
            negative_label="压缩", positive_label="拉伸",
        )
        lines.append(
            line[:-1]
            + f"；当前Tether压缩={float(parameters.get('tether_compression', 0.0) or 0.0):.3g}，"
            f"拉伸上限={float(parameters.get('tether_stretch', 0.0) or 0.0):.3g}。"
        )
    if filters.get("show_bending"):
        bending = records.get("bending") or {}
        states = np.asarray(_values(bending.get("states")), dtype=np.int8).reshape((-1,))
        kinds = np.asarray(_values(bending.get("kinds")), dtype=np.int8).reshape((-1,))
        active = int(np.count_nonzero(np.abs(states) == 2))
        lines.append(
            f"Bending：记录{len(states)}，本步触发{active}；"
            f"二面角{int(np.count_nonzero(kinds == 0))}，体积{int(np.count_nonzero(kinds == 1))}。"
        )
    if filters.get("show_motion"):
        lines.append(_branch_constraint_status_line(
            "Motion", records.get("motion") or {},
            ((0, "MaxDistance"), (1, "Backstop")),
        ))
    if filters.get("show_angle_limit"):
        lines.append(_branch_constraint_status_line(
            "Angle Limit", records.get("angle_limit") or {}, ((0, "限制"),)
        ))
    if filters.get("show_angle_restoration"):
        lines.append(_branch_constraint_status_line(
            "Angle Restoration",
            records.get("angle_restoration") or {},
            ((1, "恢复"),),
        ))
    if filters.get("show_center"):
        shift = (snapshot.get("center") or {}).get("frame_shift") or {}
        lines.append(
            "Center：移动限速"
            f"{'已触发' if shift.get('movement_speed_limited') else '未触发'}，"
            "旋转限速"
            f"{'已触发' if shift.get('rotation_speed_limited') else '未触发'}。"
        )
    if filters.get("show_teleport_status") or filters.get("show_teleport_threshold"):
        teleport = snapshot.get("teleport") or {}
        mode = int(teleport.get("mode", 0) or 0)
        applied = bool(teleport.get("applied", False))
        result = "Reset" if applied and mode == 1 else "Keep" if applied and mode == 2 else "未触发"
        lines.append(
            f"Teleport：{result}；位移阈值{float(teleport.get('distance_threshold', 0.0) or 0.0):.4g}，"
            f"旋转阈值{float(teleport.get('rotation_threshold_degrees', 0.0) or 0.0):.4g}度。"
        )
    if filters.get("show_collision_contacts"):
        contacts = native.get("external_contacts") or {}
        temporal = contacts.get("temporal") or {}
        lines.append(
            f"外碰接触：当前{int(temporal.get('active_count', 0) or 0)}，"
            f"新增{int(temporal.get('new_count', 0) or 0)}，"
            f"持续{int(temporal.get('persistent_count', 0) or 0)}，"
            f"刚失效{int(temporal.get('lost_count', 0) or 0)}。"
        )
    if filters.get("show_self_contacts"):
        self_state = snapshot.get("self_collision") or {}
        contacts = self_state.get("contact_temporal") or {}
        intersections = self_state.get("intersection_temporal") or {}
        lines.append(
            f"自碰：contact当前{int(contacts.get('active_count', 0) or 0)}/新增{int(contacts.get('new_count', 0) or 0)}/失效{int(contacts.get('lost_count', 0) or 0)}；"
            f"几何穿插当前{int(intersections.get('active_count', 0) or 0)}/新增{int(intersections.get('new_count', 0) or 0)}/失效{int(intersections.get('lost_count', 0) or 0)}。"
        )
    if filters.get("show_output"):
        output = snapshot.get("output") or {}
        applied = np.asarray(
            _values(output.get("translation_applied")), dtype=np.uint8
        ).reshape((-1,))
        lines.append(
            f"最终输出：记录{len(applied)}，本帧允许平移写回{int(np.count_nonzero(applied))}。"
        )
    return lines


def _build_world_status_text(world: PhysicsWorldCache, filters: dict) -> str:
    snapshots = _matching_slot_snapshots(world, filters)
    if not snapshots:
        return (
            "等待MC2调试快照：大多数模式需要节点先登记请求，再经过下一次真实substep才有状态。"
        )
    lines = [
        f"MC2调试状态 | world帧{int(getattr(world.frame_context, 'frame', 0) or 0)} | task {len(snapshots)}"
    ]
    for snapshot in snapshots:
        lines.extend(_build_slot_status_lines(snapshot, filters))
    interaction = world.backend_resources.get(MC2_INTERACTION_RESOURCE_KEY)
    if filters.get("show_collision_contacts") and isinstance(
        interaction, MC2NativeInteractionV0
    ):
        state = interaction.debug_draw_snapshot() or {}
        enabled = np.asarray(
            _values(state.get("contact_enabled")), dtype=np.uint8
        ).reshape((-1,))
        owners = np.asarray(_values(state.get("owner_indices")), dtype=np.int32)
        contacts = np.asarray(
            _values(state.get("contact_indices")), dtype=np.int32
        ).reshape((-1, 2))
        cross_task = 0
        for index, pair in enumerate(contacts):
            first, second = map(int, pair)
            if (
                index < len(enabled) and enabled[index]
                and 0 <= first < len(owners) and 0 <= second < len(owners)
                and int(owners[first]) != int(owners[second])
            ):
                cross_task += 1
        lines.append(f"跨task实际接触：当前启用{cross_task}。")
    return "\n".join(lines)


def _build_world_batches(world: PhysicsWorldCache, filters: dict) -> tuple[list, list, list]:
    batches = []
    point_batches = []
    triangle_meshes = {}
    task_filters = normalize_mc2_task_filters(filters["task_filter"])
    for slot in world.solver_slots.values():
        if slot.kind != MC2_SLOT_KIND:
            continue
        snapshot = slot.data.get("_debug_draw_snapshot")
        if not isinstance(snapshot, dict):
            continue
        if task_filters and not any(
            token in str(snapshot.get("task_id") or "") for token in task_filters
        ):
            continue
        _append_slot_batches(
            batches, point_batches, triangle_meshes, snapshot, filters
        )

    interaction = world.backend_resources.get(MC2_INTERACTION_RESOURCE_KEY)
    if isinstance(interaction, MC2NativeInteractionV0):
        snapshot = interaction.debug_draw_snapshot()
        if isinstance(snapshot, dict):
            if filters["show_collision_contacts"]:
                _append_interaction_contact_batches(
                    batches, snapshot, filters
                )
            _append_self_batches(
                batches, point_batches, snapshot, filters, interaction=True
            )
    triangle_batches = [
        (mesh["vertices"], mesh["indices"], _COLORS[color_name])
        for color_name, mesh in triangle_meshes.items()
        if mesh["vertices"] and mesh["indices"]
    ]
    return batches, point_batches, triangle_batches


def _batch(batches: list, lines: list, color_name: str, width: float = 1.0) -> None:
    if lines:
        batches.append((lines, _COLORS[color_name], width))


def _point_batch(
    batches: list, points: list, color_name: str, size: float = 5.0
) -> None:
    if points:
        batches.append((points, _COLORS[color_name], size))


def _triangle_mesh(meshes: dict, color_name: str) -> dict:
    return meshes.setdefault(color_name, {"vertices": [], "indices": []})


def _append_slot_batches(
    batches: list,
    point_batches: list,
    triangle_meshes: dict,
    snapshot: dict,
    filters: dict,
) -> None:
    limit = filters["max_items"]
    topology = snapshot.get("topology") or {}
    positions = np.asarray(
        _values((snapshot.get("native") or {}).get("positions")),
        dtype=np.float32,
    ).reshape((-1, 3))
    if filters["show_topology"]:
        _append_topology_batches(batches, topology, positions, limit)
    if filters["show_attributes"]:
        _append_attribute_batches(point_batches, topology, positions, limit)
    if filters["show_depth"]:
        _append_depth_batches(
            batches,
            point_batches,
            topology,
            positions,
            limit,
            selected_index=filters.get("depth_particle_index", -1),
        )
    if filters["show_step_basic"]:
        _append_step_basic_batches(
            batches, topology, snapshot.get("motion") or {}, limit
        )
    if filters["show_gravity"]:
        _append_gravity_batches(
            batches,
            snapshot.get("parameters") or {},
            topology,
            positions,
            limit,
        )
    if filters["show_velocity"]:
        _append_velocity_batches(
            batches,
            positions,
            (snapshot.get("native") or {}).get("dynamics") or {},
            snapshot.get("parameters") or {},
            limit,
        )
    if filters["show_distance"]:
        _append_distance_batches(
            batches,
            ((snapshot.get("constraint_records") or {}).get("distance") or {}),
            limit,
        )
        _append_constraint_correction_batches(
            batches,
            ((snapshot.get("constraint_records") or {}).get("distance") or {}),
            "distance_correction",
            limit,
        )
    if filters["show_tether"]:
        _append_tether_batches(
            batches,
            point_batches,
            ((snapshot.get("constraint_records") or {}).get("tether") or {}),
            limit,
        )
    if filters["show_bending"]:
        _append_bending_batches(
            batches,
            point_batches,
            ((snapshot.get("constraint_records") or {}).get("bending") or {}),
            limit,
        )
        _append_constraint_correction_batches(
            batches,
            ((snapshot.get("constraint_records") or {}).get("bending") or {}),
            "bending_correction",
            limit,
        )
    if filters["show_motion_base"]:
        _append_motion_base_batches(
            batches, point_batches, snapshot.get("motion") or {}, limit
        )
    if filters["show_motion"]:
        _append_motion_batches(
            batches,
            point_batches,
            ((snapshot.get("constraint_records") or {}).get("motion") or {}),
            limit,
        )
        _append_constraint_correction_batches(
            batches,
            ((snapshot.get("constraint_records") or {}).get("motion") or {}),
            "motion_correction",
            limit,
        )
    if filters["show_angle_restoration"]:
        _append_angle_restoration_batches(
            batches,
            point_batches,
            snapshot.get("motion") or {},
            np.asarray(
                _values((snapshot.get("native") or {}).get("positions")),
                dtype=np.float32,
            ).reshape((-1, 3)),
            limit,
        )
        _append_constraint_correction_batches(
            batches,
            ((snapshot.get("constraint_records") or {}).get(
                "angle_restoration"
            ) or {}),
            "angle_correction",
            limit,
        )
    if filters["show_angle_limit"]:
        _append_angle_limit_batches(
            batches, snapshot.get("motion") or {}, limit
        )
        _append_constraint_correction_batches(
            batches,
            ((snapshot.get("constraint_records") or {}).get("angle_limit") or {}),
            "angle_correction",
            limit,
        )
    if filters["show_center"]:
        _append_center_batches(batches, point_batches, snapshot.get("center") or {})
    if filters["show_teleport_threshold"] or filters["show_teleport_status"]:
        _append_task_teleport_batches(
            batches,
            point_batches,
            snapshot.get("teleport") or {},
            filters,
            limit,
        )
    if filters["show_collision"]:
        _append_collision_situation_batches(
            batches, triangle_meshes, snapshot, topology, positions, limit
        )
    if filters["show_collision_contacts"]:
        _append_external_contact_batches(
            batches,
            point_batches,
            triangle_meshes,
            snapshot,
            topology,
            positions,
            limit,
        )
    if filters["show_radii"]:
        _append_radius_batches(batches, snapshot, limit)
    _append_self_batches(
        batches,
        point_batches,
        snapshot.get("native") or {},
        filters,
        interaction=False,
    )
    if filters["show_output"]:
        _append_output_batches(batches, point_batches, snapshot, limit)


def _append_topology_batches(batches, topology, positions, limit):
    longitudinal = []
    lateral = []
    triangles = []
    long_edges = np.asarray(
        _values(topology.get("longitudinal_edges")), dtype=np.int32
    ).reshape((-1, 2))
    lateral_edges = np.asarray(
        _values(topology.get("lateral_edges")), dtype=np.int32
    ).reshape((-1, 2))
    classified = (
        {
            tuple(sorted(map(int, edge)))
            for edge in np.vstack((long_edges, lateral_edges))
        }
        if len(long_edges) + len(lateral_edges)
        else set()
    )
    all_edges = np.asarray(
        _values(topology.get("edges")), dtype=np.int32
    ).reshape((-1, 2))
    all_edge_keys = {tuple(sorted(map(int, edge))) for edge in all_edges}
    for edge in long_edges[:limit]:
        _add_index_line(longitudinal, positions, edge)
    for edge in lateral_edges[:limit]:
        _add_index_line(lateral, positions, edge)
    for edge in all_edges[:limit]:
        if tuple(sorted(map(int, edge))) not in classified:
            _add_index_line(longitudinal, positions, edge)
    triangle_values = np.asarray(
        _values(topology.get("triangles")), dtype=np.int32
    ).reshape((-1, 3))
    for triangle in triangle_values[:limit]:
        first, second, third = map(int, triangle)
        for edge in ((first, second), (second, third), (third, first)):
            if tuple(sorted(edge)) not in all_edge_keys:
                _add_index_line(triangles, positions, edge)
    _batch(batches, longitudinal, "longitudinal", 2.0)
    _batch(batches, lateral, "lateral", 2.4)
    _batch(batches, triangles, "triangle", 1.0)


def _active_collision_payload(collision):
    mode = int(collision.get("collision_mode", 0) or 0)
    if mode not in (1, 2):
        return mode, None
    colliders = collision.get("colliders")
    if not isinstance(colliders, dict):
        return mode, None
    if int(colliders.get("collided_by_groups", 0) or 0) == 0:
        return mode, None
    types = np.asarray(_values(colliders.get("types")), dtype=np.int32)
    group_bits = np.asarray(_values(colliders.get("group_bits")), dtype=np.int32)
    if not len(types) or len(group_bits) != len(types):
        return mode, None
    collided_by_groups = int(colliders.get("collided_by_groups", 0) or 0)
    if not any(collided_by_groups & int(value) for value in group_bits):
        return mode, None
    return mode, colliders


def _append_collision_situation_batches(
    batches, triangle_meshes, snapshot, topology, positions, limit
):
    collision = snapshot.get("collision") or {}
    mode, colliders = _active_collision_payload(collision)
    if colliders is None:
        return
    _append_collider_batches(batches, triangle_meshes, collision, limit)
    if mode == 1:
        _append_point_collision_batches(
            batches,
            triangle_meshes,
            positions,
            topology,
            collision,
            str(snapshot.get("setup_type") or ""),
            limit,
        )
    else:
        _append_edge_collision_batches(
            batches, triangle_meshes, topology, positions, collision, limit
        )


def _collision_component_ids(vertex_count, edges):
    parent = np.arange(max(int(vertex_count), 0), dtype=np.int32)

    def find(value):
        value = int(value)
        while int(parent[value]) != value:
            parent[value] = parent[int(parent[value])]
            value = int(parent[value])
        return value

    for edge in np.asarray(edges, dtype=np.int32).reshape((-1, 2)):
        left, right = map(int, edge)
        if min(left, right) < 0 or max(left, right) >= len(parent):
            continue
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root
    return np.asarray([find(index) for index in range(len(parent))], dtype=np.int32)


def _component_fair_sample(candidate_indices, component_ids, limit):
    candidates = np.asarray(candidate_indices, dtype=np.int32).reshape((-1,))
    limit = max(int(limit), 0)
    if len(candidates) <= limit:
        return candidates
    if limit == 0:
        return np.empty((0,), dtype=np.int32)

    groups = {}
    for candidate, component in zip(candidates, component_ids):
        groups.setdefault(int(component), []).append(int(candidate))
    buckets = list(groups.values())
    if len(buckets) >= limit:
        selected = np.linspace(0, len(buckets) - 1, limit, dtype=np.int32)
        return np.asarray(
            [buckets[int(index)][len(buckets[int(index)]) // 2] for index in selected],
            dtype=np.int32,
        )

    quotas = np.ones(len(buckets), dtype=np.int32)
    capacities = np.asarray([len(bucket) - 1 for bucket in buckets], dtype=np.int32)
    remaining = limit - len(buckets)
    capacity_total = int(np.sum(capacities))
    if remaining > 0 and capacity_total > 0:
        shares = capacities.astype(np.float64) * (float(remaining) / capacity_total)
        extras = np.minimum(np.floor(shares).astype(np.int32), capacities)
        quotas += extras
        remaining -= int(np.sum(extras))
        order = sorted(
            range(len(buckets)),
            key=lambda index: (
                -(shares[index] - math.floor(shares[index])),
                -capacities[index],
                index,
            ),
        )
        while remaining > 0:
            progressed = False
            for index in order:
                if quotas[index] >= len(buckets[index]):
                    continue
                quotas[index] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
            if not progressed:
                break

    selected = []
    for bucket, quota in zip(buckets, quotas):
        offsets = np.linspace(0, len(bucket) - 1, int(quota), dtype=np.int32)
        selected.extend(bucket[int(offset)] for offset in offsets)
    return np.asarray(sorted(selected), dtype=np.int32)


def _append_point_collision_batches(
    batches, triangle_meshes, positions, topology, collision, setup_type, limit
):
    attributes = np.asarray(
        _values(topology.get("vertex_attributes")), dtype=np.uint8
    )
    radii = np.asarray(_values(collision.get("particle_radii")), dtype=np.float32)
    is_spring = setup_type == "bone_spring"
    mesh = _triangle_mesh(triangle_meshes, "point_collision_surface")
    count = min(len(positions), len(attributes), len(radii))
    edges = np.asarray(_values(topology.get("edges")), dtype=np.int32).reshape((-1, 2))
    component_ids = _collision_component_ids(count, edges)
    candidates = []
    for index in range(count):
        attribute = int(attributes[index])
        valid = bool(attribute & 0x03) if is_spring else bool(attribute & 0x02)
        if not valid or attribute & 0x10:
            continue
        radius = max(float(radii[index]), 0.0)
        if radius <= 1.0e-7:
            continue
        candidates.append(index)
    selected = _component_fair_sample(
        candidates,
        component_ids[np.asarray(candidates, dtype=np.intp)],
        limit,
    )
    for index in selected:
        index = int(index)
        radius = max(float(radii[index]), 0.0)
        add_sphere_triangles(
            mesh["vertices"], mesh["indices"], positions[index], radius
        )


def _append_edge_collision_batches(
    batches, triangle_meshes, topology, positions, collision, limit
):
    mode, colliders = _active_collision_payload(collision)
    if mode != 2 or colliders is None:
        return
    edges = np.asarray(_values(topology.get("edges")), dtype=np.int32).reshape((-1, 2))
    attributes = np.asarray(
        _values(topology.get("vertex_attributes")), dtype=np.uint8
    )
    radii = np.asarray(_values(collision.get("particle_radii")), dtype=np.float32)
    mesh = _triangle_mesh(triangle_meshes, "edge_collision_surface")
    centers = []
    vertex_count = min(len(positions), len(attributes), len(radii))
    component_ids = _collision_component_ids(vertex_count, edges)
    candidates = []
    for edge_index, edge in enumerate(edges):
        left, right = map(int, edge)
        if min(left, right) < 0 or max(left, right) >= len(positions):
            continue
        if max(left, right) >= len(attributes) or max(left, right) >= len(radii):
            continue
        if not (int(attributes[left]) & 0x02 or int(attributes[right]) & 0x02):
            continue
        radius_left = max(float(radii[left]), 0.0)
        radius_right = max(float(radii[right]), 0.0)
        if max(radius_left, radius_right) <= 1.0e-7:
            continue
        candidates.append(edge_index)
    selected = _component_fair_sample(
        candidates,
        component_ids[
            np.asarray([int(edges[index][0]) for index in candidates], dtype=np.intp)
        ],
        limit,
    )
    for edge_index in selected:
        left, right = map(int, edges[int(edge_index)])
        radius_left = max(float(radii[left]), 0.0)
        radius_right = max(float(radii[right]), 0.0)
        add_line(centers, positions[left], positions[right])
        add_tapered_capsule_triangles(
            mesh["vertices"],
            mesh["indices"],
            positions[left],
            positions[right],
            radius_left,
            radius_right,
        )
    _batch(batches, centers, "edge_collision", 1.0)


def _append_attribute_batches(point_batches, topology, positions, limit):
    fixed = []
    move = []
    attributes = np.asarray(_values(topology.get("vertex_attributes")), dtype=np.uint8)
    for index, attribute in enumerate(attributes[:limit]):
        target = move if int(attribute) & 0x02 else fixed
        add_point(target, positions[index])
    _point_batch(point_batches, fixed, "fixed", 6.0)
    _point_batch(point_batches, move, "move", 4.0)


def _append_depth_batches(
    batches, point_batches, topology, positions, limit, *, selected_index=-1
):
    attributes = np.asarray(
        _values(topology.get("vertex_attributes")), dtype=np.uint8
    ).reshape((-1,))
    parents = np.asarray(
        _values(topology.get("baseline_parent_indices")), dtype=np.int32
    ).reshape((-1,))
    roots = np.asarray(
        _values(topology.get("baseline_root_indices")), dtype=np.int32
    ).reshape((-1,))
    depths = np.asarray(
        _values(topology.get("baseline_depths")), dtype=np.float32
    ).reshape((-1,))
    count = min(len(positions), len(attributes), len(parents), len(roots), len(depths))
    draw_count = min(count, limit)
    if draw_count <= 0:
        return

    def effective_root(index):
        attribute = int(attributes[index])
        if attribute & 0x01:
            return index
        root = int(roots[index])
        return root if 0 <= root < count else -1

    bins = [[] for _ in _DEPTH_COLORS]
    fixed = []
    unrooted = []
    zero_distance = []
    invalid = []
    inversion_lines = []
    jump_lines = []
    root_boundary_lines = []
    positive_deltas = []
    for index in range(count):
        if not int(attributes[index]) & 0x02:
            continue
        parent = int(parents[index])
        if 0 <= parent < count:
            delta = float(depths[index]) - float(depths[parent])
            if delta > 1.0e-6:
                positive_deltas.append(delta)
    jump_threshold = max(
        0.25,
        float(np.median(positive_deltas)) * 4.0 if positive_deltas else 0.25,
    )

    for index in range(draw_count):
        attribute = int(attributes[index])
        if not attribute & 0x03:
            continue
        if attribute & 0x01:
            add_point(fixed, positions[index])
            continue
        if attribute & 0x20:
            add_point(zero_distance, positions[index])
        parent = int(parents[index])
        root = effective_root(index)
        if root < 0:
            add_point(unrooted, positions[index])
            continue
        if parent < 0 or parent >= count:
            add_point(invalid, positions[index])
            continue
        raw_depth = float(depths[index])
        depth = min(max(raw_depth, 0.0), 1.0)
        bin_index = min(int(depth * len(_DEPTH_COLORS)), len(_DEPTH_COLORS) - 1)
        add_point(bins[bin_index], positions[index])
        parent_depth = float(depths[parent])
        parent_root = effective_root(parent)
        if raw_depth + 1.0e-5 < parent_depth or parent_root != root:
            add_line(inversion_lines, positions[parent], positions[index])
            add_point(invalid, positions[index])
        elif depth - parent_depth > jump_threshold:
            add_line(jump_lines, positions[parent], positions[index])

    edges = np.asarray(
        _values(topology.get("edges")), dtype=np.int32
    ).reshape((-1, 2))
    boundary_count = 0
    for left, right in edges:
        if boundary_count >= limit:
            break
        left = int(left)
        right = int(right)
        if min(left, right) < 0 or max(left, right) >= count:
            continue
        if int(attributes[left]) & 0x01 and int(attributes[right]) & 0x01:
            continue
        left_root = effective_root(left)
        right_root = effective_root(right)
        if left_root >= 0 and right_root >= 0 and left_root != right_root:
            add_line(root_boundary_lines, positions[left], positions[right])
            boundary_count += 1

    for index, points in enumerate(bins):
        _point_batch(point_batches, points, f"depth_{index}", 5.0)
    _point_batch(point_batches, unrooted, "depth_unrooted", 6.0)
    _point_batch(point_batches, fixed, "depth_fixed", 7.0)
    _point_batch(point_batches, zero_distance, "depth_zero_distance", 8.0)
    _point_batch(point_batches, invalid, "depth_inversion", 8.0)
    _batch(batches, root_boundary_lines, "depth_root_boundary", 1.4)
    _batch(batches, jump_lines, "depth_jump", 2.0)
    _batch(batches, inversion_lines, "depth_inversion", 2.8)
    selected_index = int(selected_index)
    if not 0 <= selected_index < count:
        return
    path_lines = []
    path_points = []
    visited = set()
    current = selected_index
    for _step in range(min(count, limit)):
        if current in visited or not 0 <= current < count:
            break
        visited.add(current)
        add_point(path_points, positions[current])
        parent = int(parents[current])
        if parent < 0 or parent >= count:
            break
        add_line(path_lines, positions[current], positions[parent])
        current = parent
    _batch(batches, path_lines, "depth_selected_path", 3.2)
    _point_batch(point_batches, path_points, "depth_selected_path", 8.0)


def _append_step_basic_batches(batches, topology, motion, limit):
    positions = motion.get("step_basic_positions")
    if positions is None:
        return
    positions = np.asarray(positions, dtype=np.float32).reshape((-1, 3))
    edges = np.asarray(
        _values(topology.get("edges")), dtype=np.int32
    ).reshape((-1, 2))
    lines = []
    for edge in edges[:limit]:
        _add_index_line(lines, positions, edge)
    _batch(batches, lines, "step_basic", 1.6)


def _append_gravity_batches(batches, parameters, topology, positions, limit):
    direction = np.asarray(
        _values(parameters.get("gravity_direction")), dtype=np.float32
    ).reshape((-1,))
    effective_strength = float(
        parameters.get("gravity_effective_strength", 0.0) or 0.0
    )
    raw_strength = (
        float(parameters.get("gravity_strength", 0.0) or 0.0)
        * float(parameters.get("scale_ratio", 1.0) or 1.0)
    )
    if len(direction) != 3 or max(raw_strength, effective_strength) <= 1.0e-8:
        return
    direction = vector3(direction)
    if direction.length <= 1.0e-8:
        return
    direction.normalize()
    attributes = np.asarray(
        _values(topology.get("vertex_attributes")), dtype=np.uint8
    ).reshape((-1,))
    raw_lines = []
    effective_lines = []
    for index, position in enumerate(positions[:limit]):
        if index < len(attributes) and not (int(attributes[index]) & 0x02):
            continue
        start = vector3(position)
        if raw_strength > 1.0e-8:
            add_arrow_lines(
                raw_lines, start, start + direction * raw_strength * 0.02
            )
        if effective_strength > 1.0e-8:
            add_arrow_lines(
                effective_lines,
                start,
                start + direction * effective_strength * 0.02,
            )
    _batch(batches, raw_lines, "gravity_raw", 1.0)
    _batch(batches, effective_lines, "gravity", 2.2)


def _append_velocity_batches(batches, positions, dynamics, parameters, limit):
    velocities = dynamics.get("velocities")
    real_velocities = dynamics.get("real_velocities")
    if velocities is None or real_velocities is None:
        return
    velocities = np.asarray(velocities, dtype=np.float32).reshape((-1, 3))
    real_velocities = np.asarray(real_velocities, dtype=np.float32).reshape((-1, 3))
    stored_lines = []
    real_lines = []
    delta_lines = []
    clamped_lines = []
    speed_limit = float(parameters.get("particle_speed_limit", -1.0) or 0.0)
    for position, velocity, real_velocity in zip(
        positions[:limit], velocities[:limit], real_velocities[:limit]
    ):
        start = vector3(position)
        stored = vector3(velocity) * 0.03
        real = vector3(real_velocity) * 0.03
        stored_speed = vector3(velocity).length
        is_clamped = (
            speed_limit >= 0.0
            and stored_speed >= max(speed_limit - 1.0e-5, 0.0)
        )
        if stored.length > 1.0e-7:
            add_arrow_lines(
                clamped_lines if is_clamped else stored_lines,
                start,
                start + stored,
            )
        if real.length > 1.0e-7:
            add_arrow_lines(real_lines, start, start + real)
        difference = stored - real
        if difference.length > 1.0e-7:
            add_arrow_lines(delta_lines, start + real, start + stored)
    _batch(batches, real_lines, "real_velocity", 1.0)
    _batch(batches, stored_lines, "velocity", 1.8)
    _batch(batches, delta_lines, "velocity_delta", 1.2)
    _batch(batches, clamped_lines, "velocity_clamped", 2.6)


def _append_constraint_correction_batches(
    batches, constraint_result, color_key, limit
):
    origins = constraint_result.get("origins")
    corrections = constraint_result.get("corrections")
    if origins is None or corrections is None:
        return
    origins = np.asarray(origins, dtype=np.float32).reshape((-1, 3))
    corrections = np.asarray(corrections, dtype=np.float32).reshape((-1, 3))
    parent_origins = constraint_result.get("parent_origins")
    parent_corrections = constraint_result.get("parent_corrections")
    if parent_origins is not None and parent_corrections is not None:
        origins = np.concatenate((
            origins,
            np.asarray(parent_origins, dtype=np.float32).reshape((-1, 3)),
        ))
        corrections = np.concatenate((
            corrections,
            np.asarray(parent_corrections, dtype=np.float32).reshape((-1, 3)),
        ))
    correction_lines = []
    drawn = 0
    for origin, correction in zip(origins, corrections):
        delta = vector3(correction)
        if delta.length <= 1.0e-8:
            continue
        start = vector3(origin)
        add_arrow_lines(correction_lines, start, start + delta)
        drawn += 1
        if drawn >= limit:
            break
    _batch(batches, correction_lines, color_key, 2.4)


def _append_distance_batches(batches, records, limit):
    origins = records.get("origins")
    target_origins = records.get("target_origins")
    states = records.get("states")
    if origins is None or target_origins is None or states is None:
        return
    origins = np.asarray(origins, dtype=np.float32).reshape((-1, 3))
    target_origins = np.asarray(target_origins, dtype=np.float32).reshape((-1, 3))
    states = np.asarray(states, dtype=np.int8).reshape((-1,))
    stretch_lines = []
    compress_lines = []
    drawn = 0
    for origin, target_origin, state in zip(origins, target_origins, states):
        if drawn >= limit:
            break
        state = int(state)
        if state == 0:
            continue
        target_lines = stretch_lines if state > 0 else compress_lines
        add_line(target_lines, origin, target_origin)
        drawn += 1
    _batch(batches, compress_lines, "distance_compress", 1.8)
    _batch(batches, stretch_lines, "distance_stretch", 1.8)


def _append_tether_batches(batches, point_batches, records, limit):
    origins = records.get("origins")
    root_origins = records.get("root_origins")
    corrections = records.get("corrections")
    states = records.get("states")
    if any(value is None for value in (origins, root_origins, corrections, states)):
        return
    origins = np.asarray(origins, dtype=np.float32).reshape((-1, 3))
    root_origins = np.asarray(root_origins, dtype=np.float32).reshape((-1, 3))
    corrections = np.asarray(corrections, dtype=np.float32).reshape((-1, 3))
    states = np.asarray(states, dtype=np.int8).reshape((-1,))
    compress_near_points = []
    compress_active_points = []
    stretch_near_points = []
    stretch_active_points = []
    guide_lines = []
    compress_arrows = []
    stretch_arrows = []
    drawn = 0
    for origin, root_origin, correction, state in zip(
        origins, root_origins, corrections, states
    ):
        if drawn >= limit:
            break
        state = int(state)
        if state == 0:
            continue
        add_line(guide_lines, root_origin, origin)
        active = abs(state) == 2
        if state < 0:
            add_point(
                compress_active_points if active else compress_near_points,
                origin,
            )
            arrows = compress_arrows
        else:
            add_point(
                stretch_active_points if active else stretch_near_points,
                origin,
            )
            arrows = stretch_arrows
        delta = vector3(correction)
        if active and delta.length > 1.0e-8:
            start = vector3(origin)
            add_arrow_lines(arrows, start, start + delta)
        drawn += 1
    _point_batch(point_batches, compress_near_points, "tether_compress_near", 3.0)
    _point_batch(
        point_batches, compress_active_points, "tether_compress_active", 7.0
    )
    _point_batch(point_batches, stretch_near_points, "tether_stretch_near", 3.0)
    _point_batch(
        point_batches, stretch_active_points, "tether_stretch_active", 7.0
    )
    _batch(batches, guide_lines, "tether_guide", 1.0)
    _batch(batches, compress_arrows, "tether_compress_active", 2.4)
    _batch(batches, stretch_arrows, "tether_stretch_active", 2.4)


def _append_bending_batches(batches, point_batches, records, limit):
    origins = records.get("origins")
    kinds = records.get("kinds")
    states = records.get("states")
    if origins is None or kinds is None or states is None:
        return
    origins = np.asarray(origins, dtype=np.float32).reshape((-1, 4, 3))
    kinds = np.asarray(kinds, dtype=np.int8).reshape((-1,))
    states = np.asarray(states, dtype=np.int8).reshape((-1,))
    guide_lines = []
    angle_points = []
    volume_points = []
    for quad_origins, kind, state in zip(origins[:limit], kinds, states):
        if abs(int(state)) != 2:
            continue
        points = [vector3(point) for point in quad_origins]
        add_line(guide_lines, points[2], points[3])
        center = sum(points, vector3((0.0, 0.0, 0.0))) / 4.0
        add_point(volume_points if int(kind) == 1 else angle_points, center)
    _batch(batches, guide_lines, "bending_guide", 1.0)
    _point_batch(point_batches, angle_points, "bending", 7.0)
    _point_batch(point_batches, volume_points, "bending_volume", 7.0)


def _append_motion_batches(batches, point_batches, records, limit):
    origins = records.get("origins")
    targets = records.get("target_origins")
    limits = records.get("limits")
    branches = records.get("branches")
    states = records.get("states")
    if any(value is None for value in (origins, targets, limits, branches, states)):
        return
    origins = np.asarray(origins, dtype=np.float32).reshape((-1, 3))
    targets = np.asarray(targets, dtype=np.float32).reshape((-1, 3))
    limits = np.asarray(limits, dtype=np.float32).reshape((-1,))
    branches = np.asarray(branches, dtype=np.int8).reshape((-1,))
    states = np.asarray(states, dtype=np.int8).reshape((-1,))
    guide_lines = []
    max_lines = []
    backstop_lines = []
    max_near_points = []
    max_active_points = []
    backstop_near_points = []
    backstop_active_points = []
    for origin, target, radius, branch, state in zip(
        origins[:limit], targets[:limit], limits[:limit], branches, states
    ):
        if int(state) == 0:
            continue
        active = abs(int(state)) == 2
        add_line(guide_lines, target, origin)
        range_lines = max_lines if int(branch) == 0 else backstop_lines
        _add_axis_sphere(range_lines, target, float(radius))
        if int(branch) == 0:
            points = max_active_points if active else max_near_points
        else:
            points = backstop_active_points if active else backstop_near_points
        add_point(points, origin)
    _batch(batches, guide_lines, "motion_guide", 0.8)
    _batch(batches, max_lines, "max_distance_range", 1.0)
    _batch(batches, backstop_lines, "backstop_range", 1.0)
    _point_batch(point_batches, max_near_points, "max_distance", 3.0)
    _point_batch(point_batches, max_active_points, "max_distance_active", 7.0)
    _point_batch(point_batches, backstop_near_points, "backstop", 3.0)
    _point_batch(point_batches, backstop_active_points, "backstop_active", 7.0)


def _append_motion_base_batches(batches, point_batches, motion, limit):
    base = motion.get("motion_base_positions")
    rotations = motion.get("motion_base_rotations_xyzw")
    if base is None or rotations is None:
        return
    base = np.asarray(base, dtype=np.float32).reshape((-1, 3))
    rotations = np.asarray(rotations, dtype=np.float32).reshape((-1, 4))
    axes = _motion_axes(base, rotations, int(motion.get("normal_axis", 1)))
    lines = []
    points = []
    for center, axis in zip(base[:limit], axes[:limit]):
        add_point(points, center)
        add_arrow_lines(
            lines,
            center,
            vector3(center) + vector3(axis) * 0.025,
            head_length=0.007,
        )
    _batch(batches, lines, "motion_base", 1.2)
    _point_batch(point_batches, points, "motion_base", 5.0)


def _append_angle_restoration_batches(
    batches, point_batches, motion, current, limit
):
    if not bool(motion.get("use_angle_restoration")):
        return
    targets = motion.get("angle_restoration_target_positions")
    valid = motion.get("angle_restoration_target_valid")
    if targets is None or valid is None:
        return
    targets = np.asarray(targets, dtype=np.float32).reshape((-1, 3))
    valid = np.asarray(valid, dtype=np.uint8)
    strengths = np.asarray(
        _values(motion.get("angle_restoration_strengths")), dtype=np.float32
    )
    lines = []
    points = []
    for index, target in enumerate(targets[:limit]):
        if index >= len(current) or index >= len(valid) or not valid[index]:
            continue
        if index < len(strengths) and float(strengths[index]) <= 1.0e-8:
            continue
        add_arrow_lines(lines, current[index], target)
        add_point(points, target)
    _batch(batches, lines, "angle_target", 1.8)
    _point_batch(point_batches, points, "angle_target", 7.0)


def _append_angle_limit_batches(batches, motion, limit):
    if not bool(motion.get("use_angle_limit")):
        return
    if float(motion.get("angle_limit_stiffness", 0.0) or 0.0) <= 1.0e-8:
        return
    targets = motion.get("angle_limit_target_positions")
    vectors = motion.get("angle_limit_target_vectors")
    valid = motion.get("angle_limit_target_valid")
    limits = motion.get("angle_limits")
    if targets is None or vectors is None or valid is None or limits is None:
        return
    targets = np.asarray(targets, dtype=np.float32).reshape((-1, 3))
    vectors = np.asarray(vectors, dtype=np.float32).reshape((-1, 3))
    valid = np.asarray(valid, dtype=np.uint8)
    limits = np.asarray(limits, dtype=np.float32)
    lines = []
    for index, (target, raw_vector) in enumerate(
        zip(targets[:limit], vectors[:limit])
    ):
        if index >= len(valid) or not valid[index] or index >= len(limits):
            continue
        vector = vector3(raw_vector)
        length = vector.length
        if length <= 1.0e-8:
            continue
        direction = vector / length
        parent = vector3(target) - vector
        angle = math.radians(max(0.0, min(180.0, float(limits[index]))))
        if angle >= math.pi - 1.0e-4:
            _add_axis_sphere(lines, parent, length)
            continue
        cap_center = parent + direction * (math.cos(angle) * length)
        cap_radius = math.sin(angle) * length
        axis_a, axis_b = _plane_axes(direction)
        if cap_radius > 1.0e-7:
            add_circle_lines(lines, cap_center, axis_a, axis_b, cap_radius)
            for side in (axis_a, -axis_a, axis_b, -axis_b):
                add_line(lines, parent, cap_center + side * cap_radius)
        else:
            add_line(lines, parent, parent + direction * length)
    _batch(batches, lines, "angle_limit", 1.4)


def _append_task_teleport_batches(
    batches, point_batches, teleport, filters, limit
):
    if "reference_position" in teleport:
        old_position = vector3(teleport.get("old_reference_position", (0.0, 0.0, 0.0)))
        position = vector3(teleport.get("reference_position", (0.0, 0.0, 0.0)))
        radius = max(float(teleport.get("distance_threshold", 0.0) or 0.0), 0.0)
        old_xyzw = teleport.get("old_reference_rotation_xyzw", (0.0, 0.0, 0.0, 1.0))
        current_xyzw = teleport.get("reference_rotation_xyzw", (0.0, 0.0, 0.0, 1.0))
        old_rotation = mathutils.Quaternion((
            float(old_xyzw[3]), float(old_xyzw[0]),
            float(old_xyzw[1]), float(old_xyzw[2]),
        ))
        current_rotation = mathutils.Quaternion((
            float(current_xyzw[3]), float(current_xyzw[0]),
            float(current_xyzw[1]), float(current_xyzw[2]),
        ))
        delta = current_rotation @ old_rotation.conjugated()
        axis = (
            delta.axis
            if abs(float(delta.angle)) > 1.0e-7
            else old_rotation @ mathutils.Vector((0.0, 0.0, 1.0))
        )
        axis_a, axis_b = _plane_axes(axis)
        arc_radius = max(min(radius * 0.28, 0.25), 0.025)
        if filters.get("show_teleport_threshold", False):
            threshold_lines = []
            direction_lines = []
            if radius > 1.0e-7:
                _add_axis_sphere(threshold_lines, old_position, radius)
            if (position - old_position).length > 1.0e-7:
                add_arrow_lines(direction_lines, old_position, position)
            rotation_limit = math.radians(max(
                float(teleport.get("rotation_threshold_degrees", 0.0) or 0.0),
                0.0,
            ))
            if rotation_limit > 1.0e-7:
                add_arc_lines(
                    threshold_lines, old_position, axis_a, axis_b,
                    arc_radius, 0.0, min(rotation_limit, math.pi),
                )
            if abs(float(delta.angle)) > 1.0e-7:
                add_arc_lines(
                    direction_lines, old_position, axis_a, axis_b,
                    arc_radius * 0.76, 0.0,
                    min(abs(float(delta.angle)), math.pi),
                )
            _batch(batches, threshold_lines, "teleport_threshold", 0.8)
            _batch(batches, direction_lines, "teleport_direction", 1.0)
        if filters.get("show_teleport_status", False):
            mode = int(teleport.get("mode", 0) or 0)
            applied = bool(teleport.get("applied", False))
            target = (
                "teleport_reset" if applied and mode == 1
                else "teleport_keep" if applied and mode == 2
                else "teleport_measure"
            )
            status_lines = []
            if (position - old_position).length > 1.0e-7:
                add_arrow_lines(status_lines, old_position, position)
            if abs(float(delta.angle)) > 1.0e-7:
                add_arc_lines(
                    status_lines,
                    old_position,
                    axis_a,
                    axis_b,
                    arc_radius * 0.76,
                    0.0,
                    min(abs(float(delta.angle)), math.pi),
                )
            _batch(batches, status_lines, target, 2.4 if applied else 1.8)
            _point_batch(point_batches, [position], target, 9.0 if applied else 6.0)
        return

    if filters.get("show_teleport_threshold", False):
        threshold = teleport.get("threshold") or {}
        old_positions = np.asarray(
            _values(threshold.get("old_positions")), dtype=np.float32
        ).reshape((-1, 3))
        positions = np.asarray(
            _values(threshold.get("positions")), dtype=np.float32
        ).reshape((-1, 3))
        old_rotations = np.asarray(
            _values(threshold.get("old_rotations_xyzw")), dtype=np.float32
        ).reshape((-1, 4))
        rotations = np.asarray(
            _values(threshold.get("rotations_xyzw")), dtype=np.float32
        ).reshape((-1, 4))
        eligible = np.asarray(
            _values(threshold.get("eligible")), dtype=np.uint8
        ).reshape((-1,))
        count = min(
            len(old_positions), len(positions), len(old_rotations), len(rotations),
            len(eligible), limit
        )
        radius = max(float(threshold.get("distance_threshold", 0.0) or 0.0), 0.0)
        rotation_limit = math.radians(max(
            float(threshold.get("rotation_threshold_degrees", 0.0) or 0.0),
            0.0,
        ))
        threshold_lines = []
        direction_lines = []
        for index in range(count):
            if eligible[index] == 0:
                continue
            old_position = vector3(old_positions[index])
            position = vector3(positions[index])
            if radius > 1.0e-7:
                _add_axis_sphere(threshold_lines, old_position, radius)
            if (position - old_position).length > 1.0e-7:
                add_arrow_lines(direction_lines, old_position, position)
            old_xyzw = old_rotations[index]
            current_xyzw = rotations[index]
            old_rotation = mathutils.Quaternion((
                float(old_xyzw[3]),
                float(old_xyzw[0]),
                float(old_xyzw[1]),
                float(old_xyzw[2]),
            ))
            current_rotation = mathutils.Quaternion((
                float(current_xyzw[3]),
                float(current_xyzw[0]),
                float(current_xyzw[1]),
                float(current_xyzw[2]),
            ))
            delta = current_rotation @ old_rotation.conjugated()
            axis = delta.axis if abs(float(delta.angle)) > 1.0e-7 else old_rotation @ mathutils.Vector((0.0, 0.0, 1.0))
            axis_a, axis_b = _plane_axes(axis)
            arc_radius = max(min(radius * 0.28, 0.25), 0.025)
            if rotation_limit > 1.0e-7:
                add_arc_lines(
                    threshold_lines,
                    old_position,
                    axis_a,
                    axis_b,
                    arc_radius,
                    0.0,
                    min(rotation_limit, math.pi),
                )
            if abs(float(delta.angle)) > 1.0e-7:
                add_arc_lines(
                    direction_lines,
                    old_position,
                    axis_a,
                    axis_b,
                    arc_radius * 0.76,
                    0.0,
                    min(abs(float(delta.angle)), math.pi),
                )
        _batch(batches, threshold_lines, "teleport_threshold", 0.8)
        _batch(batches, direction_lines, "teleport_direction", 1.0)

    if filters.get("show_teleport_status", False):
        status_payload = teleport.get("status") or {}
        positions = np.asarray(
            _values(status_payload.get("positions")), dtype=np.float32
        ).reshape((-1, 3))
        status = np.asarray(
            _values(status_payload.get("status")), dtype=np.uint8
        ).reshape((-1,))
        count = min(len(positions), len(status), limit)
        normal_points = []
        keep_points = []
        reset_points = []
        for index in range(count):
            target = (
                reset_points
                if int(status[index]) == 1
                else keep_points
                if int(status[index]) == 2
                else normal_points
            )
            add_point(target, positions[index])
        _point_batch(point_batches, normal_points, "teleport_measure", 6.0)
        _point_batch(point_batches, keep_points, "teleport_keep", 9.0)
        _point_batch(point_batches, reset_points, "teleport_reset", 9.0)


def _append_center_batches(batches, point_batches, center):
    frame_pose = center.get("frame_pose") or {}
    shift = center.get("frame_shift") or {}
    step = center.get("step") or {}
    negative = center.get("negative_scale_transition") or {}
    center_lines = []
    anchor_lines = []
    frame_lines = []
    shift_lines = []
    raw_lines = []
    anchor_shift_lines = []
    smoothing_lines = []
    world_shift_lines = []
    limited_lines = []
    step_lines = []
    inertia_lines = []
    teleport_threshold_lines = []
    teleport_measure_lines = []
    teleport_keep_lines = []
    teleport_reset_lines = []
    center_points = []
    anchor_points = []
    old_points = []
    now_points = []
    negative_points = []
    teleport_measure_points = []
    teleport_keep_points = []
    teleport_reset_points = []
    position = frame_pose.get("component_world_position")
    anchor = frame_pose.get("anchor_world_position")
    if position is not None:
        add_point(center_points, position)
        rotation = frame_pose.get("component_world_rotation_xyzw")
        if rotation is not None and len(rotation) == 4:
            add_basis_lines(
                center_lines,
                position,
                (rotation[3], rotation[0], rotation[1], rotation[2]),
                0.12,
            )
    if anchor is not None and frame_pose.get("anchor_identity"):
        add_point(anchor_points, anchor)
        if position is not None:
            add_line(anchor_lines, position, anchor)
    old_position = shift.get("old_frame_world_position")
    now_position = shift.get("now_world_position") or step.get("now_world_position")
    if old_position is not None and now_position is not None:
        add_arrow_lines(frame_lines, old_position, now_position)
        add_point(old_points, old_position)
        add_point(now_points, now_position)
    shift_vector = shift.get("frame_component_shift_vector")
    shift_origin = shift.get("teleport_origin_world_position") or position
    if shift_origin is not None and shift_vector is not None:
        add_arrow_lines(
            shift_lines,
            shift_origin,
            vector3(shift_origin) + vector3(shift_vector),
        )
        for field, target in (
            ("raw_component_delta", raw_lines),
            ("anchor_shift_vector", anchor_shift_lines),
            ("smoothing_shift_vector", smoothing_lines),
            ("world_shift_vector", world_shift_lines),
        ):
            value = shift.get(field)
            if value is not None and vector3(value).length > 1.0e-8:
                add_arrow_lines(
                    target,
                    shift_origin,
                    vector3(shift_origin) + vector3(value),
                )
        if bool(shift.get("movement_speed_limited")):
            add_arrow_lines(
                limited_lines,
                shift_origin,
                vector3(shift_origin) + vector3(shift_vector),
            )
    step_now = step.get("now_world_position")
    step_vector = step.get("step_vector")
    inertia_vector = step.get("inertia_vector")
    if step_now is not None and step_vector is not None:
        step_start = vector3(step_now) - vector3(step_vector)
        add_arrow_lines(step_lines, step_start, step_now)
        if inertia_vector is not None:
            add_arrow_lines(
                inertia_lines,
                step_start,
                step_start + vector3(inertia_vector),
            )
    teleport_mode = int(shift.get("teleport_mode", 0) or 0)
    teleport_origin = shift.get("teleport_origin_world_position")
    teleport_target = shift.get("teleport_target_world_position")
    if teleport_mode in (1, 2) and teleport_origin is not None and teleport_target is not None:
        threshold = max(float(shift.get("teleport_distance_threshold", 0.0) or 0.0), 0.0)
        measured_distance = max(float(shift.get("teleport_measured_distance", 0.0) or 0.0), 0.0)
        measured_rotation = max(float(shift.get("teleport_measured_rotation_degrees", 0.0) or 0.0), 0.0)
        rotation_threshold = max(float(shift.get("teleport_rotation_threshold_degrees", 0.0) or 0.0), 0.0)
        _add_axis_sphere(teleport_threshold_lines, teleport_origin, threshold)
        triggered = bool(shift.get("teleport_triggered"))
        if bool(shift.get("reset_teleport")):
            result_lines = teleport_reset_lines
            result_points = teleport_reset_points
        elif bool(shift.get("keep_teleport")):
            result_lines = teleport_keep_lines
            result_points = teleport_keep_points
        else:
            result_lines = teleport_measure_lines
            result_points = teleport_measure_points
        add_arrow_lines(result_lines, teleport_origin, teleport_target)
        add_point(result_points, teleport_target)
        axis = vector3(shift.get("teleport_rotation_axis"), (0.0, 0.0, 1.0))
        if axis.length <= 1.0e-8:
            axis = mathutils.Vector((0.0, 0.0, 1.0))
        else:
            axis.normalize()
        axis_a, axis_b = _plane_axes(axis)
        arc_radius = max(min(max(threshold, measured_distance) * 0.28, 0.5), 0.08)
        add_arc_lines(
            teleport_threshold_lines,
            teleport_origin,
            axis_a,
            axis_b,
            arc_radius,
            0.0,
            math.radians(min(rotation_threshold, 180.0)),
        )
        add_arc_lines(
            result_lines,
            teleport_origin,
            axis_a,
            axis_b,
            arc_radius * 0.78,
            0.0,
            math.radians(min(measured_rotation, 180.0)),
        )
        if triggered and measured_distance <= 1.0e-8 and measured_rotation <= 1.0e-8:
            add_point(result_points, teleport_origin)
    if bool(negative.get("active")):
        target = negative.get("old_component_world_position") or position
        if target is not None:
            add_point(negative_points, target)
    _batch(batches, center_lines, "center", 1.4)
    _batch(batches, anchor_lines, "center_anchor", 1.4)
    _batch(batches, frame_lines, "center_now", 1.2)
    _batch(batches, shift_lines, "shift", 1.8)
    _batch(batches, raw_lines, "center_raw", 1.0)
    _batch(batches, anchor_shift_lines, "center_anchor_shift", 1.4)
    _batch(batches, smoothing_lines, "center_smoothing", 1.4)
    _batch(batches, world_shift_lines, "center_world_shift", 1.8)
    _batch(batches, limited_lines, "center_limited", 2.6)
    _batch(batches, step_lines, "center_step", 1.5)
    _batch(batches, inertia_lines, "center_inertia", 1.5)
    _batch(batches, teleport_threshold_lines, "teleport_threshold", 1.2)
    _batch(batches, teleport_measure_lines, "teleport_measure", 1.8)
    _batch(batches, teleport_keep_lines, "teleport_keep", 2.2)
    _batch(batches, teleport_reset_lines, "teleport_reset", 2.2)
    _point_batch(point_batches, center_points, "center", 11.0)
    _point_batch(point_batches, anchor_points, "center_anchor", 9.0)
    _point_batch(point_batches, old_points, "center_old", 7.0)
    _point_batch(point_batches, now_points, "center_now", 9.0)
    _point_batch(point_batches, negative_points, "negative", 13.0)
    _point_batch(point_batches, teleport_measure_points, "teleport_measure", 7.0)
    _point_batch(point_batches, teleport_keep_points, "teleport_keep", 10.0)
    _point_batch(point_batches, teleport_reset_points, "teleport_reset", 10.0)


def _append_collider_batches(
    batches,
    triangle_meshes,
    collision,
    limit,
    *,
    active_indices=(),
    only_active=False,
):
    colliders = collision.get("colliders")
    if not isinstance(colliders, dict):
        return
    lines = []
    active_lines = []
    active_indices = {int(value) for value in active_indices}
    types = np.asarray(_values(colliders.get("types")), dtype=np.int32)
    group_bits = np.asarray(_values(colliders.get("group_bits")), dtype=np.int32)
    collided_by_groups = int(colliders.get("collided_by_groups", 0) or 0)
    centers = np.asarray(_values(colliders.get("centers")), dtype=np.float32).reshape((-1, 3))
    segment_a = np.asarray(_values(colliders.get("segment_a")), dtype=np.float32).reshape((-1, 3))
    segment_b = np.asarray(_values(colliders.get("segment_b")), dtype=np.float32).reshape((-1, 3))
    radii = np.asarray(_values(colliders.get("radii")), dtype=np.float32)
    for collider_index, (kind, group_bit, center, first, second, radius) in enumerate(zip(
        types[:limit], group_bits, centers, segment_a, segment_b, radii
    )):
        if not (collided_by_groups & int(group_bit)):
            continue
        active = collider_index in active_indices
        if only_active and not active:
            continue
        mesh = _triangle_mesh(
            triangle_meshes,
            "active_collider_surface" if active else "collider_surface",
        )
        target_lines = active_lines if active else lines
        kind = int(kind)
        radius = float(radius)
        if kind == 0:
            add_sphere_triangles(
                mesh["vertices"], mesh["indices"], center, radius
            )
        elif kind == 1:
            add_tapered_capsule_triangles(
                mesh["vertices"],
                mesh["indices"],
                first,
                second,
                radius,
                radius,
            )
            add_line(target_lines, first, second)
        elif kind == 2:
            axis_x, axis_y = _plane_axes(first)
            add_plane_triangles(
                mesh["vertices"], mesh["indices"], center, axis_x, axis_y
            )
            normal = vector3(first)
            if normal.length > 1.0e-8:
                normal.normalize()
                add_arrow_lines(
                    target_lines, center, vector3(center) + normal * 0.35
                )
        elif kind == 3:
            cross = vector3(first).cross(vector3(second))
            if cross.length > 1.0e-8:
                cross.normalize()
                add_box_triangles(
                    mesh["vertices"],
                    mesh["indices"],
                    center,
                    first,
                    second,
                    cross * radius,
                )
    _batch(batches, lines, "collider", 1.0)
    _batch(batches, active_lines, "external_contact", 1.5)


def _append_external_contact_batches(
    batches,
    point_batches,
    triangle_meshes,
    snapshot,
    topology,
    positions,
    limit,
):
    native = snapshot.get("native") or {}
    contacts = native.get("external_contacts")
    collision = snapshot.get("collision") or {}
    if not isinstance(contacts, dict):
        return
    kinds = np.asarray(
        _values(contacts.get("primitive_kinds")), dtype=np.int32
    ).reshape((-1,))
    primitive_indices = np.asarray(
        _values(contacts.get("primitive_indices")), dtype=np.int32
    ).reshape((-1,))
    collider_indices = np.asarray(
        _values(contacts.get("collider_indices")), dtype=np.int32
    ).reshape((-1,))
    contact_positions = np.asarray(
        _values(contacts.get("positions")), dtype=np.float32
    ).reshape((-1, 3))
    normals = np.asarray(
        _values(contacts.get("normals")), dtype=np.float32
    ).reshape((-1, 3))
    corrections = np.asarray(
        _values(contacts.get("corrections")), dtype=np.float32
    ).reshape((-1, 3))
    temporal_states = np.asarray(
        _values(contacts.get("temporal_states")), dtype=np.uint8
    ).reshape((-1,))
    count = min(
        limit,
        len(kinds),
        len(primitive_indices),
        len(collider_indices),
        len(contact_positions),
        len(normals),
        len(corrections),
    )
    if count <= 0:
        return
    active_colliders = set(map(int, collider_indices[:count]))
    _append_collider_batches(
        batches,
        triangle_meshes,
        collision,
        limit,
        active_indices=active_colliders,
        only_active=True,
    )
    _append_external_contact_primitive_surfaces(
        triangle_meshes,
        kinds[:count],
        primitive_indices[:count],
        topology,
        positions,
        collision,
    )
    points = []
    new_points = []
    lost_points = []
    correction_lines = []
    for index, (contact, correction) in enumerate(zip(
        contact_positions[:count],
        corrections[:count],
    )):
        is_new = index < len(temporal_states) and temporal_states[index] == 1
        target_points = new_points if is_new else points
        add_point(target_points, contact)
        correction_vector = vector3(correction)
        if correction_vector.length > 1.0e-8:
            add_arrow_lines(
                correction_lines,
                contact,
                vector3(contact)
                + correction_vector * _CONTACT_CORRECTION_DISPLAY_SCALE,
            )
    lost_positions = np.asarray(
        _values(contacts.get("lost_positions")), dtype=np.float32
    ).reshape((-1, 3))
    for contact in lost_positions[:limit]:
        add_point(lost_points, contact)
    _point_batch(point_batches, points, "external_contact_point", 5.0)
    _point_batch(point_batches, new_points, "external_contact_new", 6.0)
    _point_batch(point_batches, lost_points, "external_contact_lost", 5.0)
    _batch(batches, correction_lines, "external_contact_correction", 2.2)


def _append_external_contact_primitive_surfaces(
    triangle_meshes,
    kinds,
    primitive_indices,
    topology,
    positions,
    collision,
):
    """Draw only cloth collision shapes that produced a real external contact."""
    radii = np.asarray(
        _values(collision.get("particle_radii")), dtype=np.float32
    ).reshape((-1,))
    edges = np.asarray(
        _values(topology.get("edges")), dtype=np.int32
    ).reshape((-1, 2))
    point_mesh = _triangle_mesh(triangle_meshes, "active_point_contact_surface")
    edge_mesh = _triangle_mesh(triangle_meshes, "active_edge_contact_surface")
    seen = set()
    for kind, primitive in zip(kinds, primitive_indices):
        kind = int(kind)
        primitive = int(primitive)
        identity = (kind, primitive)
        if identity in seen:
            continue
        seen.add(identity)
        if kind == 0:
            if not (0 <= primitive < min(len(positions), len(radii))):
                continue
            radius = max(float(radii[primitive]), 0.0)
            add_sphere_triangles(
                point_mesh["vertices"],
                point_mesh["indices"],
                positions[primitive],
                radius,
            )
        elif kind == 1:
            if not 0 <= primitive < len(edges):
                continue
            left, right = map(int, edges[primitive])
            if min(left, right) < 0 or max(left, right) >= min(
                len(positions), len(radii)
            ):
                continue
            add_tapered_capsule_triangles(
                edge_mesh["vertices"],
                edge_mesh["indices"],
                positions[left],
                positions[right],
                max(float(radii[left]), 0.0),
                max(float(radii[right]), 0.0),
            )


def _append_radius_batches(batches, snapshot, limit):
    collision = snapshot.get("collision") or {}
    positions = np.asarray(_values((snapshot.get("native") or {}).get("positions")), dtype=np.float32).reshape((-1, 3))
    radii = np.asarray(_values(collision.get("particle_radii")), dtype=np.float32)
    lines = []
    for center, radius in zip(positions[:limit], radii[:limit]):
        _add_axis_sphere(lines, center, float(radius))
    _batch(batches, lines, "radius")
    self_state = snapshot.get("self_collision") or {}
    thickness = np.asarray(_values(self_state.get("thickness")), dtype=np.float32)
    indices = np.asarray(_values(self_state.get("particle_indices")), dtype=np.int32).reshape((-1, 3))
    lines = []
    for primitive, radius in zip(indices[:limit], thickness[:limit]):
        center = _primitive_center(positions, primitive)
        if center is not None:
            _add_axis_sphere(lines, center, float(radius))
    _batch(batches, lines, "self_radius")


def _append_self_batches(
    batches, point_batches, native_snapshot, filters, *, interaction
):
    state = native_snapshot if interaction else native_snapshot.get("self_collision")
    if not isinstance(state, dict) or state.get("positions") is None and interaction:
        return
    positions = np.asarray(_values(native_snapshot.get("positions")), dtype=np.float32).reshape((-1, 3))
    indices = np.asarray(_values(state.get("particle_indices")), dtype=np.int32).reshape((-1, 3))
    info = native_snapshot.get("native") or {}
    prefix = "" if interaction else "self_"
    point_count = int(info.get(f"{prefix}point_primitive_count", 0) or 0)
    edge_count = int(info.get(f"{prefix}edge_primitive_count", 0) or 0)
    limit = filters["max_items"]
    visible_primitives = np.ones((len(indices),), dtype=bool)
    visible_particles = np.ones((len(positions),), dtype=bool)
    task_filters = normalize_mc2_task_filters(filters.get("task_filter"))
    if interaction and task_filters:
        participants = tuple(native_snapshot.get("participants") or ())
        allowed_owners = {
            index
            for index, participant in enumerate(participants)
            if any(
                token in str(participant.get("task_id") or "")
                for token in task_filters
            )
        }
        owners = np.asarray(_values(state.get("owner_indices")), dtype=np.int32)
        visible_primitives = np.asarray(
            [int(owner) in allowed_owners for owner in owners], dtype=bool
        )
        visible_particles[:] = False
        offset = 0
        for owner, participant in enumerate(participants):
            count = int(participant.get("vertex_count", 0) or 0)
            if owner in allowed_owners:
                visible_particles[offset:offset + count] = True
            offset += count
    if filters["show_self_primitives"]:
        lines = []
        points = []
        for primitive_index, primitive in enumerate(indices[:limit]):
            if primitive_index >= len(visible_primitives) or not visible_primitives[primitive_index]:
                continue
            if primitive_index < point_count:
                center = _primitive_center(positions, primitive)
                if center is not None:
                    add_point(points, center)
            elif primitive_index < point_count + edge_count:
                _add_index_line(lines, positions, primitive[:2])
            else:
                _add_index_loop(lines, positions, primitive)
        _batch(batches, lines, "primitive", 1.5)
        _point_batch(point_batches, points, "primitive", 6.0)
    if filters["show_self_grid"]:
        lines = []
        grid_size = float(info.get("grid_size" if interaction else "self_grid_size", 0.0) or 0.0)
        grids = np.asarray(_values(state.get("primitive_grids")), dtype=np.int32).reshape((-1, 3))
        seen = set()
        for primitive_index, grid in enumerate(grids):
            if primitive_index >= len(visible_primitives) or not visible_primitives[primitive_index]:
                continue
            key = tuple(map(int, grid))
            if key in seen or max(map(abs, key)) >= 1000000 or len(seen) >= limit:
                continue
            seen.add(key)
            half = grid_size * 0.5
            center = (np.asarray(grid, dtype=np.float32) + 0.5) * grid_size
            add_box_lines(
                lines,
                vector3(center),
                mathutils.Vector((half, 0, 0)),
                mathutils.Vector((0, half, 0)),
                mathutils.Vector((0, 0, half)),
            )
        _batch(batches, lines, "grid")
    centers = [_primitive_center(positions, primitive) for primitive in indices]
    if filters["show_self_candidates"]:
        lines = []
        for first, second, _kind in np.asarray(_values(state.get("candidates")), dtype=np.int32).reshape((-1, 3))[:limit]:
            if not _primitive_pair_visible(visible_primitives, first, second):
                continue
            _add_center_line(lines, centers, int(first), int(second))
        _batch(batches, lines, "candidate")
    if filters["show_self_contacts"]:
        enabled_lines = []
        new_contact_lines = []
        lost_contact_lines = []
        disabled_lines = []
        contacts = np.asarray(_values(state.get("contact_indices")), dtype=np.int32).reshape((-1, 2))
        enabled = np.asarray(_values(state.get("contact_enabled")), dtype=np.uint8)
        temporal_states = np.asarray(
            _values(state.get("contact_temporal_states")), dtype=np.uint8
        ).reshape((-1,))
        corrections = np.asarray(
            _values(state.get("contact_corrections")), dtype=np.float32
        ).reshape((-1, 2, 3))
        correction_lines = []
        for index, (first, second) in enumerate(contacts[:limit]):
            if not _primitive_pair_visible(visible_primitives, first, second):
                continue
            if index >= len(enabled) or not enabled[index]:
                target = disabled_lines
            elif index < len(temporal_states) and temporal_states[index] == 1:
                target = new_contact_lines
            else:
                target = enabled_lines
            _add_center_line(target, centers, int(first), int(second))
            if index >= len(enabled) or not enabled[index]:
                continue
            if index < len(corrections):
                for side, primitive in enumerate((int(first), int(second))):
                    if not (0 <= primitive < len(centers)) or centers[primitive] is None:
                        continue
                    correction = vector3(corrections[index, side])
                    if correction.length > 1.0e-8:
                        add_arrow_lines(
                            correction_lines,
                            centers[primitive],
                            vector3(centers[primitive])
                            + correction * _CONTACT_CORRECTION_DISPLAY_SCALE,
                        )
        lost_contact_indices = np.asarray(
            _values(state.get("lost_contact_indices")), dtype=np.int32
        ).reshape((-1, 2))
        lost_contact_positions = np.asarray(
            _values(state.get("lost_contact_positions")), dtype=np.float32
        ).reshape((-1, 2, 3))
        for pair, pair_positions in zip(
            lost_contact_indices[:limit], lost_contact_positions[:limit]
        ):
            if _primitive_pair_visible(
                visible_primitives, int(pair[0]), int(pair[1])
            ):
                add_line(lost_contact_lines, pair_positions[0], pair_positions[1])
        intersections = []
        new_intersections = []
        lost_intersections = []
        intersection_states = np.asarray(
            _values(state.get("intersection_temporal_states")), dtype=np.uint8
        ).reshape((-1,))
        for index, record in enumerate(np.asarray(
            _values(state.get("intersect_records")), dtype=np.int32
        ).reshape((-1, 5))[:limit]):
            if not any(
                0 <= int(particle) < len(visible_particles)
                and visible_particles[int(particle)]
                for particle in record
            ):
                continue
            target = (
                new_intersections
                if index < len(intersection_states)
                and intersection_states[index] == 1
                else intersections
            )
            _add_index_line(target, positions, record[:2])
            _add_index_loop(target, positions, record[2:])
        lost_intersect_records = np.asarray(
            _values(state.get("lost_intersect_records")), dtype=np.int32
        ).reshape((-1, 5))
        lost_intersect_positions = np.asarray(
            _values(state.get("lost_intersect_positions")), dtype=np.float32
        ).reshape((-1, 5, 3))
        for record, record_positions in zip(
            lost_intersect_records[:limit], lost_intersect_positions[:limit]
        ):
            if not any(
                0 <= int(particle) < len(visible_particles)
                and visible_particles[int(particle)]
                for particle in record
            ):
                continue
            add_line(lost_intersections, record_positions[0], record_positions[1])
            for first, second in zip(
                record_positions[2:],
                (*record_positions[3:], record_positions[2]),
            ):
                add_line(lost_intersections, first, second)
        _batch(batches, enabled_lines, "contact", 0.8)
        _batch(batches, new_contact_lines, "contact_new", 1.2)
        _batch(batches, lost_contact_lines, "contact_lost", 0.8)
        _batch(batches, disabled_lines, "disabled_contact")
        _batch(batches, correction_lines, "contact_correction", 2.2)
        _batch(batches, intersections, "intersection", 2.6)
        _batch(batches, new_intersections, "intersection_new", 2.8)
        _batch(batches, lost_intersections, "intersection_lost", 1.6)


def _append_interaction_contact_batches(batches, state, filters):
    positions = np.asarray(
        _values(state.get("positions")), dtype=np.float32
    ).reshape((-1, 3))
    primitives = np.asarray(
        _values(state.get("particle_indices")), dtype=np.int32
    ).reshape((-1, 3))
    owners = np.asarray(
        _values(state.get("owner_indices")), dtype=np.int32
    ).reshape((-1,))
    contacts = np.asarray(
        _values(state.get("contact_indices")), dtype=np.int32
    ).reshape((-1, 2))
    enabled = np.asarray(
        _values(state.get("contact_enabled")), dtype=np.uint8
    ).reshape((-1,))
    corrections = np.asarray(
        _values(state.get("contact_corrections")), dtype=np.float32
    ).reshape((-1, 2, 3))
    if not len(contacts) or len(owners) != len(primitives):
        return
    participants = tuple(state.get("participants") or ())
    task_filters = normalize_mc2_task_filters(filters.get("task_filter"))
    allowed_owners = None
    if task_filters:
        allowed_owners = {
            index
            for index, participant in enumerate(participants)
            if any(
                token in str(participant.get("task_id") or "")
                for token in task_filters
            )
        }
    centers = [_primitive_center(positions, primitive) for primitive in primitives]
    contact_lines = []
    correction_lines = []
    for index, (first, second) in enumerate(contacts[:filters["max_items"]]):
        first = int(first)
        second = int(second)
        if (
            index >= len(enabled)
            or not enabled[index]
            or not (0 <= first < len(owners) and 0 <= second < len(owners))
            or int(owners[first]) == int(owners[second])
        ):
            continue
        if allowed_owners is not None and not (
            int(owners[first]) in allowed_owners
            or int(owners[second]) in allowed_owners
        ):
            continue
        _add_center_line(contact_lines, centers, first, second)
        if index < len(corrections):
            for side, primitive in enumerate((first, second)):
                if centers[primitive] is None:
                    continue
                correction = vector3(corrections[index, side])
                if correction.length > 1.0e-8:
                    add_arrow_lines(
                        correction_lines,
                        centers[primitive],
                        vector3(centers[primitive])
                        + correction * _CONTACT_CORRECTION_DISPLAY_SCALE,
                    )
    _batch(batches, contact_lines, "cross_task_contact", 0.8)
    _batch(batches, correction_lines, "contact_correction", 2.2)


def _append_output_batches(batches, point_batches, snapshot, limit):
    output = snapshot.get("output") or {}
    base = output.get("base_positions")
    target = output.get("target_positions")
    if base is None or target is None:
        return
    base = np.asarray(base, dtype=np.float32).reshape((-1, 3))
    target = np.asarray(target, dtype=np.float32).reshape((-1, 3))
    applied = np.asarray(
        _values(output.get("translation_applied")), dtype=np.uint8
    )
    lines = []
    points = []
    for index, (start, end) in enumerate(zip(base[:limit], target[:limit])):
        if len(applied) and (index >= len(applied) or not applied[index]):
            continue
        add_arrow_lines(lines, start, end)
        add_point(points, end)
    _batch(batches, lines, "output", 1.4)
    _point_batch(point_batches, points, "output", 5.0)


def _motion_axes(positions, rotations, normal_axis):
    axis_values = ((1, 0, 0), (0, 1, 0), (0, 0, 1), (-1, 0, 0), (0, -1, 0), (0, 0, -1))
    local = mathutils.Vector(axis_values[max(0, min(5, normal_axis))])
    result = []
    for rotation in rotations[:len(positions)]:
        quaternion = mathutils.Quaternion((rotation[3], rotation[0], rotation[1], rotation[2]))
        result.append(tuple(quaternion @ local))
    return np.asarray(result, dtype=np.float32)


def _primitive_center(positions, primitive):
    valid = [int(index) for index in primitive if 0 <= int(index) < len(positions)]
    if not valid:
        return None
    return np.mean(positions[valid], axis=0)


def _add_index_line(lines, positions, indices):
    if len(indices) >= 2 and all(0 <= int(index) < len(positions) for index in indices[:2]):
        add_line(lines, positions[int(indices[0])], positions[int(indices[1])])


def _add_index_loop(lines, positions, indices):
    valid = [int(index) for index in indices if 0 <= int(index) < len(positions)]
    if len(valid) < 2:
        return
    for index, current in enumerate(valid):
        add_line(lines, positions[current], positions[valid[(index + 1) % len(valid)]])


def _add_center_line(lines, centers, first, second):
    if 0 <= first < len(centers) and 0 <= second < len(centers):
        if centers[first] is not None and centers[second] is not None:
            add_line(lines, centers[first], centers[second])


def _primitive_pair_visible(visible, first, second):
    return any(
        0 <= int(index) < len(visible) and visible[int(index)]
        for index in (first, second)
    )


def _add_axis_sphere(lines, center, radius):
    radius = max(float(radius), 0.0)
    if radius <= 1.0e-8:
        return
    add_sphere_lines(
        lines,
        center,
        mathutils.Vector((1, 0, 0)),
        mathutils.Vector((0, 1, 0)),
        mathutils.Vector((0, 0, 1)),
        radius,
    )


def _plane_axes(normal):
    normal = vector3(normal)
    if normal.length <= 1.0e-8:
        return mathutils.Vector((1, 0, 0)), mathutils.Vector((0, 1, 0))
    normal.normalize()
    reference = mathutils.Vector((0, 0, 1))
    if abs(normal.dot(reference)) > 0.9:
        reference = mathutils.Vector((1, 0, 0))
    axis_x = reference.cross(normal).normalized()
    return axis_x, normal.cross(axis_x).normalized()


def _ensure_draw_handler():
    global _MC2_DRAW_HANDLE
    if _MC2_DRAW_HANDLE is None:
        _MC2_DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
            _draw_mc2_debug, (), "WINDOW", "POST_VIEW"
        )


def _remove_draw_handler():
    global _MC2_DRAW_HANDLE
    if _MC2_DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_MC2_DRAW_HANDLE, "WINDOW")
        except Exception:
            pass
        _MC2_DRAW_HANDLE = None


def _draw_mc2_debug():
    for item in list(_MC2_DRAW_STORE.values()):
        draw_triangle_batches(item.get("triangle_batches") or ())
        draw_point_batches(item.get("point_batches") or ())
        draw_line_batches(item.get("batches") or ())


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
    "clear_mc2_debug_draw_store",
    "mc2_debug_draw_store_snapshot",
    "update_mc2_debug_draw_store",
]
