"""Runtime controller for MC2 mesh cloth nodes."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import bpy
import numpy as np

from ...physicsWorld.mesh_cloth.base_pose import ensure_base_pose_proxy, ensure_delta_output
from ....OmniNodeSocketMapping import _OmniCache
from .. import blender_io, collision, mesh_build, params, state as mc2_state
from ..constants import MC2SystemConstants
from ..backends import normalize_backend_label, solver_for_backend
from ..merged_topology import (
    MC2_MERGED_CACHE_KIND,
    ProxyChunk,
    build_chunks,
    build_merged_state,
    copy_merged_slice_to_proxy,
    merge_runtime_params,
    split_base_positions,
    split_display_positions,
    update_merged_particle_slice,
)
from .restart import cold_restart_runtime_state
from .timing import add_timing, begin_timing, publish_debug_timing


# ---------------------------------------------------------------------------
# MC2MergedOwner：多 proxy 聚合解算的 cache 容器
# ---------------------------------------------------------------------------

@dataclass
class MC2MergedOwner:
    """持有 N 个 per-proxy MC2RuntimeOwner + 一个合并解算用 MC2RuntimeOwner。

    ProxyChunk 列表是"头标/尾标"索引，记录每个 proxy 在合并粒子数组里的范围。
    """

    proxy_owners: list = field(default_factory=list)   # list[MC2RuntimeOwner]
    merged_owner: object = None                        # MC2RuntimeOwner，用于合并解算
    chunks: list = field(default_factory=list)         # list[ProxyChunk]
    proxy_signature: tuple = field(default_factory=tuple)

    def omni_cache_dispose(self, reason: str = "") -> None:
        """释放所有子 owner。"""
        for owner in self.proxy_owners:
            dispose = getattr(owner, "omni_cache_dispose", None)
            if callable(dispose):
                try:
                    dispose(reason)
                except Exception:
                    pass
        if self.merged_owner is not None:
            dispose = getattr(self.merged_owner, "omni_cache_dispose", None)
            if callable(dispose):
                try:
                    dispose(reason)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# 工具：从 settings list 提取所有有效 proxy 设置
# ---------------------------------------------------------------------------

def _append_expanded_setting(result: list[dict], setting: dict) -> None:
    proxy_obj = setting.get("proxy_obj")
    if not proxy_obj:
        return
    if isinstance(proxy_obj, (list, tuple)):
        for obj in proxy_obj:
            if obj:
                expanded = dict(setting)
                expanded["proxy_obj"] = obj
                result.append(expanded)
        return
    result.append(setting)


def _extract_all_settings(mesh_cloth_settings) -> list[dict]:
    """Extract all settings and expand packed multi-object proxy inputs."""
    result: list[dict] = []
    pending = [mesh_cloth_settings]
    while pending:
        item = pending.pop(0)
        if isinstance(item, dict):
            _append_expanded_setting(result, item)
        elif isinstance(item, (list, tuple)):
            pending[0:0] = list(item)
    return result


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


def _cache_payload(cache_state):
    return getattr(cache_state, "value", cache_state)


def _rna_pointer(value) -> int:
    try:
        return int(value.as_pointer())
    except Exception:
        return 0


def _merged_proxy_signature(valid_objs: list[bpy.types.Object]) -> tuple:
    return tuple(
        (
            _rna_pointer(obj),
            _rna_pointer(getattr(obj, "data", None)),
            blender_io.output_key_name(obj),
        )
        for obj in valid_objs
    )


def _write_merged_delta_attributes(
    merged_state: dict,
    chunks: list[ProxyChunk],
    valid_objs: list[bpy.types.Object],
    skip_writing: bool,
) -> None:
    if skip_writing:
        return

    display_slices = split_display_positions(merged_state, chunks)
    rest_pos_merged = merged_state.get("rest_world_positions")
    base_pos_merged = merged_state.get("base_positions")
    for ch, obj, disp in zip(chunks, valid_objs, display_slices):
        if ch.base_pose_proxy is not None and base_pos_merged is not None:
            base = np.ascontiguousarray(base_pos_merged[ch.start:ch.end], np.float32)
        elif rest_pos_merged is not None:
            base = np.ascontiguousarray(rest_pos_merged[ch.start:ch.end], np.float32)
        else:
            continue
        blender_io.write_world_delta_attribute(obj, disp, base)


_SETTING_KEY_FIELDS = (
    "enabled",
    "blend_weight",
    "damping",
    "damping_curve",
    "use_tether",
    "tether_compression",
    "use_distance",
    "distance_stiffness",
    "distance_stiffness_curve",
    "use_bend",
    "bend_stiffness",
    "bend_stiffness_curve",
    "use_angle_restoration",
    "angle_restoration_stiffness",
    "angle_restoration_stiffness_curve",
    "angle_restoration_velocity_attenuation",
    "angle_restoration_velocity_attenuation_curve",
    "angle_restoration_gravity_falloff",
    "use_angle_limit",
    "angle_limit",
    "angle_limit_curve",
    "angle_limit_stiffness",
    "collision_radius",
    "use_max_distance",
    "max_distance",
    "max_distance_curve",
    "use_backstop",
    "backstop_radius",
    "backstop_distance",
    "backstop_distance_curve",
    "motion_stiffness",
)


def _object_key(obj) -> tuple | None:
    if obj is None:
        return None
    if isinstance(obj, bpy.types.ID):
        return (type(obj).__name__, int(obj.as_pointer()), str(getattr(obj, "name_full", "")))
    return None


def _key_value(value):
    object_key = _object_key(value)
    if object_key is not None:
        return object_key
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, np.ndarray):
        array = np.ascontiguousarray(value)
        return ("ndarray", str(array.dtype), tuple(array.shape), bytes(array.reshape(-1).tobytes()))
    try:
        payload = value.to_payload()
    except Exception:
        payload = None
    else:
        return _key_value(payload)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _key_value(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_key_value(item) for item in value)
    try:
        return tuple(_key_value(item) for item in value)
    except TypeError:
        return (type(value).__name__, repr(value))


def _scene_timestep_key(scene: bpy.types.Scene | None) -> tuple:
    render = getattr(scene, "render", None)
    return (
        int(getattr(render, "fps", 24) or 24),
        float(getattr(render, "fps_base", 1.0) or 1.0),
    )


def _runtime_settings_key(
    settings: dict,
    *,
    scene: bpy.types.Scene | None,
    enabled: bool,
    backend_label: str,
    substeps: int,
    iterations: int,
    gravity_dir,
    gravity_power: float,
    gravity_falloff: float,
    stablization_time_after_reset: float,
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
    normal_axis: int,
    animation_pose_ratio: float,
    use_collider_collision: bool,
    collider_friction: float,
    collider_collision_mode: int,
    time_scale: float,
) -> tuple:
    setting_items = tuple((name, _key_value(settings.get(name))) for name in _SETTING_KEY_FIELDS)
    solver_items = (
        ("enabled", bool(enabled)),
        ("backend", str(backend_label)),
        ("substeps", int(substeps)),
        ("iterations", int(iterations)),
        ("scene_timestep", _scene_timestep_key(scene)),
        ("gravity_dir", _key_value(gravity_dir)),
        ("gravity_power", float(gravity_power)),
        ("gravity_falloff", float(gravity_falloff)),
        ("stablization_time_after_reset", float(stablization_time_after_reset)),
        ("anchor_obj", _object_key(anchor_obj)),
        ("anchor_inertia", float(anchor_inertia)),
        ("world_inertia", float(world_inertia)),
        ("movement_inertia_smoothing", float(movement_inertia_smoothing)),
        ("local_inertia", float(local_inertia)),
        ("depth_inertia", float(depth_inertia)),
        ("centrifugal", float(centrifugal)),
        ("movement_speed_limit", float(movement_speed_limit)),
        ("rotation_speed_limit", float(rotation_speed_limit)),
        ("local_movement_speed_limit", float(local_movement_speed_limit)),
        ("local_rotation_speed_limit", float(local_rotation_speed_limit)),
        ("particle_speed_limit", float(particle_speed_limit)),
        ("teleport_mode", int(teleport_mode)),
        ("teleport_distance", float(teleport_distance)),
        ("teleport_rotation", float(teleport_rotation)),
        ("normal_axis", int(normal_axis)),
        ("animation_pose_ratio", float(animation_pose_ratio)),
        ("use_collider_collision", bool(use_collider_collision)),
        ("collider_friction", float(collider_friction)),
        ("collider_collision_mode", int(collider_collision_mode)),
        ("time_scale", float(time_scale)),
    )
    return ("meshcloth-runtime-settings-v1", setting_items, solver_items)


def _write_cached_delta(obj: bpy.types.Object, state: dict, use_base_pose: bool, skip_writing: bool) -> None:
    if skip_writing:
        return
    display = state.get("display_positions")
    base = state.get("base_positions") if use_base_pose else state.get("rest_world_positions")
    if isinstance(display, np.ndarray) and isinstance(base, np.ndarray):
        blender_io.write_world_delta_attribute(obj, display, base)


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
    normal_axis: int,
    animation_pose_ratio: float,
    use_collider_collision: bool,
    collider_friction: float,
    collider_collision_mode: int,
    time_scale: float,
    skip_writing: bool,
    debug_output: bool,
    solver_backend: str = "py",
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    # ---- 多 proxy 分发：超过 1 个有效 proxy 走聚合解算路径 ----
    all_settings = _extract_all_settings(mesh_cloth_settings)
    if len(all_settings) > 1:
        return _run_merged_mc2_node(
            cache_state, all_settings, scene, enabled, reset,
            substeps, iterations, gravity_dir, gravity_power, gravity_falloff,
            stablization_time_after_reset, anchor_obj, anchor_inertia,
            world_inertia, movement_inertia_smoothing, local_inertia, depth_inertia,
            centrifugal, movement_speed_limit, rotation_speed_limit,
            local_movement_speed_limit, local_rotation_speed_limit, particle_speed_limit,
            teleport_mode, teleport_distance, teleport_rotation,
            normal_axis, animation_pose_ratio, use_collider_collision,
            collider_friction, collider_collision_mode,
            time_scale, skip_writing, debug_output, solver_backend,
        )

    backend_label = normalize_backend_label(solver_backend)
    timing = begin_timing() if debug_output else None
    stage_start = time.perf_counter() if timing is not None else None

    # 从设置 dict/list 提取低模代理和物理参数（单 proxy 路径）
    settings = all_settings[0] if all_settings else {}
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

    enabled = enabled and phys_enabled
    try:
        obj = blender_io.require_mesh_object(proxy_obj, "proxy_obj")
    except ValueError:
        _dispose_cache_value(cache_state)
        return _OmniCache.replace(None), None, 0, 0
    scene = scene or bpy.context.scene
    output_key = blender_io.output_key_name(obj)
    current_settings_key = _runtime_settings_key(
        settings,
        scene=scene,
        enabled=enabled,
        backend_label=backend_label,
        substeps=substeps,
        iterations=iterations,
        gravity_dir=gravity_dir,
        gravity_power=gravity_power,
        gravity_falloff=gravity_falloff,
        stablization_time_after_reset=stablization_time_after_reset,
        anchor_obj=anchor_obj,
        anchor_inertia=anchor_inertia,
        world_inertia=world_inertia,
        movement_inertia_smoothing=movement_inertia_smoothing,
        local_inertia=local_inertia,
        depth_inertia=depth_inertia,
        centrifugal=centrifugal,
        movement_speed_limit=movement_speed_limit,
        rotation_speed_limit=rotation_speed_limit,
        local_movement_speed_limit=local_movement_speed_limit,
        local_rotation_speed_limit=local_rotation_speed_limit,
        particle_speed_limit=particle_speed_limit,
        teleport_mode=teleport_mode,
        teleport_distance=teleport_distance,
        teleport_rotation=teleport_rotation,
        normal_axis=normal_axis,
        animation_pose_ratio=animation_pose_ratio,
        use_collider_collision=use_collider_collision,
        collider_friction=collider_friction,
        collider_collision_mode=collider_collision_mode,
        time_scale=time_scale,
    )
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
    raw_cache_state = _cache_payload(cache_state)
    cache_owner = raw_cache_state if isinstance(raw_cache_state, mc2_state.MC2RuntimeOwner) else None
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
    settings_unchanged = (
        isinstance(state, dict)
        and state.get("settings_key") == current_settings_key
    )
    replace_cache = cache_owner is None or not state_matches

    cache_substage_start = time.perf_counter() if timing is not None else None
    cached_frame = blender_io.cache_frame(state)
    current_frame = int(getattr(scene, "frame_current", 0) or 0)
    same_frame = cached_frame is not None and current_frame == cached_frame
    continuous_frame = cached_frame is not None and current_frame == cached_frame + 1
    restart_required = reset or not (same_frame or continuous_frame)
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
        state["settings_key"] = current_settings_key
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
        state["settings_key"] = current_settings_key
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
        next_state["settings_key"] = current_settings_key
        blender_io.clear_delta_attribute(obj)
        publish_debug_timing(obj, output_key, current_frame, vertex_count, constraint_count, timing, backend_label)
        cache_owner.replace_state(next_state)
        cache_value = _OmniCache.replace(cache_owner) if replace_cache else _OmniCache.mutate(cache_owner)
        return cache_value, obj, vertex_count, constraint_count

    if same_frame and settings_unchanged and not reset:
        use_base_pose = mc2_state.base_pose_proxy_active(state, cache_owner.center_state.base_pose_state)
        _write_cached_delta(obj, state, use_base_pose, cache_owner.team_state.skip_writing)
        publish_debug_timing(obj, output_key, current_frame, vertex_count, constraint_count, timing, backend_label)
        cache_owner.replace_state(state)
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
        next_state["settings_key"] = current_settings_key
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
    next_state["settings_key"] = current_settings_key
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


# ---------------------------------------------------------------------------
# _run_merged_mc2_node：多 proxy 聚合解算路径
# ---------------------------------------------------------------------------

def _run_merged_mc2_node(
    cache_state: _OmniCache,
    all_settings: list[dict],
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
    normal_axis: int,
    animation_pose_ratio: float,
    use_collider_collision: bool,
    collider_friction: float,
    collider_collision_mode: int,
    time_scale: float,
    skip_writing: bool,
    debug_output: bool,
    solver_backend: str = "py",
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    """多 proxy 聚合解算：N 个 proxy 的粒子合并为一个 state 送入 solver。

    自碰撞检测在合并状态下对全部粒子生效，不同 proxy 的粒子自动互相推挤。
    每个 proxy 可以有不同的物理参数（damping / stiffness / blend_weight），
    通过 per_particle_param 机制逐粒子传入 solver。
    """
    backend_label = normalize_backend_label(solver_backend)
    scene = scene or bpy.context.scene

    # ---- 1. 验证所有 proxy，剔除无效项 ----
    valid_settings: list[dict] = []
    valid_objs: list[bpy.types.Object] = []
    for s in all_settings:
        try:
            obj = blender_io.require_mesh_object(s.get("proxy_obj"), "proxy_obj")
        except ValueError:
            continue
        valid_settings.append(s)
        valid_objs.append(obj)

    if not valid_settings:
        _dispose_cache_value(cache_state)
        return _OmniCache.replace(None), None, 0, 0
    proxy_signature = _merged_proxy_signature(valid_objs)
    if debug_output:
        proxy_names = ", ".join(
            str(getattr(obj, "name_full", getattr(obj, "name", obj)))
            for obj in valid_objs
        )
        print(
            f"[HoTools MC2] merged settings={len(all_settings)} "
            f"valid_proxies={len(valid_objs)} proxies=[{proxy_names}]"
        )

    # ---- 2. 恢复 MC2MergedOwner，或新建 ----
    proxy_settings_keys = [
        _runtime_settings_key(
            s,
            scene=scene,
            enabled=enabled and bool(s.get("enabled", True)),
            backend_label=backend_label,
            substeps=substeps,
            iterations=iterations,
            gravity_dir=gravity_dir,
            gravity_power=gravity_power,
            gravity_falloff=gravity_falloff,
            stablization_time_after_reset=stablization_time_after_reset,
            anchor_obj=anchor_obj,
            anchor_inertia=anchor_inertia,
            world_inertia=world_inertia,
            movement_inertia_smoothing=movement_inertia_smoothing,
            local_inertia=local_inertia,
            depth_inertia=depth_inertia,
            centrifugal=centrifugal,
            movement_speed_limit=movement_speed_limit,
            rotation_speed_limit=rotation_speed_limit,
            local_movement_speed_limit=local_movement_speed_limit,
            local_rotation_speed_limit=local_rotation_speed_limit,
            particle_speed_limit=particle_speed_limit,
            teleport_mode=teleport_mode,
            teleport_distance=teleport_distance,
            teleport_rotation=teleport_rotation,
            normal_axis=normal_axis,
            animation_pose_ratio=animation_pose_ratio,
            use_collider_collision=use_collider_collision,
            collider_friction=collider_friction,
            collider_collision_mode=collider_collision_mode,
            time_scale=time_scale,
        )
        for s in valid_settings
    ]
    merged_settings_key = ("meshcloth-merged-runtime-settings-v1", tuple(proxy_settings_keys))

    raw = _cache_payload(cache_state)
    merged_owner_obj: MC2MergedOwner | None = raw if isinstance(raw, MC2MergedOwner) else None

    # 代理数量/身份/顺序变化 → 强制重建，避免把第一个旧对象的 owner 错配给新对象。
    if (
        merged_owner_obj is not None
        and (
            len(merged_owner_obj.proxy_owners) != len(valid_settings)
            or tuple(getattr(merged_owner_obj, "proxy_signature", ())) != proxy_signature
        )
    ):
        merged_owner_obj.omni_cache_dispose("代理输入变化，重建合并 owner")
        merged_owner_obj = None

    if merged_owner_obj is None:
        merged_owner_obj = MC2MergedOwner(
            proxy_owners=[mc2_state.MC2RuntimeOwner() for _ in valid_settings],
            merged_owner=mc2_state.MC2RuntimeOwner(),
            chunks=[],
            proxy_signature=proxy_signature,
        )
        replace_cache = True
    else:
        merged_owner_obj.proxy_signature = proxy_signature
        replace_cache = False

    n_proxies = len(valid_settings)
    proxy_owners = merged_owner_obj.proxy_owners
    merged_owner = merged_owner_obj.merged_owner

    # ---- 3. 每个 proxy：确认 base_pose_proxy ----
    base_pose_proxies: list = []
    for obj in valid_objs:
        ensure_delta_output(obj)
        bpp = None
        refreshed = False
        if enabled:
            bpp = ensure_base_pose_proxy(obj, scene, refresh=False)
            if not blender_io.is_live_mesh_object(bpp):
                refreshed = True
                bpp = ensure_base_pose_proxy(obj, scene, refresh=True)
        if debug_output:
            obj_name = str(getattr(obj, "name_full", getattr(obj, "name", obj)))
            bpp_name = str(getattr(bpp, "name_full", getattr(bpp, "name", None)))
            print(
                f"[HoTools MC2] base_pose_proxy proxy={obj_name} "
                f"base={bpp_name} refreshed={refreshed} enabled={enabled}"
            )
        base_pose_proxies.append(bpp)

    # ---- 4. 每个 proxy 的拓扑 cache 检查 ----
    current_frame = int(getattr(scene, "frame_current", 0) or 0)
    per_proxy_states: list[dict | None] = []
    per_proxy_needs_rebuild: list[bool] = []
    any_rebuild = False
    any_restart = False
    all_same_frame = True

    for i, (s, obj, p_owner, proxy_settings_key) in enumerate(zip(valid_settings, valid_objs, proxy_owners, proxy_settings_keys)):
        collision_radius = float(s.get("collision_radius", 0.0))
        topo_cache = p_owner.topology_cache
        prev_state = p_owner.state if isinstance(p_owner.state, dict) else None

        mesh_light_key = mesh_build.mesh_light_key(obj)
        prev_light = prev_state.get("mesh_light_key") if prev_state else None
        prev_sig   = prev_state.get("mesh_signature_key") if prev_state else None
        mesh_sig   = (prev_sig if (prev_light is not None and prev_light == mesh_light_key and prev_sig is not None)
                      else mesh_build.mesh_signature_key(obj, topo_cache))
        config_key = mesh_build.config_key(obj, blender_io.output_key_name(obj), mesh_sig, collision_radius,
                                            light_key=mesh_light_key, weight_hash_cache=topo_cache)
        output_key = blender_io.output_key_name(obj)
        state_ok = mc2_state.state_matches(p_owner, obj, output_key, mesh_light_key, config_key)

        cached_frame = blender_io.cache_frame(p_owner.state if state_ok else None)
        settings_unchanged = (
            state_ok
            and isinstance(prev_state, dict)
            and prev_state.get("settings_key") == proxy_settings_key
        )
        same = state_ok and cached_frame is not None and current_frame == cached_frame
        same_replay = same and settings_unchanged
        continuous = state_ok and cached_frame is not None and current_frame == cached_frame + 1
        restart = reset or not (same or continuous)
        all_same_frame = all_same_frame and bool(same_replay)

        if not state_ok or restart:
            new_state = mc2_state.build_state(obj, output_key, mesh_light_key, mesh_sig, config_key,
                                               collision_radius, topo_cache)
            new_state["settings_key"] = proxy_settings_key
            p_owner.replace_state(new_state)
            per_proxy_needs_rebuild.append(True)
            any_rebuild = True
        else:
            per_proxy_needs_rebuild.append(False)

        per_proxy_states.append(p_owner.state)
        if restart:
            any_restart = True

    # ---- 5. 拓扑变化 → 重建合并 state ----
    need_rebuild_merged = any_rebuild or len(merged_owner_obj.chunks) != n_proxies
    if need_rebuild_merged:
        chunks = build_chunks(per_proxy_states)
        # 把 proxy 元数据写入 chunk
        for i, (s, obj, bpp) in enumerate(zip(valid_settings, valid_objs, base_pose_proxies)):
            chunks[i].proxy_obj = obj
            chunks[i].output_key = blender_io.output_key_name(obj)
            chunks[i].base_pose_proxy = bpp
            chunks[i].blend_weight = float(s.get("blend_weight", 1.0))
        merged_owner_obj.chunks = chunks
        merged_state = build_merged_state(per_proxy_states, chunks)
        merged_owner.replace_state(merged_state)
        replace_cache = True
    else:
        chunks = merged_owner_obj.chunks
        # 更新 base_pose_proxy（每帧可能刷新）
        for i, (bpp, s) in enumerate(zip(base_pose_proxies, valid_settings)):
            chunks[i].base_pose_proxy = bpp
            chunks[i].blend_weight = float(s.get("blend_weight", 1.0))
        merged_state = merged_owner.state

    # ---- 6. TeamState / lifecycle 应用到合并 owner ----
    merged_settings_unchanged = (
        isinstance(merged_state, dict)
        and merged_state.get("settings_key") == merged_settings_key
    )
    all_same_frame = all_same_frame and bool(merged_settings_unchanged)
    merged_state["settings_key"] = merged_settings_key
    merged_state["collider_owner_exclusion_ptrs"] = tuple(_rna_pointer(obj) for obj in valid_objs)

    solve_anchor_inertia  = 1.0 if any_restart else anchor_inertia
    solve_centrifugal     = 0.0 if any_restart else centrifugal
    merged_owner.team_state.apply_lifecycle_context(
        merged_state,
        time_scale=time_scale,
        skip_writing=skip_writing,
    )

    total_vertex_count = sum(ch.count for ch in chunks)

    # ---- 7. not enabled：清除 delta 并提前返回 ----
    if not enabled:
        for obj, p_owner, proxy_settings_key in zip(valid_objs, proxy_owners, proxy_settings_keys):
            blender_io.clear_delta_attribute(obj)
            proxy_state = p_owner.state if isinstance(p_owner.state, dict) else {}
            proxy_state["frame"] = current_frame
            proxy_state["settings_key"] = proxy_settings_key
            p_owner.replace_state(proxy_state)
        merged_state["frame"] = current_frame
        merged_state["settings_key"] = merged_settings_key
        merged_owner.replace_state(merged_state)
        cache_value = _OmniCache.replace(merged_owner_obj) if replace_cache else _OmniCache.mutate(merged_owner_obj)
        return cache_value, valid_objs[0], total_vertex_count, 0

    # ---- 8. restart：cold restart 各 proxy + 清 delta + 提前返回 ----
    if any_restart:
        for i, (s, obj, p_owner, ch, proxy_settings_key) in enumerate(zip(valid_settings, valid_objs, proxy_owners, chunks, proxy_settings_keys)):
            blend_weight = float(s.get("blend_weight", 1.0))
            proxy_state = p_owner.state
            proxy_state = cold_restart_runtime_state(
                proxy_state,
                obj,
                p_owner.center_state,
                p_owner.team_state,
                blend_weight,
            )
            blender_io.clear_delta_attribute(obj)
            proxy_state["frame"] = current_frame
            proxy_state["settings_key"] = proxy_settings_key
            p_owner.replace_state(proxy_state)
            # 把重置后的粒子位置写入合并 state 的对应切片
            update_merged_particle_slice(merged_state, proxy_state, ch)
        merged_state["frame"] = current_frame
        merged_state["settings_key"] = merged_settings_key
        merged_owner.replace_state(merged_state)
        cache_value = _OmniCache.replace(merged_owner_obj) if replace_cache else _OmniCache.mutate(merged_owner_obj)
        return cache_value, valid_objs[0], total_vertex_count, 0

    # ---- 9. 正常帧：per-proxy base pose sync ----
    for i, (s, obj, p_owner, ch, proxy_settings_key) in enumerate(zip(valid_settings, valid_objs, proxy_owners, chunks, proxy_settings_keys)):
        # 第一次 sync（与单 proxy 路径对齐）
        proxy_owners[i] = mc2_state.ensure_runtime_owner(p_owner)
        p_owner = proxy_owners[i]
        proxy_state = p_owner.state
        bpp = ch.base_pose_proxy
        if bpp is not None:
            proxy_state = mc2_state.sync_state_to_base_pose_write_container(proxy_state, obj)
        else:
            proxy_state = mc2_state.sync_state_to_object_transform(proxy_state, obj, p_owner.center_state)
        p_owner.replace_state(proxy_state)

        # 第二次 sync：base pose 位置同步（主 per-frame 更新）
        if bpp is not None:
            proxy_state = mc2_state.sync_state_to_base_pose_proxy(
                proxy_state,
                obj,
                bpp,
                current_frame,
                None,    # timing（合并路径暂不细分计时）
                p_owner.io_cache,
                p_owner.center_state,
            )
        proxy_state["settings_key"] = proxy_settings_key
        p_owner.replace_state(proxy_state)
        # 把同步后的 base_positions / step_basic_* 写入合并 state 的切片
        update_merged_particle_slice(merged_state, proxy_state, ch)

    # 合并 state 的 base_pose_proxy_ptr：只要有任意 proxy 有效 bpp 就设为非零，
    # 否则 base_pose_proxy_active() 返回 False → solver 进入非 base-pose 路径
    # → inertia teleport 检测可能每帧 reset display_positions → delta 全0。
    any_bpp = any(ch.base_pose_proxy is not None for ch in chunks)
    if any_bpp:
        # 取第一个有效 proxy 的 bpp 指针；solver 用它判断 base-pose 模式是否开启
        first_bpp = next((ch.base_pose_proxy for ch in chunks if ch.base_pose_proxy is not None), None)
        merged_state["base_pose_proxy_ptr"] = int(first_bpp.as_pointer()) if first_bpp is not None else 1
    else:
        merged_state["base_pose_proxy_ptr"] = 0

    # ---- 10. 构建 per-proxy MC2RuntimeParams ----
    from ..runtime_params import build_runtime_params as _build_rp
    per_proxy_runtimes: list = []
    for s, p_owner, ch in zip(valid_settings, proxy_owners, chunks):
        depths = np.asarray(p_owner.state.get("depths", []), dtype=np.float32)
        world_scale = float(p_owner.state.get("init_scale_radius") or 1.0)
        rp = _build_rp(
            curve_cache        = p_owner.center_state.curve_cache,
            depths             = depths,
            substep_count      = max(1, int(substeps)),
            world_scale_nonnegative = max(0.0, world_scale),
            damping                   = float(s.get("damping", 0.2)),
            damping_curve             = s.get("damping_curve"),
            use_tether                = bool(s.get("use_tether", True)),
            tether_compression        = float(s.get("tether_compression", MC2SystemConstants.TETHER_COMPRESSION_LIMIT)),
            use_distance              = bool(s.get("use_distance", True)),
            distance_stiffness        = float(s.get("distance_stiffness", 1.0)),
            distance_stiffness_curve  = s.get("distance_stiffness_curve"),
            use_bend                  = bool(s.get("use_bend", True)),
            bend_stiffness            = float(s.get("bend_stiffness", 0.5)),
            bend_stiffness_curve      = s.get("bend_stiffness_curve"),
            use_angle_restoration     = bool(s.get("use_angle_restoration", True)),
            angle_restoration_stiffness = float(s.get("angle_restoration_stiffness", 0.2)),
            angle_restoration_stiffness_curve = s.get("angle_restoration_stiffness_curve"),
            angle_restoration_velocity_attenuation = float(s.get(
                "angle_restoration_velocity_attenuation",
                MC2SystemConstants.ANGLE_RESTORATION_VELOCITY_ATTENUATION)),
            angle_restoration_velocity_attenuation_curve = s.get(
                "angle_restoration_velocity_attenuation_curve"),
            angle_restoration_gravity_falloff = float(s.get(
                "angle_restoration_gravity_falloff",
                MC2SystemConstants.ANGLE_RESTORATION_GRAVITY_FALLOFF)),
            use_angle_limit           = bool(s.get("use_angle_limit", False)),
            angle_limit               = float(s.get("angle_limit", 0.0)),
            angle_limit_curve         = s.get("angle_limit_curve"),
            angle_limit_stiffness     = float(s.get("angle_limit_stiffness", 1.0)),
            anchor_inertia            = solve_anchor_inertia,
            world_inertia             = world_inertia,
            movement_inertia_smoothing = movement_inertia_smoothing,
            local_inertia             = local_inertia,
            depth_inertia             = depth_inertia,
            centrifugal               = solve_centrifugal,
            movement_speed_limit      = movement_speed_limit,
            rotation_speed_limit      = rotation_speed_limit,
            local_movement_speed_limit = local_movement_speed_limit,
            local_rotation_speed_limit = local_rotation_speed_limit,
            particle_speed_limit      = particle_speed_limit,
            animation_pose_ratio      = float(animation_pose_ratio),
            velocity_weight           = float(merged_state.get("velocity_weight", 0.0)),
            blend_weight              = float(s.get("blend_weight", 1.0)),
            use_max_distance          = bool(s.get("use_max_distance", False)),
            max_distance              = float(s.get("max_distance", 0.0)),
            max_distance_curve        = s.get("max_distance_curve"),
            use_backstop              = bool(s.get("use_backstop", False)),
            backstop_radius           = float(s.get("backstop_radius", 0.0)),
            backstop_distance         = float(s.get("backstop_distance", 0.0)),
            backstop_distance_curve   = s.get("backstop_distance_curve"),
            motion_stiffness          = float(s.get("motion_stiffness", 1.0)),
            normal_axis               = int(normal_axis),
            use_collider_collision    = bool(use_collider_collision),
            collider_friction         = float(collider_friction),
            collider_collision_mode   = int(collider_collision_mode),
        )
        per_proxy_runtimes.append(rp)

    # 以第一个 runtime 作为全局参数来源（重力/惯性/速度限制由 solver 节点统一控制）
    merged_rp = merge_runtime_params(per_proxy_runtimes, chunks, per_proxy_runtimes[0])
    merged_param_slots = merged_rp.param_slots()

    def _merge_particle_param(slot_name: str, attr_name: str, minimum=None, maximum=None, squared_depth: bool = False) -> None:
        values = []
        for runtime, owner in zip(per_proxy_runtimes, proxy_owners):
            depths = np.asarray(owner.state.get("depths", []), dtype=np.float32)
            sample_depths = np.clip(depths * depths, 0.0, 1.0) if squared_depth else np.clip(depths, 0.0, 1.0)
            values.append(params.sample_param(getattr(runtime, attr_name), sample_depths))
        if values:
            merged_param_slots[slot_name] = params.per_particle_param(
                np.ascontiguousarray(np.concatenate(values), dtype=np.float32),
                minimum=minimum,
                maximum=maximum,
            )

    _merge_particle_param("tether_compression", "tether_compression_param", 0.0, 1.0)
    _merge_particle_param("angle_limit_stiffness", "angle_limit_stiffness_param", 0.0, 1.0)
    _merge_particle_param("max_distance", "max_distance_param", 0.0, None, squared_depth=True)
    _merge_particle_param("motion_stiffness", "motion_stiffness_param", 0.0, 1.0, squared_depth=True)
    _merge_particle_param("backstop_radius", "backstop_radius_param", 0.0, None, squared_depth=True)
    _merge_particle_param("backstop_distance", "backstop_distance_param", 0.0, None, squared_depth=True)
    merged_state["param_slots"] = merged_param_slots

    # ---- 11. 碰撞体 ----
    use_collider_any = bool(use_collider_collision)
    coll_mode = int(collider_collision_mode)
    if use_collider_any and coll_mode != 0:
        snap = collision.build_collision_snapshot_from_scene(scene, True, True, False)
        colliders = list(snap.get("colliders") or []) if isinstance(snap, dict) else []
    else:
        colliders = []

    # ---- 12. 一次合并解算 ----
    if all_same_frame and not reset:
        _write_merged_delta_attributes(
            merged_state,
            chunks,
            valid_objs,
            merged_owner.team_state.skip_writing,
        )
        merged_owner.replace_state(merged_state)
        cache_value = _OmniCache.replace(merged_owner_obj) if replace_cache else _OmniCache.mutate(merged_owner_obj)
        return cache_value, valid_objs[0], total_vertex_count, 0

    solve_func = solver_for_backend(backend_label)
    ref_obj = valid_objs[0]   # 为 anchor inertia 提供参考 transform

    def _pv(rp_field: str, fallback=0.0) -> float:
        """从 merged_rp 的 param dict 取均值标量（solver 需要标量，per-particle 数组已存入 param_slots）。"""
        attr = getattr(merged_rp, rp_field, None)
        if isinstance(attr, dict):
            return float(attr.get("value", fallback))
        try:
            return float(attr) if attr is not None else float(fallback)
        except (TypeError, ValueError):
            return float(fallback)

    next_merged_state = solve_func(
        merged_state,
        ref_obj,
        scene,
        substeps,
        iterations,
        gravity_dir,
        gravity_power,
        gravity_falloff,
        stablization_time_after_reset,
        merged_rp.blend_weight,
        _pv("damping_param", 0.2),
        None,   # damping_curve（已展开为 per_particle）
        any(bool(s.get("use_tether", True)) for s in valid_settings),
        _pv("tether_compression_param", MC2SystemConstants.TETHER_COMPRESSION_LIMIT),
        any(bool(s.get("use_distance", True)) for s in valid_settings),
        _pv("distance_stiffness_param", 1.0),
        None,
        any(bool(s.get("use_bend", True)) for s in valid_settings),
        _pv("bend_stiffness_param", 0.5),
        None,
        any(bool(s.get("use_angle_restoration", True)) for s in valid_settings),
        _pv("angle_restoration_param", 0.2),
        None,
        _pv("angle_restoration_velocity_attenuation_param",
            MC2SystemConstants.ANGLE_RESTORATION_VELOCITY_ATTENUATION),
        None,
        _pv("angle_restoration_gravity_falloff_param",
            MC2SystemConstants.ANGLE_RESTORATION_GRAVITY_FALLOFF),
        any(bool(s.get("use_angle_limit", False)) for s in valid_settings),
        _pv("angle_limit_param", 0.0),
        None,
        merged_rp.angle_limit_stiffness,
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
        float(animation_pose_ratio),
        any(bool(s.get("use_max_distance", False)) for s in valid_settings),
        _pv("max_distance_param", 0.0),
        None,
        any(bool(s.get("use_backstop", False)) for s in valid_settings),
        _pv("backstop_radius_param", 0.0),
        _pv("backstop_distance_param", 0.0),
        None,
        _pv("motion_stiffness_param", 0.0),
        int(normal_axis),
        use_collider_any,
        float(collider_friction),   # 传原始标量，solver 内部做 dynamic/static 分解
        coll_mode,
        None,   # timing
        colliders=colliders,
        runtime_caches=merged_owner.runtime_cache_slots(),
        center_state=merged_owner.center_state,
        team_state=merged_owner.team_state,
    )
    next_merged_state["frame"] = current_frame
    next_merged_state["settings_key"] = merged_settings_key

    # ---- 13. 分块写回各 proxy delta ----
    _write_merged_delta_attributes(
        next_merged_state,
        chunks,
        valid_objs,
        merged_owner.team_state.skip_writing,
    )

    # 把解算后的粒子状态回写到 per-proxy owner，保证下一帧连续性
    for p_owner, ch, proxy_settings_key in zip(proxy_owners, chunks, proxy_settings_keys):
        proxy_state = dict(p_owner.state)
        proxy_state["frame"] = current_frame
        proxy_state["settings_key"] = proxy_settings_key
        copy_merged_slice_to_proxy(next_merged_state, proxy_state, ch)
        p_owner.replace_state(proxy_state)

    merged_owner.replace_state(next_merged_state)
    cache_value = _OmniCache.replace(merged_owner_obj) if replace_cache else _OmniCache.mutate(merged_owner_obj)
    return cache_value, valid_objs[0], total_vertex_count, 0
