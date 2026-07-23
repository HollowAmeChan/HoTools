"""Request-driven MC2 backend debug capture contracts."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import time

import numpy as np

from ..types import PhysicsWorldCache
from .names import (
    MC2_DEBUG_DRAW_MODE,
    MC2_FUSED_PRODUCT_SLOT_KIND,
    MC2_INTERACTION_RESOURCE_KEY,
    MC2_SETUP_MESH_CLOTH,
    MC2_SLOT_KIND,
    MC2_SOLVER_ID,
)
from .runtime_parameters import (
    MC2_RUNTIME_CURVE_FIELDS,
    MC2_RUNTIME_FLOAT_FIELDS,
    MC2_RUNTIME_INT_FIELDS,
)
from .results import MC2_BONE_MOTION_ROTATION_ONLY_CONNECTED


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
            "particle_depth",
            "step_basic_reference",
            "effective_gravity",
            "particle_velocity",
            "distance_error",
            "tether_state",
            "bending_constraint",
            "motion_base_position",
            "motion_limits",
            "angle_restoration_target",
            "angle_limit_range",
            "center",
            "collision",
            "collision_contacts",
            "self_collision",
            "final_output_offset",
        ),
    },
}

MC2_DEBUG_FILTER_KEYS = (
    "show_topology",
    "show_attributes",
    "show_depth",
    "show_step_basic",
    "show_gravity",
    "show_velocity",
    "show_distance",
    "show_tether",
    "show_bending",
    "show_motion_base",
    "show_motion",
    "show_angle_restoration",
    "show_angle_limit",
    "show_center",
    "show_teleport_threshold",
    "show_teleport_status",
    "show_collision",
    "show_collision_contacts",
    "show_radii",
    "show_self_primitives",
    "show_self_grid",
    "show_self_candidates",
    "show_self_contacts",
    "show_output",
)

MC2_NATIVE_DEBUG_FILTER_KEYS = tuple(
    name for name in MC2_DEBUG_FILTER_KEYS if name not in ("show_center", "show_output")
)
MC2_SUBSTEP_DEBUG_FILTER_KEYS = tuple(
    name
    for name in MC2_NATIVE_DEBUG_FILTER_KEYS
    if name not in ("show_teleport_threshold", "show_teleport_status")
)

MC2_PRODUCT_DEBUG_FILTER_KEYS = (
    "show_topology",
    "show_attributes",
    "show_depth",
    "show_step_basic",
    "show_gravity",
    "show_velocity",
    "show_output",
    "show_center",
    "show_teleport_threshold",
    "show_teleport_status",
)


def _supports_interaction_debug(value) -> bool:
    methods = (
        "clear_debug_self_temporal_history",
        "request_debug_capture",
        "cancel_debug_capture",
        "debug_capture_state",
        "refresh_debug_draw_snapshot",
        "debug_self_temporal_history",
    )
    return value is not None and all(
        callable(getattr(value, name, None)) for name in methods
    )


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


def _annotate_external_contact_temporal(
    contacts: dict,
    history: dict,
    *,
    frame: int,
    generation: int,
) -> None:
    kinds = np.asarray(contacts.get("primitive_kinds"), dtype=np.int32).reshape((-1,))
    primitives = np.asarray(
        contacts.get("primitive_indices"), dtype=np.int32
    ).reshape((-1,))
    colliders = np.asarray(
        contacts.get("collider_indices"), dtype=np.int32
    ).reshape((-1,))
    positions = np.asarray(contacts.get("positions"), dtype=np.float32).reshape((-1, 3))
    normals = np.asarray(contacts.get("normals"), dtype=np.float32).reshape((-1, 3))
    corrections = np.asarray(
        contacts.get("corrections"), dtype=np.float32
    ).reshape((-1, 3))
    count = min(
        len(kinds),
        len(primitives),
        len(colliders),
        len(positions),
        len(normals),
        len(corrections),
    )
    previous_records = history.get("records") or {}
    history_valid = bool(
        "records" in history
        and int(history.get("frame", frame - 1)) == frame - 1
        and int(history.get("generation", generation)) == generation
    )
    current_records = {}
    states = np.zeros((count,), dtype=np.uint8)
    for index in range(count):
        key = (int(kinds[index]), int(primitives[index]), int(colliders[index]))
        current_records[key] = (
            key,
            tuple(map(float, positions[index])),
            tuple(map(float, normals[index])),
            tuple(map(float, corrections[index])),
        )
        if history_valid:
            states[index] = 2 if key in previous_records else 1
    lost_records = (
        [
            previous_records[key]
            for key in sorted(previous_records.keys() - current_records.keys())
        ]
        if history_valid
        else []
    )
    persistent_count = (
        len(previous_records.keys() & current_records.keys()) if history_valid else 0
    )
    new_count = len(current_records) - persistent_count if history_valid else 0
    lost_count = len(lost_records)
    contacts["temporal_states"] = _readonly(states)
    contacts["lost_primitive_kinds"] = _readonly(
        [record[0][0] for record in lost_records], np.int32
    )
    contacts["lost_primitive_indices"] = _readonly(
        [record[0][1] for record in lost_records], np.int32
    )
    contacts["lost_collider_indices"] = _readonly(
        [record[0][2] for record in lost_records], np.int32
    )
    contacts["lost_positions"] = _readonly(
        [record[1] for record in lost_records], np.float32
    ).reshape((-1, 3))
    contacts["lost_normals"] = _readonly(
        [record[2] for record in lost_records], np.float32
    ).reshape((-1, 3))
    contacts["lost_corrections"] = _readonly(
        [record[3] for record in lost_records], np.float32
    ).reshape((-1, 3))
    contacts["temporal"] = {
        "history_valid": history_valid,
        "active_count": len(current_records),
        "new_count": new_count,
        "persistent_count": persistent_count,
        "lost_count": lost_count,
        "churn_count": new_count + lost_count,
        "previous_frame": int(history.get("frame", -1)) if history_valid else -1,
        "frame": int(frame),
    }
    history.clear()
    history.update({
        "frame": int(frame),
        "generation": int(generation),
        "records": current_records,
    })


def _debug_primitive_center(positions, primitive):
    indices = [
        int(index)
        for index in primitive
        if 0 <= int(index) < len(positions)
    ]
    if not indices:
        return None
    return tuple(map(float, np.mean(positions[indices], axis=0)))


def _debug_values(value):
    return () if value is None else value


def _annotate_self_temporal(
    state: dict,
    history: dict,
    *,
    positions,
    frame: int,
    generation: int,
    scope,
) -> None:
    positions = np.asarray(
        _debug_values(positions), dtype=np.float32
    ).reshape((-1, 3))
    primitives = np.asarray(
        _debug_values(state.get("particle_indices")), dtype=np.int32
    ).reshape((-1, 3))
    scope = tuple(scope)
    if (
        int(history.get("generation", generation)) != generation
        or tuple(history.get("scope", scope)) != scope
    ):
        history.clear()

    contact_observed = all(
        state.get(name) is not None
        for name in ("contact_indices", "contact_types", "contact_enabled")
    )
    contacts = np.asarray(
        _debug_values(state.get("contact_indices")), dtype=np.int32
    ).reshape((-1, 2))
    contact_types = np.asarray(
        _debug_values(state.get("contact_types")), dtype=np.int32
    ).reshape((-1,))
    enabled = np.asarray(
        _debug_values(state.get("contact_enabled")), dtype=np.uint8
    ).reshape((-1,))
    contact_count = min(len(contacts), len(contact_types), len(enabled))
    previous_contact_state = history.get("contacts") or {}
    previous_contacts = previous_contact_state.get("records") or {}
    contact_history_valid = bool(
        contact_observed
        and "contacts" in history
        and int(previous_contact_state.get("frame", frame - 1)) == frame - 1
    )
    contact_states = np.zeros((contact_count,), dtype=np.uint8)
    current_contacts = {}
    for index in range(contact_count):
        if not enabled[index]:
            continue
        first, second = map(int, contacts[index])
        if not (0 <= first < len(primitives) and 0 <= second < len(primitives)):
            continue
        first_center = _debug_primitive_center(positions, primitives[first])
        second_center = _debug_primitive_center(positions, primitives[second])
        if first_center is None or second_center is None:
            continue
        if first <= second:
            pair = (first, second)
            centers = (first_center, second_center)
        else:
            pair = (second, first)
            centers = (second_center, first_center)
        key = (int(contact_types[index]), *pair)
        current_contacts[key] = (key, pair, centers)
        if contact_history_valid:
            contact_states[index] = 2 if key in previous_contacts else 1
    lost_contacts = (
        [
            previous_contacts[key]
            for key in sorted(previous_contacts.keys() - current_contacts.keys())
        ]
        if contact_history_valid
        else []
    )
    persistent_contacts = (
        len(previous_contacts.keys() & current_contacts.keys())
        if contact_history_valid
        else 0
    )
    new_contacts = (
        len(current_contacts) - persistent_contacts if contact_history_valid else 0
    )
    state["contact_temporal_states"] = _readonly(contact_states)
    state["lost_contact_types"] = _readonly(
        [record[0][0] for record in lost_contacts], np.int32
    )
    state["lost_contact_indices"] = _readonly(
        [record[1] for record in lost_contacts], np.int32
    ).reshape((-1, 2))
    state["lost_contact_positions"] = _readonly(
        [record[2] for record in lost_contacts], np.float32
    ).reshape((-1, 2, 3))
    state["contact_temporal"] = {
        "observed": contact_observed,
        "history_valid": contact_history_valid,
        "active_count": len(current_contacts),
        "new_count": new_contacts,
        "persistent_count": persistent_contacts,
        "lost_count": len(lost_contacts),
        "churn_count": new_contacts + len(lost_contacts),
        "previous_frame": (
            int(previous_contact_state.get("frame", -1))
            if contact_history_valid else -1
        ),
        "frame": int(frame),
        "observation_stride": 1,
    }

    intersection_observed = state.get("intersect_records") is not None
    intersections = np.asarray(
        _debug_values(state.get("intersect_records")), dtype=np.int32
    ).reshape((-1, 5))
    phase = int(frame) & 1
    phase_histories = history.get("intersection_phases") or {}
    previous_intersection_state = phase_histories.get(phase) or {}
    previous_intersections = previous_intersection_state.get("records") or {}
    intersection_history_valid = bool(
        intersection_observed
        and phase in phase_histories
        and int(previous_intersection_state.get("frame", frame - 2)) == frame - 2
    )
    intersection_states = np.zeros((len(intersections),), dtype=np.uint8)
    current_intersections = {}
    for index, record in enumerate(intersections):
        particle_indices = tuple(map(int, record))
        if min(particle_indices) < 0 or max(particle_indices) >= len(positions):
            continue
        edge = tuple(sorted(particle_indices[:2]))
        triangle = tuple(sorted(particle_indices[2:]))
        key = (*edge, *triangle)
        current_intersections[key] = (
            key,
            particle_indices,
            tuple(tuple(map(float, positions[particle])) for particle in particle_indices),
        )
        if intersection_history_valid:
            intersection_states[index] = (
                2 if key in previous_intersections else 1
            )
    lost_intersections = (
        [
            previous_intersections[key]
            for key in sorted(
                previous_intersections.keys() - current_intersections.keys()
            )
        ]
        if intersection_history_valid
        else []
    )
    persistent_intersections = (
        len(previous_intersections.keys() & current_intersections.keys())
        if intersection_history_valid
        else 0
    )
    new_intersections = (
        len(current_intersections) - persistent_intersections
        if intersection_history_valid else 0
    )
    state["intersection_temporal_states"] = _readonly(intersection_states)
    state["lost_intersect_records"] = _readonly(
        [record[1] for record in lost_intersections], np.int32
    ).reshape((-1, 5))
    state["lost_intersect_positions"] = _readonly(
        [record[2] for record in lost_intersections], np.float32
    ).reshape((-1, 5, 3))
    state["intersection_temporal"] = {
        "observed": intersection_observed,
        "history_valid": intersection_history_valid,
        "active_count": len(current_intersections),
        "new_count": new_intersections,
        "persistent_count": persistent_intersections,
        "lost_count": len(lost_intersections),
        "churn_count": new_intersections + len(lost_intersections),
        "previous_frame": (
            int(previous_intersection_state.get("frame", -1))
            if intersection_history_valid else -1
        ),
        "frame": int(frame),
        "phase": phase,
        "observation_stride": 2,
    }

    history.update({
        "generation": int(generation),
        "scope": scope,
    })
    if contact_observed:
        history["contacts"] = {
            "frame": int(frame),
            "records": current_contacts,
        }
    else:
        history.pop("contacts", None)
    if intersection_observed:
        phase_histories = dict(phase_histories)
        phase_histories[phase] = {
            "frame": int(frame),
            "records": current_intersections,
        }
        history["intersection_phases"] = phase_histories
    else:
        history.pop("intersection_phases", None)


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
    filters["show_self"] = any(
        bool(filters.get(name, False))
        for name in (
            "show_self_primitives",
            "show_self_grid",
            "show_self_candidates",
            "show_self_contacts",
        )
    )
    filters["show_interaction_contacts"] = bool(
        filters.get("show_collision_contacts", False)
    )
    has_modes = any(bool(filters.get(name, False)) for name in MC2_DEBUG_FILTER_KEYS)
    frame = int(getattr(world.frame_context, "frame", 0) or 0)
    task_filters = normalize_mc2_task_filters(filters.get("task_filter"))
    setup_filter = str(filters.get("setup_filter") or "all").strip().lower()
    requested = 0
    for slot in world.solver_slots.values():
        if slot.kind == MC2_FUSED_PRODUCT_SLOT_KIND:
            owner = slot.data.get("owner")
            program = getattr(getattr(owner, "compiled", None), "program", None)
            if program is None:
                continue
            task_tokens = (str(slot.slot_id), *tuple(program.partition_ids))
            matches_task = not task_filters or any(
                token in identity
                for token in task_filters
                for identity in task_tokens
            )
            matches_setup = setup_filter in ("", "all", str(program.setup_type).lower())
            state = slot.data.setdefault("_debug_capture_state", {})
            slot.data.pop("_debug_product_step_basic", None)
            if not (matches_task and matches_setup and has_modes):
                state.update({"requested": False, "filters": filters})
                continue
            state.update({
                "requested": True,
                "request_frame": frame,
                "filters": filters,
            })
            requested += 1
            continue
        if slot.kind != MC2_SLOT_KIND:
            continue
        spec = slot.data.get("spec")
        if spec is None:
            continue
        state = slot.data.setdefault("_debug_capture_state", {})
        matches_task = _matches_task_filter(spec.task_id, task_filters)
        matches_setup = setup_filter in ("", "all", str(spec.setup_type).lower())
        if not filters.get("show_collision_contacts", False) or not (
            matches_task and matches_setup
        ):
            slot.data.pop("_debug_external_contact_history", None)
        if not filters.get("show_self_contacts", False) or not (
            matches_task and matches_setup
        ):
            slot.data.pop("_debug_self_temporal_history", None)
        if not (matches_task and matches_setup and has_modes):
            state.update({"requested": False, "filters": filters})
            native_context = slot.data.get("native_context")
            if (
                native_context is not None
                and native_context.has_debug_capture_request
            ):
                native_context.clear_debug_capture_requests()
            continue
        state.update({
            "requested": True,
            "request_frame": frame,
            "filters": filters,
        })
        requested += 1
    interaction = world.backend_resources.get(MC2_INTERACTION_RESOURCE_KEY)
    if _supports_interaction_debug(interaction):
        if not (has_modes and requested and filters.get("show_self_contacts", False)):
            interaction.clear_debug_self_temporal_history()
        if has_modes and requested and (
            filters["show_self"] or filters["show_interaction_contacts"]
        ):
            interaction.request_debug_capture(frame, filters)
        else:
            interaction.cancel_debug_capture(filters)
    return requested


def _product_topology_payload(compiled, positions, *, include_depth=False) -> dict:
    program = compiled.program
    primitive_tables = {table.kind: table for table in program.primitive_tables}
    constraint_tables = {table.kind: table for table in program.constraint_tables}
    edge_table = primitive_tables.get("edge") or constraint_tables.get("distance")
    triangle_table = primitive_tables.get("triangle")
    edges = (
        np.empty((0, 2), dtype=np.int32)
        if edge_table is None
        else np.asarray(edge_table.indices, dtype=np.int32).reshape((-1, 2))
    )
    triangles = (
        np.empty((0, 3), dtype=np.int32)
        if triangle_table is None
        else np.asarray(triangle_table.indices, dtype=np.int32).reshape((-1, 3))
    )
    result = {
        "connection_model": "product_domain_v1",
        "connection_mode": 0,
        "vertex_identities": tuple(
            (
                str(program.partition_ids[int(partition)]),
                int(source),
            )
            for partition, source in zip(
                program.particle_partition_index,
                program.particle_source_element,
            )
        ),
        "vertex_attributes": _readonly(program.particle_attribute_flags, np.uint8),
        "edges": _readonly(edges, np.int32),
        "triangles": _readonly(triangles, np.int32),
        "longitudinal_edges": _readonly(edges, np.int32),
        "lateral_edges": _readonly((), np.int32).reshape((-1, 2)),
        "chain_indices": _readonly((), np.int32),
        "chain_depths": _readonly((), np.int32),
        "positions": _readonly(positions),
    }
    if include_depth:
        parents = (
            np.full(program.particle_count, -1, dtype=np.int32)
            if program.baseline_parent_indices is None
            else np.asarray(program.baseline_parent_indices, dtype=np.int32)
        )
        roots = np.full(program.particle_count, -1, dtype=np.int32)
        for fragment, view in zip(compiled.fragments, program.partition_particle_views):
            indices = np.asarray(view.resolved_indices(), dtype=np.int64)
            baseline = _baseline_for_static(fragment)
            local_roots = np.asarray(
                getattr(baseline, "root_indices", ()), dtype=np.int64
            ).reshape((-1,))
            if len(indices) != len(local_roots):
                raise RuntimeError("产品 Depth 调试的 baseline root 数量与分区粒子数不一致")
            valid = (local_roots >= 0) & (local_roots < len(indices))
            roots[indices[valid]] = indices[local_roots[valid]].astype(np.int32)
        particle_table = compiled.parameters.particle_parameters
        try:
            depth_column = particle_table.fields.index("depth")
        except ValueError as exc:
            raise RuntimeError("产品 Depth 调试缺少 depth 参数列") from exc
        result.update({
            "baseline_parent_indices": _readonly(parents, np.int32),
            "baseline_root_indices": _readonly(roots, np.int32),
            "baseline_depths": _readonly(
                particle_table.values[:, depth_column], np.float32
            ),
        })
    return result


def _product_gravity_payload(compiled, frame_packet, center_raw) -> dict:
    program = compiled.program
    table = compiled.parameters.partition_parameters
    fields = {name: index for index, name in enumerate(table.fields)}
    required = (
        "gravity", "gravity_direction_x", "gravity_direction_y",
        "gravity_direction_z",
    )
    if any(name not in fields for name in required):
        raise RuntimeError("产品 Gravity 调试缺少统一域重力参数列")
    strengths = np.asarray(
        table.values[:, fields["gravity"]], dtype=np.float32
    )
    directions = np.column_stack(tuple(
        table.values[:, fields[name]] for name in required[1:]
    )).astype(np.float32, copy=False)
    ratios = np.asarray(
        center_raw.get("gravity_ratios"), dtype=np.float32
    ).reshape((-1,))
    if ratios.shape != (program.partition_count,):
        raise RuntimeError("产品 Gravity 调试的 Center gravity_ratio 数量不匹配")
    partition_indices = np.asarray(
        program.particle_partition_index, dtype=np.int64
    )
    raw_particle = strengths[partition_indices]
    effective_partition = strengths * ratios
    effective_particle = effective_partition[partition_indices]
    particle_directions = directions[partition_indices]
    return {
        "schema": "mc2_product_gravity_debug_v1",
        "gravity_direction": _readonly(directions[0], np.float32),
        "gravity_strength": float(np.max(strengths, initial=0.0)),
        "gravity_ratio": float(np.max(ratios, initial=0.0)),
        "gravity_effective_strength": float(
            np.max(effective_partition, initial=0.0)
        ),
        "scale_ratio": 1.0,
        "gravity_directions": _readonly(particle_directions, np.float32),
        "gravity_raw_strengths": _readonly(raw_particle, np.float32),
        "gravity_effective_strengths": _readonly(
            effective_particle, np.float32
        ),
        "partitions": tuple({
            "partition_id": str(partition_id),
            "direction": _readonly(directions[index], np.float32),
            "strength": float(strengths[index]),
            "gravity_ratio": float(ratios[index]),
            "effective_strength": float(effective_partition[index]),
        } for index, partition_id in enumerate(program.partition_ids)),
        "frame": int(frame_packet.frame),
        "generation": int(frame_packet.generation),
    }


def _product_center_payload(program, frame_packet, raw) -> tuple[dict, dict]:
    center_partitions = []
    teleport_partitions = []
    flags = np.asarray(raw["teleport_flags"], dtype=np.uint32)
    modes = np.asarray(raw["teleport_modes"], dtype=np.int32)
    for index, partition_id in enumerate(program.partition_ids):
        frame_pose = {
            "component_world_position": frame_packet.partition_world_position[index],
            "component_world_rotation_xyzw": frame_packet.partition_world_rotation[index],
            "anchor_identity": (
                str(partition_id) if int(frame_packet.anchor_present[index]) else ""
            ),
            "anchor_world_position": frame_packet.anchor_world_position[index],
            "anchor_world_rotation_xyzw": frame_packet.anchor_world_rotation[index],
        }
        frame_shift = {
            "old_frame_world_position": raw["old_frame_world_positions"][index],
            "old_frame_world_rotation_xyzw": raw[
                "old_frame_world_rotations_xyzw"
            ][index],
            "now_world_position": raw["now_world_positions"][index],
            "now_world_rotation_xyzw": raw["now_world_rotations_xyzw"][index],
            "teleport_origin_world_position": raw["frame_world_positions"][index],
            "frame_component_shift_vector": raw[
                "frame_component_shift_vectors"
            ][index],
            "frame_component_shift_rotation_xyzw": raw[
                "frame_component_shift_rotations_xyzw"
            ][index],
            "raw_component_delta": raw["raw_component_deltas"][index],
            "anchor_shift_vector": raw["anchor_shift_vectors"][index],
            "smoothing_shift_vector": raw["smoothing_shift_vectors"][index],
            "world_shift_vector": raw["world_shift_vectors"][index],
            "movement_speed_limited": bool(raw["movement_speed_limited"][index]),
            "rotation_speed_limited": bool(raw["rotation_speed_limited"][index]),
        }
        center_partitions.append({
            "partition_id": str(partition_id),
            "frame_pose": frame_pose,
            "frame_shift": frame_shift,
            "step": {
                "step_vector": raw["step_vectors"][index],
                "inertia_vector": raw["inertia_vectors"][index],
                "now_world_position": raw["now_world_positions"][index],
            },
            "task_teleport": {},
            "negative_scale_transition": {},
            "frame_sync": {},
        })
        flag = int(flags[index])
        teleport_partitions.append({
            "partition_id": str(partition_id),
            "old_reference_position": raw["old_frame_world_positions"][index],
            "reference_position": raw["now_world_positions"][index],
            "old_reference_rotation_xyzw": raw[
                "old_frame_world_rotations_xyzw"
            ][index],
            "reference_rotation_xyzw": raw["now_world_rotations_xyzw"][index],
            "rotation_axis": raw["teleport_rotation_axes"][index],
            "mode": int(modes[index]),
            "applied": bool(flag & 1),
            "keep": bool(flag & 2),
            "reset": bool(flag & 4),
            "measured_distance": float(raw["teleport_measured_distances"][index]),
            "distance_threshold": float(raw["teleport_distance_thresholds"][index]),
            "measured_rotation_degrees": float(
                raw["teleport_measured_rotation_degrees"][index]
            ),
            "rotation_threshold_degrees": float(
                raw["teleport_rotation_threshold_degrees"][index]
            ),
        })
    return (
        {"schema": "mc2_product_center_debug_v1", "partitions": tuple(center_partitions)},
        {"schema": "mc2_product_teleport_debug_v1", "partitions": tuple(teleport_partitions)},
    )


def _product_output_payload(slot, compiled, frame_packet, output) -> dict:
    program = compiled.program
    base_positions = _readonly(frame_packet.animated_base_world_positions)
    target_positions = np.asarray(output.world_positions, dtype=np.float32)
    applied = np.ones((program.particle_count,), dtype=np.uint8)
    targets = tuple(target.target_id for target in program.output_targets)
    motion_modes = ()
    writeback_schema = "mc2_domain_output_v1"
    target_kind = "mesh_vertex"
    rotation_only_count = 0
    position_rotation_count = 0
    has_plan = True
    if program.setup_type != MC2_SETUP_MESH_CLOTH:
        plans = tuple((slot.data.get("output_writeback_plans") or {}).values())
        records = tuple(
            record
            for plan in plans
            for batch in plan.get("batches") or ()
            for record in batch.get("records") or ()
        )
        mode_by_name = {}
        for record in records:
            name = str(record.get("bone_name") or "")
            mode = str(record.get("motion_mode") or "")
            if not name or not mode or name in mode_by_name:
                raise RuntimeError("Bone产品调试writeback plan包含缺项或重名")
            mode_by_name[name] = mode
        logical_names = []
        for partition, source in zip(
            program.particle_partition_index,
            program.particle_source_element,
        ):
            fragment = compiled.fragments[int(partition)]
            identities = tuple(fragment.final_proxy.vertex_identities)
            source_index = int(source)
            if source_index >= len(identities):
                raise RuntimeError("Bone产品调试output map越界")
            logical_names.append(str(identities[source_index]))
        if set(logical_names) != set(mode_by_name):
            raise RuntimeError("Bone产品调试output map与writeback plan不一致")
        motion_modes = tuple((name, mode_by_name[name]) for name in logical_names)
        for index, (_name, mode) in enumerate(motion_modes):
            if mode == MC2_BONE_MOTION_ROTATION_ONLY_CONNECTED:
                applied[index] = 0
        target_positions = target_positions.copy()
        target_positions[applied == 0] = base_positions[applied == 0]
        targets = tuple(logical_names)
        target_kind = "bone"
        rotation_only_count = int(np.count_nonzero(applied == 0))
        position_rotation_count = int(np.count_nonzero(applied != 0))
        schemas = {
            str(plan.get("schema") or "") for plan in plans
            if str(plan.get("schema") or "")
        }
        if len(schemas) != 1:
            raise RuntimeError("Bone产品调试writeback plan schema不唯一")
        writeback_schema = schemas.pop()
        has_plan = bool(plans)
    target_positions = _readonly(target_positions)
    applied.flags.writeable = False
    return {
        "base_positions": base_positions,
        "target_positions": target_positions,
        "world_offsets": _readonly(target_positions - base_positions),
        "mesh_object_local_offsets": None,
        "translation_applied": applied,
        "writeback_schema": writeback_schema,
        "writeback_target_count": len(targets),
        "has_writeback_plan": has_plan,
        "writeback_targets": targets,
        "writeback_target_kind": target_kind,
        "writeback_motion_modes": motion_modes,
        "rotation_only_connected_count": rotation_only_count,
        "position_rotation_count": position_rotation_count,
    }


def capture_requested_mc2_product_debug(world, slots) -> int:
    frame = int(getattr(world.frame_context, "frame", 0) or 0)
    generation = int(world.generation)
    captured = 0
    for slot in slots:
        if getattr(slot, "kind", None) != MC2_FUSED_PRODUCT_SLOT_KIND:
            continue
        state = slot.data.get("_debug_capture_state")
        if not _state_requested(state, frame):
            continue
        filters = dict(state.get("filters") or {})
        frame_packet = slot.data.get("frame_packet")
        step_basic = slot.data.get("_debug_product_step_basic")
        if filters.get("show_step_basic", False) and (
            not isinstance(step_basic, dict)
            or frame_packet is None
            or int(step_basic.get("frame", -1)) != int(frame_packet.frame)
            or int(step_basic.get("generation", -1)) != int(frame_packet.generation)
        ):
            state["waiting_for_substep"] = True
            continue
        state.pop("waiting_for_substep", None)
        started = time.perf_counter()
        try:
            owner = slot.data.get("owner")
            compiled = getattr(owner, "compiled", None)
            program = getattr(compiled, "program", None)
            output = slot.data.get("domain_output")
            if program is None or frame_packet is None or output is None:
                raise RuntimeError("产品调试捕获需要完整的owner、frame和logical output")
            requested_modes = tuple(
                name for name in MC2_DEBUG_FILTER_KEYS if filters.get(name, False)
            )
            supported_filters = MC2_PRODUCT_DEBUG_FILTER_KEYS
            unsupported = tuple(
                name for name in requested_modes
                if name not in supported_filters
            )
            positions = _readonly(output.world_positions)
            native = {"positions": positions}
            if filters.get("show_velocity", False):
                native.update(_freeze_value(owner.read_debug_state()))
            center = {}
            teleport = {}
            if (
                filters.get("show_center", False)
                or filters.get("show_teleport_threshold", False)
                or filters.get("show_teleport_status", False)
                or filters.get("show_gravity", False)
            ):
                center_raw = _freeze_value(owner.read_center_debug_state())
                center, teleport = _product_center_payload(
                    program, frame_packet, center_raw
                )
            needs_topology = any(filters.get(name, False) for name in (
                "show_topology", "show_attributes", "show_depth",
                "show_step_basic", "show_gravity",
            ))
            topology = (
                _product_topology_payload(
                    compiled,
                    positions,
                    include_depth=filters.get("show_depth", False),
                )
                if needs_topology
                else {}
            )
            motion = (
                {
                    "step_basic_positions": _readonly(
                        step_basic["positions"], np.float32
                    ),
                    "step_basic_rotations_xyzw": _readonly(
                        step_basic["rotations"], np.float32
                    ),
                    "update_index": int(step_basic["update_index"]),
                }
                if filters.get("show_step_basic", False)
                else {}
            )
            parameters = (
                _product_gravity_payload(compiled, frame_packet, center_raw)
                if filters.get("show_gravity", False)
                else {}
            )
            output_payload = (
                _product_output_payload(
                    slot, compiled, frame_packet, output
                )
                if filters.get("show_output", False)
                else {}
            )
            snapshot = {
                "source": "mc2_product_capture",
                "schema": "mc2_product_debug_snapshot_v1",
                "slot_id": str(slot.slot_id),
                "task_id": str(slot.slot_id),
                "setup_type": str(program.setup_type),
                "partition_ids": tuple(program.partition_ids),
                "frame": frame,
                "generation": generation,
                "filters": filters,
                "supported_filters": supported_filters,
                "unsupported_filters": unsupported,
                "native": native,
                "topology": topology,
                "parameters": parameters,
                "motion": motion,
                "center": center if filters.get("show_center", False) else {},
                "teleport": (
                    teleport
                    if filters.get("show_teleport_threshold", False)
                    or filters.get("show_teleport_status", False)
                    else {}
                ),
                "collision": {},
                "self_collision": None,
                "output": output_payload,
            }
            slot.data["_debug_draw_snapshot"] = snapshot
            state.pop("error", None)
            state["captured_frame"] = frame
            captured += 1
        except Exception as exc:
            state["error"] = str(exc)
        finally:
            slot.data.pop("_debug_product_step_basic", None)
            state["requested"] = False
            state["attempted_frame"] = frame
            state["capture_ms"] = (time.perf_counter() - started) * 1000.0
    return captured


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


def _topology_payload(slot, native_snapshot, *, include_depth=False) -> dict:
    topology = slot.data.get("topology")
    static = _active_static(slot)
    proxy = getattr(static, "final_proxy", None)
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
    result = {
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
        "positions": native_snapshot["positions"],
    }
    if include_depth:
        native_baseline = native_snapshot.get("baseline") or {}
        result.update({
            "baseline_parent_indices": native_baseline.get("parent_indices"),
            "baseline_root_indices": native_baseline.get("root_indices"),
            "baseline_depths": native_baseline.get("depths"),
        })
    return result


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
        "angle_limit_target_positions": native_snapshot.get(
            "angle_limit_target_positions"
        ),
        "angle_limit_target_vectors": native_snapshot.get(
            "angle_limit_target_vectors"
        ),
        "angle_limit_target_valid": native_snapshot.get(
            "angle_limit_target_valid"
        ),
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
        "scale_ratio": scale_ratio,
        "negative_scale_sign": float(native.get("negative_scale_sign", 1.0) or 1.0),
        "animation_pose_ratio": float(native.get("animation_pose_ratio", 0.0) or 0.0),
        "particle_speed_limit": float(floats["particle_speed_limit"]),
        "tether_compression": float(floats["tether_compression_limit"]),
        "tether_stretch": float(floats["tether_stretch_limit"]),
        "bending_stiffness": float(floats["bending_stiffness"]),
        "damping": _sample_curve(curves["damping"], depths),
        "distance_stiffness": _sample_curve(curves["distance_stiffness"], depths),
    }


def _tether_constraint_record_payload(native_snapshot, motion, parameters) -> dict:
    distance = native_snapshot.get("distance_tether") or {}
    constraint = (native_snapshot.get("constraint_results") or {}).get(
        "tether"
    ) or {}
    roots = distance.get("baseline_roots")
    step_basic = motion.get("step_basic_positions")
    origins = constraint.get("origins")
    corrections = constraint.get("corrections")
    native = native_snapshot.get("native") or {}
    empty = {
        "enabled": bool(native.get("tether_enabled", False)),
        "vertices": _readonly((), np.int32),
        "roots": _readonly((), np.int32),
        "origins": _readonly((), np.float32).reshape((0, 3)),
        "root_origins": _readonly((), np.float32).reshape((0, 3)),
        "corrections": _readonly((), np.float32).reshape((0, 3)),
        "ratios": _readonly((), np.float32),
        "minimums": _readonly((), np.float32),
        "maximums": _readonly((), np.float32),
        "errors": _readonly((), np.float32),
        "states": _readonly((), np.int8),
    }
    if roots is None or step_basic is None or origins is None or corrections is None:
        return empty
    roots = np.asarray(roots, dtype=np.int32).reshape((-1,))
    step_basic = np.asarray(step_basic, dtype=np.float32).reshape((-1, 3))
    origins = np.asarray(origins, dtype=np.float32).reshape((-1, 3))
    corrections = np.asarray(corrections, dtype=np.float32).reshape((-1, 3))
    count = min(len(roots), len(step_basic), len(origins), len(corrections))
    compression = max(
        0.0, min(1.0, float(parameters.get("tether_compression", 0.0) or 0.0))
    )
    stretch = max(0.0, float(parameters.get("tether_stretch", 0.0) or 0.0))
    records = []
    for vertex in range(count):
        root = int(roots[vertex])
        if root < 0 or root >= count or root == vertex:
            continue
        rest = float(np.linalg.norm(step_basic[vertex] - step_basic[root]))
        if rest <= 1.0e-8:
            continue
        distance_value = float(np.linalg.norm(origins[vertex] - origins[root]))
        minimum = rest * (1.0 - compression)
        maximum = rest * (1.0 + stretch)
        error = (
            distance_value - minimum
            if distance_value < minimum
            else distance_value - maximum if distance_value > maximum else 0.0
        )
        correction_length = float(np.linalg.norm(corrections[vertex]))
        if correction_length > 1.0e-8:
            state = -2 if error < 0.0 else 2
        else:
            near_width = max(rest * 0.05, 1.0e-5)
            if minimum > 1.0e-8 and 0.0 <= distance_value - minimum <= near_width:
                state = -1
            elif 0.0 <= maximum - distance_value <= near_width:
                state = 1
            else:
                state = 0
        records.append((
            vertex,
            root,
            origins[vertex],
            origins[root],
            corrections[vertex],
            distance_value / rest,
            minimum,
            maximum,
            error,
            state,
        ))
    if not records:
        return empty
    return {
        "enabled": empty["enabled"],
        "vertices": _readonly([item[0] for item in records], np.int32),
        "roots": _readonly([item[1] for item in records], np.int32),
        "origins": _readonly([item[2] for item in records], np.float32),
        "root_origins": _readonly([item[3] for item in records], np.float32),
        "corrections": _readonly([item[4] for item in records], np.float32),
        "ratios": _readonly([item[5] for item in records], np.float32),
        "minimums": _readonly([item[6] for item in records], np.float32),
        "maximums": _readonly([item[7] for item in records], np.float32),
        "errors": _readonly([item[8] for item in records], np.float32),
        "states": _readonly([item[9] for item in records], np.int8),
    }


def _distance_constraint_record_payload(native_snapshot) -> dict:
    distance = native_snapshot.get("distance_tether") or {}
    results = native_snapshot.get("distance_results") or {}
    constraint = (native_snapshot.get("constraint_results") or {}).get(
        "distance"
    ) or {}
    ranges = distance.get("distance_ranges")
    targets = distance.get("distance_targets")
    origins = results.get("origins")
    corrections = results.get("corrections")
    lengths = results.get("lengths")
    rests = results.get("rests")
    valid = results.get("valid")
    pass_origins = constraint.get("origins")
    empty = {
        "phases": _readonly((), np.int8),
        "record_indices": _readonly((), np.int32),
        "vertices": _readonly((), np.int32),
        "targets": _readonly((), np.int32),
        "origins": _readonly((), np.float32).reshape((0, 3)),
        "target_origins": _readonly((), np.float32).reshape((0, 3)),
        "corrections": _readonly((), np.float32).reshape((0, 3)),
        "lengths": _readonly((), np.float32),
        "rests": _readonly((), np.float32),
        "errors": _readonly((), np.float32),
        "normalized_errors": _readonly((), np.float32),
        "states": _readonly((), np.int8),
    }
    if any(
        value is None
        for value in (
            ranges, targets, origins, corrections, lengths, rests, valid,
            pass_origins,
        )
    ):
        return empty
    ranges = np.asarray(ranges, dtype=np.int32).reshape((-1, 2))
    targets = np.asarray(targets, dtype=np.int32).reshape((-1,))
    record_count = len(targets)
    origins = np.asarray(origins, dtype=np.float32).reshape((2, record_count, 3))
    corrections = np.asarray(corrections, dtype=np.float32).reshape(
        (2, record_count, 3)
    )
    lengths = np.asarray(lengths, dtype=np.float32).reshape((2, record_count))
    rests = np.asarray(rests, dtype=np.float32).reshape((2, record_count))
    valid = np.asarray(valid, dtype=np.uint8).reshape((2, record_count))
    pass_origins = np.asarray(pass_origins, dtype=np.float32).reshape(
        (2, -1, 3)
    )
    owners = np.full((record_count,), -1, dtype=np.int32)
    for vertex, (start, count) in enumerate(ranges):
        start = int(start)
        count = int(count)
        if start < 0 or count < 0 or start + count > record_count:
            continue
        owners[start:start + count] = vertex
    records = []
    for phase in range(2):
        for record in range(record_count):
            if not valid[phase, record]:
                continue
            vertex = int(owners[record])
            target = int(targets[record])
            if (
                vertex < 0
                or vertex >= pass_origins.shape[1]
                or target < 0
                or target >= pass_origins.shape[1]
            ):
                continue
            length = float(lengths[phase, record])
            rest = float(rests[phase, record])
            error = length - rest
            correction_length = float(np.linalg.norm(corrections[phase, record]))
            if correction_length > 1.0e-8:
                state = -2 if error < 0.0 else 2
            elif abs(error) > 1.0e-8 and abs(error) <= max(rest * 0.02, 1.0e-5):
                state = -1 if error < 0.0 else 1
            else:
                state = 0
            records.append((
                phase,
                record,
                vertex,
                target,
                origins[phase, record],
                pass_origins[phase, target],
                corrections[phase, record],
                length,
                rest,
                error,
                error / max(rest, 1.0e-8),
                state,
            ))
    if not records:
        return empty
    return {
        "phases": _readonly([item[0] for item in records], np.int8),
        "record_indices": _readonly([item[1] for item in records], np.int32),
        "vertices": _readonly([item[2] for item in records], np.int32),
        "targets": _readonly([item[3] for item in records], np.int32),
        "origins": _readonly([item[4] for item in records], np.float32),
        "target_origins": _readonly([item[5] for item in records], np.float32),
        "corrections": _readonly([item[6] for item in records], np.float32),
        "lengths": _readonly([item[7] for item in records], np.float32),
        "rests": _readonly([item[8] for item in records], np.float32),
        "errors": _readonly([item[9] for item in records], np.float32),
        "normalized_errors": _readonly([item[10] for item in records], np.float32),
        "states": _readonly([item[11] for item in records], np.int8),
    }


def _bending_constraint_record_payload(native_snapshot, parameters) -> dict:
    bending = native_snapshot.get("bending") or {}
    results = native_snapshot.get("bending_results") or {}
    quads = bending.get("quads")
    raw_rests = bending.get("rests")
    markers = bending.get("markers")
    origins = results.get("origins")
    corrections = results.get("corrections")
    active = results.get("valid")
    empty = {
        "record_indices": _readonly((), np.int32),
        "kinds": _readonly((), np.int8),
        "markers": _readonly((), np.int8),
        "vertices": _readonly((), np.int32).reshape((0, 4)),
        "origins": _readonly((), np.float32).reshape((0, 4, 3)),
        "corrections": _readonly((), np.float32).reshape((0, 4, 3)),
        "currents": _readonly((), np.float32),
        "rests": _readonly((), np.float32),
        "errors": _readonly((), np.float32),
        "normalized_errors": _readonly((), np.float32),
        "states": _readonly((), np.int8),
    }
    if any(
        value is None
        for value in (quads, raw_rests, markers, origins, corrections, active)
    ):
        return empty
    quads = np.asarray(quads, dtype=np.int32).reshape((-1, 4))
    record_count = len(quads)
    raw_rests = np.asarray(raw_rests, dtype=np.float32).reshape((-1,))
    markers = np.asarray(markers, dtype=np.int8).reshape((-1,))
    origins = np.asarray(origins, dtype=np.float32).reshape(
        (record_count, 4, 3)
    )
    corrections = np.asarray(corrections, dtype=np.float32).reshape(
        (record_count, 4, 3)
    )
    active = np.asarray(active, dtype=np.uint8).reshape((-1,))
    if not (
        len(raw_rests) == len(markers) == len(active) == record_count
    ):
        return empty
    scale = float(parameters.get("scale_ratio", 1.0) or 1.0)
    negative_sign = float(parameters.get("negative_scale_sign", 1.0) or 1.0)
    currents = np.zeros((record_count,), dtype=np.float32)
    rests = np.zeros((record_count,), dtype=np.float32)
    kinds = np.zeros((record_count,), dtype=np.int8)
    for record in range(record_count):
        points = origins[record]
        marker = int(markers[record])
        if marker == 100:
            kinds[record] = 1
            currents[record] = np.float32(
                np.dot(
                    np.cross(points[1] - points[0], points[2] - points[0]),
                    points[3] - points[0],
                ) / 6.0 * 1000.0
            )
            rests[record] = np.float32(
                raw_rests[record] * scale * negative_sign
            )
            continue
        edge = points[3] - points[2]
        normal_a = np.cross(points[2] - points[0], points[3] - points[0])
        normal_b = np.cross(points[3] - points[1], points[2] - points[1])
        length_a = float(np.linalg.norm(normal_a))
        length_b = float(np.linalg.norm(normal_b))
        if float(np.linalg.norm(edge)) > 1.0e-8 and length_a > 0.0 and length_b > 0.0:
            normal_a /= length_a
            normal_b /= length_b
            angle = float(np.arccos(np.clip(np.dot(normal_a, normal_b), -1.0, 1.0)))
            direction = float(np.dot(np.cross(normal_a, normal_b), edge))
            currents[record] = np.float32(
                -angle if direction < 0.0 else angle if direction > 0.0 else 0.0
            )
        rests[record] = np.float32(
            raw_rests[record]
            * (-1.0 if marker < 0 else 1.0)
            * negative_sign
        )
    errors = rests - currents
    normalized_errors = errors / np.maximum(np.abs(rests), np.float32(1.0e-8))
    states = np.zeros((record_count,), dtype=np.int8)
    states[(active != 0) & (errors < 0.0)] = -2
    states[(active != 0) & (errors >= 0.0)] = 2
    return {
        "record_indices": _readonly(np.arange(record_count), np.int32),
        "kinds": _readonly(kinds, np.int8),
        "markers": _readonly(markers, np.int8),
        "vertices": _readonly(quads, np.int32),
        "origins": _readonly(origins, np.float32),
        "corrections": _readonly(corrections, np.float32),
        "currents": _readonly(currents, np.float32),
        "rests": _readonly(rests, np.float32),
        "errors": _readonly(errors, np.float32),
        "normalized_errors": _readonly(normalized_errors, np.float32),
        "states": _readonly(states, np.int8),
    }


def _motion_constraint_record_payload(native_snapshot, motion) -> dict:
    results = native_snapshot.get("motion_results") or {}
    origins = results.get("origins")
    corrections = results.get("corrections")
    valid = results.get("valid")
    base = motion.get("motion_base_positions")
    rotations = motion.get("motion_base_rotations_xyzw")
    empty = {
        "branches": _readonly((), np.int8),
        "vertices": _readonly((), np.int32),
        "origins": _readonly((), np.float32).reshape((0, 3)),
        "target_origins": _readonly((), np.float32).reshape((0, 3)),
        "corrections": _readonly((), np.float32).reshape((0, 3)),
        "distances": _readonly((), np.float32),
        "limits": _readonly((), np.float32),
        "errors": _readonly((), np.float32),
        "states": _readonly((), np.int8),
    }
    if any(
        value is None
        for value in (origins, corrections, valid, base, rotations)
    ):
        return empty
    origins = np.asarray(origins, dtype=np.float32)
    corrections = np.asarray(corrections, dtype=np.float32)
    valid = np.asarray(valid, dtype=np.uint8)
    base = np.asarray(base, dtype=np.float32).reshape((-1, 3))
    rotations = np.asarray(rotations, dtype=np.float32).reshape((-1, 4))
    vertex_count = len(base)
    origins = origins.reshape((2, vertex_count, 3))
    corrections = corrections.reshape((2, vertex_count, 3))
    valid = valid.reshape((2, vertex_count))
    axis_values = np.asarray(
        ((1, 0, 0), (0, 1, 0), (0, 0, 1),
         (-1, 0, 0), (0, -1, 0), (0, 0, -1)),
        dtype=np.float32,
    )
    local_axis = axis_values[max(0, min(5, int(motion.get("normal_axis", 1))))]
    q_xyz = rotations[:, :3]
    q_w = rotations[:, 3:4]
    local_axes = np.broadcast_to(local_axis, (vertex_count, 3))
    rotated_axes = local_axes + 2.0 * np.cross(
        q_xyz, np.cross(q_xyz, local_axes) + q_w * local_axes
    )
    backstop_radius = max(float(motion.get("backstop_radius", 0.0) or 0.0), 0.0)
    backstop_distances = np.asarray(
        motion.get("backstop_distances"), dtype=np.float32
    ).reshape((-1,))
    max_distances = np.asarray(
        motion.get("max_distances"), dtype=np.float32
    ).reshape((-1,))
    backstop_centers = base - rotated_axes * (
        backstop_distances[:, None] + np.float32(backstop_radius)
    )
    records = []
    for branch in range(2):
        for vertex in range(vertex_count):
            if not valid[branch, vertex]:
                continue
            target = base[vertex] if branch == 0 else backstop_centers[vertex]
            distance = float(np.linalg.norm(origins[branch, vertex] - target))
            limit = float(max_distances[vertex]) if branch == 0 else backstop_radius
            error = distance - limit if branch == 0 else limit - distance
            correction_length = float(np.linalg.norm(corrections[branch, vertex]))
            near_width = max(limit * 0.05, 1.0e-5)
            state = 2 if correction_length > 1.0e-8 else 1 if error >= -near_width else 0
            records.append((
                branch,
                vertex,
                origins[branch, vertex],
                target,
                corrections[branch, vertex],
                distance,
                limit,
                error,
                state,
            ))
    if not records:
        return empty
    return {
        "branches": _readonly([item[0] for item in records], np.int8),
        "vertices": _readonly([item[1] for item in records], np.int32),
        "origins": _readonly([item[2] for item in records], np.float32),
        "target_origins": _readonly([item[3] for item in records], np.float32),
        "corrections": _readonly([item[4] for item in records], np.float32),
        "distances": _readonly([item[5] for item in records], np.float32),
        "limits": _readonly([item[6] for item in records], np.float32),
        "errors": _readonly([item[7] for item in records], np.float32),
        "states": _readonly([item[8] for item in records], np.int8),
    }


def _angle_constraint_record_payload(native_snapshot, selected_branch: int) -> dict:
    results = native_snapshot.get("angle_results") or {}
    origins = results.get("origins")
    corrections = results.get("corrections")
    currents = results.get("currents")
    limits = results.get("limits")
    children = results.get("children")
    parents = results.get("parents")
    valid = results.get("valid")
    empty = {
        "branches": _readonly((), np.int8),
        "iterations": _readonly((), np.int8),
        "record_indices": _readonly((), np.int32),
        "children": _readonly((), np.int32),
        "parents": _readonly((), np.int32),
        "origins": _readonly((), np.float32).reshape((0, 3)),
        "parent_origins": _readonly((), np.float32).reshape((0, 3)),
        "corrections": _readonly((), np.float32).reshape((0, 3)),
        "parent_corrections": _readonly((), np.float32).reshape((0, 3)),
        "currents": _readonly((), np.float32),
        "limits": _readonly((), np.float32),
        "errors": _readonly((), np.float32),
        "normalized_errors": _readonly((), np.float32),
        "states": _readonly((), np.int8),
    }
    if any(
        value is None
        for value in (
            origins, corrections, currents, limits, children, parents, valid
        )
    ):
        return empty
    origins = np.asarray(origins, dtype=np.float32)
    corrections = np.asarray(corrections, dtype=np.float32)
    currents = np.asarray(currents, dtype=np.float32)
    limits = np.asarray(limits, dtype=np.float32)
    children = np.asarray(children, dtype=np.int32)
    parents = np.asarray(parents, dtype=np.int32)
    valid = np.asarray(valid, dtype=np.uint8)
    if origins.ndim != 5 or origins.shape[:2] != (2, 3):
        return empty
    data_count = origins.shape[2]
    records = []
    branch = max(0, min(1, int(selected_branch)))
    for iteration in range(3):
        for record in range(data_count):
            if not valid[branch, iteration, record]:
                continue
            current = float(currents[branch, iteration, record])
            limit = float(limits[branch, iteration, record])
            error = current - limit
            role_corrections = corrections[branch, iteration, record]
            correction_length = float(np.linalg.norm(role_corrections))
            near_width = np.deg2rad(5.0)
            state = 2 if correction_length > 1.0e-8 else 1 if error >= -near_width else 0
            records.append((
                branch,
                iteration,
                record,
                int(children[branch, iteration, record]),
                int(parents[branch, iteration, record]),
                origins[branch, iteration, record, 1],
                origins[branch, iteration, record, 0],
                role_corrections[1],
                role_corrections[0],
                current,
                limit,
                error,
                error / np.pi,
                state,
            ))
    if not records:
        return empty
    return {
        "branches": _readonly([item[0] for item in records], np.int8),
        "iterations": _readonly([item[1] for item in records], np.int8),
        "record_indices": _readonly([item[2] for item in records], np.int32),
        "children": _readonly([item[3] for item in records], np.int32),
        "parents": _readonly([item[4] for item in records], np.int32),
        "origins": _readonly([item[5] for item in records], np.float32),
        "parent_origins": _readonly([item[6] for item in records], np.float32),
        "corrections": _readonly([item[7] for item in records], np.float32),
        "parent_corrections": _readonly([item[8] for item in records], np.float32),
        "currents": _readonly([item[9] for item in records], np.float32),
        "limits": _readonly([item[10] for item in records], np.float32),
        "errors": _readonly([item[11] for item in records], np.float32),
        "normalized_errors": _readonly([item[12] for item in records], np.float32),
        "states": _readonly([item[13] for item in records], np.int8),
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
    sampled_radii = (
        _sample_curve(curves["radius"], depths)
        * np.asarray(radius_multipliers, dtype=np.float32)
        * scale_ratio
    )
    sampled_radii = np.where(
        np.asarray(radius_multipliers, dtype=np.float32) > 1.0e-8,
        np.maximum(sampled_radii, np.float32(0.0001)),
        np.float32(0.0),
    )
    return {
        "collision_mode": int(ints["collision_mode"]),
        "particle_radii": _readonly(sampled_radii),
        "self_collision_mode": int(ints["self_collision_mode"]),
        "self_collision_sync_mode": int(ints["self_collision_sync_mode"]),
        "colliders": collider_payload,
    }


def _center_payload(slot, item) -> dict:
    frame_input = item.get("frame_input")
    center_step = slot.data.get("center_step_result")
    frame_shift = slot.data.get("center_frame_shift_result")
    negative = slot.data.get("center_negative_scale_result")
    task_teleport = slot.data.get("task_teleport_result")
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
        "task_teleport": _freeze_value(task_teleport),
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
        if not _state_requested(state, frame):
            continue
        filters = dict(state.get("filters") or {})
        native_requested = any(
            bool(filters.get(name, False))
            for name in MC2_NATIVE_DEBUG_FILTER_KEYS
        )
        substep_requested = any(
            bool(filters.get(name, False))
            for name in MC2_SUBSTEP_DEBUG_FILTER_KEYS
        )
        if substep_requested and not item.get("substeps"):
            continue
        started = time.perf_counter()
        attempted = False
        try:
            attempted = True
            native_snapshot = {}
            if native_requested:
                native_snapshot = item["native_context"].refresh_debug_draw_snapshot(
                    include_baseline=bool(filters.get("show_depth", False)),
                    include_step_basic=bool(
                        filters.get("show_angle_restoration", False)
                        or filters.get("show_angle_limit", False)
                        or filters.get("show_step_basic", False)
                        or filters.get("show_distance", False)
                        or filters.get("show_tether", False)
                    ),
                    include_motion_base=bool(
                        filters.get("show_motion", False)
                        or filters.get("show_motion_base", False)
                    ),
                    include_angle_restoration=bool(
                        filters.get("show_angle_restoration", False)
                    ),
                    include_angle_limit=bool(filters.get("show_angle_limit", False)),
                    include_teleport_threshold=bool(
                        filters.get("show_teleport_threshold", False)
                    ),
                    include_teleport_status=bool(
                        filters.get("show_teleport_status", False)
                    ),
                    include_dynamics=bool(filters.get("show_velocity", False)),
                    include_distance_tether=bool(
                        filters.get("show_distance", False)
                        or filters.get("show_tether", False)
                    ),
                    include_bending=bool(filters.get("show_bending", False)),
                    include_constraint_results=bool(
                        filters.get("show_distance", False)
                        or filters.get("show_tether", False)
                        or filters.get("show_bending", False)
                        or filters.get("show_motion", False)
                        or filters.get("show_angle_restoration", False)
                        or filters.get("show_angle_limit", False)
                    ),
                    include_external_contacts=bool(
                        filters.get("show_collision_contacts", False)
                    ),
                    include_self_primitives=bool(
                        filters.get("show_self_primitives", False)
                    ),
                    include_self_grid=bool(filters.get("show_self_grid", False)),
                    include_self_candidates=bool(
                        filters.get("show_self_candidates", False)
                    ),
                    include_self_contacts=bool(
                        filters.get("show_self_contacts", False)
                    ),
                )
                external_contacts = native_snapshot.get("external_contacts")
                if isinstance(external_contacts, dict):
                    history = slot.data.setdefault(
                        "_debug_external_contact_history", {}
                    )
                    _annotate_external_contact_temporal(
                        external_contacts,
                        history,
                        frame=frame,
                        generation=generation,
                    )
                self_state = native_snapshot.get("self_collision")
                if (
                    filters.get("show_self_contacts", False)
                    and isinstance(self_state, dict)
                ):
                    history = slot.data.setdefault(
                        "_debug_self_temporal_history", {}
                    )
                    _annotate_self_temporal(
                        self_state,
                        history,
                        positions=native_snapshot.get("positions"),
                        frame=frame,
                        generation=generation,
                        scope=(
                            str(slot.slot_id),
                            str(item["native_context"].proxy_signature),
                        ),
                    )
            include_topology = bool(
                filters.get("show_topology", False)
                or filters.get("show_attributes", False)
                or filters.get("show_depth", False)
                or filters.get("show_step_basic", False)
                or filters.get("show_collision", False)
                or filters.get("show_collision_contacts", False)
            )
            include_parameters = bool(
                filters.get("show_gravity", False)
                or filters.get("show_distance", False)
                or filters.get("show_tether", False)
                or filters.get("show_bending", False)
                or filters.get("show_motion", False)
                or filters.get("show_motion_base", False)
                or filters.get("show_angle_restoration", False)
                or filters.get("show_angle_limit", False)
                or filters.get("show_collision", False)
                or filters.get("show_collision_contacts", False)
                or filters.get("show_radii", False)
            )
            include_motion = bool(
                filters.get("show_step_basic", False)
                or filters.get("show_distance", False)
                or filters.get("show_tether", False)
                or filters.get("show_motion", False)
                or filters.get("show_motion_base", False)
                or filters.get("show_angle_restoration", False)
                or filters.get("show_angle_limit", False)
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
                "topology": (
                    _topology_payload(
                        slot,
                        native_snapshot,
                        include_depth=bool(filters.get("show_depth", False)),
                    )
                    if include_topology else {}
                ),
                "parameters": (
                    _parameter_payload(slot, native_snapshot)
                    if include_parameters else {}
                ),
                "motion": (
                    _motion_payload(slot, native_snapshot)
                    if include_motion else {}
                ),
                "center": (
                    _center_payload(slot, item)
                    if filters.get("show_center", False) else {}
                ),
                "teleport": (
                    _freeze_value(slot.data.get("task_teleport_result"))
                    if filters.get("show_teleport_threshold", False)
                    or filters.get("show_teleport_status", False)
                    else {}
                ),
                "collision": (
                    _collision_payload(item, native_snapshot)
                    if filters.get("show_collision", False)
                    or filters.get("show_collision_contacts", False)
                    or filters.get("show_radii", False) else {}
                ),
                "self_collision": native_snapshot.get("self_collision"),
                "output": (
                    _output_payload(slot, item)
                    if filters.get("show_output", False) else {}
                ),
            }
            constraint_records = {}
            if filters.get("show_tether", False):
                constraint_records["tether"] = _tether_constraint_record_payload(
                    native_snapshot,
                    snapshot["motion"],
                    snapshot["parameters"],
                )
            if filters.get("show_distance", False):
                constraint_records["distance"] = _distance_constraint_record_payload(
                    native_snapshot
                )
            if filters.get("show_bending", False):
                constraint_records["bending"] = _bending_constraint_record_payload(
                    native_snapshot,
                    snapshot["parameters"],
                )
            if filters.get("show_motion", False):
                constraint_records["motion"] = _motion_constraint_record_payload(
                    native_snapshot,
                    snapshot["motion"],
                )
            if filters.get("show_angle_limit", False):
                constraint_records["angle_limit"] = _angle_constraint_record_payload(
                    native_snapshot, 0
                )
            if filters.get("show_angle_restoration", False):
                constraint_records["angle_restoration"] = (
                    _angle_constraint_record_payload(native_snapshot, 1)
                )
            if constraint_records:
                snapshot["constraint_records"] = constraint_records
            slot.data["_debug_draw_snapshot"] = snapshot
            state.pop("error", None)
            state["captured_frame"] = frame
            captured += 1
        except Exception as exc:
            state["error"] = str(exc)
        finally:
            if attempted:
                item["native_context"].clear_debug_capture_requests()
                state["requested"] = False
                state["attempted_frame"] = frame
                state["capture_ms"] = (time.perf_counter() - started) * 1000.0

    if _supports_interaction_debug(interaction):
        state = interaction.debug_capture_state()
        if _state_requested(state, frame) and any(item.get("substeps") for item in runtime_items):
            started = time.perf_counter()
            try:
                filters = dict(state.get("filters") or {})
                if bool(
                    filters.get("show_self", False)
                    or filters.get("show_interaction_contacts", False)
                ):
                    interaction_snapshot = interaction.refresh_debug_draw_snapshot(
                        include_primitives=bool(
                            filters.get("show_self_primitives", False)
                        ),
                        include_grid=bool(filters.get("show_self_grid", False)),
                        include_candidates=bool(
                            filters.get("show_self_candidates", False)
                        ),
                        include_contacts=bool(
                            filters.get("show_self_contacts", False)
                            or filters.get("show_interaction_contacts", False)
                        ),
                    )
                    if filters.get("show_self_contacts", False):
                        participants = tuple(
                            interaction_snapshot.get("participants") or ()
                        )
                        scope = tuple(
                            (
                                str(participant.get("task_id") or ""),
                                str(participant.get("slot_id") or ""),
                                int(participant.get("vertex_count", 0) or 0),
                                str(participant.get("proxy_signature") or ""),
                            )
                            for participant in participants
                        )
                        _annotate_self_temporal(
                            interaction_snapshot,
                            interaction.debug_self_temporal_history(),
                            positions=interaction_snapshot.get("positions"),
                            frame=frame,
                            generation=generation,
                            scope=scope,
                        )
                    captured += 1
                state.pop("error", None)
                state["captured_frame"] = frame
            except Exception as exc:
                state["error"] = str(exc)
            finally:
                state["requested"] = False
                state["attempted_frame"] = frame
                state["capture_ms"] = (time.perf_counter() - started) * 1000.0
    return captured


__all__ = [
    "MC2_DEBUG_DRAW_MODES",
    "MC2_DEBUG_FILTER_KEYS",
    "MC2_NATIVE_DEBUG_FILTER_KEYS",
    "capture_requested_mc2_debug",
    "capture_requested_mc2_product_debug",
    "request_mc2_debug_capture",
]
