"""VRM SpringBone 新重写路径的物理世界解算器槽注册逻辑。"""

from __future__ import annotations

from ..types import PhysicsWorldCache
from .declaration import SPRING_VRM_SOLVER_DECLARATION
from .results import (
    SPRING_VRM_SOLVER_ID,
    clear_spring_vrm_pose_results,
    publish_spring_vrm_stats_result,
)
from .specs import SpringVRMSolverSpec, build_spring_vrm_solver_specs


SPRING_VRM_SLOT_KIND = "spring_vrm"


def register_spring_vrm_from_chain_settings(
    world: PhysicsWorldCache,
    vrm_chain_settings,
    backend: str = "cpp",
    substeps: int = 1,
) -> tuple[int, list[str]]:
    specs = build_spring_vrm_solver_specs(
        vrm_chain_settings,
        backend=backend,
        substeps=substeps,
    )
    return register_spring_vrm_specs(world, specs)


def register_spring_vrm_specs(
    world: PhysicsWorldCache,
    specs,
) -> tuple[int, list[str]]:
    if world is None or not isinstance(world, PhysicsWorldCache):
        return 0, []

    world.acquire_write(SPRING_VRM_SOLVER_ID)
    try:
        clear_spring_vrm_pose_results(world)
        registered_ids = []
        chain_count = 0
        bone_count = 0

        for spec in list(specs or ()):
            if not isinstance(spec, SpringVRMSolverSpec):
                continue
            slot = world.ensure_solver_slot(spec.slot_id, SPRING_VRM_SLOT_KIND)
            if slot.world_generation != world.generation:
                slot.dispose("world_generation_changed")
                slot.world_generation = world.generation

            slot.data["spec"] = spec
            slot.data["declaration"] = SPRING_VRM_SOLVER_DECLARATION
            slot.data.setdefault("frame_state", {})
            slot.data.setdefault("native_context", {})
            slot.data.setdefault("writeback_plan", {})
            slot.data["_debug_snapshot"] = lambda s=spec: s.debug_dict()

            registered_ids.append(spec.slot_id)
            chain_count += int(spec.chain_count)
            bone_count += int(spec.simulated_bone_count)

        publish_spring_vrm_stats_result(
            world,
            frame=int(getattr(world.frame_context, "frame", 0) or 0),
            generation=int(world.generation),
            slot_count=len(registered_ids),
            chain_count=chain_count,
            bone_count=bone_count,
            collider_count=int((world.collider_snapshot or {}).get("source_count", 0) or 0),
            status="registered",
        )
        return len(registered_ids), registered_ids
    finally:
        world.release_write(SPRING_VRM_SOLVER_ID)
