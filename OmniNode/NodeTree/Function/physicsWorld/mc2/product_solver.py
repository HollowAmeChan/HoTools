"""MC2 setup 中立产品请求的统一域执行编排。"""

from __future__ import annotations

from .names import (
    MC2_SETUP_BONE_CLOTH,
    MC2_SETUP_BONE_SPRING,
    MC2_SETUP_MESH_CLOTH,
    MC2_SOLVER_ID,
)
from .parameters import MC2SolverSettingsSpec, make_mc2_solver_settings
from .product_request import MC2ProductRequestV1
from .product_collect import (
    collect_mc2_mesh_product_plan,
    validate_mc2_mesh_product_output_batch,
    validate_mc2_mesh_product_targets,
)
from .product_bone_collect import (
    collect_mc2_bone_product_plan,
    validate_mc2_bone_product_targets,
)
from .product_slot import (
    MC2_FUSED_PRODUCT_SLOT_KIND,
    build_mc2_bone_product_output,
    build_mc2_mesh_fused_output_batch,
    capture_and_publish_mc2_product_frame,
    discard_mc2_product_slots,
    make_mc2_product_slot_id,
    publish_mc2_bone_product_output_transaction,
    publish_mc2_mesh_fused_output_transaction,
    publish_mc2_product_output_transaction,
    step_mc2_product_substep,
    sync_mc2_product_slot,
)
from .results import make_mc2_mesh_domain_results, merge_mc2_bone_results
from ..types import PhysicsWorldCache


_BONE_SETUP_TYPES = (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING)
_PRODUCT_SETUP_TYPES = (MC2_SETUP_MESH_CLOTH, *_BONE_SETUP_TYPES)


def _product_slot_id(request: MC2ProductRequestV1) -> str:
    return make_mc2_product_slot_id(
        request.setup_type,
        request.domain_signature,
    )


def _initialize_product_base_poses(request: MC2ProductRequestV1) -> int:
    from .setups.mesh_cloth.base_pose import initialize_base_pose_proxy_if_missing

    created_count = 0
    for partition in request.plan.active_partitions:
        _base_pose, created = initialize_base_pose_proxy_if_missing(partition.source)
        created_count += int(created)
    return created_count


def _finish_single_timing(
    timing,
    *,
    world,
    request,
    collection,
    slot,
    sync,
    frame,
    public_results,
    settings,
) -> None:
    if timing is None:
        return
    timing.checkpoint("统一域结果")
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
        "created": int(sync.action == "created"),
        "rebuilt": int(sync.action == "replaced"),
        "updated": int(sync.action == "updated"),
    })


def _step_mc2_mesh_product(
    world,
    request: MC2ProductRequestV1,
    *,
    settings: MC2SolverSettingsSpec | None = None,
    enabled: bool = True,
    timing=None,
    publish_results: bool = True,
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
    slot_id = _product_slot_id(request)
    collection = collect_mc2_mesh_product_plan(
        world,
        request.plan,
        receipt_slot_id=slot_id,
    )
    validate_mc2_mesh_product_targets(collection)
    if timing is not None:
        timing.checkpoint("统一域采集")
    sync = sync_mc2_product_slot(world, collection, slot_id=slot_id)
    slot = world.solver_slots[slot_id]
    slot.data["product_sync_action"] = sync.action
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
    if publish_results:
        public_results = publish_mc2_mesh_fused_output_transaction(world, slot)
    else:
        batch = build_mc2_mesh_fused_output_batch(world, slot)
        validate_mc2_mesh_product_output_batch(collection, batch)
        public_results = make_mc2_mesh_domain_results(
            batch=batch,
            slot_id=slot.slot_id,
            world_generation=world.generation,
        )
        slot.data["output_results"] = public_results
    slot.data["product_enabled"] = True
    slot.data["collector_request"] = request
    slot.data["collector_report"] = request.report_text
    slot.data["created_base_poses"] = created_base_poses
    _finish_single_timing(
        timing,
        world=world,
        request=request,
        collection=collection,
        slot=slot,
        sync=sync,
        frame=frame,
        public_results=public_results,
        settings=settings,
    )
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
    publish_results: bool = True,
) -> tuple[object, bool, str]:
    """执行一个显式 Bone whole-domain 产品请求，不创建旧 task/context。"""

    if timing is not None:
        timing.restart()
    if not isinstance(world, PhysicsWorldCache):
        return world, False, "MC2 Bone 统一域需要 PhysicsWorldCache"
    if request.setup_type not in _BONE_SETUP_TYPES:
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
    slot_id = _product_slot_id(request)
    sync = sync_mc2_product_slot(world, collection, slot_id=slot_id)
    slot = world.solver_slots[slot_id]
    slot.data["product_sync_action"] = sync.action
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
    if publish_results:
        public_results = publish_mc2_bone_product_output_transaction(world, slot)
    else:
        public_results, _plans = build_mc2_bone_product_output(world, slot)
    slot.data["product_enabled"] = True
    slot.data["collector_request"] = request
    slot.data["collector_report"] = request.report_text
    _finish_single_timing(
        timing,
        world=world,
        request=request,
        collection=collection,
        slot=slot,
        sync=sync,
        frame=frame,
        public_results=public_results,
        settings=settings,
    )
    status = (
        f"MC2 {request.setup_type} 统一域就绪："
        f"分区 {len(collection.draft.partitions)}，"
        f"粒子 {slot.data['owner'].compiled.program.particle_count}，"
        f"子步 {frame.update_count}，目标 {len(public_results)}，"
        f"owner {sync.action}"
    )
    return world, True, status


def _dispatch_product(
    world,
    request: MC2ProductRequestV1,
    *,
    settings,
    enabled,
    timing,
    publish_results,
):
    if request.setup_type == MC2_SETUP_MESH_CLOTH:
        return _step_mc2_mesh_product(
            world,
            request,
            settings=settings,
            enabled=enabled,
            timing=timing,
            publish_results=publish_results,
        )
    if request.setup_type in _BONE_SETUP_TYPES:
        return _step_mc2_bone_product(
            world,
            request,
            settings=settings,
            enabled=enabled,
            timing=timing,
            publish_results=publish_results,
        )
    raise NotImplementedError(
        f"MC2 {request.setup_type} 产品统一域尚未完成 E5-B 接线"
    )


def step_mc2_product(
    world,
    request: MC2ProductRequestV1,
    *,
    settings: MC2SolverSettingsSpec | None = None,
    enabled: bool = True,
    timing=None,
) -> tuple[object, bool, str]:
    """单 request 兼容入口；复用同一批量事务，不保留发布旁路。"""

    if not isinstance(request, MC2ProductRequestV1):
        raise TypeError("request 必须是 MC2ProductRequestV1")
    return step_mc2_products(
        world,
        (request,),
        settings=settings,
        enabled=enabled,
        timing=timing,
    )


def step_mc2_products(
    world,
    requests,
    *,
    settings: MC2SolverSettingsSpec | None = None,
    enabled: bool = True,
    timing=None,
) -> tuple[object, bool, str]:
    """执行多个显式 domain，并在全部成功后一次发布公共结果。"""

    frozen_requests = tuple(requests)
    if any(not isinstance(request, MC2ProductRequestV1) for request in frozen_requests):
        raise TypeError("requests 必须是 MC2ProductRequestV1 序列")
    if any(request.setup_type not in _PRODUCT_SETUP_TYPES for request in frozen_requests):
        raise NotImplementedError("产品批次包含尚未实现的 setup")
    slot_ids = tuple(_product_slot_id(request) for request in frozen_requests)
    if len(set(slot_ids)) != len(slot_ids):
        raise ValueError("MC2模拟步不能重复执行同一个显式 domain request")
    if timing is not None:
        timing.restart()
    if not isinstance(world, PhysicsWorldCache):
        return world, False, "MC2 显式统一域需要 PhysicsWorldCache"
    if settings is None:
        settings = make_mc2_solver_settings()
    if not isinstance(settings, MC2SolverSettingsSpec):
        raise TypeError("settings 必须是 MC2SolverSettingsSpec")
    if not enabled:
        return world, False, "MC2 显式统一域已禁用"
    if int(world.generation) <= 0:
        return world, False, "MC2 显式统一域等待 Physics World Begin"

    existing_product_slot_ids = tuple(
        slot_id
        for slot_id, slot in world.solver_slots.items()
        if getattr(slot, "kind", None) == MC2_FUSED_PRODUCT_SLOT_KIND
    )
    stale_slot_ids = tuple(
        slot_id for slot_id in existing_product_slot_ids if slot_id not in slot_ids
    )
    if not frozen_requests:
        removed = discard_mc2_product_slots(
            world,
            stale_slot_ids,
            reason="mc2_product_request_removed",
        )
        world.clear_results(solver=MC2_SOLVER_ID)
        world.replace_required = bool(removed)
        return world, False, f"MC2 显式统一域无活动request；清理 {len(removed)}"

    has_bone = any(request.setup_type in _BONE_SETUP_TYPES for request in frozen_requests)
    bone_state_key = None
    bone_state_present = False
    bone_state_base = None
    if has_bone:
        from .setups.bone_frame_input import MC2_BONE_FRAME_STATE_KEY

        bone_state_key = MC2_BONE_FRAME_STATE_KEY
        bone_state_present = bone_state_key in world.backend_resources
        bone_state_base = world.backend_resources.get(bone_state_key)

    attempted_slot_ids = []
    slots = []
    statuses = []
    try:
        for request, slot_id in zip(frozen_requests, slot_ids):
            attempted_slot_ids.append(slot_id)
            _returned, ready, status = _dispatch_product(
                world,
                request,
                settings=settings,
                enabled=True,
                timing=None,
                publish_results=False,
            )
            if not ready:
                raise RuntimeError(status)
            slot = world.solver_slots.get(slot_id)
            if slot is None:
                raise RuntimeError("产品执行完成但对应 domain slot 不存在")
            slots.append(slot)
            statuses.append(status)
        if timing is not None:
            timing.checkpoint("统一域求解")

        mesh_results = []
        bone_entries = []
        for request, slot in zip(frozen_requests, slots):
            output_results = tuple(slot.data.get("output_results") or ())
            if request.setup_type == MC2_SETUP_MESH_CLOTH:
                mesh_results.extend(output_results)
                continue
            plans = dict(slot.data.get("output_writeback_plans") or {})
            for result in output_results:
                result_slot_id = str(result.get("slot_id") or "")
                plan = plans.get(result_slot_id)
                if plan is None:
                    raise RuntimeError("Bone 产品结果缺少对应 writeback plan")
                bone_entries.append((result, plan))

        if any(
            bool((slot.data.get("_debug_capture_state") or {}).get("requested"))
            for slot in slots
        ):
            from .debug import capture_requested_mc2_product_debug

            capture_requested_mc2_product_debug(world, slots)

        bone_results, bone_plans = merge_mc2_bone_results(bone_entries)
        public_results = (*mesh_results, *bone_results)
        published = publish_mc2_product_output_transaction(
            world,
            slots,
            public_results,
            bone_writeback_plans=bone_plans,
        )
        removed = discard_mc2_product_slots(
            world,
            stale_slot_ids,
            reason="mc2_product_request_removed",
        )
    except Exception:
        discard_mc2_product_slots(
            world,
            attempted_slot_ids,
            reason="mc2_product_batch_failure",
        )
        world.clear_results(solver=MC2_SOLVER_ID)
        world.replace_required = True
        if bone_state_key is not None:
            if bone_state_present:
                world.backend_resources[bone_state_key] = bone_state_base
            else:
                world.backend_resources.pop(bone_state_key, None)
        raise

    if timing is not None:
        timing.checkpoint("统一域结果")
        setup_counts = {}
        for request, slot in zip(frozen_requests, slots):
            collection = slot.data["collection"]
            setup_counts[request.setup_type] = (
                setup_counts.get(request.setup_type, 0)
                + len(collection.draft.partitions)
            )
        timing.finish({
            "frame": int(world.frame_context.frame),
            "generation": int(world.generation),
            "tasks": len(slots),
            "particles": sum(
                slot.data["owner"].compiled.program.particle_count for slot in slots
            ),
            "substeps": sum(
                slot.data["scheduled_frame"].schedule.update_count for slot in slots
            ),
            "max_substeps": settings.max_simulation_count_per_frame,
            "batches": len(slots),
            "colliders": sum(
                slot.data["collider_frame"].collider_count for slot in slots
            ),
            "setup_counts": setup_counts,
            "scheduled_tasks": sum(
                slot.data["scheduled_frame"].schedule.update_count > 0
                for slot in slots
            ),
            "ready_frames": len(slots),
            "writeback_results": len(published),
            "created": sum(
                slot.data.get("product_sync_action") == "created" for slot in slots
            ),
            "rebuilt": sum(
                slot.data.get("product_sync_action") == "replaced" for slot in slots
            ),
            "updated": sum(
                slot.data.get("product_sync_action") == "updated" for slot in slots
            ),
        })
    status = (
        f"MC2 显式统一域批次就绪：域 {len(slots)}，"
        f"目标 {len(published)}，清理 {len(removed)}；" + " | ".join(statuses)
    )
    return world, True, status


__all__ = ["step_mc2_product", "step_mc2_products"]
