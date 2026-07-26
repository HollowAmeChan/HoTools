"""通用写回指令。

solver 只负责把本帧要写回的目标和数据发布到这里；真正写 Blender 数据由
physicsWorld.writeback 统一执行。
"""

from __future__ import annotations

import numpy as np

from .names import (
    BONE_TRANSFORM_CHANNEL,
    GN_ATTRIBUTE_CHANNEL,
    GN_OFFSET_SPACE,
    GN_OFFSET_WRITEBACK_TYPE,
)
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


def _final_gn_offset_buffer(offsets) -> np.ndarray:
    values = np.asarray(offsets, dtype=np.float32)
    if values.ndim == 1:
        if values.size % 3:
            raise ValueError("GN offset 一维 buffer 长度必须是 3 的倍数")
        values = values.reshape((-1, 3))
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("GN offset 必须是 float32[N,3]")
    if not np.isfinite(values).all():
        raise ValueError("GN offset 不能包含 NaN 或 Inf")
    snapshot = np.array(values, dtype=np.float32, order="C", copy=True)
    snapshot.setflags(write=False)
    return snapshot


def make_gn_offset_writeback(
    *,
    solver: str,
    slot_id: str,
    object_ptr: int,
    object_data_ptr: int,
    frame: int,
    generation: int,
    local_offsets,
    transaction_id: str | None = None,
    transaction_index: int | None = None,
    transaction_size: int | None = None,
) -> dict:
    """构建一个 Mesh 目标的最终对象局部 offset 快照。

    该命令没有 attribute name、blend mode 或 solver 私有输出槽。多个中间
    offset 必须在发布前通过 exchange 归并为 ``local_offsets``。
    """
    solver_id = str(solver or "").strip()
    stable_slot_id = str(slot_id or "").strip()
    obj_ptr = int(object_ptr)
    data_ptr = int(object_data_ptr)
    if not solver_id:
        raise ValueError("GN offset writeback 需要 solver")
    if not stable_slot_id:
        raise ValueError("GN offset writeback 需要稳定 slot_id/task_id")
    if obj_ptr <= 0 or data_ptr <= 0:
        raise ValueError("GN offset writeback 需要有效 object/data pointer")
    offsets = _final_gn_offset_buffer(local_offsets)
    result = {
        "channel": GN_ATTRIBUTE_CHANNEL,
        "writeback_type": GN_OFFSET_WRITEBACK_TYPE,
        "offset_space": GN_OFFSET_SPACE,
        "solver": solver_id,
        "slot_id": stable_slot_id,
        "writer_id": f"{solver_id}:{stable_slot_id}",
        "frame": int(frame),
        "generation": int(generation),
        "object_ptr": obj_ptr,
        "object_data_ptr": data_ptr,
        "target_key": f"{obj_ptr}:{data_ptr}",
        "vertex_count": int(offsets.shape[0]),
        "local_offsets": offsets,
    }
    if transaction_id is not None:
        tx_id = str(transaction_id or "").strip()
        index = int(transaction_index) if transaction_index is not None else -1
        size = int(transaction_size) if transaction_size is not None else -1
        if not tx_id or index < 0 or size <= 0 or index >= size:
            raise ValueError("GN offset transaction metadata is invalid")
        result.update({
            "transaction_id": tx_id,
            "transaction_index": index,
            "transaction_size": size,
        })
    elif transaction_index is not None or transaction_size is not None:
        raise ValueError("GN offset transaction index/size requires transaction_id")
    return result


def publish_gn_offset_writeback(world, **kwargs) -> dict | None:
    result = make_gn_offset_writeback(**kwargs)
    return world.publish_result(
        result,
        channel=GN_ATTRIBUTE_CHANNEL,
        solver=result["solver"],
    )


def iter_gn_offset_writebacks(
    world,
    frame: int | None = None,
    generation: int | None = None,
    solver: str | None = None,
    slot_id: str | None = None,
    target_key: str | None = None,
) -> list[dict]:
    items = world.consume_results(
        GN_ATTRIBUTE_CHANNEL,
        solver=solver,
        frame=frame,
        generation=generation,
    )
    filtered = [
        item for item in items
        if isinstance(item, dict)
        and item.get("channel") == GN_ATTRIBUTE_CHANNEL
        and item.get("writeback_type") == GN_OFFSET_WRITEBACK_TYPE
        and item.get("offset_space") == GN_OFFSET_SPACE
    ]
    if slot_id is not None:
        filtered = [item for item in filtered if item.get("slot_id") == str(slot_id)]
    if target_key is not None:
        filtered = [item for item in filtered if item.get("target_key") == str(target_key)]
    return filtered


def clear_gn_offset_writebacks(world, solver: str | None = None) -> None:
    world.clear_results(GN_ATTRIBUTE_CHANNEL, solver=solver)
