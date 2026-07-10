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


def make_bone_transform_batch_writeback(
    *,
    solver: str,
    slot_id: str,
    armature_ptr: int,
    armature_data_ptr: int,
    frame: int,
    generation: int,
    bone_count: int,
    backend: str = "",
    plan_schema: str = "",
) -> dict:
    """Build one result-stream envelope for a pre-resolved bone writeback plan.

    The batch keeps live matrices and PoseBone targets in the solver slot. Normal
    playback can therefore write them without constructing one serialized dict
    per bone. Consumers that require snapshots use ``iter_bone_transform_writebacks``
    and get the legacy per-bone shape on demand.
    """
    return {
        "channel": BONE_TRANSFORM_CHANNEL,
        "writeback_type": "bone_transform_batch",
        "solver": str(solver or "unknown"),
        "backend": str(backend or ""),
        "slot_id": str(slot_id),
        "frame": int(frame),
        "generation": int(generation),
        "armature_ptr": int(armature_ptr),
        "armature_data_ptr": int(armature_data_ptr),
        "bone_count": max(0, int(bone_count)),
        "plan_schema": str(plan_schema or ""),
    }


def publish_bone_transform_batch_writeback(world, **kwargs) -> dict | None:
    result = make_bone_transform_batch_writeback(**kwargs)
    return world.publish_result(
        result,
        channel=BONE_TRANSFORM_CHANNEL,
        solver=result.get("solver", "unknown"),
    )


def _expand_bone_transform_batch(world, result: dict) -> list[dict]:
    expanded = []
    slot = getattr(world, "solver_slots", {}).get(str(result.get("slot_id") or ""))
    plan = slot.data.get("writeback_plan") if slot is not None else None
    if not isinstance(plan, dict):
        return expanded
    common = {
        "solver": result.get("solver", "unknown"),
        "slot_id": result.get("slot_id", ""),
        "armature_ptr": result.get("armature_ptr", 0),
        "armature_data_ptr": result.get("armature_data_ptr", 0),
        "frame": result.get("frame", 0),
        "generation": result.get("generation", 0),
        "backend": result.get("backend", ""),
    }
    for batch in plan.get("batches") or ():
        if not isinstance(batch, dict):
            continue
        records = batch.get("records") or ()
        matrix_bases = batch.get("matrix_bases") or ()
        target_matrices = batch.get("target_pose_matrices") or ()
        current_tails = batch.get("current_tails") or ()
        source_kind = str(batch.get("source_kind") or "")
        source_root = str(batch.get("source_root") or "")
        for index, record in enumerate(records):
            if not isinstance(record, dict) or index >= len(matrix_bases):
                continue
            matrix_basis = matrix_bases[index]
            if matrix_basis is None:
                continue
            target_matrix = target_matrices[index] if index < len(target_matrices) else None
            current_tail = current_tails[index] if index < len(current_tails) else None
            expanded.append(make_bone_transform_writeback(
                **common,
                bone_name=str(record.get("bone_name") or ""),
                pose_index=int(record.get("pose_index", -1)),
                matrix_basis=matrix_basis,
                target_pose_matrix=target_matrix,
                current_tail=current_tail,
                source_kind=source_kind,
                source_root=source_root,
            ))
    return expanded


def iter_bone_transform_writebacks(
    world,
    frame: int | None = None,
    generation: int | None = None,
    solver: str | None = None,
    slot_id: str | None = None,
    expand_batches: bool = True,
) -> list[dict]:
    items = world.consume_results(
        BONE_TRANSFORM_CHANNEL,
        solver=solver,
        frame=frame,
        generation=generation,
    )
    if slot_id is not None:
        items = [item for item in items if item.get("slot_id") == str(slot_id)]
    filtered = [
        item for item in items
        if isinstance(item, dict)
        and item.get("channel") == BONE_TRANSFORM_CHANNEL
        and item.get("writeback_type") in {"bone_transform", "bone_transform_batch"}
    ]
    if not expand_batches:
        return filtered
    expanded = []
    for item in filtered:
        if item.get("writeback_type") == "bone_transform_batch":
            expanded.extend(_expand_bone_transform_batch(world, item))
        else:
            expanded.append(item)
    return expanded


def clear_bone_transform_writebacks(world, solver: str | None = None) -> None:
    world.clear_results(BONE_TRANSFORM_CHANNEL, solver=solver)
