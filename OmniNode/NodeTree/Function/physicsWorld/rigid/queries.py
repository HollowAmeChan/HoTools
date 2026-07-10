"""Rigid/Jolt spatial query boundary."""

from __future__ import annotations

import math

from ..types import PhysicsWorldCache
from .names import (
    RIGID_BACKEND_RESOURCE_KEY,
    RIGID_BODY_SLOT_KIND,
    RIGID_QUERY_RESULT_CHANNEL,
    RIGID_QUERY_WRITER_ID,
    RIGID_SOLVER_ID,
)


def _float3(value, fallback=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    try:
        result = (float(value[0]), float(value[1]), float(value[2]))
    except Exception:
        result = tuple(float(item) for item in fallback)
    if not all(math.isfinite(item) for item in result):
        return tuple(float(item) for item in fallback)
    return result


def _slot_id_for_object(world: PhysicsWorldCache, obj) -> str:
    if obj is None:
        return ""
    try:
        obj_ptr = int(obj.as_pointer())
    except Exception:
        return ""
    prefix = f"rigid:{obj_ptr}:"
    for slot_id, slot in world.solver_slots.items():
        if slot.kind == RIGID_BODY_SLOT_KIND and str(slot_id).startswith(prefix):
            return str(slot_id)
    return ""


def _object_and_spec_for_slot(world: PhysicsWorldCache, slot_id: str):
    slot = world.solver_slots.get(str(slot_id))
    if slot is None or slot.kind != RIGID_BODY_SLOT_KIND:
        return None, None
    spec = slot.data.get("spec")
    return getattr(spec, "obj", None), spec


def _query_id(origin, direction, max_distance: float, include_sensors: bool, ignore_slot_id: str) -> str:
    values = (*_float3(origin), *_float3(direction), float(max_distance))
    signature = ":".join(f"{value:.6g}" for value in values)
    return f"ray:{signature}:{int(bool(include_sensors))}:{ignore_slot_id}"


def _make_query_result(
    data: dict,
    spec,
    frame: int,
    generation: int,
    query_id: str,
    include_sensors: bool,
    ignore_slot_id: str,
) -> dict:
    return {
        "channel": RIGID_QUERY_RESULT_CHANNEL,
        "solver": RIGID_SOLVER_ID,
        "backend": str(data.get("backend", "jolt") or "jolt"),
        "query_type": "ray_cast",
        "query_id": str(query_id),
        "frame": int(frame),
        "generation": int(generation),
        "hit": bool(data.get("hit", False)),
        "slot_id": str(data.get("slot_id", "") or ""),
        "obj_ptr": int(getattr(spec, "obj_ptr", 0) or 0),
        "data_ptr": int(getattr(spec, "data_ptr", 0) or 0),
        "body_type": str(getattr(spec, "body_type", "") or ""),
        "origin": _float3(data.get("origin")),
        "direction": _float3(data.get("direction"), (0.0, 0.0, -1.0)),
        "max_distance": max(float(data.get("max_distance", 0.0) or 0.0), 0.0),
        "end_position": _float3(data.get("end_position")),
        "position": _float3(data.get("position")),
        "normal": _float3(data.get("normal")),
        "distance": max(float(data.get("distance", 0.0) or 0.0), 0.0),
        "fraction": min(max(float(data.get("fraction", 1.0) or 0.0), 0.0), 1.0),
        "sub_shape_id": int(data.get("sub_shape_id", 0) or 0),
        "is_sensor": bool(data.get("is_sensor", False)),
        "include_sensors": bool(include_sensors),
        "ignore_slot_id": str(ignore_slot_id or ""),
        "reason": str(data.get("reason", "") or ""),
    }


def perform_rigid_ray_cast(
    world,
    origin=(0.0, 0.0, 0.0),
    direction=(0.0, 0.0, -1.0),
    max_distance: float = 100.0,
    include_sensors: bool = True,
    ignore_object=None,
) -> tuple[dict, object | None]:
    """Run a closest-hit query and publish a handle-free result snapshot."""
    if not isinstance(world, PhysicsWorldCache):
        data = {
            "hit": False,
            "origin": _float3(origin),
            "direction": _float3(direction, (0.0, 0.0, -1.0)),
            "max_distance": max(float(max_distance), 0.0),
            "position": _float3(origin),
            "end_position": _float3(origin),
            "normal": (0.0, 0.0, 0.0),
            "distance": 0.0,
            "fraction": 1.0,
            "reason": "invalid_world",
        }
        return _make_query_result(data, None, 0, 0, "ray:invalid_world", include_sensors, ""), None

    ignore_slot_id = _slot_id_for_object(world, ignore_object)
    adapter = world.backend_resources.get(RIGID_BACKEND_RESOURCE_KEY)
    if adapter is None or not bool(getattr(adapter, "_valid", False)):
        data = {
            "hit": False,
            "origin": _float3(origin),
            "direction": _float3(direction, (0.0, 0.0, -1.0)),
            "max_distance": max(float(max_distance), 0.0),
            "position": _float3(origin),
            "end_position": _float3(origin),
            "normal": (0.0, 0.0, 0.0),
            "distance": 0.0,
            "fraction": 1.0,
            "reason": "adapter_missing",
        }
    else:
        data = adapter.ray_cast(
            origin=origin,
            direction=direction,
            max_distance=max_distance,
            include_sensors=include_sensors,
            ignore_slot_id=ignore_slot_id or None,
        )

    hit_object, spec = _object_and_spec_for_slot(world, data.get("slot_id", ""))
    frame = int(getattr(world.frame_context, "frame", 0) or 0)
    query_id = _query_id(origin, direction, max_distance, include_sensors, ignore_slot_id)
    result = _make_query_result(
        data,
        spec,
        frame,
        world.generation,
        query_id,
        include_sensors,
        ignore_slot_id,
    )
    world.acquire_write(RIGID_QUERY_WRITER_ID)
    try:
        published = world.publish_result(
            result,
            channel=RIGID_QUERY_RESULT_CHANNEL,
            solver=RIGID_SOLVER_ID,
        )
    finally:
        world.release_write(RIGID_QUERY_WRITER_ID)
    return published or result, hit_object


def iter_rigid_query_results(
    world,
    frame: int | None = None,
    generation: int | None = None,
) -> list[dict]:
    if not isinstance(world, PhysicsWorldCache):
        return []
    return [
        item for item in world.consume_results(
            RIGID_QUERY_RESULT_CHANNEL,
            solver=RIGID_SOLVER_ID,
            frame=frame,
            generation=generation,
        )
        if isinstance(item, dict) and item.get("channel") == RIGID_QUERY_RESULT_CHANNEL
    ]
