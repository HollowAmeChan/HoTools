"""MeshCloth MC2 OmniNode declarations."""

import typing

import bpy
import mathutils

from .....PropertyCurve import float_curve_payload
from ...FunctionNodeCore import omni
from ...OmniNodeSocketMapping import _OmniCache, _OmniFloatCurve
from .. import _Color
from .runtime.controller import run_mesh_cloth_mc2_node as _run_mesh_cloth_mc2_node
from .constants import MC2SystemConstants
from .presets import MC2_MESH_CLOTH_SETTING_PRESETS, MC2_MESH_CLOTH_SOLVER_PRESETS


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


def _mesh_objects_from_input(values) -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []
    stack = list(values) if isinstance(values, (list, tuple)) else [values]
    while stack:
        value = stack.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            stack[0:0] = list(value)
            continue
        if not isinstance(value, bpy.types.Object) or value.type != "MESH":
            raise ValueError(f"proxy_obj 必须是 MESH 类型的物体，得到：{value!r}")
        result.append(value)
    return result


@omni(
    enable=True,
    always_run=True,   # physics solver: advance/write every frame even when graph inputs are unchanged
    bl_label="网格布料-MC2",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "网格布料设置",
        "场景",
        "启用",
        "重置",
        "子步数",
        "迭代",
        "重力方向",
        "重力强度",
        "重力衰减",
        "重置后稳定时间",
        "Anchor物体",
        "Anchor惯性",
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
        "法线轴",
        "动画姿态比例",
        "碰撞启用",
        "碰撞摩擦",
        "碰撞模式",
        "时间缩放",
        "跳过写回",
        "调试输出",
    ],
    input_init={
        "mesh_cloth_settings": {"use_multi_input": True},
        "substeps": {"min_value": 1, "max_value": 16},
        "iterations": {"min_value": 0, "max_value": 64},
        "gravity_power": {"min_value": 0.0, "max_value": 100.0},
        "gravity_falloff": {"min_value": 0.0, "max_value": 1.0, "description": "MC2 重力衰减：根据初始重力方向与当前姿态夹角削弱重力。"},
        "stablization_time_after_reset": {"min_value": 0.0, "max_value": 1.0},
        "anchor_inertia": {"min_value": 0.0, "max_value": 1.0},
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
        "normal_axis": {"min_value": 0, "max_value": 5, "description": "0=+X 1=+Y 2=+Z 3=-X 4=-Y 5=-Z"},
        "animation_pose_ratio": {"min_value": 0.0, "max_value": 1.0},
        "collider_friction": {"min_value": 0.0, "max_value": 0.5},
        "collider_collision_mode": {"min_value": 0, "max_value": 2, "description": "0=关闭 1=点碰撞 2=边碰撞"},
        "time_scale": {"min_value": 0.0, "max_value": 1.0},
    },
    omni_presets=MC2_MESH_CLOTH_SOLVER_PRESETS,
    _OUTPUT_NAME=["缓存", "低模代理", "顶点数", "约束数"],
    omni_description="""
    MC2 网格布料解算器（模拟级参数）。

    物理参数（阻尼、刚度、角度约束等）由"网格布料设置-MC2"节点提供，
    通过"网格布料设置"输入传入。本节点只保留解算器级别参数：
    子步、重力、惯性、限速、Teleport、时间缩放。
    """,
    mute_passthrough={"_OUTPUT0": "cache_state"},
)
def meshClothMC2(
    cache_state: _OmniCache,
    mesh_cloth_settings: list[typing.Any] = None,
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    iterations: int = 4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 9.8,
    gravity_falloff: float = 0.0,
    stablization_time_after_reset: float = 0.1,
    anchor_obj: bpy.types.Object = None,
    anchor_inertia: float = MC2SystemConstants.ANCHOR_INERTIA,
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
    normal_axis: int = 1,
    animation_pose_ratio: float = 0.0,
    use_collider_collision: bool = True,
    collider_friction: float = 0.05,
    collider_collision_mode: int = 1,
    time_scale: float = 1.0,
    skip_writing: bool = False,
    debug_output: bool = False,
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    return _run_mesh_cloth_mc2_node(
        cache_state,
        mesh_cloth_settings,
        scene,
        enabled,
        reset,
        substeps,
        iterations,
        gravity_dir,
        gravity_power,
        gravity_falloff,
        stablization_time_after_reset,
        anchor_obj,
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
        teleport_mode,
        teleport_distance,
        teleport_rotation,
        normal_axis,
        animation_pose_ratio,
        use_collider_collision,
        collider_friction,
        collider_collision_mode,
        time_scale,
        skip_writing,
        debug_output,
    )


@omni(
    enable=True,
    bl_label="网格布料设置-MC2",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "低模代理",
        "启用",
        "混合权重",
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
        "碰撞半径",
        "最大距离启用",
        "最大距离",
        "最大距离曲线",
        "Backstop启用",
        "Backstop半径",
        "Backstop距离",
        "Backstop距离曲线",
        "Motion刚度",
    ],
    input_init={
        "blend_weight":     {"min_value": 0.0, "max_value": 1.0,   "description": "物理混合权重：0=完全BasePose，1=完全物理结果。"},
        "damping":          {"min_value": 0.0, "max_value": 1.0},
        "damping_curve":    {"default_value": _mc2_curve_multiplier(1.0)},
        "tether_compression":{"min_value": 0.0, "max_value": 1.0},
        "distance_stiffness":{"min_value": 0.0, "max_value": 1.0},
        "distance_stiffness_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "bend_stiffness":   {"min_value": 0.0, "max_value": 1.0},
        "bend_stiffness_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_restoration_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "angle_restoration_stiffness_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_restoration_velocity_attenuation": {"min_value": 0.0, "max_value": 1.0},
        "angle_restoration_velocity_attenuation_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_restoration_gravity_falloff": {"min_value": 0.0, "max_value": 1.0},
        "angle_limit":      {"min_value": 0.0, "max_value": 180.0},
        "angle_limit_curve":{"default_value": _mc2_curve_multiplier(1.0)},
        "angle_limit_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "collision_radius": {"min_value": 0.0},
        "max_distance":     {"min_value": 0.0},
        "max_distance_curve":{"default_value": _mc2_curve_multiplier(1.0)},
        "backstop_radius":  {"min_value": 0.0, "max_value": 10.0},
        "backstop_distance":{"min_value": 0.0},
        "backstop_distance_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "motion_stiffness": {"min_value": 0.0, "max_value": 1.0},
    },
    omni_presets=MC2_MESH_CLOTH_SETTING_PRESETS,
    _OUTPUT_NAME=["网格布料设置"],
    omni_description="""
    网格布料物理参数设置节点。

    携带一个或多个低模代理网格及该布料区域的完整物理参数，接入"网格布料-MC2"解算器。
    解算器节点不再直接拥有物理参数，所有物理参数均由本节点提供。
    输出列表格式，支持多个设置节点连接到同一解算器。
    """,
)
def meshClothMC2Setting(
    proxy_obj: list[bpy.types.Object],
    enabled: bool = True,
    blend_weight: float = 1.0,
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
    collision_radius: float = 0.0,
    use_max_distance: bool = False,
    max_distance: float = 0.0,
    max_distance_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    use_backstop: bool = False,
    backstop_radius: float = 0.0,
    backstop_distance: float = 0.0,
    backstop_distance_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    motion_stiffness: float = 1.0,
) -> list[typing.Any]:
    """把低模代理和物理参数打包成网格布料设置列表，供解算器读取。"""
    proxy_objects = _mesh_objects_from_input(proxy_obj)
    if not proxy_objects:
        raise ValueError("proxy_obj input is empty")

    settings = {
        "enabled":     bool(enabled),
        "blend_weight":                          float(blend_weight),
        "damping":                               float(damping),
        "damping_curve":                         damping_curve,
        "use_tether":                            bool(use_tether),
        "tether_compression":                    float(tether_compression),
        "use_distance":                          bool(use_distance),
        "distance_stiffness":                    float(distance_stiffness),
        "distance_stiffness_curve":              distance_stiffness_curve,
        "use_bend":                              bool(use_bend),
        "bend_stiffness":                        float(bend_stiffness),
        "bend_stiffness_curve":                  bend_stiffness_curve,
        "use_angle_restoration":                 bool(use_angle_restoration),
        "angle_restoration_stiffness":           float(angle_restoration_stiffness),
        "angle_restoration_stiffness_curve":     angle_restoration_stiffness_curve,
        "angle_restoration_velocity_attenuation": float(angle_restoration_velocity_attenuation),
        "angle_restoration_velocity_attenuation_curve": angle_restoration_velocity_attenuation_curve,
        "angle_restoration_gravity_falloff":     float(angle_restoration_gravity_falloff),
        "use_angle_limit":                       bool(use_angle_limit),
        "angle_limit":                           float(angle_limit),
        "angle_limit_curve":                     angle_limit_curve,
        "angle_limit_stiffness":                 float(angle_limit_stiffness),
        "collision_radius":                      float(collision_radius),
        "use_max_distance":                      bool(use_max_distance),
        "max_distance":                          float(max_distance),
        "max_distance_curve":                    max_distance_curve,
        "use_backstop":                          bool(use_backstop),
        "backstop_radius":                       float(backstop_radius),
        "backstop_distance":                     float(backstop_distance),
        "backstop_distance_curve":               backstop_distance_curve,
        "motion_stiffness":                      float(motion_stiffness),
    }
    return [
        {
            "proxy_obj": proxy,
            **settings,
        }
        for proxy in proxy_objects
    ]


_MESH_CLOTH_MC2_CPP_META = dict(meshClothMC2.__meta)
_MESH_CLOTH_MC2_CPP_META["bl_label"] = "网格布料-MC2-CPP"
_MESH_CLOTH_MC2_CPP_META["omni_description"] = """
    MC2 MeshCloth C++ full-core 后端节点。
    它与 meshClothMC2 共用 cache、碰撞收集、帧时间、teleport/inertia 准备和 GN delta 写回，
    但把每帧核心求解循环交给 hotools_native.solve_meshcloth_mc2。
    """


@omni(**_MESH_CLOTH_MC2_CPP_META)
def meshClothMC2Cpp(
    cache_state: _OmniCache,
    mesh_cloth_settings: list[typing.Any] = None,
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    iterations: int = 4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 9.8,
    gravity_falloff: float = 0.0,
    stablization_time_after_reset: float = 0.1,
    anchor_obj: bpy.types.Object = None,
    anchor_inertia: float = MC2SystemConstants.ANCHOR_INERTIA,
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
    normal_axis: int = 1,
    animation_pose_ratio: float = 0.0,
    use_collider_collision: bool = True,
    collider_friction: float = 0.05,
    collider_collision_mode: int = 1,
    time_scale: float = 1.0,
    skip_writing: bool = False,
    debug_output: bool = False,
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    # 签名与 meshClothMC2 完全一致，唯一区别是后端为 cpp。
    # 用 locals() 转发，避免未来参数新增时需要手动同步两处调用点。
    return _run_mesh_cloth_mc2_node(**dict(locals()), solver_backend="cpp")
