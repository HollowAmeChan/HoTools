"""MeshCloth MC2 的 OmniNode 节点入口。

这里只管理 Blender 节点生命周期：cache、跳帧、reset、碰撞快照收集和
shape key 写回。物理数组构建与求解分别由 state.py 和 solver.py 负责。
"""

import time

import bpy
import mathutils

from .....PropertyCurve import float_curve_payload
from ...FunctionNodeCore import omni
from ...OmniDebug import OmniDebug
from ...OmniNodeSocketMapping import _OmniCache, _OmniFloatCurve
from .. import _Color
from . import blender_io, collision, mesh_build, params, solver, state as mc2_state
from .constants import MC2SystemConstants


_DEBUG_PROFILES = {}


def _mc2_curve_multiplier(value: float = 1.0, interpolation: str = "LINEAR", extend: str = "CLAMP") -> dict:
    value = float(value)
    return float_curve_payload(
        [
            {"x": 0.0, "y": value, "interpolation": interpolation},
            {"x": 1.0, "y": value, "interpolation": interpolation},
        ],
        value=1.0,
        interpolation=interpolation,
        extend=extend,
    )


def _begin_timing() -> dict:
    return {"start": time.perf_counter(), "stages": {}}


def _add_timing(timing: dict | None, stage: str, seconds: float) -> None:
    if timing is None:
        return
    stages = timing.setdefault("stages", {})
    stages[stage] = stages.get(stage, 0.0) + max(float(seconds), 0.0)


def _format_debug_timing_report(
    backend: str,
    obj_name: str,
    shape_key_name: str,
    frame: int,
    vertex_count: int,
    constraint_count: int,
    elapsed: float,
    sample_count: int,
    totals: dict,
) -> list[str]:
    elapsed_ms = max(float(elapsed), 0.000001) * 1000.0
    hz = sample_count / max(float(elapsed), 0.000001)
    total_ms = totals.get("total", 0.0) / sample_count * 1000.0
    divider = OmniDebug.str_color("-" * 72, 90)
    title = (
        f"{OmniDebug.str_color('OMNI DEBUG TIMING', 97)}"
        f"  |  {OmniDebug.section_label('MC2')} "
        f"{OmniDebug.func_label(str(backend).upper())}"
    )

    lines = [
        "",
        divider,
        title,
        divider,
        f"  {OmniDebug.section_label('Summary')}: "
        f"interval={OmniDebug.value_label(f'{elapsed_ms:.1f}ms')}  "
        f"samples={OmniDebug.value_label(sample_count)}  "
        f"hz={OmniDebug.value_label(f'{hz:.2f}')}  "
        f"total={OmniDebug.func_label(f'{total_ms:.3f}ms')}",
        f"  {OmniDebug.section_label('Context')}: "
        f"obj={OmniDebug.node_label(obj_name)}  "
        f"key={OmniDebug.value_label(shape_key_name)}  "
        f"frame={OmniDebug.value_label(frame)}  "
        f"verts={OmniDebug.value_label(vertex_count)}  "
        f"constraints={OmniDebug.value_label(constraint_count)}",
    ]

    step_stages = [stage for stage in totals if stage != "total"]
    step_stages.sort(key=lambda stage: totals[stage], reverse=True)

    if step_stages:
        lines.append(f"  {OmniDebug.section_label('Slow Steps')}:")
        for index, stage in enumerate(step_stages, start=1):
            avg_ms = totals[stage] / sample_count * 1000.0
            lines.append(
                f"    {OmniDebug.value_label(f'{index:02d}.')} "
                f"{OmniDebug.func_label(stage)} = {OmniDebug.value_label(f'{avg_ms:.3f}ms')}"
            )

    return lines


def _publish_debug_timing(
    obj: bpy.types.Object,
    shape_key_name: str,
    frame: int,
    vertex_count: int,
    constraint_count: int,
    timing: dict | None,
    backend_label: str = "py",
) -> None:
    if timing is None:
        return

    _add_timing(timing, "total", time.perf_counter() - float(timing.get("start", time.perf_counter())))
    backend = str(backend_label or "py")
    key = (int(obj.as_pointer()), str(shape_key_name), f"mc2_{backend}")
    now = time.perf_counter()
    profile = _DEBUG_PROFILES.get(key)
    first_publish = profile is None
    if profile is None:
        profile = {
            "last_print": 0.0,
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

    if not first_publish and now - float(profile["last_print"]) < 1.0:
        return

    sample_count = max(int(profile["frames"]), 1)
    elapsed = (
        max(float(totals.get("total", 0.0)) / sample_count, 0.000001)
        if first_publish
        else max(now - float(profile["last_print"]), 0.000001)
    )
    print(
        "\n".join(
            _format_debug_timing_report(
                backend,
                obj.name_full,
                shape_key_name,
                int(profile["frame"]),
                int(profile["vertex_count"]),
                int(profile["constraint_count"]),
                elapsed,
                sample_count,
                totals,
            )
        )
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
    collision_radius: float,
    use_backstop: bool,
    backstop_radius: float,
    backstop_distance: float,
    backstop_distance_curve,
    motion_stiffness: float,
    use_collider_collision: bool,
    collider_friction: float,
    collider_collision_mode: int,
    debug_output: bool,
    solver_backend: str = "py",
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    backend_label = "cpp" if str(solver_backend).lower() in {"cpp", "native", "native_core"} else "py"
    timing = _begin_timing() if debug_output else None
    stage_start = time.perf_counter() if timing is not None else None
    obj = blender_io.require_mesh_object(proxy_obj, "proxy_obj")
    scene = scene or bpy.context.scene
    shape_key_name = blender_io.output_shape_key_name(obj)
    target_key = blender_io.ensure_target_shape_key(obj, shape_key_name)
    if timing is not None:
        _add_timing(timing, "validate", time.perf_counter() - stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    cache_substage_start = time.perf_counter() if timing is not None else None
    mesh_light_key = mesh_build.mesh_light_key(obj)
    if timing is not None:
        _add_timing(timing, "cache_light_key", time.perf_counter() - cache_substage_start)

    vertex_count = len(obj.data.vertices)
    cache_substage_start = time.perf_counter() if timing is not None else None
    state_matches = mc2_state.state_matches(cache_state, obj, shape_key_name, mesh_light_key)
    if timing is not None:
        _add_timing(timing, "cache_match", time.perf_counter() - cache_substage_start)
    state = cache_state if state_matches else None

    cache_substage_start = time.perf_counter() if timing is not None else None
    cached_frame = blender_io.cache_frame(state)
    current_frame = int(getattr(scene, "frame_current", 0) or 0)
    if timing is not None:
        _add_timing(timing, "cache_frame", time.perf_counter() - cache_substage_start)
        _add_timing(timing, "cache", time.perf_counter() - stage_start)

    if not reset and cached_frame is not None and current_frame != cached_frame + 1:
        stage_start = time.perf_counter() if timing is not None else None
        blender_io.restore_rest_to_shape_key(obj, target_key, state)
        if timing is not None:
            _add_timing(timing, "restore", time.perf_counter() - stage_start)
            _publish_debug_timing(obj, shape_key_name, current_frame, vertex_count, 0, timing, backend_label)
        return _OmniCache(None), obj, vertex_count, 0

    if reset or not isinstance(state, dict):
        stage_start = time.perf_counter() if timing is not None else None
        blender_io.restore_rest_to_shape_key(obj, target_key, state)
        if timing is not None:
            _add_timing(timing, "restore", time.perf_counter() - stage_start)

        # MC2 运行期优先复用缓存：连续帧只用轻量结构键判断。
        # 只有 reset、跳帧清缓存、对象/mesh/顶点-loop-面数量变化时才重建完整拓扑签名。
        # 同数量但拓扑重排不会自动失效，用户需要手动 reset/清缓存。
        cache_substage_start = time.perf_counter() if timing is not None else None
        mesh_signature_key = mesh_build.mesh_signature_key(obj)
        if timing is not None:
            _add_timing(timing, "cache_mesh_signature", time.perf_counter() - cache_substage_start)

        cache_substage_start = time.perf_counter() if timing is not None else None
        config_key = mesh_build.config_key(obj, shape_key_name, mesh_signature_key, collision_radius)
        if timing is not None:
            _add_timing(timing, "cache_config", time.perf_counter() - cache_substage_start)

        stage_start = time.perf_counter() if timing is not None else None
        state = mc2_state.build_state(
            obj,
            shape_key_name,
            mesh_light_key,
            mesh_signature_key,
            config_key,
            collision_radius,
        )
        if timing is not None:
            _add_timing(timing, "rebuild", time.perf_counter() - stage_start)
    else:
        stage_start = time.perf_counter() if timing is not None else None
        state = mc2_state.sync_state_to_object_transform(state, obj)
        if timing is not None:
            _add_timing(timing, "transform", time.perf_counter() - stage_start)

    dihedral_constraint_count = len(state.get("dihedral_pairs", ()))
    volume_constraint_count = len(state.get("volume_pairs", ()))
    if use_bend:
        bend_constraint_count = (
            dihedral_constraint_count + volume_constraint_count
            if dihedral_constraint_count > 0 or volume_constraint_count > 0
            else len(state["bend_distance_i"])
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
    constraint_count = (len(state["edge_i"]) if use_distance else 0) + bend_constraint_count + angle_constraint_count

    if not enabled:
        next_state = dict(state)
        next_state["frame"] = current_frame
        _publish_debug_timing(obj, shape_key_name, current_frame, vertex_count, constraint_count, timing, backend_label)
        return _OmniCache(next_state), obj, vertex_count, constraint_count

    stage_start = time.perf_counter() if timing is not None else None
    if use_collider_collision and int(collider_collision_mode) != 0:
        collision_snapshot = collision.build_collision_snapshot_from_scene(scene, True, True, False)
        colliders = list(collision_snapshot.get("colliders") or []) if isinstance(collision_snapshot, dict) else []
    else:
        colliders = []
    if timing is not None:
        _add_timing(timing, "colliders", time.perf_counter() - stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    solve_func = solver.solve_meshcloth_native_core if backend_label == "cpp" else solver.solve_meshcloth
    next_state = solve_func(
        state,
        obj,
        scene,
        substeps,
        iterations,
        gravity_dir,
        gravity_power,
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
        teleport_mode,
        teleport_distance,
        teleport_rotation,
        use_max_distance,
        max_distance,
        max_distance_curve,
        use_backstop,
        backstop_radius,
        backstop_distance,
        backstop_distance_curve,
        motion_stiffness,
        use_collider_collision,
        collider_friction,
        collider_collision_mode,
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
        _publish_debug_timing(obj, shape_key_name, current_frame, vertex_count, constraint_count, timing, backend_label)
    return _OmniCache(next_state), obj, vertex_count, constraint_count


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
        "阻尼曲线",
        "Tether启用",
        "Tether压缩",
        "距离启用",
        "距离刚度",
        "距离刚度曲线",
        "弯曲启用",
        "弯曲刚度",
        "弯曲刚度曲线",
        "角度恢复启用",
        "角度恢复",
        "角度恢复曲线",
        "角度恢复速度衰减",
        "角度恢复速度衰减曲线",
        "角度恢复重力衰减",
        "角度限制启用",
        "角度限制",
        "角度限制曲线",
        "角度限制刚度",
        "World惯性",
        "World惯性平滑",
        "Local惯性",
        "深度惯性",
        "离心力",
        "World移动限速",
        "World旋转限速",
        "Local移动限速",
        "Local旋转限速",
        "粒子限速",
        "Teleport模式",
        "Teleport距离",
        "Teleport旋转",
        "最大距离启用",
        "最大距离",
        "最大距离曲线",
        "碰撞半径",
        "Backstop启用",
        "Backstop半径",
        "Backstop距离",
        "Backstop距离曲线",
        "Motion刚度",
        "碰撞启用",
        "碰撞摩擦",
        "碰撞模式",
        "调试输出",
    ],
    input_init={
        "substeps": {"min_value": 1, "max_value": 16},
        "iterations": {"min_value": 0, "max_value": 64},
        "gravity_power": {"min_value": 0.0, "max_value": 100.0},
        "damping": {"min_value": 0.0, "max_value": 1.0},
        "damping_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "tether_compression": {"min_value": 0.0, "max_value": 1.0},
        "distance_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "distance_stiffness_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "bend_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "bend_stiffness_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_restoration_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "angle_restoration_stiffness_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_restoration_velocity_attenuation": {"min_value": 0.0, "max_value": 1.0},
        "angle_restoration_velocity_attenuation_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_restoration_gravity_falloff": {"min_value": 0.0, "max_value": 1.0},
        "angle_limit": {"min_value": 0.0, "max_value": 180.0},
        "angle_limit_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_limit_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "world_inertia": {"min_value": 0.0, "max_value": 1.0},
        "movement_inertia_smoothing": {"min_value": 0.0, "max_value": 1.0},
        "local_inertia": {"min_value": 0.0, "max_value": 1.0},
        "depth_inertia": {"min_value": 0.0, "max_value": 1.0},
        "centrifugal": {"min_value": 0.0, "max_value": 1.0},
        "movement_speed_limit": {"min_value": -1.0, "max_value": 10.0},
        "rotation_speed_limit": {"min_value": -1.0, "max_value": 1440.0},
        "local_movement_speed_limit": {"min_value": -1.0, "max_value": 10.0},
        "local_rotation_speed_limit": {"min_value": -1.0, "max_value": 1440.0},
        "particle_speed_limit": {"min_value": -1.0, "max_value": 10.0},
        "teleport_mode": {"min_value": 0, "max_value": 2},
        "teleport_distance": {"min_value": 0.0},
        "teleport_rotation": {"min_value": 0.0},
        "max_distance": {"min_value": 0.0},
        "max_distance_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "backstop_radius": {"min_value": 0.0, "max_value": 10.0},
        "backstop_distance": {"min_value": 0.0},
        "backstop_distance_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "motion_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "collision_radius": {"min_value": 0.0},
        "collider_friction": {"min_value": 0.0, "max_value": 0.5},
        "collider_collision_mode": {
            "min_value": 0,
            "max_value": 2,
            "description": "0关闭；1点碰撞；2边碰撞。球/胶囊/平面按MC2；Box为HoTools扩展。",
        },
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
    damping: float = 0.2,
    damping_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    use_tether: bool = True,
    tether_compression: float = MC2SystemConstants.TETHER_COMPRESSION_LIMIT,
    use_distance: bool = True,
    distance_stiffness: float = 1.0,
    distance_stiffness_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    use_bend: bool = True,
    bend_stiffness: float = 0.5,
    bend_stiffness_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    use_angle_restoration: bool = True,
    angle_restoration_stiffness: float = 0.2,
    angle_restoration_stiffness_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    angle_restoration_velocity_attenuation: float = MC2SystemConstants.ANGLE_RESTORATION_VELOCITY_ATTENUATION,
    angle_restoration_velocity_attenuation_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    angle_restoration_gravity_falloff: float = MC2SystemConstants.ANGLE_RESTORATION_GRAVITY_FALLOFF,
    use_angle_limit: bool = False,
    angle_limit: float = 0.0,
    angle_limit_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    angle_limit_stiffness: float = 1.0,
    world_inertia: float = MC2SystemConstants.WORLD_INERTIA,
    movement_inertia_smoothing: float = MC2SystemConstants.MOVEMENT_INERTIA_SMOOTHING,
    local_inertia: float = MC2SystemConstants.LOCAL_INERTIA,
    depth_inertia: float = MC2SystemConstants.DEPTH_INERTIA,
    centrifugal: float = MC2SystemConstants.CENTRIFUGAL_ACCELERATION,
    movement_speed_limit: float = MC2SystemConstants.MOVEMENT_SPEED_LIMIT,
    rotation_speed_limit: float = MC2SystemConstants.ROTATION_SPEED_LIMIT,
    local_movement_speed_limit: float = MC2SystemConstants.LOCAL_MOVEMENT_SPEED_LIMIT,
    local_rotation_speed_limit: float = MC2SystemConstants.LOCAL_ROTATION_SPEED_LIMIT,
    particle_speed_limit: float = MC2SystemConstants.PARTICLE_SPEED_LIMIT,
    teleport_mode: int = 0,
    teleport_distance: float = MC2SystemConstants.TELEPORT_DISTANCE,
    teleport_rotation: float = MC2SystemConstants.TELEPORT_ROTATION,
    use_max_distance: bool = False,
    max_distance: float = 0.0,
    max_distance_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    collision_radius: float = 0.0,
    use_backstop: bool = False,
    backstop_radius: float = 0.0,
    backstop_distance: float = 0.0,
    backstop_distance_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    motion_stiffness: float = 1.0,
    use_collider_collision: bool = True,
    collider_friction: float = 0.05,
    collider_collision_mode: int = 1,
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
        teleport_mode,
        teleport_distance,
        teleport_rotation,
        use_max_distance,
        max_distance,
        max_distance_curve,
        collision_radius,
        use_backstop,
        backstop_radius,
        backstop_distance,
        backstop_distance_curve,
        motion_stiffness,
        use_collider_collision,
        collider_friction,
        collider_collision_mode,
        debug_output,
    )


_MESH_CLOTH_MC2_CPP_META = dict(meshClothMC2.__meta)
_MESH_CLOTH_MC2_CPP_META["bl_label"] = "网格布料-MC2-CPP"
_MESH_CLOTH_MC2_CPP_META["omni_description"] = """
    MC2 MeshCloth C++ full-core backend node.
    It shares cache, collider collection, frame timing, teleport/inertia preparation, and shape key writeback with
    meshClothMC2, but delegates the per-frame solver loop to hotools_native.solve_meshcloth_mc2.
    """


@omni(**_MESH_CLOTH_MC2_CPP_META)
def meshClothMC2Cpp(
    cache_state: _OmniCache,
    proxy_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    iterations: int = 4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 9.8,
    damping: float = 0.2,
    damping_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    use_tether: bool = True,
    tether_compression: float = MC2SystemConstants.TETHER_COMPRESSION_LIMIT,
    use_distance: bool = True,
    distance_stiffness: float = 1.0,
    distance_stiffness_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    use_bend: bool = True,
    bend_stiffness: float = 0.5,
    bend_stiffness_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    use_angle_restoration: bool = True,
    angle_restoration_stiffness: float = 0.2,
    angle_restoration_stiffness_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    angle_restoration_velocity_attenuation: float = MC2SystemConstants.ANGLE_RESTORATION_VELOCITY_ATTENUATION,
    angle_restoration_velocity_attenuation_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    angle_restoration_gravity_falloff: float = MC2SystemConstants.ANGLE_RESTORATION_GRAVITY_FALLOFF,
    use_angle_limit: bool = False,
    angle_limit: float = 0.0,
    angle_limit_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    angle_limit_stiffness: float = 1.0,
    world_inertia: float = MC2SystemConstants.WORLD_INERTIA,
    movement_inertia_smoothing: float = MC2SystemConstants.MOVEMENT_INERTIA_SMOOTHING,
    local_inertia: float = MC2SystemConstants.LOCAL_INERTIA,
    depth_inertia: float = MC2SystemConstants.DEPTH_INERTIA,
    centrifugal: float = MC2SystemConstants.CENTRIFUGAL_ACCELERATION,
    movement_speed_limit: float = MC2SystemConstants.MOVEMENT_SPEED_LIMIT,
    rotation_speed_limit: float = MC2SystemConstants.ROTATION_SPEED_LIMIT,
    local_movement_speed_limit: float = MC2SystemConstants.LOCAL_MOVEMENT_SPEED_LIMIT,
    local_rotation_speed_limit: float = MC2SystemConstants.LOCAL_ROTATION_SPEED_LIMIT,
    particle_speed_limit: float = MC2SystemConstants.PARTICLE_SPEED_LIMIT,
    teleport_mode: int = 0,
    teleport_distance: float = MC2SystemConstants.TELEPORT_DISTANCE,
    teleport_rotation: float = MC2SystemConstants.TELEPORT_ROTATION,
    use_max_distance: bool = False,
    max_distance: float = 0.0,
    max_distance_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    collision_radius: float = 0.0,
    use_backstop: bool = False,
    backstop_radius: float = 0.0,
    backstop_distance: float = 0.0,
    backstop_distance_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    motion_stiffness: float = 1.0,
    use_collider_collision: bool = True,
    collider_friction: float = 0.05,
    collider_collision_mode: int = 1,
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
        teleport_mode,
        teleport_distance,
        teleport_rotation,
        use_max_distance,
        max_distance,
        max_distance_curve,
        collision_radius,
        use_backstop,
        backstop_radius,
        backstop_distance,
        backstop_distance_curve,
        motion_stiffness,
        use_collider_collision,
        collider_friction,
        collider_collision_mode,
        debug_output,
        solver_backend="cpp",
    )
