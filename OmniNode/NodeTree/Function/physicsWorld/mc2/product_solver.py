"""MC2 setup 中立产品请求的统一域执行编排。"""

from __future__ import annotations

from .names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from .names import MC2_SETUP_MESH_CLOTH
from .parameters import MC2SolverSettingsSpec, make_mc2_solver_settings
from .product_request import MC2ProductRequestV1
from .product_collect import (
    collect_mc2_mesh_product_plan,
    validate_mc2_mesh_product_targets,
)
from .product_bone_collect import (
    collect_mc2_bone_product_plan,
    validate_mc2_bone_product_targets,
)
from .product_slot import (
    MC2_FUSED_MESH_SLOT_ID,
    capture_and_publish_mc2_mesh_fused_frame,
    publish_mc2_mesh_fused_output_transaction,
    step_mc2_mesh_fused_substep,
    sync_mc2_mesh_fused_slot,
    capture_and_publish_mc2_product_frame,
    make_mc2_product_slot_id,
    publish_mc2_bone_product_output_transaction,
    step_mc2_product_substep,
    sync_mc2_product_slot,
)
from ..types import PhysicsWorldCache


def _initialize_product_base_poses(request: MC2ProductRequestV1) -> int:
    from .setups.mesh_cloth.base_pose import initialize_base_pose_proxy_if_missing

    created_count = 0
    for partition in request.plan.active_partitions:
        _base_pose, created = initialize_base_pose_proxy_if_missing(partition.source)
        created_count += int(created)
    return created_count


def _step_mc2_mesh_product(
    world,
    request: MC2ProductRequestV1,
    *,
    settings: MC2SolverSettingsSpec | None = None,
    enabled: bool = True,
    timing=None,
) -> tuple[object, bool, str]:
    """执行一个明确 fused Mesh domain；不接受 task fallback。"""

    if timing is not None:
        timing.restart()
    if not isinstance(world, PhysicsWorldCache):
        return world, False, "MC2 Mesh统一域需要PhysicsWorldCache"
    if request.setup_type != MC2_SETUP_MESH_CLOTH:
        raise ValueError("Mesh 产品执行器收到不匹配的 setup")
    if settings is None:
        settings = make_mc2_solver_settings()
    if not isinstance(settings, MC2SolverSettingsSpec):
        raise TypeError("settings 必须是 MC2SolverSettingsSpec")
    if not enabled:
        return world, False, "MC2 Mesh统一域已禁用"
    if int(world.generation) <= 0:
        return world, False, "MC2 Mesh统一域等待Physics World Begin"

    created_base_poses = _initialize_product_base_poses(request)
    if timing is not None:
        timing.checkpoint("统一域输入")
    collection = collect_mc2_mesh_product_plan(world, request.plan)
    validate_mc2_mesh_product_targets(collection)
    if timing is not None:
        timing.checkpoint("统一域采集")
    sync = sync_mc2_mesh_fused_slot(world, collection)
    slot = world.solver_slots[MC2_FUSED_MESH_SLOT_ID]
    if timing is not None:
        timing.checkpoint("统一域同步")
    frame = capture_and_publish_mc2_mesh_fused_frame(
        world,
        settings=settings,
    )
    if timing is not None:
        timing.checkpoint("统一域Frame")
    for _index in range(frame.update_count):
        step_mc2_mesh_fused_substep(world, slot)
    if timing is not None:
        timing.checkpoint("统一域求解")
    public_results = publish_mc2_mesh_fused_output_transaction(world, slot)
    slot.data["product_enabled"] = True
    slot.data["collector_request"] = request
    slot.data["collector_report"] = request.report_text
    if timing is not None:
        timing.checkpoint("统一域结果")
        action_counts = {
            "created": int(sync.action == "created"),
            "rebuilt": int(sync.action == "replaced"),
            "updated": int(sync.action == "updated"),
        }
        timing.finish({
            "frame": int(world.frame_context.frame),
            "generation": int(world.generation),
            "tasks": 1,
            "particles": slot.data["owner"].compiled.program.particle_count,
            "substeps": frame.update_count,
            "max_substeps": settings.max_simulation_count_per_frame,
            "batches": 1,
            "colliders": frame.collider_count,
            "setup_counts": {"mesh_cloth": len(collection.draft.partitions)},
            "scheduled_tasks": int(frame.update_count > 0),
            "ready_frames": 1,
            "writeback_results": len(public_results),
            **action_counts,
        })
    status = (
        f"MC2 Mesh统一域就绪：分区 {len(collection.draft.partitions)}，"
        f"粒子 {slot.data['owner'].compiled.program.particle_count}，"
        f"子步 {frame.update_count}，目标 {len(public_results)}，"
        f"BasePose新建 {created_base_poses}，owner {sync.action}"
    )
    return world, True, status


def _step_mc2_bone_product(
    world,
    request: MC2ProductRequestV1,
    *,
    settings: MC2SolverSettingsSpec | None = None,
    enabled: bool = True,
    timing=None,
) -> tuple[object, bool, str]:
    """执行一个显式 Bone whole-domain 产品请求，不创建旧 task/context。"""

    if timing is not None:
        timing.restart()
    if not isinstance(world, PhysicsWorldCache):
        return world, False, "MC2 Bone 统一域需要 PhysicsWorldCache"
    if request.setup_type not in (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING):
        raise ValueError("Bone 产品执行器收到不匹配的 setup")
    if settings is None:
        settings = make_mc2_solver_settings()
    if not isinstance(settings, MC2SolverSettingsSpec):
        raise TypeError("settings 必须是 MC2SolverSettingsSpec")
    if not enabled:
        return world, False, "MC2 Bone 统一域已禁用"
    if int(world.generation) <= 0:
        return world, False, "MC2 Bone 统一域等待 Physics World Begin"

    collection = collect_mc2_bone_product_plan(world, request.plan)
    validate_mc2_bone_product_targets(collection)
    if timing is not None:
        timing.checkpoint("统一域采集")
    slot_id = make_mc2_product_slot_id(
        request.setup_type,
        request.domain_signature,
    )
    sync = sync_mc2_product_slot(
        world,
        collection,
        slot_id=slot_id,
    )
    slot = world.solver_slots[slot_id]
    if timing is not None:
        timing.checkpoint("统一域同步")
    frame = capture_and_publish_mc2_product_frame(
        world,
        slot,
        settings=settings,
    )
    if timing is not None:
        timing.checkpoint("统一域Frame")
    for _index in range(frame.update_count):
        step_mc2_product_substep(world, slot)
    if timing is not None:
        timing.checkpoint("统一域求解")
    public_results = publish_mc2_bone_product_output_transaction(world, slot)
    slot.data["product_enabled"] = True
    slot.data["collector_request"] = request
    slot.data["collector_report"] = request.report_text
    if timing is not None:
        timing.checkpoint("统一域结果")
        action_counts = {
            "created": int(sync.action == "created"),
            "rebuilt": int(sync.action == "replaced"),
            "updated": int(sync.action == "updated"),
        }
        timing.finish({
            "frame": int(world.frame_context.frame),
            "generation": int(world.generation),
            "tasks": 1,
            "particles": slot.data["owner"].compiled.program.particle_count,
            "substeps": frame.update_count,
            "max_substeps": settings.max_simulation_count_per_frame,
            "batches": 1,
            "colliders": frame.collider_count,
            "setup_counts": {
                request.setup_type: len(collection.draft.partitions),
            },
            "scheduled_tasks": int(frame.update_count > 0),
            "ready_frames": 1,
            "writeback_results": len(public_results),
            **action_counts,
        })
    status = (
        f"MC2 {request.setup_type} 统一域就绪："
        f"分区 {len(collection.draft.partitions)}，"
        f"粒子 {slot.data['owner'].compiled.program.particle_count}，"
        f"子步 {frame.update_count}，目标 {len(public_results)}，"
        f"owner {sync.action}"
    )
    return world, True, status


def step_mc2_product(
    world,
    request: MC2ProductRequestV1,
    *,
    settings: MC2SolverSettingsSpec | None = None,
    enabled: bool = True,
    timing=None,
) -> tuple[object, bool, str]:
    """按 setup 执行一个显式统一域请求；绝不回落到旧 task owner。"""

    if not isinstance(request, MC2ProductRequestV1):
        raise TypeError("request 必须是 MC2ProductRequestV1")
    if request.setup_type == MC2_SETUP_MESH_CLOTH:
        return _step_mc2_mesh_product(
            world,
            request,
            settings=settings,
            enabled=enabled,
            timing=timing,
        )
    if request.setup_type in (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING):
        return _step_mc2_bone_product(
            world,
            request,
            settings=settings,
            enabled=enabled,
            timing=timing,
        )
    raise NotImplementedError(
        f"MC2 {request.setup_type} 产品统一域尚未完成 E5-B 接线"
    )


__all__ = ["step_mc2_product"]
