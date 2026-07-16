"""统一 MC2 模拟步的 topology/slot 框架。"""

from __future__ import annotations

from dataclasses import replace
import math

from ..types import PhysicsWorldCache
from .declaration import MC2_SOLVER_DECLARATION
from .debug import capture_requested_mc2_debug
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
from .frame_state import MC2FrameInputSpec, plan_mc2_frame_sync
from .interaction_scope import build_mc2_interaction_scope
from .native import (
    MC2_INTERACTION_RESOURCE_KEY,
    MC2_STATIC_CHANGE_ALL,
    MC2_STATIC_CHANGE_CONFIG,
    MC2_STATIC_CHANGE_GEOMETRY,
    MC2_STATIC_CHANGE_SURFACE,
    MC2_STATIC_CHANGE_TOPOLOGY,
    MC2_STATIC_CHANGE_SOURCE,
    MC2NativeInteractionV0,
)
from .results import (
    make_mc2_bone_result,
    make_mc2_mesh_result,
    make_mc2_stats_result,
    merge_mc2_bone_results,
    publish_mc2_result_transaction,
)
from .scheduler import MC2TimeSchedulerState
from .specs import build_mc2_task_specs
from .state import MC2SlotRuntimeState
from .topology import build_mc2_topology_spec, static_input_fingerprint_for_task


MC2_FRAMEWORK_STATUS = (
    "MC2 context V0 已接入 Center/Move inertia、Gravity、Pin、Distance、Bending 数值 step；"
    "Mesh/Bone/stats 公共结果事务与统一writeback已接入"
)


def _ensure_mc2_interaction(world: PhysicsWorldCache) -> MC2NativeInteractionV0:
    interaction = world.backend_resources.get(MC2_INTERACTION_RESOURCE_KEY)
    if interaction is None or getattr(interaction, "disposed", False):
        interaction = MC2NativeInteractionV0()
        world.backend_resources[MC2_INTERACTION_RESOURCE_KEY] = interaction
    if not isinstance(interaction, MC2NativeInteractionV0):
        raise RuntimeError("MC2 interaction resource key is occupied by another owner")
    return interaction


def _dispose_mc2_slot(slot, reason: str) -> None:
    native_context = slot.data.get("native_context")
    if native_context is not None and hasattr(native_context, "dispose"):
        native_context.dispose()
    state = slot.data.get("runtime_state")
    if isinstance(state, MC2SlotRuntimeState):
        state.dispose(reason)


def _slot_debug_snapshot(slot) -> dict:
    topology = slot.data.get("topology")
    state = slot.data.get("runtime_state")
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
        "static_input_fingerprint": (
            slot.data["static_input_fingerprint"].debug_dict()
            if hasattr(slot.data.get("static_input_fingerprint"), "debug_dict")
            else None
        ),
        "last_static_change_mask": int(slot.data.get("last_static_change_mask", 0)),
        "runtime_state": state.debug_dict() if hasattr(state, "debug_dict") else None,
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
    reset_reason: str,
    mesh_static=None,
    bone_static=None,
    static_input_fingerprint=None,
    static_change_mask: int = MC2_STATIC_CHANGE_ALL,
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
            "mesh_static": mesh_static,
            "bone_static": bone_static,
            "static_input_fingerprint": static_input_fingerprint,
            "last_static_change_mask": int(static_change_mask),
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
    bone_static = slot.data.get("bone_static")
    active_static = mesh_static if mesh_static is not None else bone_static
    frame_pose = frame_input.center_frame_pose
    center_state = slot.data.get("center_state")
    if active_static is None or frame_pose is None:
        return None
    if not isinstance(center_state, MC2CenterPersistentState):
        raise RuntimeError("MC2 slot is missing Center persistent state")
    if center_state.center_static_signature != active_static.center.center_static_signature:
        raise RuntimeError("MC2 Center static identity changed without slot rebuild")
    if frame_input.native_producer_kind != "host":
        native_context = slot.data.get("native_context")
        if native_context is None:
            raise RuntimeError("native-produced MC2 frame has no live context")
        return native_context.derived_center_pose()
    return derive_mc2_center_world_pose(
        active_static.center,
        frame_pose,
        world_positions=frame_input.world_positions,
        world_rotations_xyzw=frame_input.world_rotations_xyzw,
        vertex_bind_pose_rotations=active_static.finalizer.vertex_bind_pose_rotations,
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
    static_change_mask: int = MC2_STATIC_CHANGE_ALL,
) -> str:
    slot = world.solver_slots.get(spec.task_id)
    if slot is None:
        return "created"
    state = slot.data.get("runtime_state")
    if not isinstance(state, MC2SlotRuntimeState):
        return "runtime_state_missing"
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
    if static_change_mask & MC2_STATIC_CHANGE_TOPOLOGY:
        return "topology_changed"
    if static_change_mask:
        return "static_input_changed"
    if state.topology_signature != topology.topology_signature:
        return "topology_changed"
    return ""


def _classify_stored_static_fingerprint(previous, current) -> int:
    if previous is None or not hasattr(previous, "native_values"):
        return MC2_STATIC_CHANGE_ALL
    mask = 0
    if previous.topology != current.topology:
        mask |= MC2_STATIC_CHANGE_TOPOLOGY
    if previous.geometry != current.geometry:
        mask |= MC2_STATIC_CHANGE_GEOMETRY
    if previous.surface != current.surface:
        mask |= MC2_STATIC_CHANGE_SURFACE
    if previous.config != current.config:
        mask |= MC2_STATIC_CHANGE_CONFIG
    return mask


def _sync_mc2_slot(
    world: PhysicsWorldCache,
    spec,
    settings: MC2SolverSettingsSpec,
    topology,
    effective,
    mesh_static,
    bone_static,
    static_input_fingerprint,
    static_change_mask,
    staged_native_context,
) -> tuple[str, object]:
    rebuild_reason = _mc2_slot_rebuild_reason(
        world,
        spec,
        topology,
        static_change_mask,
    )
    slot = world.ensure_solver_slot(spec.task_id, MC2_SLOT_KIND)
    previous_state = slot.data.get("runtime_state")

    if rebuild_reason:
        if slot.data:
            slot.dispose(rebuild_reason)
        _install_mc2_slot(
            slot,
            world=world,
            spec=spec,
            topology=topology,
            effective_parameters=effective,
            settings=settings,
            mesh_static=mesh_static,
            bone_static=bone_static,
            static_input_fingerprint=static_input_fingerprint,
            static_change_mask=static_change_mask,
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
    slot.data["static_input_fingerprint"] = static_input_fingerprint
    slot.data["last_static_change_mask"] = int(static_change_mask)
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
            static_input_fingerprint = static_input_fingerprint_for_task(spec)
            existing_slot = world.solver_slots.get(spec.task_id)
            existing_native_context = (
                existing_slot.data.get("native_context")
                if existing_slot is not None
                else None
            )
            static_change_mask = MC2_STATIC_CHANGE_ALL
            if (
                existing_native_context is not None
                and not bool(getattr(existing_native_context, "disposed", True))
            ):
                static_change_mask = existing_native_context.classify_static_fingerprint(
                    static_input_fingerprint
                )
            elif existing_slot is not None:
                static_change_mask = _classify_stored_static_fingerprint(
                    existing_slot.data.get("static_input_fingerprint"),
                    static_input_fingerprint,
                )
            topology = None
            if (
                existing_slot is not None
                and existing_slot.kind == MC2_SLOT_KIND
                and existing_slot.world_generation == world.generation
                and not (static_change_mask & MC2_STATIC_CHANGE_SOURCE)
            ):
                topology = existing_slot.data.get("topology")
            if topology is None:
                topology = build_mc2_topology_spec(spec)
            effective = make_mc2_runtime_parameters(spec.profile, spec.setup_options)
            frame_input = frame_inputs.get(spec.task_id)
            if frame_input is not None:
                _validate_mc2_frame_input(spec, topology, frame_input)
            mesh_static_supported = (
                spec.setup_type == "mesh_cloth"
                and all(source.resolved for source in topology.sources)
                and topology.particle_count > 0
            )
            bone_static_supported = (
                spec.setup_type in ("bone_cloth", "bone_spring")
                and all(source.resolved for source in topology.sources)
                and topology.particle_count > 0
            )
            rebuild_reason = _mc2_slot_rebuild_reason(
                world,
                spec,
                topology,
                static_change_mask,
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
                    staged_native_context.update_static_fingerprint(
                        static_input_fingerprint
                    )
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
                    mesh_static,
                    bone_static,
                    static_input_fingerprint,
                    static_change_mask,
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
    bone_targets: dict[tuple[int, int], set[str]] = {}
    for item in prepared:
        spec = item[0]
        bone_static = item[4]
        if bone_static is None:
            existing_slot = world.solver_slots.get(spec.task_id)
            if existing_slot is not None:
                bone_static = existing_slot.data.get("bone_static")
        if bone_static is None:
            continue
        first_source = spec.sources[0]
        armature = first_source.get("armature") if isinstance(first_source, dict) else None
        if armature is None and isinstance(first_source, tuple) and len(first_source) == 2:
            armature = first_source[0]
        target_key = (int(armature.as_pointer()), int(armature.data.as_pointer()))
        identities = set(bone_static.final_proxy.vertex_identities)
        overlap = bone_targets.setdefault(target_key, set()).intersection(identities)
        if overlap:
            for context in staged_native_contexts:
                context.dispose()
            raise ValueError(
                f"MC2 Bone components overlap on target bones: {sorted(overlap)!r}"
            )
        bone_targets[target_key].update(identities)
    counts = {"created": 0, "rebuilt": 0, "updated": 0, "reused": 0}
    active_slot_ids: list[str] = []
    public_results: list[dict] = []
    stats_slots: list[dict] = []
    bone_result_entries: list[tuple[dict, dict]] = []
    writeback_result_count = 0
    world.acquire_write(MC2_SOLVER_ID)
    try:
        runtime_items = []
        for (
            spec,
            topology,
            effective,
            mesh_static,
            bone_static,
            static_input_fingerprint,
            static_change_mask,
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
                mesh_static,
                bone_static,
                static_input_fingerprint,
                static_change_mask,
                staged_native_context,
            )
            if staged_native_context in staged_native_contexts:
                staged_native_contexts.remove(staged_native_context)
            counts[action] += 1
            active_slot_ids.append(slot.slot_id)
            runtime_items.append({
                "spec": spec,
                "topology": topology,
                "slot": slot,
                "collider_frame": collider_frame,
                "staged_native_frame_applied": staged_native_frame_applied,
                "frame_input": frame_inputs.get(spec.task_id),
                "substeps": (),
            })

        interaction_scope = build_mc2_interaction_scope(
            [item["spec"] for item in runtime_items]
        )
        interaction_participants = {
            participant.task_id: participant
            for participant in interaction_scope.participants
        }

        for item in runtime_items:
            spec = item["spec"]
            slot = item["slot"]
            frame_input = item["frame_input"]
            if frame_input is None:
                continue
            runtime_state = slot.data["runtime_state"]
            native_context = slot.data.get("native_context")
            frame_plan = plan_mc2_frame_sync(
                runtime_state,
                frame_input,
                user_reset=bool(user_reset),
            )
            center_state = slot.data.get("center_state")
            frame_pose = frame_input.center_frame_pose
            if frame_pose is not None and isinstance(
                center_state, MC2CenterPersistentState
            ):
                component_scale = tuple(frame_pose.component_world_scale)
                initial_scale = (
                    center_state.initial_scale
                    if center_state.initialized
                    else component_scale
                )
                frame_input = replace(
                    frame_input,
                    scale_ratio=max(
                        math.sqrt(sum(value * value for value in component_scale))
                        / math.sqrt(sum(value * value for value in initial_scale)),
                        1.0e-6,
                    ),
                    negative_scale_sign=(
                        -1.0 if any(value < 0.0 for value in component_scale) else 1.0
                    ),
                )
                item["frame_input"] = frame_input
            if (
                native_context is not None
                and frame_plan.action != "same_frame"
                and not item["staged_native_frame_applied"]
            ):
                collider_frame = item["collider_frame"]
                if collider_frame is not None:
                    native_context.update_colliders(collider_frame)
                native_context.update_dynamic(frame_input)
            center_pose = _derive_slot_center_pose(slot, frame_input)
            center_action = None
            center_negative_scale_result = None
            center_frame_shift_result = None
            configured_reset_teleport = False
            staged_reset_center_state = None
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
                and not item["staged_native_frame_applied"]
            ):
                if frame_plan.action == "reset" or configured_reset_teleport:
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
                    item["substeps"] = tuple(
                        (
                            float(frame_schedule.simulation_delta_time),
                            update_index == frame_schedule.update_count - 1,
                            update_index,
                        )
                        for update_index in range(frame_schedule.update_count)
                    )
                elif center_pose is None and dt > 0.0 and frame_plan.action != "reset":
                    item["substeps"] = ((dt, True, 0),)
            elif center_action in ("step", "pause"):
                raise RuntimeError("MC2 Center step requires a live native context")
            item.update({
                "runtime_state": runtime_state,
                "native_context": native_context,
                "frame_plan": frame_plan,
                "center_state": center_state,
                "center_pose": center_pose,
                "center_action": center_action,
                "center_negative_scale_result": center_negative_scale_result,
                "center_frame_shift_result": center_frame_shift_result,
                "configured_reset_teleport": configured_reset_teleport,
                "staged_reset_center_state": staged_reset_center_state,
                "frame_schedule": frame_schedule,
                "time_scheduler": time_scheduler,
                "center_step_result": None,
            })

        max_substeps = max(
            (len(item["substeps"]) for item in runtime_items),
            default=0,
        )
        interaction = _ensure_mc2_interaction(world) if max_substeps else None
        for update_index in range(max_substeps):
            batches = {}
            for item in runtime_items:
                if update_index >= len(item["substeps"]):
                    continue
                substep_dt, is_final_substep, local_update_index = item["substeps"][update_index]
                batches.setdefault((substep_dt, is_final_substep), []).append(
                    (item, local_update_index)
                )
            for (substep_dt, is_final_substep), batch in batches.items():
                contexts = []
                primary_group_bits = []
                collided_by_groups = []
                for item, local_update_index in batch:
                    native_context = item["native_context"]
                    if item["center_action"] == "step":
                        frame_interpolation = item["time_scheduler"].advance_step(
                            local_update_index
                        )
                        if local_update_index == 0:
                            step_center_state = (
                                item["staged_reset_center_state"]
                                if item["configured_reset_teleport"]
                                else item["center_state"]
                            )
                            center_step_input = step_center_state.make_step_input(
                                item["frame_input"].center_frame_pose,
                                item["center_pose"],
                                simulation_delta_time=substep_dt,
                                frame_interpolation=frame_interpolation,
                                frame_shift=(
                                    None
                                    if item["configured_reset_teleport"]
                                    else item["center_frame_shift_result"]
                                ),
                            )
                            native_context.update_center_dynamic(center_step_input)
                        else:
                            native_context.update_step_interpolation(frame_interpolation)
                    participant = interaction_participants.get(item["spec"].task_id)
                    contexts.append(native_context)
                    primary_group_bits.append(
                        participant.primary_group_bit if participant is not None else 1
                    )
                    collided_by_groups.append(
                        participant.collided_by_groups if participant is not None else 0
                    )
                interaction.set_debug_scope((
                    {
                        "task_id": str(item["spec"].task_id),
                        "slot_id": str(item["slot"].slot_id),
                        "vertex_count": int(item["native_context"].vertex_count),
                        "primary_group_bit": int(primary_group_bits[index]),
                        "collided_by_groups": int(collided_by_groups[index]),
                    }
                    for index, (item, _local_update_index) in enumerate(batch)
                ))
                interaction.step_group(
                    contexts,
                    primary_group_bits,
                    collided_by_groups,
                    substep_dt,
                    is_final_substep=is_final_substep,
                )

        for item in runtime_items:
            if item.get("center_action") == "step" and item["substeps"]:
                item["center_step_result"] = item["native_context"].read_center_step()

        for item in runtime_items:
            spec = item["spec"]
            topology = item["topology"]
            slot = item["slot"]
            frame_input = item["frame_input"]
            if frame_input is not None:
                runtime_state = item["runtime_state"]
                native_context = item["native_context"]
                frame_plan = item["frame_plan"]
                center_state = item["center_state"]
                center_pose = item["center_pose"]
                center_action = item["center_action"]
                center_negative_scale_result = item["center_negative_scale_result"]
                center_frame_shift_result = item["center_frame_shift_result"]
                configured_reset_teleport = item["configured_reset_teleport"]
                staged_reset_center_state = item["staged_reset_center_state"]
                center_step_result = item["center_step_result"]
                frame_schedule = item["frame_schedule"]
                time_scheduler = item["time_scheduler"]
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
                        native_positions, native_rotations = native_context.read_bone_output()
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
                    runtime_state.mark_frame_reset(
                        frame_input,
                        "configured_teleport",
                    )
                elif frame_plan.action == "reset":
                    runtime_state.mark_frame_reset(
                        frame_input,
                        frame_plan.reset_reason,
                    )
                elif frame_plan.action == "updated":
                    runtime_state.mark_frame_update(frame_input)
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
                        bone_result_entries.append((bone_result, writeback_plan))
            native_context = slot.data.get("native_context")
            native_info = (
                native_context.inspect()
                if native_context is not None and hasattr(native_context, "inspect")
                else {}
            )
            stats_slots.append({
                "slot_id": slot.slot_id,
                "setup_type": spec.setup_type,
                "native_schema": native_info.get("schema", ""),
                "native_available": (
                    native_context is not None and not native_info.get("released", False)
                ),
                "initialized": native_info.get("initialized", False),
                "particle_count": topology.particle_count,
                "native_frame": native_info.get("frame", 0),
                "native_generation": native_info.get("generation", 0),
                "reset_count": native_info.get("reset_count", 0),
                "step_count": native_info.get("step_count", 0),
                "parameter_revision": native_info.get("parameter_revision", 0),
                "dynamic_revision": native_info.get("dynamic_revision", 0),
                "collider_revision": native_info.get("collider_revision", 0),
                "self_contact_cache_count": native_info.get(
                    "self_contact_cache_count", 0
                ),
                "self_intersect_record_count": native_info.get(
                    "self_intersect_record_count", 0
                ),
                "debug_capture_count": native_info.get("debug_capture_count", 0),
                "debug_readback_count": native_info.get("debug_readback_count", 0),
            })
        capture_requested_mc2_debug(world, runtime_items, interaction)
        pruned = _prune_stale_mc2_slots(world, active_slot_ids)
        if int(world.generation) > 0:
            bone_results, staged_writeback_plans = merge_mc2_bone_results(
                bone_result_entries
            )
            public_results.extend(bone_results)
            writeback_result_count = len(public_results)
            public_results.append(make_mc2_stats_result(
                frame=world.frame_context.frame,
                generation=world.generation,
                slots=stats_slots,
                writeback_result_count=writeback_result_count,
            ))
            publish_mc2_result_transaction(world, public_results)
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
    return world, bool(writeback_result_count), status
