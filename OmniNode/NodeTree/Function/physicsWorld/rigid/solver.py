"""
physicsWorld.rigid.solver — 刚体 spec 收集并注册到 PhysicsWorldCache solver slot

Phase 4 只做 spec 收集和 slot 注册，不做 Jolt step 和写回。
通过 PhysicsWorldCache.omni_cache_debug_snapshot() 可观察 body / constraint 数量。
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
