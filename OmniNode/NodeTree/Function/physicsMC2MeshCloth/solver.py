"""MeshCloth Python 求解调度。

本模块只处理单帧内的 predict / constraint / collision / motion / post 顺序。
节点入口负责 Blender cache、跳帧、reset、碰撞快照收集和 GN delta 写回。
"""

import time

import bpy
import numpy as np

from . import baseline, blender_io, collision, constraints, inertia, math_utils, native_bridge, runtime_params, state as mc2_state
from .constants import MC2SystemConstants


def _add_timing(timing: dict | None, stage: str, seconds: float) -> None:
    if timing is None:
        return
    stages = timing.setdefault("stages", {})
    stages[stage] = stages.get(stage, 0.0) + max(float(seconds), 0.0)


def _stage_start(timing: dict | None) -> float | None:
    return time.perf_counter() if timing is not None else None


def _end_stage(timing: dict | None, stage: str, start: float | None) -> None:
    if timing is None or start is None:
        return
    _add_timing(timing, stage, time.perf_counter() - start)


def _runtime_cache(runtime_caches: dict | None, name: str) -> dict:
    if isinstance(runtime_caches, dict):
        cache = runtime_caches.get(name)
        if not isinstance(cache, dict):
            cache = {}
            runtime_caches[name] = cache
        return cache
    raise RuntimeError("MC2 solver requires runtime cache slots from MC2RuntimeOwner")


def _native_runtime_slot(runtime_caches: dict | None = None) -> dict:
    cache = _runtime_cache(runtime_caches, "native_cache")
    slot = cache.get("abi")
    if not isinstance(slot, dict):
        slot = {}
        cache["abi"] = slot
    return slot


def _native_abi_view_from_cache(
    state: dict,
    obj: bpy.types.Object,
    colliders: list[dict] | None,
    solver_name: str,
    runtime_caches: dict | None = None,
    topology_state=None,
    base_pose_state=None,
    particle_state=None,
    center_state=None,
    param_slots: dict | None = None,
) -> dict:
    slot = _native_runtime_slot(runtime_caches)
    value = native_bridge.build_abi_view(
        obj,
        colliders,
        topology_state=topology_state,
        base_pose_state=base_pose_state,
        particle_state=particle_state,
        center_state=center_state,
        param_slots=param_slots,
    )
    slot["abi_view_current"] = {
        "solver": solver_name,
        "frame": state.get("frame"),
        "value": value,
    }
    return value


def _write_native_debug_view(
    native_slot: dict,
    state: dict,
    obj: bpy.types.Object,
    colliders: list[dict] | None,
    solver_name: str,
    runtime_caches: dict | None,
    enabled: bool,
    topology_state=None,
    base_pose_state=None,
    particle_state=None,
    center_state=None,
    param_slots: dict | None = None,
) -> None:
    native_slot["solver"] = solver_name
    if not enabled:
        # ABI 视图只用于调试检查，正常播放不能每帧重建这份大结构。
        native_slot.pop("abi_view", None)
        native_slot.pop("abi_view_current", None)
        native_slot.pop("collider_arrays", None)
        return
    abi_view = _native_abi_view_from_cache(
        state,
        obj,
        colliders,
        solver_name,
        runtime_caches,
        topology_state,
        base_pose_state,
        particle_state,
        center_state,
        param_slots,
    )
    native_slot["abi_view"] = abi_view
    native_slot["collider_arrays"] = abi_view["colliders"]


def _team_gravity_context(
    gravity_dir,
    gravity_power: float,
    gravity_falloff: float,
    inertia_state: dict,
) -> tuple[np.ndarray, float, float]:
    world_gravity_dir = math_utils.world_gravity(gravity_dir)
    gravity_power_value = max(float(gravity_power), 0.0)
    falloff = max(0.0, min(1.0, float(gravity_falloff)))
    gravity_dot = 1.0
    if float(np.dot(world_gravity_dir, world_gravity_dir)) > MC2SystemConstants.EPSILON:
        now_rotation = np.asarray(
            inertia_state.get("now_world_rotation", (0.0, 0.0, 0.0, 1.0)),
            dtype=np.float32,
        ).reshape(4)
        init_local = inertia_state.get("init_local_gravity_direction")
        if init_local is None:
            init_local = baseline.quat_rotate(baseline.quat_inverse(now_rotation), world_gravity_dir)
            inertia_state["init_local_gravity_direction"] = np.ascontiguousarray(init_local, dtype=np.float32)
        init_local = math_utils.safe_normal_np(
            np.asarray(init_local, dtype=np.float32).reshape(3),
            world_gravity_dir,
        )
        negative_direction = np.asarray(
            inertia_state.get("negative_scale_direction", (1.0, 1.0, 1.0)),
            dtype=np.float32,
        ).reshape(3)
        falloff_local = init_local.copy()
        if float(negative_direction[1]) < 0.0:
            falloff_local[1] *= -1.0
        falloff_world = math_utils.safe_normal_np(
            baseline.quat_rotate(now_rotation, falloff_local),
            world_gravity_dir,
        )
        gravity_dot = max(0.0, min(1.0, float(np.dot(falloff_world, world_gravity_dir)) * 0.5 + 0.5))
    # MC2 TeamStepUpdate: lerp(saturate(1 - gravityFalloff), 1, saturate(1 - gravityDot)).
    gravity_ratio = 1.0 - falloff * gravity_dot if gravity_power_value > 1.0e-6 else 1.0
    gravity_ratio = max(0.0, min(1.0, float(gravity_ratio)))
    return world_gravity_dir * gravity_power_value * gravity_ratio, gravity_dot, gravity_ratio


def _sync_gravity_runtime(runtime, depths: np.ndarray, gravity_dot: float, gravity_ratio: float) -> np.ndarray:
    # gravityDot 依赖当前 Center/inertia rotation，不能在参数曲线采样阶段提前解析。
    # 这里统一把 Team gravity 上下文同步回 runtime，并生成 angle restoration 消费的最终 falloff 数组。
    runtime.gravity_dot = max(0.0, min(1.0, float(gravity_dot)))
    runtime.gravity_ratio = max(0.0, float(gravity_ratio))
    adjusted_falloff = max(
        0.0,
        min(
            1.0,
            float(runtime.angle_restoration_gravity_falloff_param["value"]) * (1.0 - runtime.gravity_dot),
        ),
    )
    runtime.angle_restoration_gravity_falloff_values = runtime_params.scalar_values_like(depths, adjusted_falloff)
    return runtime.angle_restoration_gravity_falloff_values


def _team_blend_context(
    team_state: mc2_state.MC2TeamState,
    step_dt: float,
    substep_count: int,
    stablization_time_after_reset: float,
    blend_weight: float,
) -> tuple[np.ndarray, float, float]:
    previous_velocity = max(0.0, min(1.0, float(team_state.velocity_weight)))
    stabilize_time = max(0.0, min(1.0, float(stablization_time_after_reset)))
    weights = np.empty(max(1, int(substep_count)), dtype=np.float32)
    for index in range(len(weights)):
        if previous_velocity < 1.0:
            add_weight = float(step_dt) / stabilize_time if stabilize_time > 1.0e-6 else 1.0
            previous_velocity = max(0.0, min(1.0, previous_velocity + add_weight))
        weights[index] = previous_velocity
    user_blend = max(0.0, min(1.0, float(blend_weight)))
    distance_weight = max(0.0, min(1.0, float(team_state.distance_weight)))
    return (
        np.ascontiguousarray(weights, dtype=np.float32),
        previous_velocity,
        max(0.0, min(1.0, previous_velocity * user_blend * distance_weight)),
    )


def _blend_display_positions(base_positions: np.ndarray, display_positions: np.ndarray, blend_weight: float) -> np.ndarray:
    weight = max(0.0, min(1.0, float(blend_weight)))
    if weight >= 1.0 - MC2SystemConstants.EPSILON:
        return np.ascontiguousarray(display_positions, dtype=np.float32)
    base = np.ascontiguousarray(base_positions, dtype=np.float32)
    display = np.ascontiguousarray(display_positions, dtype=np.float32)
    return np.ascontiguousarray(base + (display - base) * weight, dtype=np.float32)


def _particle_array(particle_state, key: str) -> np.ndarray:
    if particle_state is None:
        raise RuntimeError("MC2 solver requires MC2ParticleState")
    return np.ascontiguousarray(getattr(particle_state, key), dtype=np.float32)


def _base_pose_array(base_pose_state, key: str) -> np.ndarray:
    if base_pose_state is None:
        raise RuntimeError("MC2 solver requires MC2BasePoseState")
    return np.ascontiguousarray(getattr(base_pose_state, key), dtype=np.float32)


def _topology_array(topology_state, key: str, dtype) -> np.ndarray:
    if topology_state is None:
        raise RuntimeError("MC2 solver requires MC2TopologyState")
    return np.ascontiguousarray(getattr(topology_state, key), dtype=dtype)


def _team_time_scale(team_state) -> float:
    try:
        value = float(getattr(team_state, "time_scale", 1.0))
    except (TypeError, ValueError):
        value = 1.0
    if not np.isfinite(value):
        return 1.0
    return max(0.0, value)


def _team_frame_delta_time(scene: bpy.types.Scene, team_state) -> float:
    return blender_io.scene_delta_time(scene) * _team_time_scale(team_state)


def _paused_state_for_time_scale(
    state: dict,
    team_state,
    frame_dt: float,
    step_dt: float,
    substep_count: int,
    timing: dict | None,
) -> dict:
    stage_start = time.perf_counter() if timing is not None else None
    next_state = mc2_state.inherit_runtime_slots(state, dict(state))
    team_state.apply_frame_context(
        frame_dt,
        step_dt,
        0,
        0,
        team_state.frame_interpolation,
        next_state,
        substep_count=substep_count,
    )
    team_state.mirror_to_legacy(next_state)
    if timing is not None:
        _add_timing(timing, "time_scale_pause", time.perf_counter() - stage_start)
    return next_state


def _apply_chain_param_overrides(runtime, state: dict, substep_count: int) -> None:
    """把 BoneCloth per-chain 参数覆盖注入 MC2RuntimeParams。

    BoneCloth controller 在 state["chain_param_overrides"] 里存入 {param_name: ndarray}，
    每条链展开成粒子数组。本函数在 build_runtime_params 之后、局部变量解包之前调用，
    同时替换 *_param dict（C++ param_slots 路径）和 *_values ndarray（Python solve 路径），
    保证两条执行路径都能拿到 per-chain 值。

    MeshCloth merged state 也会通过 state["param_slots"] 传入 per-particle 参数，
    这里统一转换成 runtime 覆盖，保证 Python/C++ 路径都拿到同一组数组。
    """
    import numpy as _np
    from . import params as _params
    from .runtime_params import substep_damping_values as _substep_damp

    overrides = {}
    chain_overrides = state.get("chain_param_overrides")
    if isinstance(chain_overrides, dict):
        overrides.update(chain_overrides)

    particle_count = len(getattr(runtime, "substep_damping_values", ()))
    param_slots = state.get("param_slots")
    if isinstance(param_slots, dict):
        for name, slot in param_slots.items():
            if name in overrides or not isinstance(slot, dict):
                continue
            if str(slot.get("mode", "")) != "per_particle":
                continue
            samples = slot.get("samples")
            if samples is None:
                continue
            arr = _np.ascontiguousarray(samples, dtype=_np.float32).reshape(-1)
            if len(arr) == particle_count:
                overrides[name] = arr

    if not overrides:
        return

    for param_name, arr in overrides.items():
        if not isinstance(arr, _np.ndarray) or len(arr) == 0:
            continue
        arr32 = _np.ascontiguousarray(arr, dtype=_np.float32)

        if param_name == "damping":
            runtime.damping_param = _params.per_particle_param(arr32, minimum=0.0, maximum=1.0)
            # substep_damping_values 是帧阻尼的 per-substep 推导值，需重算
            runtime.substep_damping_values = _substep_damp(arr32, substep_count)

        elif param_name == "distance_stiffness":
            runtime.distance_stiffness_param = _params.per_particle_param(arr32, minimum=0.0, maximum=1.0)
            runtime.distance_stiffness_values = arr32

        elif param_name == "bend_stiffness":
            runtime.bend_stiffness_param = _params.per_particle_param(arr32, minimum=0.0, maximum=1.0)
            runtime.bend_stiffness_values = arr32

        elif param_name == "angle_restoration_stiffness":
            runtime.angle_restoration_param = _params.per_particle_param(arr32, minimum=0.0, maximum=1.0)
            runtime.angle_restoration_values = arr32

        elif param_name == "angle_restoration_velocity_attenuation":
            runtime.angle_restoration_velocity_attenuation_param = _params.per_particle_param(arr32, minimum=0.0, maximum=1.0)
            runtime.angle_restoration_velocity_attenuation_values = arr32

        elif param_name == "angle_restoration_gravity_falloff":
            runtime.angle_restoration_gravity_falloff_param = _params.per_particle_param(arr32, minimum=0.0, maximum=1.0)
            runtime.angle_restoration_gravity_falloff_values = arr32

        elif param_name == "angle_limit":
            runtime.angle_limit_param = _params.per_particle_param(arr32, minimum=0.0, maximum=180.0)
            runtime.angle_limit_values = arr32

        elif param_name == "angle_limit_stiffness":
            runtime.angle_limit_stiffness_param = _params.per_particle_param(arr32, minimum=0.0, maximum=1.0)
            runtime.angle_limit_stiffness = float(_np.clip(arr32, 0.0, 1.0).mean())

        elif param_name == "tether_compression":
            runtime.tether_compression_param = _params.per_particle_param(arr32, minimum=0.0, maximum=1.0)

        elif param_name == "max_distance":
            runtime.max_distance_param = _params.per_particle_param(arr32, minimum=0.0)

        elif param_name == "motion_stiffness":
            runtime.motion_stiffness_param = _params.per_particle_param(arr32, minimum=0.0, maximum=1.0)

        elif param_name == "backstop_radius":
            runtime.backstop_radius_param = _params.per_particle_param(arr32, minimum=0.0)

        elif param_name == "backstop_distance":
            runtime.backstop_distance_param = _params.per_particle_param(arr32, minimum=0.0)


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
    gravity_falloff: float,
    stablization_time_after_reset: float,
    blend_weight: float,
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
    anchor_obj: bpy.types.Object | None,
    anchor_inertia: float,
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
    animation_pose_ratio: float,
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
    runtime_caches: dict | None = None,
    debug_native_view: bool = False,
    center_state: mc2_state.MC2CenterState | mc2_state.MC2RuntimeOwner | None = None,
    team_state: mc2_state.MC2TeamState | mc2_state.MC2RuntimeOwner | None = None,
) -> dict:
    stage_start = time.perf_counter() if timing is not None else None
    substage_start = _stage_start(timing)
    team_state_ref = mc2_state.team_state_for_solver(state, team_state)
    center_state_ref = mc2_state.coerce_center_state(center_state)
    colliders = collision.with_previous_collider_pose(
        colliders,
        mc2_state.previous_collider_snapshot_for_center(state, center_state_ref),
    )
    frame_inertia_state = mc2_state.inertia_state_for_center(state, center_state_ref, obj)
    particle_state_ref = mc2_state.particle_state_for_center(state, center_state_ref)
    base_pose_state_ref = mc2_state.base_pose_state_for_center(state, center_state_ref)
    topology_state_ref = mc2_state.topology_state_for_center(state, center_state_ref)
    positions = _particle_array(particle_state_ref, "next_positions")
    old_positions = _particle_array(particle_state_ref, "old_positions")
    base_positions = _base_pose_array(base_pose_state_ref, "base_positions")
    base_normals = _base_pose_array(base_pose_state_ref, "base_normals")
    base_rotations = _base_pose_array(base_pose_state_ref, "base_rotations")
    step_basic_positions = _base_pose_array(base_pose_state_ref, "step_basic_positions")
    step_basic_rotations = _base_pose_array(base_pose_state_ref, "step_basic_rotations")
    attributes = _topology_array(topology_state_ref, "attributes", np.uint8)
    depths = _topology_array(topology_state_ref, "depths", np.float32)
    friction = _particle_array(particle_state_ref, "friction")
    static_friction = _particle_array(particle_state_ref, "static_friction")
    velocity_positions = _particle_array(particle_state_ref, "velocity_positions")
    velocity = _particle_array(particle_state_ref, "velocity")
    real_velocity = _particle_array(particle_state_ref, "real_velocity")
    inv_masses = mc2_state.calc_inverse_masses(attributes, depths, friction)
    collision_radii = _topology_array(topology_state_ref, "collision_radii", np.float32)
    self_collision_inv_masses = _topology_array(topology_state_ref, "self_collision_inv_masses", np.float32)
    collided_by_groups = math_utils.clamp_group_mask(topology_state_ref.collided_by_groups)
    collision_normals = _particle_array(particle_state_ref, "collision_normals")
    collision_normals.fill(0.0)
    parent_indices = _topology_array(topology_state_ref, "parent_indices", np.int32)
    root_indices = _topology_array(topology_state_ref, "root_indices", np.int32)
    tether_rest_lengths = _topology_array(topology_state_ref, "tether_rest_lengths", np.float32)
    baseline_start = _topology_array(topology_state_ref, "baseline_start", np.int32)
    baseline_count = _topology_array(topology_state_ref, "baseline_count", np.int32)
    baseline_data = _topology_array(topology_state_ref, "baseline_data", np.int32)
    vertex_local_positions = _topology_array(topology_state_ref, "vertex_local_positions", np.float32)
    vertex_local_rotations = _topology_array(topology_state_ref, "vertex_local_rotations", np.float32)
    distance_start = _topology_array(topology_state_ref, "distance_start", np.int32)
    distance_count = _topology_array(topology_state_ref, "distance_count", np.int32)
    distance_data = _topology_array(topology_state_ref, "distance_data", np.int32)
    distance_rest = _topology_array(topology_state_ref, "distance_rest", np.float32)
    bend_distance_start = _topology_array(topology_state_ref, "bend_distance_start", np.int32)
    bend_distance_count = _topology_array(topology_state_ref, "bend_distance_count", np.int32)
    bend_distance_data = _topology_array(topology_state_ref, "bend_distance_data", np.int32)
    bend_distance_neighbor_rest = _topology_array(topology_state_ref, "bend_distance_neighbor_rest", np.float32)
    dihedral_pairs = _topology_array(topology_state_ref, "dihedral_pairs", np.int32)
    dihedral_rest_angles = _topology_array(topology_state_ref, "dihedral_rest_angles", np.float32)
    dihedral_signs = _topology_array(topology_state_ref, "dihedral_signs", np.int8)
    volume_pairs = _topology_array(topology_state_ref, "volume_pairs", np.int32)
    volume_rest = _topology_array(topology_state_ref, "volume_rest", np.float32)
    edges = _topology_array(topology_state_ref, "edges", np.int32)
    movable = inv_masses > MC2SystemConstants.EPSILON
    fixed = ~movable
    _end_stage(timing, "solve_setup.arrays", substage_start)

    substage_start = _stage_start(timing)
    frame_dt = _team_frame_delta_time(scene, team_state_ref)
    substep_count = max(1, min(16, int(substeps)))
    iteration_count = max(0, min(64, int(iterations)))
    step_dt = frame_dt / substep_count if substep_count > 0 else frame_dt
    if frame_dt <= MC2SystemConstants.EPSILON:
        return _paused_state_for_time_scale(state, team_state_ref, frame_dt, step_dt, substep_count, timing)
    gravity = math_utils.world_gravity(gravity_dir) * max(float(gravity_power), 0.0)
    world_scale = math_utils.matrix_scale_radius(obj.matrix_world)
    world_scale_nonnegative = max(float(world_scale), 0.0)
    base_pose_mode = mc2_state.base_pose_proxy_active(state, base_pose_state_ref)
    self_collision_enabled = bool(getattr(topology_state_ref, "self_collision_enabled", False))
    self_collision_surface_thickness = max(float(getattr(topology_state_ref, "self_collision_surface_thickness", 0.0)), 0.0)
    self_collision_mass = max(float(getattr(topology_state_ref, "self_collision_mass", 0.0)), 0.0)
    animation_pose_ratio_value = max(0.0, min(1.0, float(animation_pose_ratio)))
    team_state_ref.apply_solver_inputs(animation_pose_ratio_value, blend_weight, state)
    substep_velocity_weights, velocity_weight_value, blend_weight_value = _team_blend_context(
        team_state_ref,
        step_dt,
        substep_count,
        stablization_time_after_reset,
        blend_weight,
    )
    team_state_ref.apply_blend_context(velocity_weight_value, blend_weight_value, state)
    curve_cache = _runtime_cache(runtime_caches, "curve_cache")
    _end_stage(timing, "solve_setup.team", substage_start)

    substage_start = _stage_start(timing)
    runtime = runtime_params.build_runtime_params(
        curve_cache,
        depths,
        substep_count,
        world_scale_nonnegative,
        damping,
        damping_curve,
        use_tether,
        tether_compression,
        use_distance,
        distance_stiffness,
        distance_stiffness_curve,
        use_bend,
        bend_stiffness,
        bend_stiffness_curve,
        use_angle_restoration,
        angle_restoration_stiffness,
        angle_restoration_stiffness_curve,
        angle_restoration_velocity_attenuation,
        angle_restoration_velocity_attenuation_curve,
        angle_restoration_gravity_falloff,
        use_angle_limit,
        angle_limit,
        angle_limit_curve,
        angle_limit_stiffness,
        anchor_inertia,
        world_inertia,
        movement_inertia_smoothing,
        local_inertia,
        depth_inertia,
        centrifugal,
        movement_speed_limit,
        rotation_speed_limit,
        local_movement_speed_limit,
        local_rotation_speed_limit,
        particle_speed_limit,
        animation_pose_ratio_value,
        velocity_weight_value,
        blend_weight_value,
        use_max_distance,
        max_distance,
        max_distance_curve,
        use_backstop,
        backstop_radius,
        backstop_distance,
        backstop_distance_curve,
        motion_stiffness,
        normal_axis,
        use_collider_collision,
        collider_friction,
        collider_collision_mode,
        timing,
        _add_timing,
        timing_prefix="solve_setup.params",
    )
    # BoneCloth per-chain / MeshCloth merged per-particle 参数覆盖。
    _apply_chain_param_overrides(runtime, state, substep_count)
    _end_stage(timing, "solve_setup.params", substage_start)

    substage_start = _stage_start(timing)
    substep_damping_values = runtime.substep_damping_values
    distance_stiffness_values = runtime.distance_stiffness_values
    bend_stiffness_values = runtime.bend_stiffness_values
    angle_restoration_values = runtime.angle_restoration_values
    angle_restoration_velocity_attenuation_values = runtime.angle_restoration_velocity_attenuation_values
    angle_restoration_gravity_falloff_values = runtime.angle_restoration_gravity_falloff_values
    angle_limit_values = runtime.angle_limit_values
    angle_limit_stiffness_value = runtime.angle_limit_stiffness
    normal_axis_value = runtime.normal_axis
    world_inertia_param = runtime.world_inertia_param
    movement_inertia_smoothing_param = runtime.movement_inertia_smoothing_param
    local_inertia_param = runtime.local_inertia_param
    depth_inertia_param = runtime.depth_inertia_param
    centrifugal_param = runtime.centrifugal_param
    movement_speed_limit_value = runtime.movement_speed_limit
    rotation_speed_limit_value = runtime.rotation_speed_limit
    local_movement_speed_limit_value = runtime.local_movement_speed_limit
    local_rotation_speed_limit_value = runtime.local_rotation_speed_limit
    particle_speed_limit_value = runtime.particle_speed_limit
    tether_compression_param = runtime.tether_compression_param
    tether_stretch_param = runtime.tether_stretch_param
    max_distance_param = runtime.max_distance_param
    motion_stiffness_param = runtime.motion_stiffness_param
    backstop_radius_param = runtime.backstop_radius_param
    backstop_distance_param = runtime.backstop_distance_param
    motion_enabled = runtime.motion_enabled
    dynamic_friction = runtime.dynamic_friction
    static_friction_speed = runtime.static_friction_speed
    collision_mode = runtime.collision_mode
    runtime.velocity_weight = velocity_weight_value
    runtime.blend_weight = blend_weight_value
    _end_stage(timing, "solve_setup.param_unpack", substage_start)

    substage_start = _stage_start(timing)
    has_collision = collision_mode != 0 and bool(colliders) and bool(collided_by_groups) and bool(
        np.any(collision_radii > MC2SystemConstants.EPSILON)
    )
    collider_arrays = (
        collision.collider_arrays_for_native(
            obj,
            colliders,
            topology_state_ref,
            excluded_owner_ptrs=state.get("collider_owner_exclusion_ptrs"),
        )
        if has_collision
        else None
    )
    _end_stage(timing, "solve_setup.collider_abi", substage_start)

    substage_start = _stage_start(timing)
    if base_pose_mode:
        # BasePose 模式下，骨架/对象级基础运动已经通过 base_positions 输入。
        # 这里禁止再把写入对象矩阵变化当作整体惯性位移，避免双重变换和 Python 顶点循环卡顿。
        inertia_state = inertia.prepare_frame(
            frame_inertia_state,
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
            frame_inertia_state,
            obj,
            frame_dt,
            float(world_inertia_param["value"]),
            float(movement_inertia_smoothing_param["value"]),
            movement_speed_limit_value * max(float(world_scale), 0.0) if movement_speed_limit_value >= 0.0 else -1.0,
            rotation_speed_limit_value,
            int(teleport_mode),
            float(teleport_distance) * max(float(world_scale), 0.0),
            float(teleport_rotation),
            anchor_obj,
            float(runtime.anchor_inertia_param["value"]),
        )
    mc2_state.set_inertia_state_for_center(state, inertia_state, center_state_ref)
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
        display_positions = _particle_array(particle_state_ref, "display_positions")
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
    _end_stage(timing, "solve_setup.inertia", substage_start)

    substage_start = _stage_start(timing)
    gravity, gravity_dot, gravity_ratio = _team_gravity_context(
        gravity_dir,
        gravity_power,
        gravity_falloff,
        inertia_state,
    )
    if center_state_ref is not None:
        center_state_ref.refresh_inertia_summary()
    team_state_ref.apply_gravity_context(gravity_dot, gravity_ratio, state)
    angle_restoration_gravity_falloff_values = _sync_gravity_runtime(
        runtime,
        depths,
        team_state_ref.gravity_dot,
        team_state_ref.gravity_ratio,
    )
    _end_stage(timing, "solve_setup.gravity", substage_start)
    if timing is not None:
        _add_timing(timing, "solve_setup", time.perf_counter() - stage_start)

    for _substep in range(substep_count):
        # MC2 的 AnimationPoseRatio 同时影响 baseline pose 与 distance rest lerp。
        # ratio>0 时独立 native distance kernel 暂不支持 animated rest，走 Python fallback。
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
            parent_indices,
            baseline_start,
            baseline_count,
            baseline_data,
            vertex_local_positions,
            vertex_local_rotations,
            animation_pose_ratio_value,
        )
        if native_step_basic_pose is None:
            step_basic_positions, step_basic_rotations = baseline.update_step_basic_pose(
                base_positions,
                base_rotations,
                parent_indices,
                baseline_start,
                baseline_count,
                baseline_data,
                vertex_local_positions,
                vertex_local_rotations,
                animation_pose_ratio_value,
            )
        else:
            step_basic_positions, step_basic_rotations = native_step_basic_pose
        if timing is not None:
            _add_timing(timing, "baseline", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        inv_masses = mc2_state.calc_inverse_masses(attributes, depths, friction)
        if self_collision_enabled:
            self_collision_inv_masses = mc2_state.calc_self_collision_inverse_masses(
                attributes,
                depths,
                friction,
                getattr(topology_state_ref, "self_collision_mass", 0.0),
            )
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
            velocity[movable] *= float(substep_velocity_weights[_substep])
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
                root_indices,
                tether_rest_lengths,
                velocity_positions,
                1.0,
                float(tether_compression_param["value"]),
                float(tether_stretch_param["value"]),
            ):
                constraints.project_tether(
                    positions,
                    inv_masses,
                    root_indices,
                    tether_rest_lengths,
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
                    edges,
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
                        edges,
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
                projected = False
                if animation_pose_ratio_value <= MC2SystemConstants.EPSILON:
                    projected = native_bridge.project_neighbor_constraints(
                        positions,
                        inv_masses,
                        distance_start,
                        distance_count,
                        distance_data,
                        distance_rest,
                        distance_stiffness_values,
                        velocity_positions,
                        MC2SystemConstants.DISTANCE_VELOCITY_ATTENUATION,
                    )
                if not projected:
                    constraints.project_neighbor_constraints(
                        positions,
                        inv_masses,
                        distance_start,
                        distance_count,
                        distance_data,
                        distance_rest,
                        distance_stiffness_values,
                        velocity_positions,
                        MC2SystemConstants.DISTANCE_VELOCITY_ATTENUATION,
                        base_positions,
                        animation_pose_ratio_value,
                    )
                if timing is not None:
                    _add_timing(timing, "distance", time.perf_counter() - stage_start)

            if use_angle_restoration or use_angle_limit:
                # angle 复用同一批 baseline / step_basic 数据，恢复与限制共用一轮求解。
                stage_start = time.perf_counter() if timing is not None else None
                if not native_bridge.project_angle_constraints(
                    positions,
                    inv_masses,
                    parent_indices,
                    baseline_start,
                    baseline_count,
                    baseline_data,
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
                        parent_indices,
                        baseline_start,
                        baseline_count,
                        baseline_data,
                        step_basic_positions,
                        step_basic_rotations,
                        vertex_local_positions,
                        vertex_local_rotations,
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
                if len(dihedral_pairs) > 0 or len(volume_pairs) > 0:
                    if not native_bridge.project_triangle_bending(
                        positions,
                        inv_masses,
                        dihedral_pairs,
                        dihedral_rest_angles,
                        dihedral_signs,
                        volume_pairs,
                        volume_rest,
                        bend_stiffness_values,
                    ):
                        constraints.project_triangle_bending(
                            positions,
                            inv_masses,
                            dihedral_pairs,
                            dihedral_rest_angles,
                            dihedral_signs,
                            volume_pairs,
                            volume_rest,
                            bend_stiffness_values,
                        )
                else:
                    if not native_bridge.project_neighbor_constraints(
                        positions,
                        inv_masses,
                        bend_distance_start,
                        bend_distance_count,
                        bend_distance_data,
                        bend_distance_neighbor_rest,
                        bend_stiffness_values,
                        velocity_positions,
                        MC2SystemConstants.DISTANCE_VELOCITY_ATTENUATION,
                    ):
                        constraints.project_neighbor_constraints(
                            positions,
                            inv_masses,
                            bend_distance_start,
                            bend_distance_count,
                            bend_distance_data,
                            bend_distance_neighbor_rest,
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
                        edges,
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
                            edges,
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
                projected = False
                if animation_pose_ratio_value <= MC2SystemConstants.EPSILON:
                    projected = native_bridge.project_neighbor_constraints(
                        positions,
                        inv_masses,
                        distance_start,
                        distance_count,
                        distance_data,
                        distance_rest,
                        distance_stiffness_values,
                        velocity_positions,
                        MC2SystemConstants.DISTANCE_VELOCITY_ATTENUATION,
                    )
                if not projected:
                    constraints.project_neighbor_constraints(
                        positions,
                        inv_masses,
                        distance_start,
                        distance_count,
                        distance_data,
                        distance_rest,
                        distance_stiffness_values,
                        velocity_positions,
                        MC2SystemConstants.DISTANCE_VELOCITY_ATTENUATION,
                        base_positions,
                        animation_pose_ratio_value,
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

        has_self_collision = (
            self_collision_enabled
            and self_collision_surface_thickness > MC2SystemConstants.EPSILON
            and bool(np.any(self_collision_inv_masses > MC2SystemConstants.EPSILON))
            and (len(topology_state_ref.edges) > 0 or len(topology_state_ref.triangles) > 0)
        )
        if has_self_collision:
            stage_start = time.perf_counter() if timing is not None else None
            collision.project_self_collisions(
                positions,
                old_positions,
                self_collision_inv_masses,
                topology_state_ref.edges,
                topology_state_ref.triangles,
                attributes,
                self_collision_surface_thickness * world_scale_nonnegative,
                collision_normals,
                friction,
            )
            if timing is not None:
                _add_timing(timing, "self_collision", time.perf_counter() - stage_start)

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
        substep_velocity_weight = float(substep_velocity_weights[_substep])
        if substep_velocity_weight < 1.0 - MC2SystemConstants.EPSILON:
            velocity[movable] *= substep_velocity_weight
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
    next_state = mc2_state.inherit_runtime_slots(state, dict(state))
    team_state_ref.apply_frame_context(
        frame_dt,
        step_dt,
        1,
        0,
        team_state_ref.frame_interpolation,
        next_state,
        substep_count=substep_count,
    )
    team_state_ref.mirror_to_legacy(next_state)
    next_state["substep_damping"] = float(np.max(substep_damping_values)) if len(substep_damping_values) else 0.0
    committed_inertia_state = mc2_state.commit_inertia_state_for_center(
        next_state,
        inertia_state,
        obj,
        center_state_ref,
    )
    if center_state_ref is not None:
        center_state_ref.refresh_inertia_summary()
        next_state["scale_ratio"] = float(center_state_ref.scale_ratio or world_scale)
        next_state["negative_scale_sign"] = int(center_state_ref.negative_scale_sign or 1)
        negative_scale_direction = center_state_ref.negative_scale_direction
    else:
        next_state["scale_ratio"] = float(committed_inertia_state.get("scale_ratio", world_scale) or world_scale)
        next_state["negative_scale_sign"] = int(committed_inertia_state.get("negative_scale_sign", 1) or 1)
        negative_scale_direction = committed_inertia_state.get("negative_scale_direction")
    team_state_ref.apply_scale_context(
        next_state["scale_ratio"],
        next_state["negative_scale_sign"],
        next_state,
        negative_scale_direction,
    )
    display_positions = native_bridge.calculate_display_positions(
        positions,
        real_velocity,
        root_indices,
        frame_dt,
        MC2SystemConstants.MAX_DISTANCE_RATIO_FUTURE_PREDICTION,
    )
    if display_positions is None:
        display_positions = _calc_display_positions(
            positions,
            real_velocity,
            root_indices,
            frame_dt,
        )
    display_positions = _blend_display_positions(base_positions, display_positions, blend_weight_value)
    mc2_state.commit_particle_state_for_center(
        next_state,
        center_state_ref,
        next_positions=positions,
        old_positions=old_positions,
        velocity_positions=velocity_positions,
        display_positions=display_positions,
        velocity=velocity,
        real_velocity=real_velocity,
        friction=friction,
        static_friction=static_friction,
        collision_normals=collision_normals,
        inv_masses=inv_masses,
    )
    if center_state_ref is None:
        next_state["next_positions"] = np.ascontiguousarray(positions, dtype=np.float32)
        next_state["old_positions"] = np.ascontiguousarray(old_positions, dtype=np.float32)
        next_state["display_positions"] = np.ascontiguousarray(display_positions, dtype=np.float32)
        next_state["velocity_positions"] = np.ascontiguousarray(velocity_positions, dtype=np.float32)
        next_state["velocity"] = np.ascontiguousarray(velocity, dtype=np.float32)
        next_state["real_velocity"] = np.ascontiguousarray(real_velocity, dtype=np.float32)
        next_state["friction"] = np.ascontiguousarray(friction, dtype=np.float32)
        next_state["static_friction"] = np.ascontiguousarray(static_friction, dtype=np.float32)
        next_state["collision_normals"] = np.ascontiguousarray(collision_normals, dtype=np.float32)
        next_state["inv_masses"] = np.ascontiguousarray(inv_masses, dtype=np.float32)
    proxy_ptr, proxy_name, proxy_frame = mc2_state.base_pose_proxy_metadata(state, base_pose_state_ref)
    mc2_state.commit_base_pose_state_for_center(
        next_state,
        center_state_ref,
        base_positions=base_positions,
        base_normals=base_normals,
        base_rotations=base_rotations,
        step_basic_positions=step_basic_positions,
        step_basic_rotations=step_basic_rotations,
        proxy_ptr=proxy_ptr,
        proxy_name=proxy_name,
        proxy_frame=proxy_frame,
    )
    if center_state_ref is None:
        next_state["step_basic_positions"] = np.ascontiguousarray(step_basic_positions, dtype=np.float32)
        next_state["step_basic_rotations"] = np.ascontiguousarray(step_basic_rotations, dtype=np.float32)
    mc2_state.set_previous_collider_snapshot_for_center(
        next_state,
        collision.compact_collider_snapshot(colliders),
        center_state_ref,
    )
    param_slots = runtime.param_slots()
    runtime_params.write_param_slots(next_state, runtime, param_slots)

    native_slot = _native_runtime_slot(runtime_caches)
    _write_native_debug_view(
        native_slot,
        next_state,
        obj,
        colliders,
        "py",
        runtime_caches,
        debug_native_view,
        topology_state_ref,
        base_pose_state_ref,
        particle_state_ref,
        center_state_ref,
        param_slots,
    )
    mc2_state.feature_slots(next_state)["native"] = native_slot
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
    gravity_falloff: float,
    stablization_time_after_reset: float,
    blend_weight: float,
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
    anchor_obj: bpy.types.Object | None,
    anchor_inertia: float,
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
    animation_pose_ratio: float,
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
    runtime_caches: dict | None = None,
    debug_native_view: bool = False,
    center_state: mc2_state.MC2CenterState | mc2_state.MC2RuntimeOwner | None = None,
    team_state: mc2_state.MC2TeamState | mc2_state.MC2RuntimeOwner | None = None,
) -> dict:
    # native_core 路径尽量保持和 Python 求解同一套顺序：
    # 输入整理 -> 曲线采样 -> substep inertia -> motion 采样 -> C++ 核心求解 -> 状态回填。
    stage_start = time.perf_counter() if timing is not None else None
    substage_start = _stage_start(timing)
    if not native_bridge.has_function("solve_meshcloth_mc2"):
        status = native_bridge.native_status("solve_meshcloth_mc2")
        raise RuntimeError(f"MC2 C++ backend is unavailable: {status}")
    team_state_ref = mc2_state.team_state_for_solver(state, team_state)
    center_state_ref = mc2_state.coerce_center_state(center_state)
    colliders = collision.with_previous_collider_pose(
        colliders,
        mc2_state.previous_collider_snapshot_for_center(state, center_state_ref),
    )
    frame_inertia_state = mc2_state.inertia_state_for_center(state, center_state_ref, obj)
    particle_state_ref = mc2_state.particle_state_for_center(state, center_state_ref)
    base_pose_state_ref = mc2_state.base_pose_state_for_center(state, center_state_ref)
    topology_state_ref = mc2_state.topology_state_for_center(state, center_state_ref)

    positions = _particle_array(particle_state_ref, "next_positions")
    old_positions = _particle_array(particle_state_ref, "old_positions")
    base_positions = _base_pose_array(base_pose_state_ref, "base_positions")
    base_normals = _base_pose_array(base_pose_state_ref, "base_normals")
    base_rotations = _base_pose_array(base_pose_state_ref, "base_rotations")
    step_basic_positions = _base_pose_array(base_pose_state_ref, "step_basic_positions")
    step_basic_rotations = _base_pose_array(base_pose_state_ref, "step_basic_rotations")
    attributes = _topology_array(topology_state_ref, "attributes", np.uint8)
    depths = _topology_array(topology_state_ref, "depths", np.float32)
    friction = _particle_array(particle_state_ref, "friction")
    static_friction = _particle_array(particle_state_ref, "static_friction")
    velocity_positions = _particle_array(particle_state_ref, "velocity_positions")
    velocity = _particle_array(particle_state_ref, "velocity")
    real_velocity = _particle_array(particle_state_ref, "real_velocity")
    inv_masses = mc2_state.calc_inverse_masses(
        attributes,
        depths,
        friction,
    )
    collision_radii = _topology_array(topology_state_ref, "collision_radii", np.float32)
    collided_by_groups = math_utils.clamp_group_mask(topology_state_ref.collided_by_groups)
    collision_normals = _particle_array(particle_state_ref, "collision_normals")
    collision_normals.fill(0.0)
    _end_stage(timing, "solve_setup.arrays", substage_start)

    substage_start = _stage_start(timing)
    frame_dt = _team_frame_delta_time(scene, team_state_ref)
    substep_count = max(1, min(16, int(substeps)))
    iteration_count = max(0, min(64, int(iterations)))
    step_dt = frame_dt / substep_count if substep_count > 0 else frame_dt
    if frame_dt <= MC2SystemConstants.EPSILON:
        return _paused_state_for_time_scale(state, team_state_ref, frame_dt, step_dt, substep_count, timing)
    gravity = math_utils.world_gravity(gravity_dir) * max(float(gravity_power), 0.0)
    world_scale = math_utils.matrix_scale_radius(obj.matrix_world)
    world_scale_nonnegative = max(float(world_scale), 0.0)
    base_pose_mode = mc2_state.base_pose_proxy_active(state, base_pose_state_ref)
    self_collision_enabled = bool(getattr(topology_state_ref, "self_collision_enabled", False))
    self_collision_surface_thickness = max(float(getattr(topology_state_ref, "self_collision_surface_thickness", 0.0)), 0.0)
    self_collision_mass = max(float(getattr(topology_state_ref, "self_collision_mass", 0.0)), 0.0)
    animation_pose_ratio_value = max(0.0, min(1.0, float(animation_pose_ratio)))
    team_state_ref.apply_solver_inputs(animation_pose_ratio_value, blend_weight, state)
    substep_velocity_weights, velocity_weight_value, blend_weight_value = _team_blend_context(
        team_state_ref,
        step_dt,
        substep_count,
        stablization_time_after_reset,
        blend_weight,
    )
    team_state_ref.apply_blend_context(velocity_weight_value, blend_weight_value, state)
    curve_cache = _runtime_cache(runtime_caches, "curve_cache")
    _end_stage(timing, "solve_setup.team", substage_start)

    substage_start = _stage_start(timing)
    runtime = runtime_params.build_runtime_params(
        curve_cache,
        depths,
        substep_count,
        world_scale_nonnegative,
        damping,
        damping_curve,
        use_tether,
        tether_compression,
        use_distance,
        distance_stiffness,
        distance_stiffness_curve,
        use_bend,
        bend_stiffness,
        bend_stiffness_curve,
        use_angle_restoration,
        angle_restoration_stiffness,
        angle_restoration_stiffness_curve,
        angle_restoration_velocity_attenuation,
        angle_restoration_velocity_attenuation_curve,
        angle_restoration_gravity_falloff,
        use_angle_limit,
        angle_limit,
        angle_limit_curve,
        angle_limit_stiffness,
        anchor_inertia,
        world_inertia,
        movement_inertia_smoothing,
        local_inertia,
        depth_inertia,
        centrifugal,
        movement_speed_limit,
        rotation_speed_limit,
        local_movement_speed_limit,
        local_rotation_speed_limit,
        particle_speed_limit,
        animation_pose_ratio_value,
        velocity_weight_value,
        blend_weight_value,
        use_max_distance,
        max_distance,
        max_distance_curve,
        use_backstop,
        backstop_radius,
        backstop_distance,
        backstop_distance_curve,
        motion_stiffness,
        normal_axis,
        use_collider_collision,
        collider_friction,
        collider_collision_mode,
        timing,
        _add_timing,
        timing_prefix="solve_setup.params",
    )
    # BoneCloth per-chain / MeshCloth merged per-particle 参数覆盖。
    _apply_chain_param_overrides(runtime, state, substep_count)
    _end_stage(timing, "solve_setup.params", substage_start)

    substage_start = _stage_start(timing)
    native_param_context = mc2_state.update_native_context_keys(
        state,
        runtime,
        center_state_ref,
        topology_state_ref,
    )
    _end_stage(timing, "solve_setup.native_context", substage_start)

    substage_start = _stage_start(timing)
    substep_damping_values = runtime.substep_damping_values
    distance_stiffness_values = runtime.distance_stiffness_values
    bend_stiffness_values = runtime.bend_stiffness_values
    angle_restoration_values = runtime.angle_restoration_values
    angle_restoration_velocity_attenuation_values = runtime.angle_restoration_velocity_attenuation_values
    angle_restoration_gravity_falloff_values = runtime.angle_restoration_gravity_falloff_values
    angle_limit_values = runtime.angle_limit_values
    angle_limit_stiffness_value = runtime.angle_limit_stiffness
    normal_axis_value = runtime.normal_axis
    world_inertia_param = runtime.world_inertia_param
    movement_inertia_smoothing_param = runtime.movement_inertia_smoothing_param
    local_inertia_param = runtime.local_inertia_param
    depth_inertia_param = runtime.depth_inertia_param
    centrifugal_param = runtime.centrifugal_param
    movement_speed_limit_value = runtime.movement_speed_limit
    rotation_speed_limit_value = runtime.rotation_speed_limit
    local_movement_speed_limit_value = runtime.local_movement_speed_limit
    local_rotation_speed_limit_value = runtime.local_rotation_speed_limit
    particle_speed_limit_value = runtime.particle_speed_limit
    tether_compression_param = runtime.tether_compression_param
    tether_stretch_param = runtime.tether_stretch_param
    max_distance_param = runtime.max_distance_param
    motion_stiffness_param = runtime.motion_stiffness_param
    backstop_radius_param = runtime.backstop_radius_param
    backstop_distance_param = runtime.backstop_distance_param
    motion_enabled = runtime.motion_enabled
    dynamic_friction = runtime.dynamic_friction
    static_friction_speed = runtime.static_friction_speed
    collision_mode = runtime.collision_mode
    runtime.velocity_weight = velocity_weight_value
    runtime.blend_weight = blend_weight_value
    _end_stage(timing, "solve_setup.param_unpack", substage_start)

    substage_start = _stage_start(timing)
    has_collision = collision_mode != 0 and bool(colliders) and bool(collided_by_groups) and bool(
        np.any(collision_radii > MC2SystemConstants.EPSILON)
    )
    collider_arrays = (
        collision.collider_arrays_for_native(
            obj,
            colliders,
            topology_state_ref,
            excluded_owner_ptrs=state.get("collider_owner_exclusion_ptrs"),
        )
        if has_collision
        else None
    )
    _end_stage(timing, "solve_setup.collider_abi", substage_start)

    substage_start = _stage_start(timing)
    if base_pose_mode:
        # BasePose 模式下基础动画来自只读代理，写入对象矩阵不再驱动物理整体惯性。
        # 这能避免移动骨架对象时 solve_setup 进入 apply_frame_shift 顶点循环。
        inertia_state = inertia.prepare_frame(
            frame_inertia_state,
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
            frame_inertia_state,
            obj,
            frame_dt,
            float(world_inertia_param["value"]),
            float(movement_inertia_smoothing_param["value"]),
            movement_speed_limit_value * world_scale_nonnegative if movement_speed_limit_value >= 0.0 else -1.0,
            rotation_speed_limit_value,
            int(teleport_mode),
            float(teleport_distance) * world_scale_nonnegative,
            float(teleport_rotation),
            anchor_obj,
            float(runtime.anchor_inertia_param["value"]),
        )
    mc2_state.set_inertia_state_for_center(state, inertia_state, center_state_ref)
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
        display_positions = _particle_array(particle_state_ref, "display_positions")
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
    _end_stage(timing, "solve_setup.inertia", substage_start)

    substage_start = _stage_start(timing)
    gravity, gravity_dot, gravity_ratio = _team_gravity_context(
        gravity_dir,
        gravity_power,
        gravity_falloff,
        inertia_state,
    )
    if center_state_ref is not None:
        center_state_ref.refresh_inertia_summary()
    team_state_ref.apply_gravity_context(gravity_dot, gravity_ratio, state)
    angle_restoration_gravity_falloff_values = _sync_gravity_runtime(
        runtime,
        depths,
        team_state_ref.gravity_dot,
        team_state_ref.gravity_ratio,
    )
    _end_stage(timing, "solve_setup.gravity", substage_start)

    substage_start = _stage_start(timing)
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
    _end_stage(timing, "solve_setup.substep_inertia", substage_start)

    substage_start = _stage_start(timing)
    motion_samples = runtime_params.sample_motion_params(
        curve_cache,
        runtime,
        depths,
        world_scale_nonnegative,
        timing,
        _add_timing,
        timing_prefix="solve_setup.motion_samples",
    )
    _end_stage(timing, "solve_setup.motion_samples", substage_start)

    substage_start = _stage_start(timing)
    particle_speed_limit_scaled = (
        particle_speed_limit_value * world_scale_nonnegative
        if particle_speed_limit_value >= 0.0
        else -1.0
    )

    param_arrays = {
        "distance_stiffness_values": distance_stiffness_values,
        "bend_stiffness_values": bend_stiffness_values,
        "angle_restoration_values": angle_restoration_values,
        "angle_restoration_velocity_attenuation_values": angle_restoration_velocity_attenuation_values,
        "angle_restoration_gravity_falloff_values": angle_restoration_gravity_falloff_values,
        "angle_limit_values": angle_limit_values,
        "substep_damping_values": substep_damping_values,
        "max_distances": motion_samples.max_distances,
        "motion_stiffness_values": motion_samples.motion_stiffness_values,
        "backstop_radii": motion_samples.backstop_radii,
        "backstop_distances": motion_samples.backstop_distances,
    }
    context_stage_start = _stage_start(timing)
    native_context = mc2_state.ensure_native_context_for_center(state, center_state_ref)
    native_param_context = mc2_state.update_native_context_keys(
        state,
        runtime,
        center_state_ref,
        topology_state_ref,
    )
    static_arrays = native_context.upload_static_arrays(topology_state_ref, base_pose_state_ref)
    native_params_ready = bool(
        native_context.upload_param_arrays(param_arrays)
        and native_bridge.has_function("solve_meshcloth_mc2_context_cached_params")
    )
    _end_stage(timing, "solve_setup.native_context", context_stage_start)
    use_native_context_solve = bool(
        native_context.handle is not None
        and native_context.native_static_ready
        and native_bridge.has_function("solve_meshcloth_mc2_context")
    )
    arrays = {} if use_native_context_solve else dict(static_arrays)
    arrays.update(
        native_bridge.dynamic_state_arrays_for_native(
            particle_state_ref,
            base_pose_state_ref,
            topology_state_ref,
            center_state_ref,
        )
    )
    arrays.update(
        {
            "positions": np.ascontiguousarray(positions, dtype=np.float32),
            "old_positions": np.ascontiguousarray(old_positions, dtype=np.float32),
            "base_positions": np.ascontiguousarray(base_positions, dtype=np.float32),
            "base_normals": np.ascontiguousarray(base_normals, dtype=np.float32),
            "base_rotations": np.ascontiguousarray(base_rotations, dtype=np.float32),
            "step_basic_positions": np.ascontiguousarray(step_basic_positions, dtype=np.float32),
            "step_basic_rotations": np.ascontiguousarray(step_basic_rotations, dtype=np.float32),
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
    _end_stage(timing, "solve_setup.native_arrays", substage_start)
    if timing is not None:
        _add_timing(timing, "solve_setup", time.perf_counter() - stage_start)

    # C++ 核心前先构建与 Python 路径同构的运行时数组。
    stage_start = time.perf_counter() if timing is not None else None
    solved = native_bridge.solve_meshcloth_core(
        arrays,
        context_handle=native_context.handle if use_native_context_solve else None,
        context_params_cached=native_params_ready if use_native_context_solve else False,
        distance_stiffness_values=distance_stiffness_values,
        bend_stiffness_values=bend_stiffness_values,
        angle_restoration_values=angle_restoration_values,
        angle_restoration_velocity_attenuation_values=angle_restoration_velocity_attenuation_values,
        angle_restoration_gravity_falloff_values=angle_restoration_gravity_falloff_values,
        angle_limit_values=angle_limit_values,
        substep_damping_values=substep_damping_values,
        max_distances=motion_samples.max_distances,
        motion_stiffness_values=motion_samples.motion_stiffness_values,
        backstop_radii=motion_samples.backstop_radii,
        backstop_distances=motion_samples.backstop_distances,
        collider_arrays=collider_arrays,
        substep_inertia_arrays=substep_inertia_arrays,
        substep_velocity_weights=substep_velocity_weights,
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
        animation_pose_ratio=animation_pose_ratio_value,
        blend_weight=blend_weight_value,
        self_collision_enabled=self_collision_enabled,
        self_collision_surface_thickness=self_collision_surface_thickness * world_scale_nonnegative,
        self_collision_mass=self_collision_mass,
    )
    if timing is not None:
        _add_timing(timing, "native_core", time.perf_counter() - stage_start)
    if not solved:
        status = native_bridge.native_status("solve_meshcloth_mc2")
        raise RuntimeError(f"MC2 C++ backend solve failed or is unavailable: {status}")

    stage_start = time.perf_counter() if timing is not None else None
    next_state = mc2_state.inherit_runtime_slots(state, dict(state))
    team_state_ref.apply_frame_context(
        frame_dt,
        step_dt,
        1,
        0,
        team_state_ref.frame_interpolation,
        next_state,
        substep_count=substep_count,
    )
    team_state_ref.mirror_to_legacy(next_state)
    next_state["substep_damping"] = float(np.max(substep_damping_values)) if len(substep_damping_values) else 0.0
    committed_inertia_state = mc2_state.commit_inertia_state_for_center(
        next_state,
        inertia_state,
        obj,
        center_state_ref,
    )
    if center_state_ref is not None:
        center_state_ref.refresh_inertia_summary()
        next_state["scale_ratio"] = float(center_state_ref.scale_ratio or world_scale_nonnegative)
        next_state["negative_scale_sign"] = int(center_state_ref.negative_scale_sign or 1)
        negative_scale_direction = center_state_ref.negative_scale_direction
    else:
        next_state["scale_ratio"] = float(
            committed_inertia_state.get("scale_ratio", world_scale_nonnegative) or world_scale_nonnegative
        )
        next_state["negative_scale_sign"] = int(committed_inertia_state.get("negative_scale_sign", 1) or 1)
        negative_scale_direction = committed_inertia_state.get("negative_scale_direction")
    team_state_ref.apply_scale_context(
        next_state["scale_ratio"],
        next_state["negative_scale_sign"],
        next_state,
        negative_scale_direction,
    )
    mc2_state.commit_particle_state_for_center(
        next_state,
        center_state_ref,
        next_positions=arrays["positions"],
        old_positions=arrays["old_positions"],
        velocity_positions=arrays["velocity_positions"],
        display_positions=arrays["display_positions"],
        velocity=arrays["velocity"],
        real_velocity=arrays["real_velocity"],
        friction=arrays["friction"],
        static_friction=arrays["static_friction"],
        collision_normals=arrays["collision_normals"],
        inv_masses=arrays["inv_masses"],
    )
    if center_state_ref is None:
        next_state["next_positions"] = np.ascontiguousarray(arrays["positions"], dtype=np.float32)
        next_state["old_positions"] = np.ascontiguousarray(arrays["old_positions"], dtype=np.float32)
        next_state["display_positions"] = np.ascontiguousarray(arrays["display_positions"], dtype=np.float32)
        next_state["velocity_positions"] = np.ascontiguousarray(arrays["velocity_positions"], dtype=np.float32)
        next_state["velocity"] = np.ascontiguousarray(arrays["velocity"], dtype=np.float32)
        next_state["real_velocity"] = np.ascontiguousarray(arrays["real_velocity"], dtype=np.float32)
        next_state["friction"] = np.ascontiguousarray(arrays["friction"], dtype=np.float32)
        next_state["static_friction"] = np.ascontiguousarray(arrays["static_friction"], dtype=np.float32)
        next_state["collision_normals"] = np.ascontiguousarray(arrays["collision_normals"], dtype=np.float32)
        next_state["inv_masses"] = np.ascontiguousarray(arrays["inv_masses"], dtype=np.float32)
    proxy_ptr, proxy_name, proxy_frame = mc2_state.base_pose_proxy_metadata(state, base_pose_state_ref)
    mc2_state.commit_base_pose_state_for_center(
        next_state,
        center_state_ref,
        base_positions=arrays["base_positions"],
        base_normals=arrays["base_normals"],
        base_rotations=arrays["base_rotations"],
        step_basic_positions=arrays["step_basic_positions"],
        step_basic_rotations=arrays["step_basic_rotations"],
        proxy_ptr=proxy_ptr,
        proxy_name=proxy_name,
        proxy_frame=proxy_frame,
    )
    if center_state_ref is None:
        next_state["step_basic_positions"] = np.ascontiguousarray(arrays["step_basic_positions"], dtype=np.float32)
        next_state["step_basic_rotations"] = np.ascontiguousarray(arrays["step_basic_rotations"], dtype=np.float32)
    mc2_state.set_previous_collider_snapshot_for_center(
        next_state,
        collision.compact_collider_snapshot(colliders),
        center_state_ref,
    )
    runtime_params.write_param_slots(next_state, runtime, native_param_context.param_slots)

    native_slot = _native_runtime_slot(runtime_caches)
    _write_native_debug_view(
        native_slot,
        next_state,
        obj,
        colliders,
        "cpp_core",
        runtime_caches,
        debug_native_view,
        topology_state_ref,
        base_pose_state_ref,
        particle_state_ref,
        center_state_ref,
        native_param_context.param_slots,
    )
    mc2_state.feature_slots(next_state)["native"] = native_slot
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
