"""Runtime controller for MC2 mesh cloth nodes."""

from __future__ import annotations

import time

import bpy

from ......PhysicsTools.meshClothBasePose import ensure_base_pose_proxy, ensure_delta_output
from ....OmniNodeSocketMapping import _OmniCache
from .. import blender_io, collision, mesh_build, params, state as mc2_state
from ..constants import MC2SystemConstants
from ..backends import normalize_backend_label, solver_for_backend
from .restart import cold_restart_runtime_state
from .timing import add_timing, begin_timing, publish_debug_timing


def _dispose_cache_value(cache_state) -> None:
    if cache_state is None or isinstance(cache_state, (str, bool, int, float)):
        return
    if hasattr(cache_state, "value"):
        _dispose_cache_value(getattr(cache_state, "value", None))
        return
    dispose = getattr(cache_state, "omni_cache_dispose", None)
    if callable(dispose):
        try:
            dispose("mc2 invalid RNA input")
        except Exception:
            pass
        return
    if isinstance(cache_state, dict):
        for value in cache_state.values():
            _dispose_cache_value(value)
        return
    if isinstance(cache_state, (list, tuple, set)):
        for value in cache_state:
            _dispose_cache_value(value)


def _constraint_count(
    state: dict,
    vertex_count: int,
    use_distance: bool,
    use_bend: bool,
    use_angle_restoration: bool,
    angle_restoration_stiffness: float,
    angle_restoration_stiffness_curve,
    use_angle_limit: bool,
    angle_limit: float,
    angle_limit_curve,
) -> int:
    dihedral_constraint_count = len(state.get("dihedral_pairs", ()))
    volume_constraint_count = len(state.get("volume_pairs", ()))
    if use_bend:
        bend_constraint_count = (
            dihedral_constraint_count + volume_constraint_count
            if dihedral_constraint_count > 0 or volume_constraint_count > 0
            else len(state.get("bend_distance_i", ()))
        )
    else:
        bend_constraint_count = 0

    angle_constraint_count = 0
    angle_restoration_enabled = use_angle_restoration and params.param_has_positive(
        params.curve_value_param(
            angle_restoration_stiffness,
            angle_restoration_stiffness_curve,
            minimum=0.0,
            maximum=1.0,
        )
    )
    angle_limit_enabled = use_angle_limit and params.param_has_positive(
        params.curve_value_param(
            angle_limit,
            angle_limit_curve,
            minimum=0.0,
            maximum=180.0,
        )
    )
    if angle_restoration_enabled or angle_limit_enabled:
        angle_constraint_count = max(0, len(state.get("baseline_data", ())) - len(state.get("baseline_start", ())))

    try:
        self_collision_thickness = float(state.get("self_collision_surface_thickness", 0.0) or 0.0)
    except (TypeError, ValueError):
        self_collision_thickness = 0.0
    self_collision_active = (
        bool(state.get("self_collision_enabled", False))
        and self_collision_thickness > MC2SystemConstants.EPSILON
    )
    self_collision_constraint_count = (
        vertex_count + len(state.get("edges", ())) + len(state.get("triangles", ()))
        if self_collision_active
        else 0
    )
    return (
        (len(state["edge_i"]) if use_distance else 0)
        + bend_constraint_count
        + angle_constraint_count
        + self_collision_constraint_count
    )


def run_mesh_cloth_mc2_node(
    cache_state: _OmniCache,
    mesh_cloth_settings,
    scene: bpy.types.Scene,
    enabled: bool,
    reset: bool,
    substeps: int,
    iterations: int,
    gravity_dir,
    gravity_power: float,
    gravity_falloff: float,
    stablization_time_after_reset: float,
    anchor_obj: bpy.types.Object,
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
    time_scale: float,
    skip_writing: bool,
    debug_output: bool,
    solver_backend: str = "py",
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    backend_label = normalize_backend_label(solver_backend)
    timing = begin_timing() if debug_output else None
    stage_start = time.perf_counter() if timing is not None else None

    # 从设置 dict/list 提取低模代理和物理参数
    # meshClothMC2Setting 现在输出 list 格式，兼容旧版 dict 格式
    # TODO: 多 proxy 并联支持
    #   当前只取列表中第一个有效 dict，多个 meshClothMC2Setting 接入同一解算器时
    #   后续的 proxy 会被静默忽略。要真正支持"一个解算器并联多个不同代理网格"需要：
    #   1. 为每个 proxy_obj 维护独立的拓扑 state（不同网格顶点数/边/baseline 不同）
    #   2. 分别 solve 或在同一粒子空间合并（concat particles + offset edge indices）
    #   3. 分别写回各自的 GN delta attribute
    #   这是架构级改动，暂不实现。
    if isinstance(mesh_cloth_settings, (list, tuple)):
        settings = next(
            (s for s in mesh_cloth_settings if isinstance(s, dict) and s.get("proxy_obj")),
            {},
        )
    elif isinstance(mesh_cloth_settings, dict):
        settings = mesh_cloth_settings
    else:
        settings = {}
    proxy_obj = settings.get("proxy_obj")
    phys_enabled = bool(settings.get("enabled", True))
    blend_weight               = float(settings.get("blend_weight", 1.0))
    damping                    = float(settings.get("damping", 0.2))
    damping_curve              = settings.get("damping_curve")
    use_tether                 = bool(settings.get("use_tether", True))
    tether_compression         = float(settings.get("tether_compression", MC2SystemConstants.TETHER_COMPRESSION_LIMIT))
    use_distance               = bool(settings.get("use_distance", True))
    distance_stiffness         = float(settings.get("distance_stiffness", 1.0))
    distance_stiffness_curve   = settings.get("distance_stiffness_curve")
    use_bend                   = bool(settings.get("use_bend", True))
    bend_stiffness             = float(settings.get("bend_stiffness", 0.5))
    bend_stiffness_curve       = settings.get("bend_stiffness_curve")
    use_angle_restoration      = bool(settings.get("use_angle_restoration", True))
    angle_restoration_stiffness = float(settings.get("angle_restoration_stiffness", 0.2))
    angle_restoration_stiffness_curve = settings.get("angle_restoration_stiffness_curve")
    angle_restoration_velocity_attenuation = float(settings.get("angle_restoration_velocity_attenuation", MC2SystemConstants.ANGLE_RESTORATION_VELOCITY_ATTENUATION))
    angle_restoration_velocity_attenuation_curve = settings.get("angle_restoration_velocity_attenuation_curve")
    angle_restoration_gravity_falloff = float(settings.get("angle_restoration_gravity_falloff", MC2SystemConstants.ANGLE_RESTORATION_GRAVITY_FALLOFF))
    use_angle_limit            = bool(settings.get("use_angle_limit", False))
    angle_limit                = float(settings.get("angle_limit", 0.0))
    angle_limit_curve          = settings.get("angle_limit_curve")
    angle_limit_stiffness      = float(settings.get("angle_limit_stiffness", 1.0))
    collision_radius           = float(settings.get("collision_radius", 0.0))
    use_max_distance           = bool(settings.get("use_max_distance", False))
    max_distance               = float(settings.get("max_distance", 0.0))
    max_distance_curve         = settings.get("max_distance_curve")
    use_backstop               = bool(settings.get("use_backstop", False))
    backstop_radius            = float(settings.get("backstop_radius", 0.0))
    backstop_distance          = float(settings.get("backstop_distance", 0.0))
    backstop_distance_curve    = settings.get("backstop_distance_curve")
    motion_stiffness           = float(settings.get("motion_stiffness", 1.0))
    normal_axis                = int(settings.get("normal_axis", 1))
    animation_pose_ratio       = float(settings.get("animation_pose_ratio", 0.0))
    use_collider_collision     = bool(settings.get("use_collider_collision", True))
    collider_friction          = float(settings.get("collider_friction", 0.05))
    collider_collision_mode    = int(settings.get("collider_collision_mode", 1))

    enabled = enabled and phys_enabled
    try:
        obj = blender_io.require_mesh_object(proxy_obj, "proxy_obj")
    except ValueError:
        _dispose_cache_value(cache_state)
        return _OmniCache.replace(None), None, 0, 0
    scene = scene or bpy.context.scene
    output_key = blender_io.output_key_name(obj)
    ensure_delta_output(obj)
    if timing is not None:
        add_timing(timing, "validate", time.perf_counter() - stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    cache_substage_start = time.perf_counter() if timing is not None else None
    mesh_light_key = mesh_build.mesh_light_key(obj)
    if timing is not None:
        add_timing(timing, "cache.light_key", time.perf_counter() - cache_substage_start)

    vertex_count = len(obj.data.vertices)
    cache_substage_start = time.perf_counter() if timing is not None else None
    cache_owner = cache_state if isinstance(cache_state, mc2_state.MC2RuntimeOwner) else None
    mesh_signature_key = None
    config_key = None
    if cache_owner is not None:
        topology_cache = cache_owner.topology_cache
        prev_state = cache_owner.state if isinstance(cache_owner.state, dict) else None
        prev_signature = prev_state.get("mesh_signature_key") if isinstance(prev_state, dict) else None
        prev_light_key = prev_state.get("mesh_light_key") if isinstance(prev_state, dict) else None
        sig_substage_start = time.perf_counter() if timing is not None else None
        if prev_signature is not None and prev_light_key is not None and prev_light_key == mesh_light_key:
            # 廉价 light_key 一致说明拓扑数量未变；直接复用上一帧已算好的
            # mesh_signature_key，跳过每帧重建连通性数组 + array_hash。
            mesh_signature_key = prev_signature
        else:
            mesh_signature_key = mesh_build.mesh_signature_key(obj, topology_cache)
        if timing is not None:
            add_timing(timing, "cache.match.signature", time.perf_counter() - sig_substage_start)
        cfg_substage_start = time.perf_counter() if timing is not None else None
        config_key = mesh_build.config_key(
            obj,
            output_key,
            mesh_signature_key,
            collision_radius,
            light_key=mesh_light_key,
            weight_hash_cache=topology_cache,
        )
        if timing is not None:
            add_timing(timing, "cache.match.config_key", time.perf_counter() - cfg_substage_start)
    sm_substage_start = time.perf_counter() if timing is not None else None
    state_matches = (
        cache_owner is not None
        and mc2_state.state_matches(cache_owner, obj, output_key, mesh_light_key, config_key)
    )
    if timing is not None:
        add_timing(timing, "cache.match.state_matches", time.perf_counter() - sm_substage_start)
        add_timing(timing, "cache.match", time.perf_counter() - cache_substage_start)
    state = cache_owner.state if state_matches else None
    replace_cache = cache_owner is None or not state_matches

    cache_substage_start = time.perf_counter() if timing is not None else None
    cached_frame = blender_io.cache_frame(state)
    current_frame = int(getattr(scene, "frame_current", 0) or 0)
    continuous_frame = cached_frame is not None and current_frame == cached_frame + 1
    restart_required = reset or not continuous_frame
    solve_anchor_inertia = 1.0 if restart_required else anchor_inertia
    solve_motion_stiffness = 0.0 if restart_required else motion_stiffness
    solve_centrifugal = 0.0 if restart_required else centrifugal
    if timing is not None:
        add_timing(timing, "cache.frame", time.perf_counter() - cache_substage_start)
        add_timing(timing, "cache", time.perf_counter() - stage_start)
    if restart_required:
        replace_cache = True
        mesh_signature_key = None
        config_key = None

    base_pose_proxy = None
    if enabled:
        base_proxy_stage_start = time.perf_counter() if timing is not None else None
        stage_start = time.perf_counter() if timing is not None else None
        base_pose_proxy = ensure_base_pose_proxy(obj, scene, refresh=False)
        ensure_delta_output(obj)
        if timing is not None:
            add_timing(timing, "base_proxy.ensure", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        if not blender_io.is_live_mesh_object(base_pose_proxy):
            base_pose_proxy = ensure_base_pose_proxy(obj, scene, refresh=True)
        if timing is not None:
            add_timing(timing, "base_proxy.validate", time.perf_counter() - stage_start)
            add_timing(timing, "base_proxy", time.perf_counter() - base_proxy_stage_start)

    if restart_required or not isinstance(state, dict):
        replace_cache = True
        cache_owner = mc2_state.MC2RuntimeOwner()
        topology_cache = cache_owner.topology_cache
        rebuild_stage_start = time.perf_counter() if timing is not None else None
        stage_start = time.perf_counter() if timing is not None else None
        blender_io.clear_delta_attribute(obj)
        if timing is not None:
            add_timing(timing, "rebuild.restore", time.perf_counter() - stage_start)

        cache_substage_start = time.perf_counter() if timing is not None else None
        if mesh_signature_key is None:
            mesh_signature_key = mesh_build.mesh_signature_key(obj, topology_cache)
        if timing is not None:
            add_timing(timing, "rebuild.mesh_signature", time.perf_counter() - cache_substage_start)

        cache_substage_start = time.perf_counter() if timing is not None else None
        if config_key is None:
            config_key = mesh_build.config_key(
                obj,
                output_key,
                mesh_signature_key,
                collision_radius,
                light_key=mesh_light_key,
                weight_hash_cache=topology_cache,
            )
        if timing is not None:
            add_timing(timing, "rebuild.config", time.perf_counter() - cache_substage_start)

        stage_start = time.perf_counter() if timing is not None else None
        state = mc2_state.build_state(
            obj,
            output_key,
            mesh_light_key,
            mesh_signature_key,
            config_key,
            collision_radius,
            topology_cache,
        )
        cache_owner.replace_state(state)
        if timing is not None:
            add_timing(timing, "rebuild.build_state", time.perf_counter() - stage_start)
            add_timing(timing, "rebuild", time.perf_counter() - rebuild_stage_start)
    else:
        cache_owner = mc2_state.ensure_runtime_owner(cache_owner)
        stage_start = time.perf_counter() if timing is not None else None
        if base_pose_proxy is not None:
            state = mc2_state.sync_state_to_base_pose_write_container(state, obj)
        else:
            state = mc2_state.sync_state_to_object_transform(state, obj, cache_owner.center_state)
        cache_owner.replace_state(state)
        if timing is not None:
            add_timing(timing, "transform", time.perf_counter() - stage_start)

    cache_owner.team_state.apply_lifecycle_context(
        state,
        time_scale=time_scale,
        skip_writing=skip_writing,
    )

    constraint_count = _constraint_count(
        state,
        vertex_count,
        use_distance,
        use_bend,
        use_angle_restoration,
        angle_restoration_stiffness,
        angle_restoration_stiffness_curve,
        use_angle_limit,
        angle_limit,
        angle_limit_curve,
    )

    if not enabled:
        next_state = mc2_state.inherit_runtime_slots(state, dict(state))
        next_state["frame"] = current_frame
        blender_io.clear_delta_attribute(obj)
        publish_debug_timing(obj, output_key, current_frame, vertex_count, constraint_count, timing, backend_label)
        cache_owner.replace_state(next_state)
        cache_value = _OmniCache.replace(cache_owner) if replace_cache else _OmniCache.mutate(cache_owner)
        return cache_value, obj, vertex_count, constraint_count

    stage_start = time.perf_counter() if timing is not None else None
    state = mc2_state.sync_state_to_base_pose_proxy(
        state,
        obj,
        base_pose_proxy,
        current_frame,
        timing,
        cache_owner.io_cache,
        cache_owner.center_state,
    )
    cache_owner.replace_state(state)
    if timing is not None:
        add_timing(timing, "base_pose_sync", time.perf_counter() - stage_start)

    if restart_required:
        state = cold_restart_runtime_state(
            state,
            obj,
            cache_owner.center_state,
            cache_owner.team_state,
            blend_weight,
        )
        blender_io.clear_delta_attribute(obj)
        next_state = mc2_state.inherit_runtime_slots(state, dict(state))
        next_state["frame"] = current_frame
        publish_debug_timing(obj, output_key, current_frame, vertex_count, constraint_count, timing, backend_label)
        cache_owner.replace_state(next_state)
        cache_value = _OmniCache.replace(cache_owner) if replace_cache else _OmniCache.mutate(cache_owner)
        return cache_value, obj, vertex_count, constraint_count

    stage_start = time.perf_counter() if timing is not None else None
    if use_collider_collision and int(collider_collision_mode) != 0:
        collision_snapshot = collision.build_collision_snapshot_from_scene(scene, True, True, False)
        colliders = list(collision_snapshot.get("colliders") or []) if isinstance(collision_snapshot, dict) else []
    else:
        colliders = []
    if timing is not None:
        add_timing(timing, "colliders", time.perf_counter() - stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    solve_func = solver_for_backend(backend_label)
    next_state = solve_func(
        state,
        obj,
        scene,
        substeps,
        iterations,
        gravity_dir,
        gravity_power,
        gravity_falloff,
        stablization_time_after_reset,
        blend_weight,
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
        anchor_obj,
        solve_anchor_inertia,
        world_inertia,
        movement_inertia_smoothing,
        local_inertia,
        depth_inertia,
        solve_centrifugal,
        movement_speed_limit,
        rotation_speed_limit,
        local_movement_speed_limit,
        local_rotation_speed_limit,
        particle_speed_limit,
        teleport_mode,
        teleport_distance,
        teleport_rotation,
        animation_pose_ratio,
        use_max_distance,
        max_distance,
        max_distance_curve,
        use_backstop,
        backstop_radius,
        backstop_distance,
        backstop_distance_curve,
        solve_motion_stiffness,
        normal_axis,
        use_collider_collision,
        collider_friction,
        collider_collision_mode,
        timing,
        colliders=colliders,
        runtime_caches=cache_owner.runtime_cache_slots(),
        center_state=cache_owner.center_state,
        team_state=cache_owner.team_state,
    )
    if timing is not None:
        add_timing(timing, "solve_total", time.perf_counter() - stage_start)

    next_state["frame"] = current_frame
    stage_start = time.perf_counter() if timing is not None else None
    write_substage_start = time.perf_counter() if timing is not None else None
    base_positions = next_state["base_positions"] if base_pose_proxy is not None else next_state["rest_world_positions"]
    if timing is not None:
        add_timing(timing, "write.base_positions", time.perf_counter() - write_substage_start)

    write_substage_start = time.perf_counter() if timing is not None else None
    if cache_owner.team_state.skip_writing:
        if timing is not None:
            add_timing(timing, "write.skip_writing", time.perf_counter() - write_substage_start)
    else:
        blender_io.write_world_delta_attribute(obj, next_state["display_positions"], base_positions)
        if timing is not None:
            add_timing(timing, "write.delta_attribute", time.perf_counter() - write_substage_start)
    if timing is not None:
        add_timing(timing, "write", time.perf_counter() - stage_start)
        publish_debug_timing(obj, output_key, current_frame, vertex_count, constraint_count, timing, backend_label)
    cache_owner.replace_state(next_state)
    cache_value = _OmniCache.replace(cache_owner) if replace_cache else _OmniCache.mutate(cache_owner)
    return cache_value, obj, vertex_count, constraint_count
