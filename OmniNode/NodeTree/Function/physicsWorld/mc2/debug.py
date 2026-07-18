"""Request-driven MC2 backend debug capture contracts."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import time

import numpy as np

from ..types import PhysicsWorldCache
from .names import MC2_DEBUG_DRAW_MODE, MC2_SLOT_KIND, MC2_SOLVER_ID
from .native_context import MC2_INTERACTION_RESOURCE_KEY, MC2NativeInteractionV0
from .runtime_parameters import (
    MC2_RUNTIME_CURVE_FIELDS,
    MC2_RUNTIME_FLOAT_FIELDS,
    MC2_RUNTIME_INT_FIELDS,
)


MC2_DEBUG_DRAW_MODES = {
    MC2_DEBUG_DRAW_MODE: {
        "solver": MC2_SOLVER_ID,
        "label": "MC2调试",
        "source": "request_driven_cpp_snapshot",
        "draw_item_contract": "physicsWorld.utils.debug_draw",
        "implementation_status": "active",
        "setup_types": ("mesh_cloth", "bone_cloth", "bone_spring"),
        "semantic_layers": (
            "topology",
            "step_basic_reference",
            "effective_gravity",
            "motion_base_position",
            "motion_limits",
            "angle_restoration_target",
            "angle_limit_range",
            "center",
            "collision",
            "self_collision",
            "final_output_offset",
        ),
    },
}


def normalize_mc2_task_filters(value) -> tuple[str, ...]:
    pending = list(value) if isinstance(value, (list, tuple, set)) else [value]
    result = []
    while pending:
        item = pending.pop(0)
        if item is None:
            continue
        if isinstance(item, (list, tuple, set)):
            pending[0:0] = list(item)
            continue
        text = str(item).replace(";", "\n").replace(",", "\n")
        for token in text.splitlines():
            token = token.strip()
            if token and token not in result:
                result.append(token)
    return tuple(result)


def _matches_task_filter(task_id, filters) -> bool:
    task_id = str(task_id or "")
    return not filters or any(token in task_id for token in filters)


def _readonly(values, dtype=None) -> np.ndarray:
    result = np.array(values, dtype=dtype, copy=True, order="C")
    result.flags.writeable = False
    return result


def _freeze_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, np.ndarray):
        return _readonly(value)
    if is_dataclass(value):
        return _freeze_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _freeze_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_value(item) for item in value)
    return repr(value)


def _state_requested(state, frame: int) -> bool:
    return (
        isinstance(state, dict)
        and bool(state.get("requested", False))
        and int(state.get("request_frame", frame) or 0) != frame
    )


def request_mc2_debug_capture(
    world,
    *,
    filters: dict | None = None,
) -> int:
    if not isinstance(world, PhysicsWorldCache):
        return 0
    filters = dict(filters or {})
    frame = int(getattr(world.frame_context, "frame", 0) or 0)
    task_filters = normalize_mc2_task_filters(filters.get("task_filter"))
    setup_filter = str(filters.get("setup_filter") or "all").strip().lower()
    requested = 0
    for slot in world.solver_slots.values():
        if slot.kind != MC2_SLOT_KIND:
            continue
        spec = slot.data.get("spec")
        if spec is None:
            continue
        if not _matches_task_filter(spec.task_id, task_filters):
            continue
        if setup_filter not in ("", "all", str(spec.setup_type).lower()):
            continue
        state = slot.data.setdefault("_debug_capture_state", {})
        state.update({
            "requested": True,
            "request_frame": frame,
            "filters": filters,
        })
        requested += 1
    interaction = world.backend_resources.get(MC2_INTERACTION_RESOURCE_KEY)
    if isinstance(interaction, MC2NativeInteractionV0):
        interaction.request_debug_capture(frame, filters)
    return requested


def _active_static(slot):
    return slot.data.get("mesh_static") or slot.data.get("bone_static")


def _baseline_for_static(static):
    baseline = getattr(static, "baseline", None)
    return getattr(baseline, "baseline", baseline)


def _curve_maps(effective) -> tuple[dict, dict, dict]:
    return (
        dict(zip(MC2_RUNTIME_FLOAT_FIELDS, effective.float_values)),
        dict(zip(MC2_RUNTIME_INT_FIELDS, effective.int_values)),
        dict(zip(MC2_RUNTIME_CURVE_FIELDS, effective.curve_values)),
    )


def _sample_curve(values, depths, *, square_depth=False) -> np.ndarray:
    curve = np.asarray(values, dtype=np.float32)
    depth = np.asarray(depths, dtype=np.float32)
    if square_depth:
        depth = depth * depth
    scaled = np.clip(depth, 0.0, 1.0) * np.float32(15.0)
    lower = np.floor(scaled).astype(np.int32)
    upper = np.minimum(lower + 1, 15)
    weight = scaled - lower.astype(np.float32)
    return _readonly(curve[lower] * (1.0 - weight) + curve[upper] * weight)


def _topology_payload(slot, native_snapshot) -> dict:
    topology = slot.data.get("topology")
    static = _active_static(slot)
    proxy = getattr(static, "final_proxy", None)
    baseline = _baseline_for_static(static)
    connection = getattr(topology, "bone_connection", None)
    longitudinal = []
    lateral = []
    if connection is not None:
        roots = connection.root_indices
        levels = connection.levels
        for edge in connection.lines:
            left, right = edge
            if roots[left] == roots[right] and abs(levels[left] - levels[right]) == 1:
                longitudinal.append(edge)
            else:
                lateral.append(edge)
    return {
        "connection_model": str(getattr(topology, "connection_model", "")),
        "connection_mode": int(getattr(topology, "connection_mode", 0) or 0),
        "vertex_identities": tuple(getattr(proxy, "vertex_identities", ()) or ()),
        "vertex_attributes": _readonly(
            getattr(proxy, "vertex_attributes", ()), np.uint8
        ),
        "edges": _readonly(getattr(proxy, "edges", ()), np.int32).reshape((-1, 2)),
        "triangles": _readonly(
            getattr(proxy, "triangles", ()), np.int32
        ).reshape((-1, 3)),
        "longitudinal_edges": _readonly(longitudinal, np.int32).reshape((-1, 2)),
        "lateral_edges": _readonly(lateral, np.int32).reshape((-1, 2)),
        "chain_indices": _readonly(
            getattr(connection, "root_indices", ()), np.int32
        ),
        "chain_depths": _readonly(getattr(connection, "levels", ()), np.int32),
        "baseline_depths": _readonly(getattr(baseline, "depths", ()), np.float32),
        "positions": native_snapshot["positions"],
    }


def _motion_payload(slot, native_snapshot) -> dict:
    effective = slot.data.get("effective_parameters")
    static = _active_static(slot)
    baseline = _baseline_for_static(static)
    depths = getattr(baseline, "depths", ())
    if depths is None:
        depths = ()
    floats, ints, curves = _curve_maps(effective)
    return {
        "motion_base_positions": native_snapshot.get("motion_base_positions"),
        "motion_base_rotations_xyzw": native_snapshot.get(
            "motion_base_rotations_xyzw"
        ),
        "step_basic_positions": native_snapshot.get("step_basic_positions"),
        "step_basic_rotations_xyzw": native_snapshot.get("step_basic_rotations_xyzw"),
        "use_angle_restoration": bool(ints["use_angle_restoration"]),
        "angle_restoration_target_positions": native_snapshot.get(
            "angle_restoration_target_positions"
        ),
        "angle_restoration_target_vectors": native_snapshot.get(
            "angle_restoration_target_vectors"
        ),
        "angle_restoration_target_valid": native_snapshot.get(
            "angle_restoration_target_valid"
        ),
        "angle_restoration_strengths": _sample_curve(
            curves["angle_restoration_stiffness"], depths
        ),
        "use_angle_limit": bool(ints["use_angle_limit"]),
        "angle_limits": _sample_curve(curves["angle_limit"], depths),
        "angle_limit_stiffness": float(floats["angle_limit_stiffness"]),
        "normal_axis": int(ints["normal_axis"]),
        "use_max_distance": bool(ints["use_max_distance"]),
        "max_distances": _sample_curve(
            curves["max_distance"], depths, square_depth=True
        ),
        "use_backstop": bool(ints["use_backstop"]),
        "backstop_radius": float(floats["backstop_radius"]),
        "backstop_distances": _sample_curve(
            curves["backstop_distance"], depths, square_depth=True
        ),
        "motion_stiffness": float(floats["motion_stiffness"]),
    }


def _parameter_payload(slot, native_snapshot) -> dict:
    effective = slot.data.get("effective_parameters")
    static = _active_static(slot)
    baseline = _baseline_for_static(static)
    depths = getattr(baseline, "depths", ())
    if depths is None:
        depths = ()
    floats, _ints, curves = _curve_maps(effective)
    native = native_snapshot.get("native") or {}
    direction = np.asarray((
        floats["gravity_direction_x"],
        floats["gravity_direction_y"],
        floats["gravity_direction_z"],
    ), dtype=np.float32)
    gravity_ratio = float(native.get("gravity_ratio", 1.0) or 0.0)
    scale_ratio = float(native.get("scale_ratio", 1.0) or 1.0)
    gravity_strength = float(floats["gravity"])
    return {
        "gravity_direction": _readonly(direction),
        "gravity_strength": gravity_strength,
        "gravity_ratio": gravity_ratio,
        "gravity_effective_strength": gravity_strength * gravity_ratio * scale_ratio,
        "damping": _sample_curve(curves["damping"], depths),
        "distance_stiffness": _sample_curve(curves["distance_stiffness"], depths),
    }


def _collision_payload(item, native_snapshot) -> dict:
    slot = item["slot"]
    effective = slot.data.get("effective_parameters")
    static = _active_static(slot)
    baseline = _baseline_for_static(static)
    depths = getattr(baseline, "depths", ())
    if depths is None:
        depths = ()
    _floats, ints, curves = _curve_maps(effective)
    native = native_snapshot.get("native") or {}
    scale_ratio = float(native.get("scale_ratio", 1.0) or 1.0)
    radius_multipliers = getattr(static, "radius_multipliers", None)
    if radius_multipliers is None:
        radius_multipliers = np.ones(len(depths), dtype=np.float32)
    collider = item.get("collider_frame")
    collider_payload = None
    if collider is not None:
        collider_payload = {
            "keys": tuple(getattr(collider, "collider_keys", ()) or ()),
            "source_pointer": int(getattr(collider, "source_pointer", 0) or 0),
            "collided_by_groups": int(collider.collided_by_groups),
            "types": _readonly(collider.collider_types),
            "group_bits": _readonly(collider.collider_group_bits),
            "centers": _readonly(collider.collider_centers),
            "segment_a": _readonly(collider.collider_segment_a),
            "segment_b": _readonly(collider.collider_segment_b),
            "old_centers": _readonly(collider.collider_old_centers),
            "old_segment_a": _readonly(collider.collider_old_segment_a),
            "old_segment_b": _readonly(collider.collider_old_segment_b),
            "radii": _readonly(collider.collider_radii),
        }
    return {
        "collision_mode": int(ints["collision_mode"]),
        "particle_radii": _readonly(
            _sample_curve(curves["radius"], depths)
            * np.asarray(radius_multipliers, dtype=np.float32)
            * scale_ratio
        ),
        "self_collision_mode": int(ints["self_collision_mode"]),
        "self_collision_sync_mode": int(ints["self_collision_sync_mode"]),
        "colliders": collider_payload,
    }


def _center_payload(slot, item) -> dict:
    frame_input = item.get("frame_input")
    center_step = slot.data.get("center_step_result")
    frame_shift = slot.data.get("center_frame_shift_result")
    negative = slot.data.get("center_negative_scale_result")
    return {
        "frame_pose": _freeze_value(
            getattr(frame_input, "center_frame_pose", None)
        ),
        "source_world_linear": _freeze_value(
            getattr(frame_input, "source_world_linear", None)
        ),
        "scale_ratio": float(getattr(frame_input, "scale_ratio", 1.0) or 1.0),
        "negative_scale_sign": float(
            getattr(frame_input, "negative_scale_sign", 1.0) or 1.0
        ),
        "step": _freeze_value(center_step),
        "frame_shift": _freeze_value(frame_shift),
        "negative_scale_transition": _freeze_value(negative),
        "frame_sync": _freeze_value(item.get("frame_plan")),
    }


def _output_payload(slot, item) -> dict:
    plan = slot.data.get("writeback_plan")
    is_bone_plan = (
        isinstance(plan, dict)
        and str(plan.get("schema") or "") == "mc2_bone_writeback_plan_v0"
    )
    static = _active_static(slot)
    proxy = getattr(static, "final_proxy", None)
    candidate = slot.data.get("result_candidate")
    frame_input = item.get("frame_input")
    targets = []
    motion_modes = []
    if is_bone_plan:
        for batch in plan.get("batches") or ():
            for record in batch.get("records") or ():
                name = str(record.get("bone_name") or "")
                if name:
                    targets.append(name)
                    motion_modes.append((name, str(record.get("motion_mode") or "")))
    if not targets:
        targets = [str(value) for value in getattr(proxy, "vertex_identities", ())]
    base_positions = getattr(frame_input, "world_positions", None)
    target_positions = getattr(candidate, "world_positions", None)
    offsets = None
    applied = None
    local_offsets = getattr(candidate, "mesh_object_local_offsets", None)
    if base_positions is not None and target_positions is not None:
        base_positions = np.asarray(base_positions, dtype=np.float32)
        target_positions = np.asarray(target_positions, dtype=np.float32)
        if base_positions.shape == target_positions.shape:
            applied = np.ones((len(base_positions),), dtype=np.uint8)
            if is_bone_plan and motion_modes:
                for index, (_name, mode) in enumerate(motion_modes):
                    if index < len(applied) and mode == "rotation_only_connected":
                        applied[index] = 0
                target_positions = target_positions.copy()
                target_positions[applied == 0] = base_positions[applied == 0]
            offsets = target_positions - base_positions
    return {
        "base_positions": _readonly(base_positions) if base_positions is not None else None,
        "target_positions": _readonly(target_positions) if target_positions is not None else None,
        "world_offsets": _readonly(offsets) if offsets is not None else None,
        "mesh_object_local_offsets": (
            _readonly(local_offsets) if local_offsets is not None else None
        ),
        "translation_applied": _readonly(applied) if applied is not None else None,
        "writeback_schema": str(plan.get("schema") or "") if isinstance(plan, dict) else "",
        "writeback_target_count": len(targets),
        "has_writeback_plan": bool(plan),
        "writeback_targets": tuple(targets),
        "writeback_target_kind": "bone" if is_bone_plan else "mesh_vertex",
        "writeback_motion_modes": tuple(motion_modes),
        "rotation_only_connected_count": int(
            plan.get("rotation_only_connected_count", 0) or 0
        ) if is_bone_plan else 0,
        "position_rotation_count": int(
            plan.get("position_rotation_count", 0) or 0
        ) if is_bone_plan else 0,
    }


def capture_requested_mc2_debug(
    world: PhysicsWorldCache,
    runtime_items,
    interaction,
) -> int:
    frame = int(getattr(world.frame_context, "frame", 0) or 0)
    generation = int(world.generation)
    captured = 0
    for item in runtime_items:
        slot = item["slot"]
        state = slot.data.get("_debug_capture_state")
        if not _state_requested(state, frame) or not item.get("substeps"):
            continue
        started = time.perf_counter()
        attempted = False
        try:
            attempted = True
            filters = dict(state.get("filters") or {})
            native_snapshot = item["native_context"].refresh_debug_draw_snapshot(
                include_step_basic=bool(
                    filters.get("show_angle_restoration", True)
                    or filters.get("show_angle_limit", False)
                    or filters.get("show_step_basic", False)
                ),
                include_motion_debug=bool(
                    filters.get("show_motion", True)
                    or filters.get("show_motion_base", True)
                    or filters.get("show_angle_restoration", True)
                    or filters.get("show_angle_limit", False)
                ),
                include_self=bool(filters.get("show_self", True)),
            )
            snapshot = {
                "source": "mc2_capture",
                "schema": "mc2_debug_snapshot_v0",
                "slot_id": str(slot.slot_id),
                "task_id": str(item["spec"].task_id),
                "setup_type": str(item["spec"].setup_type),
                "frame": frame,
                "generation": generation,
                "filters": filters,
                "native": native_snapshot,
                "topology": _topology_payload(slot, native_snapshot),
                "parameters": _parameter_payload(slot, native_snapshot),
                "motion": _motion_payload(slot, native_snapshot),
                "center": _center_payload(slot, item),
                "collision": _collision_payload(item, native_snapshot),
                "self_collision": native_snapshot.get("self_collision"),
                "output": _output_payload(slot, item),
            }
            slot.data["_debug_draw_snapshot"] = snapshot
            state.pop("error", None)
            state["captured_frame"] = frame
            captured += 1
        except Exception as exc:
            state["error"] = str(exc)
        finally:
            if attempted:
                state["requested"] = False
                state["attempted_frame"] = frame
                state["capture_ms"] = (time.perf_counter() - started) * 1000.0

    if isinstance(interaction, MC2NativeInteractionV0):
        state = interaction.debug_capture_state()
        if _state_requested(state, frame) and any(item.get("substeps") for item in runtime_items):
            started = time.perf_counter()
            try:
                interaction.refresh_debug_draw_snapshot()
                state.pop("error", None)
                state["captured_frame"] = frame
                captured += 1
            except Exception as exc:
                state["error"] = str(exc)
            finally:
                state["requested"] = False
                state["attempted_frame"] = frame
                state["capture_ms"] = (time.perf_counter() - started) * 1000.0
    return captured


__all__ = [
    "MC2_DEBUG_DRAW_MODES",
    "capture_requested_mc2_debug",
    "request_mc2_debug_capture",
]
