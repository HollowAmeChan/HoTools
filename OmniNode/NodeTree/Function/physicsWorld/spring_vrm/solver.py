"""VRM SpringBone 新重写路径的物理世界解算器槽注册逻辑。"""

from __future__ import annotations

from ..types import PhysicsWorldCache
from .declaration import SPRING_VRM_SOLVER_DECLARATION
from .names import (
    SPRING_VRM_SLOT_KIND,
    SPRING_VRM_SOLVER_ID,
    SPRING_VRM_STEP_WRITER_ID,
)
from .results import (
    clear_spring_vrm_pose_results,
    publish_spring_vrm_pose_batch_result,
    publish_spring_vrm_stats_result,
)
from .specs import SpringVRMSolverSpec, build_spring_vrm_solver_specs
from .implicit_objects import collect_spring_vrm_chain_objects
from .debug import (
    install_spring_vrm_slot_debug_snapshot,
    spring_vrm_native_context_stats_for_slots,
)
from .native import step_spring_vrm_slot


def _dispose_spring_vrm_slot(slot, reason: str) -> None:
    contexts = slot.data.get("_native_ctxs")
    if not isinstance(contexts, dict):
        return
    for context in list(contexts.values()):
        dispose = getattr(context, "dispose", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:
                pass
    contexts.clear()


def _install_spring_vrm_slot_dispose(slot) -> None:
    slot.data["_dispose"] = (
        lambda reason, slot=slot: _dispose_spring_vrm_slot(slot, reason)
    )


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


def _register_slots_from_specs(
    world: PhysicsWorldCache,
    specs,
) -> tuple[list[str], int, int]:
    """把 specs 落进 world.solver_slots，返回 (registered_ids, chain_count, bone_count)。

    register_spring_vrm_specs（外部注册入口）和 step_spring_vrm（节点每帧路径）
    共用这段 slot 生命周期逻辑，避免两处并行真值源漂移（见 ARCHITECTURE §7.3）。
    调用方负责 acquire_write / clear_spring_vrm_pose_results / prune / 发布 stats。
    """
    registered_ids: list[str] = []
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
        slot.data.setdefault("_native_ctxs", {})
        slot.data.setdefault("writeback_plan", {})
        _install_spring_vrm_slot_dispose(slot)
        install_spring_vrm_slot_debug_snapshot(slot, spec)

        registered_ids.append(spec.slot_id)
        chain_count += int(spec.chain_count)
        bone_count += int(spec.simulated_bone_count)

    return registered_ids, chain_count, bone_count


def register_spring_vrm_specs(
    world: PhysicsWorldCache,
    specs,
) -> tuple[int, list[str]]:
    if world is None or not isinstance(world, PhysicsWorldCache):
        return 0, []

    world.acquire_write(SPRING_VRM_SOLVER_ID)
    try:
        clear_spring_vrm_pose_results(world)
        registered_ids, chain_count, bone_count = _register_slots_from_specs(world, specs)

        _prune_stale_spring_vrm_slots(world, registered_ids)

        publish_spring_vrm_stats_result(
            world,
            frame=int(getattr(world.frame_context, "frame", 0) or 0),
            generation=int(world.generation),
            slot_count=len(registered_ids),
            chain_count=chain_count,
            bone_count=bone_count,
            collider_count=int(len((world.collider_snapshot or {}).get("colliders") or ())),
            status="registered",
            native_context=spring_vrm_native_context_stats_for_slots(world, registered_ids),
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

    fc = getattr(world, "frame_context", None)
    effective_substeps = max(1, min(16, int(substeps or 1)))

    chain_objects = _resolve_chain_objects(world)
    specs = build_spring_vrm_solver_specs(
        chain_objects,
        backend="cpp",
        substeps=effective_substeps,
    )

    solver_id = SPRING_VRM_STEP_WRITER_ID
    world.acquire_write(solver_id)
    try:
        clear_spring_vrm_pose_results(world)
        errors: list[str] = []

        registered_ids, chain_count, bone_count = _register_slots_from_specs(world, specs)

        _prune_stale_spring_vrm_slots(world, registered_ids)

        restart = bool(getattr(fc, "restart_required", False))
        same_frame = bool(getattr(fc, "same_frame", False))
        dt = float(getattr(fc, "dt", 0.0) or 0.0)
        paused = dt <= 0.0

        published = 0
        step_ms = 0.0
        if not same_frame and (not paused or restart):
            for slot_id in registered_ids:
                slot = world.solver_slots.get(slot_id)
                if slot is None:
                    continue
                count, elapsed, slot_errors = step_spring_vrm_slot(
                    world,
                    slot,
                    dt=dt,
                    substeps=effective_substeps,
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
            published = _republish_writeback_plans(world, registered_ids)

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
            native_context=spring_vrm_native_context_stats_for_slots(world, registered_ids),
        )
        return published, step_ms
    finally:
        world.release_write(solver_id)


def _resolve_chain_objects(
    world: PhysicsWorldCache,
) -> list[dict]:
    return collect_spring_vrm_chain_objects(world)


def _prune_stale_spring_vrm_slots(world: PhysicsWorldCache, active_slot_ids) -> int:
    active = set(str(slot_id) for slot_id in (active_slot_ids or ()))
    stale_ids = [
        slot_id
        for slot_id, slot in list(world.solver_slots.items())
        if slot.kind == SPRING_VRM_SLOT_KIND and slot_id not in active
    ]
    for slot_id in stale_ids:
        slot = world.solver_slots.pop(slot_id, None)
        if slot is None:
            continue
        try:
            slot.dispose("spring_vrm_scope_prune")
        except Exception:
            pass
    if stale_ids:
        world.replace_required = True
    return len(stale_ids)


def _republish_writeback_plans(world: PhysicsWorldCache, slot_ids: list[str]) -> int:
    frame = int(getattr(world.frame_context, "frame", 0) or 0)
    generation = int(world.generation)
    published = 0
    for slot_id in slot_ids:
        slot = world.solver_slots.get(slot_id)
        if slot is None:
            continue
        plan = slot.data.get("writeback_plan")
        if not isinstance(plan, dict):
            continue
        batches = plan.get("batches") or ()
        bone_count = max(0, int(plan.get("bone_count", 0) or 0))
        armature = plan.get("armature")
        if not batches or not bone_count or armature is None:
            continue
        plan["frame"] = frame
        plan["generation"] = generation
        publish_spring_vrm_pose_batch_result(
            world,
            slot_id=slot_id,
            armature_ptr=int(plan.get("armature_ptr", 0) or 0),
            armature_data_ptr=int(plan.get("armature_data_ptr", 0) or 0),
            frame=frame,
            generation=generation,
            bone_count=bone_count,
            plan_schema=str(plan.get("schema") or ""),
        )
        published += bone_count
    return published
