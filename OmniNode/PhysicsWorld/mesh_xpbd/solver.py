"""Mesh XPBD Physics World slot、native step 与 result 事务。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time

from ..types import PhysicsWorldCache
from .colliders import build_mesh_xpbd_collider_frame
from .debug import (
    install_mesh_xpbd_slot_debug_snapshot,
    update_mesh_xpbd_slot_debug,
)
from .declaration import MESH_XPBD_SOLVER_DECLARATION
from .names import (
    MESH_XPBD_SLOT_KIND,
    MESH_XPBD_SOLVER_ID,
    MESH_XPBD_STEP_WRITER_ID,
)
from .native import MeshXpbdNativeContext
from .results import (
    clear_mesh_xpbd_writeback_results,
    make_mesh_xpbd_writeback_result,
    publish_mesh_xpbd_stats_result,
    publish_mesh_xpbd_writeback_result,
)
from .specs import MeshXpbdTaskSpec, build_mesh_xpbd_task_specs
from .topology import (
    MeshXpbdReferenceFrame,
    MeshXpbdTopology,
    build_mesh_xpbd_reference_frame,
    build_mesh_xpbd_topology,
)


@dataclass
class _PreparedTask:
    spec: MeshXpbdTaskSpec
    topology: MeshXpbdTopology
    reference: MeshXpbdReferenceFrame
    colliders: object
    staged_context: MeshXpbdNativeContext | None
    replacement_reason: str


def _slot_needs_replacement(world, spec, topology) -> tuple[bool, str]:
    slot = world.solver_slots.get(spec.slot_id)
    if slot is None:
        return True, "new_slot"
    if slot.kind != MESH_XPBD_SLOT_KIND:
        raise RuntimeError(
            f"Mesh XPBD slot id 与其它 solver kind 冲突: {spec.slot_id}"
        )
    owner = slot.data.get("native_context")
    if slot.world_generation != world.generation:
        return True, "world_generation_changed"
    if not isinstance(owner, MeshXpbdNativeContext) or not owner.ready:
        return True, "native_context_missing"
    if slot.data.get("topology_signature") != topology.topology_signature:
        return True, "topology_changed"
    return False, ""


def _prepare_tasks(world, specs) -> list[_PreparedTask]:
    prepared = []
    current_staged = None
    try:
        for spec in specs:
            topology = build_mesh_xpbd_topology(spec)
            reference = build_mesh_xpbd_reference_frame(
                topology, spec.source_object
            )
            collider_frame = build_mesh_xpbd_collider_frame(
                world.collider_snapshot,
                spec.source_object,
                spec.collided_by_groups,
            )
            replace, reason = _slot_needs_replacement(world, spec, topology)
            staged = None
            if replace:
                staged = MeshXpbdNativeContext()
                current_staged = staged
                staged.rebuild(topology, reference, spec)
                staged.reset(reference)
            prepared.append(_PreparedTask(
                spec,
                topology,
                reference,
                collider_frame,
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


def _dispose_mesh_xpbd_slot(slot, reason: str) -> None:
    owner = slot.data.get("native_context")
    if isinstance(owner, MeshXpbdNativeContext):
        owner.dispose()


def _install_slot_lifecycle(slot) -> None:
    slot.data["_dispose"] = (
        lambda reason, slot=slot: _dispose_mesh_xpbd_slot(slot, reason)
    )
    install_mesh_xpbd_slot_debug_snapshot(slot)


def _adopt_prepared_context(world, item: _PreparedTask):
    slot = world.ensure_solver_slot(item.spec.slot_id, MESH_XPBD_SLOT_KIND)
    if item.staged_context is not None:
        previous = slot.data.get("native_context")
        if isinstance(previous, MeshXpbdNativeContext):
            previous.dispose()
        slot.data.clear()
        slot.data["native_context"] = item.staged_context
        item.staged_context = None
        world.replace_required = True
    slot.world_generation = world.generation
    slot.data["declaration"] = MESH_XPBD_SOLVER_DECLARATION
    slot.data["source_name"] = item.spec.source_name
    slot.data["source_object_ptr"] = item.spec.source_object_ptr
    slot.data["source_data_ptr"] = item.spec.source_data_ptr
    slot.data["topology"] = item.topology
    slot.data["topology_signature"] = item.topology.topology_signature
    slot.data.setdefault("writeback_plan", {})
    _install_slot_lifecycle(slot)
    return slot


def _transaction_id(prepared, frame: int, generation: int) -> str | None:
    if len(prepared) <= 1:
        return None
    digest = hashlib.sha256()
    for item in prepared:
        digest.update(item.spec.slot_id.encode("utf-8"))
        digest.update(b"\0")
    return f"mesh_xpbd:{generation}:{frame}:{digest.hexdigest()[:16]}"


def _prune_stale_slots(world, active_slot_ids) -> int:
    active = set(active_slot_ids)
    stale = [
        slot_id
        for slot_id, slot in list(world.solver_slots.items())
        if slot.kind == MESH_XPBD_SLOT_KIND and slot_id not in active
    ]
    for slot_id in stale:
        slot = world.solver_slots.pop(slot_id, None)
        if slot is not None:
            slot.dispose("mesh_xpbd_task_prune")
    if stale:
        world.replace_required = True
    return len(stale)


def _stats_counts(prepared) -> tuple[int, int, int, int]:
    return (
        sum(item.topology.particle_count for item in prepared),
        sum(int(item.topology.stretch_indices.shape[0]) for item in prepared),
        sum(int(item.topology.bend_indices.shape[0]) for item in prepared),
        sum(item.colliders.collider_count for item in prepared),
    )


def step_mesh_xpbd(
    world: PhysicsWorldCache,
    task_values,
    *,
    debug_capture: bool = False,
) -> tuple[int, float]:
    if not isinstance(world, PhysicsWorldCache):
        return 0, 0.0
    started = time.perf_counter()
    specs = build_mesh_xpbd_task_specs(task_values)
    active_specs = tuple(spec for spec in specs if spec.enabled)
    prepared = _prepare_tasks(world, active_specs)
    frame_context = world.frame_context
    frame = int(getattr(frame_context, "frame", 0) or 0)
    generation = int(world.generation)
    same_frame = bool(getattr(frame_context, "same_frame", False))
    restart = bool(getattr(frame_context, "restart_required", False))
    delta_time = float(getattr(frame_context, "dt", 0.0) or 0.0)
    substeps = max(1, min(16, int(getattr(frame_context, "substeps", 1) or 1)))
    particle_count, stretch_count, bend_count, collider_count = _stats_counts(prepared)

    world.acquire_write(MESH_XPBD_STEP_WRITER_ID)
    try:
        clear_mesh_xpbd_writeback_results(world)
        pending = []
        stepped_count = 0
        reset_count = 0
        republished_count = 0
        active_slot_ids = [item.spec.slot_id for item in prepared]

        for item in prepared:
            slot = _adopt_prepared_context(world, item)
            owner = slot.data["native_context"]
            static_dirty = (
                slot.data.get("static_signature") != item.topology.static_signature
            )
            reference_dirty = (
                slot.data.get("reference_signature") != item.reference.signature
            )
            parameter_dirty = (
                slot.data.get("parameter_signature") != item.spec.parameter_signature
            )
            if item.replacement_reason:
                static_dirty = False
                reference_dirty = False
                parameter_dirty = False
            else:
                if static_dirty or reference_dirty:
                    owner.update_reference(item.topology, item.reference)
                if parameter_dirty:
                    owner.update_parameters(item.spec)

            must_reset = bool(item.replacement_reason or static_dirty or restart)
            slot_started = time.perf_counter()
            if must_reset:
                owner.reset(item.reference)
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
            local_offsets = item.reference.local_offsets(positions)
            elapsed_ms = (time.perf_counter() - slot_started) * 1000.0
            pending.append((item, slot, positions, local_offsets, decision, elapsed_ms))

        transaction_id = _transaction_id(prepared, frame, generation)
        results = []
        for index, (item, _slot, _positions, offsets, _decision, _elapsed) in enumerate(pending):
            kwargs = {}
            if transaction_id is not None:
                kwargs = {
                    "transaction_id": transaction_id,
                    "transaction_index": index,
                    "transaction_size": len(pending),
                }
            results.append(make_mesh_xpbd_writeback_result(
                slot_id=item.spec.slot_id,
                object_ptr=item.spec.source_object_ptr,
                object_data_ptr=item.spec.source_data_ptr,
                frame=frame,
                generation=generation,
                local_offsets=offsets,
                **kwargs,
            ))

        for result in results:
            publish_mesh_xpbd_writeback_result(world, result)
        for (item, slot, positions, offsets, decision, elapsed_ms), result in zip(pending, results):
            slot.data["static_signature"] = item.topology.static_signature
            slot.data["reference_signature"] = item.reference.signature
            slot.data["parameter_signature"] = item.spec.parameter_signature
            slot.data["last_result"] = result
            slot.data["writeback_plan"] = {
                "object_ptr": item.spec.source_object_ptr,
                "object_data_ptr": item.spec.source_data_ptr,
                "vertex_count": item.topology.particle_count,
            }
            slot.data.pop("_mesh_xpbd_error", None)
            update_mesh_xpbd_slot_debug(
                slot,
                topology=item.topology,
                colliders=item.colliders,
                decision=decision,
                frame=frame,
                generation=generation,
                elapsed_ms=elapsed_ms,
                native_stats=slot.data["native_context"].stats(),
                capture=bool(debug_capture),
                world_positions=positions,
                local_offsets=offsets,
            )

        _prune_stale_slots(world, active_slot_ids)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        publish_mesh_xpbd_stats_result(
            world,
            frame=frame,
            generation=generation,
            slot_count=len(prepared),
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
        return len(results), elapsed_ms
    except Exception as exc:
        clear_mesh_xpbd_writeback_results(world)
        for item in prepared:
            if item.staged_context is not None:
                item.staged_context.dispose()
        publish_mesh_xpbd_stats_result(
            world,
            frame=frame,
            generation=generation,
            slot_count=len(prepared),
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
        world.release_write(MESH_XPBD_STEP_WRITER_ID)
