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
from ...physicsMC2MeshCloth import collision, state as mc2_state
from ...physicsMC2MeshCloth.backends import normalize_backend_label, solver_for_backend
from ...physicsMC2MeshCloth.runtime.restart import cold_restart_runtime_state
from ...physicsMC2MeshCloth.runtime.timing import begin_timing, publish_debug_timing
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


def _write_records_cache(cache_owner: mc2_state.MC2RuntimeOwner) -> dict:
    return cache_owner.runtime_cache("bonecloth_io")


def run_bone_cloth_mc2_node(
    cache_state: _OmniCache,
    armature_obj: bpy.types.Object,
    bone_cloth_chains,
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
    timing = begin_timing() if debug_output else None
    armature = _resolve_armature(armature_obj)
    if armature is None:
        _dispose_cache_value(cache_state)
        return _OmniCache.replace(None), None, 0, 0
    scene = scene or bpy.context.scene

    settings = bone_build.flatten_bone_cloth_chain_settings(bone_cloth_chains)
    chains = bone_build.chains_from_settings(settings)
    if debug_output:
        raw_len = len(bone_cloth_chains) if hasattr(bone_cloth_chains, "__len__") else "?"
        print(
            f"[BoneCloth INPUT] raw inputs={raw_len}  "
            f"settings after flatten={len(settings)}  "
            f"chains after from_settings={len(chains)}"
        )
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

    if debug_output:
        import numpy as _np
        # ─── 每次重建时输出完整拓扑摘要 ───
        if restart_required:
            chain_info = ", ".join(f"{c['root']}({len(c['bones'])}骨)" for c in chains)
            depths = state.get("depths")
            depth_str = str(_np.round(depths, 2).tolist()) if depths is not None else "?"
            attrs  = state.get("attributes")
            attr_str = str(attrs.tolist()) if attrs is not None else "?"
            mode_label = {0: "Line", 1: "SequentialNonLoop", 2: "SequentialLoop"}.get(
                int(connection_mode), str(connection_mode))
            print(
                f"\n[BoneCloth REBUILD] 帧={current_frame} armature={armature.name} "
                f"mode={mode_label}\n"
                f"  settings 数量={len(settings)}  chains 数量={len(chains)}\n"
                f"  骨链: {chain_info}\n"
                f"  粒子总数={vertex_count}  depths={depth_str}\n"
                f"  attributes={attr_str}\n"
                f"  constraint: distance={n_distance} bend={n_bend}"
            )
        # ─── 每帧输出连续帧状态 ───
        else:
            disp = state.get("display_positions")
            base = state.get("base_positions")
            if disp is not None and base is not None:
                delta = float(_np.max(_np.abs(_np.asarray(disp) - _np.asarray(base))))
            else:
                delta = 0.0
            print(
                f"[BoneCloth] 帧={current_frame} "
                f"cached_frame={cached_frame} continuous={continuous_frame} "
                f"max|disp-base|={delta:.5f}"
            )

    if not enabled:
        next_state = mc2_state.inherit_runtime_slots(state, dict(state))
        next_state["frame"] = current_frame
        # 与 MeshCloth clear_delta_attribute 等价：禁用时把骨骼还原到动画姿态
        if not cache_owner.team_state.skip_writing:
            bone_io.write_bone_rotations(
                armature, chains, write_records,
                state["base_positions"], state["base_positions"],
                rotational_interpolation, blend_weight,
                write_runtime=io_cache,
                step_basic_rotations=state.get("step_basic_rotations"),
                vertex_local_positions=state.get("vertex_local_positions"),
                vertex_local_rotations=state.get("vertex_local_rotations"),
                parent_indices=state.get("parent_indices"),
                baseline_start=state.get("baseline_start"),
                baseline_count=state.get("baseline_count"),
                baseline_data=state.get("baseline_data"),
                attributes=state.get("attributes"),
                anime_ratio=float(animation_pose_ratio),
            )
            armature.update_tag()
        cache_owner.replace_state(next_state)
        cache_value = _OmniCache.replace(cache_owner) if replace_cache else _OmniCache.mutate(cache_owner)
        return cache_value, armature, vertex_count, constraint_count

    # 冷启动：重置粒子动态状态，骨骼写回 base_positions（animated pose）
    if restart_required:
        state = cold_restart_runtime_state(
            state,
            armature,
            cache_owner.center_state,
            cache_owner.team_state,
            blend_weight,
        )
        # 把 base_positions（当前 animated pose）写回骨骼，避免跳帧后骨骼停留在上一帧物理位置。
        # 注意：不用 restore_initial_pose（identity 重置），那会造成首帧爆炸。
        # 用 base_positions 作为 display_positions 写回，等效于把骨骼还原到动画姿态。
        if not cache_owner.team_state.skip_writing:
            bone_io.write_bone_rotations(
                armature, chains, write_records,
                state["base_positions"], state["base_positions"],
                rotational_interpolation, blend_weight,
                write_runtime=io_cache,
                step_basic_rotations=state.get("step_basic_rotations"),
                vertex_local_positions=state.get("vertex_local_positions"),
                vertex_local_rotations=state.get("vertex_local_rotations"),
                parent_indices=state.get("parent_indices"),
                baseline_start=state.get("baseline_start"),
                baseline_count=state.get("baseline_count"),
                baseline_data=state.get("baseline_data"),
                attributes=state.get("attributes"),
                anime_ratio=float(animation_pose_ratio),
            )
            armature.update_tag()  # 通知 Blender 骨架数据已变化，触发视口重绘
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
        timing,
        colliders=colliders,
        runtime_caches=cache_owner.runtime_cache_slots(),
        center_state=cache_owner.center_state,
        team_state=cache_owner.team_state,
    )

    next_state["frame"] = current_frame

    if not cache_owner.team_state.skip_writing:
        bone_io.write_bone_rotations(
            armature, chains, write_records,
            next_state["display_positions"], next_state["base_positions"],
            rotational_interpolation,
            float(next_state.get("blend_weight", blend_weight)),
            write_runtime=io_cache,
            step_basic_rotations=next_state.get("step_basic_rotations"),
            vertex_local_positions=next_state.get("vertex_local_positions"),
            vertex_local_rotations=next_state.get("vertex_local_rotations"),
            parent_indices=next_state.get("parent_indices"),
            baseline_start=next_state.get("baseline_start"),
            baseline_count=next_state.get("baseline_count"),
            baseline_data=next_state.get("baseline_data"),
            attributes=next_state.get("attributes"),
            anime_ratio=float(animation_pose_ratio),
        )
        armature.update_tag()  # 通知 Blender 骨架数据已变化，触发视口重绘
        if debug_output:
            import numpy as _np
            disp = _np.asarray(next_state["display_positions"])
            base = _np.asarray(next_state["base_positions"])
            # 逐链报告最大位移和写回的骨骼名
            print(f"[BoneCloth WRITEBACK] 帧={current_frame} records={len(write_records)}")
            cursor = 0
            for ci, ch in enumerate(chains):
                n = len(ch.get("bones") or [])
                nroot = ch.get("root", "?")
                if n > 0:
                    dz = float(_np.max(_np.abs(disp[cursor:cursor+n, 2] - base[cursor:cursor+n, 2])))
                    print(f"  chain{ci} root={nroot} 粒子[{cursor}:{cursor+n}] 最大Z位移={dz:.5f}")
                cursor += n

    cache_owner.replace_state(next_state)
    cache_value = _OmniCache.replace(cache_owner) if replace_cache else _OmniCache.mutate(cache_owner)
    return cache_value, armature, vertex_count, constraint_count
