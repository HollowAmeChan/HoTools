"""VRM SpringBone 新解算器使用的纯快照结果流辅助函数。"""

from __future__ import annotations

from ..writeback_commands import (
    clear_bone_transform_writebacks,
    iter_bone_transform_writebacks,
    make_bone_transform_writeback,
    publish_bone_transform_batch_writeback,
)
from .names import SPRING_VRM_SOLVER_ID, SPRING_VRM_STATS_CHANNEL


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
    result = make_bone_transform_writeback(
        solver=SPRING_VRM_SOLVER_ID,
        slot_id=slot_id,
        armature_ptr=armature_ptr,
        armature_data_ptr=armature_data_ptr,
        frame=frame,
        generation=generation,
        bone_name=bone_name,
        pose_index=pose_index,
        matrix_basis=matrix_basis,
        target_pose_matrix=target_pose_matrix,
        current_tail=current_tail,
        source_kind="spring_vrm",
        source_root=chain_root,
        backend=backend,
    )
    result["chain_root"] = str(chain_root or "")
    return result


def publish_spring_vrm_pose_result(world, **kwargs) -> dict | None:
    result = make_spring_vrm_pose_result(**kwargs)
    return world.publish_result(result, channel=result.get("channel"), solver=SPRING_VRM_SOLVER_ID)


def publish_spring_vrm_pose_batch_result(world, **kwargs) -> dict | None:
    return publish_bone_transform_batch_writeback(
        world,
        solver=SPRING_VRM_SOLVER_ID,
        backend="cpp",
        **kwargs,
    )


def iter_spring_vrm_pose_results(
    world,
    frame: int | None = None,
    generation: int | None = None,
    slot_id: str | None = None,
) -> list[dict]:
    items = iter_bone_transform_writebacks(
        world,
        solver=SPRING_VRM_SOLVER_ID,
        frame=frame,
        generation=generation,
        slot_id=slot_id,
    )
    return [
        item for item in items
        if isinstance(item, dict) and item.get("solver") == SPRING_VRM_SOLVER_ID
    ]


def clear_spring_vrm_pose_results(world) -> None:
    clear_bone_transform_writebacks(world, solver=SPRING_VRM_SOLVER_ID)


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
    native_context: dict | None = None,
) -> dict:
    result = {
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
    if isinstance(native_context, dict):
        result["native_context"] = dict(native_context)
    return result


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
