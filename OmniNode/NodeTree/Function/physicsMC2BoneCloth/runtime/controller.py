"""BoneCloth 节点运行中控。

职责与 physicsMC2/runtime/controller.py 对齐：输入校验、cache 命中/重建、
per-frame base pose 同步、collider 快照、跳帧冷启动、solver 调用、骨骼姿态写回。

关键复用：
  - MC2RuntimeOwner：拓扑无关的 cache owner，直接复用，不新建 BoneRuntimeOwner
  - solve_meshcloth / solve_meshcloth_native_core：solver 只认 state key 契约
  - cold_restart_runtime_state：冷启动粒子状态重置
差异点：
  - 输入是 armature + root_bones 列表，不是 mesh proxy
  - 无 base_pose_proxy 双对象；base pose 直接每帧从骨架 evaluated pose 采样
  - 写回 PoseBone.matrix_basis，不写 GN delta 属性
"""

from __future__ import annotations

import time

import bpy

from ....OmniNodeSocketMapping import _OmniCache
from ...physicsMC2 import collision, state as mc2_state
from ...physicsMC2.backends import normalize_backend_label, solver_for_backend
from ...physicsMC2.runtime.restart import cold_restart_runtime_state
from .. import bone_build, bone_io


def _dispose_cache_value(cache_state) -> None:
    if cache_state is None or isinstance(cache_state, (str, bool, int, float)):
        return
    if hasattr(cache_state, "value"):
        _dispose_cache_value(getattr(cache_state, "value", None))
        return
    dispose = getattr(cache_state, "omni_cache_dispose", None)
    if callable(dispose):
        try:
            dispose("bonecloth invalid RNA input")
        except Exception:
            pass


def _resolve_armature(armature_obj) -> bpy.types.Object | None:
    if not isinstance(armature_obj, bpy.types.Object):
        return None
    if armature_obj.type != "ARMATURE":
        return None
    return armature_obj


def _flatten_root_bone_names(root_bones) -> list[str]:
    """把 list[_OmniBone] 多重输入展平成骨名列表，保持用户填入顺序。"""
    names: list[str] = []
    if root_bones is None:
        return names
    stack = list(root_bones) if isinstance(root_bones, (list, tuple)) else [root_bones]
    for value in stack:
        if isinstance(value, (list, tuple)):
            for inner in value:
                names.extend(_flatten_root_bone_names(inner))
            continue
        if isinstance(value, dict):
            name = str(value.get("bone") or "").strip()
            if name:
                names.append(name)
        elif isinstance(value, str):
            name = value.strip()
            if name:
                names.append(name)
    return names


def _write_records_cache(cache_owner: mc2_state.MC2RuntimeOwner) -> dict:
    return cache_owner.runtime_cache("bonecloth_io")


def run_bone_cloth_mc2_node(
    cache_state: _OmniCache,
    armature_obj: bpy.types.Object,
    root_bones,
    connection_mode: int,
    rotational_interpolation: float,
    scene: bpy.types.Scene,
    enabled: bool,
    reset: bool,
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
    animation_pose_ratio: float,
    use_max_distance: bool,
    max_distance: float,
    max_distance_curve,
    collision_radius: float,
    use_backstop: bool,
    backstop_radius: float,
    backstop_distance: float,
    backstop_distance_curve,
    motion_stiffness: float,
    normal_axis: int,
    use_collider_collision: bool,
    collider_friction: float,
    collider_collision_mode: int,
    time_scale: float,
    skip_writing: bool,
    debug_output: bool,
    solver_backend: str = "py",
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    backend_label = normalize_backend_label(solver_backend)
    armature = _resolve_armature(armature_obj)
    if armature is None:
        _dispose_cache_value(cache_state)
        return _OmniCache.replace(None), None, 0, 0
    scene = scene or bpy.context.scene

    root_bone_names = _flatten_root_bone_names(root_bones)
    chains = bone_build.collect_bone_chains(armature, root_bone_names)
    if not chains:
        _dispose_cache_value(cache_state)
        return _OmniCache.replace(None), armature, 0, 0

    bone_names = bone_build.flatten_chain_bone_names(chains)
    vertex_count = len(bone_names)
    output_key = armature.name_full
    topology_key = bone_build.bone_topology_key(armature, bone_names, int(connection_mode))

    cache_owner = cache_state if isinstance(cache_state, mc2_state.MC2RuntimeOwner) else None
    prev_state = cache_owner.state if (cache_owner is not None and isinstance(cache_owner.state, dict)) else None
    state_matches = (
        prev_state is not None
        and prev_state.get("kind") == mc2_state.MC2_CACHE_KIND
        and prev_state.get("bone_topology_key") == topology_key
    )
    state = prev_state if state_matches else None
    replace_cache = cache_owner is None or not state_matches

    cached_frame = prev_state.get("frame") if isinstance(prev_state, dict) else None
    current_frame = int(getattr(scene, "frame_current", 0) or 0)
    continuous_frame = cached_frame is not None and current_frame == cached_frame + 1
    restart_required = reset or not continuous_frame or not state_matches
    solve_anchor_inertia = 1.0 if restart_required else anchor_inertia
    solve_motion_stiffness = 0.0 if restart_required else motion_stiffness
    solve_centrifugal = 0.0 if restart_required else centrifugal

    # 重建 state（首帧 / reset / 跳帧 / 拓扑变化）
    if restart_required or not isinstance(state, dict):
        replace_cache = True
        cache_owner = mc2_state.MC2RuntimeOwner()
        state = bone_build.build_bone_state(
            armature,
            chains,
            int(connection_mode),
            output_key,
            topology_key,
            collision_radius,
        )
        cache_owner.replace_state(state)
    else:
        cache_owner = mc2_state.ensure_runtime_owner(cache_owner)
        state = bone_build.sync_bone_state_to_pose(state, armature, chains, cache_owner.center_state)
        cache_owner.replace_state(state)

    cache_owner.team_state.apply_lifecycle_context(
        state,
        time_scale=time_scale,
        skip_writing=skip_writing,
    )

    # 写回记录（拓扑不变时缓存复用）
    io_cache = _write_records_cache(cache_owner)
    write_records = io_cache.get("write_records")
    if write_records is None or io_cache.get("topology_key") != topology_key:
        write_records = bone_io.build_bone_write_records(armature, chains)
        io_cache["write_records"] = write_records
        io_cache["topology_key"] = topology_key

    # 约束数统计：distance 边 + bend（distance-approx 或 dihedral/volume）
    n_distance = len(state.get("edge_i", ())) if use_distance else 0
    n_bend = 0
    if use_bend:
        if len(state.get("dihedral_pairs", ())) > 0 or len(state.get("volume_pairs", ())) > 0:
            n_bend = len(state.get("dihedral_pairs", ())) + len(state.get("volume_pairs", ()))
        else:
            n_bend = len(state.get("bend_i", ()))
    constraint_count = n_distance + n_bend

    if debug_output and restart_required:
        # 拓扑摘要：重建时打印一次，不每帧打印
        edges = state.get("edges")
        triangles = state.get("triangles")
        chain_info = ", ".join(
            f"{c['root']}({len(c['bones'])}骨)" for c in chains
        )
        n_edges = len(edges) if edges is not None else 0
        n_tris = len(triangles) if triangles is not None else 0
        # 横向边 = 总边 - 纵向骨链父子边（每链链长-1 条）
        n_longitudinal = sum(max(len(c["bones"]) - 1, 0) for c in chains)
        n_lateral = n_edges - n_longitudinal
        mode_label = {0: "Line", 1: "SequentialNonLoop", 2: "SequentialLoop"}.get(
            int(connection_mode), str(connection_mode)
        )
        print(
            f"[骨骼布料-MC2] {armature.name} | "
            f"骨链: {chain_info} | "
            f"模式: {mode_label} | "
            f"粒子={vertex_count} 边={n_edges}(纵{n_longitudinal}/横{n_lateral}) "
            f"三角={n_tris} | "
            f"约束: distance={n_distance} bend={n_bend}"
        )

    if not enabled:
        next_state = mc2_state.inherit_runtime_slots(state, dict(state))
        next_state["frame"] = current_frame
        cache_owner.replace_state(next_state)
        cache_value = _OmniCache.replace(cache_owner) if replace_cache else _OmniCache.mutate(cache_owner)
        return cache_value, armature, vertex_count, constraint_count

    # 冷启动：重置粒子动态状态并把骨骼恢复到初始姿态
    if restart_required:
        state = cold_restart_runtime_state(
            state,
            armature,
            cache_owner.center_state,
            cache_owner.team_state,
            blend_weight,
        )
        bone_io.restore_initial_pose(armature, write_records)
        next_state = mc2_state.inherit_runtime_slots(state, dict(state))
        next_state["frame"] = current_frame
        cache_owner.replace_state(next_state)
        cache_value = _OmniCache.replace(cache_owner) if replace_cache else _OmniCache.mutate(cache_owner)
        return cache_value, armature, vertex_count, constraint_count

    # collider 快照
    if use_collider_collision and int(collider_collision_mode) != 0:
        collision_snapshot = collision.build_collision_snapshot_from_scene(scene, True, True, False)
        colliders = list(collision_snapshot.get("colliders") or []) if isinstance(collision_snapshot, dict) else []
    else:
        colliders = []

    solve_func = solver_for_backend(backend_label)
    next_state = solve_func(
        state,
        armature,
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
        None,
        colliders=colliders,
        runtime_caches=cache_owner.runtime_cache_slots(),
        center_state=cache_owner.center_state,
        team_state=cache_owner.team_state,
    )

    next_state["frame"] = current_frame

    if not cache_owner.team_state.skip_writing:
        bone_io.write_bone_rotations(
            armature,
            write_records,
            next_state["display_positions"],
            rotational_interpolation,
            write_runtime=io_cache,
        )

    cache_owner.replace_state(next_state)
    cache_value = _OmniCache.replace(cache_owner) if replace_cache else _OmniCache.mutate(cache_owner)
    return cache_value, armature, vertex_count, constraint_count
