"""Rigid/Jolt debug snapshot helpers."""

from __future__ import annotations

from .names import (
    RIGID_BACKEND_RESOURCE_KEY,
    RIGID_BODY_SLOT_KIND,
    RIGID_CONSTRAINT_SLOT_KIND,
    RIGID_DEBUG_DRAW_MODE,
    RIGID_SOLVER_ID,
)


RIGID_DEBUG_DRAW_MODES = {
    RIGID_DEBUG_DRAW_MODE: {
        "solver": RIGID_SOLVER_ID,
        "label": "Rigid/Jolt Debug",
        "source": "ConstraintSpec + rigid result streams",
        "draw_item_contract": "physicsWorld.utils.debug_draw",
        "summary": (
            "Rigid/Jolt debug draw consumes plain spec/result snapshots. Constraint "
            "meaning is dispatched through rigid.constraint_debug per-type renderers; "
            "no Jolt BodyID, ConstraintID, or native debug renderer state is exposed."
        ),
    }
}


def install_rigid_slot_debug_snapshot(slot, spec) -> None:
    slot.data["_debug_snapshot"] = (
        lambda slot=slot, spec=spec: rigid_slot_debug_snapshot(slot, spec)
    )


def rigid_slot_debug_snapshot(slot, spec) -> dict:
    if hasattr(spec, "debug_dict"):
        snapshot = spec.debug_dict()
    else:
        snapshot = {"spec_type": type(spec).__name__}
    snapshot.update(
        {
            "slot_id": getattr(slot, "slot_id", ""),
            "kind": getattr(slot, "kind", ""),
            "world_generation": int(getattr(slot, "world_generation", 0) or 0),
            "jolt_synced_generation": slot.data.get("_jolt_generation"),
            "has_jolt_handle": "_jolt_handle" in slot.data,
            "kinematic_pose_dirty": bool(slot.data.get("_jolt_kinematic_pose_dirty", False)),
        }
    )
    return snapshot


def rigid_backend_debug_snapshot(adapter) -> dict:
    if adapter is None:
        return {
            "backend": "jolt",
            "available": False,
            "reason": "adapter_missing",
        }
    try:
        body_count = int(getattr(adapter, "body_count", 0) or 0)
    except Exception:
        body_count = 0
    try:
        constraint_count = int(getattr(adapter, "constraint_count", 0) or 0)
    except Exception:
        constraint_count = 0
    try:
        contact_events = list(adapter.get_contact_events())
    except Exception:
        contact_events = []
    contact_state_counts: dict[str, int] = {}
    for event in contact_events:
        state = str(event.get("state", "unknown") or "unknown")
        contact_state_counts[state] = contact_state_counts.get(state, 0) + 1
    sensor_event_count = sum(
        1 for event in contact_events if bool(event.get("is_sensor", False))
    )

    return {
        "backend": getattr(adapter, "BACKEND", "jolt"),
        "available": bool(getattr(adapter, "_valid", False)),
        "body_count": body_count,
        "constraint_count": constraint_count,
        "contact_event_count": len(contact_events),
        "sensor_event_count": sensor_event_count,
        "contact_event_state_counts": contact_state_counts,
        "contact_event_overflow": int(
            getattr(adapter, "last_contact_event_overflow", 0) or 0
        ),
        "contact_event_sample": [dict(event) for event in contact_events[:16]],
        "contact_event_sample_truncated": max(0, len(contact_events) - 16),
        "last_step_ms": round(float(getattr(adapter, "last_step_ms", 0.0) or 0.0), 3),
        "last_command_count": int(getattr(adapter, "last_command_count", 0) or 0),
        "last_command_failed": int(getattr(adapter, "last_command_failed", 0) or 0),
        "last_command_errors": list(getattr(adapter, "last_command_errors", []) or []),
        "jolt_world_gravity": tuple(getattr(adapter, "last_jolt_world_gravity", (0.0, 0.0, -9.81))),
        "jolt_world_settings_signature": str(getattr(adapter, "_jolt_world_settings_signature", "default") or "default"),
        "jolt_max_bodies": int(getattr(adapter, "jolt_max_bodies", 0) or 0),
        "jolt_max_body_pairs": int(getattr(adapter, "jolt_max_body_pairs", 0) or 0),
        "jolt_max_contact_constraints": int(getattr(adapter, "jolt_max_contact_constraints", 0) or 0),
    }


def rigid_debug_summary_for_world(world) -> dict:
    slots = list(getattr(world, "solver_slots", {}).values())
    body_slots = [slot for slot in slots if getattr(slot, "kind", None) == RIGID_BODY_SLOT_KIND]
    constraint_slots = [slot for slot in slots if getattr(slot, "kind", None) == RIGID_CONSTRAINT_SLOT_KIND]
    adapter = getattr(world, "backend_resources", {}).get(RIGID_BACKEND_RESOURCE_KEY)
    return {
        "solver": RIGID_SOLVER_ID,
        "body_slot_count": len(body_slots),
        "constraint_slot_count": len(constraint_slots),
        "backend": rigid_backend_debug_snapshot(adapter),
    }
