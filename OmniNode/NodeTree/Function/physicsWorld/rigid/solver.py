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
    clear_rigid_transform_results,
    publish_rigid_transform_result,
    publish_rigid_solver_stats_result,
)


RIGID_BODY_COMMANDS_CHANNEL = "rigid_body_commands"
_RIGID_COMMAND_CONSUMER_KEY = "_consumed_by_rigid_solver"


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
    if _has_pending_rigid_body_commands(world):
        return True
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


def _consume_exchange(world: PhysicsWorldCache, channel: str) -> list[dict]:
    return [item for item in world.consume_exchange(channel) if isinstance(item, dict)]


def _rigid_command_token(world: PhysicsWorldCache) -> tuple[int, int]:
    fc = getattr(world, "frame_context", None)
    frame = int(getattr(fc, "frame", 0) or 0)
    return (int(getattr(world, "generation", 0) or 0), frame)


def _has_pending_rigid_body_commands(world: PhysicsWorldCache) -> bool:
    token = _rigid_command_token(world)
    for item in _consume_exchange(world, RIGID_BODY_COMMANDS_CHANNEL):
        if item.get(_RIGID_COMMAND_CONSUMER_KEY) != token:
            return True
    return False


def _vec3(value, fallback=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except Exception:
        return (float(fallback[0]), float(fallback[1]), float(fallback[2]))


def _bool_value(value, fallback: bool = False) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    try:
        return bool(value)
    except Exception:
        return bool(fallback)


def _apply_rigid_body_commands(world: PhysicsWorldCache, adapter) -> tuple[int, int]:
    """
    消费 frame exchange 中的 rigid_body_commands。

    item 会被打上本 generation/frame 的 consumer 标记，避免同一图执行里
    多次调用 rigid solver 时重复应用 impulse / force。
    """
    token = _rigid_command_token(world)
    applied = 0
    failed = 0
    errors: list[str] = []

    for item in _consume_exchange(world, RIGID_BODY_COMMANDS_CHANNEL):
        if item.get(_RIGID_COMMAND_CONSUMER_KEY) == token:
            continue
        item[_RIGID_COMMAND_CONSUMER_KEY] = token

        slot_id = str(item.get("target_slot_id") or item.get("slot_id") or "")
        command = str(item.get("command") or "").strip().lower()
        ok = False
        error_recorded = False
        try:
            if not slot_id or not command:
                raise ValueError("missing target_slot_id or command")
            if command in {"set_velocity", "set_body_velocity"}:
                ok = adapter.set_body_velocity(
                    slot_id,
                    _vec3(item.get("linear_velocity")),
                    _vec3(item.get("angular_velocity")),
                )
            elif command in {"add_force", "add_body_force"}:
                ok = adapter.add_body_force(
                    slot_id,
                    _vec3(item.get("force")),
                    _vec3(item.get("torque")),
                )
            elif command in {"add_impulse", "add_body_impulse"}:
                ok = adapter.add_body_impulse(
                    slot_id,
                    _vec3(item.get("impulse")),
                    _vec3(item.get("angular_impulse")),
                )
            elif command in {"set_gravity_factor", "set_body_gravity_factor"}:
                ok = adapter.set_body_gravity_factor(
                    slot_id,
                    float(item.get("gravity_factor", 1.0)),
                )
            elif command in {"set_material_response", "set_body_material_response"}:
                ok = adapter.set_body_material_response(
                    slot_id,
                    float(item.get("friction", 0.5)),
                    float(item.get("restitution", 0.0)),
                )
            elif command in {"set_motion_quality", "set_body_motion_quality"}:
                ok = adapter.set_body_motion_quality(
                    slot_id,
                    str(item.get("motion_quality", "DISCRETE")),
                )
            elif command in {"set_active", "activate_body"}:
                ok = adapter.set_body_active(
                    slot_id,
                    _bool_value(item.get("active", True), True),
                )
            else:
                raise ValueError(f"unknown command {command!r}")
        except Exception as exc:
            errors.append(f"{slot_id or '<missing>'}:{command or '<missing>'}:{exc}")
            error_recorded = True
            ok = False

        if ok:
            applied += 1
        else:
            failed += 1
            if not error_recorded:
                errors.append(f"{slot_id or '<missing>'}:{command or '<missing>'}:adapter returned False")

    try:
        adapter.last_command_count = applied
        adapter.last_command_failed = failed
        adapter.last_command_errors = errors[-5:]
    except Exception:
        pass

    return applied, failed


def _publish_rigid_transform_results(world: PhysicsWorldCache, adapter) -> int:
    """
    从 backend 采样本帧刚体 transform，写入 world result stream。

    这是 solver 和 writeback/debug/export 之间的边界：下游不应再读取
    solver slot、adapter._body_handles 或 adapter._jw 来拿本帧 transform。
    """
    fc = world.frame_context
    frame = int(getattr(fc, "frame", 0) or 0)
    published = 0
    clear_rigid_transform_results(world)

    for slot_id, slot in list(world.solver_slots.items()):
        if slot.kind != "rigid_body":
            continue
        spec = slot.data.get("spec")
        if spec is None:
            continue

        try:
            state = None
            if hasattr(adapter, "get_body_state"):
                state = adapter.get_body_state(slot_id)

            if state is not None:
                pos_arr = state.get("position")
                rot_arr = state.get("rotation_wxyz")
            else:
                result = adapter.get_body_transform(slot_id)
                if result is None:
                    continue
                pos_arr, rot_arr = result

            published_result = publish_rigid_transform_result(
                world,
                slot_id=slot_id,
                spec=spec,
                frame=frame,
                generation=world.generation,
                position=pos_arr,
                rotation_wxyz=rot_arr,
                linear_velocity=state.get("linear_velocity") if state else None,
                angular_velocity=state.get("angular_velocity") if state else None,
                active=state.get("active") if state else None,
                sleeping=state.get("sleeping") if state else None,
                backend=getattr(adapter, "BACKEND", "jolt"),
            )
            if published_result is None:
                continue
            slot.data.pop("_result_error", None)
            published += 1
        except Exception as exc:
            slot.data["_result_error"] = str(exc)

    return published


def _rigid_slot_error_counts(world: PhysicsWorldCache) -> tuple[int, int]:
    sync_error_count = 0
    result_error_count = 0
    for slot in world.solver_slots.values():
        if slot.kind not in {"rigid_body", "rigid_constraint"}:
            continue
        if slot.data.get("_jolt_error"):
            sync_error_count += 1
        if slot.data.get("_result_error"):
            result_error_count += 1
    return sync_error_count, result_error_count


def _publish_rigid_solver_stats(
    world: PhysicsWorldCache,
    adapter,
    step_ms: float,
    transform_count: int,
) -> dict | None:
    fc = world.frame_context
    sync_error_count, result_error_count = _rigid_slot_error_counts(world)
    return publish_rigid_solver_stats_result(
        world,
        frame=int(getattr(fc, "frame", 0) or 0),
        generation=int(world.generation),
        body_count=int(getattr(adapter, "body_count", 0) or 0),
        constraint_count=int(getattr(adapter, "constraint_count", 0) or 0),
        step_ms=float(step_ms),
        dt=float(getattr(fc, "dt", 0.0) or 0.0),
        substeps=int(getattr(fc, "substeps", 1) or 1),
        same_frame=bool(getattr(fc, "same_frame", False)),
        restart_required=bool(getattr(fc, "restart_required", False)),
        transform_count=int(transform_count),
        command_count=int(getattr(adapter, "last_command_count", 0) or 0),
        command_failed=int(getattr(adapter, "last_command_failed", 0) or 0),
        command_errors=list(getattr(adapter, "last_command_errors", []) or []),
        sync_error_count=sync_error_count,
        result_error_count=result_error_count,
        backend=getattr(adapter, "BACKEND", "jolt"),
    )


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
        if adapter is not None:
            adapter.last_command_count = 0
            adapter.last_command_failed = 0
            adapter.last_command_errors = []
            transform_count = _publish_rigid_transform_results(world, adapter)
            _publish_rigid_solver_stats(world, adapter, 0.0, transform_count)
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
                    slot.data.pop("_jolt_error", None)
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
                    slot.data.pop("_jolt_error", None)
                except Exception as e:
                    slot.data["_jolt_error"] = str(e)

        _apply_rigid_body_commands(world, adapter)

        if same_frame:
            transform_count = _publish_rigid_transform_results(world, adapter)
            _publish_rigid_solver_stats(world, adapter, 0.0, transform_count)
            return adapter.body_count, 0.0

        # --- step ---
        step_ms = adapter.step(dt, substeps)
        transform_count = _publish_rigid_transform_results(world, adapter)
        _publish_rigid_solver_stats(world, adapter, step_ms, transform_count)

        # 注意：写回由下游 Physics Writeback 节点统一处理。
        # adapter.writeback_transforms 不在此处调用，以便写回节点能先捕获 frame=0 初始位置。
        return adapter.body_count, step_ms

    finally:
        world.release_write(solver_id)
