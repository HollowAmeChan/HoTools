"""
physicsWorld.rigid.solver — 刚体 spec 收集 + Jolt 模拟步

Phase 4：spec 收集（已由 physicsWorldBegin 自动完成）。
Phase 5：step_rigid_bodies — 接入 Jolt adapter，执行模拟步。
"""

from __future__ import annotations

from ..types import PhysicsWorldCache
from .specs import (
    RigidBodySpec,
    ConstraintSpec,
    build_rigid_body_spec,
    build_constraint_spec,
)
from .results import (
    RIGID_TRANSFORM_RESULT_KEY,
    clear_rigid_transform_result,
    make_rigid_transform_result,
)


# ---------------------------------------------------------------------------
# 刚体 spec 注册
# ---------------------------------------------------------------------------

def register_rigid_bodies(
    world: PhysicsWorldCache,
    objects,
) -> tuple[int, list[str]]:
    """
    从对象列表构造 RigidBodySpec，注册到 world solver slot。

    每个对象必须有 hotools_rigid_type custom property，否则跳过（不是刚体）。
    slot_id = "rigid:{obj_ptr}:{data_ptr}"，双指针防止 Blender 指针复用。

    返回 (body_count, slot_ids)：
      body_count — 成功注册的刚体数量
      slot_ids   — 本次注册的 slot id 列表（供 debug 使用）
    """
    if world is None or not isinstance(world, PhysicsWorldCache):
        return 0, []

    solver_id = "rigid_body_solver"
    world.acquire_write(solver_id)
    try:
        registered_ids: list[str] = []

        for obj in (_flatten(objects) or []):
            spec = build_rigid_body_spec(obj)
            if spec is None:
                continue

            slot = world.ensure_solver_slot(spec.slot_id, "rigid_body")

            # world generation 变化时冷启动 slot（清掉旧 spec 和 native handle）
            if slot.world_generation != world.generation:
                slot.data.clear()
                slot.world_generation = world.generation

            slot.data["spec"] = spec
            slot.data["_debug_snapshot"] = lambda s=spec: s.debug_dict()
            registered_ids.append(spec.slot_id)

        return len(registered_ids), registered_ids
    finally:
        world.release_write(solver_id)


# ---------------------------------------------------------------------------
# 约束 spec 注册
# ---------------------------------------------------------------------------

def register_constraints(
    world: PhysicsWorldCache,
    constraint_objects,
) -> tuple[int, list[str]]:
    """
    从 Empty 对象列表构造 ConstraintSpec，注册到 world solver slot。

    每个 Empty 必须有 hotools_constraint_type custom property，否则跳过。
    slot_id = "constraint:{empty_ptr}"（约束点是 Empty，data 不唯一有意义）。

    返回 (constraint_count, slot_ids)。
    """
    if world is None or not isinstance(world, PhysicsWorldCache):
        return 0, []

    solver_id = "constraint_solver"
    world.acquire_write(solver_id)
    try:
        registered_ids: list[str] = []

        for obj in (_flatten(constraint_objects) or []):
            spec = build_constraint_spec(obj)
            if spec is None:
                continue

            slot = world.ensure_solver_slot(spec.slot_id, "rigid_constraint")

            if slot.world_generation != world.generation:
                slot.data.clear()
                slot.world_generation = world.generation

            slot.data["spec"] = spec
            slot.data["_debug_snapshot"] = lambda s=spec: s.debug_dict()
            registered_ids.append(spec.slot_id)

        return len(registered_ids), registered_ids
    finally:
        world.release_write(solver_id)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _flatten(objects) -> list:
    """递归展平嵌套 list（多重输入传来的结构）。"""
    result = []
    stack = list(objects) if isinstance(objects, (list, tuple)) else (
        [objects] if objects is not None else []
    )
    while stack:
        item = stack.pop(0)
        if isinstance(item, (list, tuple)):
            stack[0:0] = list(item)
        else:
            result.append(item)
    return result


def _has_pending_jolt_work(world: PhysicsWorldCache) -> bool:
    for slot in world.solver_slots.values():
        if slot.kind not in {"rigid_body", "rigid_constraint"}:
            continue
        if slot.data.get("spec") is None:
            continue
        if slot.data.get("_jolt_generation") != world.generation:
            return True
        if slot.kind == "rigid_body" and slot.data.get("_jolt_kinematic_pose_dirty"):
            return True
    return False


def _publish_rigid_transform_results(world: PhysicsWorldCache, adapter) -> int:
    """
    从 backend 采样本帧刚体 transform，写入 solver slot 的 result stream。

    这是 solver 和 writeback/debug/export 之间的边界：下游不应再读取
    adapter._body_handles 或 adapter._jw。
    """
    fc = world.frame_context
    frame = int(getattr(fc, "frame", 0) or 0)
    published = 0

    for slot_id, slot in list(world.solver_slots.items()):
        if slot.kind != "rigid_body":
            continue
        spec = slot.data.get("spec")
        if spec is None:
            clear_rigid_transform_result(slot)
            continue

        try:
            result = adapter.get_body_transform(slot_id)
            if result is None:
                clear_rigid_transform_result(slot)
                continue
            pos_arr, rot_arr = result
            slot.data[RIGID_TRANSFORM_RESULT_KEY] = make_rigid_transform_result(
                slot_id=slot_id,
                spec=spec,
                frame=frame,
                generation=world.generation,
                position=pos_arr,
                rotation_wxyz=rot_arr,
                backend=getattr(adapter, "BACKEND", "jolt"),
            )
            slot.data.pop("_result_error", None)
            published += 1
        except Exception as exc:
            clear_rigid_transform_result(slot)
            slot.data["_result_error"] = str(exc)

    return published


# ---------------------------------------------------------------------------
# Phase 5：Jolt 模拟步
# ---------------------------------------------------------------------------

def step_rigid_bodies(
    world: PhysicsWorldCache,
    enabled: bool = True,
) -> tuple[int, float]:
    """
    Phase 5 核心：驱动 Jolt 模拟一帧。

    流程：
    1. 获取或创建 JoltAdapter（挂在 world.backend_resources["rigid_solver"]）。
    2. 对每个 rigid_body slot：
       - 若 slot 在本 generation 内首次遇到，sync_body 注册到 Jolt。
       - KINEMATIC body 每帧调用 update_kinematic 跟随动画。
    3. 对每个 rigid_constraint slot：
       - 若 slot 在本 generation 内首次遇到，sync_constraint 注册到 Jolt。
    4. 执行 Jolt step（使用 world.frame_context.dt 和 substeps）。
    5. 发布 rigid transform result；写回由下游 Physics Writeback 节点统一处理。

    返回 (body_count, step_ms)。
    """
    if not enabled or world is None or not isinstance(world, PhysicsWorldCache):
        return 0, 0.0

    fc = world.frame_context
    same_frame = bool(getattr(fc, "same_frame", False)) if fc is not None else False
    if same_frame and not _has_pending_jolt_work(world):
        adapter = world.backend_resources.get("rigid_solver")
        body_count = int(getattr(adapter, "body_count", 0) or 0)
        return body_count, 0.0

    from .backends.jolt import ensure_jolt_adapter

    adapter = ensure_jolt_adapter(world)
    if adapter is None:
        # hotools_jolt 未编译，静默降级
        return 0, 0.0

    solver_id = "jolt_step"
    world.acquire_write(solver_id)
    try:
        dt = float(fc.dt) if fc is not None and fc.dt > 0.0 else 1.0 / 60.0
        substeps = max(1, int(fc.substeps)) if fc is not None else 1
        restart = bool(fc.restart_required) if fc is not None else True

        # --- sync rigid bodies ---
        for slot_id, slot in list(world.solver_slots.items()):
            if slot.kind != "rigid_body":
                continue
            spec = slot.data.get("spec")
            if spec is None:
                continue

            needs_sync = (
                restart
                or slot.data.get("_jolt_generation") != world.generation
            )
            if needs_sync:
                try:
                    adapter.sync_body(slot_id, spec)
                    slot.data["_jolt_generation"] = world.generation
                    slot.data.pop("_jolt_kinematic_pose_dirty", None)
                except Exception as e:
                    slot.data["_jolt_error"] = str(e)
            elif spec.body_type == "KINEMATIC":
                adapter.update_kinematic(slot_id, spec, dt)
                slot.data.pop("_jolt_kinematic_pose_dirty", None)

        # --- sync constraints ---
        for slot_id, slot in list(world.solver_slots.items()):
            if slot.kind != "rigid_constraint":
                continue
            spec = slot.data.get("spec")
            if spec is None:
                continue

            needs_sync = (
                restart
                or slot.data.get("_jolt_generation") != world.generation
            )
            if needs_sync:
                try:
                    adapter.sync_constraint(slot_id, spec)
                    slot.data["_jolt_generation"] = world.generation
                except Exception as e:
                    slot.data["_jolt_error"] = str(e)

        if same_frame:
            _publish_rigid_transform_results(world, adapter)
            return adapter.body_count, 0.0

        # --- step ---
        step_ms = adapter.step(dt, substeps)
        _publish_rigid_transform_results(world, adapter)

        # 注意：写回由下游 Physics Writeback 节点统一处理。
        # adapter.writeback_transforms 不在此处调用，以便写回节点能先捕获 frame=0 初始位置。
        return adapter.body_count, step_ms

    finally:
        world.release_write(solver_id)
