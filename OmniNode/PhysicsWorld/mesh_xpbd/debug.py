"""Mesh XPBD request-driven slot debug 快照。"""

from __future__ import annotations

import numpy as np

from ..types import PhysicsWorldCache
from .names import MESH_XPBD_SLOT_KIND


MESH_XPBD_DEBUG_REQUEST_KEY = "_debug_draw_request"
MESH_XPBD_DEBUG_CAPTURE_SOURCE_KEY = "_debug_capture_source"


def _readonly(values, dtype=None) -> np.ndarray:
    result = np.array(values, dtype=dtype, order="C", copy=True)
    result.setflags(write=False)
    return result


def install_mesh_xpbd_slot_debug_snapshot(slot) -> None:
    slot.data["_debug_snapshot"] = (
        lambda slot=slot: mesh_xpbd_slot_debug_snapshot(slot)
    )


def request_mesh_xpbd_debug_capture(
    world,
    *,
    enabled: bool,
    filters: dict | None = None,
) -> int:
    if not isinstance(world, PhysicsWorldCache):
        return 0
    count = 0
    for slot in world.solver_slots.values():
        if slot.kind != MESH_XPBD_SLOT_KIND:
            continue
        if enabled:
            slot.data[MESH_XPBD_DEBUG_REQUEST_KEY] = dict(filters or {})
            count += 1
        else:
            slot.data.pop(MESH_XPBD_DEBUG_REQUEST_KEY, None)
            if slot.data.get(MESH_XPBD_DEBUG_CAPTURE_SOURCE_KEY) == "draw":
                slot.data.pop("debug_capture", None)
                slot.data.pop(MESH_XPBD_DEBUG_CAPTURE_SOURCE_KEY, None)
    return count


def mesh_xpbd_debug_capture_requested(slot) -> bool:
    return isinstance(
        getattr(slot, "data", {}).get(MESH_XPBD_DEBUG_REQUEST_KEY),
        dict,
    )


def update_mesh_xpbd_slot_debug(
    slot,
    *,
    topology,
    reference,
    task,
    colliders,
    decision: str,
    frame: int,
    generation: int,
    elapsed_ms: float,
    native_stats: dict,
    capture: bool,
    capture_source: str = "",
    world_positions=None,
    local_offsets=None,
) -> None:
    slot.data["debug_summary"] = {
        "frame": int(frame),
        "generation": int(generation),
        "decision": str(decision),
        "elapsed_ms": float(elapsed_ms),
        "topology": topology.debug_dict(),
        "colliders": colliders.debug_dict(),
        "native": dict(native_stats),
    }
    if not capture:
        slot.data.pop("debug_capture", None)
        slot.data.pop(MESH_XPBD_DEBUG_CAPTURE_SOURCE_KEY, None)
        return
    if capture_source not in {"draw", "solver"}:
        raise ValueError("Mesh XPBD debug capture source must be draw or solver")
    slot.data["debug_capture"] = {
        "world_positions": _readonly(world_positions, np.float32),
        "rest_world_positions": _readonly(
            reference.rest_world_positions, np.float32
        ),
        "local_offsets": _readonly(local_offsets, np.float32),
        "stretch_indices": topology.stretch_indices,
        "loop_triangles": topology.loop_triangles,
        "bend_indices": topology.bend_indices,
        "inverse_masses": topology.inverse_masses,
        "world_collision_radii": reference.world_collision_radii,
        "collider_types": colliders.collider_types,
        "collider_group_bits": colliders.collider_group_bits,
        "collider_keys": tuple(colliders.collider_keys),
        "collider_centers": colliders.collider_centers,
        "collider_segment_a": colliders.collider_segment_a,
        "collider_segment_b": colliders.collider_segment_b,
        "collider_radii": colliders.collider_radii,
        "task": task.debug_dict(),
    }
    slot.data[MESH_XPBD_DEBUG_CAPTURE_SOURCE_KEY] = capture_source


def mesh_xpbd_slot_debug_snapshot(slot) -> dict:
    data = getattr(slot, "data", {})
    result = {
        "schema": "mesh_xpbd_slot_debug_v1",
        "slot_id": str(getattr(slot, "slot_id", "")),
        "kind": str(getattr(slot, "kind", "")),
        "world_generation": int(getattr(slot, "world_generation", 0)),
        "source_name": str(data.get("source_name") or ""),
        "source_object_ptr": int(data.get("source_object_ptr", 0) or 0),
        "source_data_ptr": int(data.get("source_data_ptr", 0) or 0),
        "topology_signature": str(data.get("topology_signature") or ""),
        "static_signature": str(data.get("static_signature") or ""),
        "reference_signature": str(data.get("reference_signature") or ""),
        "parameter_signature": str(data.get("parameter_signature") or ""),
        "summary": dict(data.get("debug_summary") or {}),
    }
    if isinstance(data.get("debug_capture"), dict):
        result["capture"] = dict(data["debug_capture"])
    if data.get("_mesh_xpbd_error"):
        result["error"] = str(data["_mesh_xpbd_error"])
    return result


__all__ = [
    "MESH_XPBD_DEBUG_REQUEST_KEY",
    "MESH_XPBD_DEBUG_CAPTURE_SOURCE_KEY",
    "install_mesh_xpbd_slot_debug_snapshot",
    "mesh_xpbd_debug_capture_requested",
    "mesh_xpbd_slot_debug_snapshot",
    "request_mesh_xpbd_debug_capture",
    "update_mesh_xpbd_slot_debug",
]
