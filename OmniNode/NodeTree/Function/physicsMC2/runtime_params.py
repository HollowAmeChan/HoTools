"""MC2 每帧参数运行态。

这个文件只负责把节点输入整理成解算器可直接消费的参数：
1. 标量/曲线输入统一转为 param slot。
2. 按顶点深度采样曲线，生成 stiffness / damping / motion 数组。
3. 维护写回 state["param_slots"] 的统一入口。

实际约束求解、碰撞、惯性与 Blender IO 不放在这里，避免参数层和执行层互相污染。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from . import params
from .constants import MC2SystemConstants


def _add_timing(timing: dict | None, add_timing, stage: str, start: float | None) -> None:
    if timing is None or add_timing is None or start is None:
        return
    add_timing(timing, stage, time.perf_counter() - start)


def zero_values_like(values: np.ndarray) -> np.ndarray:
    return np.zeros(len(values), dtype=np.float32)


def scalar_values_like(values: np.ndarray, value: float) -> np.ndarray:
    return np.full(len(values), float(value), dtype=np.float32)


def component_slot(enabled: bool) -> dict:
    return params.scalar_param(1.0 if enabled else 0.0)


def substep_damping_values(frame_damping_values: np.ndarray, substeps: int) -> np.ndarray:
    values = np.clip(np.ascontiguousarray(frame_damping_values, dtype=np.float32), 0.0, 1.0)
    substep_count = max(1, int(substeps))
    return np.ascontiguousarray(1.0 - np.power(1.0 - values, 1.0 / float(substep_count)), dtype=np.float32)


@dataclass(slots=True)
class MC2RuntimeParams:
    normal_axis: int
    motion_enabled: bool
    collision_mode: int
    angle_limit_stiffness: float
    movement_speed_limit: float
    rotation_speed_limit: float
    local_movement_speed_limit: float
    local_rotation_speed_limit: float
    particle_speed_limit: float
    dynamic_friction: float
    static_friction_speed: float
    damping_param: dict
    distance_stiffness_param: dict
    bend_stiffness_param: dict
    angle_restoration_param: dict
    angle_restoration_velocity_attenuation_param: dict
    angle_restoration_gravity_falloff_param: dict
    angle_limit_param: dict
    angle_limit_stiffness_param: dict
    world_inertia_param: dict
    movement_inertia_smoothing_param: dict
    local_inertia_param: dict
    depth_inertia_param: dict
    centrifugal_param: dict
    movement_speed_limit_param: dict
    rotation_speed_limit_param: dict
    local_movement_speed_limit_param: dict
    local_rotation_speed_limit_param: dict
    particle_speed_limit_param: dict
    max_distance_param: dict
    tether_compression_param: dict
    tether_stretch_param: dict
    motion_stiffness_param: dict
    backstop_radius_param: dict
    backstop_distance_param: dict
    collider_friction_param: dict
    collider_collision_mode_param: dict
    use_tether_param: dict
    use_distance_param: dict
    use_bend_param: dict
    use_angle_restoration_param: dict
    use_angle_limit_param: dict
    use_max_distance_param: dict
    use_backstop_param: dict
    use_collider_collision_param: dict
    substep_damping_values: np.ndarray
    distance_stiffness_values: np.ndarray
    bend_stiffness_values: np.ndarray
    angle_restoration_values: np.ndarray
    angle_restoration_velocity_attenuation_values: np.ndarray
    angle_restoration_gravity_falloff_values: np.ndarray
    angle_limit_values: np.ndarray

    def param_slots(self) -> dict:
        return {
            "distance_stiffness": self.distance_stiffness_param,
            "bend_stiffness": self.bend_stiffness_param,
            "angle_restoration_stiffness": self.angle_restoration_param,
            "angle_restoration_velocity_attenuation": self.angle_restoration_velocity_attenuation_param,
            "angle_restoration_gravity_falloff": self.angle_restoration_gravity_falloff_param,
            "angle_limit": self.angle_limit_param,
            "angle_limit_stiffness": self.angle_limit_stiffness_param,
            "world_inertia": self.world_inertia_param,
            "movement_inertia_smoothing": self.movement_inertia_smoothing_param,
            "local_inertia": self.local_inertia_param,
            "depth_inertia": self.depth_inertia_param,
            "centrifugal": self.centrifugal_param,
            "movement_speed_limit": self.movement_speed_limit_param,
            "rotation_speed_limit": self.rotation_speed_limit_param,
            "local_movement_speed_limit": self.local_movement_speed_limit_param,
            "local_rotation_speed_limit": self.local_rotation_speed_limit_param,
            "particle_speed_limit": self.particle_speed_limit_param,
            "max_distance": self.max_distance_param,
            "tether_compression": self.tether_compression_param,
            "tether_stretch": self.tether_stretch_param,
            "motion_stiffness": self.motion_stiffness_param,
            "normal_axis": params.scalar_param(float(self.normal_axis)),
            "damping": self.damping_param,
            "backstop_radius": self.backstop_radius_param,
            "backstop_distance": self.backstop_distance_param,
            "collider_friction": self.collider_friction_param,
            "collider_collision_mode": self.collider_collision_mode_param,
            "use_tether": self.use_tether_param,
            "use_distance": self.use_distance_param,
            "use_bend": self.use_bend_param,
            "use_angle_restoration": self.use_angle_restoration_param,
            "use_angle_limit": self.use_angle_limit_param,
            "use_max_distance": self.use_max_distance_param,
            "use_backstop": self.use_backstop_param,
            "use_collider_collision": self.use_collider_collision_param,
        }


@dataclass(slots=True)
class MC2MotionSamples:
    max_distances: np.ndarray
    motion_stiffness_values: np.ndarray
    backstop_radii: np.ndarray
    backstop_distances: np.ndarray


def build_runtime_params(
    curve_cache: dict,
    depths: np.ndarray,
    substep_count: int,
    world_scale_nonnegative: float,
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
    add_timing=None,
) -> MC2RuntimeParams:
    normal_axis_value = max(0, min(5, int(normal_axis)))
    stiffness_depths = np.clip(np.ascontiguousarray(depths, dtype=np.float32), 0.0, 1.0)

    stage_start = time.perf_counter() if timing is not None else None
    damping_param = params.curve_value_param_cached(curve_cache, "damping", damping, damping_curve, minimum=0.0, maximum=1.0)
    distance_stiffness_param = (
        params.curve_value_param_cached(
            curve_cache,
            "distance_stiffness",
            distance_stiffness,
            distance_stiffness_curve,
            minimum=0.0,
            maximum=1.0,
        )
        if use_distance
        else params.scalar_param(0.0)
    )
    bend_stiffness_param = (
        params.curve_value_param_cached(
            curve_cache,
            "bend_stiffness",
            bend_stiffness,
            bend_stiffness_curve,
            minimum=0.0,
            maximum=1.0,
        )
        if use_bend
        else params.scalar_param(0.0)
    )
    angle_restoration_param = (
        params.curve_value_param_cached(
            curve_cache,
            "angle_restoration_stiffness",
            angle_restoration_stiffness,
            angle_restoration_stiffness_curve,
            minimum=0.0,
            maximum=1.0,
        )
        if use_angle_restoration
        else params.scalar_param(0.0)
    )
    angle_restoration_velocity_attenuation_param = (
        params.curve_value_param_cached(
            curve_cache,
            "angle_restoration_velocity_attenuation",
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
        params.curve_value_param_cached(curve_cache, "angle_limit", angle_limit, angle_limit_curve, minimum=0.0, maximum=180.0)
        if use_angle_limit
        else params.scalar_param(0.0)
    )
    angle_limit_stiffness_value = max(0.0, min(1.0, float(angle_limit_stiffness)))
    angle_limit_stiffness_param = params.scalar_param(angle_limit_stiffness_value)
    max_distance_param = (
        params.curve_value_param_cached(curve_cache, "max_distance", max_distance, max_distance_curve, minimum=0.0)
        if use_max_distance
        else params.scalar_param(0.0)
    )
    backstop_radius_param = (
        params.float_param_cached(curve_cache, "backstop_radius", backstop_radius, minimum=0.0)
        if use_backstop
        else params.scalar_param(0.0)
    )
    backstop_distance_param = (
        params.curve_value_param_cached(curve_cache, "backstop_distance", backstop_distance, backstop_distance_curve, minimum=0.0)
        if use_backstop
        else params.scalar_param(0.0)
    )
    _add_timing(timing, add_timing, "param_curves", stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    damping_values = np.ascontiguousarray(
        np.clip(
            params.sample_param_cached(curve_cache, "damping", damping_param, stiffness_depths)
            * float(MC2SystemConstants.DAMPING_SCALE),
            0.0,
            1.0,
        ),
        dtype=np.float32,
    )
    distance_stiffness_values = (
        np.ascontiguousarray(
            np.clip(
                params.sample_param_cached(curve_cache, "distance_stiffness", distance_stiffness_param, stiffness_depths),
                0.0,
                1.0,
            ),
            dtype=np.float32,
        )
        if use_distance
        else zero_values_like(stiffness_depths)
    )
    bend_stiffness_values = (
        np.ascontiguousarray(
            np.clip(params.sample_param_cached(curve_cache, "bend_stiffness", bend_stiffness_param, stiffness_depths), 0.0, 1.0),
            dtype=np.float32,
        )
        if use_bend
        else zero_values_like(stiffness_depths)
    )
    angle_restoration_values = (
        np.ascontiguousarray(
            np.clip(
                params.sample_param_cached(curve_cache, "angle_restoration_stiffness", angle_restoration_param, stiffness_depths),
                0.0,
                1.0,
            ),
            dtype=np.float32,
        )
        if use_angle_restoration
        else zero_values_like(stiffness_depths)
    )
    angle_restoration_velocity_attenuation_values = (
        np.ascontiguousarray(
            np.clip(
                params.sample_param_cached(
                    curve_cache,
                    "angle_restoration_velocity_attenuation",
                    angle_restoration_velocity_attenuation_param,
                    stiffness_depths,
                ),
                0.0,
                1.0,
            ),
            dtype=np.float32,
        )
        if use_angle_restoration
        else zero_values_like(stiffness_depths)
    )
    angle_restoration_gravity_falloff_values = (
        scalar_values_like(stiffness_depths, angle_restoration_gravity_falloff_param["value"])
        if use_angle_restoration
        else zero_values_like(stiffness_depths)
    )
    angle_limit_values = (
        np.ascontiguousarray(
            np.clip(params.sample_param_cached(curve_cache, "angle_limit", angle_limit_param, stiffness_depths), 0.0, 180.0),
            dtype=np.float32,
        )
        if use_angle_limit
        else zero_values_like(stiffness_depths)
    )
    _add_timing(timing, add_timing, "stiffness_curves", stage_start)

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
        * float(world_scale_nonnegative)
    )
    collision_mode = max(0, min(2, int(collider_collision_mode))) if use_collider_collision else 0

    return MC2RuntimeParams(
        normal_axis=normal_axis_value,
        motion_enabled=motion_enabled,
        collision_mode=collision_mode,
        angle_limit_stiffness=angle_limit_stiffness_value,
        movement_speed_limit=movement_speed_limit_value,
        rotation_speed_limit=rotation_speed_limit_value,
        local_movement_speed_limit=local_movement_speed_limit_value,
        local_rotation_speed_limit=local_rotation_speed_limit_value,
        particle_speed_limit=particle_speed_limit_value,
        dynamic_friction=dynamic_friction,
        static_friction_speed=static_friction_speed,
        damping_param=damping_param,
        distance_stiffness_param=distance_stiffness_param,
        bend_stiffness_param=bend_stiffness_param,
        angle_restoration_param=angle_restoration_param,
        angle_restoration_velocity_attenuation_param=angle_restoration_velocity_attenuation_param,
        angle_restoration_gravity_falloff_param=angle_restoration_gravity_falloff_param,
        angle_limit_param=angle_limit_param,
        angle_limit_stiffness_param=angle_limit_stiffness_param,
        world_inertia_param=world_inertia_param,
        movement_inertia_smoothing_param=movement_inertia_smoothing_param,
        local_inertia_param=local_inertia_param,
        depth_inertia_param=depth_inertia_param,
        centrifugal_param=centrifugal_param,
        movement_speed_limit_param=movement_speed_limit_param,
        rotation_speed_limit_param=rotation_speed_limit_param,
        local_movement_speed_limit_param=local_movement_speed_limit_param,
        local_rotation_speed_limit_param=local_rotation_speed_limit_param,
        particle_speed_limit_param=particle_speed_limit_param,
        max_distance_param=max_distance_param,
        tether_compression_param=tether_compression_param,
        tether_stretch_param=tether_stretch_param,
        motion_stiffness_param=motion_stiffness_param,
        backstop_radius_param=backstop_radius_param,
        backstop_distance_param=backstop_distance_param,
        collider_friction_param=collider_friction_param,
        collider_collision_mode_param=params.scalar_param(float(collision_mode)),
        use_tether_param=component_slot(use_tether),
        use_distance_param=component_slot(use_distance),
        use_bend_param=component_slot(use_bend),
        use_angle_restoration_param=component_slot(use_angle_restoration),
        use_angle_limit_param=component_slot(use_angle_limit),
        use_max_distance_param=component_slot(use_max_distance),
        use_backstop_param=component_slot(use_backstop),
        use_collider_collision_param=component_slot(use_collider_collision),
        substep_damping_values=substep_damping_values(damping_values, substep_count),
        distance_stiffness_values=distance_stiffness_values,
        bend_stiffness_values=bend_stiffness_values,
        angle_restoration_values=angle_restoration_values,
        angle_restoration_velocity_attenuation_values=angle_restoration_velocity_attenuation_values,
        angle_restoration_gravity_falloff_values=angle_restoration_gravity_falloff_values,
        angle_limit_values=angle_limit_values,
    )


def sample_motion_params(
    curve_cache: dict,
    runtime: MC2RuntimeParams,
    depths: np.ndarray,
    world_scale_nonnegative: float,
    timing: dict | None = None,
    add_timing=None,
) -> MC2MotionSamples:
    stage_start = time.perf_counter() if timing is not None else None
    motion_depths = np.clip(np.ascontiguousarray(depths, dtype=np.float32) * np.ascontiguousarray(depths, dtype=np.float32), 0.0, 1.0)
    if runtime.motion_enabled:
        max_distances = np.ascontiguousarray(
            params.sample_param_cached(curve_cache, "max_distance_motion", runtime.max_distance_param, motion_depths)
            * float(world_scale_nonnegative),
            dtype=np.float32,
        )
        motion_stiffness_values = np.ascontiguousarray(
            np.clip(params.sample_param_cached(curve_cache, "motion_stiffness", runtime.motion_stiffness_param, motion_depths), 0.0, 1.0),
            dtype=np.float32,
        )
        backstop_radii = np.ascontiguousarray(
            params.sample_param_cached(curve_cache, "backstop_radius_motion", runtime.backstop_radius_param, motion_depths)
            * float(world_scale_nonnegative),
            dtype=np.float32,
        )
        backstop_distances = np.ascontiguousarray(
            params.sample_param_cached(curve_cache, "backstop_distance_motion", runtime.backstop_distance_param, motion_depths)
            * float(world_scale_nonnegative),
            dtype=np.float32,
        )
    else:
        max_distances = zero_values_like(motion_depths)
        motion_stiffness_values = zero_values_like(motion_depths)
        backstop_radii = zero_values_like(motion_depths)
        backstop_distances = zero_values_like(motion_depths)
    _add_timing(timing, add_timing, "motion_curves", stage_start)
    return MC2MotionSamples(
        max_distances=max_distances,
        motion_stiffness_values=motion_stiffness_values,
        backstop_radii=backstop_radii,
        backstop_distances=backstop_distances,
    )


def write_param_slots(next_state: dict, runtime: MC2RuntimeParams) -> None:
    param_slots = dict(next_state.get("param_slots") or {})
    param_slots.update(runtime.param_slots())
    next_state["param_slots"] = param_slots
