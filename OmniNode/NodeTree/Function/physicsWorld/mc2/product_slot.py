"""Physics World 中统一粒子域 CPU 产品 slot 的生命周期。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..types import PhysicsSolverSlot
from ..types import PhysicsWorldCache
from .collider_frame import MC2DomainColliderFrameSpec
from .domain_collect import build_mc2_domain_collider_frame_for_draft
from .domain_collect import build_mc2_mesh_domain_collider_frame
from .domain_ir import MC2DomainFramePacketV1
from .domain_output import MC2MeshWritebackBatchV1
from .domain_output import make_mc2_mesh_writeback_batch
from .domain_owner import MC2FusedCPUOwnerSyncReportV1
from .domain_owner import MC2FusedCPUOwnerV1
from .names import MC2_FUSED_PRODUCT_SLOT_KIND
from .names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from .names import MC2_SETUP_MESH_CLOTH
from .setups.bone_cloth.product import MC2BoneProductCollectionV1
from .setups.mesh_cloth.product import MC2MeshProductCollectionV1
from .setups.mesh_cloth.product import validate_mc2_mesh_product_output_batch
from .product_scheduler import MC2ProductScheduledFrameV1
from .product_scheduler import MC2ProductSchedulerStateV1
from .reference_step import make_mc2_compiled_domain_pipeline_settings
from .results import make_mc2_mesh_domain_results
from .results import make_mc2_bone_domain_results
from .results import publish_mc2_result_transaction


MC2_FUSED_MESH_SLOT_ID = "mc2.domain.mesh.product.v1"
_MC2_FUSED_PRODUCT_WRITER = "mc2_fused_cpu_product"
_MC2_CONSTRAINT_DEBUG_ANGLE = 1
_MC2_CONSTRAINT_DEBUG_MOTION = 2
_MC2_CONSTRAINT_DEBUG_DISTANCE = 4
_MC2_CONSTRAINT_DEBUG_TETHER = 8
_MC2_CONSTRAINT_DEBUG_BENDING = 16
_MC2_CONSTRAINT_DEBUG_EXTERNAL_COLLISION = 32
_MC2_CONSTRAINT_DEBUG_WHOLE_DOMAIN_SELF = 64


def _constraint_debug_mask(filters: dict) -> int:
    mask = 0
    if filters.get("show_angle_restoration") or filters.get("show_angle_limit"):
        mask |= _MC2_CONSTRAINT_DEBUG_ANGLE
    if filters.get("show_motion"):
        mask |= _MC2_CONSTRAINT_DEBUG_MOTION
    if filters.get("show_distance"):
        mask |= _MC2_CONSTRAINT_DEBUG_DISTANCE
    if filters.get("show_tether"):
        mask |= _MC2_CONSTRAINT_DEBUG_TETHER
    if filters.get("show_bending"):
        mask |= _MC2_CONSTRAINT_DEBUG_BENDING
    if (
        filters.get("show_collision")
        or filters.get("show_collision_contacts")
        or filters.get("show_radii")
    ):
        mask |= _MC2_CONSTRAINT_DEBUG_EXTERNAL_COLLISION
    if any(filters.get(name) for name in (
        "show_self_primitives",
        "show_self_grid",
        "show_self_candidates",
        "show_self_contacts",
    )):
        mask |= _MC2_CONSTRAINT_DEBUG_WHOLE_DOMAIN_SELF
    return mask


def make_mc2_product_slot_id(setup_type: str, domain_signature: str) -> str:
    setup = str(setup_type or "").strip()
    signature = str(domain_signature or "").strip()
    if not setup or len(signature) != 64:
        raise ValueError("product slot requires setup type and domain signature")
    return f"mc2.domain.product.v1:{setup}:{signature}"


def _is_product_collection(value) -> bool:
    return isinstance(value, (MC2MeshProductCollectionV1, MC2BoneProductCollectionV1))


@dataclass(frozen=True)
class MC2FusedProductSlotSyncResultV1:
    action: str
    slot_id: str
    world_generation: int
    owner_report: MC2FusedCPUOwnerSyncReportV1

    def __post_init__(self) -> None:
        if self.action not in {"created", "updated", "replaced"}:
            raise ValueError("invalid fused Mesh slot action")
        if not str(self.slot_id or "").strip():
            raise ValueError("invalid fused product slot id")
        if self.world_generation < 0:
            raise ValueError("world_generation cannot be negative")
        if not isinstance(self.owner_report, MC2FusedCPUOwnerSyncReportV1):
            raise TypeError("owner_report must be MC2FusedCPUOwnerSyncReportV1")

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_fused_product_slot_sync_result_v1",
            "action": self.action,
            "slot_id": self.slot_id,
            "world_generation": self.world_generation,
            "owner": self.owner_report.debug_dict(),
        }


@dataclass(frozen=True)
class MC2FusedProductFramePublishResultV1:
    frame: int
    generation: int
    partition_ids: tuple[str, ...]
    collider_count: int
    update_count: int
    skip_count: int

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_fused_product_frame_publish_result_v1",
            "frame": self.frame,
            "generation": self.generation,
            "partition_ids": list(self.partition_ids),
            "collider_count": self.collider_count,
            "update_count": self.update_count,
            "skip_count": self.skip_count,
        }


@dataclass(frozen=True)
class MC2FusedProductSubstepResultV1:
    frame: int
    generation: int
    update_index: int
    update_count: int
    frame_interpolation: float
    is_final_substep: bool
    scheduler_revision: int

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_fused_product_substep_result_v1",
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
    if isinstance(owner, MC2FusedCPUOwnerV1):
        owner.dispose()


def _slot_debug_snapshot(slot: PhysicsSolverSlot) -> dict:
    owner = slot.data.get("owner")
    collection = slot.data.get("collection")
    scheduler_state = slot.data.get("scheduler_state")
    return {
        "slot_id": slot.slot_id,
        "kind": slot.kind,
        "world_generation": slot.world_generation,
        "owner": owner.inspect() if isinstance(owner, MC2FusedCPUOwnerV1) else None,
        "collection": (
            collection.debug_dict()
            if _is_product_collection(collection)
            else None
        ),
        "scheduler_state": (
            scheduler_state.debug_dict()
            if isinstance(scheduler_state, MC2ProductSchedulerStateV1)
            else None
        ),
        "frame_ready": bool(slot.data.get("frame_ready", False)),
        "completed_substeps": int(slot.data.get("completed_substeps", 0)),
        "frame_complete": bool(slot.data.get("frame_complete", False)),
        "last_step_failure": slot.data.get("last_step_failure"),
    }


def _make_slot(world, owner, collection, report, *, slot_id: str) -> PhysicsSolverSlot:
    slot = PhysicsSolverSlot(
        slot_id,
        MC2_FUSED_PRODUCT_SLOT_KIND,
        int(world.generation),
    )
    slot.data.update({
        "owner": owner,
        "collection": collection,
        "last_sync": report,
        "scheduler_state": MC2ProductSchedulerStateV1(
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


def _sync_product_static(owner: MC2FusedCPUOwnerV1, collection):
    frame_state_stage = None
    if isinstance(collection, MC2MeshProductCollectionV1):
        return owner.sync(
            collection.draft,
            collection.static_snapshots,
            world_gravity_directions=collection.world_gravity_directions,
        )
    if isinstance(collection, MC2BoneProductCollectionV1):
        from .setups.bone_cloth.fragment_cache import MC2BoneFragmentCacheV1

        cache = owner.fragment_cache
        if not isinstance(cache, MC2BoneFragmentCacheV1):
            raise TypeError("Bone product owner has an incompatible fragment cache")
        batch = cache.stage(collection.static_inputs)
        return owner.sync_fragments(
            collection.draft,
            batch.fragments,
            fragment_cache_revision=cache.revision + 1,
            fragment_cache_hits=batch.hit_count,
            fragment_builds=batch.build_count,
            commit_static=lambda: cache.commit(batch),
        )
    raise TypeError("collection must be an MC2 product collection")


def _make_product_owner(kernel, collection) -> MC2FusedCPUOwnerV1:
    if isinstance(collection, MC2BoneProductCollectionV1):
        from .setups.bone_cloth.fragment_cache import MC2BoneFragmentCacheV1

        return MC2FusedCPUOwnerV1(
            kernel,
            fragment_cache=MC2BoneFragmentCacheV1(),
        )
    if isinstance(collection, MC2MeshProductCollectionV1):
        return MC2FusedCPUOwnerV1(kernel)
    raise TypeError("collection must be an MC2 product collection")


def sync_mc2_product_slot(
    world: PhysicsWorldCache,
    collection,
    *,
    slot_id: str,
    kernel=None,
) -> MC2FusedProductSlotSyncResultV1:
    """创建或更新一个显式产品域，不启用任何旧 task fallback。"""

    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world must be PhysicsWorldCache")
    if not _is_product_collection(collection):
        raise TypeError("collection must be an MC2 product collection")
    slot_id = str(slot_id or "").strip()
    if not slot_id:
        raise ValueError("slot_id cannot be empty")
    generation = int(world.generation)
    existing = world.solver_slots.get(slot_id)
    reusable = (
        existing is not None
        and existing.kind == MC2_FUSED_PRODUCT_SLOT_KIND
        and existing.world_generation == generation
        and isinstance(existing.data.get("owner"), MC2FusedCPUOwnerV1)
        and existing.data["owner"].domain is not None
    )

    if reusable:
        world.acquire_write(_MC2_FUSED_PRODUCT_WRITER)
        try:
            report = _sync_product_static(existing.data["owner"], collection)
            existing.data["collection"] = collection
            existing.data["last_sync"] = report
            if not report.native_domain_reused:
                existing.data["scheduler_state"] = MC2ProductSchedulerStateV1(
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
                    "output_batch",
                    "domain_output",
                    "output_results",
                    "output_writeback_plans",
                    "published_output_batch",
                    "published_output_results",
                    "published_output_writeback_plans",
                    "writeback_plan",
                ):
                    existing.data.pop(name, None)
                existing.data["completed_substeps"] = 0
                existing.data["frame_complete"] = False
        finally:
            world.release_write(_MC2_FUSED_PRODUCT_WRITER)
        return MC2FusedProductSlotSyncResultV1(
            action="updated",
            slot_id=slot_id,
            world_generation=generation,
            owner_report=report,
        )

    if kernel is None:
        from .cpu_native_kernel import MC2NativeCPUKernelV1

        kernel = MC2NativeCPUKernelV1()
    staged_owner = _make_product_owner(kernel, collection)
    try:
        report = _sync_product_static(staged_owner, collection)
        staged_slot = _make_slot(
            world,
            staged_owner,
            collection,
            report,
            slot_id=slot_id,
        )
    except Exception:
        staged_owner.dispose()
        raise

    world.acquire_write(_MC2_FUSED_PRODUCT_WRITER)
    try:
        old_slot = world.solver_slots.get(slot_id)
        world.solver_slots[slot_id] = staged_slot
    finally:
        world.release_write(_MC2_FUSED_PRODUCT_WRITER)
    if old_slot is not None:
        old_slot.dispose("mc2_fused_mesh_staged_replacement")
    return MC2FusedProductSlotSyncResultV1(
        action="created" if old_slot is None else "replaced",
        slot_id=slot_id,
        world_generation=generation,
        owner_report=report,
    )


def discard_mc2_product_slots(
    world: PhysicsWorldCache,
    slot_ids,
    *,
    reason: str,
) -> tuple[str, ...]:
    """失败关闭：先从 world 摘除整批产品 slot，再释放其 native owner。"""

    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world must be PhysicsWorldCache")
    frozen_ids = tuple(dict.fromkeys(
        str(slot_id or "").strip() for slot_id in slot_ids
    ))
    if any(not slot_id for slot_id in frozen_ids):
        raise ValueError("product slot id cannot be empty")
    removed = []
    world.acquire_write(_MC2_FUSED_PRODUCT_WRITER)
    try:
        for slot_id in frozen_ids:
            slot = world.solver_slots.get(slot_id)
            if (
                isinstance(slot, PhysicsSolverSlot)
                and slot.kind == MC2_FUSED_PRODUCT_SLOT_KIND
            ):
                world.solver_slots.pop(slot_id, None)
                removed.append(slot)
    finally:
        world.release_write(_MC2_FUSED_PRODUCT_WRITER)
    for slot in removed:
        slot.dispose(str(reason or "mc2_product_batch_failure"))
    return tuple(slot.slot_id for slot in removed)


def publish_mc2_product_output_transaction(
    world: PhysicsWorldCache,
    slots,
    results,
    *,
    bone_writeback_plans=None,
) -> tuple[dict, ...]:
    """一次发布多个显式 domain，并同步提交最终 Bone 反馈指纹。"""

    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world must be PhysicsWorldCache")
    frozen_slots = tuple(slots)
    if not frozen_slots:
        raise ValueError("product output transaction requires at least one slot")
    if any(
        not isinstance(slot, PhysicsSolverSlot)
        or slot.kind != MC2_FUSED_PRODUCT_SLOT_KIND
        for slot in frozen_slots
    ):
        raise TypeError("product output transaction contains an invalid slot")
    slot_ids = tuple(slot.slot_id for slot in frozen_slots)
    if len(set(slot_ids)) != len(slot_ids):
        raise ValueError("product output transaction contains duplicate slots")

    frozen_results = tuple(results)
    plans = dict(bone_writeback_plans or {})
    published_plan_ids = tuple(dict.fromkeys(
        str(result.get("slot_id") or "")
        for result in frozen_results
        if isinstance(result, dict)
        and str(result.get("slot_id") or "") in plans
    ))
    feedback_stage = None
    if published_plan_ids:
        from .setups.bone_frame_input import prepare_mc2_bone_writeback_expectations

        feedback_stage = prepare_mc2_bone_writeback_expectations(
            world,
            tuple(plans[slot_id] for slot_id in published_plan_ids),
        )

    world.acquire_write(_MC2_FUSED_PRODUCT_WRITER)
    try:
        generation = int(world.generation)
        for slot in frozen_slots:
            if (
                world.solver_slots.get(slot.slot_id) is not slot
                or slot.world_generation != generation
            ):
                raise RuntimeError(
                    "product slot changed before batch result publication"
                )
        if feedback_stage is not None:
            feedback_stage.validate(world)
        published = publish_mc2_result_transaction(world, frozen_results)
        if feedback_stage is not None:
            feedback_stage.commit(world)
        for slot in frozen_slots:
            slot_results = tuple(
                result
                for result in published
                if str(result.get("slot_id") or "") == slot.slot_id
            )
            slot.data["published_output_results"] = slot_results
            if "output_batch" in slot.data:
                slot.data["published_output_batch"] = slot.data["output_batch"]
            if slot.slot_id in plans:
                slot.data["published_output_writeback_plans"] = plans
                slot.data["writeback_plan"] = plans[slot.slot_id]
        return published
    finally:
        world.release_write(_MC2_FUSED_PRODUCT_WRITER)


def publish_mc2_product_frame(
    world: PhysicsWorldCache,
    slot: PhysicsSolverSlot,
    scheduled_frame: MC2ProductScheduledFrameV1,
    collider_frame: MC2DomainColliderFrameSpec,
    *,
    partition_snapshots=(),
    frame_state_stage=None,
) -> MC2FusedProductFramePublishResultV1:
    """把准备完成的整域帧原子发布到仍为 current 的产品 owner。"""

    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world must be PhysicsWorldCache")
    if not isinstance(slot, PhysicsSolverSlot) or slot.kind != MC2_FUSED_PRODUCT_SLOT_KIND:
        raise TypeError("slot must be an MC2 fused product PhysicsSolverSlot")
    if not isinstance(scheduled_frame, MC2ProductScheduledFrameV1):
        raise TypeError("scheduled_frame must be MC2ProductScheduledFrameV1")
    frame_packet = scheduled_frame.frame_packet
    if not isinstance(collider_frame, MC2DomainColliderFrameSpec):
        raise TypeError("collider_frame must be MC2DomainColliderFrameSpec")
    if collider_frame.frame != frame_packet.frame:
        raise ValueError("product frame and collider frame numbers must match")
    owner = slot.data.get("owner")
    collection = slot.data.get("collection")
    scheduler_state = slot.data.get("scheduler_state")
    if not isinstance(owner, MC2FusedCPUOwnerV1) or not _is_product_collection(
        collection
    ):
        raise RuntimeError("fused product slot is incomplete")
    if owner.compiled is None:
        raise RuntimeError("fused Mesh owner has no compiled program")
    if not isinstance(scheduler_state, MC2ProductSchedulerStateV1):
        raise RuntimeError("fused product slot has no product scheduler state")
    program = owner.compiled.program
    if (
        frame_packet.domain_signature != program.domain_signature
        or frame_packet.layout_signature != program.layout_signature
    ):
        raise ValueError("fused Mesh frame identity does not match the live owner")
    if scheduler_state.partition_ids != tuple(program.partition_ids):
        raise ValueError("fused Mesh scheduler partition identity is stale")
    scheduler_state.validate_commit(scheduled_frame)

    world.acquire_write(_MC2_FUSED_PRODUCT_WRITER)
    try:
        if (
            world.solver_slots.get(slot.slot_id) is not slot
            or slot.world_generation != int(world.generation)
            or slot.data.get("owner") is not owner
        ):
            raise RuntimeError("fused product slot changed while its frame was captured")
        scheduler_state.validate_commit(scheduled_frame)
        if frame_state_stage is not None:
            frame_state_stage.validate(world)
        owner.update_frame(frame_packet)
        if scheduled_frame.schedule.update_count == 0:
            owner.apply_zero_substep_frame(
                scheduled_frame.anchor_component_local_positions
            )
        scheduler_state.commit(scheduled_frame)
        if frame_state_stage is not None:
            frame_state_stage.commit(world)
        slot.data["frame_packet"] = frame_packet
        slot.data["scheduled_frame"] = scheduled_frame
        slot.data["partition_frame_snapshots"] = tuple(partition_snapshots)
        slot.data["collider_frame"] = collider_frame
        slot.data["frame_ready"] = True
        slot.data["completed_substeps"] = 0
        slot.data["frame_complete"] = scheduled_frame.schedule.update_count == 0
        slot.data.pop("last_substep", None)
        slot.data.pop("last_step_failure", None)
        slot.data.pop("output_batch", None)
        slot.data.pop("domain_output", None)
        slot.data.pop("output_results", None)
        slot.data.pop("output_writeback_plans", None)
        slot.data.pop("published_output_batch", None)
        slot.data.pop("published_output_results", None)
        slot.data.pop("published_output_writeback_plans", None)
        slot.data.pop("writeback_plan", None)
    finally:
        world.release_write(_MC2_FUSED_PRODUCT_WRITER)
    return MC2FusedProductFramePublishResultV1(
        frame=int(frame_packet.frame),
        generation=int(frame_packet.generation),
        partition_ids=tuple(program.partition_ids),
        collider_count=int(collider_frame.collider_count),
        update_count=int(scheduled_frame.schedule.update_count),
        skip_count=int(scheduled_frame.schedule.skip_count),
    )


def step_mc2_product_substep(
    world: PhysicsWorldCache,
    slot: PhysicsSolverSlot,
) -> MC2FusedProductSubstepResultV1:
    """执行并提交一个完整混合 pass 顺序的 whole-domain substep。"""

    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world must be PhysicsWorldCache")
    if not isinstance(slot, PhysicsSolverSlot) or slot.kind != MC2_FUSED_PRODUCT_SLOT_KIND:
        raise TypeError("slot must be an MC2 fused product PhysicsSolverSlot")
    owner = slot.data.get("owner")
    scheduler_state = slot.data.get("scheduler_state")
    scheduled_frame = slot.data.get("scheduled_frame")
    collider_frame = slot.data.get("collider_frame")
    if not isinstance(owner, MC2FusedCPUOwnerV1) or owner.compiled is None:
        raise RuntimeError("fused product slot has no live owner")
    if not isinstance(scheduler_state, MC2ProductSchedulerStateV1):
        raise RuntimeError("fused product slot has no product scheduler state")
    if not isinstance(scheduled_frame, MC2ProductScheduledFrameV1) or not isinstance(
        collider_frame, MC2DomainColliderFrameSpec
    ):
        raise RuntimeError("fused product slot has no published frame")
    if not bool(slot.data.get("frame_ready", False)):
        raise RuntimeError("fused Mesh frame is not ready")
    if bool(slot.data.get("frame_complete", False)):
        raise RuntimeError("fused Mesh frame has no pending substeps")

    world.acquire_write(_MC2_FUSED_PRODUCT_WRITER)
    try:
        if (
            world.solver_slots.get(slot.slot_id) is not slot
            or slot.world_generation != int(world.generation)
            or slot.data.get("owner") is not owner
            or slot.data.get("scheduler_state") is not scheduler_state
        ):
            raise RuntimeError("fused product slot changed before its substep")
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
        debug_state = slot.data.get("_debug_capture_state") or {}
        debug_filters = debug_state.get("filters") or {}
        debug_requested = bool(debug_state.get("requested"))
        is_final = bool(staged_substep.plan.is_final_substep)
        constraint_debug_mask = (
            _constraint_debug_mask(debug_filters)
            if debug_requested and is_final
            else 0
        )
        constraint_inputs_requested = debug_requested and is_final and any(
            debug_filters.get(name, False)
            for name in (
                "show_motion_base",
                "show_motion",
                "show_angle_restoration",
                "show_angle_limit",
            )
        )
        constraint_debug_started = False
        try:
            if constraint_debug_mask:
                owner.begin_constraint_debug(constraint_debug_mask)
                constraint_debug_started = True
            owner.step(settings)
            if constraint_debug_started:
                owner.end_constraint_debug()
        except Exception as exc:
            if constraint_debug_started:
                owner.clear_constraint_debug()
            slot.data.pop("_debug_product_constraint_capture", None)
            slot.data["last_step_failure"] = f"{type(exc).__name__}: {exc}"
            raise
        if constraint_debug_started:
            slot.data["_debug_product_constraint_capture"] = {
                "frame": int(scheduled_frame.frame_packet.frame),
                "generation": int(scheduled_frame.frame_packet.generation),
                "update_index": update_index,
                "mask": constraint_debug_mask,
            }
        if constraint_inputs_requested:
            slot.data["_debug_product_constraint_inputs"] = {
                "frame": int(scheduled_frame.frame_packet.frame),
                "generation": int(scheduled_frame.frame_packet.generation),
                "update_index": update_index,
                "motion_base_positions": settings["motion_base_positions"],
                "motion_base_rotations_xyzw": settings["motion_base_rotations"],
                "motion_normal_axis_values": settings["motion_normal_axis_values"],
                "motion_max_distance_enabled_values": settings["motion_max_distance_enabled_values"],
                "motion_backstop_enabled_values": settings["motion_backstop_enabled_values"],
                "angle_restoration_enabled_values": settings["angle_restoration_enabled_values"],
                "angle_limit_enabled_values": settings["angle_limit_enabled_values"],
            }
        if debug_requested and bool(
            debug_filters.get("show_step_basic", False)
        ):
            slot.data["_debug_product_step_basic"] = {
                "frame": int(scheduled_frame.frame_packet.frame),
                "generation": int(scheduled_frame.frame_packet.generation),
                "update_index": update_index,
                "positions": settings["step_basic_positions"],
                "rotations": settings["step_basic_rotations"],
            }
        scheduler_state.commit_substep(staged_substep)
        completed = update_index + 1
        result = MC2FusedProductSubstepResultV1(
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
        world.release_write(_MC2_FUSED_PRODUCT_WRITER)


def build_mc2_bone_product_output(
    world: PhysicsWorldCache,
    slot: PhysicsSolverSlot,
) -> tuple[tuple[dict, ...], dict[str, dict]]:
    """在完整帧尾从 logical output 构造 Bone 公共结果与 writeback plan。"""

    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world must be PhysicsWorldCache")
    if not isinstance(slot, PhysicsSolverSlot) or slot.kind != MC2_FUSED_PRODUCT_SLOT_KIND:
        raise TypeError("slot must be an MC2 fused product PhysicsSolverSlot")
    owner = slot.data.get("owner")
    collection = slot.data.get("collection")
    frame_packet = slot.data.get("frame_packet")
    if not isinstance(owner, MC2FusedCPUOwnerV1) or owner.compiled is None:
        raise RuntimeError("Bone product slot has no live owner")
    if not isinstance(collection, MC2BoneProductCollectionV1):
        raise RuntimeError("Bone product slot has no Bone collection")
    if not isinstance(frame_packet, MC2DomainFramePacketV1):
        raise RuntimeError("Bone product slot has no published frame")
    if not bool(slot.data.get("frame_complete", False)):
        raise RuntimeError("Bone product output is only available after the final substep")
    from .setups.bone_cloth.product import validate_mc2_bone_product_targets

    validate_mc2_bone_product_targets(collection)
    output = owner.read_output()
    results, plans = make_mc2_bone_domain_results(
        collection=collection,
        compiled=owner.compiled,
        frame_packet=frame_packet,
        output=output,
        slot_id=slot.slot_id,
        world_generation=world.generation,
        revision=owner.revision,
    )
    slot.data["domain_output"] = output
    slot.data["output_results"] = results
    slot.data["output_writeback_plans"] = plans
    return results, plans


def publish_mc2_bone_product_output_transaction(
    world: PhysicsWorldCache,
    slot: PhysicsSolverSlot,
) -> tuple[dict, ...]:
    """原子发布 Bone 公共结果，并同时提交下一帧反馈指纹。"""

    results, plans = build_mc2_bone_product_output(world, slot)
    from .setups.bone_frame_input import prepare_mc2_bone_writeback_expectations

    feedback_stage = prepare_mc2_bone_writeback_expectations(
        world,
        tuple(plans.values()),
    )
    world.acquire_write(_MC2_FUSED_PRODUCT_WRITER)
    try:
        if (
            world.solver_slots.get(slot.slot_id) is not slot
            or slot.world_generation != int(world.generation)
        ):
            raise RuntimeError("Bone product slot changed before result publication")
        feedback_stage.validate(world)
        published = publish_mc2_result_transaction(world, results)
        feedback_stage.commit(world)
        slot.data["published_output_results"] = published
        slot.data["published_output_writeback_plans"] = plans
        slot.data["writeback_plan"] = plans.get(slot.slot_id)
        return published
    finally:
        world.release_write(_MC2_FUSED_PRODUCT_WRITER)


def build_mc2_mesh_fused_output_batch(
    world: PhysicsWorldCache,
    slot: PhysicsSolverSlot | None = None,
) -> MC2MeshWritebackBatchV1:
    """只在完整帧尾读取一次 logical output 并生成多目标事务。"""

    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world must be PhysicsWorldCache")
    if slot is None:
        slot = world.solver_slots.get(MC2_FUSED_MESH_SLOT_ID)
    if not isinstance(slot, PhysicsSolverSlot) or slot.kind != MC2_FUSED_PRODUCT_SLOT_KIND:
        raise TypeError("slot must be the fused Mesh PhysicsSolverSlot")
    owner = slot.data.get("owner")
    frame_packet = slot.data.get("frame_packet")
    if not isinstance(owner, MC2FusedCPUOwnerV1) or owner.compiled is None:
        raise RuntimeError("fused Mesh slot has no live owner")
    if not isinstance(frame_packet, MC2DomainFramePacketV1):
        raise RuntimeError("fused Mesh slot has no published frame packet")
    if not bool(slot.data.get("frame_complete", False)):
        raise RuntimeError("fused Mesh output is only available after the final substep")
    output = owner.read_output()
    batch = make_mc2_mesh_writeback_batch(
        owner.compiled.program,
        frame_packet,
        output,
    )
    slot.data["domain_output"] = output
    slot.data["output_batch"] = batch
    return batch


def publish_mc2_mesh_fused_output_transaction(
    world: PhysicsWorldCache,
    slot: PhysicsSolverSlot | None = None,
) -> tuple[dict, ...]:
    """校验全部 live targets 后一次替换 MC2 公共结果流。"""

    if slot is None:
        slot = world.solver_slots.get(MC2_FUSED_MESH_SLOT_ID)
    if not isinstance(slot, PhysicsSolverSlot) or slot.kind != MC2_FUSED_PRODUCT_SLOT_KIND:
        raise TypeError("slot must be the fused Mesh PhysicsSolverSlot")
    collection = slot.data.get("collection")
    if not isinstance(collection, MC2MeshProductCollectionV1):
        raise RuntimeError("fused Mesh slot has no product collection")
    batch = build_mc2_mesh_fused_output_batch(world, slot)
    validate_mc2_mesh_product_output_batch(collection, batch)
    public_results = make_mc2_mesh_domain_results(
        batch=batch,
        slot_id=slot.slot_id,
        world_generation=world.generation,
    )
    published = publish_mc2_result_transaction(world, public_results)
    slot.data["published_output_batch"] = batch
    slot.data["published_output_results"] = published
    return published


def capture_and_publish_mc2_product_frame(
    world: PhysicsWorldCache,
    slot: PhysicsSolverSlot,
    *,
    settings=None,
    depsgraph=None,
    partition_frame_flags=None,
    velocity_weights=None,
    gravity_ratios=None,
) -> MC2FusedProductFramePublishResultV1:
    """先采集完整 partition/collider POD，再在 World 锁内发布。"""

    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world must be PhysicsWorldCache")
    if not isinstance(slot, PhysicsSolverSlot) or slot.kind != MC2_FUSED_PRODUCT_SLOT_KIND:
        raise RuntimeError("Physics World has no matching fused product slot")
    owner = slot.data.get("owner")
    collection = slot.data.get("collection")
    if not isinstance(owner, MC2FusedCPUOwnerV1) or not _is_product_collection(
        collection
    ):
        raise RuntimeError("fused product slot is incomplete")
    scheduler_state = slot.data.get("scheduler_state")
    if not isinstance(scheduler_state, MC2ProductSchedulerStateV1):
        raise RuntimeError("fused product slot has no product scheduler state")
    from .parameters import MC2SolverSettingsSpec
    from .parameters import make_mc2_solver_settings

    if settings is None:
        settings = make_mc2_solver_settings()
    if not isinstance(settings, MC2SolverSettingsSpec):
        raise TypeError("settings must be MC2SolverSettingsSpec")
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

    if isinstance(collection, MC2MeshProductCollectionV1):
        from .setups.mesh_cloth.product import capture_mc2_mesh_product_frame

        frame_packet, partition_snapshots = capture_mc2_mesh_product_frame(
            world,
            collection,
            owner,
            depsgraph=depsgraph,
            partition_frame_flags=partition_frame_flags,
            velocity_weights=velocity_weights,
            gravity_ratios=gravity_ratios,
        )
    else:
        from .setups.bone_cloth.product import compile_mc2_bone_product_frame
        from .setups.bone_frame_input import capture_mc2_bone_product_frame_inputs

        frame_inputs, frame_state_stage = capture_mc2_bone_product_frame_inputs(
            world,
            collection.static_inputs,
            frame=int(frame_context.frame),
            generation=int(world.generation),
        )
        frame_packet, partition_snapshots = compile_mc2_bone_product_frame(
            owner.compiled,
            frame_inputs,
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
    collider_frame = (
        build_mc2_mesh_domain_collider_frame(world, collection.draft)
        if isinstance(collection, MC2MeshProductCollectionV1)
        else build_mc2_domain_collider_frame_for_draft(world, collection.draft)
    )
    return publish_mc2_product_frame(
        world,
        slot,
        scheduled_frame,
        collider_frame,
        partition_snapshots=partition_snapshots,
        frame_state_stage=(
            frame_state_stage
            if isinstance(collection, MC2BoneProductCollectionV1)
            else None
        ),
    )


__all__ = [
    "MC2_FUSED_PRODUCT_SLOT_KIND",
    "MC2_FUSED_MESH_SLOT_ID",
    "MC2FusedProductFramePublishResultV1",
    "MC2FusedProductSubstepResultV1",
    "MC2FusedProductSlotSyncResultV1",
    "build_mc2_bone_product_output",
    "build_mc2_mesh_fused_output_batch",
    "capture_and_publish_mc2_product_frame",
    "discard_mc2_product_slots",
    "make_mc2_product_slot_id",
    "publish_mc2_product_frame",
    "publish_mc2_mesh_fused_output_transaction",
    "publish_mc2_bone_product_output_transaction",
    "publish_mc2_product_output_transaction",
    "step_mc2_product_substep",
    "sync_mc2_product_slot",
]
