"""Task-local Object Anchor frame adapter for MC2 Center inertia."""

from __future__ import annotations

from dataclasses import replace
import math

from .center_state import MC2CenterFramePoseSpec


def _live_object_pointer(obj) -> int:
    pointer = getattr(obj, "as_pointer", None)
    if not callable(pointer):
        raise TypeError("MC2 Anchor must be a Blender Object")
    try:
        value = int(pointer())
    except (ReferenceError, RuntimeError) as exc:
        raise ValueError("MC2 Anchor Object is unavailable") from exc
    if value <= 0 or not hasattr(obj, "matrix_world"):
        raise ValueError("MC2 Anchor Object is unavailable")
    return value


def attach_mc2_task_anchor(
    frame_pose: MC2CenterFramePoseSpec,
    task,
    *,
    depsgraph=None,
) -> MC2CenterFramePoseSpec:
    """Attach the task's evaluated Object transform without changing topology."""
    if not isinstance(frame_pose, MC2CenterFramePoseSpec):
        raise TypeError("frame_pose must be MC2CenterFramePoseSpec")
    anchor = getattr(task, "anchor_object", None)
    if anchor is None:
        return frame_pose
    pointer = _live_object_pointer(anchor)
    evaluated = anchor
    if depsgraph is not None:
        try:
            evaluated = anchor.evaluated_get(depsgraph)
        except (AttributeError, ReferenceError, RuntimeError) as exc:
            raise ValueError("MC2 Anchor Object cannot be evaluated") from exc
    try:
        matrix = evaluated.matrix_world
        position = tuple(float(matrix[row][3]) for row in range(3))
        quaternion = matrix.to_quaternion()
        length = math.sqrt(
            sum(float(value) * float(value) for value in quaternion)
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError) as exc:
        raise ValueError("MC2 Anchor Object has no valid world transform") from exc
    if not all(math.isfinite(value) for value in position) or not math.isfinite(length):
        raise ValueError("MC2 Anchor Object world transform contains NaN/Inf")
    if length <= 1.0e-8:
        raise ValueError("MC2 Anchor Object world rotation is degenerate")
    quaternion.normalize()
    return replace(
        frame_pose,
        anchor_identity=f"object:{pointer}",
        anchor_world_position=position,
        anchor_world_rotation_xyzw=(
            float(quaternion.x),
            float(quaternion.y),
            float(quaternion.z),
            float(quaternion.w),
        ),
    )


__all__ = ["attach_mc2_task_anchor"]
