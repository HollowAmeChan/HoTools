"""Mesh XPBD 公共 GN writeback 与私有 stats result 快照。"""

from __future__ import annotations

from ..names import GN_ATTRIBUTE_CHANNEL
from ..writeback_commands import make_gn_offset_writeback
from .names import MESH_XPBD_SOLVER_ID, MESH_XPBD_STATS_CHANNEL


def make_mesh_xpbd_writeback_result(
    *,
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
    return make_gn_offset_writeback(
        solver=MESH_XPBD_SOLVER_ID,
        slot_id=slot_id,
        object_ptr=object_ptr,
        object_data_ptr=object_data_ptr,
        frame=frame,
        generation=generation,
        local_offsets=local_offsets,
        transaction_id=transaction_id,
        transaction_index=transaction_index,
        transaction_size=transaction_size,
    )


def publish_mesh_xpbd_writeback_result(world, result: dict) -> dict | None:
    return world.publish_result(
        result,
        channel=GN_ATTRIBUTE_CHANNEL,
        solver=MESH_XPBD_SOLVER_ID,
    )


def clear_mesh_xpbd_writeback_results(world) -> None:
    world.clear_results(GN_ATTRIBUTE_CHANNEL, solver=MESH_XPBD_SOLVER_ID)


def make_mesh_xpbd_stats_result(
    *,
    frame: int,
    generation: int,
    slot_count: int,
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
) -> dict:
    return {
        "channel": MESH_XPBD_STATS_CHANNEL,
        "solver": MESH_XPBD_SOLVER_ID,
        "backend": "native_context",
        "frame": int(frame),
        "generation": int(generation),
        "slot_count": int(slot_count),
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
        "errors": [str(value) for value in errors],
    }


def publish_mesh_xpbd_stats_result(world, **kwargs) -> dict | None:
    world.clear_results(MESH_XPBD_STATS_CHANNEL, solver=MESH_XPBD_SOLVER_ID)
    result = make_mesh_xpbd_stats_result(**kwargs)
    return world.publish_result(
        result,
        channel=MESH_XPBD_STATS_CHANNEL,
        solver=MESH_XPBD_SOLVER_ID,
    )


def get_mesh_xpbd_stats_result(world) -> dict | None:
    values = world.consume_results(
        MESH_XPBD_STATS_CHANNEL,
        solver=MESH_XPBD_SOLVER_ID,
    )
    return values[-1] if values else None
