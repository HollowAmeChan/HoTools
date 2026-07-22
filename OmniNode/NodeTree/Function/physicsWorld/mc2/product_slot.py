"""Physics World slot lifecycle for the fused MeshCloth CPU owner."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..types import PhysicsSolverSlot
from ..types import PhysicsWorldCache
from .collider_frame import MC2DomainColliderFrameSpec
from .domain_collect import build_mc2_mesh_domain_collider_frame
from .domain_ir import MC2DomainFramePacketV1
from .domain_owner import MC2FusedCPUOwnerSyncReportV1
from .domain_owner import MC2MeshFusedCPUOwnerV1
from .product_collect import MC2MeshProductCollectionV1
from .product_scheduler import MC2MeshProductScheduledFrameV1
from .product_scheduler import MC2MeshProductSchedulerStateV1
from .reference_step import make_mc2_compiled_domain_pipeline_settings


MC2_FUSED_MESH_SLOT_ID = "mc2.domain.mesh.product.v1"
MC2_FUSED_MESH_SLOT_KIND = "mc2_fused_mesh_cpu_v1"
_MC2_FUSED_MESH_WRITER = "mc2_fused_mesh_cpu"


@dataclass(frozen=True)
class MC2FusedMeshSlotSyncResultV1:
    action: str
    slot_id: str
    world_generation: int
    owner_report: MC2FusedCPUOwnerSyncReportV1

    def __post_init__(self) -> None:
        if self.action not in {"created", "updated", "replaced"}:
            raise ValueError("invalid fused Mesh slot action")
        if self.slot_id != MC2_FUSED_MESH_SLOT_ID:
            raise ValueError("invalid fused Mesh slot id")
        if self.world_generation < 0:
            raise ValueError("world_generation cannot be negative")
        if not isinstance(self.owner_report, MC2FusedCPUOwnerSyncReportV1):
            raise TypeError("owner_report must be MC2FusedCPUOwnerSyncReportV1")

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_fused_mesh_slot_sync_result_v1",
            "action": self.action,
            "slot_id": self.slot_id,
            "world_generation": self.world_generation,
            "owner": self.owner_report.debug_dict(),
        }


@dataclass(frozen=True)
class MC2FusedMeshFramePublishResultV1:
    frame: int
    generation: int
    partition_ids: tuple[str, ...]
    collider_count: int
    update_count: int
    skip_count: int

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_fused_mesh_frame_publish_result_v1",
            "frame": self.frame,
            "generation": self.generation,
            "partition_ids": list(self.partition_ids),
            "collider_count": self.collider_count,
            "update_count": self.update_count,
            "skip_count": self.skip_count,
        }


@dataclass(frozen=True)
class MC2FusedMeshSubstepResultV1:
    frame: int
    generation: int
    update_index: int
    update_count: int
    frame_interpolation: float
    is_final_substep: bool
    scheduler_revision: int

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_fused_mesh_substep_result_v1",
            "frame": self.frame,
            "generation": self.generation,
            "update_index": self.update_index,
            "update_count": self.update_count,
            "frame_interpolation": self.frame_interpolation,
            "is_final_substep": self.is_final_substep,
            "scheduler_revision": self.scheduler_revision,
        }


def _dispose_slot_owner(slot: PhysicsSolverSlot, _reason: str) -> None:
    owner = slot.data.get("owner")
    if isinstance(owner, MC2MeshFusedCPUOwnerV1):
        owner.dispose()


def _slot_debug_snapshot(slot: PhysicsSolverSlot) -> dict:
    owner = slot.data.get("owner")
    collection = slot.data.get("collection")
    scheduler_state = slot.data.get("scheduler_state")
    return {
        "slot_id": slot.slot_id,
        "kind": slot.kind,
        "world_generation": slot.world_generation,
        "owner": owner.inspect() if isinstance(owner, MC2MeshFusedCPUOwnerV1) else None,
        "collection": (
            collection.debug_dict()
            if isinstance(collection, MC2MeshProductCollectionV1)
            else None
        ),
        "scheduler_state": (
            scheduler_state.debug_dict()
            if isinstance(scheduler_state, MC2MeshProductSchedulerStateV1)
            else None
        ),
        "frame_ready": bool(slot.data.get("frame_ready", False)),
        "completed_substeps": int(slot.data.get("completed_substeps", 0)),
        "frame_complete": bool(slot.data.get("frame_complete", False)),
        "last_step_failure": slot.data.get("last_step_failure"),
    }


def _make_slot(world, owner, collection, report) -> PhysicsSolverSlot:
    slot = PhysicsSolverSlot(
        MC2_FUSED_MESH_SLOT_ID,
        MC2_FUSED_MESH_SLOT_KIND,
        int(world.generation),
    )
    slot.data.update({
        "owner": owner,
        "collection": collection,
        "last_sync": report,
        "scheduler_state": MC2MeshProductSchedulerStateV1(
            owner.compiled.program.partition_ids
        ),
        "product_enabled": False,
        "frame_ready": False,
        "completed_substeps": 0,
        "frame_complete": False,
        "_dispose": lambda reason, slot=slot: _dispose_slot_owner(slot, reason),
        "_debug_snapshot": lambda slot=slot: _slot_debug_snapshot(slot),
    })
    return slot


def sync_mc2_mesh_fused_slot(
    world: PhysicsWorldCache,
    collection: MC2MeshProductCollectionV1,
    *,
    kernel=None,
) -> MC2FusedMeshSlotSyncResultV1:
    """Stage or update the world owner without enabling the product solve path."""

    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world must be PhysicsWorldCache")
    if not isinstance(collection, MC2MeshProductCollectionV1):
        raise TypeError("collection must be MC2MeshProductCollectionV1")
    generation = int(world.generation)
    existing = world.solver_slots.get(MC2_FUSED_MESH_SLOT_ID)
    reusable = (
        existing is not None
        and existing.kind == MC2_FUSED_MESH_SLOT_KIND
        and existing.world_generation == generation
        and isinstance(existing.data.get("owner"), MC2MeshFusedCPUOwnerV1)
        and existing.data["owner"].domain is not None
    )

    if reusable:
        world.acquire_write(_MC2_FUSED_MESH_WRITER)
        try:
            report = existing.data["owner"].sync(
                collection.draft,
                collection.static_snapshots,
                world_gravity_directions=collection.world_gravity_directions,
            )
            existing.data["collection"] = collection
            existing.data["last_sync"] = report
            if not report.native_domain_reused:
                existing.data["scheduler_state"] = MC2MeshProductSchedulerStateV1(
                    existing.data["owner"].compiled.program.partition_ids
                )
                existing.data["frame_ready"] = False
                for name in (
                    "frame_packet",
                    "partition_frame_snapshots",
                    "collider_frame",
                    "scheduled_frame",
                    "last_substep",
                    "last_step_failure",
                ):
                    existing.data.pop(name, None)
                existing.data["completed_substeps"] = 0
                existing.data["frame_complete"] = False
        finally:
            world.release_write(_MC2_FUSED_MESH_WRITER)
        return MC2FusedMeshSlotSyncResultV1(
            action="updated",
            slot_id=MC2_FUSED_MESH_SLOT_ID,
            world_generation=generation,
            owner_report=report,
        )

    if kernel is None:
        from .cpu_native_kernel import MC2NativeCPUKernelV1

        kernel = MC2NativeCPUKernelV1()
    staged_owner = MC2MeshFusedCPUOwnerV1(kernel)
    try:
        report = staged_owner.sync(
            collection.draft,
            collection.static_snapshots,
            world_gravity_directions=collection.world_gravity_directions,
        )
        staged_slot = _make_slot(world, staged_owner, collection, report)
    except Exception:
        staged_owner.dispose()
        raise

    world.acquire_write(_MC2_FUSED_MESH_WRITER)
    try:
        old_slot = world.solver_slots.get(MC2_FUSED_MESH_SLOT_ID)
        world.solver_slots[MC2_FUSED_MESH_SLOT_ID] = staged_slot
    finally:
        world.release_write(_MC2_FUSED_MESH_WRITER)
    if old_slot is not None:
        old_slot.dispose("mc2_fused_mesh_staged_replacement")
    return MC2FusedMeshSlotSyncResultV1(
        action="created" if old_slot is None else "replaced",
        slot_id=MC2_FUSED_MESH_SLOT_ID,
        world_generation=generation,
        owner_report=report,
    )


def publish_mc2_mesh_fused_frame(
    world: PhysicsWorldCache,
    slot: PhysicsSolverSlot,
    scheduled_frame: MC2MeshProductScheduledFrameV1,
    collider_frame: MC2DomainColliderFrameSpec,
    *,
    partition_snapshots=(),
) -> MC2FusedMeshFramePublishResultV1:
    """Atomically publish one prepared frame to the still-current fused owner."""

    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world must be PhysicsWorldCache")
    if not isinstance(slot, PhysicsSolverSlot) or slot.kind != MC2_FUSED_MESH_SLOT_KIND:
        raise TypeError("slot must be the fused Mesh PhysicsSolverSlot")
    if not isinstance(scheduled_frame, MC2MeshProductScheduledFrameV1):
        raise TypeError("scheduled_frame must be MC2MeshProductScheduledFrameV1")
    frame_packet = scheduled_frame.frame_packet
    if not isinstance(collider_frame, MC2DomainColliderFrameSpec):
        raise TypeError("collider_frame must be MC2DomainColliderFrameSpec")
    if collider_frame.frame != frame_packet.frame:
        raise ValueError("fused Mesh frame and collider frame numbers must match")
    owner = slot.data.get("owner")
    collection = slot.data.get("collection")
    scheduler_state = slot.data.get("scheduler_state")
    if not isinstance(owner, MC2MeshFusedCPUOwnerV1) or not isinstance(
        collection, MC2MeshProductCollectionV1
    ):
        raise RuntimeError("fused Mesh slot is incomplete")
    if owner.compiled is None:
        raise RuntimeError("fused Mesh owner has no compiled program")
    if not isinstance(scheduler_state, MC2MeshProductSchedulerStateV1):
        raise RuntimeError("fused Mesh slot has no product scheduler state")
    program = owner.compiled.program
    if (
        frame_packet.domain_signature != program.domain_signature
        or frame_packet.layout_signature != program.layout_signature
    ):
        raise ValueError("fused Mesh frame identity does not match the live owner")
    if scheduler_state.partition_ids != tuple(program.partition_ids):
        raise ValueError("fused Mesh scheduler partition identity is stale")
    scheduler_state.validate_commit(scheduled_frame)

    world.acquire_write(_MC2_FUSED_MESH_WRITER)
    try:
        if (
            world.solver_slots.get(MC2_FUSED_MESH_SLOT_ID) is not slot
            or slot.world_generation != int(world.generation)
            or slot.data.get("owner") is not owner
        ):
            raise RuntimeError("fused Mesh slot changed while its frame was captured")
        scheduler_state.validate_commit(scheduled_frame)
        owner.update_frame(frame_packet)
        scheduler_state.commit(scheduled_frame)
        slot.data["frame_packet"] = frame_packet
        slot.data["scheduled_frame"] = scheduled_frame
        slot.data["partition_frame_snapshots"] = tuple(partition_snapshots)
        slot.data["collider_frame"] = collider_frame
        slot.data["frame_ready"] = True
        slot.data["completed_substeps"] = 0
        slot.data["frame_complete"] = scheduled_frame.schedule.update_count == 0
        slot.data.pop("last_substep", None)
        slot.data.pop("last_step_failure", None)
    finally:
        world.release_write(_MC2_FUSED_MESH_WRITER)
    return MC2FusedMeshFramePublishResultV1(
        frame=int(frame_packet.frame),
        generation=int(frame_packet.generation),
        partition_ids=tuple(program.partition_ids),
        collider_count=int(collider_frame.collider_count),
        update_count=int(scheduled_frame.schedule.update_count),
        skip_count=int(scheduled_frame.schedule.skip_count),
    )


def step_mc2_mesh_fused_substep(
    world: PhysicsWorldCache,
    slot: PhysicsSolverSlot | None = None,
) -> MC2FusedMeshSubstepResultV1:
    """Execute and commit exactly one staged E4 whole-domain substep."""

    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world must be PhysicsWorldCache")
    if slot is None:
        slot = world.solver_slots.get(MC2_FUSED_MESH_SLOT_ID)
    if not isinstance(slot, PhysicsSolverSlot) or slot.kind != MC2_FUSED_MESH_SLOT_KIND:
        raise TypeError("slot must be the fused Mesh PhysicsSolverSlot")
    owner = slot.data.get("owner")
    scheduler_state = slot.data.get("scheduler_state")
    scheduled_frame = slot.data.get("scheduled_frame")
    collider_frame = slot.data.get("collider_frame")
    if not isinstance(owner, MC2MeshFusedCPUOwnerV1) or owner.compiled is None:
        raise RuntimeError("fused Mesh slot has no live owner")
    if not isinstance(scheduler_state, MC2MeshProductSchedulerStateV1):
        raise RuntimeError("fused Mesh slot has no product scheduler state")
    if not isinstance(scheduled_frame, MC2MeshProductScheduledFrameV1) or not isinstance(
        collider_frame, MC2DomainColliderFrameSpec
    ):
        raise RuntimeError("fused Mesh slot has no published frame")
    if not bool(slot.data.get("frame_ready", False)):
        raise RuntimeError("fused Mesh frame is not ready")
    if bool(slot.data.get("frame_complete", False)):
        raise RuntimeError("fused Mesh frame has no pending substeps")

    world.acquire_write(_MC2_FUSED_MESH_WRITER)
    try:
        if (
            world.solver_slots.get(MC2_FUSED_MESH_SLOT_ID) is not slot
            or slot.world_generation != int(world.generation)
            or slot.data.get("owner") is not owner
            or slot.data.get("scheduler_state") is not scheduler_state
        ):
            raise RuntimeError("fused Mesh slot changed before its substep")
        update_index = int(slot.data.get("completed_substeps", 0))
        staged_substep = scheduler_state.stage_substep(update_index)
        pose = owner.prepare_step_basic_pose()
        # V0 product execution currently never supplies distance-culling weights;
        # make that observed all-enabled behavior explicit per partition.
        distance_weights = np.ones(
            owner.compiled.program.partition_count,
            dtype=np.float32,
        )
        distance_weights.flags.writeable = False
        settings = make_mc2_compiled_domain_pipeline_settings(
            owner.compiled,
            scheduled_frame.frame_packet,
            staged_substep.plan,
            anchor_component_local_positions=(
                scheduled_frame.anchor_component_local_positions
            ),
            step_basic_positions=pose["positions"],
            step_basic_rotations=pose["rotations"],
            distance_weights=distance_weights,
            external_collision=collider_frame.native_mapping(),
        )
        try:
            owner.step(settings)
        except Exception as exc:
            slot.data["last_step_failure"] = f"{type(exc).__name__}: {exc}"
            raise
        scheduler_state.commit_substep(staged_substep)
        completed = update_index + 1
        is_final = bool(staged_substep.plan.is_final_substep)
        result = MC2FusedMeshSubstepResultV1(
            frame=int(scheduled_frame.frame_packet.frame),
            generation=int(scheduled_frame.frame_packet.generation),
            update_index=update_index,
            update_count=int(scheduled_frame.schedule.update_count),
            frame_interpolation=float(staged_substep.plan.frame_interpolation),
            is_final_substep=is_final,
            scheduler_revision=scheduler_state.revision,
        )
        slot.data["completed_substeps"] = completed
        slot.data["frame_complete"] = is_final
        slot.data["last_substep"] = result
        slot.data.pop("last_step_failure", None)
        return result
    finally:
        world.release_write(_MC2_FUSED_MESH_WRITER)


def capture_and_publish_mc2_mesh_fused_frame(
    world: PhysicsWorldCache,
    *,
    settings=None,
    depsgraph=None,
    partition_frame_flags=None,
    velocity_weights=None,
    gravity_ratios=None,
) -> MC2FusedMeshFramePublishResultV1:
    """Capture all partition and collider POD before publishing under the World lock."""

    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world must be PhysicsWorldCache")
    slot = world.solver_slots.get(MC2_FUSED_MESH_SLOT_ID)
    if slot is None or slot.kind != MC2_FUSED_MESH_SLOT_KIND:
        raise RuntimeError("Physics World has no fused Mesh slot")
    owner = slot.data.get("owner")
    collection = slot.data.get("collection")
    if not isinstance(owner, MC2MeshFusedCPUOwnerV1) or not isinstance(
        collection, MC2MeshProductCollectionV1
    ):
        raise RuntimeError("fused Mesh slot is incomplete")
    scheduler_state = slot.data.get("scheduler_state")
    if not isinstance(scheduler_state, MC2MeshProductSchedulerStateV1):
        raise RuntimeError("fused Mesh slot has no product scheduler state")
    from .parameters import MC2SolverSettingsSpec
    from .parameters import make_mc2_solver_settings

    if settings is None:
        settings = make_mc2_solver_settings()
    if not isinstance(settings, MC2SolverSettingsSpec):
        raise TypeError("settings must be MC2SolverSettingsSpec")
    from .product_frame import capture_mc2_mesh_product_frame

    frame_context = getattr(world, "frame_context", None)
    if frame_context is None:
        raise RuntimeError("Physics World has no active frame context")
    initialization_only = (
        "frame_packet" not in slot.data
        or bool(getattr(frame_context, "restart_required", False))
        or bool(getattr(frame_context, "reset_requested", False))
    )
    if partition_frame_flags is None and initialization_only:
        partition_frame_flags = (1,) * len(collection.draft.partitions)

    frame_packet, partition_snapshots = capture_mc2_mesh_product_frame(
        world,
        collection,
        owner,
        depsgraph=depsgraph,
        partition_frame_flags=partition_frame_flags,
        velocity_weights=velocity_weights,
        gravity_ratios=gravity_ratios,
    )
    world_time_scale = float(getattr(frame_context, "time_scale", 0.0) or 0.0)
    frame_delta_time = float(getattr(frame_context, "raw_dt", 0.0) or 0.0)
    effective_time_scale = world_time_scale * float(settings.time_scale)
    if frame_delta_time <= 0.0 and effective_time_scale > 0.0:
        effective_dt = (
            float(getattr(frame_context, "dt", 0.0) or 0.0)
            * float(settings.time_scale)
        )
        frame_delta_time = effective_dt / effective_time_scale
    scheduled_frame = scheduler_state.stage_frame(
        frame_packet,
        settings,
        frame_delta_time=frame_delta_time,
        world_time_scale=world_time_scale,
        initialize_only=initialization_only,
    )
    collider_frame = build_mc2_mesh_domain_collider_frame(world, collection.draft)
    return publish_mc2_mesh_fused_frame(
        world,
        slot,
        scheduled_frame,
        collider_frame,
        partition_snapshots=partition_snapshots,
    )


__all__ = [
    "MC2_FUSED_MESH_SLOT_ID",
    "MC2_FUSED_MESH_SLOT_KIND",
    "MC2FusedMeshFramePublishResultV1",
    "MC2FusedMeshSubstepResultV1",
    "MC2FusedMeshSlotSyncResultV1",
    "capture_and_publish_mc2_mesh_fused_frame",
    "publish_mc2_mesh_fused_frame",
    "step_mc2_mesh_fused_substep",
    "sync_mc2_mesh_fused_slot",
]
