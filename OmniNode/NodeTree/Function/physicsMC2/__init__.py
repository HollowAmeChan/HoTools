"""MeshCloth MC2 的 OmniNode 节点入口。

这里只管理 Blender 节点生命周期：cache、跳帧、reset、碰撞快照收集和
shape key 写回。物理数组构建与求解分别由 state.py 和 solver.py 负责。
"""

import time

import bpy
import mathutils

from ...FunctionNodeCore import omni
from ...OmniNodeSocketMapping import _OmniCache
from .. import _Color
from . import blender_io, collision, mesh_build, solver, state as mc2_state


_DEBUG_PROFILES = {}


def _begin_timing() -> dict:
    return {"start": time.perf_counter(), "stages": {}}


def _add_timing(timing: dict | None, stage: str, seconds: float) -> None:
    if timing is None:
        return
    stages = timing.setdefault("stages", {})
    stages[stage] = stages.get(stage, 0.0) + max(float(seconds), 0.0)


def _publish_debug_timing(
    obj: bpy.types.Object,
    shape_key_name: str,
    frame: int,
    vertex_count: int,
    constraint_count: int,
    timing: dict | None,
) -> None:
    if timing is None:
        return

    _add_timing(timing, "total", time.perf_counter() - float(timing.get("start", time.perf_counter())))
    key = (int(obj.as_pointer()), str(shape_key_name), "mc2_py")
    now = time.perf_counter()
    profile = _DEBUG_PROFILES.get(key)
    if profile is None:
        profile = {
            "last_print": now,
            "frames": 0,
            "frame": frame,
            "vertex_count": vertex_count,
            "constraint_count": constraint_count,
            "stages": {},
        }
        _DEBUG_PROFILES[key] = profile

    profile["frames"] += 1
    profile["frame"] = frame
    profile["vertex_count"] = vertex_count
    profile["constraint_count"] = constraint_count
    totals = profile["stages"]
    for stage, seconds in timing.get("stages", {}).items():
        totals[stage] = totals.get(stage, 0.0) + float(seconds)

    if now - float(profile["last_print"]) < 1.0:
        return

    sample_count = max(int(profile["frames"]), 1)
    ordered_stages = (
        "validate",
        "cache",
        "restore",
        "rebuild",
        "transform",
        "colliders",
        "solve_setup",
        "predict",
        "pin",
        "tether",
        "distance",
        "bend",
        "collision",
        "motion",
        "post",
        "solve_total",
        "write",
        "total",
    )
    used = set()
    stage_text = []
    for stage in ordered_stages:
        if stage in totals:
            used.add(stage)
            stage_text.append(f"{stage}={totals[stage] / sample_count * 1000.0:.3f}ms")
    for stage in sorted(set(totals.keys()) - used):
        stage_text.append(f"{stage}={totals[stage] / sample_count * 1000.0:.3f}ms")

    print(
        f"[MeshClothMC2:py] obj={obj.name_full} key={shape_key_name} "
        f"frame={profile['frame']} samples={sample_count} verts={profile['vertex_count']} "
        f"constraints={profile['constraint_count']} "
        + " ".join(stage_text)
    )

    _DEBUG_PROFILES[key] = {
        "last_print": now,
        "frames": 0,
        "stages": {},
    }


def _run_mesh_cloth_mc2_node(
    cache_state: _OmniCache,
    proxy_obj: bpy.types.Object,
    scene: bpy.types.Scene,
    enabled: bool,
    reset: bool,
    substeps: int,
    iterations: int,
    gravity_dir,
    gravity_power: float,
    damping: float,
    distance_stiffness: float,
    bend_stiffness: float,
    max_distance: float,
    collision_radius: float,
    backstop_radius: float,
    backstop_distance: float,
    collider_friction: float,
    debug_output: bool,
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    timing = _begin_timing() if debug_output else None
    stage_start = time.perf_counter() if timing is not None else None
    obj = blender_io.require_mesh_object(proxy_obj, "proxy_obj")
    scene = scene or bpy.context.scene
    shape_key_name = blender_io.output_shape_key_name(obj)
    target_key = blender_io.ensure_target_shape_key(obj, shape_key_name)
    if timing is not None:
        _add_timing(timing, "validate", time.perf_counter() - stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    mesh_signature_key = mesh_build.mesh_signature_key(obj)
    config_key = mesh_build.config_key(obj, shape_key_name, mesh_signature_key, collision_radius)
    vertex_count = len(obj.data.vertices)
    state = (
        cache_state
        if mc2_state.state_matches(cache_state, obj, shape_key_name, mesh_signature_key, config_key)
        else None
    )
    cached_frame = blender_io.cache_frame(state)
    current_frame = int(getattr(scene, "frame_current", 0) or 0)
    if timing is not None:
        _add_timing(timing, "cache", time.perf_counter() - stage_start)

    if not reset and cached_frame is not None and current_frame != cached_frame + 1:
        stage_start = time.perf_counter() if timing is not None else None
        blender_io.restore_rest_to_shape_key(obj, target_key, state)
        if timing is not None:
            _add_timing(timing, "restore", time.perf_counter() - stage_start)
            _publish_debug_timing(obj, shape_key_name, current_frame, vertex_count, 0, timing)
        return None, obj, vertex_count, 0

    if reset or not isinstance(state, dict):
        stage_start = time.perf_counter() if timing is not None else None
        blender_io.restore_rest_to_shape_key(obj, target_key, state)
        if timing is not None:
            _add_timing(timing, "restore", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        state = mc2_state.build_state(obj, shape_key_name, mesh_signature_key, config_key, collision_radius)
        if timing is not None:
            _add_timing(timing, "rebuild", time.perf_counter() - stage_start)
    else:
        stage_start = time.perf_counter() if timing is not None else None
        state = mc2_state.sync_state_to_object_transform(state, obj)
        if timing is not None:
            _add_timing(timing, "transform", time.perf_counter() - stage_start)

    dihedral_constraint_count = len(state.get("dihedral_pairs", ()))
    volume_constraint_count = len(state.get("volume_pairs", ()))
    bend_constraint_count = (
        dihedral_constraint_count + volume_constraint_count
        if dihedral_constraint_count > 0 or volume_constraint_count > 0
        else len(state["bend_distance_i"])
    )
    constraint_count = len(state["edge_i"]) + bend_constraint_count

    if not enabled:
        next_state = dict(state)
        next_state["frame"] = current_frame
        _publish_debug_timing(obj, shape_key_name, current_frame, vertex_count, constraint_count, timing)
        return next_state, obj, vertex_count, constraint_count

    stage_start = time.perf_counter() if timing is not None else None
    collision_snapshot = collision.build_collision_snapshot_from_scene(scene, True, True, False)
    colliders = list(collision_snapshot.get("colliders") or []) if isinstance(collision_snapshot, dict) else []
    if timing is not None:
        _add_timing(timing, "colliders", time.perf_counter() - stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    next_state = solver.solve_meshcloth(
        state,
        obj,
        scene,
        substeps,
        iterations,
        gravity_dir,
        gravity_power,
        damping,
        distance_stiffness,
        bend_stiffness,
        max_distance,
        backstop_radius,
        backstop_distance,
        collider_friction,
        timing,
        colliders=colliders,
    )
    if timing is not None:
        _add_timing(timing, "solve_total", time.perf_counter() - stage_start)

    next_state["frame"] = current_frame
    stage_start = time.perf_counter() if timing is not None else None
    blender_io.write_world_positions_to_shape_key(obj, target_key, next_state["display_positions"])
    if timing is not None:
        _add_timing(timing, "write", time.perf_counter() - stage_start)
        _publish_debug_timing(obj, shape_key_name, current_frame, vertex_count, constraint_count, timing)
    return next_state, obj, vertex_count, constraint_count


@omni(
    enable=True,
    bl_label="网格布料-MC2",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "低模代理",
        "场景",
        "启用",
        "重置",
        "子步数",
        "迭代",
        "重力方向",
        "重力强度",
        "阻尼",
        "距离刚度",
        "弯曲刚度",
        "最大距离",
        "碰撞半径",
        "Backstop半径",
        "Backstop距离",
        "碰撞摩擦",
        "调试输出",
    ],
    input_init={
        "substeps": {"min_value": 1, "max_value": 16},
        "iterations": {"min_value": 0, "max_value": 64},
        "gravity_power": {"min_value": 0.0, "max_value": 100.0},
        "damping": {"min_value": 0.0, "max_value": 1.0},
        "distance_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "bend_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "max_distance": {"min_value": 0.0},
        "backstop_radius": {"min_value": 0.0, "max_value": 10.0},
        "backstop_distance": {"min_value": 0.0},
        "collision_radius": {"min_value": 0.0},
        "collider_friction": {"min_value": 0.0, "max_value": 0.5},
    },
    _OUTPUT_NAME=["缓存", "低模代理", "顶点数", "约束数"],
    omni_description="""
    MC2 风格 MeshCloth Python 参考解算器。
    输入 mesh 永远就是被直接驱动的低模代理；解算器永远不做减面或高低模映射。
    状态在世界空间中计算，并沿用 SpringBone 风格的连续帧语义：只有下一连续帧
    可以继承 cache 中的速度继续推进。
    """,
)
def meshClothMC2(
    cache_state: _OmniCache,
    proxy_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    iterations: int = 4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 9.8,
    damping: float = 0.04,
    distance_stiffness: float = 1.0,
    bend_stiffness: float = 0.5,
    max_distance: float = 0.0,
    collision_radius: float = 0.0,
    backstop_radius: float = 0.0,
    backstop_distance: float = 0.0,
    collider_friction: float = 0.05,
    debug_output: bool = False,
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    return _run_mesh_cloth_mc2_node(
        cache_state,
        proxy_obj,
        scene,
        enabled,
        reset,
        substeps,
        iterations,
        gravity_dir,
        gravity_power,
        damping,
        distance_stiffness,
        bend_stiffness,
        max_distance,
        collision_radius,
        backstop_radius,
        backstop_distance,
        collider_friction,
        debug_output,
    )
