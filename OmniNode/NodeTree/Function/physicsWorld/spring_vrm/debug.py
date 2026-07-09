"""SpringBone VRM 调试快照与 native context 统计。"""

from __future__ import annotations

from ..types import PhysicsWorldCache
from .native import native_context_debug_dict, native_context_stats_dict
from .names import SPRING_VRM_DEBUG_DRAW_MODE, SPRING_VRM_SOLVER_ID
from .specs import SpringVRMSolverSpec


SPRING_VRM_DEBUG_DRAW_MODES = {
    SPRING_VRM_DEBUG_DRAW_MODE: {
        "solver": SPRING_VRM_SOLVER_ID,
        "label": "SpringBone 调试",
        "source": "solver_slot.debug_snapshot",
        "draw_item_contract": "physicsWorld.utils.debug_draw",
        "summary": (
            "SpringBone 自有调试绘制入口；只复用 physicsWorld.utils.debug_draw "
            "里的线段/GPU/基础几何工具。"
        ),
    }
}


def install_spring_vrm_slot_debug_snapshot(slot, spec: SpringVRMSolverSpec) -> None:
    slot.data["_debug_snapshot"] = (
        lambda slot=slot, spec=spec: spring_vrm_slot_debug_snapshot(slot, spec)
    )


def spring_vrm_slot_debug_snapshot(slot, spec: SpringVRMSolverSpec) -> dict:
    snapshot = spec.debug_dict()
    snapshot["native_context"] = native_context_debug_dict(slot.data.get("_native_ctxs"))
    frame_state = slot.data.get("frame_state")
    if isinstance(frame_state, dict):
        chains = frame_state.get("chains")
        snapshot["frame_state"] = {
            "spec_hash": str(frame_state.get("spec_hash") or ""),
            "chain_count": len(chains) if isinstance(chains, dict) else 0,
        }
    return snapshot


def spring_vrm_native_context_stats_for_slots(
    world: PhysicsWorldCache,
    slot_ids: list[str],
) -> dict:
    contexts = []
    for slot_id in slot_ids:
        slot = world.solver_slots.get(slot_id)
        if slot is None:
            continue
        contexts.append(native_context_stats_dict(slot.data.get("_native_ctxs")))
    return {
        "available": any(bool(item.get("available", False)) for item in contexts),
        "slot_count": len(contexts),
        "chain_count": sum(int(item.get("chain_count", 0) or 0) for item in contexts),
        "buffer_count": sum(int(item.get("buffer_count", 0) or 0) for item in contexts),
        "step_count": sum(int(item.get("step_count", 0) or 0) for item in contexts),
        "topology_serial": sum(int(item.get("topology_serial", 0) or 0) for item in contexts),
    }
