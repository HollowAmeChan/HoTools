"""MeshCloth Python 求解调度。

本模块负责单帧内的 predict/pin/tether/distance/bend/collision/motion/post 顺序。
节点入口仍负责 cache、跳帧、reset、碰撞快照收集和 shape key 写回。
"""

import time

import bpy
import numpy as np

from . import blender_io, collision, constraints, math_utils, params, state as mc2_state
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
    timing: dict | None = None,
    colliders: list[dict] | None = None,
) -> dict:
    stage_start = time.perf_counter() if timing is not None else None
    positions = np.ascontiguousarray(state["next_positions"], dtype=np.float32)
    old_positions = np.ascontiguousarray(state["old_positions"], dtype=np.float32)
    base_positions = np.ascontiguousarray(state["base_positions"], dtype=np.float32)
    attributes = np.ascontiguousarray(state["attributes"], dtype=np.uint8)
    depths = np.ascontiguousarray(state["depths"], dtype=np.float32)
    friction = np.ascontiguousarray(state["friction"], dtype=np.float32)
    inv_masses = mc2_state.calc_inverse_masses(attributes, depths, friction)
    collision_radii = np.ascontiguousarray(state["collision_radii"], dtype=np.float32)
    collided_by_groups = math_utils.clamp_group_mask(state.get("collided_by_groups", 0))
    collision_normals = np.zeros_like(positions, dtype=np.float32)
    movable = inv_masses > MC2SystemConstants.EPSILON
    fixed = ~movable

    dt = blender_io.scene_delta_time(scene)
    substep_count = max(1, min(16, int(substeps)))
    iteration_count = max(0, min(64, int(iterations)))
    step_dt = dt / substep_count if substep_count > 0 else dt
    gravity = math_utils.world_gravity(gravity_dir) * max(float(gravity_power), 0.0)
    substep_damping = blender_io.substep_damping(damping, substep_count)
    distance_stiffness = max(0.0, min(1.0, float(distance_stiffness)))
    bend_stiffness = max(0.0, min(1.0, float(bend_stiffness)))
    max_distance_param = params.scalar_param(max(float(max_distance), 0.0))
    tether_compression_param = params.scalar_param(MC2SystemConstants.TETHER_COMPRESSION_LIMIT)
    tether_stretch_param = params.scalar_param(MC2SystemConstants.TETHER_STRETCH_LIMIT)
    motion_stiffness_param = params.scalar_param(1.0)
    world_scale = math_utils.matrix_scale_radius(obj.matrix_world)
    has_collision = bool(colliders) and bool(collided_by_groups) and bool(
        np.any(collision_radii > MC2SystemConstants.EPSILON)
    )
    if timing is not None:
        _add_timing(timing, "solve_setup", time.perf_counter() - stage_start)

    for _ in range(substep_count):
        stage_start = time.perf_counter() if timing is not None else None
        previous = positions.copy()
        # 帧长来自 Blender render.fps/fps_base；阻尼按场景帧输入，在子步前换算。
        inertia = (positions - old_positions) * (1.0 - substep_damping)
        positions[movable] += inertia[movable] + gravity * (step_dt * step_dt)
        old_positions = previous
        if timing is not None:
            _add_timing(timing, "predict", time.perf_counter() - stage_start)

        if bool(np.any(fixed)):
            stage_start = time.perf_counter() if timing is not None else None
            positions[fixed] = base_positions[fixed]
            old_positions[fixed] = base_positions[fixed]
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
        )
        if timing is not None:
            _add_timing(timing, "tether", time.perf_counter() - stage_start)

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
            )
            if timing is not None:
                _add_timing(timing, "collision", time.perf_counter() - stage_start)

        for _iteration in range(iteration_count):
            stage_start = time.perf_counter() if timing is not None else None
            constraints.project_neighbor_constraints(
                positions,
                inv_masses,
                state["distance_start"],
                state["distance_count"],
                state["distance_data"],
                state["distance_rest"],
                distance_stiffness,
            )
            if timing is not None:
                _add_timing(timing, "distance", time.perf_counter() - stage_start)

            stage_start = time.perf_counter() if timing is not None else None
            constraints.project_neighbor_constraints(
                positions,
                inv_masses,
                state["bend_start"],
                state["bend_count"],
                state["bend_data"],
                state["bend_neighbor_rest"],
                bend_stiffness,
            )
            if timing is not None:
                _add_timing(timing, "bend", time.perf_counter() - stage_start)

            if bool(np.any(fixed)):
                stage_start = time.perf_counter() if timing is not None else None
                positions[fixed] = base_positions[fixed]
                old_positions[fixed] = base_positions[fixed]
                if timing is not None:
                    _add_timing(timing, "pin", time.perf_counter() - stage_start)

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
                )
                if timing is not None:
                    _add_timing(timing, "collision", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        constraints.project_motion_constraint(
            positions,
            base_positions,
            inv_masses,
            depths,
            max_distance_param,
            motion_stiffness_param,
            world_scale,
        )
        if timing is not None:
            _add_timing(timing, "motion", time.perf_counter() - stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    velocity_positions = np.ascontiguousarray(positions - old_positions, dtype=np.float32)
    velocity = (
        velocity_positions / step_dt
        if step_dt > MC2SystemConstants.EPSILON
        else np.zeros_like(positions)
    )
    next_state = dict(state)
    next_state["frame_delta_time"] = float(dt)
    next_state["step_delta_time"] = float(step_dt)
    next_state["substep_damping"] = float(substep_damping)
    next_state["next_positions"] = np.ascontiguousarray(positions, dtype=np.float32)
    next_state["old_positions"] = np.ascontiguousarray(old_positions, dtype=np.float32)
    next_state["display_positions"] = np.ascontiguousarray(positions.copy(), dtype=np.float32)
    next_state["velocity_positions"] = velocity_positions
    next_state["velocity"] = np.ascontiguousarray(velocity, dtype=np.float32)
    next_state["real_velocity"] = np.ascontiguousarray(velocity, dtype=np.float32)
    next_state["collision_normals"] = np.ascontiguousarray(collision_normals, dtype=np.float32)
    next_state["inv_masses"] = np.ascontiguousarray(inv_masses, dtype=np.float32)
    next_state["param_slots"] = dict(next_state.get("param_slots") or {})
    next_state["param_slots"]["distance_stiffness"] = params.scalar_param(distance_stiffness)
    next_state["param_slots"]["bend_stiffness"] = params.scalar_param(bend_stiffness)
    next_state["param_slots"]["max_distance"] = max_distance_param
    next_state["param_slots"]["tether_compression"] = tether_compression_param
    next_state["param_slots"]["tether_stretch"] = tether_stretch_param
    next_state["param_slots"]["motion_stiffness"] = motion_stiffness_param
    next_state["param_slots"]["damping"] = params.scalar_param(damping)
    next_state["param_slots"]["backstop_radius"] = params.scalar_param(10.0)
    next_state["param_slots"]["backstop_distance"] = params.scalar_param(0.0)
    next_state["param_slots"]["collider_friction"] = params.scalar_param(0.05)

    extension_slots = dict(next_state.get("extension_slots") or {})
    native_slot = dict(extension_slots.get("native") or {})
    native_slot["collider_arrays"] = collision.collider_arrays_for_native(next_state, obj, colliders)
    extension_slots["native"] = native_slot
    next_state["extension_slots"] = extension_slots
    if timing is not None:
        _add_timing(timing, "post", time.perf_counter() - stage_start)
    return next_state
