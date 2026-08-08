"""
physicsWorld.rigid.solver — 刚体 spec 收集 + Jolt 模拟步

Phase 4：spec 收集（已由 physicsWorldBegin 自动完成）。
Phase 5：step_rigid_bodies — 接入 Jolt adapter，执行模拟步。
"""

from __future__ import annotations

import time

from .names import (
    JOLT_STEP_WRITER_ID,
    RIGID_BACKEND_RESOURCE_KEY,
    RIGID_BODY_COMMANDS_CHANNEL,
    RIGID_BODY_REGISTER_WRITER_ID,
    RIGID_BODY_SLOT_KIND,
    RIGID_CONSTRAINT_REGISTER_WRITER_ID,
    RIGID_CONSTRAINT_SLOT_KIND,
)
from ..types import PhysicsWorldCache
from .specs import (
    RigidBodySpec,
    ConstraintSpec,
    build_rigid_body_spec,
    build_constraint_spec,
)
from .implicit_objects import (
    has_pending_generated_constraints,
    has_pending_jolt_world_settings,
    sync_generated_constraint_slots,
    sync_rigid_jolt_world_settings,
)
from .results import (
    clear_rigid_constraint_state_results,
    clear_rigid_transform_results,
    publish_rigid_contact_event_batches,
    publish_rigid_constraint_state_result,
    publish_rigid_transform_batch,
    publish_rigid_transform_result,
    publish_rigid_solver_stats_result,
    RIGID_TRANSFORM_COLUMNS_CACHE_KEY,
)
from .declaration import RIGID_SOLVER_DECLARATION
from .debug import install_rigid_slot_debug_snapshot


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

    solver_id = RIGID_BODY_REGISTER_WRITER_ID
    world.acquire_write(solver_id)
    try:
        registered_ids: list[str] = []

        for obj in (_flatten(objects) or []):
            spec = build_rigid_body_spec(obj)
            if spec is None:
                continue

            slot = world.ensure_solver_slot(spec.slot_id, RIGID_BODY_SLOT_KIND)

            # world generation 变化时冷启动 slot（清掉旧 spec 和 native handle）
            if slot.world_generation != world.generation:
                slot.data.clear()
                slot.world_generation = world.generation

            slot.data["spec"] = spec
            slot.data["declaration"] = RIGID_SOLVER_DECLARATION
            install_rigid_slot_debug_snapshot(slot, spec)
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

    solver_id = RIGID_CONSTRAINT_REGISTER_WRITER_ID
    world.acquire_write(solver_id)
    try:
        registered_ids: list[str] = []

        for obj in (_flatten(constraint_objects) or []):
            spec = build_constraint_spec(obj)
            if spec is None:
                continue

            slot = world.ensure_solver_slot(spec.slot_id, RIGID_CONSTRAINT_SLOT_KIND)

            if slot.world_generation != world.generation:
                slot.data.clear()
                slot.world_generation = world.generation

            slot.data["spec"] = spec
            slot.data["declaration"] = RIGID_SOLVER_DECLARATION
            install_rigid_slot_debug_snapshot(slot, spec)
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
    if has_pending_jolt_world_settings(world):
        return True
    if has_pending_generated_constraints(world):
        return True
    for slot in world.solver_slots.values():
        if slot.kind not in {RIGID_BODY_SLOT_KIND, RIGID_CONSTRAINT_SLOT_KIND}:
            continue
        if slot.data.get("spec") is None:
            continue
        if slot.data.get("_jolt_generation") != world.generation:
            return True
        if slot.kind == RIGID_BODY_SLOT_KIND and slot.data.get("_jolt_kinematic_pose_dirty"):
            return True
    return False


def _ordered_solver_slots(
    world: PhysicsWorldCache,
    kind: str,
) -> list[tuple[str, object]]:
    """按语义身份排序，并拒绝缺失或冲突的模拟排序键。"""
    keyed: dict[tuple[str, ...], list[tuple[str, object]]] = {}
    for slot_id, slot in world.solver_slots.items():
        if slot.kind != kind:
            continue
        spec = slot.data.get("spec")
        if spec is None:
            continue
        raw_key = getattr(spec, "simulation_order_key", ())
        key = tuple(str(part) for part in raw_key) if isinstance(raw_key, (tuple, list)) else ()
        if not key or not any(key):
            message = f"模拟排序键缺失或无效: {slot_id}"
            slot.data["_simulation_order_error"] = message
            slot.data["_jolt_error"] = message
            continue
        keyed.setdefault(key, []).append((slot_id, slot))

    ordered: list[tuple[str, object]] = []
    for key in sorted(keyed):
        entries = keyed[key]
        if len(entries) != 1:
            message = f"模拟排序键冲突: {key!r}"
            for _slot_id, slot in entries:
                slot.data["_simulation_order_error"] = message
                slot.data["_jolt_error"] = message
            continue
        slot_id, slot = entries[0]
        previous = slot.data.pop("_simulation_order_error", None)
        if previous and slot.data.get("_jolt_error") == previous:
            slot.data.pop("_jolt_error", None)
        ordered.append((slot_id, slot))
    return ordered


def _ordered_constraint_slots(world: PhysicsWorldCache) -> list[tuple[str, object]]:
    """按 constraint-to-constraint 依赖排序，并把无效拓扑留在 slot diagnostics。"""
    entries = _ordered_solver_slots(world, RIGID_CONSTRAINT_SLOT_KIND)
    slots_by_id = dict(entries)
    state: dict[str, int] = {}
    ordered: list[tuple[str, object]] = []

    def visit(slot_id: str, stack: tuple[str, ...] = ()) -> bool:
        status = state.get(slot_id, 0)
        if status == 2:
            return True
        if status == -1:
            return False
        if status == 1:
            cycle = " -> ".join(stack + (slot_id,))
            slot = slots_by_id[slot_id]
            slot.data["_jolt_error"] = f"约束依赖形成循环: {cycle}"
            state[slot_id] = -1
            return False

        slot = slots_by_id[slot_id]
        spec = slot.data["spec"]
        constraint_type = str(getattr(spec, "constraint_type", "FIXED") or "FIXED")
        expected_types = {
            "GEAR": ("HINGE", "HINGE"),
            "RACK_AND_PINION": ("HINGE", "SLIDER"),
        }.get(constraint_type)
        references = (
            str(getattr(spec, "reference_constraint_a", "") or ""),
            str(getattr(spec, "reference_constraint_b", "") or ""),
        )
        state[slot_id] = 1
        if expected_types:
            for index, reference in enumerate(references):
                reference_slot = slots_by_id.get(reference)
                if reference_slot is None:
                    slot.data["_jolt_error"] = (
                        f"{constraint_type} 缺少引用约束 {index + 1}: {reference or '<empty>'}"
                    )
                    state[slot_id] = -1
                    return False
                reference_spec = reference_slot.data.get("spec")
                actual_type = str(
                    getattr(reference_spec, "constraint_type", "") or ""
                )
                if actual_type != expected_types[index]:
                    slot.data["_jolt_error"] = (
                        f"{constraint_type} 引用约束 {index + 1} 必须是 "
                        f"{expected_types[index]}，实际为 {actual_type or '<unknown>'}"
                    )
                    state[slot_id] = -1
                    return False
                if not visit(reference, stack + (slot_id,)):
                    slot.data["_jolt_error"] = f"依赖约束同步失败: {reference}"
                    state[slot_id] = -1
                    return False

        state[slot_id] = 2
        ordered.append((slot_id, slot))
        return True

    for slot_id, _slot in entries:
        visit(slot_id)
    return ordered


def _consume_exchange(world: PhysicsWorldCache, channel: str) -> list[dict]:
    return [item for item in world.consume_exchange(channel) if isinstance(item, dict)]


def _ordered_rigid_body_commands(world: PhysicsWorldCache) -> list[dict]:
    """保留图中显式 command 次序，同时让次序成为可检查的普通数据。"""
    items = _consume_exchange(world, RIGID_BODY_COMMANDS_CHANNEL)
    decorated = []
    for fallback_index, item in enumerate(items):
        raw_key = item.get("command_order_key")
        if isinstance(raw_key, (tuple, list)) and raw_key:
            key = tuple(str(part) for part in raw_key)
        else:
            key = (f"{fallback_index:012d}",)
        decorated.append((key, fallback_index, item))
    decorated.sort(key=lambda row: (row[0], row[1]))
    return [item for _key, _index, item in decorated]


def _rigid_command_token(world: PhysicsWorldCache) -> tuple[int, int]:
    fc = getattr(world, "frame_context", None)
    frame = int(getattr(fc, "frame", 0) or 0)
    return (int(getattr(world, "generation", 0) or 0), frame)


def _has_pending_rigid_body_commands(world: PhysicsWorldCache) -> bool:
    token = _rigid_command_token(world)
    for item in _ordered_rigid_body_commands(world):
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

    for item in _ordered_rigid_body_commands(world):
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


def _publish_rigid_transform_results(
    world: PhysicsWorldCache,
    adapter,
    ordered_slots=None,
    timing=None,
) -> int:
    """
    从 backend 采样本帧刚体 transform，写入 world result stream。

    这是 solver 和 writeback/debug/export 之间的边界：下游不应再读取
    solver slot、adapter._body_handles 或 adapter._jw 来拿本帧 transform。
    """
    fc = world.frame_context
    frame = int(getattr(fc, "frame", 0) or 0)
    published = 0
    if timing is not None:
        started = time.perf_counter()
    clear_rigid_transform_results(world)
    if timing is not None:
        timing["transform_clear_ms"] = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
    batch_columns = None
    get_body_state_columns = getattr(adapter, "get_body_state_columns", None)
    if callable(get_body_state_columns):
        batch_columns = get_body_state_columns()
    batch_states = None
    get_body_states = getattr(adapter, "get_body_states", None)
    if batch_columns is None and callable(get_body_states):
        batch_states = get_body_states()
    if timing is not None:
        timing["transform_state_fetch_ms"] = (time.perf_counter() - started) * 1000.0

    if batch_columns is None:
        world.backend_resources.pop(RIGID_TRANSFORM_COLUMNS_CACHE_KEY, None)

    if ordered_slots is None:
        ordered_slots = _ordered_solver_slots(world, RIGID_BODY_SLOT_KIND)
    if timing is not None:
        started = time.perf_counter()

    if batch_columns is not None:
        slot_indices = batch_columns[6]
        entries = []
        column_object_indices = {}
        for slot_id, slot in ordered_slots:
            spec = slot.data.get("spec")
            if spec is None:
                continue
            native_index = slot_indices.get(slot_id)
            if native_index is None:
                continue
            object_ptr = int(getattr(spec, "obj_ptr", 0) or 0)
            data_ptr = int(getattr(spec, "data_ptr", 0) or 0)
            body_type = str(getattr(spec, "body_type", "DYNAMIC") or "DYNAMIC")
            native_index = int(native_index)
            entries.append((slot_id, object_ptr, data_ptr, body_type, native_index))
            if object_ptr > 0:
                column_object_indices[object_ptr] = native_index
            slot.data.pop("_result_error", None)

        world.backend_resources[RIGID_TRANSFORM_COLUMNS_CACHE_KEY] = {
            "frame": frame,
            "generation": int(world.generation),
            "columns": batch_columns,
            "entries": tuple(entries),
            "object_indices": column_object_indices,
        }
        batch = publish_rigid_transform_batch(
            world,
            entries=entries,
            columns=batch_columns,
            frame=frame,
            generation=world.generation,
            backend=getattr(adapter, "BACKEND", "jolt"),
        )
        published = len(entries) if batch is not None else 0
        if timing is not None:
            timing["transform_result_loop_ms"] = (
                time.perf_counter() - started
            ) * 1000.0
        return published

    for slot_id, slot in ordered_slots:
        spec = slot.data.get("spec")
        if spec is None:
            continue

        try:
            state = None
            linear_velocity = None
            angular_velocity = None
            active = None
            sleeping = None
            if batch_states is not None:
                state = batch_states.get(slot_id)
                if state is None:
                    continue
                pos_arr = state.get("position")
                rot_arr = state.get("rotation_wxyz")
                linear_velocity = state.get("linear_velocity")
                angular_velocity = state.get("angular_velocity")
                active = state.get("active")
                sleeping = state.get("sleeping")
            elif hasattr(adapter, "get_body_state"):
                state = adapter.get_body_state(slot_id)
                if state is None:
                    continue
                pos_arr = state.get("position")
                rot_arr = state.get("rotation_wxyz")
                linear_velocity = state.get("linear_velocity")
                angular_velocity = state.get("angular_velocity")
                active = state.get("active")
                sleeping = state.get("sleeping")
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
                linear_velocity=linear_velocity,
                angular_velocity=angular_velocity,
                active=active,
                sleeping=sleeping,
                backend=getattr(adapter, "BACKEND", "jolt"),
            )
            if published_result is None:
                continue
            slot.data.pop("_result_error", None)
            published += 1
        except Exception as exc:
            slot.data["_result_error"] = str(exc)

    if timing is not None:
        timing["transform_result_loop_ms"] = (time.perf_counter() - started) * 1000.0

    return published


def _publish_rigid_constraint_state_results(
    world: PhysicsWorldCache,
    adapter,
    ordered_slots=None,
) -> int:
    """发布本帧约束状态；结果不得暴露 native constraint handle。"""
    fc = world.frame_context
    frame = int(getattr(fc, "frame", 0) or 0)
    published = 0
    clear_rigid_constraint_state_results(world)

    if ordered_slots is None:
        ordered_slots = _ordered_constraint_slots(world)
    for slot_id, slot in ordered_slots:
        spec = slot.data.get("spec")
        if spec is None:
            continue
        try:
            state = adapter.get_constraint_state(slot_id)
            if state is None:
                continue
            state = dict(state)
            state["broken"] = bool(slot.data.get("_jolt_broken", False))
            state["breaking_impulse"] = float(
                slot.data.get("_jolt_breaking_impulse", 0.0) or 0.0
            )
            result = publish_rigid_constraint_state_result(
                world,
                slot_id=slot_id,
                spec=spec,
                frame=frame,
                generation=world.generation,
                state=state,
                backend=getattr(adapter, "BACKEND", "jolt"),
            )
            if result is None:
                continue
            slot.data.pop("_result_error", None)
            published += 1
        except Exception as exc:
            slot.data["_result_error"] = str(exc)

    return published


def _publish_rigid_contact_event_results(
    world: PhysicsWorldCache,
    adapter,
) -> tuple[int, int]:
    """登记 native contact 批快照；逐事件结果只在消费者读取时展开。"""
    frame = int(getattr(world.frame_context, "frame", 0) or 0)
    contact_count = getattr(adapter, "last_contact_event_count", None)
    sensor_count = getattr(adapter, "last_sensor_event_count", None)
    if contact_count is None or sensor_count is None:
        # 非 Jolt 测试适配器/旧 ABI 没有原生计数时保留兼容读取。
        events = list(adapter.get_contact_events())
        contact_count = len(events)
        sensor_count = sum(1 for event in events if bool(event.get("is_sensor", False)))
    return publish_rigid_contact_event_batches(
        world,
        adapter,
        frame=frame,
        generation=world.generation,
        contact_count=int(contact_count or 0),
        sensor_count=int(sensor_count or 0),
        backend=getattr(adapter, "BACKEND", "jolt"),
    )


def _apply_breakable_constraint_policy(world: PhysicsWorldCache, adapter, ordered_slots=None) -> int:
    """在 Jolt step 后按每步约束冲量禁用超过阈值的约束。"""
    broken_count = 0
    if ordered_slots is None:
        ordered_slots = _ordered_constraint_slots(world)
    for slot_id, slot in ordered_slots:
        spec = slot.data.get("spec")
        if spec is None or not bool(getattr(spec, "breakable", False)):
            continue
        if bool(slot.data.get("_jolt_broken", False)):
            continue
        try:
            state = adapter.get_constraint_state(slot_id)
            if state is None or not bool(state.get("enabled", False)):
                continue
            impulse = float(state.get("lambda_max_abs", 0.0) or 0.0)
            threshold = max(
                float(getattr(spec, "breaking_threshold", 1000.0) or 0.0),
                0.0,
            )
            if impulse <= threshold:
                continue
            if not adapter.set_constraint_enabled(slot_id, False):
                continue
            slot.data["_jolt_broken"] = True
            slot.data["_jolt_breaking_impulse"] = impulse
            broken_count += 1
        except Exception as exc:
            slot.data["_jolt_error"] = str(exc)
    return broken_count


def _rigid_slot_error_counts(world: PhysicsWorldCache) -> tuple[int, int]:
    sync_error_count = 0
    result_error_count = 0
    for slot in world.solver_slots.values():
        if slot.kind not in {RIGID_BODY_SLOT_KIND, RIGID_CONSTRAINT_SLOT_KIND}:
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
    contact_event_count: int = 0,
    sensor_event_count: int = 0,
    timing: dict | None = None,
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
        contact_event_count=int(contact_event_count),
        sensor_event_count=int(sensor_event_count),
        contact_event_overflow=int(
            getattr(adapter, "last_contact_event_overflow", 0) or 0
        ),
        command_count=int(getattr(adapter, "last_command_count", 0) or 0),
        command_failed=int(getattr(adapter, "last_command_failed", 0) or 0),
        command_errors=list(getattr(adapter, "last_command_errors", []) or []),
        sync_error_count=sync_error_count,
        result_error_count=result_error_count,
        timing=timing,
        backend=getattr(adapter, "BACKEND", "jolt"),
    )


# ---------------------------------------------------------------------------
# Phase 5：Jolt 模拟步
# ---------------------------------------------------------------------------

def step_rigid_bodies(
    world: PhysicsWorldCache,
    enabled: bool = True,
    hotspot_timing: bool = False,
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

    timing = (
        {"schema": "jolt_rigid_step_timing_v1", "unit": "ms"}
        if bool(hotspot_timing)
        else None
    )
    fc = world.frame_context
    same_frame = bool(getattr(fc, "same_frame", False)) if fc is not None else False
    if same_frame and not _has_pending_jolt_work(world):
        adapter = world.backend_resources.get(RIGID_BACKEND_RESOURCE_KEY)
        body_count = int(getattr(adapter, "body_count", 0) or 0)
        if adapter is not None:
            adapter.last_command_count = 0
            adapter.last_command_failed = 0
            adapter.last_command_errors = []
            transform_count = _publish_rigid_transform_results(world, adapter, timing=timing)
            _publish_rigid_constraint_state_results(world, adapter)
            contact_count, sensor_count = _publish_rigid_contact_event_results(world, adapter)
            _publish_rigid_solver_stats(
                world, adapter, 0.0, transform_count, contact_count, sensor_count,
                timing=timing,
            )
        return body_count, 0.0

    from .backends.jolt import ensure_jolt_adapter

    adapter = ensure_jolt_adapter(world)
    if adapter is None:
        # hotools_jolt 未编译，静默降级
        return 0, 0.0

    # same-frame 只有在完全无待处理工作时才允许重发上一真实 step 的接触快照。
    # 走到这里说明 body/constraint/command 等状态即将变化，旧接触必须立即失效。
    if same_frame:
        clear_contacts = getattr(adapter, "_clear_contact_events", None)
        if callable(clear_contacts):
            clear_contacts()

    solver_id = JOLT_STEP_WRITER_ID
    world.acquire_write(solver_id)
    try:
        dt = float(fc.dt) if fc is not None and fc.dt > 0.0 else 1.0 / 60.0
        substeps = max(1, int(fc.substeps)) if fc is not None else 1
        try:
            from .implicit_objects import active_rigid_jolt_world_substeps
            configured_substeps = active_rigid_jolt_world_substeps(world)
            if configured_substeps > 0:
                substeps = configured_substeps
        except Exception:
            pass
        # Jolt rigid-world settings and generated constraints are persistent implicit objects.
        # Apply Jolt rigid-world settings first, then materialize generated constraints as regular slots.
        if timing is not None:
            started = time.perf_counter()
        sync_rigid_jolt_world_settings(world, adapter)
        sync_generated_constraint_slots(world, adapter=adapter)
        if timing is not None:
            timing["settings_sync_ms"] = (time.perf_counter() - started) * 1000.0

        # --- sync rigid bodies ---
        if timing is not None:
            started = time.perf_counter()
        ordered_body_slots = _ordered_solver_slots(world, RIGID_BODY_SLOT_KIND)
        pending_body_sync = []
        for slot_id, slot in ordered_body_slots:
            spec = slot.data.get("spec")
            if spec is None:
                continue

            needs_sync = slot.data.get("_jolt_generation") != world.generation
            if needs_sync:
                pending_body_sync.append((slot_id, slot, spec))
            elif spec.body_type == "KINEMATIC":
                adapter.update_kinematic(slot_id, spec, dt)
                slot.data.pop("_jolt_kinematic_pose_dirty", None)

        if pending_body_sync:
            batch_entries = [(slot_id, spec) for slot_id, _slot, spec in pending_body_sync]
            batch_errors = adapter.sync_bodies_batch(batch_entries)
            for slot_id, slot, _spec in pending_body_sync:
                error = batch_errors.get(str(slot_id))
                if error is not None:
                    slot.data["_jolt_error"] = error
                    continue
                slot.data["_jolt_generation"] = world.generation
                slot.data.pop("_jolt_kinematic_pose_dirty", None)
                slot.data.pop("_jolt_error", None)
        if timing is not None:
            timing["body_sync_ms"] = (time.perf_counter() - started) * 1000.0

        # --- sync constraints ---
        if timing is not None:
            started = time.perf_counter()
        ordered_constraint_slots = _ordered_constraint_slots(world)
        for slot_id, slot in ordered_constraint_slots:
            spec = slot.data["spec"]

            needs_sync = slot.data.get("_jolt_generation") != world.generation
            if needs_sync:
                try:
                    adapter.sync_constraint(slot_id, spec)
                    slot.data["_jolt_generation"] = world.generation
                    slot.data.pop("_jolt_broken", None)
                    slot.data.pop("_jolt_breaking_impulse", None)
                    slot.data.pop("_jolt_error", None)
                except Exception as e:
                    slot.data["_jolt_error"] = str(e)
        if timing is not None:
            timing["constraint_sync_ms"] = (time.perf_counter() - started) * 1000.0

        if timing is not None:
            started = time.perf_counter()
        _apply_rigid_body_commands(world, adapter)
        if timing is not None:
            timing["command_apply_ms"] = (time.perf_counter() - started) * 1000.0

        restart = bool(getattr(fc, "restart_required", True)) if fc is not None else True
        # 非连续 restart 只发布冷启动姿态，避免本帧刚清零的 Object.delta_*
        # 被重力等首步结果立即重新写入；首次初始化仍保持历史首帧推进语义。
        restart_without_step = restart and getattr(fc, "previous_frame", None) is not None
        if same_frame or restart_without_step:
            transform_count = _publish_rigid_transform_results(
                world, adapter, ordered_body_slots, timing=timing
            )
            _publish_rigid_constraint_state_results(world, adapter, ordered_constraint_slots)
            contact_count, sensor_count = _publish_rigid_contact_event_results(world, adapter)
            _publish_rigid_solver_stats(
                world, adapter, 0.0, transform_count, contact_count, sensor_count,
                timing=timing,
            )
            return adapter.body_count, 0.0

        # --- step ---
        if timing is None:
            step_ms = adapter.step(dt, substeps)
        else:
            step_ms = adapter.step(dt, substeps, timing=timing)
        if timing is not None:
            started = time.perf_counter()
        _apply_breakable_constraint_policy(world, adapter, ordered_constraint_slots)
        if timing is not None:
            timing["breakable_policy_ms"] = (time.perf_counter() - started) * 1000.0
            started = time.perf_counter()
        transform_count = _publish_rigid_transform_results(
            world, adapter, ordered_body_slots, timing=timing
        )
        if timing is not None:
            timing["transform_publish_ms"] = (time.perf_counter() - started) * 1000.0
            started = time.perf_counter()
        _publish_rigid_constraint_state_results(world, adapter, ordered_constraint_slots)
        if timing is not None:
            timing["constraint_publish_ms"] = (time.perf_counter() - started) * 1000.0
            started = time.perf_counter()
        contact_count, sensor_count = _publish_rigid_contact_event_results(world, adapter)
        if timing is not None:
            timing["contact_publish_ms"] = (time.perf_counter() - started) * 1000.0
        _publish_rigid_solver_stats(
            world, adapter, step_ms, transform_count, contact_count, sensor_count,
            timing=timing,
        )

        # 注意：写回由下游 Physics Writeback 节点统一处理。
        # adapter.writeback_transforms 不在此处调用，以便写回节点能先捕获 frame=0 初始位置。
        return adapter.body_count, step_ms

    finally:
        world.release_write(solver_id)
