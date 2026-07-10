"""Rigid/Jolt 自有可视化调试绘制。"""

from __future__ import annotations

import bpy
import mathutils

from .names import RIGID_BODY_SLOT_KIND, RIGID_CONSTRAINT_SLOT_KIND
from .constraint_debug import build_constraint_debug_lines
from ..types import PhysicsWorldCache
from ..utils.debug_draw import (
    add_box_lines,
    add_capsule_lines,
    add_cross_lines,
    add_line,
    add_plane_lines,
    add_sphere_lines,
    axis_from_matrix,
    draw_line_batches,
    float_value,
    half_extents,
    matrix_from_position_rotation,
    vector3,
)
from .results import (
    get_rigid_constraint_state_result,
    get_rigid_transform_result,
    iter_rigid_contact_event_results,
)


_COLOR_BODY_DYNAMIC = (0.20, 0.90, 0.20, 0.85)
_COLOR_BODY_STATIC = (0.60, 0.60, 0.65, 0.70)
_COLOR_BODY_KINEMATIC = (0.40, 0.60, 1.00, 0.85)
_COLOR_BODY_SLEEP = (0.35, 0.70, 0.35, 0.50)
_COLOR_CONSTRAINT = (1.00, 0.75, 0.10, 0.90)
_COLOR_CONSTRAINT_LIMIT = (1.00, 0.30, 0.05, 0.95)
_COLOR_CONSTRAINT_MOTOR = (1.00, 0.15, 0.85, 0.95)
_COLOR_CONSTRAINT_STATE = (0.10, 0.90, 1.00, 0.95)
_COLOR_PROBLEM = (1.00, 0.10, 0.10, 0.95)
_COLOR_CONTACT = (0.95, 0.95, 0.95, 0.95)
_COLOR_SENSOR = (1.00, 0.20, 0.80, 0.90)
_COLOR_REMOVED_CONTACT = (1.00, 0.35, 0.10, 0.75)
_COLOR_REMOVED_SENSOR = (0.65, 0.30, 1.00, 0.75)

_MAX_DEBUG_CONTACT_EVENTS = 256
_MAX_DEBUG_POINTS_PER_EVENT = 4

_RIGID_DRAW_STORE: dict[str, dict] = {}
_RIGID_DRAW_HANDLE = None


def update_rigid_debug_draw_store(
    node_uid: str,
    world,
    enabled: bool,
    show_bodies: bool = True,
    show_constraints: bool = True,
    show_problems: bool = True,
    show_contacts: bool = True,
    show_sensors: bool = True,
) -> None:
    node_key = str(node_uid)
    if not enabled or not isinstance(world, PhysicsWorldCache):
        clear_rigid_debug_draw_store(node_key)
        return

    _ensure_rigid_draw_handler()

    _RIGID_DRAW_STORE[node_key] = build_rigid_debug_draw_snapshot(
        world,
        show_bodies=show_bodies,
        show_constraints=show_constraints,
        show_problems=show_problems,
        show_contacts=show_contacts,
        show_sensors=show_sensors,
    )


def build_rigid_debug_draw_snapshot(
    world,
    show_bodies: bool = True,
    show_constraints: bool = True,
    show_problems: bool = True,
    show_contacts: bool = True,
    show_sensors: bool = True,
) -> dict:
    """Build an immutable-by-convention viewport snapshot from slots/results."""
    if not isinstance(world, PhysicsWorldCache):
        return _empty_rigid_debug_draw_snapshot(world)

    frame = int(getattr(world.frame_context, "frame", 0) or 0)
    generation = int(world.generation)
    dynamic_lines: list[tuple[float, float, float]] = []
    static_lines: list[tuple[float, float, float]] = []
    kinematic_lines: list[tuple[float, float, float]] = []
    sleeping_lines: list[tuple[float, float, float]] = []
    constraint_lines: list[tuple[float, float, float]] = []
    constraint_limit_lines: list[tuple[float, float, float]] = []
    constraint_motor_lines: list[tuple[float, float, float]] = []
    constraint_state_lines: list[tuple[float, float, float]] = []
    problem_lines: list[tuple[float, float, float]] = []
    contact_lines: list[tuple[float, float, float]] = []
    sensor_lines: list[tuple[float, float, float]] = []
    removed_contact_lines: list[tuple[float, float, float]] = []
    removed_sensor_lines: list[tuple[float, float, float]] = []
    constraint_type_counts: dict[str, int] = {}
    unknown_constraint_types: list[str] = []

    for slot_id, slot in list(world.solver_slots.items()):
        spec = slot.data.get("spec")
        if spec is None:
            continue
        if show_bodies and slot.kind == RIGID_BODY_SLOT_KIND:
            result = get_rigid_transform_result(
                world,
                slot_id=slot_id,
                frame=frame,
                generation=generation,
            )
            _append_body_shape_lines(
                _body_line_target(
                    spec,
                    result,
                    dynamic_lines,
                    static_lines,
                    kinematic_lines,
                    sleeping_lines,
                ),
                spec,
                result,
            )
        elif slot.kind == RIGID_CONSTRAINT_SLOT_KIND and (show_constraints or show_problems):
            state = get_rigid_constraint_state_result(
                world,
                slot_id=slot_id,
                frame=frame,
                generation=generation,
            )
            constraint_type = str(getattr(spec, "constraint_type", "FIXED") or "FIXED").upper()
            constraint_type_counts[constraint_type] = constraint_type_counts.get(constraint_type, 0) + 1
            if show_constraints:
                semantic_lines = build_constraint_debug_lines(spec, state)
                constraint_lines.extend(semantic_lines["base"])
                constraint_limit_lines.extend(semantic_lines["limits"])
                constraint_motor_lines.extend(semantic_lines["motor"])
                constraint_state_lines.extend(semantic_lines["state"])
                if not semantic_lines["known_type"]:
                    unknown_constraint_types.append(constraint_type)
            if show_problems and _constraint_has_problem(spec, state):
                anchor = vector3(
                    getattr(
                        spec,
                        "anchor_position_a",
                        getattr(spec, "anchor_position", (0.0, 0.0, 0.0)),
                    )
                )
                add_cross_lines(problem_lines, anchor, 0.25)

    contact_events = iter_rigid_contact_event_results(
        world,
        frame=frame,
        generation=generation,
    ) if show_contacts or show_sensors else []
    visible_contact_events = 0
    visible_sensor_events = 0
    for event in contact_events[:_MAX_DEBUG_CONTACT_EVENTS]:
        is_sensor = bool(event.get("is_sensor", False))
        if is_sensor and not show_sensors:
            continue
        if not is_sensor and not show_contacts:
            continue
        removed = str(event.get("state", "")) == "removed"
        if is_sensor:
            visible_sensor_events += 1
            lines = removed_sensor_lines if removed else sensor_lines
        else:
            visible_contact_events += 1
            lines = removed_contact_lines if removed else contact_lines
        _append_contact_event_lines(lines, event)

    return {
        "world_id": str(id(world)),
        "frame": frame,
        "generation": generation,
        "dynamic_lines": dynamic_lines,
        "static_lines": static_lines,
        "kinematic_lines": kinematic_lines,
        "sleeping_lines": sleeping_lines,
        "constraint_lines": constraint_lines,
        "constraint_limit_lines": constraint_limit_lines,
        "constraint_motor_lines": constraint_motor_lines,
        "constraint_state_lines": constraint_state_lines,
        "problem_lines": problem_lines,
        "contact_lines": contact_lines,
        "sensor_lines": sensor_lines,
        "removed_contact_lines": removed_contact_lines,
        "removed_sensor_lines": removed_sensor_lines,
        "contact_event_count": visible_contact_events,
        "sensor_event_count": visible_sensor_events,
        "contact_event_truncated": max(
            0,
            len(contact_events) - _MAX_DEBUG_CONTACT_EVENTS,
        ),
        "constraint_type_counts": constraint_type_counts,
        "unknown_constraint_types": sorted(set(unknown_constraint_types)),
        "constraint_frame_source": "constraint_spec_backend_input",
        "constraint_runtime_frame_readback": False,
    }


def _empty_rigid_debug_draw_snapshot(world=None) -> dict:
    return {
        "world_id": str(id(world)) if world is not None else "",
        "frame": 0,
        "generation": 0,
        "dynamic_lines": [],
        "static_lines": [],
        "kinematic_lines": [],
        "sleeping_lines": [],
        "constraint_lines": [],
        "constraint_limit_lines": [],
        "constraint_motor_lines": [],
        "constraint_state_lines": [],
        "problem_lines": [],
        "contact_lines": [],
        "sensor_lines": [],
        "removed_contact_lines": [],
        "removed_sensor_lines": [],
        "contact_event_count": 0,
        "sensor_event_count": 0,
        "contact_event_truncated": 0,
        "constraint_type_counts": {},
        "unknown_constraint_types": [],
        "constraint_frame_source": "constraint_spec_backend_input",
        "constraint_runtime_frame_readback": False,
    }


def clear_rigid_debug_draw_store(
    node_uid: str | None = None,
    world_id: str | None = None,
) -> None:
    if node_uid is not None:
        _RIGID_DRAW_STORE.pop(str(node_uid), None)
    elif world_id is not None:
        wid = str(world_id)
        for key, value in list(_RIGID_DRAW_STORE.items()):
            if str(value.get("world_id")) == wid:
                _RIGID_DRAW_STORE.pop(key, None)
    else:
        _RIGID_DRAW_STORE.clear()

    if not _RIGID_DRAW_STORE:
        _remove_rigid_draw_handler()


def _ensure_rigid_draw_handler() -> None:
    global _RIGID_DRAW_HANDLE
    if _RIGID_DRAW_HANDLE is None:
        _RIGID_DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
            _draw_rigid_debug,
            (),
            "WINDOW",
            "POST_VIEW",
        )


def _remove_rigid_draw_handler() -> None:
    global _RIGID_DRAW_HANDLE
    if _RIGID_DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_RIGID_DRAW_HANDLE, "WINDOW")
        except Exception:
            pass
        _RIGID_DRAW_HANDLE = None


def _draw_rigid_debug() -> None:
    draw_line_batches(
        (data.get("dynamic_lines"), _COLOR_BODY_DYNAMIC, 1.5)
        for data in list(_RIGID_DRAW_STORE.values())
    )
    draw_line_batches(
        (data.get("static_lines"), _COLOR_BODY_STATIC, 1.0)
        for data in list(_RIGID_DRAW_STORE.values())
    )
    draw_line_batches(
        (data.get("kinematic_lines"), _COLOR_BODY_KINEMATIC, 1.5)
        for data in list(_RIGID_DRAW_STORE.values())
    )
    draw_line_batches(
        (data.get("sleeping_lines"), _COLOR_BODY_SLEEP, 1.0)
        for data in list(_RIGID_DRAW_STORE.values())
    )
    draw_line_batches(
        (data.get("constraint_lines"), _COLOR_CONSTRAINT, 1.5)
        for data in list(_RIGID_DRAW_STORE.values())
    )
    draw_line_batches(
        (data.get("constraint_limit_lines"), _COLOR_CONSTRAINT_LIMIT, 1.75)
        for data in list(_RIGID_DRAW_STORE.values())
    )
    draw_line_batches(
        (data.get("constraint_motor_lines"), _COLOR_CONSTRAINT_MOTOR, 2.0)
        for data in list(_RIGID_DRAW_STORE.values())
    )
    draw_line_batches(
        (data.get("constraint_state_lines"), _COLOR_CONSTRAINT_STATE, 2.0)
        for data in list(_RIGID_DRAW_STORE.values())
    )
    draw_line_batches(
        (data.get("problem_lines"), _COLOR_PROBLEM, 2.5)
        for data in list(_RIGID_DRAW_STORE.values())
    )
    draw_line_batches(
        (data.get("contact_lines"), _COLOR_CONTACT, 2.0)
        for data in list(_RIGID_DRAW_STORE.values())
    )
    draw_line_batches(
        (data.get("sensor_lines"), _COLOR_SENSOR, 2.0)
        for data in list(_RIGID_DRAW_STORE.values())
    )
    draw_line_batches(
        (data.get("removed_contact_lines"), _COLOR_REMOVED_CONTACT, 1.5)
        for data in list(_RIGID_DRAW_STORE.values())
    )
    draw_line_batches(
        (data.get("removed_sensor_lines"), _COLOR_REMOVED_SENSOR, 1.5)
        for data in list(_RIGID_DRAW_STORE.values())
    )


def _append_contact_event_lines(lines: list, event: dict) -> None:
    points_a = list(event.get("points_on_a") or ())
    points_b = list(event.get("points_on_b") or ())
    point_count = min(
        max(len(points_a), len(points_b)),
        _MAX_DEBUG_POINTS_PER_EVENT,
    )
    centers = []
    for index in range(point_count):
        point_a = vector3(points_a[index] if index < len(points_a) else points_b[index])
        point_b = vector3(points_b[index] if index < len(points_b) else points_a[index])
        center = (point_a + point_b) * 0.5
        centers.append(center)
        add_cross_lines(lines, center, 0.035)
        if (point_b - point_a).length_squared > 1.0e-12:
            add_line(lines, point_a, point_b)

    if not centers:
        return
    origin = sum(centers[1:], centers[0].copy()) / len(centers)
    normal = vector3(event.get("normal", (0.0, 0.0, 0.0)))
    if normal.length_squared <= 1.0e-12:
        return
    normal.normalize()
    depth = abs(float_value(event.get("penetration_depth", 0.0), 0.0))
    normal_length = max(0.15, min(depth, 0.75))
    add_line(lines, origin, origin + normal * normal_length)


def _body_line_target(
    spec,
    result: dict | None,
    dynamic_lines: list,
    static_lines: list,
    kinematic_lines: list,
    sleeping_lines: list,
) -> list:
    body_type = str(getattr(spec, "body_type", "DYNAMIC"))
    if body_type == "DYNAMIC" and bool(result and result.get("sleeping")):
        return sleeping_lines
    if body_type == "STATIC":
        return static_lines
    if body_type == "KINEMATIC":
        return kinematic_lines
    return dynamic_lines


def _append_body_shape_lines(lines: list, spec, result: dict | None) -> None:
    mat = _shape_matrix(spec, result)
    if mat is None:
        return
    center = mat.translation.copy()
    axis_x = axis_from_matrix(mat, 0, (1.0, 0.0, 0.0))
    axis_y = axis_from_matrix(mat, 1, (0.0, 1.0, 0.0))
    axis_z = axis_from_matrix(mat, 2, (0.0, 0.0, 1.0))
    shape_type = str(getattr(spec, "shape_type", "SPHERE"))

    if shape_type == "BOX":
        hx, hy, hz = half_extents(getattr(spec, "shape_half_extents", (0.5, 0.5, 0.5)))
        add_box_lines(lines, center, axis_x * hx, axis_y * hy, axis_z * hz)
    elif shape_type == "CAPSULE":
        radius = max(float_value(getattr(spec, "shape_radius", 0.5), 0.5), 0.0)
        half_height = max(float_value(getattr(spec, "shape_half_height", 0.5), 0.5), 0.0)
        add_capsule_lines(lines, center - axis_y * half_height, center + axis_y * half_height, radius)
    elif shape_type == "PLANE":
        extent = max(float_value(getattr(spec, "shape_plane_half_extent", 10.0), 10.0), 1.0)
        add_plane_lines(lines, center, axis_x * extent, axis_y * extent, axis_z)
    else:
        radius = max(float_value(getattr(spec, "shape_radius", 0.5), 0.5), 0.0)
        add_sphere_lines(lines, center, axis_x, axis_y, axis_z, radius)


def _constraint_has_problem(spec, state: dict | None) -> bool:
    empty_obj = getattr(spec, "empty_obj", None)
    targets = (getattr(spec, "target_a", None), getattr(spec, "target_b", None))
    has_problem = all(target is None for target in targets)
    for target in targets:
        if target is None or empty_obj is None:
            continue
        try:
            if target.as_pointer() == empty_obj.as_pointer():
                has_problem = True
        except Exception:
            has_problem = True
    return bool(has_problem or (state and state.get("broken", False)))


def _shape_matrix(spec, result: dict | None) -> mathutils.Matrix | None:
    body = _body_matrix(spec, result)
    if body is None:
        return None
    try:
        offset = vector3(getattr(spec, "shape_offset", (0.0, 0.0, 0.0)))
    except Exception:
        offset = mathutils.Vector((0.0, 0.0, 0.0))
    try:
        rot = mathutils.Quaternion(getattr(spec, "shape_rotation_wxyz", (1.0, 0.0, 0.0, 0.0)))
    except Exception:
        rot = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))
    return body @ mathutils.Matrix.Translation(offset) @ rot.to_matrix().to_4x4()


def _body_matrix(spec, result: dict | None) -> mathutils.Matrix | None:
    if isinstance(result, dict):
        mat = matrix_from_position_rotation(result.get("position"), result.get("rotation_wxyz"))
        if mat is not None:
            return mat
    return matrix_from_position_rotation(
        getattr(spec, "world_position", (0.0, 0.0, 0.0)),
        getattr(spec, "world_rotation_wxyz", (1.0, 0.0, 0.0, 0.0)),
    )
