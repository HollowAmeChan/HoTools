"""
physicsWorld.rigid.results - rigid solver frame result helpers.

Result data is plain dict/tuple data published to PhysicsWorldCache.result_streams.
Consumers such as Physics Writeback, debug draw, bake and export should read
these results instead of reaching into backend-private Jolt handles.
"""

from __future__ import annotations


RIGID_TRANSFORM_CHANNEL = "rigid_transform"
RIGID_SOLVER_ID = "rigid_jolt"


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
