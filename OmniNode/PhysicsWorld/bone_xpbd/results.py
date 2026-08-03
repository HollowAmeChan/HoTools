"""Bone XPBD 公共 Bone 写回计划与 stats result。"""

from __future__ import annotations

from ..names import BONE_TRANSFORM_CHANNEL
from ..utils.writeback_pose import matrix_basis_from_pose_matrix
from ..writeback_commands import make_bone_transform_batch_writeback
from .names import BONE_XPBD_SOLVER_ID, BONE_XPBD_STATS_CHANNEL


def make_bone_xpbd_writeback_plan(
    *,
    spec,
    topology,
    target_pose_matrices: dict[str, object],
    all_target_pose_matrices: dict[str, object],
    world_positions,
) -> dict:
    """构造求解阶段的临时计划。

    此对象会先交给 feedback stage 读取当前 PoseBone，随后必须通过
    ``freeze_bone_xpbd_writeback_plan`` 转成纯值计划后才能放进 slot。
    """

    armature = spec.armature
    pose_bones = armature.pose.bones
    records = []
    bases = []
    targets = []
    tails = []
    for segment in topology.segments:
        pose_bone = pose_bones.get(segment.bone_name)
        if pose_bone is None:
            raise ValueError(f"Bone XPBD 写回目标已失效: {segment.bone_name!r}")
        target = target_pose_matrices[segment.bone_name]
        records.append({
            "bone_name": segment.bone_name,
            "pose_index": segment.pose_index,
            "pose_bone": pose_bone,
            "parent_name": segment.parent_name,
            "head_particle": segment.head_particle,
            "tail_particle": segment.tail_particle,
            "tail_follow": spec.tail_follow,
        })
        bases.append(matrix_basis_from_pose_matrix(
            pose_bone,
            target,
            all_target_pose_matrices,
        ))
        targets.append(target)
        tails.append(tuple(float(value) for value in world_positions[segment.tail_particle]))
    return {
        "schema": "bone_xpbd_writeback_plan_v1",
        "armature": armature,
        "armature_ptr": spec.object_spec.armature_ptr,
        "armature_data_ptr": spec.object_spec.armature_data_ptr,
        "bone_count": len(records),
        "batches": ({
            "source_kind": "bone_xpbd",
            "source_root": spec.object_spec.collection_root,
            "records": tuple(records),
            "matrix_bases": tuple(bases),
            "target_pose_matrices": tuple(targets),
            "current_tails": tuple(tails),
        },),
    }


def freeze_bone_xpbd_writeback_plan(plan: dict) -> dict:
    """移除 Blender RNA 活引用，生成可跨帧保存的公共写回计划。"""

    if not isinstance(plan, dict) or plan.get("schema") != "bone_xpbd_writeback_plan_v1":
        raise TypeError("Bone XPBD 写回计划 schema 无效")
    frozen_batches = []
    record_count = 0
    for batch in plan.get("batches") or ():
        if not isinstance(batch, dict):
            raise TypeError("Bone XPBD 写回 batch 必须是 dict")
        records = []
        for record in batch.get("records") or ():
            if not isinstance(record, dict):
                raise TypeError("Bone XPBD 写回 record 必须是 dict")
            records.append({
                "bone_name": str(record.get("bone_name") or ""),
                "pose_index": int(record.get("pose_index", -1)),
                "parent_name": str(record.get("parent_name") or ""),
                "head_particle": int(record.get("head_particle", -1)),
                "tail_particle": int(record.get("tail_particle", -1)),
                "tail_follow": bool(record.get("tail_follow", True)),
            })
        matrix_bases = tuple(
            matrix.copy() if hasattr(matrix, "copy") else matrix
            for matrix in (batch.get("matrix_bases") or ())
        )
        target_matrices = tuple(
            matrix.copy() if hasattr(matrix, "copy") else matrix
            for matrix in (batch.get("target_pose_matrices") or ())
        )
        current_tails = tuple(
            tuple(float(value) for value in tail)
            for tail in (batch.get("current_tails") or ())
        )
        if len(records) != len(matrix_bases):
            raise ValueError("Bone XPBD 写回 record 与 matrix_basis 数量不一致")
        record_count += len(records)
        frozen_batches.append({
            "source_kind": str(batch.get("source_kind") or ""),
            "source_root": str(batch.get("source_root") or ""),
            "records": tuple(records),
            "matrix_bases": matrix_bases,
            "target_pose_matrices": target_matrices,
            "current_tails": current_tails,
        })
    expected_count = int(plan.get("bone_count", -1))
    if expected_count != record_count:
        raise ValueError(
            f"Bone XPBD 写回计划骨骼数不一致: plan={expected_count}, records={record_count}"
        )
    return {
        "schema": "bone_xpbd_writeback_plan_v1",
        "armature_ptr": int(plan.get("armature_ptr", 0) or 0),
        "armature_data_ptr": int(plan.get("armature_data_ptr", 0) or 0),
        "bone_count": record_count,
        "batches": tuple(frozen_batches),
    }


def make_bone_xpbd_writeback_result(
    *,
    spec,
    frame: int,
    generation: int,
    bone_count: int,
    transaction_id: str,
    transaction_index: int,
    transaction_size: int,
    publication_id: int,
) -> dict:
    result = make_bone_transform_batch_writeback(
        solver=BONE_XPBD_SOLVER_ID,
        slot_id=spec.slot_id,
        armature_ptr=spec.object_spec.armature_ptr,
        armature_data_ptr=spec.object_spec.armature_data_ptr,
        frame=frame,
        generation=generation,
        bone_count=bone_count,
        backend="xpbd_distance_context_v1",
        plan_schema="bone_xpbd_writeback_plan_v1",
        transaction_id=transaction_id,
        transaction_index=transaction_index,
        transaction_size=transaction_size,
    )
    result.update({
        "ready": True,
        "task_signature": spec.signature,
        "tail_follow": spec.tail_follow,
        "publication_id": int(publication_id),
    })
    return result


def publish_bone_xpbd_writeback_result(world, result: dict) -> dict | None:
    return world.publish_result(
        result,
        channel=BONE_TRANSFORM_CHANNEL,
        solver=BONE_XPBD_SOLVER_ID,
    )


def clear_bone_xpbd_writeback_results(world) -> None:
    world.clear_results(BONE_TRANSFORM_CHANNEL, solver=BONE_XPBD_SOLVER_ID)


def publish_bone_xpbd_stats_result(
    world,
    *,
    frame: int,
    generation: int,
    slot_count: int,
    bone_count: int,
    particle_count: int,
    stretch_constraint_count: int,
    bend_constraint_count: int,
    collider_count: int,
    stepped_slot_count: int,
    reset_slot_count: int,
    republished_slot_count: int,
    writeback_count: int,
    step_ms: float,
    status: str = "ok",
    errors=(),
) -> dict | None:
    world.clear_results(BONE_XPBD_STATS_CHANNEL, solver=BONE_XPBD_SOLVER_ID)
    result = {
        "channel": BONE_XPBD_STATS_CHANNEL,
        "solver": BONE_XPBD_SOLVER_ID,
        "backend": "xpbd_distance_context_v1",
        "frame": int(frame),
        "generation": int(generation),
        "slot_count": int(slot_count),
        "bone_count": int(bone_count),
        "particle_count": int(particle_count),
        "stretch_constraint_count": int(stretch_constraint_count),
        "bend_constraint_count": int(bend_constraint_count),
        "collider_count": int(collider_count),
        "stepped_slot_count": int(stepped_slot_count),
        "reset_slot_count": int(reset_slot_count),
        "republished_slot_count": int(republished_slot_count),
        "writeback_count": int(writeback_count),
        "step_ms": float(step_ms),
        "status": str(status),
        "errors": tuple(str(error) for error in errors),
    }
    return world.publish_result(
        result,
        channel=BONE_XPBD_STATS_CHANNEL,
        solver=BONE_XPBD_SOLVER_ID,
    )


def get_bone_xpbd_stats_result(world) -> dict | None:
    values = world.consume_results(
        BONE_XPBD_STATS_CHANNEL,
        solver=BONE_XPBD_SOLVER_ID,
    )
    return values[-1] if values else None


__all__ = [
    "clear_bone_xpbd_writeback_results",
    "freeze_bone_xpbd_writeback_plan",
    "get_bone_xpbd_stats_result",
    "make_bone_xpbd_writeback_plan",
    "make_bone_xpbd_writeback_result",
    "publish_bone_xpbd_stats_result",
    "publish_bone_xpbd_writeback_result",
]
