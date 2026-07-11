"""统一 MC2 模拟步的 topology/slot 框架。"""

from __future__ import annotations

from ..types import PhysicsWorldCache
from .declaration import MC2_SOLVER_DECLARATION
from .names import MC2_SLOT_KIND, MC2_SOLVER_ID
from .parameters import (
    MC2SolverSettingsSpec,
    make_mc2_effective_parameters,
    make_mc2_solver_settings,
)
from .initial_state import MC2InitialStateSpec, build_mc2_initial_state
from .specs import build_mc2_task_specs
from .state import MC2ParticleBuffer, MC2SlotRuntimeState
from .topology import build_mc2_topology_spec


MC2_FRAMEWORK_STATUS = (
    "MC2 topology/particle-buffer 框架已就绪；MeshCloth、BoneCloth、BoneSpring 后端尚未接入"
)


def _dispose_mc2_slot(slot, reason: str) -> None:
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
        "has_backend": False,
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
) -> MC2SlotRuntimeState:
    state = MC2SlotRuntimeState(
        topology_signature=topology.topology_signature,
        config_signature=spec.config_signature,
        parameter_signature=effective_parameters.parameter_signature,
        settings_signature=settings.signature,
        world_generation=int(world.generation),
        particle_count=int(topology.particle_count),
        last_reset_reason=str(reset_reason),
        initialized=True,
    )
    particle_buffer = MC2ParticleBuffer.from_initial_state(initial_state)
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
        )
        return "created" if rebuild_reason == "created" else "rebuilt", slot

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
    enabled: bool = True,
) -> tuple[object, bool, str]:
    """同步 topology/slot；不调用 backend，也不发布 solver result。"""
    specs = build_mc2_task_specs(tasks)
    if settings is None:
        settings = make_mc2_solver_settings()
    if not isinstance(settings, MC2SolverSettingsSpec):
        raise TypeError("settings 必须是 MC2SolverSettingsSpec")
    if not enabled:
        return world, False, "MC2 模拟步已禁用"
    if not isinstance(world, PhysicsWorldCache):
        return world, False, "MC2 模拟步需要 PhysicsWorldCache"

    active_specs = tuple(spec for spec in specs if spec.enabled and spec.sources)
    # 先完成全部只读构建，保证任一 task 校验失败时 world 不会半更新。
    prepared_items = []
    for spec in active_specs:
        topology = build_mc2_topology_spec(spec)
        effective = make_mc2_effective_parameters(
            spec.profile,
            settings,
            spec.setup_options,
        )
        static_input_signature = None
        if spec.setup_type == "mesh_cloth":
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
        if rebuild_reason and spec.setup_type == "mesh_cloth":
            from .setups.mesh_cloth.static_build import (
                build_mc2_mesh_cloth_static_for_task,
            )

            mesh_static = build_mc2_mesh_cloth_static_for_task(spec, topology)
        prepared_items.append(
            (
                spec,
                topology,
                effective,
                initial_state,
                mesh_static,
                static_input_signature,
            )
        )
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
            )
            counts[action] += 1
            active_slot_ids.append(slot.slot_id)
        pruned = _prune_stale_mc2_slots(world, active_slot_ids)
    finally:
        world.release_write(MC2_SOLVER_ID)

    status = (
        f"{MC2_FRAMEWORK_STATUS}（任务 {len(active_specs)}，"
        f"新建 {counts['created']}，重建 {counts['rebuilt']}，"
        f"更新 {counts['updated']}，复用 {counts['reused']}，清理 {pruned}）"
    )
    return world, False, status
