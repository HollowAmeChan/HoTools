"""统一 MC2 模拟步的 topology/slot 框架。"""

from __future__ import annotations

from dataclasses import replace
import math

from ..types import PhysicsWorldCache
from .declaration import MC2_SOLVER_DECLARATION
from .names import MC2_SETUP_BONE_SPRING, MC2_SLOT_KIND, MC2_SOLVER_ID
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
from .results import (
    make_mc2_bone_result,
    make_mc2_mesh_result,
    publish_mc2_result_transaction,
)
from .scheduler import MC2TimeSchedulerState
from .specs import build_mc2_task_specs
from .state import MC2ParticleBuffer, MC2SlotRuntimeState
from .topology import build_mc2_topology_spec


MC2_FRAMEWORK_STATUS = (
    "MC2 context V0 已接入 Center/Move inertia、Gravity、Pin、Distance、Bending 数值 step；"
    "Mesh/Bone 公共结果事务与统一writeback已接入"
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
    bone_static = slot.data.get("bone_static")
    native_context = slot.data.get("native_context")
    result_candidate = slot.data.get("result_candidate")
    center_state = slot.data.get("center_state")
    time_scheduler = slot.data.get("time_scheduler")
    center_step_result = slot.data.get("center_step_result")
    center_frame_shift_result = slot.data.get("center_frame_shift_result")
    frame_schedule = slot.data.get("frame_schedule")
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
        "bone_static": (
            bone_static.debug_dict()
            if hasattr(bone_static, "debug_dict")
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
        "time_scheduler": (
            time_scheduler.debug_dict()
            if isinstance(time_scheduler, MC2TimeSchedulerState)
            else None
        ),
        "frame_schedule": (
            frame_schedule.debug_dict()
            if hasattr(frame_schedule, "debug_dict")
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
                "smoothing_velocity": center_frame_shift_result.smoothing_velocity,
                "keep_teleport": center_frame_shift_result.keep_teleport,
                "reset_teleport": center_frame_shift_result.reset_teleport,
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
    bone_static=None,
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
    active_static = mesh_static if mesh_static is not None else bone_static
    center_state = (
        MC2CenterPersistentState(active_static.center.center_static_signature)
        if active_static is not None
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
            "bone_static": bone_static,
            "static_input_signature": static_input_signature,
            "particle_buffer": particle_buffer,
            "native_context": native_context,
            "runtime_state": state,
            "center_state": center_state,
            "time_scheduler": MC2TimeSchedulerState(),
            "frame_schedule": None,
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
    center_pose,
    simulation_delta_time: float,
    *,
    frame_dt: float,
    time_scale: float,
    skip_count: int,
    negative_scale_transition=None,
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
    smoothing_active = float(profile.movement_inertia_smoothing) >= 1.0e-6
    time_scale_active = float(time_scale) < 1.0 - 1.0e-8
    skip_shift_active = int(skip_count) > 0
    teleport_mode = int(profile.teleport_mode)
    configured_teleport_active = teleport_mode in (1, 2)
    unit_positive_scale_domain = all(
        math.isclose(float(value), expected, abs_tol=1.0e-8)
        for values in (
            center_state.old_component_world_scale,
            frame_pose.component_world_scale,
        )
        for value, expected in zip(values, unit_scale)
    )
    configured_negative_transition_domain = bool(
        teleport_mode in (1, 2)
        and negative_scale_transition is not None
        and negative_scale_transition.active
    )
    in_verified_domain = (
        (
            world_shift_active
            or anchor_shift_active
            or smoothing_active
            or time_scale_active
            or skip_shift_active
            or configured_teleport_active
        )
        and 0.0 <= float(time_scale) <= 1.0
        and math.isclose(float(center_state.velocity_weight), 1.0, abs_tol=1.0e-8)
        and (
            unit_positive_scale_domain
            or configured_negative_transition_domain
        )
    )
    if not in_verified_domain:
        return None
    shift_input = center_state.make_frame_shift_input(
        frame_pose,
        center_pose=center_pose,
        simulation_delta_time=simulation_delta_time,
        frame_delta_time=frame_dt,
        world_inertia=profile.world_inertia,
        anchor_inertia=profile.anchor_inertia,
        movement_inertia_smoothing=profile.movement_inertia_smoothing,
        movement_speed_limit=profile.movement_speed_limit,
        rotation_speed_limit=profile.rotation_speed_limit,
        is_running=float(time_scale) > 0.0,
        now_time_scale=time_scale,
        skip_count=int(skip_count),
        teleport_mode=teleport_mode if configured_teleport_active else 0,
        teleport_distance=profile.teleport_distance,
        teleport_rotation=profile.teleport_rotation,
        negative_scale_transition=negative_scale_transition,
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
    if not isinstance(slot.data.get("time_scheduler"), MC2TimeSchedulerState):
        return "time_scheduler_missing"
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
    bone_static,
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
            bone_static=bone_static,
            static_input_signature=static_input_signature,
            reset_reason=rebuild_reason,
            native_context=staged_native_context,
        )
        return "created" if rebuild_reason == "created" else "rebuilt", slot

    parameter_will_change = (
        previous_state.config_signature != spec.config_signature
        or previous_state.parameter_signature != effective.parameter_signature
    )
    previous_spec = slot.data.get("spec")
    team_options_will_change = (
        previous_spec is None
        or previous_spec.profile.animation_pose_ratio
        != spec.profile.animation_pose_ratio
    )
    native_context = slot.data.get("native_context")
    if parameter_will_change and native_context is not None:
        native_context.update_parameters(
            effective,
            animation_pose_ratio=spec.profile.animation_pose_ratio,
        )
    elif team_options_will_change and native_context is not None:
        native_context.update_team_options(spec.profile.animation_pose_ratio)
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
    if parameter_changed or settings_changed or team_options_will_change:
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
            bone_static_supported = (
                spec.setup_type in ("bone_cloth", "bone_spring")
                and len(topology.sources) == 1
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
            elif bone_static_supported:
                from .setups.bone_cloth.static_build import (
                    bone_cloth_static_input_signature_for_task,
                )

                static_input_signature = bone_cloth_static_input_signature_for_task(
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
            bone_static = None
            if rebuild_reason and mesh_static_supported:
                from .setups.mesh_cloth.static_build import (
                    build_mc2_mesh_cloth_static_for_task,
                )

                mesh_static = build_mc2_mesh_cloth_static_for_task(spec, topology)
            elif rebuild_reason and bone_static_supported:
                from .setups.bone_cloth.static_build import (
                    build_mc2_bone_cloth_static_for_task,
                )

                bone_static = build_mc2_bone_cloth_static_for_task(spec, topology)
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
            elif frame_input is None and automatic_frame_inputs and bone_static_supported:
                from .setups.bone_frame_input import build_mc2_bone_frame_input

                frame_input = build_mc2_bone_frame_input(
                    spec,
                    topology,
                    frame=int(getattr(world.frame_context, "frame", 0) or 0),
                    generation=int(world.generation),
                )
                _validate_mc2_frame_input(spec, topology, frame_input)
                frame_inputs[spec.task_id] = frame_input
            collider_frame = None
            if frame_input is not None and (mesh_static_supported or bone_static_supported):
                from .collider_frame import build_mc2_collider_frame

                collider_frame = build_mc2_collider_frame(
                    world,
                    spec.sources[0],
                    collided_by_groups=(
                        None
                        if mesh_static_supported
                        else spec.setup_options.collided_by_groups
                    ),
                    allowed_types=(
                        frozenset(("SPHERE",))
                        if spec.setup_type == MC2_SETUP_BONE_SPRING
                        else None
                    ),
                )
            staged_native_context = None
            staged_native_frame_applied = False
            if rebuild_reason and topology.particle_count > 0:
                from .native import MC2NativeContextV0

                staged_native_context = MC2NativeContextV0(
                    topology.particle_count,
                    setup_type=spec.setup_type,
                )
                try:
                    if mesh_static is not None:
                        staged_native_context.update_mesh_static(mesh_static)
                    elif bone_static is not None:
                        staged_native_context.update_bone_static(bone_static)
                    staged_native_context.update_parameters(
                        effective,
                        animation_pose_ratio=spec.profile.animation_pose_ratio,
                    )
                    if frame_input is not None:
                        if collider_frame is not None:
                            staged_native_context.update_colliders(collider_frame)
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
                    bone_static,
                    static_input_signature,
                    collider_frame,
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
    staged_writeback_plans: dict[str, dict] = {}
    published_results = ()
    world.acquire_write(MC2_SOLVER_ID)
    try:
        for (
            spec,
            topology,
            effective,
            initial_state,
            mesh_static,
            bone_static,
            static_input_signature,
            collider_frame,
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
                bone_static,
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
                if center_pose is not None and isinstance(
                    center_state, MC2CenterPersistentState
                ):
                    initial_scale = (
                        center_state.initial_scale
                        if center_state.initialized
                        else center_pose.scale
                    )
                    frame_input = replace(
                        frame_input,
                        scale_ratio=max(
                            math.sqrt(sum(value * value for value in center_pose.scale))
                            / math.sqrt(sum(value * value for value in initial_scale)),
                            1.0e-6,
                        ),
                        negative_scale_sign=(
                            -1.0 if any(value < 0.0 for value in center_pose.scale) else 1.0
                        ),
                    )
                center_action = None
                center_negative_scale_result = None
                center_frame_shift_result = None
                configured_reset_teleport = False
                staged_reset_center_state = None
                center_step_input = None
                center_step_result = None
                frame_schedule = None
                time_scheduler = slot.data.get("time_scheduler")
                if not isinstance(time_scheduler, MC2TimeSchedulerState):
                    raise RuntimeError("MC2 slot is missing its time scheduler")
                if center_pose is not None and frame_plan.action != "same_frame":
                    if frame_plan.action == "reset" or not center_state.initialized:
                        center_action = "reset"
                    else:
                        effective_time_scale = (
                            float(world.frame_context.time_scale)
                            * float(settings.time_scale)
                        )
                        if effective_time_scale > 0.0 and dt <= 0.0:
                            raise ValueError(
                                "MC2 continuous Center frame requires a positive dt"
                            )
                        frame_dt = float(
                            getattr(world.frame_context, "raw_dt", 0.0) or 0.0
                        )
                        if frame_dt <= 0.0 and effective_time_scale > 0.0:
                            frame_dt = dt / effective_time_scale
                        if frame_dt <= 0.0:
                            raise ValueError(
                                "MC2 Center frame shift requires a positive raw frame dt"
                            )
                        frame_schedule = time_scheduler.plan_frame(
                            frame_delta_time=frame_dt,
                            now_time_scale=effective_time_scale,
                            simulation_delta_time=(
                                1.0 / float(settings.simulation_frequency)
                            ),
                            max_simulation_count_per_frame=(
                                settings.max_simulation_count_per_frame
                            ),
                        )
                        if effective_time_scale <= 0.0:
                            center_action = "pause"
                        elif frame_schedule.update_count > 0:
                            center_action = "step"
                        else:
                            center_action = "idle"
                        center_negative_scale_result = (
                            center_state.make_negative_scale_transition(
                                frame_input.center_frame_pose,
                                center_pose,
                            )
                        )
                        if center_action in ("step", "pause"):
                            center_frame_shift_result = _make_slot_center_frame_shift(
                                slot,
                                frame_input,
                                center_pose,
                                (
                                    frame_schedule.simulation_delta_time
                                    if center_action == "step"
                                    else 0.0
                                ),
                                frame_dt=frame_dt,
                                time_scale=effective_time_scale,
                                skip_count=frame_schedule.skip_count,
                                negative_scale_transition=center_negative_scale_result,
                            )
                            configured_reset_teleport = bool(
                                center_frame_shift_result is not None
                                and center_frame_shift_result.reset_teleport
                            )
                            if configured_reset_teleport:
                                staged_reset_center_state = replace(center_state)
                                stabilization = float(
                                    spec.profile.stabilization_time_after_reset
                                )
                                staged_reset_center_state.reset(
                                    frame_input.center_frame_pose,
                                    center_pose.position,
                                    center_pose.rotation_xyzw,
                                    velocity_weight=(
                                        0.0 if stabilization > 1.0e-6 else 1.0
                                    ),
                                )
                if (
                    native_context is not None
                    and frame_plan.action != "same_frame"
                    and not staged_native_frame_applied
                ):
                    if collider_frame is not None:
                        native_context.update_colliders(collider_frame)
                    native_context.update_dynamic(frame_input)
                    if frame_plan.action == "reset":
                        native_context.reset()
                    else:
                        if configured_reset_teleport:
                            native_context.reset()
                        else:
                            if (
                                center_negative_scale_result is not None
                                and center_negative_scale_result.active
                            ):
                                native_context.apply_center_negative_scale_teleport(
                                    center_negative_scale_result
                                )
                            if center_frame_shift_result is not None:
                                frame_shift_pivot = (
                                    center_negative_scale_result.old_component_world_position
                                    if (
                                        center_negative_scale_result is not None
                                        and center_negative_scale_result.active
                                    )
                                    else center_state.old_component_world_position
                                )
                                native_context.apply_center_frame_shift(
                                    frame_shift_pivot,
                                    center_frame_shift_result,
                                )
                        if center_action == "step":
                            step_center_state = (
                                staged_reset_center_state
                                if configured_reset_teleport
                                else center_state
                            )
                            for update_index in range(frame_schedule.update_count):
                                frame_interpolation = time_scheduler.advance_step(
                                    update_index
                                )
                                if update_index == 0:
                                    center_step_input = step_center_state.make_step_input(
                                        frame_input.center_frame_pose,
                                        center_pose,
                                        simulation_delta_time=(
                                            frame_schedule.simulation_delta_time
                                        ),
                                        frame_interpolation=frame_interpolation,
                                        frame_shift=(
                                            None
                                            if configured_reset_teleport
                                            else center_frame_shift_result
                                        ),
                                    )
                                    native_context.update_center_dynamic(center_step_input)
                                else:
                                    native_context.update_step_interpolation(
                                        frame_interpolation
                                    )
                                native_context.step_no_collision(
                                    frame_schedule.simulation_delta_time,
                                    is_final_substep=(
                                        update_index == frame_schedule.update_count - 1
                                    ),
                                )
                            center_step_result = native_context.read_center_step()
                        elif center_pose is None and dt > 0.0:
                            native_context.step_no_collision(dt)
                elif center_action in ("step", "pause"):
                    raise RuntimeError("MC2 Center step requires a live native context")
                candidate = (
                    slot.data.get("result_candidate")
                    if frame_plan.action == "same_frame"
                    else None
                )
                if native_context is not None and frame_plan.action != "same_frame":
                    native_positions, native_rotations = native_context.read()
                    has_mesh_static = slot.data.get("mesh_static") is not None
                    has_bone_static = slot.data.get("bone_static") is not None
                    if has_bone_static:
                        native_positions, native_rotations = (
                            native_context.read_bone_output()
                        )
                    if has_mesh_static or has_bone_static:
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
                    time_scheduler.reset()
                    slot.data["frame_schedule"] = None
                    stabilization = float(spec.profile.stabilization_time_after_reset)
                    center_state.reset(
                        frame_input.center_frame_pose,
                        center_pose.position,
                        center_pose.rotation_xyzw,
                        velocity_weight=0.0 if stabilization > 1.0e-6 else 1.0,
                    )
                    slot.data["center_step_result"] = None
                    slot.data["center_frame_shift_result"] = None
                    slot.data["center_negative_scale_result"] = None
                elif center_action == "step":
                    if center_step_result is None:
                        raise RuntimeError("MC2 native Center step did not produce a result")
                    committed_center_state = (
                        staged_reset_center_state
                        if configured_reset_teleport
                        else center_state
                    )
                    if configured_reset_teleport:
                        slot.data["center_state"] = committed_center_state
                        center_state = committed_center_state
                    else:
                        center_state.apply_negative_scale_transition(
                            center_negative_scale_result
                        )
                        center_state.commit_frame_shift(center_frame_shift_result)
                    committed_center_state.commit_step(
                        frame_input.center_frame_pose,
                        center_pose,
                        center_step_result,
                    )
                    slot.data["center_step_result"] = center_step_result
                    slot.data["center_frame_shift_result"] = center_frame_shift_result
                    slot.data["center_negative_scale_result"] = (
                        None
                        if configured_reset_teleport
                        else center_negative_scale_result
                    )
                    slot.data["frame_schedule"] = frame_schedule
                elif center_action == "pause":
                    if center_frame_shift_result is None:
                        raise RuntimeError("MC2 paused Center frame requires a frame shift")
                    if configured_reset_teleport:
                        slot.data["center_state"] = staged_reset_center_state
                        center_state = staged_reset_center_state
                    else:
                        center_state.apply_negative_scale_transition(
                            center_negative_scale_result
                        )
                        center_state.commit_paused_frame(
                            frame_input.center_frame_pose,
                            center_frame_shift_result,
                        )
                    slot.data["center_step_result"] = None
                    slot.data["center_frame_shift_result"] = center_frame_shift_result
                    slot.data["center_negative_scale_result"] = (
                        None
                        if configured_reset_teleport
                        else center_negative_scale_result
                    )
                    slot.data["frame_schedule"] = frame_schedule
                elif center_action == "idle":
                    slot.data["center_step_result"] = None
                    slot.data["center_frame_shift_result"] = None
                    slot.data["center_negative_scale_result"] = None
                    slot.data["frame_schedule"] = frame_schedule
                if configured_reset_teleport:
                    slot.data["particle_buffer"].reset_from_frame(frame_input)
                    runtime_state.mark_frame_reset(
                        frame_input,
                        "configured_teleport",
                    )
                else:
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
                    elif int(world.generation) > 0 and slot.data.get("bone_static") is not None:
                        bone_result, writeback_plan = make_mc2_bone_result(
                            spec=spec,
                            slot=slot,
                            candidate=candidate,
                            frame=frame_input.frame,
                            world_generation=world.generation,
                        )
                        public_results.append(bone_result)
                        staged_writeback_plans[slot.slot_id] = writeback_plan
        pruned = _prune_stale_mc2_slots(world, active_slot_ids)
        if int(world.generation) > 0:
            published_results = publish_mc2_result_transaction(world, public_results)
            for slot_id, writeback_plan in staged_writeback_plans.items():
                slot = world.solver_slots.get(slot_id)
                if slot is not None:
                    slot.data["writeback_plan"] = writeback_plan
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
