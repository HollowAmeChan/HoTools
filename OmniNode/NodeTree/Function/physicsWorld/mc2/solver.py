"""统一 MC2 模拟步的 topology/slot 框架。"""

from __future__ import annotations

import math

from ..types import PhysicsWorldCache
from .declaration import MC2_SOLVER_DECLARATION
from .names import MC2_SLOT_KIND, MC2_SOLVER_ID
from .parameters import (
    MC2SolverSettingsSpec,
    make_mc2_solver_settings,
)
from .runtime_parameters import make_mc2_runtime_parameters
from .frame_state import MC2FrameInputSpec, plan_mc2_frame_sync, sync_mc2_frame_input
from .initial_state import MC2InitialStateSpec, build_mc2_initial_state
from .specs import build_mc2_task_specs
from .state import MC2ParticleBuffer, MC2SlotRuntimeState
from .topology import build_mc2_topology_spec


MC2_FRAMEWORK_STATUS = (
    "MC2 context V0已接入gravity/Pin/Distance/Bending数值step；inertia与结果发布尚未接入"
)


def _dispose_mc2_slot(slot, reason: str) -> None:
    native_context = slot.data.get("native_context")
    if native_context is not None and hasattr(native_context, "dispose"):
        native_context.dispose()
    particle_buffer = slot.data.get("particle_buffer")
    if isinstance(particle_buffer, MC2ParticleBuffer):
        particle_buffer.dispose()
    state = slot.data.get("runtime_state")
    if isinstance(state, MC2SlotRuntimeState):
        state.dispose(reason)


def _slot_debug_snapshot(slot) -> dict:
    topology = slot.data.get("topology")
    state = slot.data.get("runtime_state")
    particle_buffer = slot.data.get("particle_buffer")
    spec = slot.data.get("spec")
    mesh_static = slot.data.get("mesh_static")
    native_context = slot.data.get("native_context")
    return {
        "slot_id": slot.slot_id,
        "kind": slot.kind,
        "world_generation": slot.world_generation,
        "task": spec.debug_dict() if hasattr(spec, "debug_dict") else None,
        "topology": topology.debug_dict() if hasattr(topology, "debug_dict") else None,
        "mesh_static": (
            mesh_static.debug_dict()
            if hasattr(mesh_static, "debug_dict")
            else None
        ),
        "static_input_signature": slot.data.get("static_input_signature", ""),
        "runtime_state": state.debug_dict() if hasattr(state, "debug_dict") else None,
        "particle_buffer": (
            particle_buffer.debug_dict()
            if hasattr(particle_buffer, "debug_dict")
            else None
        ),
        "native_context": (
            native_context.inspect()
            if native_context is not None and hasattr(native_context, "inspect")
            else None
        ),
        "has_backend": native_context is not None,
        "has_writeback_plan": bool(slot.data.get("writeback_plan")),
    }


def _install_mc2_slot(
    slot,
    *,
    world: PhysicsWorldCache,
    spec,
    topology,
    effective_parameters,
    settings: MC2SolverSettingsSpec,
    initial_state: MC2InitialStateSpec,
    reset_reason: str,
    mesh_static=None,
    static_input_signature: str | None = None,
    native_context=None,
) -> MC2SlotRuntimeState:
    state = MC2SlotRuntimeState(
        task_id=spec.task_id,
        topology_signature=topology.topology_signature,
        config_signature=spec.config_signature,
        parameter_signature=effective_parameters.parameter_signature,
        settings_signature=settings.signature,
        world_generation=int(world.generation),
        particle_count=int(topology.particle_count),
        allocation_reason=str(reset_reason),
        last_reset_reason="allocation_pending",
        initialized=False,
    )
    particle_buffer = MC2ParticleBuffer.allocate(initial_state)
    slot.kind = MC2_SLOT_KIND
    slot.world_generation = int(world.generation)
    slot.data.update(
        {
            "spec": spec,
            "topology": topology,
            "effective_parameters": effective_parameters,
            "settings": settings,
            "initial_state": initial_state,
            "mesh_static": mesh_static,
            "static_input_signature": static_input_signature,
            "particle_buffer": particle_buffer,
            "native_context": native_context,
            "runtime_state": state,
            "declaration": MC2_SOLVER_DECLARATION,
            "frame_state": {},
            "writeback_plan": {},
            "_dispose": lambda reason, slot=slot: _dispose_mc2_slot(slot, reason),
            "_debug_snapshot": lambda slot=slot: _slot_debug_snapshot(slot),
        }
    )
    return state


def _mc2_slot_rebuild_reason(
    world: PhysicsWorldCache,
    spec,
    topology,
    static_input_signature: str | None = None,
) -> str:
    slot = world.solver_slots.get(spec.task_id)
    if slot is None:
        return "created"
    state = slot.data.get("runtime_state")
    if not isinstance(state, MC2SlotRuntimeState):
        return "runtime_state_missing"
    if not isinstance(slot.data.get("particle_buffer"), MC2ParticleBuffer):
        return "particle_buffer_missing"
    if not isinstance(slot.data.get("initial_state"), MC2InitialStateSpec):
        return "initial_state_missing"
    native_context = slot.data.get("native_context")
    if topology.particle_count > 0 and (
        native_context is None or bool(getattr(native_context, "disposed", True))
    ):
        return "native_context_missing"
    if slot.kind != MC2_SLOT_KIND:
        return "slot_kind_changed"
    if slot.world_generation != world.generation:
        return "world_generation_changed"
    if state.topology_signature != topology.topology_signature:
        return "topology_changed"
    if slot.data.get("static_input_signature") != static_input_signature:
        return "static_input_changed"
    return ""


def _sync_mc2_slot(
    world: PhysicsWorldCache,
    spec,
    settings: MC2SolverSettingsSpec,
    topology,
    effective,
    initial_state,
    mesh_static,
    static_input_signature,
    staged_native_context,
) -> tuple[str, object]:
    rebuild_reason = _mc2_slot_rebuild_reason(
        world,
        spec,
        topology,
        static_input_signature,
    )
    slot = world.ensure_solver_slot(spec.task_id, MC2_SLOT_KIND)
    previous_state = slot.data.get("runtime_state")

    if rebuild_reason:
        if not isinstance(initial_state, MC2InitialStateSpec):
            raise RuntimeError("MC2 slot 重建缺少 MC2InitialStateSpec")
        if slot.data:
            slot.dispose(rebuild_reason)
        _install_mc2_slot(
            slot,
            world=world,
            spec=spec,
            topology=topology,
            effective_parameters=effective,
            settings=settings,
            initial_state=initial_state,
            mesh_static=mesh_static,
            static_input_signature=static_input_signature,
            reset_reason=rebuild_reason,
            native_context=staged_native_context,
        )
        return "created" if rebuild_reason == "created" else "rebuilt", slot

    parameter_will_change = (
        previous_state.config_signature != spec.config_signature
        or previous_state.parameter_signature != effective.parameter_signature
    )
    native_context = slot.data.get("native_context")
    if parameter_will_change and native_context is not None:
        native_context.update_parameters(effective)
    parameter_changed, settings_changed = previous_state.update_contracts(
        config_signature=spec.config_signature,
        parameter_signature=effective.parameter_signature,
        settings_signature=settings.signature,
    )
    slot.data["spec"] = spec
    slot.data["topology"] = topology
    slot.data["effective_parameters"] = effective
    slot.data["settings"] = settings
    if parameter_changed:
        slot.data["writeback_plan"] = {}
    if parameter_changed or settings_changed:
        return "updated", slot
    return "reused", slot


def _prune_stale_mc2_slots(world: PhysicsWorldCache, active_slot_ids) -> int:
    active = set(str(slot_id) for slot_id in (active_slot_ids or ()))
    stale_ids = [
        slot_id
        for slot_id, slot in list(world.solver_slots.items())
        if slot.kind == MC2_SLOT_KIND and slot_id not in active
    ]
    for slot_id in stale_ids:
        slot = world.solver_slots.pop(slot_id, None)
        if slot is not None:
            slot.dispose("mc2_scope_prune")
    if stale_ids:
        world.replace_required = True
    return len(stale_ids)


def step_mc2(
    world,
    tasks=None,
    *,
    settings: MC2SolverSettingsSpec | None = None,
    frame_inputs: dict[str, MC2FrameInputSpec] | None = None,
    user_reset: bool = False,
    dt: float = 0.0,
    enabled: bool = True,
) -> tuple[object, bool, str]:
    """同步 topology/slot/context；V0连续帧执行Pin/Distance且不发布solver result。"""
    specs = build_mc2_task_specs(tasks)
    if settings is None:
        settings = make_mc2_solver_settings()
    if not isinstance(settings, MC2SolverSettingsSpec):
        raise TypeError("settings 必须是 MC2SolverSettingsSpec")
    if not enabled:
        return world, False, "MC2 模拟步已禁用"
    if not isinstance(world, PhysicsWorldCache):
        return world, False, "MC2 模拟步需要 PhysicsWorldCache"
    dt = float(dt)
    if not math.isfinite(dt) or dt < 0.0:
        raise ValueError("MC2 dt必须是有限非负数")

    active_specs = tuple(spec for spec in specs if spec.enabled and spec.sources)
    frame_inputs = dict(frame_inputs or {})
    unknown_frame_ids = set(frame_inputs) - {spec.task_id for spec in active_specs}
    if unknown_frame_ids:
        raise ValueError(f"MC2 frame inputs contain unknown task ids: {sorted(unknown_frame_ids)!r}")
    if any(not isinstance(value, MC2FrameInputSpec) for value in frame_inputs.values()):
        raise TypeError("frame_inputs values must be MC2FrameInputSpec")
    # 先完成全部只读构建，保证任一 task 校验失败时 world 不会半更新。
    prepared_items = []
    staged_native_contexts = []
    try:
        for spec in active_specs:
            topology = build_mc2_topology_spec(spec)
            effective = make_mc2_runtime_parameters(spec.profile, spec.setup_options)
            frame_input = frame_inputs.get(spec.task_id)
            if frame_input is not None:
                if frame_input.task_id != spec.task_id:
                    raise ValueError("MC2 frame input task identity mismatch")
                if frame_input.topology_signature != topology.topology_signature:
                    raise ValueError("MC2 frame input topology identity mismatch")
                if frame_input.particle_count != topology.particle_count:
                    raise ValueError("MC2 frame input particle count mismatch")
            static_input_signature = None
            mesh_static_supported = (
                spec.setup_type == "mesh_cloth"
                and all(source.resolved for source in topology.sources)
                and topology.particle_count > 0
            )
            if mesh_static_supported:
                from .setups.mesh_cloth.static_build import (
                    mesh_cloth_static_input_signature_for_task,
                )

                static_input_signature = mesh_cloth_static_input_signature_for_task(
                    spec,
                    topology,
                )
            rebuild_reason = _mc2_slot_rebuild_reason(
                world,
                spec,
                topology,
                static_input_signature,
            )
            initial_state = (
                build_mc2_initial_state(spec, topology)
                if rebuild_reason
                else None
            )
            mesh_static = None
            if rebuild_reason and mesh_static_supported:
                from .setups.mesh_cloth.static_build import (
                    build_mc2_mesh_cloth_static_for_task,
                )

                mesh_static = build_mc2_mesh_cloth_static_for_task(spec, topology)
            staged_native_context = None
            staged_native_frame_applied = False
            if rebuild_reason and topology.particle_count > 0:
                from .native import MC2NativeContextV0

                staged_native_context = MC2NativeContextV0(topology.particle_count)
                try:
                    if mesh_static is not None:
                        staged_native_context.update_mesh_static(mesh_static)
                    staged_native_context.update_parameters(effective)
                    if frame_input is not None:
                        staged_native_context.update_dynamic(frame_input)
                        staged_native_context.reset()
                        staged_native_context.read()
                        staged_native_frame_applied = True
                except Exception:
                    staged_native_context.dispose()
                    raise
                staged_native_contexts.append(staged_native_context)
            prepared_items.append(
                (
                    spec,
                    topology,
                    effective,
                    initial_state,
                    mesh_static,
                    static_input_signature,
                    staged_native_context,
                    staged_native_frame_applied,
                )
            )
    except Exception:
        for context in staged_native_contexts:
            context.dispose()
        raise
    prepared = tuple(prepared_items)
    counts = {"created": 0, "rebuilt": 0, "updated": 0, "reused": 0}
    active_slot_ids: list[str] = []
    world.acquire_write(MC2_SOLVER_ID)
    try:
        for (
            spec,
            topology,
            effective,
            initial_state,
            mesh_static,
            static_input_signature,
            staged_native_context,
            staged_native_frame_applied,
        ) in prepared:
            action, slot = _sync_mc2_slot(
                world,
                spec,
                settings,
                topology,
                effective,
                initial_state,
                mesh_static,
                static_input_signature,
                staged_native_context,
            )
            if staged_native_context in staged_native_contexts:
                staged_native_contexts.remove(staged_native_context)
            counts[action] += 1
            active_slot_ids.append(slot.slot_id)
            frame_input = frame_inputs.get(spec.task_id)
            if frame_input is not None:
                runtime_state = slot.data["runtime_state"]
                native_context = slot.data.get("native_context")
                frame_plan = plan_mc2_frame_sync(
                    runtime_state,
                    frame_input,
                    user_reset=bool(user_reset),
                )
                if (
                    native_context is not None
                    and frame_plan.action != "same_frame"
                    and not staged_native_frame_applied
                ):
                    native_context.update_dynamic(frame_input)
                    if frame_plan.action == "reset":
                        native_context.reset()
                    else:
                        native_context.step_no_collision(dt)
                    native_context.read()
                frame_result = sync_mc2_frame_input(
                    runtime_state,
                    slot.data["particle_buffer"],
                    frame_input,
                    user_reset=bool(user_reset),
                )
                if frame_result != frame_plan:
                    raise RuntimeError("MC2 frame plan changed during commit")
        pruned = _prune_stale_mc2_slots(world, active_slot_ids)
    finally:
        world.release_write(MC2_SOLVER_ID)
        for context in staged_native_contexts:
            context.dispose()

    status = (
        f"{MC2_FRAMEWORK_STATUS}（任务 {len(active_specs)}，"
        f"新建 {counts['created']}，重建 {counts['rebuilt']}，"
        f"更新 {counts['updated']}，复用 {counts['reused']}，清理 {pruned}）"
    )
    return world, False, status
