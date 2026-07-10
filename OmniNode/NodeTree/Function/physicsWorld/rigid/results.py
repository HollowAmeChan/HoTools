"""
physicsWorld.rigid.results - rigid solver frame result helpers.

Result data is plain dict/tuple data published to PhysicsWorldCache.result_streams.
Consumers such as Physics Writeback, debug draw, bake and export should read
these results instead of reaching into backend-private Jolt handles.
"""

from __future__ import annotations

from .names import (
    RIGID_CONTACT_EVENT_CHANNEL,
    RIGID_CONSTRAINT_STATE_CHANNEL,
    RIGID_SENSOR_EVENT_CHANNEL,
    RIGID_SOLVER_ID,
    RIGID_SOLVER_STATS_CHANNEL,
    RIGID_TRANSFORM_CHANNEL,
)


def _float3(value) -> tuple[float, float, float]:
    return (float(value[0]), float(value[1]), float(value[2]))


def _float4(value) -> tuple[float, float, float, float]:
    return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))


def make_rigid_transform_result(
    slot_id: str,
    spec,
    frame: int,
    generation: int,
    position,
    rotation_wxyz,
    linear_velocity=None,
    angular_velocity=None,
    active: bool | None = None,
    sleeping: bool | None = None,
    backend: str = "jolt",
) -> dict:
    return {
        "channel": RIGID_TRANSFORM_CHANNEL,
        "solver": RIGID_SOLVER_ID,
        "backend": str(backend),
        "slot_id": str(slot_id),
        "frame": int(frame),
        "generation": int(generation),
        "obj_ptr": int(getattr(spec, "obj_ptr", 0) or 0),
        "data_ptr": int(getattr(spec, "data_ptr", 0) or 0),
        "body_type": str(getattr(spec, "body_type", "DYNAMIC") or "DYNAMIC"),
        "position": _float3(position),
        "rotation_wxyz": _float4(rotation_wxyz),
        "linear_velocity": _float3(linear_velocity if linear_velocity is not None else (0.0, 0.0, 0.0)),
        "angular_velocity": _float3(angular_velocity if angular_velocity is not None else (0.0, 0.0, 0.0)),
        "active": bool(active) if active is not None else False,
        "sleeping": bool(sleeping) if sleeping is not None else False,
    }


def publish_rigid_transform_result(
    world,
    slot_id: str,
    spec,
    frame: int,
    generation: int,
    position,
    rotation_wxyz,
    linear_velocity=None,
    angular_velocity=None,
    active: bool | None = None,
    sleeping: bool | None = None,
    backend: str = "jolt",
) -> dict | None:
    result = make_rigid_transform_result(
        slot_id=slot_id,
        spec=spec,
        frame=frame,
        generation=generation,
        position=position,
        rotation_wxyz=rotation_wxyz,
        linear_velocity=linear_velocity,
        angular_velocity=angular_velocity,
        active=active,
        sleeping=sleeping,
        backend=backend,
    )
    return world.publish_result(result, channel=RIGID_TRANSFORM_CHANNEL, solver=RIGID_SOLVER_ID)


def iter_rigid_transform_results(
    world,
    frame: int | None = None,
    generation: int | None = None,
) -> list[dict]:
    items = world.consume_results(
        RIGID_TRANSFORM_CHANNEL,
        solver=RIGID_SOLVER_ID,
        frame=frame,
        generation=generation,
    )
    return [
        item for item in items
        if isinstance(item, dict) and item.get("channel") == RIGID_TRANSFORM_CHANNEL
    ]


def get_rigid_transform_result(
    world,
    slot_id: str | None = None,
    obj_ptr: int | None = None,
    data_ptr: int | None = None,
    frame: int | None = None,
    generation: int | None = None,
) -> dict | None:
    slot_id = str(slot_id) if slot_id else None
    obj_ptr = int(obj_ptr) if obj_ptr is not None else None
    data_ptr = int(data_ptr) if data_ptr is not None else None
    for result in iter_rigid_transform_results(world, frame=frame, generation=generation):
        if slot_id is not None and result.get("slot_id") != slot_id:
            continue
        if obj_ptr is not None and int(result.get("obj_ptr", 0) or 0) != obj_ptr:
            continue
        if data_ptr is not None and int(result.get("data_ptr", 0) or 0) != data_ptr:
            continue
        return result
    return None


def clear_rigid_transform_results(world) -> None:
    world.clear_results(RIGID_TRANSFORM_CHANNEL, solver=RIGID_SOLVER_ID)


def make_rigid_constraint_state_result(
    slot_id: str,
    spec,
    frame: int,
    generation: int,
    state: dict,
    backend: str = "jolt",
) -> dict:
    return {
        "channel": RIGID_CONSTRAINT_STATE_CHANNEL,
        "solver": RIGID_SOLVER_ID,
        "backend": str(backend),
        "slot_id": str(slot_id),
        "frame": int(frame),
        "generation": int(generation),
        "empty_ptr": int(getattr(spec, "empty_ptr", 0) or 0),
        "target_a_ptr": int(getattr(spec, "target_a_ptr", 0) or 0),
        "target_b_ptr": int(getattr(spec, "target_b_ptr", 0) or 0),
        "anchor_mode": str(getattr(spec, "anchor_mode", "SHARED_WORLD") or "SHARED_WORLD"),
        "anchor_position_a": _float3(getattr(spec, "anchor_position_a", (0.0, 0.0, 0.0))),
        "anchor_rotation_wxyz_a": _float4(getattr(spec, "anchor_rotation_wxyz_a", (1.0, 0.0, 0.0, 0.0))),
        "anchor_position_b": _float3(getattr(spec, "anchor_position_b", (0.0, 0.0, 0.0))),
        "anchor_rotation_wxyz_b": _float4(getattr(spec, "anchor_rotation_wxyz_b", (1.0, 0.0, 0.0, 0.0))),
        "constraint_type": str(state.get("constraint_type", getattr(spec, "constraint_type", "FIXED"))),
        "enabled": bool(state.get("enabled", False)),
        "breakable": bool(getattr(spec, "breakable", False)),
        "breaking_threshold": float(getattr(spec, "breaking_threshold", 1000.0) or 0.0),
        "broken": bool(state.get("broken", False)),
        "breaking_impulse": float(state.get("breaking_impulse", 0.0) or 0.0),
        "current_value_kind": str(state.get("current_value_kind", "none") or "none"),
        "current_value": float(state.get("current_value", 0.0) or 0.0),
        "lambda_position": _float3(state.get("lambda_position", (0.0, 0.0, 0.0))),
        "lambda_rotation": _float3(state.get("lambda_rotation", (0.0, 0.0, 0.0))),
        "lambda_limit": float(state.get("lambda_limit", 0.0) or 0.0),
        "lambda_motor": float(state.get("lambda_motor", 0.0) or 0.0),
        "lambda_max_abs": float(state.get("lambda_max_abs", 0.0) or 0.0),
    }


def publish_rigid_constraint_state_result(
    world,
    slot_id: str,
    spec,
    frame: int,
    generation: int,
    state: dict,
    backend: str = "jolt",
) -> dict | None:
    result = make_rigid_constraint_state_result(
        slot_id=slot_id,
        spec=spec,
        frame=frame,
        generation=generation,
        state=state,
        backend=backend,
    )
    return world.publish_result(
        result,
        channel=RIGID_CONSTRAINT_STATE_CHANNEL,
        solver=RIGID_SOLVER_ID,
    )


def iter_rigid_constraint_state_results(
    world,
    frame: int | None = None,
    generation: int | None = None,
) -> list[dict]:
    items = world.consume_results(
        RIGID_CONSTRAINT_STATE_CHANNEL,
        solver=RIGID_SOLVER_ID,
        frame=frame,
        generation=generation,
    )
    return [
        item for item in items
        if isinstance(item, dict) and item.get("channel") == RIGID_CONSTRAINT_STATE_CHANNEL
    ]


def get_rigid_constraint_state_result(
    world,
    slot_id: str | None = None,
    empty_ptr: int | None = None,
    frame: int | None = None,
    generation: int | None = None,
) -> dict | None:
    slot_id = str(slot_id) if slot_id else None
    empty_ptr = int(empty_ptr) if empty_ptr is not None else None
    for result in iter_rigid_constraint_state_results(
        world,
        frame=frame,
        generation=generation,
    ):
        if slot_id is not None and result.get("slot_id") != slot_id:
            continue
        if empty_ptr is not None and int(result.get("empty_ptr", 0) or 0) != empty_ptr:
            continue
        return result
    return None


def clear_rigid_constraint_state_results(world) -> None:
    world.clear_results(RIGID_CONSTRAINT_STATE_CHANNEL, solver=RIGID_SOLVER_ID)


def make_rigid_contact_event_result(
    event: dict,
    frame: int,
    generation: int,
    event_index: int,
    channel: str = RIGID_CONTACT_EVENT_CHANNEL,
    backend: str = "jolt",
) -> dict:
    if channel not in {RIGID_CONTACT_EVENT_CHANNEL, RIGID_SENSOR_EVENT_CHANNEL}:
        raise ValueError(f"unsupported rigid contact event channel: {channel!r}")
    body_a_slot_id = str(event.get("body_a_slot_id", "") or "")
    body_b_slot_id = str(event.get("body_b_slot_id", "") or "")
    body_a_sensor = bool(event.get("body_a_sensor", False))
    body_b_sensor = bool(event.get("body_b_sensor", False))
    return {
        "channel": channel,
        "solver": RIGID_SOLVER_ID,
        "backend": str(backend),
        "frame": int(frame),
        "generation": int(generation),
        "event_index": int(event_index),
        "state": str(event.get("state", "") or ""),
        "body_a_slot_id": body_a_slot_id,
        "body_b_slot_id": body_b_slot_id,
        "body_a_sensor": body_a_sensor,
        "body_b_sensor": body_b_sensor,
        "is_sensor": bool(event.get("is_sensor", False)),
        "sensor_slot_ids": tuple(
            slot_id for slot_id, is_sensor in (
                (body_a_slot_id, body_a_sensor),
                (body_b_slot_id, body_b_sensor),
            )
            if slot_id and is_sensor
        ),
        "normal": _float3(event.get("normal", (0.0, 0.0, 0.0))),
        "penetration_depth": float(event.get("penetration_depth", 0.0) or 0.0),
        "points_on_a": tuple(_float3(point) for point in event.get("points_on_a", ())),
        "points_on_b": tuple(_float3(point) for point in event.get("points_on_b", ())),
        "sub_shape_a": int(event.get("sub_shape_a", 0) or 0),
        "sub_shape_b": int(event.get("sub_shape_b", 0) or 0),
    }


def publish_rigid_contact_event_result(
    world,
    event: dict,
    frame: int,
    generation: int,
    event_index: int,
    channel: str = RIGID_CONTACT_EVENT_CHANNEL,
    backend: str = "jolt",
) -> dict | None:
    result = make_rigid_contact_event_result(
        event=event,
        frame=frame,
        generation=generation,
        event_index=event_index,
        channel=channel,
        backend=backend,
    )
    return world.publish_result(result, channel=channel, solver=RIGID_SOLVER_ID)


def iter_rigid_contact_event_results(
    world,
    frame: int | None = None,
    generation: int | None = None,
    sensor_only: bool = False,
) -> list[dict]:
    channel = RIGID_SENSOR_EVENT_CHANNEL if sensor_only else RIGID_CONTACT_EVENT_CHANNEL
    items = world.consume_results(
        channel,
        solver=RIGID_SOLVER_ID,
        frame=frame,
        generation=generation,
    )
    return [
        item for item in items
        if isinstance(item, dict) and item.get("channel") == channel
    ]


def clear_rigid_contact_event_results(world) -> None:
    world.clear_results(RIGID_CONTACT_EVENT_CHANNEL, solver=RIGID_SOLVER_ID)
    world.clear_results(RIGID_SENSOR_EVENT_CHANNEL, solver=RIGID_SOLVER_ID)


def make_rigid_solver_stats_result(
    frame: int,
    generation: int,
    body_count: int,
    constraint_count: int,
    step_ms: float,
    dt: float,
    substeps: int,
    same_frame: bool,
    restart_required: bool,
    transform_count: int,
    contact_event_count: int = 0,
    sensor_event_count: int = 0,
    contact_event_overflow: int = 0,
    command_count: int = 0,
    command_failed: int = 0,
    command_errors: list[str] | None = None,
    sync_error_count: int = 0,
    result_error_count: int = 0,
    backend: str = "jolt",
) -> dict:
    return {
        "channel": RIGID_SOLVER_STATS_CHANNEL,
        "solver": RIGID_SOLVER_ID,
        "backend": str(backend),
        "frame": int(frame),
        "generation": int(generation),
        "body_count": int(body_count),
        "constraint_count": int(constraint_count),
        "step_ms": float(step_ms),
        "dt": float(dt),
        "substeps": int(substeps),
        "same_frame": bool(same_frame),
        "restart_required": bool(restart_required),
        "transform_count": int(transform_count),
        "contact_event_count": int(contact_event_count),
        "sensor_event_count": int(sensor_event_count),
        "contact_event_overflow": int(contact_event_overflow),
        "command_count": int(command_count),
        "command_failed": int(command_failed),
        "command_errors": list(command_errors or ()),
        "sync_error_count": int(sync_error_count),
        "result_error_count": int(result_error_count),
    }


def publish_rigid_solver_stats_result(
    world,
    frame: int,
    generation: int,
    body_count: int,
    constraint_count: int,
    step_ms: float,
    dt: float,
    substeps: int,
    same_frame: bool,
    restart_required: bool,
    transform_count: int,
    contact_event_count: int = 0,
    sensor_event_count: int = 0,
    contact_event_overflow: int = 0,
    command_count: int = 0,
    command_failed: int = 0,
    command_errors: list[str] | None = None,
    sync_error_count: int = 0,
    result_error_count: int = 0,
    backend: str = "jolt",
) -> dict | None:
    world.clear_results(RIGID_SOLVER_STATS_CHANNEL, solver=RIGID_SOLVER_ID)
    result = make_rigid_solver_stats_result(
        frame=frame,
        generation=generation,
        body_count=body_count,
        constraint_count=constraint_count,
        step_ms=step_ms,
        dt=dt,
        substeps=substeps,
        same_frame=same_frame,
        restart_required=restart_required,
        transform_count=transform_count,
        contact_event_count=contact_event_count,
        sensor_event_count=sensor_event_count,
        contact_event_overflow=contact_event_overflow,
        command_count=command_count,
        command_failed=command_failed,
        command_errors=command_errors,
        sync_error_count=sync_error_count,
        result_error_count=result_error_count,
        backend=backend,
    )
    return world.publish_result(result, channel=RIGID_SOLVER_STATS_CHANNEL, solver=RIGID_SOLVER_ID)


def iter_rigid_solver_stats_results(
    world,
    frame: int | None = None,
    generation: int | None = None,
) -> list[dict]:
    items = world.consume_results(
        RIGID_SOLVER_STATS_CHANNEL,
        solver=RIGID_SOLVER_ID,
        frame=frame,
        generation=generation,
    )
    return [
        item for item in items
        if isinstance(item, dict) and item.get("channel") == RIGID_SOLVER_STATS_CHANNEL
    ]


def get_rigid_solver_stats_result(
    world,
    frame: int | None = None,
    generation: int | None = None,
) -> dict | None:
    items = iter_rigid_solver_stats_results(world, frame=frame, generation=generation)
    return items[-1] if items else None
