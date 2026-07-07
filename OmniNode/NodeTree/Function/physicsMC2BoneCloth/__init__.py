"""BoneCloth MC2 OmniNode declarations.

骨骼布料解算器：把多条骨链当作布料粒子求解，支持按 root 列表顺序自动生成横向约束，
解决链骨只有纵向约束、相邻链互相穿插飘散的痛点。

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# "根骨骼"输入的语义（使用者必读）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# 填入所有链的【共用父级骨骼】，而不是链头本身。
# 例如裙摆有15条链（Skirt_A_01 … Skirt_O_01），它们共同的父骨是 SkirtCtrl，
# 则根骨骼填 SkirtCtrl，节点自动采集其所有直接子骨作为各链起点。
#
# 骨骼角色说明：
#
#   SkirtCtrl（根骨骼输入）
#   │  不进入模拟，位置和旋转完全由动画驱动，物理无法修改。
#   │
#   ├── Skirt_A_01   ← 链首固定骨（depth=0）
#   │   │  位置被物理锁定到动画姿态（MC2_ATTR_FIXED），不会被推动。
#   │   │  旋转由物理写回——跟随下一节骨骼（Skirt_A_02）的模拟方向旋转，
#   │   │  而非一直指向动画原始方向。这样裙摆摆动时第一节可见骨也会转动。
#   │   ├── Skirt_A_02  ← 可动骨（depth=1）
#   │   │     位置和旋转均由物理完全驱动。
#   │   └── ...
#   │
#   ├── Skirt_B_01   ← 链首固定骨（depth=0）
#   │   └── ...
#   └── ...（共15条链，依此类推）
#
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

节点拓扑（对齐 VRM SpringBone per-chain 参数设计）：
  骨骼布料-物理属性-MC2  →  骨骼布料-MC2（解算器）
  │  接受根骨骼，采集子链，携带完整物理参数
  └─ 多个本节点输出可直接连入解算器多重输入，每组骨链独立调参

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
from .presets import BONE_CLOTH_CHAIN_PRESETS, BONE_CLOTH_SOLVER_PRESETS
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


def _bone_socket_values_from_input(values) -> list[tuple[bpy.types.Object, str]]:
    result: list[tuple[bpy.types.Object, str]] = []
    stack = list(values) if isinstance(values, (list, tuple)) else [values]
    while stack:
        value = stack.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            stack[0:0] = list(value)
            continue
        if not isinstance(value, dict):
            raise ValueError("root_bone is invalid")

        armature_obj = value.get("armature")
        bone_name = str(value.get("bone") or "").strip()
        if (
            not isinstance(armature_obj, bpy.types.Object)
            or armature_obj.type != "ARMATURE"
            or not bone_name
        ):
            raise ValueError(f"root_bone 无效：armature={armature_obj} bone={bone_name}")
        result.append((armature_obj, bone_name))
    return result


@omni(
    enable=True,
    bl_label="骨骼布料-物理属性-MC2",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "根骨骼",
        "启用",
        "旋转插值",
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
        "最大距离启用",
        "最大距离",
        "最大距离曲线",
        "Backstop启用",
        "Backstop半径",
        "Backstop距离",
        "Backstop距离曲线",
        "Motion刚度",
        "法线轴",
        "动画姿态比例",
        "碰撞启用",
        "碰撞摩擦",
        "碰撞模式",
    ],
    input_init={
        "rotational_interpolation": {"min_value": 0.0, "max_value": 1.0,
            "description": "骨骼旋转跟随程度：0保持初始朝向，1完全跟随模拟方向。"},
        "blend_weight":     {"min_value": 0.0, "max_value": 1.0,
            "description": "物理混合权重：0=完全BasePose，1=完全物理结果。"},
        "damping":          {"min_value": 0.0, "max_value": 1.0},
        "damping_curve":    {"default_value": _mc2_curve_multiplier(1.0)},
        "tether_compression": {"min_value": 0.0, "max_value": 1.0},
        "distance_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "distance_stiffness_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "bend_stiffness":   {"min_value": 0.0, "max_value": 1.0},
        "bend_stiffness_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_restoration_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "angle_restoration_stiffness_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_restoration_velocity_attenuation": {"min_value": 0.0, "max_value": 1.0},
        "angle_restoration_velocity_attenuation_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_restoration_gravity_falloff": {"min_value": 0.0, "max_value": 1.0},
        "angle_limit":      {"min_value": 0.0, "max_value": 180.0},
        "angle_limit_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "angle_limit_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "max_distance":     {"min_value": 0.0},
        "max_distance_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "backstop_radius":  {"min_value": 0.0, "max_value": 10.0},
        "backstop_distance": {"min_value": 0.0},
        "backstop_distance_curve": {"default_value": _mc2_curve_multiplier(1.0)},
        "motion_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "normal_axis":      {"min_value": 0, "max_value": 5,
            "description": "0=+X 1=+Y 2=+Z 3=-X 4=-Y 5=-Z"},
        "animation_pose_ratio": {"min_value": 0.0, "max_value": 1.0},
        "collider_friction": {"min_value": 0.0, "max_value": 0.5},
        "collider_collision_mode": {"min_value": 0, "max_value": 2,
            "description": "0=关闭 1=点碰撞 2=边碰撞"},
    },
    _OUTPUT_NAME=["骨链设置"],
    omni_presets=BONE_CLOTH_CHAIN_PRESETS,
    omni_description="""
    骨骼布料链设置 + 物理参数（合并节点，对齐 VRM SpringBone per-chain 参数设计）。

    传入一个或多个"中控骨/父骨"，自动采集其所有直接子链；同时携带该组骨链的完整物理参数。
    不同骨链组（头发/裙摆/尾巴）各接一个本节点，实现独立调参。

    骨骼布料-MC2 解算器不再有物理参数输入，所有物理参数均由本节点提供。
    """,
)
def boneClothMC2ChainPhysics(
    root_bone: list[_OmniBone],
    enabled: bool = True,
    rotational_interpolation: float = 1.0,
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
    use_max_distance: bool = False,
    max_distance: float = 0.0,
    max_distance_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    use_backstop: bool = False,
    backstop_radius: float = 0.0,
    backstop_distance: float = 0.0,
    backstop_distance_curve: _OmniFloatCurve = _mc2_curve_multiplier(1.0),
    motion_stiffness: float = 1.0,
    normal_axis: int = 1,
    animation_pose_ratio: float = 0.0,
    use_collider_collision: bool = True,
    collider_friction: float = 0.05,
    collider_collision_mode: int = 1,
) -> list[typing.Any]:
    """采集骨链并附加完整 per-chain 物理参数，输出供解算器消费的链设置列表。"""
    root_values = _bone_socket_values_from_input(root_bone)
    if not root_values:
        raise ValueError("root_bone input is empty")

    collected_chains: list[tuple[bpy.types.Object, dict]] = []
    for armature_obj, bone_name in root_values:
        pose_bone = armature_obj.pose.bones.get(bone_name)
        if pose_bone is None:
            raise ValueError(f"骨骼未找到：{bone_name}")
        child_names = [c.name for c in (pose_bone.children or [])]
        if not child_names:
            raise ValueError(f"骨骼 {bone_name} 没有直接子骨，无法采集骨链")
        chains = _bone_build.collect_bone_chains(armature_obj, child_names)
        if not chains:
            raise ValueError(f"子骨链采集失败：{child_names}")
        collected_chains.extend((armature_obj, chain) for chain in chains)

    physics = {
        "rotational_interpolation":                      float(rotational_interpolation),
        "blend_weight":                                  float(blend_weight),
        "damping":                                       float(damping),
        "damping_curve":                                 damping_curve,
        "use_tether":                                    bool(use_tether),
        "tether_compression":                            float(tether_compression),
        "use_distance":                                  bool(use_distance),
        "distance_stiffness":                            float(distance_stiffness),
        "distance_stiffness_curve":                      distance_stiffness_curve,
        "use_bend":                                      bool(use_bend),
        "bend_stiffness":                                float(bend_stiffness),
        "bend_stiffness_curve":                          bend_stiffness_curve,
        "use_angle_restoration":                         bool(use_angle_restoration),
        "angle_restoration_stiffness":                   float(angle_restoration_stiffness),
        "angle_restoration_stiffness_curve":             angle_restoration_stiffness_curve,
        "angle_restoration_velocity_attenuation":        float(angle_restoration_velocity_attenuation),
        "angle_restoration_velocity_attenuation_curve":  angle_restoration_velocity_attenuation_curve,
        "angle_restoration_gravity_falloff":             float(angle_restoration_gravity_falloff),
        "use_angle_limit":                               bool(use_angle_limit),
        "angle_limit":                                   float(angle_limit),
        "angle_limit_curve":                             angle_limit_curve,
        "angle_limit_stiffness":                         float(angle_limit_stiffness),
        "use_max_distance":                              bool(use_max_distance),
        "max_distance":                                  float(max_distance),
        "max_distance_curve":                            max_distance_curve,
        "use_backstop":                                  bool(use_backstop),
        "backstop_radius":                               float(backstop_radius),
        "backstop_distance":                             float(backstop_distance),
        "backstop_distance_curve":                       backstop_distance_curve,
        "motion_stiffness":                              float(motion_stiffness),
        "normal_axis":                                   int(normal_axis),
        "animation_pose_ratio":                          float(animation_pose_ratio),
        "use_collider_collision":                        bool(use_collider_collision),
        "collider_friction":                             float(collider_friction),
        "collider_collision_mode":                       int(collider_collision_mode),
    }

    return [
        {
            "armature": armature_obj,
            "root_bone": ch["root"],
            "bones":     ch["bones"],
            "enabled":   bool(enabled),
            "params":    physics,
            # 同一节点调用产出的所有链共享同一横向组 ID（physics 对象地址），
            # 解算器据此判断哪些链之间允许建横向连接，防止跨节点调用的链产生伪横向边。
            "lateral_group": id(physics),
        }
        for armature_obj, ch in collected_chains
    ]


@omni(
    enable=True,
    always_run=True,   # 物理解算器，每帧推进状态
    bl_label="骨骼布料-MC2",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存", "骨链设置", "连接模式", "场景", "启用", "重置",
        "子步数", "迭代", "重力方向", "重力强度", "重力衰减",
        "重置后稳定时间", "Anchor物体", "Anchor惯性",
        "World惯性", "World惯性平滑", "Local惯性", "深度惯性", "离心力",
        "World移动限速", "World旋转限速", "Local移动限速", "Local旋转限速", "粒子限速",
        "Teleport模式", "Teleport距离", "Teleport旋转",
        "时间缩放", "跳过写回", "调试输出", "自碰撞",
    ],
    input_init={
        "connection_mode": {"min_value": 0, "max_value": 2,
            "description": "0仅纵向，1顺序连接相邻链（默认），2顺序成环。"},
        "substeps":   {"min_value": 1, "max_value": 16},
        "iterations": {"min_value": 0, "max_value": 64},
        "gravity_power":   {"min_value": 0.0, "max_value": 100.0},
        "gravity_falloff": {"min_value": 0.0, "max_value": 1.0,
            "description": "按粒子朝向与重力夹角衰减重力：0=不衰减，1=垂直时重力为0。"},
        "stablization_time_after_reset": {"min_value": 0.0, "max_value": 1.0},
        "anchor_inertia": {"min_value": 0.0, "max_value": 1.0},
        "world_inertia":  {"min_value": 0.0, "max_value": 1.0},
        "movement_inertia_smoothing": {"min_value": 0.0, "max_value": 1.0},
        "local_inertia":  {"min_value": 0.0, "max_value": 1.0},
        "depth_inertia":  {"min_value": 0.0, "max_value": 1.0},
        "centrifugal":    {"min_value": 0.0, "max_value": 1.0},
        "movement_speed_limit":       {"min_value": -1.0, "max_value": 10.0},
        "rotation_speed_limit":       {"min_value": -1.0, "max_value": 1440.0},
        "local_movement_speed_limit": {"min_value": -1.0, "max_value": 10.0},
        "local_rotation_speed_limit": {"min_value": -1.0, "max_value": 1440.0},
        "particle_speed_limit":       {"min_value": -1.0, "max_value": 10.0},
        "teleport_mode":     {"min_value": 0, "max_value": 2},
        "teleport_distance": {"min_value": 0.0},
        "teleport_rotation": {"min_value": 0.0},
        "time_scale": {"min_value": 0.0, "max_value": 1.0},
        "use_self_collision": {
            "description": "开启后，同一个骨骼布料节点参与解算的多个骨架会互相作为骨骼碰撞体。",
        },
    },
    omni_presets=BONE_CLOTH_SOLVER_PRESETS,
    _OUTPUT_NAME=["缓存", "骨架列表", "骨骼数", "约束数"],
    omni_description="""
    MC2 骨骼布料解算器（模拟级参数），支持多骨架批量解算。

    物理参数（阻尼、刚度、角度约束等）由"骨骼布料-物理属性-MC2"节点提供，
    通过"骨链设置"多重输入传入。不同骨链组可各接一个物理参数节点实现独立调参。
    来自不同骨架的骨链设置可直接一起接入，节点自动按骨架分组独立解算。
    横向约束（连接模式）在同一骨架的骨链之间生效，跨骨架的骨链无横向连接。
    本节点只保留解算器级别参数：子步、重力、惯性、限速、Teleport、时间缩放、自碰撞。
    """,
    mute_passthrough={"_OUTPUT0": "cache_state"},
)
def boneClothMC2(
    cache_state: _OmniCache,
    bone_cloth_chains: list[typing.Any] = None,
    connection_mode: int = 1,
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
    time_scale: float = 1.0,
    skip_writing: bool = False,
    debug_output: bool = False,
    use_self_collision: bool = False,
) -> tuple[_OmniCache, list[bpy.types.Object], int, int]:
    return _run_bone_cloth_mc2_node(
        cache_state, bone_cloth_chains, connection_mode, scene,
        enabled, reset, substeps, iterations,
        gravity_dir, gravity_power, gravity_falloff, stablization_time_after_reset,
        anchor_obj, anchor_inertia, world_inertia, movement_inertia_smoothing,
        local_inertia, depth_inertia, centrifugal,
        movement_speed_limit, rotation_speed_limit,
        local_movement_speed_limit, local_rotation_speed_limit, particle_speed_limit,
        teleport_mode, teleport_distance, teleport_rotation,
        time_scale, skip_writing, debug_output, use_self_collision,
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
    bone_cloth_chains: list[typing.Any] = None,
    connection_mode: int = 1,
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
    time_scale: float = 1.0,
    skip_writing: bool = False,
    debug_output: bool = False,
    use_self_collision: bool = False,
) -> tuple[_OmniCache, list[bpy.types.Object], int, int]:
    return _run_bone_cloth_mc2_node(
        cache_state, bone_cloth_chains, connection_mode, scene,
        enabled, reset, substeps, iterations,
        gravity_dir, gravity_power, gravity_falloff, stablization_time_after_reset,
        anchor_obj, anchor_inertia, world_inertia, movement_inertia_smoothing,
        local_inertia, depth_inertia, centrifugal,
        movement_speed_limit, rotation_speed_limit,
        local_movement_speed_limit, local_rotation_speed_limit, particle_speed_limit,
        teleport_mode, teleport_distance, teleport_rotation,
        time_scale, skip_writing, debug_output, use_self_collision,
        solver_backend="cpp",
    )
