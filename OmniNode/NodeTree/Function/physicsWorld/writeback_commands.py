"""通用写回指令。

solver 只负责把本帧要写回的目标和数据发布到这里；真正写 Blender 数据由
physicsWorld.writeback 统一执行。
"""

from __future__ import annotations

from .names import BONE_TRANSFORM_CHANNEL
from .utils.values import float3, matrix16


def make_bone_transform_writeback(
    *,
    solver: str,
    slot_id: str,
    armature_ptr: int,
    armature_data_ptr: int,
    frame: int,
    generation: int,
    bone_name: str,
    matrix_basis,
    pose_index: int = -1,
    target_pose_matrix=None,
    current_tail=None,
    source_kind: str = "",
    source_root: str = "",
    backend: str = "",
) -> dict:
    result = {
        "channel": BONE_TRANSFORM_CHANNEL,
        "writeback_type": "bone_transform",
        "solver": str(solver or "unknown"),
        "backend": str(backend or ""),
        "slot_id": str(slot_id),
        "frame": int(frame),
        "generation": int(generation),
        "armature_ptr": int(armature_ptr),
        "armature_data_ptr": int(armature_data_ptr),
        "bone_name": str(bone_name or ""),
        "pose_index": int(pose_index),
        "matrix_basis": matrix16(matrix_basis),
        "source_kind": str(source_kind or ""),
        "source_root": str(source_root or ""),
    }
    if target_pose_matrix is not None:
        result["target_pose_matrix"] = matrix16(target_pose_matrix)
    if current_tail is not None:
        result["current_tail"] = float3(current_tail)
    return result


def publish_bone_transform_writeback(world, **kwargs) -> dict | None:
    result = make_bone_transform_writeback(**kwargs)
    return world.publish_result(
        result,
        channel=BONE_TRANSFORM_CHANNEL,
        solver=result.get("solver", "unknown"),
    )


def iter_bone_transform_writebacks(
    world,
    frame: int | None = None,
    generation: int | None = None,
    solver: str | None = None,
    slot_id: str | None = None,
) -> list[dict]:
    items = world.consume_results(
        BONE_TRANSFORM_CHANNEL,
        solver=solver,
        frame=frame,
        generation=generation,
    )
    if slot_id is not None:
        items = [item for item in items if item.get("slot_id") == str(slot_id)]
    return [
        item for item in items
        if isinstance(item, dict)
        and item.get("channel") == BONE_TRANSFORM_CHANNEL
        and item.get("writeback_type") == "bone_transform"
    ]


def clear_bone_transform_writebacks(world, solver: str | None = None) -> None:
    world.clear_results(BONE_TRANSFORM_CHANNEL, solver=solver)
