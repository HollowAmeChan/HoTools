"""Simple Cloth final-offset result envelopes."""

from __future__ import annotations

import numpy as np

from ..names import (
    GN_ATTRIBUTE_CHANNEL,
    GN_OFFSET_SPACE,
    GN_OFFSET_WRITEBACK_TYPE,
)


def _final_offset_buffer(offsets) -> np.ndarray:
    values = np.asarray(offsets, dtype=np.float32)
    if values.ndim == 1:
        if values.size % 3:
            raise ValueError("Simple Cloth offset 一维 buffer 长度必须是 3 的倍数")
        values = values.reshape((-1, 3))
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("Simple Cloth offset 必须是 float32[N,3]")
    if not np.isfinite(values).all():
        raise ValueError("Simple Cloth offset 不能包含 NaN 或 Inf")
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
    """构建一个 Simple Cloth 目标的最终对象局部 offset 快照。"""
    solver_id = str(solver or "").strip()
    stable_slot_id = str(slot_id or "").strip()
    obj_ptr = int(object_ptr)
    data_ptr = int(object_data_ptr)
    if not solver_id:
        raise ValueError("Simple Cloth offset writeback 需要 solver")
    if not stable_slot_id:
        raise ValueError("Simple Cloth offset writeback 需要稳定 slot_id/task_id")
    if obj_ptr <= 0 or data_ptr <= 0:
        raise ValueError("Simple Cloth offset writeback 需要有效 object/data pointer")
    offsets = _final_offset_buffer(local_offsets)
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
            raise ValueError("Simple Cloth offset transaction metadata is invalid")
        result.update({
            "transaction_id": tx_id,
            "transaction_index": index,
            "transaction_size": size,
        })
    elif transaction_index is not None or transaction_size is not None:
        raise ValueError(
            "Simple Cloth offset transaction index/size requires transaction_id"
        )
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
        filtered = [
            item for item in filtered
            if item.get("target_key") == str(target_key)
        ]
    return filtered


def clear_gn_offset_writebacks(world, solver: str | None = None) -> None:
    world.clear_results(GN_ATTRIBUTE_CHANNEL, solver=solver)


__all__ = [
    "clear_gn_offset_writebacks",
    "iter_gn_offset_writebacks",
    "make_gn_offset_writeback",
    "publish_gn_offset_writeback",
]
