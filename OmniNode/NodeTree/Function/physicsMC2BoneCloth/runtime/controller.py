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

import bpy

from ....OmniNodeSocketMapping import _OmniCache
from ...physicsMC2MeshCloth import collision, state as mc2_state
from ...physicsMC2MeshCloth.backends import normalize_backend_label, solver_for_backend
from ...physicsMC2MeshCloth.runtime.restart import cold_restart_runtime_state
from ...physicsMC2MeshCloth.runtime.timing import begin_timing
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



def _extract_chain_physics(chains: list) -> dict:
    """从骨链列表提取代表性物理参数（取第一条有 params 的链）。

    当所有链使用相同物理参数时，直接作为 solve_func 的标量输入；
    链间有差异时，extract 提供基准值，expand_chain_params_to_particle_arrays
    负责构建 per-particle 覆盖数组。无任何链有 params 时返回系统默认值。
    """
    from ...physicsMC2MeshCloth.constants import MC2SystemConstants as _C
    defaults = {
        "rotational_interpolation":              1.0,
        "blend_weight":                          1.0,
        "damping":                               0.2,
        "damping_curve":                         None,
        "use_tether":                            True,
        "tether_compression":                    _C.TETHER_COMPRESSION_LIMIT,
        "use_distance":                          True,
        "distance_stiffness":                    1.0,
        "distance_stiffness_curve":              None,
        "use_bend":                              True,
        "bend_stiffness":                        0.5,
        "bend_stiffness_curve":                  None,
        "use_angle_restoration":                 True,
        "angle_restoration_stiffness":           0.2,
        "angle_restoration_stiffness_curve":     None,
        "angle_restoration_velocity_attenuation": _C.ANGLE_RESTORATION_VELOCITY_ATTENUATION,
        "angle_restoration_velocity_attenuation_curve": None,
        "angle_restoration_gravity_falloff":     _C.ANGLE_RESTORATION_GRAVITY_FALLOFF,
        "use_angle_limit":                       False,
        "angle_limit":                           0.0,
        "angle_limit_curve":                     None,
        "angle_limit_stiffness":                 1.0,
        "use_max_distance":                      False,
        "max_distance":                          0.0,
        "max_distance_curve":                    None,
        "use_backstop":                          False,
        "backstop_radius":                       0.0,
        "backstop_distance":                     0.0,
        "backstop_distance_curve":               None,
        "motion_stiffness":                      1.0,
        "normal_axis":                           1,
        "animation_pose_ratio":                  0.0,
        "use_collider_collision":                True,
        "collider_friction":                     0.05,
        "collider_collision_mode":               1,
    }
    for chain in chains:
        params = chain.get("params")
        if isinstance(params, dict) and params:
            merged = dict(defaults)
            merged.update(params)
            return merged
    return defaults


def run_bone_cloth_mc2_node(
    cache_state: _OmniCache,
    bone_cloth_chains,
    connection_mode: int,
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
    scene = scene or bpy.context.scene

    settings = bone_build.flatten_bone_cloth_chain_settings(bone_cloth_chains)

    # 骨架从链设置里提取（所有链必须属于同一骨架）
    armature = None
    for s in settings:
        candidate = _resolve_armature(s.get("armature"))
        if candidate is not None:
            armature = candidate
            break
    if armature is None:
        _dispose_cache_value(cache_state)
        return _OmniCache.replace(None), None, 0, 0

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

    # 从链的 params 字段提取物理参数（骨链物理参数-MC2 节点写入）
    physics = _extract_chain_physics(chains)
    rotational_interpolation = physics["rotational_interpolation"]
    blend_weight             = physics["blend_weight"]
    damping                  = physics["damping"]
    damping_curve            = physics["damping_curve"]
    use_tether               = physics["use_tether"]
    tether_compression       = physics["tether_compression"]
    use_distance             = physics["use_distance"]
    distance_stiffness       = physics["distance_stiffness"]
    distance_stiffness_curve = physics["distance_stiffness_curve"]
    use_bend                 = physics["use_bend"]
    bend_stiffness           = physics["bend_stiffness"]
    bend_stiffness_curve     = physics["bend_stiffness_curve"]
    use_angle_restoration    = physics["use_angle_restoration"]
    angle_restoration_stiffness = physics["angle_restoration_stiffness"]
    angle_restoration_stiffness_curve = physics["angle_restoration_stiffness_curve"]
    angle_restoration_velocity_attenuation = physics["angle_restoration_velocity_attenuation"]
    angle_restoration_velocity_attenuation_curve = physics["angle_restoration_velocity_attenuation_curve"]
    angle_restoration_gravity_falloff = physics["angle_restoration_gravity_falloff"]
    use_angle_limit          = physics["use_angle_limit"]
    angle_limit              = physics["angle_limit"]
    angle_limit_curve        = physics["angle_limit_curve"]
    angle_limit_stiffness    = physics["angle_limit_stiffness"]
    use_max_distance         = physics["use_max_distance"]
    max_distance             = physics["max_distance"]
    max_distance_curve       = physics["max_distance_curve"]
    use_backstop             = physics["use_backstop"]
    backstop_radius          = physics["backstop_radius"]
    backstop_distance        = physics["backstop_distance"]
    backstop_distance_curve  = physics["backstop_distance_curve"]
    motion_stiffness         = physics["motion_stiffness"]
    normal_axis              = physics["normal_axis"]
    animation_pose_ratio     = physics["animation_pose_ratio"]
    use_collider_collision   = physics["use_collider_collision"]
    collider_friction        = physics["collider_friction"]
    collider_collision_mode  = physics["collider_collision_mode"]

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
        raw_colliders = list(collision_snapshot.get("colliders") or []) if isinstance(collision_snapshot, dict) else []
        # BoneCloth 特有修正：
        # 1. project_vertex_collision 里 `collider["owner"] is owner_obj` 本是为 MeshCloth 防止
        #    网格与自身骨骼碰撞而设计的，但在 BoneCloth 里会把全部骨骼碰撞体排除掉。
        #    修复：把同骨架的骨骼碰撞体 owner 置 None，绕过自排除检查。
        # 2. 裙骨自身（被模拟的布料骨骼）如果设置了碰撞属性，也会进入 colliders。
        #    解算时粒子会被推离"自身上一帧位置" → 正反馈 → 乱飞爆炸。
        #    修复：把属于当前骨架且骨骼名在 bone_names 中的条目直接剔除。
        cloth_bone_set = set(bone_names)
        colliders = [
            dict(c, owner=None) if c.get("owner_type") == "BONE" and c.get("owner") is armature else c
            for c in raw_colliders
            if not (
                c.get("owner_type") == "BONE"
                and c.get("owner") is armature
                and c.get("bone") in cloth_bone_set
            )
        ]
    else:
        colliders = []

    if debug_output:
        bone_coll_count = sum(
            1 for c in colliders if c.get("owner_type") == "BONE"
        )
        obj_coll_count = sum(
            1 for c in colliders if c.get("owner_type") == "OBJECT"
        )
        print(
            f"[BoneCloth COLLISION] 帧={current_frame} "
            f"use_collider={use_collider_collision} mode={collider_collision_mode} "
            f"碰撞体总数={len(colliders)}（骨骼={bone_coll_count} 物体={obj_coll_count}）"
        )

    solve_func = solver_for_backend(backend_label)

    # per-chain 物理参数覆盖注入：
    # 若有链使用了 boneClothMC2ChainPhysics 节点设置了独立参数，展开成粒子数组后存入
    # state["chain_param_overrides"]，由 solver._apply_chain_param_overrides 在
    # build_runtime_params 之后读取并 patch MC2RuntimeParams，对 Python 和 C++ 路径均生效。
    # 无 per-chain override 时 expand 函数快速返回空 dict，不影响性能。
    chain_param_overrides = bone_build.expand_chain_params_to_particle_arrays(
        chains,
        vertex_count,
        global_fallbacks={
            "damping":                                float(damping),
            "distance_stiffness":                     float(distance_stiffness),
            "bend_stiffness":                         float(bend_stiffness),
            "angle_restoration_stiffness":            float(angle_restoration_stiffness),
            "angle_restoration_velocity_attenuation": float(angle_restoration_velocity_attenuation),
            "angle_restoration_gravity_falloff":      float(angle_restoration_gravity_falloff),
            "angle_limit":                            float(angle_limit),
            "angle_limit_stiffness":                  float(angle_limit_stiffness),
            "tether_compression":                     float(tether_compression),
            "blend_weight":                           float(blend_weight),
        },
    )
    if chain_param_overrides:
        state["chain_param_overrides"] = chain_param_overrides
    else:
        state.pop("chain_param_overrides", None)

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
            # 使用用户配置的 blend_weight（而非 state["blend_weight"]，
            # 那是 MC2 内部速度/混合累加器，初值为 0，在 BoneCloth 写回时不适用）。
            blend_weight,
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
