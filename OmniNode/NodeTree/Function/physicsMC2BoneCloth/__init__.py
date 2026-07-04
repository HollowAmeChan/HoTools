"""BoneCloth MC2 OmniNode declarations.

骨骼布料解算器：把多条骨链当作布料粒子求解，支持按 root 列表顺序自动生成横向约束，
解决链骨只有纵向约束、相邻链互相穿插飘散的痛点。

与网格布料-MC2 共用同一套 solver kernel（distance/angle/bend/tether/collision/inertia/motion/post），
只替换 I/O：输入 armature + 根骨骼列表，输出写回 PoseBone.matrix_basis。

连接模式：
  0 = 仅纵向    只连父子骨，无横向
  1 = 顺序连接  按根骨列表顺序连接相邻链（默认，披肩/刘海/尾巴）
  2 = 顺序成环  同上但首末链成环（裙摆/围脖）
"""

import bpy
import mathutils
import typing

from .....PropertyCurve import float_curve_payload
from ...FunctionNodeCore import omni
from ...OmniNodeSocketMapping import _OmniBone, _OmniCache, _OmniFloatCurve
from .. import _Color
from ..physicsMC2MeshCloth.constants import MC2SystemConstants
from . import bone_build as _bone_build
from .presets import BONE_CLOTH_PRESETS
from .runtime.controller import run_bone_cloth_mc2_node as _run_bone_cloth_mc2_node


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


@omni(
    enable=True,
    bl_label="骨骼布料-MC2链设置",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["根骨骼", "启用"],
    _OUTPUT_NAME=["骨链设置"],
    omni_description="""
    以根骨骼的每个直接子骨作为独立链的 root，采集所有平级骨链。

    适合"中控骨 + 多条平级骨串"结构（如裙摆 Skirt_0 下挂多条链）：
    传入中控骨，自动收集全部子骨链，返回链列表接入"骨骼布料-MC2"的多重输入。
    根骨骼（Root/中控骨）本身不参与物理，每条子链的根骨为固定锚点。
    """,
)
def boneClothMC2ChainSetting(
    root_bone: _OmniBone,
    enabled: bool = True,
) -> typing.Any:
    if not isinstance(root_bone, dict):
        raise ValueError("root_bone is invalid")
    armature_obj = root_bone.get("armature")
    bone_name = str(root_bone.get("bone") or "").strip()
    if (
        not isinstance(armature_obj, bpy.types.Object)
        or armature_obj.type != "ARMATURE"
        or not bone_name
    ):
        raise ValueError(f"root_bone is invalid: armature={armature_obj} bone={bone_name}")

    pose_bone = armature_obj.pose.bones.get(bone_name)
    if pose_bone is None:
        raise ValueError(f"骨骼未找到：{bone_name}")
    child_names = [c.name for c in (pose_bone.children or [])]
    if not child_names:
        raise ValueError(f"骨骼 {bone_name} 没有直接子骨，无法采集骨链")
    chains = _bone_build.collect_bone_chains(armature_obj, child_names)
    if not chains:
        raise ValueError(f"子骨链采集失败：{child_names}")
    return [
        {
            "armature": armature_obj,
            "root_bone": ch["root"],
            "bones": ch["bones"],
            "enabled": bool(enabled),
        }
        for ch in chains
    ]


@omni(
    enable=True,
    bl_label="骨骼布料-MC2",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "骨架",
        "骨链设置",
        "连接模式",
        "旋转插值",
        "场景",
        "启用",
        "重置",
        "子步数",
        "迭代",
        "重力方向",
        "重力强度",
        "重力衰减",
        "重置后稳定时间",
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
        "动画姿态比例",
        "最大距离启用",
        "最大距离",
        "最大距离曲线",
        "Backstop启用",
        "Backstop半径",
        "Backstop距离",
        "Backstop距离曲线",
        "Motion刚度",
        "法线轴",
        "碰撞启用",
        "碰撞摩擦",
        "碰撞模式",
        "时间缩放",
        "跳过写回",
        "调试输出",
    ],
    input_init={
        "connection_mode": {
            "min_value": 0,
            "max_value": 2,
            "description": "0仅纵向，1顺序连接相邻链（默认），2顺序成环。按根骨列表顺序连接，不做距离查找。",
        },
        "rotational_interpolation": {
            "min_value": 0.0,
            "max_value": 1.0,
            "description": "骨骼旋转跟随程度：0保持初始朝向，1完全跟随模拟方向。",
        },
        "substeps": {"min_value": 1, "max_value": 16, "description": "每帧子步数，越大越稳定但越贵。裙摆建议 2，不稳定时加到 4~8。"},
        "iterations": {"min_value": 0, "max_value": 64, "description": "每子步约束迭代次数，增大使布料更硬、碰撞更准确。"},
        "gravity_power": {"min_value": 0.0, "max_value": 100.0, "description": "重力强度（m/s²），预设会覆盖此值。"},
        "gravity_falloff": {"min_value": 0.0, "max_value": 1.0, "description": "按粒子朝向与重力夹角衰减重力：0 = 不衰减，1 = 垂直时重力为 0。"},
        "stablization_time_after_reset": {"min_value": 0.0, "max_value": 1.0, "description": "冷启动后速度权重爬升到 1 所需的秒数，防止初始帧抖动。"},
        "blend_weight": {"min_value": 0.0, "max_value": 1.0, "description": "物理混合权重：0 = 完全 BasePose，1 = 完全物理结果。"},
        "damping": {"min_value": 0.0, "max_value": 1.0, "description": "速度阻尼，控制振荡衰减速度，越大收敛越快但晃动感越少。"},
        "damping_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "tether_compression": {"min_value": 0.0, "max_value": 1.0, "description": "Tether 约束压缩限制：值越大越限制骨链向根骨方向压缩。"},
        "distance_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "distance_stiffness_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "bend_stiffness": {"min_value": 0.0, "max_value": 1.0, "description": "弯曲约束刚度。Line 模式无三角形时意义不大；Sequential 模式横向约束后才有效。"},
        "bend_stiffness_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_restoration_stiffness": {"min_value": 0.0, "max_value": 1.0, "description": "角度恢复刚度，控制骨骼弹回初始朝向的弹簧强度。"},
        "angle_restoration_stiffness_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_restoration_velocity_attenuation": {"min_value": 0.0, "max_value": 1.0, "description": "角度恢复时的速度衰减，防止恢复力过强导致振荡。"},
        "angle_restoration_velocity_attenuation_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_restoration_gravity_falloff": {"min_value": 0.0, "max_value": 1.0, "description": "重力方向上角度恢复衰减：0 = 各方向均匀，1 = 垂直重力方向不恢复。"},
        "angle_limit": {"min_value": 0.0, "max_value": 180.0, "description": "最大允许偏转角（度），超出时约束限制骨骼旋转，0 = 不限制。"},
        "angle_limit_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_limit_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "anchor_inertia": {"min_value": 0.0, "max_value": 1.0, "description": "Anchor 物体惯性影响：0 = 忽略 Anchor 运动，1 = 完全跟随。"},
        "world_inertia": {"min_value": 0.0, "max_value": 1.0, "description": "世界空间惯性：1 = 骨架移动时布料最大滞后效果，0 = 立即跟随。"},
        "movement_inertia_smoothing": {"min_value": 0.0, "max_value": 1.0, "description": "移动速度平滑系数，值越大惯性响应越顺滑越慢。"},
        "local_inertia": {"min_value": 0.0, "max_value": 1.0, "description": "局部惯性：响应骨架旋转运动，1 = 最大旋转惯性。"},
        "depth_inertia": {"min_value": 0.0, "max_value": 1.0, "description": "深度惯性：叶子骨惯性比根骨更大，0 = 各深度均匀，1 = 叶子骨惯性最大。"},
        "centrifugal": {"min_value": 0.0, "max_value": 1.0, "description": "离心力系数：旋转时向外张开，使裙摆旋转时展开。"},
        "movement_speed_limit": {"min_value": -1.0, "max_value": 10.0, "description": "世界空间移动限速（m/s），-1 = 不限制。限制可防止极端惯性时骨骼飞出。"},
        "rotation_speed_limit": {"min_value": -1.0, "max_value": 1440.0, "description": "世界空间旋转限速（°/s），-1 = 不限制。"},
        "local_movement_speed_limit": {"min_value": -1.0, "max_value": 10.0, "description": "局部空间移动限速（m/s），-1 = 不限制。"},
        "local_rotation_speed_limit": {"min_value": -1.0, "max_value": 1440.0, "description": "局部空间旋转限速（°/s），-1 = 不限制。"},
        "particle_speed_limit": {"min_value": -1.0, "max_value": 10.0, "description": "单粒子速度上限（m/s），防止粒子速度爆炸，-1 = 不限制。"},
        "teleport_mode": {
            "min_value": 0,
            "max_value": 2,
            "description": "0 = 不检测；1 = 重置（推荐，检测到瞬移时重置速度）；2 = 保持（保留位置但重设速度）。",
        },
        "teleport_distance": {"min_value": 0.0, "description": "触发 Teleport 的移动距离阈值（m）。"},
        "teleport_rotation": {"min_value": 0.0, "description": "触发 Teleport 的旋转角度阈值（°）。"},
        "animation_pose_ratio": {"min_value": 0.0, "max_value": 1.0, "description": "0 = 用初始姿态距离作为约束静止长度，1 = 每帧更新为当前动画姿态距离。"},
        "max_distance": {"min_value": 0.0, "description": "粒子距初始位置的最大位移（m），超出时被拉回，0 = 不限制。"},
        "max_distance_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "backstop_radius": {"min_value": 0.0, "max_value": 10.0, "description": "Backstop 胶囊体半径（m），防止布料穿入角色身体。"},
        "backstop_distance": {"min_value": 0.0, "description": "Backstop 从初始位置沿法线方向的偏移距离（m）。"},
        "backstop_distance_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "motion_stiffness": {"min_value": 0.0, "max_value": 1.0, "description": "Motion 约束弹簧强度，控制粒子被拉向 max_distance/backstop 边界的弹力。"},
        "normal_axis": {
            "min_value": 0,
            "max_value": 5,
            "description": "法线轴用于 Motion/Backstop 判断方向：0=+X 1=+Y（上，默认） 2=+Z 3=-X 4=-Y 5=-Z。",
        },
        "collider_friction": {"min_value": 0.0, "max_value": 0.5},
        "collider_collision_mode": {
            "min_value": 0,
            "max_value": 2,
            "description": "0 = 关闭；1 = 点碰撞（默认，每粒子做球/胶囊检测）；2 = 边碰撞（更精确但更贵）。",
        },
        "time_scale": {"min_value": 0.0, "max_value": 1.0, "description": "时间缩放（0~1）：0 = 暂停物理推进，1 = 正常速度。"},
    },
    _OUTPUT_NAME=["缓存", "骨架", "骨骼数", "约束数"],
    omni_presets=BONE_CLOTH_PRESETS,
    omni_description="""
    MC2 风格骨骼布料 Python 参考解算器。

    输入一个骨架和多条骨链的根骨骼（多重输入）。每根骨骼 head 作为一个布料粒子，
    root 骨作为固定锚点。solver 与网格布料-MC2 同源，只替换骨骼 I/O。

    横向约束按“根骨骼”列表顺序连接相邻链，不做空间距离查找：用户填入列表的顺序
    就是布料面的横向走向。骨骼名一般带顺时针/逆时针序号，直接按序填入即可。

    结果写回 PoseBone.matrix_basis，只改骨骼旋转不改位置，兼容 connected 骨。
    """,
)
def boneClothMC2(
    cache_state: _OmniCache,
    armature_obj: bpy.types.Object,
    bone_cloth_chains: list[typing.Any] = None,
    connection_mode: int = 1,
    rotational_interpolation: float = 1.0,
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    iterations: int = 4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 9.8,
    gravity_falloff: float = 0.0,
    stablization_time_after_reset: float = 0.1,
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
    animation_pose_ratio: float = 0.0,
    use_max_distance: bool = False,
    max_distance: float = 0.0,
    max_distance_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    use_backstop: bool = False,
    backstop_radius: float = 0.0,
    backstop_distance: float = 0.0,
    backstop_distance_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    motion_stiffness: float = 1.0,
    normal_axis: int = 1,
    use_collider_collision: bool = True,
    collider_friction: float = 0.05,
    collider_collision_mode: int = 1,
    time_scale: float = 1.0,
    skip_writing: bool = False,
    debug_output: bool = False,
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    return _run_bone_cloth_mc2_node(
        cache_state,
        armature_obj,
        bone_cloth_chains,
        connection_mode,
        rotational_interpolation,
        scene,
        enabled,
        reset,
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
        animation_pose_ratio,
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
        time_scale,
        skip_writing,
        debug_output,
    )


_BONE_CLOTH_MC2_CPP_META = dict(boneClothMC2.__meta)
_BONE_CLOTH_MC2_CPP_META["bl_label"] = "骨骼布料-MC2-CPP"
_BONE_CLOTH_MC2_CPP_META["omni_description"] = """
    骨骼布料-MC2 的 C++ 后端版本。

    与骨骼布料-MC2 共用骨链采集、拓扑构建、cache、BasePose 同步、inertia 准备和骨骼旋转写回，
    但把每帧核心求解循环交给 hotools_native.solve_meshcloth_mc2。
    节点输入输出与 Python 版完全一致，可随时切换对比效果和性能。
    """


@omni(**_BONE_CLOTH_MC2_CPP_META)
def boneClothMC2Cpp(
    cache_state: _OmniCache,
    armature_obj: bpy.types.Object,
    bone_cloth_chains: list[typing.Any] = None,
    connection_mode: int = 1,
    rotational_interpolation: float = 1.0,
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    iterations: int = 4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 9.8,
    gravity_falloff: float = 0.0,
    stablization_time_after_reset: float = 0.1,
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
    animation_pose_ratio: float = 0.0,
    use_max_distance: bool = False,
    max_distance: float = 0.0,
    max_distance_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    use_backstop: bool = False,
    backstop_radius: float = 0.0,
    backstop_distance: float = 0.0,
    backstop_distance_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    motion_stiffness: float = 1.0,
    normal_axis: int = 1,
    use_collider_collision: bool = True,
    collider_friction: float = 0.05,
    collider_collision_mode: int = 1,
    time_scale: float = 1.0,
    skip_writing: bool = False,
    debug_output: bool = False,
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    return _run_bone_cloth_mc2_node(
        cache_state,
        armature_obj,
        bone_cloth_chains,
        connection_mode,
        rotational_interpolation,
        scene,
        enabled,
        reset,
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
        animation_pose_ratio,
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
        time_scale,
        skip_writing,
        debug_output,
        solver_backend="cpp",
    )
