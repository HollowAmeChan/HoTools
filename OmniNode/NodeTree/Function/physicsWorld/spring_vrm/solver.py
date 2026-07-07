"""VRM SpringBone 新重写路径的物理世界解算器槽注册逻辑。"""

from __future__ import annotations

from ..names import SPRING_VRM_POSE_CHANNEL, SPRING_VRM_SLOT_KIND, SPRING_VRM_STEP_WRITER_ID
from ..types import PhysicsWorldCache
from .declaration import SPRING_VRM_SOLVER_DECLARATION
from .results import (
    SPRING_VRM_SOLVER_ID,
    clear_spring_vrm_pose_results,
    publish_spring_vrm_stats_result,
)
from .specs import SpringVRMSolverSpec, build_spring_vrm_solver_specs
from .implicit_objects import collect_spring_vrm_chain_objects
from .native import step_spring_vrm_slot


def register_spring_vrm_from_chain_properties(
    world: PhysicsWorldCache,
    vrm_chain_properties,
    backend: str = "cpp",
    substeps: int = 1,
) -> tuple[int, list[str]]:
    specs = build_spring_vrm_solver_specs(
        vrm_chain_properties,
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
            collider_count=int(len((world.collider_snapshot or {}).get("colliders") or ())),
            status="registered",
        )
        return len(registered_ids), registered_ids
    finally:
        world.release_write(SPRING_VRM_SOLVER_ID)


def step_spring_vrm(
    world: PhysicsWorldCache,
    enabled: bool = True,
    substeps: int = 1,
) -> tuple[int, float]:
    if not enabled or world is None or not isinstance(world, PhysicsWorldCache):
        return 0, 0.0

    chain_objects = _resolve_chain_objects(world)
    specs = build_spring_vrm_solver_specs(
        chain_objects,
        backend="cpp",
        substeps=max(1, int(substeps)),
    )

    solver_id = SPRING_VRM_STEP_WRITER_ID
    world.acquire_write(solver_id)
    try:
        clear_spring_vrm_pose_results(world)
        registered_ids = []
        chain_count = 0
        bone_count = 0
        errors: list[str] = []

        for spec in specs:
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

        fc = getattr(world, "frame_context", None)
        restart = bool(getattr(fc, "restart_required", False))
        same_frame = bool(getattr(fc, "same_frame", False))
        dt = float(getattr(fc, "dt", 0.0) or 0.0)
        if dt <= 0.0:
            dt = 1.0 / 60.0

        published = 0
        step_ms = 0.0
        if not same_frame:
            for slot_id in registered_ids:
                slot = world.solver_slots.get(slot_id)
                if slot is None:
                    continue
                count, elapsed, slot_errors = step_spring_vrm_slot(
                    world,
                    slot,
                    dt=dt,
                    substeps=max(1, int(substeps)),
                    restart=restart,
                )
                published += int(count)
                step_ms += float(elapsed)
                if slot_errors:
                    slot.data["_spring_vrm_error"] = "; ".join(str(item) for item in slot_errors)
                    errors.extend(f"{slot_id}: {item}" for item in slot_errors)
                else:
                    slot.data.pop("_spring_vrm_error", None)
        else:
            _republish_last_results(world, registered_ids)
            published = len(world.consume_results(
                SPRING_VRM_POSE_CHANNEL,
                solver=SPRING_VRM_SOLVER_ID,
                frame=int(getattr(fc, "frame", 0) or 0),
                generation=world.generation,
            ))

        publish_spring_vrm_stats_result(
            world,
            frame=int(getattr(fc, "frame", 0) or 0),
            generation=int(world.generation),
            slot_count=len(registered_ids),
            chain_count=chain_count,
            bone_count=bone_count,
            collider_count=int(len((world.collider_snapshot or {}).get("colliders") or ())),
            step_ms=step_ms,
            writeback_count=published,
            backend="cpp",
            status="ok" if not errors else "error",
            errors=errors[-8:],
        )
        return published, step_ms
    finally:
        world.release_write(solver_id)


def _resolve_chain_objects(
    world: PhysicsWorldCache,
) -> list[dict]:
    return collect_spring_vrm_chain_objects(world)


def _republish_last_results(world: PhysicsWorldCache, slot_ids: list[str]) -> None:
    frame = int(getattr(world.frame_context, "frame", 0) or 0)
    generation = int(world.generation)
    for slot_id in slot_ids:
        slot = world.solver_slots.get(slot_id)
        if slot is None:
            continue
        frame_state = slot.data.get("frame_state")
        chains = frame_state.get("chains") if isinstance(frame_state, dict) else None
        if not isinstance(chains, dict):
            continue
        for chain_state in chains.values():
            if not isinstance(chain_state, dict):
                continue
            for item in list(chain_state.get("last_results") or ()):
                if not isinstance(item, dict):
                    continue
                result = dict(item)
                result["frame"] = frame
                result["generation"] = generation
                world.publish_result(result, channel=result.get("channel"), solver=SPRING_VRM_SOLVER_ID)
