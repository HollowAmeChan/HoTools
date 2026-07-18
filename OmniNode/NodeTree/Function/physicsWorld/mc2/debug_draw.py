"""Implicit MC2 viewport debug drawing from frozen solver snapshots only."""

from __future__ import annotations

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
    vector3,
)
from .debug import normalize_mc2_task_filters, request_mc2_debug_capture
from .native_context import MC2_INTERACTION_RESOURCE_KEY, MC2NativeInteractionV0
from .names import MC2_SLOT_KIND


_COLORS = {
    "longitudinal": (0.95, 0.70, 0.18, 0.95),
    "lateral": (0.20, 0.85, 0.95, 0.95),
    "triangle": (0.38, 0.62, 0.82, 0.50),
    "fixed": (0.95, 0.25, 0.20, 0.95),
    "move": (0.25, 0.95, 0.40, 0.85),
    "motion_base": (0.20, 0.85, 1.00, 0.90),
    "angle_target": (1.00, 0.32, 0.72, 0.95),
    "max_distance": (0.30, 0.75, 1.00, 0.36),
    "backstop": (1.00, 0.40, 0.22, 0.55),
    "center": (1.00, 0.92, 0.25, 0.95),
    "shift": (0.98, 0.45, 0.15, 0.95),
    "negative": (0.95, 0.20, 0.70, 0.95),
    "collider": (0.72, 0.75, 0.82, 0.65),
    "radius": (0.32, 0.92, 0.72, 0.38),
    "self_radius": (0.94, 0.52, 0.92, 0.42),
    "primitive": (0.75, 0.42, 0.98, 0.72),
    "grid": (0.45, 0.50, 0.58, 0.25),
    "candidate": (0.95, 0.72, 0.25, 0.35),
    "contact": (1.00, 0.15, 0.12, 0.95),
    "disabled_contact": (0.55, 0.55, 0.60, 0.38),
    "intersection": (1.00, 0.05, 0.72, 1.00),
    "output": (0.30, 1.00, 0.82, 0.85),
}

_MC2_DRAW_STORE: dict[str, dict] = {}
_MC2_DRAW_HANDLE = None


def _values(value):
    return () if value is None else value


def update_mc2_debug_draw_store(
    node_uid: str,
    world,
    enabled: bool,
    *,
    show_topology: bool = True,
    show_attributes: bool = True,
    show_motion: bool = True,
    show_center: bool = True,
    show_collision: bool = True,
    show_radii: bool = True,
    show_self_primitives: bool = False,
    show_self_grid: bool = False,
    show_self_candidates: bool = False,
    show_self_contacts: bool = True,
    show_output: bool = True,
    task_filter: str = "",
    max_items: int = 2000,
    show_motion_base: bool = True,
    show_angle_restoration: bool = True,
) -> None:
    node_key = str(node_uid)
    if not enabled or not isinstance(world, PhysicsWorldCache):
        clear_mc2_debug_draw_store(node_uid=node_key)
        return

    filters = {
        "show_topology": bool(show_topology),
        "show_attributes": bool(show_attributes),
        "show_motion": bool(show_motion),
        "show_motion_base": bool(show_motion_base),
        "show_angle_restoration": bool(show_angle_restoration),
        "show_center": bool(show_center),
        "show_collision": bool(show_collision),
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
    batches, point_batches = _build_world_batches(world, filters)
    _MC2_DRAW_STORE[node_key] = {
        "world_id": str(id(world)),
        "frame": int(getattr(world.frame_context, "frame", 0) or 0),
        "batches": batches,
        "point_batches": point_batches,
    }
    _ensure_draw_handler()
    _tag_view3d_redraw()


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
    flattened = [
        coordinate
        for specs in (line_batches, point_batches)
        for batch in specs
        for point in batch[0]
        for coordinate in point
    ]
    return {
        "world_id": item["world_id"],
        "frame": item["frame"],
        "batch_count": len(line_batches) + len(point_batches),
        "line_vertex_count": sum(len(batch[0]) for batch in line_batches),
        "point_vertex_count": sum(len(batch[0]) for batch in point_batches),
        "coordinate_checksum": round(
            sum((index + 1) * float(value) for index, value in enumerate(flattened)),
            6,
        ),
    }


def _build_world_batches(world: PhysicsWorldCache, filters: dict) -> tuple[list, list]:
    batches = []
    point_batches = []
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
        _append_slot_batches(batches, point_batches, snapshot, filters)

    interaction = world.backend_resources.get(MC2_INTERACTION_RESOURCE_KEY)
    if isinstance(interaction, MC2NativeInteractionV0):
        snapshot = interaction.debug_draw_snapshot()
        if isinstance(snapshot, dict):
            _append_self_batches(
                batches, point_batches, snapshot, filters, interaction=True
            )
    return batches, point_batches


def _batch(batches: list, lines: list, color_name: str, width: float = 1.0) -> None:
    if lines:
        batches.append((lines, _COLORS[color_name], width))


def _point_batch(
    batches: list, points: list, color_name: str, size: float = 5.0
) -> None:
    if points:
        batches.append((points, _COLORS[color_name], size))


def _append_slot_batches(
    batches: list, point_batches: list, snapshot: dict, filters: dict
) -> None:
    limit = filters["max_items"]
    topology = snapshot.get("topology") or {}
    positions = np.asarray(_values(topology.get("positions")), dtype=np.float32).reshape((-1, 3))
    if filters["show_topology"]:
        _append_topology_batches(batches, topology, positions, limit)
    if filters["show_attributes"]:
        _append_attribute_batches(point_batches, topology, positions, limit)
    if filters["show_motion_base"]:
        _append_motion_base_batches(
            batches, point_batches, snapshot.get("motion") or {}, limit
        )
    if filters["show_motion"]:
        _append_motion_batches(batches, snapshot.get("motion") or {}, limit)
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
    if filters["show_center"]:
        _append_center_batches(batches, point_batches, snapshot.get("center") or {})
    if filters["show_collision"]:
        _append_collider_batches(batches, snapshot.get("collision") or {}, limit)
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
    long_edges = np.asarray(_values(topology.get("longitudinal_edges")), dtype=np.int32).reshape((-1, 2))
    lateral_edges = np.asarray(_values(topology.get("lateral_edges")), dtype=np.int32).reshape((-1, 2))
    classified = {tuple(sorted(map(int, edge))) for edge in np.vstack((long_edges, lateral_edges))} if len(long_edges) + len(lateral_edges) else set()
    all_edges = np.asarray(_values(topology.get("edges")), dtype=np.int32).reshape((-1, 2))
    for edge in long_edges[:limit]:
        _add_index_line(longitudinal, positions, edge)
    for edge in lateral_edges[:limit]:
        _add_index_line(lateral, positions, edge)
    for edge in all_edges[:limit]:
        if tuple(sorted(map(int, edge))) not in classified:
            _add_index_line(longitudinal, positions, edge)
    for triangle in np.asarray(_values(topology.get("triangles")), dtype=np.int32).reshape((-1, 3))[:limit]:
        _add_index_loop(triangles, positions, triangle)
    _batch(batches, longitudinal, "longitudinal", 2.0)
    _batch(batches, lateral, "lateral", 2.4)
    _batch(batches, triangles, "triangle", 1.0)


def _append_attribute_batches(point_batches, topology, positions, limit):
    fixed = []
    move = []
    attributes = np.asarray(_values(topology.get("vertex_attributes")), dtype=np.uint8)
    for index, attribute in enumerate(attributes[:limit]):
        target = move if int(attribute) & 0x02 else fixed
        add_point(target, positions[index])
    _point_batch(point_batches, fixed, "fixed", 8.0)
    _point_batch(point_batches, move, "move", 5.0)


def _append_motion_batches(batches, motion, limit):
    base = motion.get("motion_base_positions")
    rotations = motion.get("motion_base_rotations_xyzw")
    if base is None or rotations is None:
        return
    base = np.asarray(base, dtype=np.float32).reshape((-1, 3))
    rotations = np.asarray(rotations, dtype=np.float32).reshape((-1, 4))
    axes = _motion_axes(base, rotations, int(motion.get("normal_axis", 1)))
    if bool(motion.get("use_max_distance")):
        lines = []
        for center, radius in zip(base[:limit], np.asarray(_values(motion.get("max_distances")))[:limit]):
            _add_axis_sphere(lines, center, float(radius))
        _batch(batches, lines, "max_distance")
    if bool(motion.get("use_backstop")):
        lines = []
        radius = max(float(motion.get("backstop_radius", 0.0) or 0.0), 0.0)
        distances = np.asarray(_values(motion.get("backstop_distances")))
        for center, axis, distance in zip(base[:limit], axes[:limit], distances[:limit]):
            backstop_center = center - axis * (float(distance) + radius)
            _add_axis_sphere(lines, backstop_center, radius)
            add_line(lines, center, backstop_center)
        _batch(batches, lines, "backstop", 1.4)


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


def _append_center_batches(batches, point_batches, center):
    frame_pose = center.get("frame_pose") or {}
    shift = center.get("frame_shift") or {}
    step = center.get("step") or {}
    negative = center.get("negative_scale_transition") or {}
    center_lines = []
    shift_lines = []
    center_points = []
    anchor_points = []
    old_points = []
    now_points = []
    negative_points = []
    position = frame_pose.get("component_world_position")
    anchor = frame_pose.get("anchor_world_position")
    if position is not None:
        add_point(center_points, position)
    if anchor is not None and frame_pose.get("anchor_identity"):
        add_point(anchor_points, anchor)
        if position is not None:
            add_line(center_lines, position, anchor)
    old_position = shift.get("old_frame_world_position")
    now_position = shift.get("now_world_position") or step.get("now_world_position")
    if old_position is not None and now_position is not None:
        add_arrow_lines(shift_lines, old_position, now_position)
        add_point(old_points, old_position)
        add_point(now_points, now_position)
    shift_vector = shift.get("frame_component_shift_vector")
    if position is not None and shift_vector is not None:
        add_arrow_lines(
            shift_lines, position, vector3(position) + vector3(shift_vector)
        )
    if bool(negative.get("active")):
        target = negative.get("old_component_world_position") or position
        if target is not None:
            add_point(negative_points, target)
    _batch(batches, center_lines, "center", 2.0)
    _batch(batches, shift_lines, "shift", 2.0)
    _point_batch(point_batches, center_points, "center", 11.0)
    _point_batch(point_batches, anchor_points, "center", 9.0)
    _point_batch(point_batches, old_points, "shift", 7.0)
    _point_batch(point_batches, now_points, "shift", 9.0)
    _point_batch(point_batches, negative_points, "negative", 13.0)


def _append_collider_batches(batches, collision, limit):
    colliders = collision.get("colliders")
    if not isinstance(colliders, dict):
        return
    lines = []
    types = np.asarray(_values(colliders.get("types")), dtype=np.int32)
    centers = np.asarray(_values(colliders.get("centers")), dtype=np.float32).reshape((-1, 3))
    segment_a = np.asarray(_values(colliders.get("segment_a")), dtype=np.float32).reshape((-1, 3))
    segment_b = np.asarray(_values(colliders.get("segment_b")), dtype=np.float32).reshape((-1, 3))
    radii = np.asarray(_values(colliders.get("radii")), dtype=np.float32)
    for kind, center, first, second, radius in zip(types[:limit], centers, segment_a, segment_b, radii):
        kind = int(kind)
        radius = float(radius)
        if kind == 0:
            _add_axis_sphere(lines, center, radius)
        elif kind == 1:
            add_capsule_lines(lines, first, second, radius)
        elif kind == 2:
            axis_x, axis_y = _plane_axes(first)
            add_plane_lines(lines, center, axis_x, axis_y, first)
        elif kind == 3:
            cross = vector3(first).cross(vector3(second))
            if cross.length > 1.0e-8:
                cross.normalize()
                add_box_lines(lines, center, first, second, cross * radius)
    _batch(batches, lines, "collider", 1.4)


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
        disabled_lines = []
        contacts = np.asarray(_values(state.get("contact_indices")), dtype=np.int32).reshape((-1, 2))
        enabled = np.asarray(_values(state.get("contact_enabled")), dtype=np.uint8)
        normals = np.asarray(_values(state.get("contact_normals")), dtype=np.float32).reshape((-1, 3))
        thickness = np.asarray(_values(state.get("contact_thickness")), dtype=np.float32)
        for index, (first, second) in enumerate(contacts[:limit]):
            if not _primitive_pair_visible(visible_primitives, first, second):
                continue
            target = enabled_lines if index < len(enabled) and enabled[index] else disabled_lines
            _add_center_line(target, centers, int(first), int(second))
            if index < len(normals) and 0 <= int(first) < len(centers) and centers[int(first)] is not None:
                length = float(thickness[index]) if index < len(thickness) else 0.04
                add_arrow_lines(
                    target,
                    centers[int(first)],
                    vector3(centers[int(first)])
                    + vector3(normals[index]) * max(length, 0.02),
                )
        intersections = []
        for record in np.asarray(_values(state.get("intersect_records")), dtype=np.int32).reshape((-1, 5))[:limit]:
            if not any(
                0 <= int(particle) < len(visible_particles)
                and visible_particles[int(particle)]
                for particle in record
            ):
                continue
            _add_index_line(intersections, positions, record[:2])
            _add_index_loop(intersections, positions, record[2:])
        _batch(batches, enabled_lines, "contact", 2.2)
        _batch(batches, disabled_lines, "disabled_contact")
        _batch(batches, intersections, "intersection", 2.6)


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
        draw_line_batches(item.get("batches") or ())
        draw_point_batches(item.get("point_batches") or ())


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
