"""VRM SpringBone 新解算器使用的纯快照结果流辅助函数。"""

from __future__ import annotations

from ..names import (
    SPRING_VRM_POSE_CHANNEL,
    SPRING_VRM_SOLVER_ID,
    SPRING_VRM_STATS_CHANNEL,
)
from ..utils.values import float3, matrix16


def make_spring_vrm_pose_result(
    slot_id: str,
    armature_ptr: int,
    armature_data_ptr: int,
    frame: int,
    generation: int,
    bone_name: str,
    pose_index: int,
    matrix_basis,
    target_pose_matrix=None,
    current_tail=None,
    chain_root: str = "",
    backend: str = "cpp",
) -> dict:
    result = {
        "channel": SPRING_VRM_POSE_CHANNEL,
        "solver": SPRING_VRM_SOLVER_ID,
        "backend": str(backend),
        "slot_id": str(slot_id),
        "frame": int(frame),
        "generation": int(generation),
        "armature_ptr": int(armature_ptr),
        "armature_data_ptr": int(armature_data_ptr),
        "chain_root": str(chain_root or ""),
        "bone_name": str(bone_name or ""),
        "pose_index": int(pose_index),
        "matrix_basis": matrix16(matrix_basis),
    }
    if target_pose_matrix is not None:
        result["target_pose_matrix"] = matrix16(target_pose_matrix)
    if current_tail is not None:
        result["current_tail"] = float3(current_tail)
    return result


def publish_spring_vrm_pose_result(world, **kwargs) -> dict | None:
    result = make_spring_vrm_pose_result(**kwargs)
    return world.publish_result(result, channel=SPRING_VRM_POSE_CHANNEL, solver=SPRING_VRM_SOLVER_ID)


def iter_spring_vrm_pose_results(
    world,
    frame: int | None = None,
    generation: int | None = None,
    slot_id: str | None = None,
) -> list[dict]:
    items = world.consume_results(
        SPRING_VRM_POSE_CHANNEL,
        solver=SPRING_VRM_SOLVER_ID,
        frame=frame,
        generation=generation,
    )
    if slot_id is not None:
        items = [item for item in items if item.get("slot_id") == str(slot_id)]
    return [
        item for item in items
        if isinstance(item, dict) and item.get("channel") == SPRING_VRM_POSE_CHANNEL
    ]


def clear_spring_vrm_pose_results(world) -> None:
    world.clear_results(SPRING_VRM_POSE_CHANNEL, solver=SPRING_VRM_SOLVER_ID)


def make_spring_vrm_stats_result(
    frame: int,
    generation: int,
    slot_count: int,
    chain_count: int,
    bone_count: int,
    collider_count: int,
    step_ms: float = 0.0,
    writeback_count: int = 0,
    backend: str = "cpp",
    status: str = "ok",
    errors: list[str] | None = None,
) -> dict:
    return {
        "channel": SPRING_VRM_STATS_CHANNEL,
        "solver": SPRING_VRM_SOLVER_ID,
        "backend": str(backend),
        "frame": int(frame),
        "generation": int(generation),
        "slot_count": int(slot_count),
        "chain_count": int(chain_count),
        "bone_count": int(bone_count),
        "collider_count": int(collider_count),
        "step_ms": float(step_ms),
        "writeback_count": int(writeback_count),
        "status": str(status),
        "errors": list(errors or ()),
    }


def publish_spring_vrm_stats_result(world, **kwargs) -> dict | None:
    world.clear_results(SPRING_VRM_STATS_CHANNEL, solver=SPRING_VRM_SOLVER_ID)
    result = make_spring_vrm_stats_result(**kwargs)
    return world.publish_result(result, channel=SPRING_VRM_STATS_CHANNEL, solver=SPRING_VRM_SOLVER_ID)


def iter_spring_vrm_stats_results(
    world,
    frame: int | None = None,
    generation: int | None = None,
) -> list[dict]:
    items = world.consume_results(
        SPRING_VRM_STATS_CHANNEL,
        solver=SPRING_VRM_SOLVER_ID,
        frame=frame,
        generation=generation,
    )
    return [
        item for item in items
        if isinstance(item, dict) and item.get("channel") == SPRING_VRM_STATS_CHANNEL
    ]


def get_spring_vrm_stats_result(
    world,
    frame: int | None = None,
    generation: int | None = None,
) -> dict | None:
    items = iter_spring_vrm_stats_results(world, frame=frame, generation=generation)
    return items[-1] if items else None


def clear_spring_vrm_stats_results(world) -> None:
    world.clear_results(SPRING_VRM_STATS_CHANNEL, solver=SPRING_VRM_SOLVER_ID)
