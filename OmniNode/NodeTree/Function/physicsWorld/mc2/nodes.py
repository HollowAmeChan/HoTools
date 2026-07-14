"""Unified MC2 parameters, setup tasks, and simulation-step nodes."""

import typing

import mathutils

from ....FunctionNodeCore import omni
from ....OmniNodeSocketMapping import _OmniFloatCurve
from ... import _Color
from ..types import PhysicsWorldCache
from .names import (
    MC2_SETUP_BONE_CLOTH,
    MC2_SETUP_BONE_SPRING,
    MC2_SETUP_MESH_CLOTH,
)
from .solver import step_mc2
from .parameters import (
    make_mc2_particle_profile,
    make_mc2_setup_options,
    make_mc2_solver_settings,
)
from .specs import make_mc2_task_spec


def _task(setup_type: str, sources, profile, enabled: bool, **setup_values):
    if profile is None:
        profile = make_mc2_particle_profile()
    return [
        make_mc2_task_spec(
            setup_type,
            sources,
            profile=profile,
            setup_options=make_mc2_setup_options(setup_type, **setup_values),
            enabled=enabled,
        )
    ]


@omni(
    enable=True,
    bl_label="MC2粒子配置",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "混合权重", "重力", "重力强度", "重力衰减", "重置稳定时间", "法线轴",
        "动画姿态比例", "Anchor惯性", "World惯性", "惯性平滑", "World移动限速",
        "World旋转限速", "Local惯性", "Local移动限速", "Local旋转限速", "深度惯性",
        "离心力", "粒子限速", "Teleport模式", "Teleport距离", "Teleport旋转",
        "阻尼", "阻尼曲线", "粒子半径", "半径曲线",
        "Tether压缩", "距离刚度", "距离刚度曲线", "弯曲刚度",
        "角度恢复", "角度恢复刚度", "角度恢复曲线", "恢复速度衰减", "恢复重力衰减",
        "角度限制", "限制角度", "限制角度曲线", "限制刚度",
        "最大距离", "最大距离值", "最大距离曲线", "Backstop", "Backstop半径",
        "Backstop距离", "Backstop曲线", "Motion刚度", "碰撞模式", "碰撞摩擦",
        "BoneSpring碰撞限制", "碰撞限制曲线", "自碰撞模式", "自碰撞厚度", "自碰撞曲线", "布料质量",
        "Spring启用", "Spring强度", "Spring距离", "Spring法线限制", "Spring噪声",
        "风影响", "风频率", "风湍流", "风噪声混合", "风同步", "风深度权重", "移动风",
    ],
    input_init={
        "blend_weight": {"min_value": 0.0, "max_value": 1.0},
        "gravity": {"min_value": 0.0, "max_value": 20.0},
        "gravity_falloff": {"min_value": 0.0, "max_value": 1.0},
        "stabilization_time_after_reset": {"min_value": 0.0, "max_value": 1.0},
        "normal_axis": {"min_value": 0, "max_value": 5},
        "animation_pose_ratio": {"min_value": 0.0, "max_value": 1.0},
        "anchor_inertia": {"min_value": 0.0, "max_value": 1.0},
        "world_inertia": {"min_value": 0.0, "max_value": 1.0},
        "movement_inertia_smoothing": {"min_value": 0.0, "max_value": 1.0},
        "movement_speed_limit": {"min_value": -1.0, "max_value": 10.0},
        "rotation_speed_limit": {"min_value": -1.0, "max_value": 1440.0},
        "local_inertia": {"min_value": 0.0, "max_value": 1.0},
        "local_movement_speed_limit": {"min_value": -1.0, "max_value": 10.0},
        "local_rotation_speed_limit": {"min_value": -1.0, "max_value": 1440.0},
        "depth_inertia": {"min_value": 0.0, "max_value": 1.0},
        "centrifugal_acceleration": {"min_value": 0.0, "max_value": 1.0},
        "particle_speed_limit": {"min_value": -1.0, "max_value": 10.0},
        "teleport_mode": {"min_value": 0, "max_value": 2},
        "teleport_distance": {"min_value": 0.0},
        "teleport_rotation": {"min_value": 0.0},
        "damping": {"min_value": 0.0, "max_value": 1.0},
        "radius": {"min_value": 0.001, "max_value": 1.0},
        "tether_compression": {"min_value": 0.0, "max_value": 1.0},
        "distance_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "bending_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "angle_restoration_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "angle_restoration_velocity_attenuation": {"min_value": 0.0, "max_value": 1.0},
        "angle_restoration_gravity_falloff": {"min_value": 0.0, "max_value": 1.0},
        "angle_limit": {"min_value": 0.0, "max_value": 180.0},
        "angle_limit_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "max_distance": {"min_value": 0.0, "max_value": 5.0},
        "backstop_radius": {"min_value": 0.0, "max_value": 10.0},
        "backstop_distance": {"min_value": 0.0, "max_value": 1.0},
        "motion_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "collision_mode": {"min_value": 0, "max_value": 2},
        "collision_friction": {"min_value": 0.0, "max_value": 0.5},
        "collision_limit_distance": {"min_value": 0.0, "max_value": 1.0},
        "self_collision_mode": {"min_value": 0, "max_value": 2},
        "self_collision_thickness": {"min_value": 0.001, "max_value": 0.05},
        "cloth_mass": {"min_value": 0.0, "max_value": 1.0},
        "spring_power": {"min_value": 0.001, "max_value": 1.0},
        "spring_limit_distance": {"min_value": 0.0},
        "spring_normal_limit_ratio": {"min_value": 0.0, "max_value": 1.0},
        "spring_noise": {"min_value": 0.0, "max_value": 1.0},
        "wind_influence": {"min_value": 0.0, "max_value": 2.0},
        "wind_frequency": {"min_value": 0.0, "max_value": 2.0},
        "wind_turbulence": {"min_value": 0.0, "max_value": 2.0},
        "wind_blend": {"min_value": 0.0, "max_value": 1.0},
        "wind_synchronization": {"min_value": 0.0, "max_value": 1.0},
        "wind_depth_weight": {"min_value": 0.0, "max_value": 1.0},
        "moving_wind": {"min_value": 0.0, "max_value": 10.0},
    },
    _OUTPUT_NAME=["MC2粒子配置"],
    omni_description="三种 MC2 setup 共用的一套粒子/约束模型；setup 只在规范化时覆盖少量规则。",
)
def physicsMC2ParticleProfile(
    blend_weight: float = 1.0,
    gravity_direction: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity: float = 5.0,
    gravity_falloff: float = 0.0,
    stabilization_time_after_reset: float = 0.1,
    normal_axis: int = 1,
    animation_pose_ratio: float = 0.0,
    anchor_inertia: float = 0.0,
    world_inertia: float = 1.0,
    movement_inertia_smoothing: float = 0.4,
    movement_speed_limit: float = 5.0,
    rotation_speed_limit: float = 720.0,
    local_inertia: float = 1.0,
    local_movement_speed_limit: float = -1.0,
    local_rotation_speed_limit: float = -1.0,
    depth_inertia: float = 0.0,
    centrifugal_acceleration: float = 0.0,
    particle_speed_limit: float = 4.0,
    teleport_mode: int = 0,
    teleport_distance: float = 0.5,
    teleport_rotation: float = 90.0,
    damping: float = 0.05,
    damping_curve: _OmniFloatCurve = None,
    radius: float = 0.02,
    radius_curve: _OmniFloatCurve = None,
    tether_compression: float = 0.4,
    distance_stiffness: float = 1.0,
    distance_stiffness_curve: _OmniFloatCurve = None,
    bending_stiffness: float = 1.0,
    angle_restoration_enabled: bool = True,
    angle_restoration_stiffness: float = 0.2,
    angle_restoration_curve: _OmniFloatCurve = None,
    angle_restoration_velocity_attenuation: float = 0.8,
    angle_restoration_gravity_falloff: float = 0.0,
    angle_limit_enabled: bool = False,
    angle_limit: float = 60.0,
    angle_limit_curve: _OmniFloatCurve = None,
    angle_limit_stiffness: float = 1.0,
    max_distance_enabled: bool = False,
    max_distance: float = 0.3,
    max_distance_curve: _OmniFloatCurve = None,
    backstop_enabled: bool = False,
    backstop_radius: float = 10.0,
    backstop_distance: float = 0.0,
    backstop_distance_curve: _OmniFloatCurve = None,
    motion_stiffness: float = 1.0,
    collision_mode: int = 1,
    collision_friction: float = 0.05,
    collision_limit_distance: float = 0.05,
    collision_limit_curve: _OmniFloatCurve = None,
    self_collision_mode: int = 0,
    self_collision_thickness: float = 0.005,
    self_collision_curve: _OmniFloatCurve = None,
    cloth_mass: float = 0.0,
    spring_enabled: bool = True,
    spring_power: float = 0.04,
    spring_limit_distance: float = 0.1,
    spring_normal_limit_ratio: float = 1.0,
    spring_noise: float = 0.0,
    wind_influence: float = 1.0,
    wind_frequency: float = 1.0,
    wind_turbulence: float = 1.0,
    wind_blend: float = 0.7,
    wind_synchronization: float = 0.7,
    wind_depth_weight: float = 0.0,
    moving_wind: float = 0.0,
) -> typing.Any:
    return make_mc2_particle_profile(**locals())


@omni(
    enable=True,
    bl_label="MC2模拟设置",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "子步数", "迭代", "时间缩放", "模拟频率", "每帧最大模拟次数",
    ],
    input_init={
        "substeps": {"min_value": 1, "max_value": 16},
        "iterations": {"min_value": 0, "max_value": 64},
        "time_scale": {"min_value": 0.0, "max_value": 1.0},
        "simulation_frequency": {"min_value": 30, "max_value": 150},
        "max_simulation_count_per_frame": {"min_value": 1, "max_value": 5},
    },
    _OUTPUT_NAME=["MC2模拟设置"],
)
def physicsMC2SolverSettings(
    substeps: int = 1,
    iterations: int = 4,
    time_scale: float = 1.0,
    simulation_frequency: int = 90,
    max_simulation_count_per_frame: int = 3,
) -> typing.Any:
    return make_mc2_solver_settings(**locals())


@omni(
    enable=True,
    bl_label="MC2 MeshCloth任务（框架）",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["代理网格", "粒子配置", "启用"],
    _OUTPUT_NAME=["MC2任务"],
)
def physicsMC2MeshClothTask(
    sources: list[typing.Any],
    profile: typing.Any = None,
    enabled: bool = True,
) -> list[typing.Any]:
    return _task(MC2_SETUP_MESH_CLOTH, sources, profile, enabled)


@omni(
    enable=True,
    bl_label="MC2 BoneCloth任务（框架）",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["骨链", "粒子配置", "连接模式", "旋转插值", "根旋转", "启用"],
    input_init={
        "connection_mode": {"min_value": 0, "max_value": 2},
        "rotational_interpolation": {"min_value": 0.0, "max_value": 1.0},
        "root_rotation": {"min_value": 0.0, "max_value": 1.0},
    },
    _OUTPUT_NAME=["MC2任务"],
)
def physicsMC2BoneClothTask(
    sources: list[typing.Any],
    profile: typing.Any = None,
    connection_mode: int = 0,
    rotational_interpolation: float = 0.5,
    root_rotation: float = 0.5,
    enabled: bool = True,
) -> list[typing.Any]:
    return _task(
        MC2_SETUP_BONE_CLOTH,
        sources,
        profile,
        enabled,
        connection_mode=connection_mode,
        rotational_interpolation=rotational_interpolation,
        root_rotation=root_rotation,
    )


@omni(
    enable=True,
    bl_label="MC2 BoneSpring任务（框架）",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["骨链", "粒子配置", "旋转插值", "根旋转", "启用"],
    input_init={
        "rotational_interpolation": {"min_value": 0.0, "max_value": 1.0},
        "root_rotation": {"min_value": 0.0, "max_value": 1.0},
    },
    _OUTPUT_NAME=["MC2任务"],
)
def physicsMC2BoneSpringTask(
    sources: list[typing.Any],
    profile: typing.Any = None,
    rotational_interpolation: float = 0.5,
    root_rotation: float = 0.5,
    enabled: bool = True,
) -> list[typing.Any]:
    return _task(
        MC2_SETUP_BONE_SPRING,
        sources,
        profile,
        enabled,
        rotational_interpolation=rotational_interpolation,
        root_rotation=root_rotation,
    )


@omni(
    enable=True,
    bl_label="MC2模拟步（框架）",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "MC2任务", "模拟设置", "启用"],
    _OUTPUT_NAME=["物理世界", "就绪", "状态"],
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsMC2Step(
    world: PhysicsWorldCache,
    mc2_tasks: list[typing.Any],
    settings: typing.Any = None,
    enabled: bool = True,
) -> tuple[PhysicsWorldCache, bool, str]:
    return step_mc2(world, mc2_tasks, settings=settings, enabled=enabled)
