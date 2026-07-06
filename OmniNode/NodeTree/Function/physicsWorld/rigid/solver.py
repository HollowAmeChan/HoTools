"""
physicsWorld.rigid.solver — 刚体 spec 收集 + Jolt 模拟步

Phase 4：spec 收集（已由 physicsWorldBegin 自动完成）。
Phase 5：step_rigid_bodies — 接入 Jolt adapter，执行模拟步，写回变换。
"""

from __future__ import annotations

from ..types import PhysicsWorldCache
from .specs import (
    RigidBodySpec,
    ConstraintSpec,
    build_rigid_body_spec,
    build_constraint_spec,
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


# ---------------------------------------------------------------------------
# Phase 5：Jolt 模拟步 + 写回
# ---------------------------------------------------------------------------

def step_rigid_bodies(
    world: PhysicsWorldCache,
    enabled: bool = True,
) -> tuple[int, float]:
    """
    Phase 5 核心：驱动 Jolt 模拟一帧并把结果写回 Blender 对象变换。

    流程：
    1. 获取或创建 JoltAdapter（挂在 world.backend_resources["rigid_solver"]）。
    2. 对每个 rigid_body slot：
       - 若 slot 在本 generation 内首次遇到，sync_body 注册到 Jolt。
       - KINEMATIC body 每帧调用 update_kinematic 跟随动画。
    3. 对每个 rigid_constraint slot：
       - 若 slot 在本 generation 内首次遇到，sync_constraint 注册到 Jolt。
    4. 执行 Jolt step（使用 world.frame_context.dt 和 substeps）。
    5. DYNAMIC body 写回 Blender 对象位置/旋转。

    返回 (body_count, step_ms)。
    """
    if not enabled or world is None or not isinstance(world, PhysicsWorldCache):
        return 0, 0.0

    from .backends.jolt import ensure_jolt_adapter

    adapter = ensure_jolt_adapter(world)
    if adapter is None:
        # hotools_jolt 未编译，静默降级
        return 0, 0.0

    solver_id = "jolt_step"
    world.acquire_write(solver_id)
    try:
        fc = world.frame_context
        dt = float(fc.dt) if fc.dt > 0.0 else 1.0 / 60.0
        substeps = max(1, int(fc.substeps))
        restart = bool(fc.restart_required)

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
                except Exception as e:
                    slot.data["_jolt_error"] = str(e)
            elif spec.body_type == "KINEMATIC":
                adapter.update_kinematic(slot_id, spec, dt)

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

        # --- step ---
        step_ms = adapter.step(dt, substeps)

        # 注意：写回由下游 Physics Writeback 节点统一处理。
        # adapter.writeback_transforms 不在此处调用，以便写回节点能先捕获 frame=0 初始位置。
        return adapter._jw.body_count, step_ms

    finally:
        world.release_write(solver_id)
