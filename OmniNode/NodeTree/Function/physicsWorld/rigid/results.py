"""
physicsWorld.rigid.results - rigid solver frame result helpers.

Result data is plain dict/tuple data stored on solver slots. Consumers such as
Physics Writeback, debug draw, bake and export should read these results instead
of reaching into backend-private Jolt handles.
"""

from __future__ import annotations


RIGID_TRANSFORM_RESULT_KEY = "result.rigid_transform"
RIGID_TRANSFORM_CHANNEL = "object_transform"
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
    }


def get_rigid_transform_result(
    slot,
    frame: int | None = None,
    generation: int | None = None,
) -> dict | None:
    try:
        result = slot.data.get(RIGID_TRANSFORM_RESULT_KEY)
    except Exception:
        return None
    if not isinstance(result, dict):
        return None
    if result.get("channel") != RIGID_TRANSFORM_CHANNEL:
        return None
    if frame is not None and int(result.get("frame", -1)) != int(frame):
        return None
    if generation is not None and int(result.get("generation", -1)) != int(generation):
        return None
    return result


def clear_rigid_transform_result(slot) -> None:
    try:
        slot.data.pop(RIGID_TRANSFORM_RESULT_KEY, None)
    except Exception:
        pass
