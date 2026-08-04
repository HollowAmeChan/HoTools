"""Bone XPBD Physics World slot、native step 与公共 Bone 结果事务。"""

from __future__ import annotations

from dataclasses import dataclass
import time

from ..colliders import build_mesh_xpbd_collider_frame
from ...types import PhysicsWorldCache
from .declaration import BONE_XPBD_SOLVER_DECLARATION
from .feedback import prepare_bone_xpbd_feedback
from .names import (
    BONE_XPBD_DEBUG_REQUESTERS_KEY,
    BONE_XPBD_SLOT_KIND,
    BONE_XPBD_SOLVER_ID,
    BONE_XPBD_STEP_WRITER_ID,
)
from .native import BoneXpbdNativeContext
from .pose import (
    build_bone_xpbd_pose_frame,
    target_pose_matrices_from_particles,
)
from .results import (
    clear_bone_xpbd_writeback_results,
    freeze_bone_xpbd_writeback_plan,
    make_bone_xpbd_writeback_plan,
    make_bone_xpbd_writeback_result,
    publish_bone_xpbd_stats_result,
    publish_bone_xpbd_writeback_result,
)
from .specs import BoneXpbdTaskSpec, build_bone_xpbd_task_specs
from .topology import build_bone_xpbd_topology


_PUBLICATION_SERIAL_KEY = "bone_xpbd.publication_serial"


@dataclass
class _PreparedTask:
    spec: BoneXpbdTaskSpec
    topology: object
    pose_frame: object
    colliders: object
    staged_context: BoneXpbdNativeContext | None
    replacement_reason: str


def _world_collision_radii_key(pose_frame) -> tuple[float, ...]:
    return tuple(float(value) for value in pose_frame.world_collision_radii)


def _slot_replacement_reason(world, spec, topology, pose_frame) -> str:
    slot = world.solver_slots.get(spec.slot_id)
    if slot is None:
        return "new_slot"
    if slot.kind != BONE_XPBD_SLOT_KIND:
        raise RuntimeError(f"Bone XPBD slot id 与其它 solver 冲突: {spec.slot_id}")
    owner = slot.data.get("native_context")
    if slot.world_generation != world.generation:
        return "world_generation_changed"
    if bool(getattr(world.frame_context, "restart_required", False)):
        return "world_restart"
    if not isinstance(owner, BoneXpbdNativeContext) or not owner.ready:
        return "native_context_missing"
    if slot.data.get("topology_signature") != topology.topology_signature:
        return "topology_changed"
    if slot.data.get("static_signature") != topology.static_signature:
        return "pin_or_radius_changed"
    if slot.data.get("world_collision_radii") != _world_collision_radii_key(pose_frame):
        return "armature_world_scale_changed"
    return ""


def _prepare_tasks(
    world,
    specs,
    topologies,
    logical_pose_matrices,
) -> list[_PreparedTask]:
    prepared = []
    current_staged = None
    try:
        if len(specs) != len(topologies):
            raise ValueError("Bone XPBD task 与 topology 数量不一致")
        for spec, topology in zip(specs, topologies):
            pose_frame = build_bone_xpbd_pose_frame(
                topology,
                spec,
                logical_pose_matrices,
            )
            colliders = build_mesh_xpbd_collider_frame(
                world.collider_snapshot,
                spec.armature,
                spec.collided_by_groups,
                excluded_bone_names=spec.bone_names,
            )
            reason = _slot_replacement_reason(world, spec, topology, pose_frame)
            staged = None
            if reason:
                staged = BoneXpbdNativeContext()
                current_staged = staged
                staged.rebuild(topology, pose_frame, spec)
            prepared.append(_PreparedTask(
                spec,
                topology,
                pose_frame,
                colliders,
                staged,
                reason,
            ))
            current_staged = None
    except Exception:
        if current_staged is not None:
            current_staged.dispose()
        for item in prepared:
            if item.staged_context is not None:
                item.staged_context.dispose()
        raise
    return prepared


def _dispose_slot(slot, _reason: str) -> None:
    owner = slot.data.get("native_context")
    if isinstance(owner, BoneXpbdNativeContext):
        owner.dispose()


def _adopt_context(world, item: _PreparedTask):
    slot = world.ensure_solver_slot(item.spec.slot_id, BONE_XPBD_SLOT_KIND)
    if item.staged_context is not None:
        previous = slot.data.get("native_context")
        if isinstance(previous, BoneXpbdNativeContext):
            previous.dispose()
        debug_requested = bool(slot.data.get("_debug_requested", False))
        debug_requesters = slot.data.get(BONE_XPBD_DEBUG_REQUESTERS_KEY)
        slot.data.clear()
        slot.data["_debug_requested"] = debug_requested
        if isinstance(debug_requesters, dict):
            slot.data[BONE_XPBD_DEBUG_REQUESTERS_KEY] = debug_requesters
        slot.data["native_context"] = item.staged_context
        item.staged_context = None
        world.replace_required = True
    slot.world_generation = world.generation
    slot.data["declaration"] = BONE_XPBD_SOLVER_DECLARATION
    slot.data["task_snapshot"] = item.spec.debug_dict()
    slot.data["armature_ptr"] = item.spec.object_spec.armature_ptr
    slot.data["armature_data_ptr"] = item.spec.object_spec.armature_data_ptr
    slot.data["source_name"] = item.spec.object_spec.armature_name
    slot.data["bone_names"] = item.spec.bone_names
    slot.data["topology"] = item.topology
    slot.data["topology_signature"] = item.topology.topology_signature
    slot.data["static_signature"] = item.topology.static_signature
    slot.data["world_collision_radii"] = _world_collision_radii_key(item.pose_frame)
    slot.data.setdefault("writeback_plan", {})
    slot.data["_dispose"] = lambda reason, slot=slot: _dispose_slot(slot, reason)
    return slot


def _prune_stale_slots(world, active_slot_ids) -> int:
    active = set(active_slot_ids)
    stale = [
        slot_id
        for slot_id, slot in list(world.solver_slots.items())
        if slot.kind == BONE_XPBD_SLOT_KIND and slot_id not in active
    ]
    for slot_id in stale:
        slot = world.solver_slots.pop(slot_id, None)
        if slot is not None:
            slot.dispose("bone_xpbd_task_prune")
    if stale:
        world.replace_required = True
    return len(stale)


def _discard_failed_slots(world, prepared, error: Exception) -> None:
    """失败后的 native 状态已不可提交；整批丢弃，下一次从输入姿态重建。"""

    for item in prepared:
        if item.staged_context is not None:
            item.staged_context.dispose()
            item.staged_context = None
    _discard_spec_slots(
        world,
        (item.spec for item in prepared),
        reason="bone_xpbd_step_failed",
        error=error,
    )


def _discard_spec_slots(world, specs, *, reason: str, error: Exception) -> None:
    """只丢弃本批 Bone XPBD owner，solver-kind 冲突时不碰其它域。"""

    removed = False
    for spec in specs:
        slot = world.solver_slots.get(spec.slot_id)
        if slot is None or slot.kind != BONE_XPBD_SLOT_KIND:
            continue
        world.solver_slots.pop(spec.slot_id, None)
        slot.data["_bone_xpbd_error"] = str(error)
        slot.dispose(reason)
        removed = True
    if removed:
        world.replace_required = True


def _discard_all_bone_xpbd_slots(world, *, reason: str) -> int:
    slot_ids = [
        slot_id
        for slot_id, slot in tuple(world.solver_slots.items())
        if slot.kind == BONE_XPBD_SLOT_KIND
    ]
    for slot_id in slot_ids:
        slot = world.solver_slots.pop(slot_id, None)
        if slot is not None:
            slot.dispose(reason)
    if slot_ids:
        world.replace_required = True
    return len(slot_ids)


def _publish_task_parse_failure(world, *, frame, generation, started, error):
    world.acquire_write(BONE_XPBD_STEP_WRITER_ID)
    try:
        clear_bone_xpbd_writeback_results(world)
        _discard_all_bone_xpbd_slots(
            world,
            reason="bone_xpbd_task_parse_failed",
        )
        publish_bone_xpbd_stats_result(
            world,
            frame=frame,
            generation=generation,
            slot_count=0,
            bone_count=0,
            particle_count=0,
            stretch_constraint_count=0,
            bend_constraint_count=0,
            collider_count=0,
            stepped_slot_count=0,
            reset_slot_count=0,
            republished_slot_count=0,
            writeback_count=0,
            step_ms=(time.perf_counter() - started) * 1000.0,
            status="error",
            errors=(str(error),),
        )
    finally:
        world.release_write(BONE_XPBD_STEP_WRITER_ID)


def _publish_prepare_failure(world, active_specs, *, frame, generation, started, error):
    world.acquire_write(BONE_XPBD_STEP_WRITER_ID)
    try:
        clear_bone_xpbd_writeback_results(world)
        _discard_spec_slots(
            world,
            active_specs,
            reason="bone_xpbd_prepare_failed",
            error=error,
        )
        publish_bone_xpbd_stats_result(
            world,
            frame=frame,
            generation=generation,
            slot_count=len(active_specs),
            bone_count=0,
            particle_count=0,
            stretch_constraint_count=0,
            bend_constraint_count=0,
            collider_count=0,
            stepped_slot_count=0,
            reset_slot_count=0,
            republished_slot_count=0,
            writeback_count=0,
            step_ms=(time.perf_counter() - started) * 1000.0,
            status="error",
            errors=(str(error),),
        )
    finally:
        world.release_write(BONE_XPBD_STEP_WRITER_ID)


def _stats_counts(prepared) -> tuple[int, int, int, int, int]:
    return (
        sum(len(item.topology.segments) for item in prepared),
        sum(item.topology.particle_count for item in prepared),
        sum(int(item.topology.stretch_indices.shape[0]) for item in prepared),
        sum(int(item.topology.bend_indices.shape[0]) for item in prepared),
        sum(item.colliders.collider_count for item in prepared),
    )


def _next_publication_id(world) -> int:
    publication_id = int(
        world.runtime_caches.get(_PUBLICATION_SERIAL_KEY, 0) or 0
    ) + 1
    world.runtime_caches[_PUBLICATION_SERIAL_KEY] = publication_id
    return publication_id


def _capture_slot_debug(
    slot,
    item,
    positions,
    decision,
    elapsed_ms,
    frame,
    generation,
    *,
    capture_requested: bool,
):
    slot.data["debug_summary"] = {
        "schema": "bone_xpbd_slot_debug_v1",
        "slot_id": slot.slot_id,
        "source_name": item.spec.object_spec.armature_name,
        "bone_names": item.spec.bone_names,
        "decision": decision,
        "frame": frame,
        "generation": generation,
        "elapsed_ms": float(elapsed_ms),
        "tail_follow": item.spec.tail_follow,
        "particle_count": item.topology.particle_count,
        "segment_count": len(item.topology.segments),
        "native_stats": slot.data["native_context"].stats(),
    }
    if not capture_requested:
        slot.data.pop("debug_capture", None)
        return
    slot.data["debug_capture"] = {
        "world_positions": positions.copy(),
        "rest_world_positions": item.pose_frame.world_positions.copy(),
        "segment_pins": item.topology.segment_pins.copy(),
        "inverse_masses": item.topology.inverse_masses.copy(),
        "endpoint_particles": item.topology.endpoint_particles.copy(),
        "stretch_indices": item.topology.stretch_indices.copy(),
        "bend_indices": item.topology.bend_indices.copy(),
        "segments": tuple(segment.debug_dict() for segment in item.topology.segments),
    }


def step_bone_xpbd(
    world: PhysicsWorldCache,
    task_values,
    *,
    debug_capture: bool = False,
) -> tuple[int, float]:
    if not isinstance(world, PhysicsWorldCache):
        return 0, 0.0
    started = time.perf_counter()
    frame_context = world.frame_context
    frame = int(getattr(frame_context, "frame", 0) or 0)
    generation = int(world.generation)
    try:
        specs = build_bone_xpbd_task_specs(task_values)
    except Exception as exc:
        _publish_task_parse_failure(
            world,
            frame=frame,
            generation=generation,
            started=started,
            error=exc,
        )
        raise
    active_specs = tuple(spec for spec in specs if spec.enabled)
    try:
        topologies = tuple(
            build_bone_xpbd_topology(spec, world=world)
            for spec in active_specs
        )
        pinned_bone_keys = {
            (
                topology.armature_ptr,
                topology.armature_data_ptr,
                segment.bone_name,
            )
            for topology in topologies
            for segment, pinned in zip(topology.segments, topology.segment_pins)
            if bool(pinned)
        }
        feedback_stage = prepare_bone_xpbd_feedback(
            world,
            active_specs,
            pinned_bone_keys=pinned_bone_keys,
        )
        prepared = _prepare_tasks(
            world,
            active_specs,
            topologies,
            feedback_stage.logical_pose_matrices,
        )
    except Exception as exc:
        _publish_prepare_failure(
            world,
            active_specs,
            frame=frame,
            generation=generation,
            started=started,
            error=exc,
        )
        raise
    same_frame = bool(getattr(frame_context, "same_frame", False))
    delta_time = float(getattr(frame_context, "dt", 0.0) or 0.0)
    substeps = max(1, min(16, int(getattr(frame_context, "substeps", 1) or 1)))
    bone_count, particle_count, stretch_count, bend_count, collider_count = (
        _stats_counts(prepared)
    )

    world.acquire_write(BONE_XPBD_STEP_WRITER_ID)
    try:
        clear_bone_xpbd_writeback_results(world)
        pending = []
        stepped_count = 0
        reset_count = 0
        republished_count = 0
        for item in prepared:
            slot = _adopt_context(world, item)
            owner = slot.data["native_context"]
            if not item.replacement_reason:
                owner.update_pin_targets(item.pose_frame)
                if slot.data.get("parameter_signature") != item.spec.parameter_signature:
                    owner.update_parameters(item.spec)
            slot_started = time.perf_counter()
            if item.replacement_reason:
                owner.reset(item.pose_frame)
                positions = owner.read_positions()
                decision = "reset"
                reset_count += 1
            elif same_frame:
                positions = owner.read_positions()
                decision = "same_frame_republish"
                republished_count += 1
            elif delta_time <= 0.0:
                positions = owner.read_positions()
                decision = "paused_republish"
                republished_count += 1
            else:
                positions = owner.step(
                    delta_time=delta_time,
                    substeps=substeps,
                    gravity_direction=item.spec.gravity_direction,
                    gravity_power=item.spec.gravity_power,
                    colliders=item.colliders,
                    collided_by_groups=item.spec.collided_by_groups,
                )
                decision = "step"
                stepped_count += 1
            pending.append((
                item,
                slot,
                positions,
                decision,
                (time.perf_counter() - slot_started) * 1000.0,
            ))

        targets_by_item = []
        grouped_targets: dict[tuple[int, int], dict[str, object]] = {}
        for item, _slot, positions, _decision, _elapsed in pending:
            targets = target_pose_matrices_from_particles(
                item.topology,
                item.pose_frame,
                positions,
                tail_follow=item.spec.tail_follow,
            )
            key = (
                item.spec.object_spec.armature_ptr,
                item.spec.object_spec.armature_data_ptr,
            )
            group = grouped_targets.setdefault(key, {})
            overlap = set(group).intersection(targets)
            if overlap:
                raise ValueError(f"Bone XPBD 写回目标重叠: {sorted(overlap)}")
            group.update(targets)
            targets_by_item.append(targets)

        runtime_plans = []
        results = []
        publication_id = _next_publication_id(world)
        transaction_sizes = {}
        for item, _slot, _positions, _decision, _elapsed in pending:
            key = (
                item.spec.object_spec.armature_ptr,
                item.spec.object_spec.armature_data_ptr,
            )
            transaction_sizes[key] = transaction_sizes.get(key, 0) + 1
        transaction_indices = {key: 0 for key in transaction_sizes}
        for pending_item, targets in zip(pending, targets_by_item):
            item, slot, positions, _decision, _elapsed = pending_item
            key = (
                item.spec.object_spec.armature_ptr,
                item.spec.object_spec.armature_data_ptr,
            )
            plan = make_bone_xpbd_writeback_plan(
                spec=item.spec,
                topology=item.topology,
                target_pose_matrices=targets,
                all_target_pose_matrices=grouped_targets[key],
                world_positions=positions,
            )
            runtime_plans.append(plan)
            transaction_index = transaction_indices[key]
            transaction_indices[key] += 1
            transaction_id = (
                f"{BONE_XPBD_SOLVER_ID}:{generation}:{frame}:{publication_id}:"
                f"{key[0]}:{key[1]}"
            )
            results.append(make_bone_xpbd_writeback_result(
                spec=item.spec,
                frame=frame,
                generation=generation,
                bone_count=plan["bone_count"],
                transaction_id=transaction_id,
                transaction_index=transaction_index,
                transaction_size=transaction_sizes[key],
                publication_id=publication_id,
            ))
        feedback_stage.stage_writeback_expectations(runtime_plans, results)
        plans = tuple(
            freeze_bone_xpbd_writeback_plan(plan)
            for plan in runtime_plans
        )
        for (_item, slot, _positions, _decision, _elapsed), plan in zip(pending, plans):
            previous_plan = slot.data.get("writeback_plan")
            previous_buffer = (
                previous_plan.get("basis_values")
                if isinstance(previous_plan, dict)
                else None
            )
            if isinstance(previous_buffer, list):
                plan["basis_values"] = previous_buffer
            slot.data["writeback_plan"] = plan
        for result in results:
            if publish_bone_xpbd_writeback_result(world, result) is None:
                raise RuntimeError("Bone XPBD 公共写回结果发布失败")

        for item, slot, positions, decision, elapsed_ms in pending:
            slot.data["parameter_signature"] = item.spec.parameter_signature
            slot.data["last_result"] = next(
                result for result in results if result["slot_id"] == slot.slot_id
            )
            slot.data.pop("_bone_xpbd_error", None)
            node_debug_requested = bool(
                slot.data.pop("_debug_requested", False)
            )
            _capture_slot_debug(
                slot,
                item,
                positions,
                decision,
                elapsed_ms,
                frame,
                generation,
                capture_requested=(
                    bool(debug_capture)
                    or node_debug_requested
                ),
            )

        _prune_stale_slots(world, (item.spec.slot_id for item in prepared))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        publish_bone_xpbd_stats_result(
            world,
            frame=frame,
            generation=generation,
            slot_count=len(prepared),
            bone_count=bone_count,
            particle_count=particle_count,
            stretch_constraint_count=stretch_count,
            bend_constraint_count=bend_count,
            collider_count=collider_count,
            stepped_slot_count=stepped_count,
            reset_slot_count=reset_count,
            republished_slot_count=republished_count,
            writeback_count=len(results),
            step_ms=elapsed_ms,
        )
        # 反馈只在结果、调试与统计全部成功后提交，避免失败帧伪装成已写回。
        feedback_stage.commit(world)
        return len(results), elapsed_ms
    except Exception as exc:
        clear_bone_xpbd_writeback_results(world)
        _discard_failed_slots(world, prepared, exc)
        publish_bone_xpbd_stats_result(
            world,
            frame=frame,
            generation=generation,
            slot_count=len(prepared),
            bone_count=bone_count,
            particle_count=particle_count,
            stretch_constraint_count=stretch_count,
            bend_constraint_count=bend_count,
            collider_count=collider_count,
            stepped_slot_count=0,
            reset_slot_count=0,
            republished_slot_count=0,
            writeback_count=0,
            step_ms=(time.perf_counter() - started) * 1000.0,
            status="error",
            errors=(str(exc),),
        )
        raise
    finally:
        world.release_write(BONE_XPBD_STEP_WRITER_ID)


__all__ = ["step_bone_xpbd"]
