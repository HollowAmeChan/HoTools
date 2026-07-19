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
    "longitudinal": (0.95, 0.70, 0.18, 0.95),
    "lateral": (0.20, 0.85, 0.95, 0.95),
    "triangle": (0.38, 0.62, 0.82, 0.50),
    "edge_collision": (0.70, 0.20, 0.04, 0.58),
    "edge_collision_surface": (1.00, 0.30, 0.04, 0.32),
    "point_collision_surface": (0.10, 0.92, 0.32, 0.26),
    "collider_surface": (0.03, 0.58, 1.00, 0.42),
    "fixed": (0.95, 0.25, 0.20, 0.95),
    "move": (0.25, 0.95, 0.40, 0.85),
    "depth_fixed": (1.00, 0.18, 0.62, 1.00),
    "depth_unrooted": (0.72, 0.18, 1.00, 1.00),
    "depth_root_boundary": (0.92, 0.96, 1.00, 0.90),
    "depth_inversion": (1.00, 0.04, 0.03, 1.00),
    "depth_jump": (1.00, 0.42, 0.04, 0.98),
    "depth_zero_distance": (1.00, 0.96, 0.12, 1.00),
    "motion_base": (0.20, 0.85, 1.00, 0.90),
    "step_basic": (0.58, 0.72, 1.00, 0.72),
    "gravity": (0.45, 1.00, 0.30, 0.95),
    "velocity": (0.20, 0.92, 1.00, 0.92),
    "real_velocity": (1.00, 0.52, 0.18, 0.72),
    "distance_ok": (0.35, 0.95, 0.42, 0.72),
    "distance_stretch": (1.00, 0.18, 0.12, 0.95),
    "distance_compress": (0.20, 0.48, 1.00, 0.95),
    "tether": (0.72, 0.76, 0.82, 0.55),
    "tether_min": (0.22, 0.55, 1.00, 0.72),
    "tether_max": (1.00, 0.78, 0.18, 0.72),
    "bending": (0.70, 0.38, 1.00, 0.72),
    "bending_error": (1.00, 0.20, 0.14, 0.95),
    "bending_volume": (0.20, 0.90, 0.82, 0.72),
    "angle_target": (1.00, 0.32, 0.72, 0.95),
    "angle_limit": (1.00, 0.82, 0.20, 0.78),
    "max_distance": (0.30, 0.75, 1.00, 0.36),
    "backstop": (1.00, 0.40, 0.22, 0.55),
    "center": (1.00, 0.92, 0.25, 0.95),
    "center_anchor": (0.10, 0.88, 1.00, 0.92),
    "center_old": (0.28, 0.52, 1.00, 0.78),
    "center_now": (1.00, 0.72, 0.12, 0.96),
    "shift": (1.00, 0.38, 0.08, 0.94),
    "center_step": (0.22, 0.78, 1.00, 0.92),
    "center_inertia": (0.72, 0.32, 1.00, 0.92),
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
    "contact": (1.00, 0.15, 0.12, 0.95),
    "disabled_contact": (0.55, 0.55, 0.60, 0.38),
    "intersection": (1.00, 0.05, 0.72, 1.00),
    "output": (0.30, 1.00, 0.82, 0.85),
}

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
    show_topology: bool = True,
    show_attributes: bool = True,
    show_depth: bool = False,
    show_motion: bool = True,
    show_center: bool = True,
    show_collision: bool = True,
    show_radii: bool = False,
    show_self_primitives: bool = False,
    show_self_grid: bool = False,
    show_self_candidates: bool = False,
    show_self_contacts: bool = True,
    show_output: bool = True,
    task_filter: str = "",
    max_items: int = 2000,
    show_step_basic: bool = False,
    show_gravity: bool = False,
    show_velocity: bool = False,
    show_distance: bool = False,
    show_tether: bool = False,
    show_bending: bool = False,
    show_motion_base: bool = True,
    show_angle_restoration: bool = True,
    show_angle_limit: bool = False,
    show_teleport_threshold: bool = False,
    show_teleport_status: bool = False,
) -> None:
    node_key = str(node_uid)
    if not enabled or not isinstance(world, PhysicsWorldCache):
        if isinstance(world, PhysicsWorldCache):
            request_mc2_debug_capture(world, filters={})
        clear_mc2_debug_draw_store(node_uid=node_key)
        return

    filters = {
        "show_topology": bool(show_topology),
        "show_attributes": bool(show_attributes),
        "show_depth": bool(show_depth),
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
    _MC2_DRAW_STORE[node_key] = {
        "world_id": str(id(world)),
        "frame": int(getattr(world.frame_context, "frame", 0) or 0),
        "batches": batches,
        "point_batches": point_batches,
        "triangle_batches": triangle_batches,
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
        "coordinate_checksum": round(
            sum((index + 1) * float(value) for index, value in enumerate(flattened)),
            6,
        ),
    }


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
        _append_depth_batches(batches, point_batches, topology, positions, limit)
    if filters["show_step_basic"]:
        _append_step_basic_batches(
            batches, topology, snapshot.get("motion") or {}, limit
        )
    if filters["show_gravity"]:
        _append_gravity_batches(
            batches,
            snapshot.get("parameters") or {},
            snapshot.get("center") or {},
            positions,
        )
    if filters["show_velocity"]:
        _append_velocity_batches(
            batches,
            positions,
            (snapshot.get("native") or {}).get("dynamics") or {},
            limit,
        )
    if filters["show_distance"]:
        _append_distance_batches(
            batches,
            positions,
            snapshot.get("motion") or {},
            snapshot.get("parameters") or {},
            (snapshot.get("native") or {}).get("distance_tether") or {},
            limit,
        )
    if filters["show_tether"]:
        _append_tether_batches(
            batches,
            positions,
            snapshot.get("motion") or {},
            snapshot.get("parameters") or {},
            (snapshot.get("native") or {}).get("distance_tether") or {},
            limit,
        )
    if filters["show_bending"]:
        _append_bending_batches(
            batches,
            positions,
            snapshot.get("parameters") or {},
            (snapshot.get("native") or {}).get("bending") or {},
            limit,
        )
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
    if filters["show_angle_limit"]:
        _append_angle_limit_batches(
            batches, snapshot.get("motion") or {}, limit
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


def _append_depth_batches(batches, point_batches, topology, positions, limit):
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


def _append_gravity_batches(batches, parameters, center, positions):
    direction = np.asarray(
        _values(parameters.get("gravity_direction")), dtype=np.float32
    ).reshape((-1,))
    strength = float(parameters.get("gravity_effective_strength", 0.0) or 0.0)
    if len(direction) != 3 or strength <= 1.0e-8:
        return
    direction = vector3(direction)
    if direction.length <= 1.0e-8:
        return
    direction.normalize()
    frame_pose = center.get("frame_pose") or {}
    step = center.get("step") or {}
    origin = step.get("now_world_position") or frame_pose.get(
        "component_world_position"
    )
    if origin is None:
        if not len(positions):
            return
        origin = positions[0]
    start = vector3(origin)
    add = direction * strength * 0.02
    lines = []
    add_arrow_lines(lines, start, start + add)
    _batch(batches, lines, "gravity", 2.2)


def _append_velocity_batches(batches, positions, dynamics, limit):
    velocities = dynamics.get("velocities")
    real_velocities = dynamics.get("real_velocities")
    if velocities is None or real_velocities is None:
        return
    velocities = np.asarray(velocities, dtype=np.float32).reshape((-1, 3))
    real_velocities = np.asarray(real_velocities, dtype=np.float32).reshape((-1, 3))
    stored_lines = []
    real_lines = []
    for position, velocity, real_velocity in zip(
        positions[:limit], velocities[:limit], real_velocities[:limit]
    ):
        start = vector3(position)
        stored = vector3(velocity) * 0.03
        real = vector3(real_velocity) * 0.03
        if stored.length > 1.0e-7:
            add_arrow_lines(stored_lines, start, start + stored)
        if real.length > 1.0e-7:
            add_arrow_lines(real_lines, start, start + real)
    _batch(batches, real_lines, "real_velocity", 1.0)
    _batch(batches, stored_lines, "velocity", 1.8)


def _append_distance_batches(
    batches, positions, motion, parameters, distance, limit
):
    ranges = distance.get("distance_ranges")
    targets = distance.get("distance_targets")
    rests = distance.get("distance_rest_signed")
    step_basic = motion.get("step_basic_positions")
    if ranges is None or targets is None or rests is None or step_basic is None:
        return
    ranges = np.asarray(ranges, dtype=np.int32).reshape((-1, 2))
    targets = np.asarray(targets, dtype=np.int32)
    rests = np.asarray(rests, dtype=np.float32)
    step_basic = np.asarray(step_basic, dtype=np.float32).reshape((-1, 3))
    stiffness = np.asarray(
        _values(parameters.get("distance_stiffness")), dtype=np.float32
    )
    scale = float(parameters.get("scale_ratio", 1.0) or 1.0)
    animation_ratio = max(
        0.0, min(1.0, float(parameters.get("animation_pose_ratio", 0.0) or 0.0))
    )
    ok_lines = []
    stretch_lines = []
    compress_lines = []
    seen = set()
    drawn = 0
    for vertex, (start, count) in enumerate(ranges):
        if drawn >= limit or vertex >= len(positions):
            break
        if vertex < len(stiffness) and float(stiffness[vertex]) <= 1.0e-8:
            continue
        for record in range(int(start), int(start + count)):
            if drawn >= limit or record < 0 or record >= len(targets):
                break
            target = int(targets[record])
            if target < 0 or target >= len(positions) or record >= len(rests):
                continue
            key = (min(vertex, target), max(vertex, target))
            if key in seen:
                continue
            seen.add(key)
            current = (vector3(positions[target]) - vector3(positions[vertex])).length
            static_rest = abs(float(rests[record])) * scale
            animated_rest = (
                vector3(step_basic[target]) - vector3(step_basic[vertex])
            ).length
            rest = static_rest * (1.0 - animation_ratio) + animated_rest * animation_ratio
            error = current - rest
            tolerance = max(rest * 0.02, 1.0e-5)
            target_lines = (
                stretch_lines
                if error > tolerance
                else compress_lines if error < -tolerance else ok_lines
            )
            add_line(target_lines, positions[vertex], positions[target])
            drawn += 1
    _batch(batches, ok_lines, "distance_ok", 1.4)
    _batch(batches, compress_lines, "distance_compress", 1.8)
    _batch(batches, stretch_lines, "distance_stretch", 1.8)


def _append_tether_batches(
    batches, positions, motion, parameters, distance, limit
):
    roots = distance.get("baseline_roots")
    step_basic = motion.get("step_basic_positions")
    if roots is None or step_basic is None:
        return
    roots = np.asarray(roots, dtype=np.int32)
    step_basic = np.asarray(step_basic, dtype=np.float32).reshape((-1, 3))
    compression = max(
        0.0, min(1.0, float(parameters.get("tether_compression", 0.0) or 0.0))
    )
    stretch = max(0.0, float(parameters.get("tether_stretch", 0.0) or 0.0))
    current_lines = []
    minimum_lines = []
    maximum_lines = []
    drawn = 0
    for vertex, root in enumerate(roots):
        root = int(root)
        if drawn >= limit:
            break
        if root < 0 or root >= len(positions) or vertex == root or vertex >= len(positions):
            continue
        rest_vector = vector3(step_basic[vertex]) - vector3(step_basic[root])
        rest = rest_vector.length
        if rest <= 1.0e-7:
            continue
        current_vector = vector3(positions[vertex]) - vector3(positions[root])
        direction = current_vector.normalized() if current_vector.length > 1.0e-7 else rest_vector.normalized()
        axis_a, axis_b = _plane_axes(direction)
        minimum = rest * (1.0 - compression)
        maximum = rest * (1.0 + stretch)
        ring_radius = max(rest * 0.035, 0.002)
        root_position = vector3(positions[root])
        add_line(current_lines, root_position, positions[vertex])
        if minimum > 1.0e-7:
            add_circle_lines(
                minimum_lines,
                root_position + direction * minimum,
                axis_a,
                axis_b,
                ring_radius,
            )
        add_circle_lines(
            maximum_lines,
            root_position + direction * maximum,
            axis_a,
            axis_b,
            ring_radius,
        )
        drawn += 1
    _batch(batches, current_lines, "tether", 1.0)
    _batch(batches, minimum_lines, "tether_min", 1.5)
    _batch(batches, maximum_lines, "tether_max", 1.5)


def _append_bending_batches(batches, positions, parameters, bending, limit):
    quads = bending.get("quads")
    rests = bending.get("rests")
    markers = bending.get("markers")
    if quads is None or rests is None or markers is None:
        return
    if float(parameters.get("bending_stiffness", 0.0) or 0.0) <= 1.0e-8:
        return
    quads = np.asarray(quads, dtype=np.int32).reshape((-1, 4))
    rests = np.asarray(rests, dtype=np.float32)
    markers = np.asarray(markers, dtype=np.int32)
    negative_sign = float(parameters.get("negative_scale_sign", 1.0) or 1.0)
    scale = float(parameters.get("scale_ratio", 1.0) or 1.0)
    normal_lines = []
    error_lines = []
    volume_lines = []
    for record, quad in enumerate(quads[:limit]):
        if record >= len(rests) or record >= len(markers):
            continue
        indices = tuple(int(value) for value in quad)
        if any(index < 0 or index >= len(positions) for index in indices):
            continue
        points = [vector3(positions[index]) for index in indices]
        marker = int(markers[record])
        if marker == 100:
            volume = (
                (points[1] - points[0]).cross(points[2] - points[0])
            ).dot(points[3] - points[0]) / 6.0 * 1000.0
            expected = float(rests[record]) * scale * negative_sign
            target_lines = (
                error_lines
                if abs(volume - expected) > max(abs(expected) * 0.05, 1.0e-5)
                else volume_lines
            )
            for first, second in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)):
                add_line(target_lines, points[first], points[second])
            continue
        edge = points[3] - points[2]
        normal_a = (points[2] - points[0]).cross(points[3] - points[0])
        normal_b = (points[3] - points[1]).cross(points[2] - points[1])
        if edge.length <= 1.0e-7 or normal_a.length <= 1.0e-7 or normal_b.length <= 1.0e-7:
            continue
        normal_a.normalize()
        normal_b.normalize()
        angle = math.acos(max(-1.0, min(1.0, normal_a.dot(normal_b))))
        direction = normal_a.cross(normal_b).dot(edge)
        if direction < 0.0:
            angle = -angle
        expected = float(rests[record]) * (-1.0 if marker < 0 else 1.0) * negative_sign
        target_lines = error_lines if abs(angle - expected) > math.radians(5.0) else normal_lines
        for first, second in ((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)):
            add_line(target_lines, points[first], points[second])
    _batch(batches, normal_lines, "bending", 1.2)
    _batch(batches, volume_lines, "bending_volume", 1.2)
    _batch(batches, error_lines, "bending_error", 2.0)


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
        if filters.get("show_teleport_threshold", False):
            threshold_lines = []
            direction_lines = []
            radius = max(float(teleport.get("distance_threshold", 0.0) or 0.0), 0.0)
            if radius > 1.0e-7:
                _add_axis_sphere(threshold_lines, old_position, radius)
            if (position - old_position).length > 1.0e-7:
                add_arrow_lines(direction_lines, old_position, position)
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
            if abs(float(delta.angle)) > 1.0e-7:
                axis = delta.axis
            else:
                axis = old_rotation @ mathutils.Vector((0.0, 0.0, 1.0))
            axis_a, axis_b = _plane_axes(axis)
            arc_radius = max(min(radius * 0.28, 0.25), 0.025)
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


def _append_collider_batches(batches, triangle_meshes, collision, limit):
    colliders = collision.get("colliders")
    if not isinstance(colliders, dict):
        return
    lines = []
    mesh = _triangle_mesh(triangle_meshes, "collider_surface")
    types = np.asarray(_values(colliders.get("types")), dtype=np.int32)
    group_bits = np.asarray(_values(colliders.get("group_bits")), dtype=np.int32)
    collided_by_groups = int(colliders.get("collided_by_groups", 0) or 0)
    centers = np.asarray(_values(colliders.get("centers")), dtype=np.float32).reshape((-1, 3))
    segment_a = np.asarray(_values(colliders.get("segment_a")), dtype=np.float32).reshape((-1, 3))
    segment_b = np.asarray(_values(colliders.get("segment_b")), dtype=np.float32).reshape((-1, 3))
    radii = np.asarray(_values(colliders.get("radii")), dtype=np.float32)
    for kind, group_bit, center, first, second, radius in zip(
        types[:limit], group_bits, centers, segment_a, segment_b, radii
    ):
        if not (collided_by_groups & int(group_bit)):
            continue
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
            add_line(lines, first, second)
        elif kind == 2:
            axis_x, axis_y = _plane_axes(first)
            add_plane_triangles(
                mesh["vertices"], mesh["indices"], center, axis_x, axis_y
            )
            normal = vector3(first)
            if normal.length > 1.0e-8:
                normal.normalize()
                add_arrow_lines(lines, center, vector3(center) + normal * 0.35)
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
