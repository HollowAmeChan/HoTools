"""MeshCloth Python 求解调度。

本模块只处理单帧内的 predict / constraint / collision / motion / post 顺序。
节点入口负责 Blender cache、跳帧、reset、碰撞快照收集和 GN delta 写回。
"""

import time

import bpy
import numpy as np

from . import baseline, blender_io, collision, constraints, inertia, math_utils, native_bridge, params, state as mc2_state
from .constants import MC2SystemConstants


def _add_timing(timing: dict | None, stage: str, seconds: float) -> None:
    if timing is None:
        return
    stages = timing.setdefault("stages", {})
    stages[stage] = stages.get(stage, 0.0) + max(float(seconds), 0.0)


def _zero_values_like(values: np.ndarray) -> np.ndarray:
    return np.zeros(len(values), dtype=np.float32)


def _component_slot(enabled: bool) -> dict:
    return params.scalar_param(1.0 if enabled else 0.0)


def _scalar_values_like(values: np.ndarray, value: float) -> np.ndarray:
    return np.full(len(values), float(value), dtype=np.float32)


def _substep_damping_values(frame_damping_values: np.ndarray, substeps: int) -> np.ndarray:
    values = np.clip(np.ascontiguousarray(frame_damping_values, dtype=np.float32), 0.0, 1.0)
    substep_count = max(1, int(substeps))
    return np.ascontiguousarray(1.0 - np.power(1.0 - values, 1.0 / float(substep_count)), dtype=np.float32)


# 运行顺序说明：
# 1. 先做一次输入整理、曲线采样、碰撞快照与惯性状态准备。
# 2. 每个 substep 内固定顺序为：
#    baseline -> predict -> pin/tether -> 初始碰撞 -> iteration 循环 -> motion -> post。
# 3. iteration 循环内固定顺序为：
#    distance -> angle -> bend -> collision -> distance_after_collision -> pin。
# 4. 最后统一打包 next_state / param_slots / native 扩展数据。
def solve_meshcloth(
    state: dict,
    obj: bpy.types.Object,
    scene: bpy.types.Scene,
    substeps: int,
    iterations: int,
    gravity_dir,
    gravity_power: float,
    damping: float,
    damping_curve,
    use_tether: bool,
    tether_compression: float,
    use_distance: bool,
    distance_stiffness: float,
    distance_stiffness_curve,
    use_bend: bool,
    bend_stiffness: float,
    bend_stiffness_curve,
    use_angle_restoration: bool,
    angle_restoration_stiffness: float,
    angle_restoration_stiffness_curve,
    angle_restoration_velocity_attenuation: float,
    angle_restoration_velocity_attenuation_curve,
    angle_restoration_gravity_falloff: float,
    use_angle_limit: bool,
    angle_limit: float,
    angle_limit_curve,
    angle_limit_stiffness: float,
    world_inertia: float,
    movement_inertia_smoothing: float,
    local_inertia: float,
    depth_inertia: float,
    centrifugal: float,
    movement_speed_limit: float,
    rotation_speed_limit: float,
    local_movement_speed_limit: float,
    local_rotation_speed_limit: float,
    particle_speed_limit: float,
    teleport_mode: int,
    teleport_distance: float,
    teleport_rotation: float,
    use_max_distance: bool,
    max_distance: float,
    max_distance_curve,
    use_backstop: bool,
    backstop_radius: float,
    backstop_distance: float,
    backstop_distance_curve,
    motion_stiffness: float,
    normal_axis: int,
    use_collider_collision: bool,
    collider_friction: float,
    collider_collision_mode: int,
    timing: dict | None = None,
    colliders: list[dict] | None = None,
) -> dict:
    stage_start = time.perf_counter() if timing is not None else None
    colliders = collision.with_previous_collider_pose(colliders, state.get("previous_collider_snapshot"))
    positions = np.ascontiguousarray(state["next_positions"], dtype=np.float32)
    old_positions = np.ascontiguousarray(state["old_positions"], dtype=np.float32)
    base_positions = np.ascontiguousarray(state["base_positions"], dtype=np.float32)
    base_normals = np.ascontiguousarray(state["base_normals"], dtype=np.float32)
    base_rotations = np.ascontiguousarray(state["base_rotations"], dtype=np.float32)
    step_basic_positions = np.ascontiguousarray(state["step_basic_positions"], dtype=np.float32)
    step_basic_rotations = np.ascontiguousarray(state["step_basic_rotations"], dtype=np.float32)
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
    world_scale = math_utils.matrix_scale_radius(obj.matrix_world)
    base_pose_mode = int(state.get("base_pose_proxy_ptr", 0) or 0) != 0
    normal_axis_value = max(0, min(5, int(normal_axis)))
    curve_stage_start = time.perf_counter() if timing is not None else None
    stiffness_depths = np.clip(np.ascontiguousarray(depths, dtype=np.float32), 0.0, 1.0)
    damping_param = params.curve_value_param(damping, damping_curve, minimum=0.0, maximum=1.0)
    distance_stiffness_param = (
        params.curve_value_param(distance_stiffness, distance_stiffness_curve, minimum=0.0, maximum=1.0)
        if use_distance
        else params.scalar_param(0.0)
    )
    bend_stiffness_param = (
        params.curve_value_param(bend_stiffness, bend_stiffness_curve, minimum=0.0, maximum=1.0)
        if use_bend
        else params.scalar_param(0.0)
    )
    angle_restoration_param = (
        params.curve_value_param(
            angle_restoration_stiffness,
            angle_restoration_stiffness_curve,
            minimum=0.0,
            maximum=1.0,
        )
        if use_angle_restoration
        else params.scalar_param(0.0)
    )
    angle_restoration_velocity_attenuation_param = (
        params.curve_value_param(
            angle_restoration_velocity_attenuation,
            angle_restoration_velocity_attenuation_curve,
            minimum=0.0,
            maximum=1.0,
        )
        if use_angle_restoration
        else params.scalar_param(0.0)
    )
    angle_restoration_gravity_falloff_param = (
        params.scalar_param(max(0.0, min(1.0, float(angle_restoration_gravity_falloff))))
        if use_angle_restoration
        else params.scalar_param(0.0)
    )
    angle_limit_param = (
        params.curve_value_param(angle_limit, angle_limit_curve, minimum=0.0, maximum=180.0)
        if use_angle_limit
        else params.scalar_param(0.0)
    )
    angle_limit_stiffness_value = max(0.0, min(1.0, float(angle_limit_stiffness)))
    angle_limit_stiffness_param = params.scalar_param(angle_limit_stiffness_value)
    max_distance_param = (
        params.curve_value_param(max_distance, max_distance_curve, minimum=0.0)
        if use_max_distance
        else params.scalar_param(0.0)
    )
    backstop_radius_param = params.float_param(backstop_radius, minimum=0.0) if use_backstop else params.scalar_param(0.0)
    backstop_distance_param = (
        params.curve_value_param(backstop_distance, backstop_distance_curve, minimum=0.0)
        if use_backstop
        else params.scalar_param(0.0)
    )
    if timing is not None:
        _add_timing(timing, "param_curves", time.perf_counter() - curve_stage_start)
    curve_stage_start = time.perf_counter() if timing is not None else None
    damping_values = np.clip(
        params.sample_param(damping_param, stiffness_depths) * float(MC2SystemConstants.DAMPING_SCALE),
        0.0,
        1.0,
    )
    substep_damping_values = _substep_damping_values(damping_values, substep_count)
    distance_stiffness_values = (
        np.clip(params.sample_param(distance_stiffness_param, stiffness_depths), 0.0, 1.0)
        if use_distance
        else _zero_values_like(stiffness_depths)
    )
    bend_stiffness_values = (
        np.clip(params.sample_param(bend_stiffness_param, stiffness_depths), 0.0, 1.0)
        if use_bend
        else _zero_values_like(stiffness_depths)
    )
    angle_restoration_values = (
        np.clip(params.sample_param(angle_restoration_param, stiffness_depths), 0.0, 1.0)
        if use_angle_restoration
        else _zero_values_like(stiffness_depths)
    )
    angle_restoration_velocity_attenuation_values = (
        np.clip(params.sample_param(angle_restoration_velocity_attenuation_param, stiffness_depths), 0.0, 1.0)
        if use_angle_restoration
        else _zero_values_like(stiffness_depths)
    )
    angle_restoration_gravity_falloff_values = (
        _scalar_values_like(stiffness_depths, angle_restoration_gravity_falloff_param["value"])
        if use_angle_restoration
        else _zero_values_like(stiffness_depths)
    )
    angle_limit_values = (
        np.clip(params.sample_param(angle_limit_param, stiffness_depths), 0.0, 180.0)
        if use_angle_limit
        else _zero_values_like(stiffness_depths)
    )
    if timing is not None:
        _add_timing(timing, "stiffness_curves", time.perf_counter() - curve_stage_start)

    world_inertia_param = params.scalar_param(max(0.0, min(1.0, float(world_inertia))))
    movement_inertia_smoothing_param = params.scalar_param(max(0.0, min(1.0, float(movement_inertia_smoothing))))
    local_inertia_param = params.scalar_param(max(0.0, min(1.0, float(local_inertia))))
    depth_inertia_param = params.scalar_param(max(0.0, min(1.0, float(depth_inertia))))
    centrifugal_param = params.scalar_param(max(0.0, min(1.0, float(centrifugal))))
    movement_speed_limit_value = float(movement_speed_limit)
    rotation_speed_limit_value = float(rotation_speed_limit)
    local_movement_speed_limit_value = float(local_movement_speed_limit)
    local_rotation_speed_limit_value = float(local_rotation_speed_limit)
    particle_speed_limit_value = float(particle_speed_limit)
    movement_speed_limit_param = params.scalar_param(movement_speed_limit_value)
    rotation_speed_limit_param = params.scalar_param(rotation_speed_limit_value)
    local_movement_speed_limit_param = params.scalar_param(local_movement_speed_limit_value)
    local_rotation_speed_limit_param = params.scalar_param(local_rotation_speed_limit_value)
    particle_speed_limit_param = params.scalar_param(particle_speed_limit_value)

    tether_compression_param = params.scalar_param(
        max(0.0, float(tether_compression)) if use_tether else 0.0
    )
    tether_stretch_param = params.scalar_param(MC2SystemConstants.TETHER_STRETCH_LIMIT if use_tether else 0.0)
    motion_enabled = bool(use_max_distance or use_backstop)
    motion_stiffness_param = params.scalar_param(
        max(0.0, min(1.0, float(motion_stiffness))) if motion_enabled else 0.0
    )
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
    collision_mode = max(0, min(2, int(collider_collision_mode))) if use_collider_collision else 0

    has_collision = collision_mode != 0 and bool(colliders) and bool(collided_by_groups) and bool(
        np.any(collision_radii > MC2SystemConstants.EPSILON)
    )
    collider_arrays = (
        collision.collider_arrays_for_native(state, obj, colliders)
        if has_collision
        else None
    )
    if base_pose_mode:
        # BasePose 模式下，骨架/对象级基础运动已经通过 base_positions 输入。
        # 这里禁止再把写入对象矩阵变化当作整体惯性位移，避免双重变换和 Python 顶点循环卡顿。
        inertia_state = inertia.prepare_frame(
            state.get("inertia_state"),
            obj,
            frame_dt,
            1.0,
            0.0,
            -1.0,
            -1.0,
            inertia.TELEPORT_NONE,
            0.0,
            0.0,
        )
    else:
        inertia_state = inertia.prepare_frame(
            state.get("inertia_state"),
            obj,
            frame_dt,
            float(world_inertia_param["value"]),
            float(movement_inertia_smoothing_param["value"]),
            movement_speed_limit_value * max(float(world_scale), 0.0) if movement_speed_limit_value >= 0.0 else -1.0,
            rotation_speed_limit_value,
            int(teleport_mode),
            float(teleport_distance) * max(float(world_scale), 0.0),
            float(teleport_rotation),
        )
    if int(inertia_state.get("teleport_state", 0)) == inertia.TELEPORT_RESET:
        positions = base_positions.copy()
        old_positions = base_positions.copy()
        velocity_positions = base_positions.copy()
        display_positions = base_positions.copy()
        velocity.fill(0.0)
        real_velocity.fill(0.0)
        friction.fill(0.0)
        static_friction.fill(0.0)
    else:
        display_positions = np.ascontiguousarray(state["display_positions"], dtype=np.float32)
        inertia.apply_negative_scale_teleport(
            old_positions,
            velocity_positions,
            display_positions,
            velocity,
            real_velocity,
            inertia_state,
        )
        inertia.apply_frame_shift(
            old_positions,
            velocity_positions,
            display_positions,
            velocity,
            real_velocity,
            inertia_state,
        )
        positions = old_positions.copy()
    if timing is not None:
        _add_timing(timing, "solve_setup", time.perf_counter() - stage_start)

    for _substep in range(substep_count):
        # 每个 substep 的第一段：更新基础骨架，再做惯性与重力预测。
        inertia_step = inertia.prepare_substep(
            inertia_state,
            _substep,
            substep_count,
            step_dt,
            float(local_inertia_param["value"]),
            local_movement_speed_limit_value * max(float(world_scale), 0.0)
            if local_movement_speed_limit_value >= 0.0
            else -1.0,
            local_rotation_speed_limit_value,
        )
        stage_start = time.perf_counter() if timing is not None else None
        native_step_basic_pose = native_bridge.update_step_basic_pose(
            base_positions,
            base_rotations,
            state["parent_indices"],
            state["baseline_start"],
            state["baseline_count"],
            state["baseline_data"],
            state["vertex_local_positions"],
            state["vertex_local_rotations"],
        )
        if native_step_basic_pose is None:
            step_basic_positions, step_basic_rotations = baseline.update_step_basic_pose(
                base_positions,
                base_rotations,
                state["parent_indices"],
                state["baseline_start"],
                state["baseline_count"],
                state["baseline_data"],
                state["vertex_local_positions"],
                state["vertex_local_rotations"],
            )
        else:
            step_basic_positions, step_basic_rotations = native_step_basic_pose
        if timing is not None:
            _add_timing(timing, "baseline", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        inv_masses = mc2_state.calc_inverse_masses(attributes, depths, friction)
        movable = inv_masses > MC2SystemConstants.EPSILON
        fixed = ~movable
        collision_normals.fill(0.0)
        if not native_bridge.apply_substep_inertia(
            old_positions,
            velocity,
            depths,
            inv_masses,
            inertia_step,
            float(depth_inertia_param["value"]),
        ):
            inertia.apply_substep_inertia(
                old_positions,
                velocity,
                depths,
                movable,
                inertia_step,
                float(depth_inertia_param["value"]),
            )
        velocity_positions = old_positions.copy()
        if step_dt > MC2SystemConstants.EPSILON:
            velocity[movable] *= (1.0 - substep_damping_values[movable])[:, None]
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
        if use_tether:
            # Tether 只在开启时执行一次；关闭时完全跳过，不参与后续迭代。
            stage_start = time.perf_counter() if timing is not None else None
            if not native_bridge.project_tether(
                positions,
                inv_masses,
                state["root_indices"],
                state["tether_rest_lengths"],
                velocity_positions,
                1.0,
                float(tether_compression_param["value"]),
                float(tether_stretch_param["value"]),
            ):
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
            # 首轮先做一次碰撞预投影，减少迭代开始时的穿插量。
            stage_start = time.perf_counter() if timing is not None else None
            if collision_mode == 2:
                if not native_bridge.project_edge_collisions(
                    positions,
                    state["edges"],
                    attributes,
                    inv_masses,
                    collision_radii,
                    collided_by_groups,
                    collider_arrays or {},
                    collision_normals,
                    friction,
                ):
                    collision.project_edge_collisions(
                        positions,
                        state["edges"],
                        attributes,
                        collision_radii,
                        collided_by_groups,
                        colliders,
                        obj,
                        collision_normals,
                        friction,
                    )
            else:
                if not native_bridge.project_collisions(
                    positions,
                    base_positions,
                    inv_masses,
                    collision_radii,
                    collided_by_groups,
                    collider_arrays or {},
                    collision_normals,
                    friction,
                ):
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
            if use_distance:
                # distance 是迭代中的第一道约束，碰撞后还会再补一次。
                stage_start = time.perf_counter() if timing is not None else None
                if not native_bridge.project_neighbor_constraints(
                    positions,
                    inv_masses,
                    state["distance_start"],
                    state["distance_count"],
                    state["distance_data"],
                    state["distance_rest"],
                    distance_stiffness_values,
                    velocity_positions,
                    MC2SystemConstants.DISTANCE_VELOCITY_ATTENUATION,
                ):
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

            if use_angle_restoration or use_angle_limit:
                # angle 复用同一批 baseline / step_basic 数据，恢复与限制共用一轮求解。
                stage_start = time.perf_counter() if timing is not None else None
                if not native_bridge.project_angle_constraints(
                    positions,
                    inv_masses,
                    state["parent_indices"],
                    state["baseline_start"],
                    state["baseline_count"],
                    state["baseline_data"],
                    step_basic_positions,
                    step_basic_rotations,
                    angle_restoration_values,
                    angle_limit_values,
                    velocity_positions,
                    angle_restoration_velocity_attenuation_values,
                    angle_restoration_gravity_falloff_values,
                    angle_limit_stiffness_value,
                ):
                    constraints.project_angle_constraints(
                        positions,
                        inv_masses,
                        depths,
                        state["parent_indices"],
                        state["baseline_start"],
                        state["baseline_count"],
                        state["baseline_data"],
                        step_basic_positions,
                        step_basic_rotations,
                        state["vertex_local_positions"],
                        state["vertex_local_rotations"],
                        angle_restoration_values,
                        velocity_positions,
                        angle_restoration_velocity_attenuation_values,
                        angle_restoration_gravity_falloff_values,
                        angle_limit_values,
                        angle_limit_stiffness_value,
                    )
                if timing is not None:
                    _add_timing(timing, "angle", time.perf_counter() - stage_start)

            if use_bend:
                # bend 在 angle 之后执行，优先走面内/二面角，再回退到邻接近似。
                stage_start = time.perf_counter() if timing is not None else None
                if len(state.get("dihedral_pairs", ())) > 0 or len(state.get("volume_pairs", ())) > 0:
                    if not native_bridge.project_triangle_bending(
                        positions,
                        inv_masses,
                        state["dihedral_pairs"],
                        state["dihedral_rest_angles"],
                        state["dihedral_signs"],
                        state["volume_pairs"],
                        state["volume_rest"],
                        bend_stiffness_values,
                    ):
                        constraints.project_triangle_bending(
                            positions,
                            inv_masses,
                            state["dihedral_pairs"],
                            state["dihedral_rest_angles"],
                            state["dihedral_signs"],
                            state["volume_pairs"],
                            state["volume_rest"],
                            bend_stiffness_values,
                        )
                else:
                    if not native_bridge.project_neighbor_constraints(
                        positions,
                        inv_masses,
                        state["bend_distance_start"],
                        state["bend_distance_count"],
                        state["bend_distance_data"],
                        state["bend_distance_neighbor_rest"],
                        bend_stiffness_values,
                        velocity_positions,
                        MC2SystemConstants.DISTANCE_VELOCITY_ATTENUATION,
                    ):
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
                # collision 插在迭代中部，保证后续约束能继续修正碰撞后的结果。
                stage_start = time.perf_counter() if timing is not None else None
                if collision_mode == 2:
                    if not native_bridge.project_edge_collisions(
                        positions,
                        state["edges"],
                        attributes,
                        inv_masses,
                        collision_radii,
                        collided_by_groups,
                        collider_arrays or {},
                        collision_normals,
                        friction,
                    ):
                        collision.project_edge_collisions(
                            positions,
                            state["edges"],
                            attributes,
                            collision_radii,
                            collided_by_groups,
                            colliders,
                            obj,
                            collision_normals,
                            friction,
                        )
                else:
                    if not native_bridge.project_collisions(
                        positions,
                        base_positions,
                        inv_masses,
                        collision_radii,
                        collided_by_groups,
                        collider_arrays or {},
                        collision_normals,
                        friction,
                    ):
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

            if use_distance:
                # collision 之后再补一次 distance，减少碰撞修正后拉断的问题。
                stage_start = time.perf_counter() if timing is not None else None
                if not native_bridge.project_neighbor_constraints(
                    positions,
                    inv_masses,
                    state["distance_start"],
                    state["distance_count"],
                    state["distance_data"],
                    state["distance_rest"],
                    distance_stiffness_values,
                    velocity_positions,
                    MC2SystemConstants.DISTANCE_VELOCITY_ATTENUATION,
                ):
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

        # motion 只在 substep 结束后统一执行一次，属于收尾约束。
        stage_start = time.perf_counter() if timing is not None else None
        if motion_enabled:
            stage_start = time.perf_counter() if timing is not None else None
            if not native_bridge.project_motion_constraint(
                positions,
                base_positions,
                base_rotations,
                inv_masses,
                depths,
                max_distance_param,
                motion_stiffness_param,
                backstop_radius_param,
                backstop_distance_param,
                world_scale,
                velocity_positions,
                normal_axis_value,
            ):
                constraints.project_motion_constraint(
                    positions,
                    base_positions,
                    base_rotations,
                    inv_masses,
                    depths,
                    max_distance_param,
                    motion_stiffness_param,
                    backstop_radius_param,
                    backstop_distance_param,
                    world_scale,
                    normal_axis_value,
                    velocity_positions,
                )
            if timing is not None:
                _add_timing(timing, "motion", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        particle_speed_limit = (
            particle_speed_limit_value * max(float(world_scale), 0.0)
            if particle_speed_limit_value >= 0.0
            else -1.0
        )
        if not native_bridge.apply_post_step(
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
            particle_speed_limit,
        ):
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
                particle_speed_limit,
            )
        if not native_bridge.apply_centrifugal_velocity(
            positions,
            velocity,
            depths,
            inv_masses,
            inertia_step,
            float(centrifugal_param["value"]),
        ):
            inertia.apply_centrifugal_velocity(
                positions,
                velocity,
                depths,
                movable,
                inertia_step,
                float(centrifugal_param["value"]),
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

    # 最后一段只负责把运行结果打包回 state，不再做新的求解。
    stage_start = time.perf_counter() if timing is not None else None
    next_state = dict(state)
    next_state["frame_delta_time"] = float(frame_dt)
    next_state["step_delta_time"] = float(step_dt)
    next_state["substep_damping"] = float(np.max(substep_damping_values)) if len(substep_damping_values) else 0.0
    next_state["inertia_state"] = inertia.commit_frame(inertia_state, obj)
    next_state["scale_ratio"] = float(next_state["inertia_state"].get("scale_ratio", world_scale) or world_scale)
    next_state["negative_scale_sign"] = int(next_state["inertia_state"].get("negative_scale_sign", 1) or 1)
    next_state["next_positions"] = np.ascontiguousarray(positions, dtype=np.float32)
    next_state["old_positions"] = np.ascontiguousarray(old_positions, dtype=np.float32)
    display_positions = native_bridge.calculate_display_positions(
        positions,
        real_velocity,
        state["root_indices"],
        frame_dt,
        MC2SystemConstants.MAX_DISTANCE_RATIO_FUTURE_PREDICTION,
    )
    if display_positions is None:
        display_positions = _calc_display_positions(
            positions,
            real_velocity,
            state["root_indices"],
            frame_dt,
        )
    next_state["display_positions"] = np.ascontiguousarray(display_positions, dtype=np.float32)
    next_state["step_basic_positions"] = np.ascontiguousarray(step_basic_positions, dtype=np.float32)
    next_state["step_basic_rotations"] = np.ascontiguousarray(step_basic_rotations, dtype=np.float32)
    next_state["velocity_positions"] = np.ascontiguousarray(velocity_positions, dtype=np.float32)
    next_state["velocity"] = np.ascontiguousarray(velocity, dtype=np.float32)
    next_state["real_velocity"] = np.ascontiguousarray(real_velocity, dtype=np.float32)
    next_state["friction"] = np.ascontiguousarray(friction, dtype=np.float32)
    next_state["static_friction"] = np.ascontiguousarray(static_friction, dtype=np.float32)
    next_state["collision_normals"] = np.ascontiguousarray(collision_normals, dtype=np.float32)
    next_state["inv_masses"] = np.ascontiguousarray(inv_masses, dtype=np.float32)
    next_state["previous_collider_snapshot"] = collision.compact_collider_snapshot(colliders)
    next_state["param_slots"] = dict(next_state.get("param_slots") or {})
    next_state["param_slots"]["distance_stiffness"] = distance_stiffness_param
    next_state["param_slots"]["bend_stiffness"] = bend_stiffness_param
    next_state["param_slots"]["angle_restoration_stiffness"] = angle_restoration_param
    next_state["param_slots"]["angle_restoration_velocity_attenuation"] = angle_restoration_velocity_attenuation_param
    next_state["param_slots"]["angle_restoration_gravity_falloff"] = angle_restoration_gravity_falloff_param
    next_state["param_slots"]["angle_limit"] = angle_limit_param
    next_state["param_slots"]["angle_limit_stiffness"] = angle_limit_stiffness_param
    next_state["param_slots"]["world_inertia"] = world_inertia_param
    next_state["param_slots"]["movement_inertia_smoothing"] = movement_inertia_smoothing_param
    next_state["param_slots"]["local_inertia"] = local_inertia_param
    next_state["param_slots"]["depth_inertia"] = depth_inertia_param
    next_state["param_slots"]["centrifugal"] = centrifugal_param
    next_state["param_slots"]["movement_speed_limit"] = movement_speed_limit_param
    next_state["param_slots"]["rotation_speed_limit"] = rotation_speed_limit_param
    next_state["param_slots"]["local_movement_speed_limit"] = local_movement_speed_limit_param
    next_state["param_slots"]["local_rotation_speed_limit"] = local_rotation_speed_limit_param
    next_state["param_slots"]["particle_speed_limit"] = particle_speed_limit_param
    next_state["param_slots"]["max_distance"] = max_distance_param
    next_state["param_slots"]["tether_compression"] = tether_compression_param
    next_state["param_slots"]["tether_stretch"] = tether_stretch_param
    next_state["param_slots"]["motion_stiffness"] = motion_stiffness_param
    next_state["param_slots"]["normal_axis"] = params.scalar_param(float(normal_axis_value))
    next_state["param_slots"]["damping"] = damping_param
    next_state["param_slots"]["backstop_radius"] = backstop_radius_param
    next_state["param_slots"]["backstop_distance"] = backstop_distance_param
    next_state["param_slots"]["collider_friction"] = collider_friction_param
    next_state["param_slots"]["collider_collision_mode"] = params.scalar_param(float(collision_mode))
    next_state["param_slots"]["use_tether"] = _component_slot(use_tether)
    next_state["param_slots"]["use_distance"] = _component_slot(use_distance)
    next_state["param_slots"]["use_bend"] = _component_slot(use_bend)
    next_state["param_slots"]["use_angle_restoration"] = _component_slot(use_angle_restoration)
    next_state["param_slots"]["use_angle_limit"] = _component_slot(use_angle_limit)
    next_state["param_slots"]["use_max_distance"] = _component_slot(use_max_distance)
    next_state["param_slots"]["use_backstop"] = _component_slot(use_backstop)
    next_state["param_slots"]["use_collider_collision"] = _component_slot(use_collider_collision)

    extension_slots = dict(next_state.get("extension_slots") or {})
    native_slot = dict(extension_slots.get("native") or {})
    native_slot["abi_view"] = native_bridge.build_abi_view(next_state, obj, colliders)
    native_slot["collider_arrays"] = native_slot["abi_view"]["colliders"]
    extension_slots["native"] = native_slot
    next_state["extension_slots"] = extension_slots
    if timing is not None:
        _add_timing(timing, "post_pack", time.perf_counter() - stage_start)
    return next_state


def solve_meshcloth_native_core(
    state: dict,
    obj: bpy.types.Object,
    scene: bpy.types.Scene,
    substeps: int,
    iterations: int,
    gravity_dir,
    gravity_power: float,
    damping: float,
    damping_curve,
    use_tether: bool,
    tether_compression: float,
    use_distance: bool,
    distance_stiffness: float,
    distance_stiffness_curve,
    use_bend: bool,
    bend_stiffness: float,
    bend_stiffness_curve,
    use_angle_restoration: bool,
    angle_restoration_stiffness: float,
    angle_restoration_stiffness_curve,
    angle_restoration_velocity_attenuation: float,
    angle_restoration_velocity_attenuation_curve,
    angle_restoration_gravity_falloff: float,
    use_angle_limit: bool,
    angle_limit: float,
    angle_limit_curve,
    angle_limit_stiffness: float,
    world_inertia: float,
    movement_inertia_smoothing: float,
    local_inertia: float,
    depth_inertia: float,
    centrifugal: float,
    movement_speed_limit: float,
    rotation_speed_limit: float,
    local_movement_speed_limit: float,
    local_rotation_speed_limit: float,
    particle_speed_limit: float,
    teleport_mode: int,
    teleport_distance: float,
    teleport_rotation: float,
    use_max_distance: bool,
    max_distance: float,
    max_distance_curve,
    use_backstop: bool,
    backstop_radius: float,
    backstop_distance: float,
    backstop_distance_curve,
    motion_stiffness: float,
    normal_axis: int,
    use_collider_collision: bool,
    collider_friction: float,
    collider_collision_mode: int,
    timing: dict | None = None,
    colliders: list[dict] | None = None,
) -> dict:
    # native_core 路径尽量保持和 Python 求解同一套顺序：
    # 输入整理 -> 曲线采样 -> substep inertia -> motion 采样 -> C++ 核心求解 -> 状态回填。
    stage_start = time.perf_counter() if timing is not None else None
    if not native_bridge.has_function("solve_meshcloth_mc2"):
        status = native_bridge.native_status("solve_meshcloth_mc2")
        raise RuntimeError(f"MC2 C++ backend is unavailable: {status}")
    colliders = collision.with_previous_collider_pose(colliders, state.get("previous_collider_snapshot"))

    positions = np.ascontiguousarray(state["next_positions"], dtype=np.float32)
    old_positions = np.ascontiguousarray(state["old_positions"], dtype=np.float32)
    base_positions = np.ascontiguousarray(state["base_positions"], dtype=np.float32)
    depths = np.ascontiguousarray(state["depths"], dtype=np.float32)
    friction = np.ascontiguousarray(state["friction"], dtype=np.float32)
    static_friction = np.ascontiguousarray(state["static_friction"], dtype=np.float32)
    velocity_positions = np.ascontiguousarray(state["velocity_positions"], dtype=np.float32)
    velocity = np.ascontiguousarray(state["velocity"], dtype=np.float32)
    real_velocity = np.ascontiguousarray(state["real_velocity"], dtype=np.float32)
    inv_masses = mc2_state.calc_inverse_masses(
        np.ascontiguousarray(state["attributes"], dtype=np.uint8),
        depths,
        friction,
    )
    collision_radii = np.ascontiguousarray(state["collision_radii"], dtype=np.float32)
    collided_by_groups = math_utils.clamp_group_mask(state.get("collided_by_groups", 0))
    collision_normals = np.ascontiguousarray(state["collision_normals"], dtype=np.float32)
    collision_normals.fill(0.0)

    frame_dt = blender_io.scene_delta_time(scene)
    substep_count = max(1, min(16, int(substeps)))
    iteration_count = max(0, min(64, int(iterations)))
    step_dt = frame_dt / substep_count if substep_count > 0 else frame_dt
    gravity = math_utils.world_gravity(gravity_dir) * max(float(gravity_power), 0.0)
    world_scale = math_utils.matrix_scale_radius(obj.matrix_world)
    world_scale_nonnegative = max(float(world_scale), 0.0)
    base_pose_mode = int(state.get("base_pose_proxy_ptr", 0) or 0) != 0
    normal_axis_value = max(0, min(5, int(normal_axis)))
    curve_stage_start = time.perf_counter() if timing is not None else None
    stiffness_depths = np.clip(depths, 0.0, 1.0)
    damping_param = params.curve_value_param(damping, damping_curve, minimum=0.0, maximum=1.0)
    distance_stiffness_param = (
        params.curve_value_param(distance_stiffness, distance_stiffness_curve, minimum=0.0, maximum=1.0)
        if use_distance
        else params.scalar_param(0.0)
    )
    bend_stiffness_param = (
        params.curve_value_param(bend_stiffness, bend_stiffness_curve, minimum=0.0, maximum=1.0)
        if use_bend
        else params.scalar_param(0.0)
    )
    angle_restoration_param = (
        params.curve_value_param(
            angle_restoration_stiffness,
            angle_restoration_stiffness_curve,
            minimum=0.0,
            maximum=1.0,
        )
        if use_angle_restoration
        else params.scalar_param(0.0)
    )
    angle_restoration_velocity_attenuation_param = (
        params.curve_value_param(
            angle_restoration_velocity_attenuation,
            angle_restoration_velocity_attenuation_curve,
            minimum=0.0,
            maximum=1.0,
        )
        if use_angle_restoration
        else params.scalar_param(0.0)
    )
    angle_restoration_gravity_falloff_param = (
        params.scalar_param(max(0.0, min(1.0, float(angle_restoration_gravity_falloff))))
        if use_angle_restoration
        else params.scalar_param(0.0)
    )
    angle_limit_param = (
        params.curve_value_param(angle_limit, angle_limit_curve, minimum=0.0, maximum=180.0)
        if use_angle_limit
        else params.scalar_param(0.0)
    )
    angle_limit_stiffness_value = max(0.0, min(1.0, float(angle_limit_stiffness)))
    angle_limit_stiffness_param = params.scalar_param(angle_limit_stiffness_value)
    max_distance_param = (
        params.curve_value_param(max_distance, max_distance_curve, minimum=0.0)
        if use_max_distance
        else params.scalar_param(0.0)
    )
    backstop_radius_param = params.float_param(backstop_radius, minimum=0.0) if use_backstop else params.scalar_param(0.0)
    backstop_distance_param = (
        params.curve_value_param(backstop_distance, backstop_distance_curve, minimum=0.0)
        if use_backstop
        else params.scalar_param(0.0)
    )
    if timing is not None:
        _add_timing(timing, "param_curves", time.perf_counter() - curve_stage_start)
    curve_stage_start = time.perf_counter() if timing is not None else None
    damping_values = np.ascontiguousarray(
        np.clip(
            params.sample_param(damping_param, stiffness_depths) * float(MC2SystemConstants.DAMPING_SCALE),
            0.0,
            1.0,
        ),
        dtype=np.float32,
    )
    substep_damping_values = _substep_damping_values(damping_values, substep_count)
    distance_stiffness_values = (
        np.ascontiguousarray(np.clip(params.sample_param(distance_stiffness_param, stiffness_depths), 0.0, 1.0), dtype=np.float32)
        if use_distance
        else _zero_values_like(stiffness_depths)
    )
    bend_stiffness_values = (
        np.ascontiguousarray(np.clip(params.sample_param(bend_stiffness_param, stiffness_depths), 0.0, 1.0), dtype=np.float32)
        if use_bend
        else _zero_values_like(stiffness_depths)
    )
    angle_restoration_values = (
        np.ascontiguousarray(
            np.clip(params.sample_param(angle_restoration_param, stiffness_depths), 0.0, 1.0),
            dtype=np.float32,
        )
        if use_angle_restoration
        else _zero_values_like(stiffness_depths)
    )
    angle_restoration_velocity_attenuation_values = (
        np.ascontiguousarray(
            np.clip(params.sample_param(angle_restoration_velocity_attenuation_param, stiffness_depths), 0.0, 1.0),
            dtype=np.float32,
        )
        if use_angle_restoration
        else _zero_values_like(stiffness_depths)
    )
    angle_restoration_gravity_falloff_values = (
        _scalar_values_like(stiffness_depths, angle_restoration_gravity_falloff_param["value"])
        if use_angle_restoration
        else _zero_values_like(stiffness_depths)
    )
    angle_limit_values = (
        np.ascontiguousarray(
            np.clip(params.sample_param(angle_limit_param, stiffness_depths), 0.0, 180.0),
            dtype=np.float32,
        )
        if use_angle_limit
        else _zero_values_like(stiffness_depths)
    )
    if timing is not None:
        _add_timing(timing, "stiffness_curves", time.perf_counter() - curve_stage_start)

    world_inertia_param = params.scalar_param(max(0.0, min(1.0, float(world_inertia))))
    movement_inertia_smoothing_param = params.scalar_param(max(0.0, min(1.0, float(movement_inertia_smoothing))))
    local_inertia_param = params.scalar_param(max(0.0, min(1.0, float(local_inertia))))
    depth_inertia_param = params.scalar_param(max(0.0, min(1.0, float(depth_inertia))))
    centrifugal_param = params.scalar_param(max(0.0, min(1.0, float(centrifugal))))
    movement_speed_limit_value = float(movement_speed_limit)
    rotation_speed_limit_value = float(rotation_speed_limit)
    local_movement_speed_limit_value = float(local_movement_speed_limit)
    local_rotation_speed_limit_value = float(local_rotation_speed_limit)
    particle_speed_limit_value = float(particle_speed_limit)
    movement_speed_limit_param = params.scalar_param(movement_speed_limit_value)
    rotation_speed_limit_param = params.scalar_param(rotation_speed_limit_value)
    local_movement_speed_limit_param = params.scalar_param(local_movement_speed_limit_value)
    local_rotation_speed_limit_param = params.scalar_param(local_rotation_speed_limit_value)
    particle_speed_limit_param = params.scalar_param(particle_speed_limit_value)

    tether_compression_param = params.scalar_param(max(0.0, float(tether_compression)) if use_tether else 0.0)
    tether_stretch_param = params.scalar_param(MC2SystemConstants.TETHER_STRETCH_LIMIT if use_tether else 0.0)
    motion_enabled = bool(use_max_distance or use_backstop)
    motion_stiffness_param = params.scalar_param(
        max(0.0, min(1.0, float(motion_stiffness))) if motion_enabled else 0.0
    )
    collider_friction_param = params.scalar_param(max(0.0, min(0.5, float(collider_friction))))
    dynamic_friction = (
        float(collider_friction_param["value"])
        * MC2SystemConstants.COLLIDER_COLLISION_DYNAMIC_FRICTION_RATIO
    )
    static_friction_speed = (
        float(collider_friction_param["value"])
        * MC2SystemConstants.COLLIDER_COLLISION_STATIC_FRICTION_RATIO
        * world_scale_nonnegative
    )
    collision_mode = max(0, min(2, int(collider_collision_mode))) if use_collider_collision else 0

    has_collision = collision_mode != 0 and bool(colliders) and bool(collided_by_groups) and bool(
        np.any(collision_radii > MC2SystemConstants.EPSILON)
    )
    collider_arrays = (
        collision.collider_arrays_for_native(state, obj, colliders)
        if has_collision
        else None
    )

    if base_pose_mode:
        # BasePose 模式下基础动画来自只读代理，写入对象矩阵不再驱动物理整体惯性。
        # 这能避免移动骨架对象时 solve_setup 进入 apply_frame_shift 顶点循环。
        inertia_state = inertia.prepare_frame(
            state.get("inertia_state"),
            obj,
            frame_dt,
            1.0,
            0.0,
            -1.0,
            -1.0,
            inertia.TELEPORT_NONE,
            0.0,
            0.0,
        )
    else:
        inertia_state = inertia.prepare_frame(
            state.get("inertia_state"),
            obj,
            frame_dt,
            float(world_inertia_param["value"]),
            float(movement_inertia_smoothing_param["value"]),
            movement_speed_limit_value * world_scale_nonnegative if movement_speed_limit_value >= 0.0 else -1.0,
            rotation_speed_limit_value,
            int(teleport_mode),
            float(teleport_distance) * world_scale_nonnegative,
            float(teleport_rotation),
        )
    if int(inertia_state.get("teleport_state", 0)) == inertia.TELEPORT_RESET:
        positions = base_positions.copy()
        old_positions = base_positions.copy()
        velocity_positions = base_positions.copy()
        display_positions = base_positions.copy()
        velocity.fill(0.0)
        real_velocity.fill(0.0)
        friction.fill(0.0)
        static_friction.fill(0.0)
    else:
        display_positions = np.ascontiguousarray(state["display_positions"], dtype=np.float32)
        inertia.apply_negative_scale_teleport(
            old_positions,
            velocity_positions,
            display_positions,
            velocity,
            real_velocity,
            inertia_state,
        )
        inertia.apply_frame_shift(
            old_positions,
            velocity_positions,
            display_positions,
            velocity,
            real_velocity,
            inertia_state,
        )
        positions = old_positions.copy()

    substep_inertia_lists = {
        "old_world_positions": [],
        "step_vectors": [],
        "step_rotations": [],
        "inertia_vectors": [],
        "inertia_rotations": [],
        "now_world_positions": [],
        "rotation_axes": [],
        "angular_velocities": [],
    }
    for substep_index in range(substep_count):
        inertia_step = inertia.prepare_substep(
            inertia_state,
            substep_index,
            substep_count,
            step_dt,
            float(local_inertia_param["value"]),
            local_movement_speed_limit_value * world_scale_nonnegative
            if local_movement_speed_limit_value >= 0.0
            else -1.0,
            local_rotation_speed_limit_value,
        )
        substep_inertia_lists["old_world_positions"].append(inertia_step["old_world_position"])
        substep_inertia_lists["step_vectors"].append(inertia_step["step_vector"])
        substep_inertia_lists["step_rotations"].append(inertia_step["step_rotation"])
        substep_inertia_lists["inertia_vectors"].append(inertia_step["inertia_vector"])
        substep_inertia_lists["inertia_rotations"].append(inertia_step["inertia_rotation"])
        substep_inertia_lists["now_world_positions"].append(inertia_step["now_world_position"])
        substep_inertia_lists["rotation_axes"].append(inertia_step["rotation_axis"])
        substep_inertia_lists["angular_velocities"].append(float(inertia_step.get("angular_velocity", 0.0) or 0.0))
    substep_inertia_arrays = {
        key: np.ascontiguousarray(value, dtype=np.float32)
        for key, value in substep_inertia_lists.items()
    }
    curve_stage_start = time.perf_counter() if timing is not None else None
    motion_depths = np.clip(depths * depths, 0.0, 1.0)
    if motion_enabled:
        max_distances = np.ascontiguousarray(
            params.sample_param(max_distance_param, motion_depths) * world_scale_nonnegative,
            dtype=np.float32,
        )
        motion_stiffness_values = np.ascontiguousarray(
            np.clip(params.sample_param(motion_stiffness_param, motion_depths), 0.0, 1.0),
            dtype=np.float32,
        )
        backstop_radii = np.ascontiguousarray(
            params.sample_param(backstop_radius_param, motion_depths) * world_scale_nonnegative,
            dtype=np.float32,
        )
        backstop_distances = np.ascontiguousarray(
            params.sample_param(backstop_distance_param, motion_depths) * world_scale_nonnegative,
            dtype=np.float32,
        )
    else:
        max_distances = _zero_values_like(motion_depths)
        motion_stiffness_values = _zero_values_like(motion_depths)
        backstop_radii = _zero_values_like(motion_depths)
        backstop_distances = _zero_values_like(motion_depths)
    if timing is not None:
        _add_timing(timing, "motion_curves", time.perf_counter() - curve_stage_start)
    particle_speed_limit_scaled = (
        particle_speed_limit_value * world_scale_nonnegative
        if particle_speed_limit_value >= 0.0
        else -1.0
    )

    arrays = native_bridge.state_arrays_for_native(state)
    arrays.update(
        {
            "positions": np.ascontiguousarray(positions, dtype=np.float32),
            "old_positions": np.ascontiguousarray(old_positions, dtype=np.float32),
            "velocity_positions": np.ascontiguousarray(velocity_positions, dtype=np.float32),
            "velocity": np.ascontiguousarray(velocity, dtype=np.float32),
            "real_velocity": np.ascontiguousarray(real_velocity, dtype=np.float32),
            "friction": np.ascontiguousarray(friction, dtype=np.float32),
            "static_friction": np.ascontiguousarray(static_friction, dtype=np.float32),
            "collision_normals": np.ascontiguousarray(collision_normals, dtype=np.float32),
            "inv_masses": np.ascontiguousarray(inv_masses, dtype=np.float32),
            "display_positions": np.ascontiguousarray(display_positions, dtype=np.float32),
        }
    )
    if timing is not None:
        _add_timing(timing, "solve_setup", time.perf_counter() - stage_start)

    # C++ 核心前先构建与 Python 路径同构的运行时数组。
    stage_start = time.perf_counter() if timing is not None else None
    solved = native_bridge.solve_meshcloth_core(
        arrays,
        distance_stiffness_values=distance_stiffness_values,
        bend_stiffness_values=bend_stiffness_values,
        angle_restoration_values=angle_restoration_values,
        angle_restoration_velocity_attenuation_values=angle_restoration_velocity_attenuation_values,
        angle_restoration_gravity_falloff_values=angle_restoration_gravity_falloff_values,
        angle_limit_values=angle_limit_values,
        substep_damping_values=substep_damping_values,
        max_distances=max_distances,
        motion_stiffness_values=motion_stiffness_values,
        backstop_radii=backstop_radii,
        backstop_distances=backstop_distances,
        collider_arrays=collider_arrays,
        substep_inertia_arrays=substep_inertia_arrays,
        frame_dt=frame_dt,
        step_dt=step_dt,
        substeps=substep_count,
        iterations=iteration_count,
        gravity=gravity,
        depth_inertia=float(depth_inertia_param["value"]),
        centrifugal=float(centrifugal_param["value"]),
        use_tether=bool(use_tether),
        tether_compression=float(tether_compression_param["value"]),
        tether_stretch=float(tether_stretch_param["value"]),
        dynamic_friction=dynamic_friction,
        static_friction_speed=static_friction_speed,
        particle_speed_limit=particle_speed_limit_scaled,
        angle_limit_stiffness=angle_limit_stiffness_value,
        normal_axis=normal_axis_value,
        collided_by_groups=collided_by_groups,
        collider_collision_mode=collision_mode,
        display_max_distance_ratio=MC2SystemConstants.MAX_DISTANCE_RATIO_FUTURE_PREDICTION,
        animation_pose_ratio=0.0,
    )
    if timing is not None:
        _add_timing(timing, "native_core", time.perf_counter() - stage_start)
    if not solved:
        status = native_bridge.native_status("solve_meshcloth_mc2")
        raise RuntimeError(f"MC2 C++ backend solve failed or is unavailable: {status}")

    stage_start = time.perf_counter() if timing is not None else None
    next_state = dict(state)
    next_state["frame_delta_time"] = float(frame_dt)
    next_state["step_delta_time"] = float(step_dt)
    next_state["substep_damping"] = float(np.max(substep_damping_values)) if len(substep_damping_values) else 0.0
    next_state["inertia_state"] = inertia.commit_frame(inertia_state, obj)
    next_state["scale_ratio"] = float(
        next_state["inertia_state"].get("scale_ratio", world_scale_nonnegative) or world_scale_nonnegative
    )
    next_state["negative_scale_sign"] = int(next_state["inertia_state"].get("negative_scale_sign", 1) or 1)
    next_state["next_positions"] = np.ascontiguousarray(arrays["positions"], dtype=np.float32)
    next_state["old_positions"] = np.ascontiguousarray(arrays["old_positions"], dtype=np.float32)
    next_state["display_positions"] = np.ascontiguousarray(arrays["display_positions"], dtype=np.float32)
    next_state["step_basic_positions"] = np.ascontiguousarray(arrays["step_basic_positions"], dtype=np.float32)
    next_state["step_basic_rotations"] = np.ascontiguousarray(arrays["step_basic_rotations"], dtype=np.float32)
    next_state["velocity_positions"] = np.ascontiguousarray(arrays["velocity_positions"], dtype=np.float32)
    next_state["velocity"] = np.ascontiguousarray(arrays["velocity"], dtype=np.float32)
    next_state["real_velocity"] = np.ascontiguousarray(arrays["real_velocity"], dtype=np.float32)
    next_state["friction"] = np.ascontiguousarray(arrays["friction"], dtype=np.float32)
    next_state["static_friction"] = np.ascontiguousarray(arrays["static_friction"], dtype=np.float32)
    next_state["collision_normals"] = np.ascontiguousarray(arrays["collision_normals"], dtype=np.float32)
    next_state["inv_masses"] = np.ascontiguousarray(arrays["inv_masses"], dtype=np.float32)
    next_state["previous_collider_snapshot"] = collision.compact_collider_snapshot(colliders)
    next_state["param_slots"] = dict(next_state.get("param_slots") or {})
    next_state["param_slots"]["distance_stiffness"] = distance_stiffness_param
    next_state["param_slots"]["bend_stiffness"] = bend_stiffness_param
    next_state["param_slots"]["angle_restoration_stiffness"] = angle_restoration_param
    next_state["param_slots"]["angle_restoration_velocity_attenuation"] = angle_restoration_velocity_attenuation_param
    next_state["param_slots"]["angle_restoration_gravity_falloff"] = angle_restoration_gravity_falloff_param
    next_state["param_slots"]["angle_limit"] = angle_limit_param
    next_state["param_slots"]["angle_limit_stiffness"] = angle_limit_stiffness_param
    next_state["param_slots"]["world_inertia"] = world_inertia_param
    next_state["param_slots"]["movement_inertia_smoothing"] = movement_inertia_smoothing_param
    next_state["param_slots"]["local_inertia"] = local_inertia_param
    next_state["param_slots"]["depth_inertia"] = depth_inertia_param
    next_state["param_slots"]["centrifugal"] = centrifugal_param
    next_state["param_slots"]["movement_speed_limit"] = movement_speed_limit_param
    next_state["param_slots"]["rotation_speed_limit"] = rotation_speed_limit_param
    next_state["param_slots"]["local_movement_speed_limit"] = local_movement_speed_limit_param
    next_state["param_slots"]["local_rotation_speed_limit"] = local_rotation_speed_limit_param
    next_state["param_slots"]["particle_speed_limit"] = particle_speed_limit_param
    next_state["param_slots"]["max_distance"] = max_distance_param
    next_state["param_slots"]["tether_compression"] = tether_compression_param
    next_state["param_slots"]["tether_stretch"] = tether_stretch_param
    next_state["param_slots"]["motion_stiffness"] = motion_stiffness_param
    next_state["param_slots"]["normal_axis"] = params.scalar_param(float(normal_axis_value))
    next_state["param_slots"]["damping"] = damping_param
    next_state["param_slots"]["backstop_radius"] = backstop_radius_param
    next_state["param_slots"]["backstop_distance"] = backstop_distance_param
    next_state["param_slots"]["collider_friction"] = collider_friction_param
    next_state["param_slots"]["collider_collision_mode"] = params.scalar_param(float(collision_mode))
    next_state["param_slots"]["use_tether"] = _component_slot(use_tether)
    next_state["param_slots"]["use_distance"] = _component_slot(use_distance)
    next_state["param_slots"]["use_bend"] = _component_slot(use_bend)
    next_state["param_slots"]["use_angle_restoration"] = _component_slot(use_angle_restoration)
    next_state["param_slots"]["use_angle_limit"] = _component_slot(use_angle_limit)
    next_state["param_slots"]["use_max_distance"] = _component_slot(use_max_distance)
    next_state["param_slots"]["use_backstop"] = _component_slot(use_backstop)
    next_state["param_slots"]["use_collider_collision"] = _component_slot(use_collider_collision)

    extension_slots = dict(next_state.get("extension_slots") or {})
    native_slot = dict(extension_slots.get("native") or {})
    native_slot["abi_view"] = native_bridge.build_abi_view(next_state, obj, colliders)
    native_slot["collider_arrays"] = native_slot["abi_view"]["colliders"]
    native_slot["solver"] = "cpp_core"
    extension_slots["native"] = native_slot
    next_state["extension_slots"] = extension_slots
    if timing is not None:
        _add_timing(timing, "post_pack", time.perf_counter() - stage_start)
    return next_state


def _calc_display_positions(
    positions: np.ndarray,
    real_velocity: np.ndarray,
    root_indices: np.ndarray,
    frame_dt: float,
) -> np.ndarray:
    display_positions = np.ascontiguousarray(positions, dtype=np.float32).copy()
    if frame_dt <= MC2SystemConstants.EPSILON:
        return display_positions

    future_positions = display_positions + np.ascontiguousarray(real_velocity, dtype=np.float32) * float(frame_dt)

    roots = np.ascontiguousarray(root_indices, dtype=np.int32)
    for vertex_index in range(len(future_positions)):
        root_index = int(roots[vertex_index]) if vertex_index < len(roots) else -1
        if root_index < 0 or root_index >= len(future_positions):
            continue
        root_position = display_positions[root_index]
        original_dist = float(np.linalg.norm(display_positions[vertex_index] - root_position))
        clamp_dist = original_dist * float(MC2SystemConstants.MAX_DISTANCE_RATIO_FUTURE_PREDICTION)
        if clamp_dist <= MC2SystemConstants.EPSILON:
            continue
        delta = future_positions[vertex_index] - root_position
        length = float(np.linalg.norm(delta))
        if length > clamp_dist and length > MC2SystemConstants.EPSILON:
            future_positions[vertex_index] = root_position + delta * (clamp_dist / length)

    return np.ascontiguousarray(future_positions, dtype=np.float32)
