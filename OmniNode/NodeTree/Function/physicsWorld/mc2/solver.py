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
from .candidate import make_mc2_result_candidate
from .center_state import (
    MC2CenterPersistentState,
    derive_mc2_center_world_pose,
    evaluate_mc2_center_frame_shift,
)
from .frame_state import MC2FrameInputSpec, plan_mc2_frame_sync, sync_mc2_frame_input
from .initial_state import MC2InitialStateSpec, build_mc2_initial_state
from .results import make_mc2_mesh_result, publish_mc2_result_transaction
from .specs import build_mc2_task_specs
from .state import MC2ParticleBuffer, MC2SlotRuntimeState
from .topology import build_mc2_topology_spec


MC2_FRAMEWORK_STATUS = (
    "MC2 context V0 已接入 Center/Move inertia、Gravity、Pin、Distance、Bending 数值 step；"
    "Mesh 公共结果事务已接入"
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
    result_candidate = slot.data.get("result_candidate")
    center_state = slot.data.get("center_state")
    center_step_result = slot.data.get("center_step_result")
    center_frame_shift_result = slot.data.get("center_frame_shift_result")
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
        "center_state": (
            center_state.debug_dict()
            if isinstance(center_state, MC2CenterPersistentState)
            else None
        ),
        "center_step_result": (
            {
                "frame_interpolation": center_step_result.frame_interpolation,
                "now_world_position": center_step_result.now_world_position,
                "inertia_vector": center_step_result.inertia_vector,
                "velocity_weight": center_step_result.velocity_weight,
                "blend_weight": center_step_result.blend_weight,
            }
            if center_step_result is not None
            else None
        ),
        "center_frame_shift_result": (
            {
                "shift_vector": center_frame_shift_result.frame_component_shift_vector,
                "shift_rotation": center_frame_shift_result.frame_component_shift_rotation_xyzw,
                "moving_speed": center_frame_shift_result.frame_moving_speed,
            }
            if center_frame_shift_result is not None
            else None
        ),
        "result_candidate": (
            result_candidate.debug_dict()
            if hasattr(result_candidate, "debug_dict")
            else None
        ),
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
    center_state = (
        MC2CenterPersistentState(mesh_static.center.center_static_signature)
        if mesh_static is not None
        else None
    )
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
            "center_state": center_state,
            "center_step_result": None,
            "center_frame_shift_result": None,
            "declaration": MC2_SOLVER_DECLARATION,
            "frame_state": {},
            "writeback_plan": {},
            "result_candidate": None,
            "result_candidate_revision": 0,
            "_dispose": lambda reason, slot=slot: _dispose_mc2_slot(slot, reason),
            "_debug_snapshot": lambda slot=slot: _slot_debug_snapshot(slot),
        }
    )
    return state


def _derive_slot_center_pose(slot, frame_input: MC2FrameInputSpec):
    mesh_static = slot.data.get("mesh_static")
    frame_pose = frame_input.center_frame_pose
    center_state = slot.data.get("center_state")
    if mesh_static is None or frame_pose is None:
        return None
    if not isinstance(center_state, MC2CenterPersistentState):
        raise RuntimeError("Mesh MC2 slot is missing Center persistent state")
    if center_state.center_static_signature != mesh_static.center.center_static_signature:
        raise RuntimeError("Mesh MC2 Center static identity changed without slot rebuild")
    return derive_mc2_center_world_pose(
        mesh_static.center,
        frame_pose,
        world_positions=frame_input.world_positions,
        world_rotations_xyzw=frame_input.world_rotations_xyzw,
        vertex_bind_pose_rotations=mesh_static.finalizer.vertex_bind_pose_rotations,
    )


def _make_slot_center_frame_shift(
    slot,
    frame_input: MC2FrameInputSpec,
    dt: float,
    *,
    time_scale: float,
    substeps: int,
):
    mesh_static = slot.data.get("mesh_static")
    center_state = slot.data.get("center_state")
    spec = slot.data.get("spec")
    frame_pose = frame_input.center_frame_pose
    if mesh_static is None or frame_pose is None or spec is None:
        return None
    if not isinstance(center_state, MC2CenterPersistentState) or not center_state.initialized:
        return None
    profile = spec.profile
    unit_scale = (1.0, 1.0, 1.0)
    anchor_stable = bool(
        center_state.anchor_identity
        and center_state.anchor_identity == frame_pose.anchor_identity
    )
    anchor_shift_active = (
        anchor_stable and float(profile.anchor_inertia) < 1.0 - 1.0e-8
    )
    world_shift_active = float(profile.world_inertia) < 1.0 - 1.0e-8
    in_verified_domain = (
        not mesh_static.center.fixed_indices
        and (world_shift_active or anchor_shift_active)
        and math.isclose(float(time_scale), 1.0, abs_tol=1.0e-8)
        and int(substeps) == 1
        and math.isclose(float(profile.movement_inertia_smoothing), 0.0, abs_tol=1.0e-8)
        and math.isclose(float(center_state.velocity_weight), 1.0, abs_tol=1.0e-8)
        and all(
            math.isclose(float(value), expected, abs_tol=1.0e-8)
            for values in (
                center_state.old_component_world_scale,
                frame_pose.component_world_scale,
            )
            for value, expected in zip(values, unit_scale)
        )
    )
    if not in_verified_domain:
        return None
    shift_input = center_state.make_frame_shift_input(
        frame_pose,
        simulation_delta_time=dt,
        frame_delta_time=dt,
        world_inertia=profile.world_inertia,
        anchor_inertia=profile.anchor_inertia,
        movement_speed_limit=profile.movement_speed_limit,
        rotation_speed_limit=profile.rotation_speed_limit,
        now_time_scale=time_scale,
    )
    return evaluate_mc2_center_frame_shift(shift_input)


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


def _validate_mc2_frame_input(spec, topology, frame_input: MC2FrameInputSpec) -> None:
    if frame_input.task_id != spec.task_id:
        raise ValueError("MC2 frame input task identity mismatch")
    if frame_input.topology_signature != topology.topology_signature:
        raise ValueError("MC2 frame input topology identity mismatch")
    if frame_input.particle_count != topology.particle_count:
        raise ValueError("MC2 frame input particle count mismatch")


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
    """Sync MC2 slots, run the no-collision Mesh slice, and publish results."""
    specs = build_mc2_task_specs(tasks)
    if settings is None:
        settings = make_mc2_solver_settings()
    if not isinstance(settings, MC2SolverSettingsSpec):
        raise TypeError("settings 必须是 MC2SolverSettingsSpec")
    if not enabled:
        return world, False, "MC2 模拟步已禁用"
    if not isinstance(world, PhysicsWorldCache):
        return world, False, "MC2 模拟步需要 PhysicsWorldCache"
    automatic_frame_inputs = frame_inputs is None and int(world.generation) > 0
    dt = float(dt)
    if automatic_frame_inputs and dt == 0.0:
        dt = float(getattr(world.frame_context, "dt", 0.0) or 0.0) * settings.time_scale
    if not math.isfinite(dt) or dt < 0.0:
        raise ValueError("MC2 dt必须是有限非负数")

    active_specs = tuple(spec for spec in specs if spec.enabled and spec.sources)
    frame_inputs = dict(frame_inputs or {})
    unknown_frame_ids = set(frame_inputs) - {spec.task_id for spec in active_specs}
    if unknown_frame_ids:
        raise ValueError(f"MC2 frame inputs contain unknown task ids: {sorted(unknown_frame_ids)!r}")
    if any(not isinstance(value, MC2FrameInputSpec) for value in frame_inputs.values()):
        raise TypeError("frame_inputs values must be MC2FrameInputSpec")
    if int(world.generation) > 0:
        world_frame = int(getattr(world.frame_context, "frame", 0) or 0)
        mismatched_frames = sorted(
            task_id
            for task_id, frame_input in frame_inputs.items()
            if frame_input.frame != world_frame
        )
        if mismatched_frames:
            raise ValueError(
                "MC2 frame inputs do not match the active Physics World frame: "
                f"{mismatched_frames!r}"
            )
    # 先完成全部只读构建，保证任一 task 校验失败时 world 不会半更新。
    prepared_items = []
    staged_native_contexts = []
    try:
        for spec in active_specs:
            topology = build_mc2_topology_spec(spec)
            effective = make_mc2_runtime_parameters(spec.profile, spec.setup_options)
            frame_input = frame_inputs.get(spec.task_id)
            if frame_input is not None:
                _validate_mc2_frame_input(spec, topology, frame_input)
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
            if frame_input is None and automatic_frame_inputs and mesh_static_supported:
                active_mesh_static = mesh_static
                if active_mesh_static is None:
                    existing_slot = world.solver_slots.get(spec.task_id)
                    if existing_slot is not None:
                        active_mesh_static = existing_slot.data.get("mesh_static")
                if active_mesh_static is None:
                    raise RuntimeError("automatic MC2 Mesh frame input has no static bundle")
                from .setups.mesh_cloth.frame_input import (
                    build_mc2_mesh_frame_input_for_task,
                )

                frame_input = build_mc2_mesh_frame_input_for_task(
                    world,
                    spec,
                    topology,
                    active_mesh_static,
                )
                _validate_mc2_frame_input(spec, topology, frame_input)
                frame_inputs[spec.task_id] = frame_input
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
    public_results: list[dict] = []
    published_results = ()
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
                center_state = slot.data.get("center_state")
                center_pose = _derive_slot_center_pose(slot, frame_input)
                center_action = None
                center_frame_shift_result = None
                center_step_input = None
                center_step_result = None
                if center_pose is not None and frame_plan.action != "same_frame":
                    if frame_plan.action == "reset" or not center_state.initialized:
                        center_action = "reset"
                    else:
                        if dt <= 0.0:
                            raise ValueError(
                                "MC2 continuous Center frame requires a positive dt"
                            )
                        center_action = "step"
                        center_frame_shift_result = _make_slot_center_frame_shift(
                            slot,
                            frame_input,
                            dt,
                            time_scale=world.frame_context.time_scale,
                            substeps=world.frame_context.substeps,
                        )
                        center_step_input = center_state.make_step_input(
                            frame_input.center_frame_pose,
                            center_pose,
                            simulation_delta_time=dt,
                            frame_interpolation=frame_input.frame_interpolation,
                            frame_shift=center_frame_shift_result,
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
                        if center_step_input is not None:
                            native_context.update_center_dynamic(center_step_input)
                            if center_frame_shift_result is not None:
                                native_context.apply_center_frame_shift(
                                    center_state.old_component_world_position,
                                    center_frame_shift_result,
                                )
                        native_context.step_no_collision(dt)
                        if center_step_input is not None:
                            center_step_result = native_context.read_center_step()
                elif center_step_input is not None:
                    raise RuntimeError("MC2 Center step requires a live native context")
                candidate = (
                    slot.data.get("result_candidate")
                    if frame_plan.action == "same_frame"
                    else None
                )
                if native_context is not None and frame_plan.action != "same_frame":
                    native_positions, native_rotations = native_context.read()
                    if slot.data.get("mesh_static") is not None:
                        candidate_revision = int(
                            slot.data.get("result_candidate_revision", 0)
                        ) + 1
                        candidate = make_mc2_result_candidate(
                            spec=spec,
                            slot=slot,
                            frame_input=frame_input,
                            revision=candidate_revision,
                            native_info=native_context.inspect(),
                            world_positions=native_positions,
                            world_rotations_xyzw=native_rotations,
                        )
                if center_action == "reset":
                    stabilization = float(spec.profile.stabilization_time_after_reset)
                    center_state.reset(
                        frame_input.center_frame_pose,
                        center_pose.position,
                        center_pose.rotation_xyzw,
                        velocity_weight=0.0 if stabilization > 1.0e-6 else 1.0,
                    )
                    slot.data["center_step_result"] = None
                    slot.data["center_frame_shift_result"] = None
                elif center_action == "step":
                    if center_step_result is None:
                        raise RuntimeError("MC2 native Center step did not produce a result")
                    center_state.commit_step(
                        frame_input.center_frame_pose,
                        center_pose,
                        center_step_result,
                    )
                    slot.data["center_step_result"] = center_step_result
                    slot.data["center_frame_shift_result"] = center_frame_shift_result
                frame_result = sync_mc2_frame_input(
                    runtime_state,
                    slot.data["particle_buffer"],
                    frame_input,
                    user_reset=bool(user_reset),
                )
                if frame_result != frame_plan:
                    raise RuntimeError("MC2 frame plan changed during commit")
                if candidate is not None:
                    slot.data["result_candidate"] = candidate
                    slot.data["result_candidate_revision"] = candidate.revision
                    if int(world.generation) > 0 and spec.setup_type == "mesh_cloth":
                        public_results.append(
                            make_mc2_mesh_result(
                                spec=spec,
                                candidate=candidate,
                                frame=frame_input.frame,
                                world_generation=world.generation,
                            )
                        )
        pruned = _prune_stale_mc2_slots(world, active_slot_ids)
        if int(world.generation) > 0:
            published_results = publish_mc2_result_transaction(world, public_results)
    finally:
        world.release_write(MC2_SOLVER_ID)
        for context in staged_native_contexts:
            context.dispose()

    status = (
        f"{MC2_FRAMEWORK_STATUS}（任务 {len(active_specs)}，"
        f"新建 {counts['created']}，重建 {counts['rebuilt']}，"
        f"更新 {counts['updated']}，复用 {counts['reused']}，清理 {pruned}）"
    )
    return world, bool(published_results), status
