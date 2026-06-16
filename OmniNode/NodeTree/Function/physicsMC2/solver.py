"""MeshCloth Python 求解调度。

本模块只处理单帧内的 predict / constraint / collision / motion / post 顺序。
节点入口负责 Blender cache、跳帧、reset、碰撞快照收集和 shape key 写回。
"""

import time

import bpy
import numpy as np

from . import blender_io, collision, constraints, math_utils, native_bridge, params, state as mc2_state
from .constants import MC2SystemConstants


def _add_timing(timing: dict | None, stage: str, seconds: float) -> None:
    if timing is None:
        return
    stages = timing.setdefault("stages", {})
    stages[stage] = stages.get(stage, 0.0) + max(float(seconds), 0.0)


def solve_meshcloth(
    state: dict,
    obj: bpy.types.Object,
    scene: bpy.types.Scene,
    substeps: int,
    iterations: int,
    gravity_dir,
    gravity_power: float,
    damping: float,
    distance_stiffness: float,
    bend_stiffness: float,
    max_distance: float,
    backstop_radius: float,
    backstop_distance: float,
    collider_friction: float,
    timing: dict | None = None,
    colliders: list[dict] | None = None,
) -> dict:
    stage_start = time.perf_counter() if timing is not None else None
    positions = np.ascontiguousarray(state["next_positions"], dtype=np.float32)
    old_positions = np.ascontiguousarray(state["old_positions"], dtype=np.float32)
    base_positions = np.ascontiguousarray(state["base_positions"], dtype=np.float32)
    base_normals = np.ascontiguousarray(state["base_normals"], dtype=np.float32)
    attributes = np.ascontiguousarray(state["attributes"], dtype=np.uint8)
    depths = np.ascontiguousarray(state["depths"], dtype=np.float32)
    friction = np.ascontiguousarray(state["friction"], dtype=np.float32)
    static_friction = np.ascontiguousarray(state["static_friction"], dtype=np.float32)
    velocity_positions = np.ascontiguousarray(state["velocity_positions"], dtype=np.float32)
    velocity = np.ascontiguousarray(state["velocity"], dtype=np.float32)
    real_velocity = np.ascontiguousarray(state["real_velocity"], dtype=np.float32)
    inv_masses = mc2_state.calc_inverse_masses(attributes, depths, friction)
    collision_radii = np.ascontiguousarray(state["collision_radii"], dtype=np.float32)
    collided_by_groups = math_utils.clamp_group_mask(state.get("collided_by_groups", 0))
    collision_normals = np.ascontiguousarray(state["collision_normals"], dtype=np.float32)
    collision_normals.fill(0.0)
    movable = inv_masses > MC2SystemConstants.EPSILON
    fixed = ~movable

    frame_dt = blender_io.scene_delta_time(scene)
    substep_count = max(1, min(16, int(substeps)))
    iteration_count = max(0, min(64, int(iterations)))
    step_dt = frame_dt / substep_count if substep_count > 0 else frame_dt
    gravity = math_utils.world_gravity(gravity_dir) * max(float(gravity_power), 0.0)
    substep_damping = blender_io.substep_damping(damping, substep_count)
    world_scale = math_utils.matrix_scale_radius(obj.matrix_world)

    stiffness_depths = np.clip(np.ascontiguousarray(depths, dtype=np.float32), 0.0, 1.0)
    distance_stiffness_param = params.scalar_param(max(0.0, min(1.0, float(distance_stiffness))))
    bend_stiffness_param = params.scalar_param(max(0.0, min(1.0, float(bend_stiffness))))
    distance_stiffness_values = np.clip(params.sample_param(distance_stiffness_param, stiffness_depths), 0.0, 1.0)
    bend_stiffness_values = np.clip(params.sample_param(bend_stiffness_param, stiffness_depths), 0.0, 1.0)

    max_distance_param = params.scalar_param(max(float(max_distance), 0.0))
    backstop_radius_param = params.scalar_param(max(float(backstop_radius), 0.0))
    backstop_distance_param = params.scalar_param(max(float(backstop_distance), 0.0))
    tether_compression_param = params.scalar_param(MC2SystemConstants.TETHER_COMPRESSION_LIMIT)
    tether_stretch_param = params.scalar_param(MC2SystemConstants.TETHER_STRETCH_LIMIT)
    motion_stiffness_param = params.scalar_param(1.0)
    collider_friction_param = params.scalar_param(max(0.0, min(0.5, float(collider_friction))))
    dynamic_friction = (
        float(collider_friction_param["value"])
        * MC2SystemConstants.COLLIDER_COLLISION_DYNAMIC_FRICTION_RATIO
    )
    static_friction_speed = (
        float(collider_friction_param["value"])
        * MC2SystemConstants.COLLIDER_COLLISION_STATIC_FRICTION_RATIO
        * max(float(world_scale), 0.0)
    )

    has_collision = bool(colliders) and bool(collided_by_groups) and bool(
        np.any(collision_radii > MC2SystemConstants.EPSILON)
    )
    if timing is not None:
        _add_timing(timing, "solve_setup", time.perf_counter() - stage_start)

    for _substep in range(substep_count):
        stage_start = time.perf_counter() if timing is not None else None
        inv_masses = mc2_state.calc_inverse_masses(attributes, depths, friction)
        movable = inv_masses > MC2SystemConstants.EPSILON
        fixed = ~movable
        velocity_positions = old_positions.copy()
        collision_normals.fill(0.0)
        if step_dt > MC2SystemConstants.EPSILON:
            velocity[movable] *= 1.0 - substep_damping
            velocity[movable] += gravity * step_dt
            positions[movable] = old_positions[movable] + velocity[movable] * step_dt
        if timing is not None:
            _add_timing(timing, "predict", time.perf_counter() - stage_start)

        if bool(np.any(fixed)):
            stage_start = time.perf_counter() if timing is not None else None
            positions[fixed] = base_positions[fixed]
            velocity_positions[fixed] = base_positions[fixed]
            if timing is not None:
                _add_timing(timing, "pin", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        constraints.project_tether(
            positions,
            inv_masses,
            state["root_indices"],
            state["tether_rest_lengths"],
            1.0,
            float(tether_compression_param["value"]),
            float(tether_stretch_param["value"]),
            velocity_positions,
        )
        if timing is not None:
            _add_timing(timing, "tether", time.perf_counter() - stage_start)

        if has_collision and iteration_count == 0:
            stage_start = time.perf_counter() if timing is not None else None
            collision.project_collisions(
                positions,
                base_positions,
                inv_masses,
                collision_radii,
                collided_by_groups,
                colliders,
                obj,
                collision_normals,
                friction,
            )
            if timing is not None:
                _add_timing(timing, "collision", time.perf_counter() - stage_start)
            inv_masses = mc2_state.calc_inverse_masses(attributes, depths, friction)

        for _iteration in range(iteration_count):
            stage_start = time.perf_counter() if timing is not None else None
            constraints.project_neighbor_constraints(
                positions,
                inv_masses,
                state["distance_start"],
                state["distance_count"],
                state["distance_data"],
                state["distance_rest"],
                distance_stiffness_values,
                velocity_positions,
                MC2SystemConstants.DISTANCE_VELOCITY_ATTENUATION,
            )
            if timing is not None:
                _add_timing(timing, "distance", time.perf_counter() - stage_start)

            stage_start = time.perf_counter() if timing is not None else None
            constraints.project_neighbor_constraints(
                positions,
                inv_masses,
                state["bend_distance_start"],
                state["bend_distance_count"],
                state["bend_distance_data"],
                state["bend_distance_neighbor_rest"],
                bend_stiffness_values,
                velocity_positions,
                MC2SystemConstants.DISTANCE_VELOCITY_ATTENUATION,
            )
            if timing is not None:
                _add_timing(timing, "bend", time.perf_counter() - stage_start)

            if has_collision:
                stage_start = time.perf_counter() if timing is not None else None
                collision.project_collisions(
                    positions,
                    base_positions,
                    inv_masses,
                    collision_radii,
                    collided_by_groups,
                    colliders,
                    obj,
                    collision_normals,
                    friction,
                )
                if timing is not None:
                    _add_timing(timing, "collision", time.perf_counter() - stage_start)
                inv_masses = mc2_state.calc_inverse_masses(attributes, depths, friction)

            stage_start = time.perf_counter() if timing is not None else None
            constraints.project_neighbor_constraints(
                positions,
                inv_masses,
                state["distance_start"],
                state["distance_count"],
                state["distance_data"],
                state["distance_rest"],
                distance_stiffness_values,
                velocity_positions,
                MC2SystemConstants.DISTANCE_VELOCITY_ATTENUATION,
            )
            if timing is not None:
                _add_timing(timing, "distance_after_collision", time.perf_counter() - stage_start)

            if bool(np.any(fixed)):
                stage_start = time.perf_counter() if timing is not None else None
                positions[fixed] = base_positions[fixed]
                velocity_positions[fixed] = base_positions[fixed]
                if timing is not None:
                    _add_timing(timing, "pin", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        constraints.project_motion_constraint(
            positions,
            base_positions,
            base_normals,
            inv_masses,
            depths,
            max_distance_param,
            motion_stiffness_param,
            backstop_radius_param,
            backstop_distance_param,
            world_scale,
            velocity_positions,
        )
        if timing is not None:
            _add_timing(timing, "motion", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        constraints.apply_post_step(
            positions,
            old_positions,
            velocity_positions,
            velocity,
            real_velocity,
            friction,
            static_friction,
            collision_normals,
            inv_masses,
            step_dt,
            dynamic_friction,
            static_friction_speed,
            MC2SystemConstants.PARTICLE_SPEED_LIMIT * max(float(world_scale), 0.0),
        )
        if bool(np.any(fixed)):
            positions[fixed] = base_positions[fixed]
            old_positions[fixed] = base_positions[fixed]
            velocity_positions[fixed] = base_positions[fixed]
            velocity[fixed] = 0.0
            real_velocity[fixed] = 0.0
            friction[fixed] = 0.0
            static_friction[fixed] = 0.0
        if timing is not None:
            _add_timing(timing, "post", time.perf_counter() - stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    next_state = dict(state)
    next_state["frame_delta_time"] = float(frame_dt)
    next_state["step_delta_time"] = float(step_dt)
    next_state["substep_damping"] = float(substep_damping)
    next_state["next_positions"] = np.ascontiguousarray(positions, dtype=np.float32)
    next_state["old_positions"] = np.ascontiguousarray(old_positions, dtype=np.float32)
    next_state["display_positions"] = np.ascontiguousarray(positions.copy(), dtype=np.float32)
    next_state["velocity_positions"] = np.ascontiguousarray(velocity_positions, dtype=np.float32)
    next_state["velocity"] = np.ascontiguousarray(velocity, dtype=np.float32)
    next_state["real_velocity"] = np.ascontiguousarray(real_velocity, dtype=np.float32)
    next_state["friction"] = np.ascontiguousarray(friction, dtype=np.float32)
    next_state["static_friction"] = np.ascontiguousarray(static_friction, dtype=np.float32)
    next_state["collision_normals"] = np.ascontiguousarray(collision_normals, dtype=np.float32)
    next_state["inv_masses"] = np.ascontiguousarray(inv_masses, dtype=np.float32)
    next_state["param_slots"] = dict(next_state.get("param_slots") or {})
    next_state["param_slots"]["distance_stiffness"] = distance_stiffness_param
    next_state["param_slots"]["bend_stiffness"] = bend_stiffness_param
    next_state["param_slots"]["max_distance"] = max_distance_param
    next_state["param_slots"]["tether_compression"] = tether_compression_param
    next_state["param_slots"]["tether_stretch"] = tether_stretch_param
    next_state["param_slots"]["motion_stiffness"] = motion_stiffness_param
    next_state["param_slots"]["damping"] = params.scalar_param(damping)
    next_state["param_slots"]["backstop_radius"] = backstop_radius_param
    next_state["param_slots"]["backstop_distance"] = backstop_distance_param
    next_state["param_slots"]["collider_friction"] = collider_friction_param

    extension_slots = dict(next_state.get("extension_slots") or {})
    native_slot = dict(extension_slots.get("native") or {})
    native_slot["abi_view"] = native_bridge.build_abi_view(next_state, obj, colliders)
    native_slot["collider_arrays"] = native_slot["abi_view"]["colliders"]
    extension_slots["native"] = native_slot
    next_state["extension_slots"] = extension_slots
    if timing is not None:
        _add_timing(timing, "post_pack", time.perf_counter() - stage_start)
    return next_state
