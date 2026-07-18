"""Unified MC2 parameters, setup tasks, and simulation-step nodes."""

import typing

import bpy
import mathutils

from ....FunctionNodeCore import omni
from ....OmniNodeSocketMapping import _OmniBitMask, _OmniBone, _OmniFloatCurve
from ... import _Color
from ..types import PhysicsWorldCache
from .debug_draw import update_mc2_debug_draw_store
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
from .presets import MC2_PARTICLE_PRESETS
from .specs import make_mc2_task_spec


def _task_name_output(tasks) -> str:
    return "\n".join(str(task.task_id) for task in tasks)


def _mesh_cloth_tasks(mesh_objects, profile, enabled: bool):
    if profile is None:
        profile = make_mc2_particle_profile(spring_enabled=False)
    sources = _flatten_values(mesh_objects)
    for source in sources:
        if getattr(source, "type", None) != "MESH":
            raise TypeError("MeshCloth product source must be a Mesh Object socket")
    return [
        make_mc2_task_spec(
            MC2_SETUP_MESH_CLOTH,
            [source],
            profile=profile,
            setup_options=make_mc2_setup_options(
                MC2_SETUP_MESH_CLOTH,
                self_collision_radius_model="derived_radius",
            ),
            enabled=enabled,
        )
        for source in sources
    ]


def _flatten_values(values) -> list:
    pending = list(values) if isinstance(values, list) else [values]
    result = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, list):
            pending[0:0] = value
            continue
        result.append(value)
    return result


def _bone_chain_names(root_bone) -> list[str]:
    names = []
    current = root_bone
    guard = 0
    while current is not None and guard < 4096:
        names.append(str(getattr(current, "name", "") or ""))
        children = list(getattr(current, "children", ()) or ())
        current = children[0] if children else None
        guard += 1
    return [name for name in names if name]


def _expand_hotools_bone_source(value) -> list[dict]:
    chains = []
    if isinstance(value, dict) and value.get("armature") is not None:
        armature = value.get("armature")
        explicit = [str(name) for name in (value.get("bones") or ()) if str(name)]
        if explicit:
            return [{
                "armature": armature,
                "root_bone": str(value.get("root_bone") or explicit[0]),
                "bones": explicit,
            }]
        parent_name = str(value.get("bone") or value.get("root_bone") or "").strip()
    elif isinstance(value, tuple) and len(value) == 2:
        armature, parent_name = value
        parent_name = str(parent_name or "").strip()
    else:
        raise TypeError("BoneCloth product source must be a Bone socket or explicit chain")

    pose_bones = getattr(getattr(armature, "pose", None), "bones", None)
    parent = pose_bones.get(parent_name) if pose_bones is not None else None
    if parent is None:
        raise ValueError(f"BoneCloth parent bone not found: {parent_name!r}")
    children = list(getattr(parent, "children", ()) or ())
    if not children:
        raise ValueError(f"BoneCloth parent bone has no child chains: {parent_name!r}")
    for child in children:
        names = _bone_chain_names(child)
        if names:
            chains.append({
                "armature": armature,
                "root_bone": names[0],
                "bones": names,
            })
    return chains


def _owner_key(source: dict) -> tuple[int, int]:
    armature = source["armature"]
    pointer = getattr(armature, "as_pointer", None)
    data = getattr(armature, "data", None)
    data_pointer = getattr(data, "as_pointer", None)
    owner_id = int(pointer()) if callable(pointer) else id(armature)
    data_id = int(data_pointer()) if callable(data_pointer) else id(data)
    return owner_id, data_id


def _hotools_bone_tasks(control_bones, profile, enabled: bool, **setup_values):
    if profile is None:
        profile = make_mc2_particle_profile(spring_enabled=False)
    groups: list[list[dict]] = []
    explicit_group_indices: dict[tuple[int, int], int] = {}
    for value in _flatten_values(control_bones):
        sources = _expand_hotools_bone_source(value)
        is_explicit_chain = isinstance(value, dict) and bool(value.get("bones"))
        if not is_explicit_chain:
            groups.append(sources)
            continue
        owner_key = _owner_key(sources[0])
        group_index = explicit_group_indices.get(owner_key)
        if group_index is None:
            explicit_group_indices[owner_key] = len(groups)
            groups.append(list(sources))
        else:
            groups[group_index].extend(sources)
    return [
        make_mc2_task_spec(
            MC2_SETUP_BONE_CLOTH,
            group,
            profile=profile,
            setup_options=make_mc2_setup_options(
                MC2_SETUP_BONE_CLOTH,
                connection_model="hotools_product",
                **setup_values,
            ),
            enabled=enabled,
        )
        for group in groups
    ]


def _bone_spring_tasks(root_bones, profile, enabled: bool, **setup_values):
    if profile is None:
        profile = make_mc2_particle_profile(spring_enabled=False)
    grouped: dict[tuple[int, int], list[dict]] = {}
    for source in _flatten_values(root_bones):
        if not isinstance(source, dict) or source.get("armature") is None:
            raise TypeError("BoneSpring product source must be a root Bone socket")
        root_name = str(source.get("bone") or source.get("root_bone") or "").strip()
        if not root_name and not source.get("bones"):
            raise ValueError("BoneSpring root Bone socket is empty")
        grouped.setdefault(_owner_key(source), []).append(source)
    return [
        make_mc2_task_spec(
            MC2_SETUP_BONE_SPRING,
            group,
            profile=profile,
            setup_options=make_mc2_setup_options(
                MC2_SETUP_BONE_SPRING,
                **setup_values,
            ),
            enabled=enabled,
        )
        for group in grouped.values()
    ]


def _profile_input(description: str, **settings) -> dict:
    return {"description": description, **settings}


_PROFILE_LABELS = {
    "blend_weight": "混合权重", "gravity_direction": "重力方向", "gravity": "重力强度",
    "gravity_falloff": "重力衰减", "stabilization_time_after_reset": "重置稳定时间",
    "normal_axis": "法线轴", "animation_pose_ratio": "动画姿态比例",
    "anchor_inertia": "Anchor惯性", "world_inertia": "World惯性",
    "movement_inertia_smoothing": "惯性平滑", "movement_speed_limit": "World移动限速",
    "rotation_speed_limit": "World旋转限速", "local_inertia": "Local惯性",
    "local_movement_speed_limit": "Local移动限速", "local_rotation_speed_limit": "Local旋转限速",
    "depth_inertia": "深度惯性", "centrifugal_acceleration": "离心力",
    "particle_speed_limit": "粒子限速", "teleport_mode": "Teleport模式",
    "teleport_distance": "Teleport距离", "teleport_rotation": "Teleport旋转",
    "damping": "阻尼", "damping_curve": "阻尼曲线", "radius": "粒子半径",
    "radius_curve": "半径曲线", "tether_compression": "Tether压缩",
    "distance_stiffness": "距离刚度", "distance_stiffness_curve": "距离刚度曲线",
    "bending_stiffness": "弯曲刚度", "angle_restoration_enabled": "角度恢复",
    "angle_restoration_stiffness": "角度恢复刚度", "angle_restoration_curve": "角度恢复曲线",
    "angle_restoration_velocity_attenuation": "恢复速度衰减",
    "angle_restoration_gravity_falloff": "恢复重力衰减", "angle_limit_enabled": "角度限制",
    "angle_limit": "限制角度", "angle_limit_curve": "限制角度曲线",
    "angle_limit_stiffness": "限制刚度", "max_distance_enabled": "最大距离",
    "max_distance": "最大距离值", "max_distance_curve": "最大距离曲线",
    "backstop_enabled": "Backstop", "backstop_radius": "Backstop半径",
    "backstop_distance": "Backstop距离", "backstop_distance_curve": "Backstop曲线",
    "motion_stiffness": "Motion刚度", "collision_mode": "碰撞模式",
    "collision_friction": "碰撞摩擦", "collision_limit_distance": "碰撞限制距离",
    "collision_limit_curve": "碰撞限制曲线", "self_collision_enabled": "自碰撞",
    "self_collision_interaction": "跨物体自碰撞", "cloth_mass": "布料质量",
}

_PROFILE_INPUT_INIT = {
    "blend_weight": _profile_input("物理混合\n0:动画  1:完整物理", min_value=0.0, max_value=1.0),
    "gravity_direction": _profile_input("世界空间重力方向；仅MeshCloth/BoneCloth消费。"),
    "gravity": _profile_input("重力加速度强度；BoneSpring强制为0。", min_value=0.0, max_value=20.0),
    "gravity_falloff": _profile_input("沿粒子深度衰减重力的比例。", min_value=0.0, max_value=1.0),
    "stabilization_time_after_reset": _profile_input("Reset或Teleport后的稳定时间。\n单位：秒", min_value=0.0, max_value=1.0),
    "normal_axis": _profile_input("粒子局部法线轴。\n0:+X  1:+Y  2:+Z\n3:-X  4:-Y  5:-Z", min_value=0, max_value=5),
    "animation_pose_ratio": _profile_input("约束参考姿态中动画姿态所占比例。", min_value=0.0, max_value=1.0),
    "anchor_inertia": _profile_input("Anchor坐标变化保留到粒子运动中的比例。", min_value=0.0, max_value=1.0),
    "world_inertia": _profile_input("世界空间移动/旋转惯性比例。", min_value=0.0, max_value=1.0),
    "movement_inertia_smoothing": _profile_input("世界移动惯性的平滑比例。", min_value=0.0, max_value=1.0),
    "movement_speed_limit": _profile_input("世界移动速度上限；负值禁用。", min_value=-1.0, max_value=10.0),
    "rotation_speed_limit": _profile_input("世界旋转速度上限（度/秒）；负值禁用。", min_value=-1.0, max_value=1440.0),
    "local_inertia": _profile_input("局部空间移动/旋转惯性比例。", min_value=0.0, max_value=1.0),
    "local_movement_speed_limit": _profile_input("局部移动速度上限；负值禁用。", min_value=-1.0, max_value=10.0),
    "local_rotation_speed_limit": _profile_input("局部旋转速度上限（度/秒）；负值禁用。", min_value=-1.0, max_value=1440.0),
    "depth_inertia": _profile_input("按粒子深度增加的惯性比例。", min_value=0.0, max_value=1.0),
    "centrifugal_acceleration": _profile_input("由组件旋转产生的离心加速度比例。", min_value=0.0, max_value=1.0),
    "particle_speed_limit": _profile_input("粒子速度上限；负值禁用。", min_value=-1.0, max_value=10.0),
    "teleport_mode": _profile_input("Teleport处理模式。\n0:None  1:Reset  2:Keep", min_value=0, max_value=2),
    "teleport_distance": _profile_input("触发Teleport判定的组件位移阈值。", min_value=0.0),
    "teleport_rotation": _profile_input("触发Teleport判定的组件旋转阈值（度）。", min_value=0.0),
    "damping": _profile_input("粒子速度阻尼基础值。", min_value=0.0, max_value=1.0),
    "damping_curve": _profile_input("按粒子深度乘到阻尼基础值上的曲线。"),
    "radius": _profile_input("粒子碰撞半径基础值。", min_value=0.001, max_value=1.0),
    "radius_curve": _profile_input("按粒子深度乘到半径基础值上的曲线。"),
    "tether_compression": _profile_input("Tether允许压缩的比例。\nBoneSpring使用固定值。", min_value=0.0, max_value=1.0),
    "distance_stiffness": _profile_input("相邻粒子距离刚度\nBoneSpring固定", min_value=0.0, max_value=1.0),
    "distance_stiffness_curve": _profile_input("按粒子深度乘到距离刚度上的曲线。"),
    "bending_stiffness": _profile_input("三角/链弯曲约束刚度；0关闭。", min_value=0.0, max_value=1.0),
    "angle_restoration_enabled": _profile_input("启用粒子角度恢复约束。"),
    "angle_restoration_stiffness": _profile_input("角度恢复刚度基础值。", min_value=0.0, max_value=1.0),
    "angle_restoration_curve": _profile_input("按粒子深度乘到角度恢复刚度上的曲线。"),
    "angle_restoration_velocity_attenuation": _profile_input("角度恢复时保留速度的比例。", min_value=0.0, max_value=1.0),
    "angle_restoration_gravity_falloff": _profile_input("角度恢复受重力影响的衰减比例。", min_value=0.0, max_value=1.0),
    "angle_limit_enabled": _profile_input("启用相邻粒子的最大弯折角限制。"),
    "angle_limit": _profile_input("允许的最大弯折角（度）。", min_value=0.0, max_value=180.0),
    "angle_limit_curve": _profile_input("按粒子深度乘到限制角度上的曲线。"),
    "angle_limit_stiffness": _profile_input("超过限制角度后的修正刚度。", min_value=0.0, max_value=1.0),
    "max_distance_enabled": _profile_input("最大移动距离开关\nBoneSpring关闭"),
    "max_distance": _profile_input("粒子相对动画姿态允许移动的最大距离。", min_value=0.0, max_value=5.0),
    "max_distance_curve": _profile_input("按粒子深度乘到最大距离上的曲线。"),
    "backstop_enabled": _profile_input("Backstop开关\nBoneSpring关闭"),
    "backstop_radius": _profile_input("Backstop球半径。", min_value=0.0, max_value=10.0),
    "backstop_distance": _profile_input("Backstop球心相对动画姿态的法线距离。", min_value=0.0, max_value=1.0),
    "backstop_distance_curve": _profile_input("按粒子深度乘到Backstop距离上的曲线。"),
    "motion_stiffness": _profile_input("Motion/动画姿态限制的修正刚度。", min_value=0.0, max_value=1.0),
    "collision_mode": _profile_input("碰撞：0:None / 1:Point / 2:Edge\nEdge使用final proxy边。\nBoneSpring固定Point。", min_value=0, max_value=2),
    "collision_friction": _profile_input("外部碰撞摩擦系数。\nBoneSpring使用固定值。", min_value=0.0, max_value=0.5),
    "collision_limit_distance": _profile_input("BoneSpring soft-sphere碰撞限制距离。", min_value=0.0, max_value=1.0),
    "collision_limit_curve": _profile_input("BoneSpring碰撞距离的深度曲线"),
    "self_collision_enabled": _profile_input("启用FullMesh自碰撞；内部转换为MC2模式2。"),
    "self_collision_interaction": _profile_input("跨任务自碰撞\n范围：同一Physics World"),
    "cloth_mass": _profile_input("跨布料自碰撞时用于质量比例的参数。", min_value=0.0, max_value=1.0),
}

_CLOTH_PROFILE_FIELDS = tuple(name for name in _PROFILE_LABELS if name not in {
    "collision_limit_distance", "collision_limit_curve",
})
_SPRING_PROFILE_FIELDS = tuple(name for name in _PROFILE_LABELS if name not in {
    "gravity_direction", "gravity", "gravity_falloff", "tether_compression",
    "distance_stiffness", "distance_stiffness_curve", "max_distance_enabled", "max_distance",
    "max_distance_curve", "backstop_enabled", "backstop_radius", "backstop_distance",
    "backstop_distance_curve", "collision_mode", "collision_friction", "self_collision_enabled",
    "self_collision_interaction", "cloth_mass",
})


def _profile_presets(fields: tuple[str, ...]) -> tuple[dict, ...]:
    result = []
    for preset in MC2_PARTICLE_PRESETS:
        source = preset["values"]
        values = {}
        for name in fields:
            if name == "self_collision_enabled":
                values[name] = int(source.get("self_collision_mode", 0)) == 2
            elif name in source:
                values[name] = source[name]
        result.append({**preset, "values": values})
    return tuple(result)


def _profile_meta(fields: tuple[str, ...], *, label: str, description: str) -> dict:
    return {
        "enable": True,
        "bl_label": label,
        "base_color": _Color.colorCat["Operator"],
        "is_output_node": False,
        "_INPUT_NAME": [_PROFILE_LABELS[name] for name in fields],
        "input_init": {name: _PROFILE_INPUT_INIT[name] for name in fields},
        "omni_presets": _profile_presets(fields),
        "_OUTPUT_NAME": ["MC2粒子配置"],
        "mute_passthrough": False,
        "omni_description": description,
    }


def _make_profile(values: dict, setup_type: str):
    values = dict(values)
    if "self_collision_enabled" in values:
        values["self_collision_mode"] = 2 if values.pop("self_collision_enabled") else 0
    values["self_collision_sync_mode"] = 2 if values.pop(
        "self_collision_interaction", False
    ) else 0
    values["spring_enabled"] = False
    return make_mc2_particle_profile(**values)


@omni(**_profile_meta(
    _CLOTH_PROFILE_FIELDS,
    label="MC2 MeshCloth粒子配置",
    description="只显示MeshCloth实际可调字段；输出统一MC2ParticleProfileSpec。Spring字段不进入本节点。",
))
def physicsMC2MeshClothProfile(
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
    self_collision_enabled: bool = False,
    self_collision_interaction: bool = False,
    cloth_mass: float = 0.0,
) -> typing.Any:
    profile_values = dict(locals())
    return _make_profile(profile_values, MC2_SETUP_MESH_CLOTH)


@omni(**_profile_meta(
    _CLOTH_PROFILE_FIELDS,
    label="MC2 BoneCloth粒子配置",
    description="只显示BoneCloth实际可调字段；输出统一MC2ParticleProfileSpec。Spring字段不进入本节点。",
))
def physicsMC2BoneClothProfile(
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
    self_collision_enabled: bool = False,
    self_collision_interaction: bool = False,
    cloth_mass: float = 0.0,
) -> typing.Any:
    profile_values = dict(locals())
    return _make_profile(profile_values, MC2_SETUP_BONE_CLOTH)


@omni(**_profile_meta(
    _SPRING_PROFILE_FIELDS,
    label="MC2 BoneSpring粒子配置",
    description="只显示BoneSpring实际消费的字段；源码固定/关闭的cloth字段以及当前native未消费的Spring/wind兼容字段不公开。输出统一MC2ParticleProfileSpec。",
))
def physicsMC2BoneSpringProfile(
    blend_weight: float = 1.0,
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
    motion_stiffness: float = 1.0,
    collision_limit_distance: float = 0.05,
    collision_limit_curve: _OmniFloatCurve = None,
) -> typing.Any:
    profile_values = dict(locals())
    return _make_profile(profile_values, MC2_SETUP_BONE_SPRING)


@omni(
    enable=True,
    bl_label="MC2 MeshCloth任务",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["代理网格", "粒子配置", "启用"],
    input_init={
        "mesh_objects": {"description": "MeshCloth网格列表\n每对象一个任务"},
        "profile": {"description": "MC2 MeshCloth配置\n留空使用默认值"},
        "enabled": {"description": "保留任务但不参与模拟"},
    },
    _OUTPUT_NAME=["MC2任务", "任务名称"],
    mute_passthrough=False,
)
def physicsMC2MeshClothTask(
    mesh_objects: list[bpy.types.Object],
    profile: typing.Any = None,
    enabled: bool = True,
) -> tuple[list[typing.Any], str]:
    tasks = _mesh_cloth_tasks(
        mesh_objects,
        profile,
        enabled,
    )
    return tasks, _task_name_output(tasks)


@omni(
    enable=True,
    bl_label="MC2 BoneCloth任务",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["中控骨", "粒子配置", "连接模式", "旋转插值", "根旋转", "被碰撞组", "启用"],
    input_init={
        "control_bones": {"description": "直接子骨生成模拟链\n每个中控骨独立横连"},
        "profile": {"description": "MC2 BoneCloth配置\n留空使用默认值"},
        "connection_mode": {
            "min_value": 0,
            "max_value": 2,
            "description": "横连：0 Line / 1 Seq / 2 SeqLoop",
        },
        "rotational_interpolation": {"min_value": 0.0, "max_value": 1.0, "description": "粒子方向写回骨骼旋转时的插值比例。"},
        "root_rotation": {"min_value": 0.0, "max_value": 1.0, "description": "模拟链根部旋转参与写回的比例。"},
        "collided_by_groups": {"mask_length": 16, "description": "被碰撞组Mask\n0:不筛选"},
        "enabled": {"description": "保留任务但不参与模拟"},
    },
    _OUTPUT_NAME=["MC2任务", "任务名称"],
    mute_passthrough=False,
)
def physicsMC2BoneClothTask(
    control_bones: list[_OmniBone],
    profile: typing.Any = None,
    connection_mode: int = 1,
    rotational_interpolation: float = 0.5,
    root_rotation: float = 0.5,
    collided_by_groups: _OmniBitMask = 0,
    enabled: bool = True,
) -> tuple[list[typing.Any], str]:
    tasks = _hotools_bone_tasks(
        control_bones,
        profile,
        enabled,
        connection_mode=connection_mode,
        rotational_interpolation=rotational_interpolation,
        root_rotation=root_rotation,
        collided_by_groups=collided_by_groups,
    )
    return tasks, _task_name_output(tasks)


@omni(
    enable=True,
    bl_label="MC2 BoneSpring任务",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["根骨", "粒子配置", "旋转插值", "根旋转", "被碰撞组", "启用"],
    input_init={
        "root_bones": {"description": "BoneSpring根骨列表\n递归收集后代"},
        "profile": {"description": "MC2 BoneSpring配置\n留空使用默认值"},
        "rotational_interpolation": {"min_value": 0.0, "max_value": 1.0, "description": "粒子方向写回骨骼旋转时的插值比例。"},
        "root_rotation": {"min_value": 0.0, "max_value": 1.0, "description": "模拟链根部旋转参与写回的比例。"},
        "collided_by_groups": {"mask_length": 16, "description": "被碰撞组Mask\n0:不筛选"},
        "enabled": {"description": "保留任务但不参与模拟"},
    },
    _OUTPUT_NAME=["MC2任务", "任务名称"],
    mute_passthrough=False,
)
def physicsMC2BoneSpringTask(
    root_bones: list[_OmniBone],
    profile: typing.Any = None,
    rotational_interpolation: float = 0.5,
    root_rotation: float = 0.5,
    collided_by_groups: _OmniBitMask = 0,
    enabled: bool = True,
) -> tuple[list[typing.Any], str]:
    tasks = _bone_spring_tasks(
        root_bones,
        profile,
        enabled,
        rotational_interpolation=rotational_interpolation,
        root_rotation=root_rotation,
        collided_by_groups=collided_by_groups,
    )
    return tasks, _task_name_output(tasks)


@omni(
    enable=True,
    always_run=True,
    bl_label="MC2模拟步",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "物理世界", "MC2任务", "时间缩放", "模拟频率",
        "每帧最大模拟次数", "启用",
    ],
    input_init={
        "world": {"description": "Physics World统一时间源"},
        "mc2_tasks": {"description": "全部MC2任务\n单步统一处理"},
        "time_scale": {"min_value": 0.0, "max_value": 1.0, "description": "MC2局部时间倍率\n缩放统一dt"},
        "simulation_frequency": {"min_value": 30, "max_value": 150, "description": "MC2固定步频率（Hz）"},
        "max_simulation_count_per_frame": {"min_value": 1, "max_value": 5, "description": "每帧固定步上限\n超出时跳过"},
        "enabled": {"description": "关闭整个MC2模拟步，不推进任何MC2 task。"},
    },
    _OUTPUT_NAME=["物理世界", "就绪", "状态"],
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsMC2Step(
    world: PhysicsWorldCache,
    mc2_tasks: list[typing.Any],
    time_scale: float = 1.0,
    simulation_frequency: int = 90,
    max_simulation_count_per_frame: int = 3,
    enabled: bool = True,
) -> tuple[PhysicsWorldCache, bool, str]:
    if (
        isinstance(mc2_tasks, list)
        and len(mc2_tasks) == 1
        and type(mc2_tasks[0]) is float
        and mc2_tasks[0] == 0.0
    ):
        mc2_tasks = []
    settings = make_mc2_solver_settings(
        time_scale=time_scale,
        simulation_frequency=simulation_frequency,
        max_simulation_count_per_frame=max_simulation_count_per_frame,
    )
    return step_mc2(world, mc2_tasks, settings=settings, enabled=enabled)


@omni(
    enable=True,
    always_run=True,
    bl_label="MC2可视化调试",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=[
        "物理世界", "任务筛选", "最大显示项", "拓扑连接", "Fixed/Move",
        "StepBasic参考姿态", "有效重力", "粒子速度", "Distance误差", "Tether范围",
        "Bending约束", "Motion BasePosition", "Motion约束",
        "Angle恢复目标", "Angle限制范围", "Center/Teleport", "碰撞情况", "粒子半径",
        "自碰1 几何单元", "自碰2 空间网格", "自碰3 候选配对",
        "自碰4 接触结果", "最终输出偏移",
    ],
    input_init={
        "world": {"description": "包含MC2 slot和隐式debug快照的Physics World。"},
        "show_topology": {"description": "显示真实纵向/横向拓扑连接。"},
        "show_attributes": {"description": "显示Fixed/Move等粒子属性。"},
        "show_step_basic": {"description": "显示结构约束实际使用的StepBasic参考姿态。\n它不同于Motion动画基准。"},
        "show_gravity": {"description": "绿色箭头显示实际有效重力。\n已包含强度、Center重力衰减和scale。\n显示长度=加速度x0.02。"},
        "show_velocity": {"description": "显示post后的粒子速度。\n青色=solver保存速度\n橙色=本步真实位移速度\n显示长度=速度x0.03。"},
        "show_distance": {"description": "显示Distance当前长度相对有效rest长度。\n绿色=接近rest\n红色=拉长\n蓝色=压缩。"},
        "show_tether": {"description": "显示粒子到baseline root的Tether范围。\n灰线=当前距离\n蓝环=最短允许距离\n黄环=最长允许距离。"},
        "show_bending": {"description": "显示实际Bending quad。\n紫色=角度约束\n青色=volume约束\n红色=偏离rest。"},
        "show_motion_base": {"description": "Motion实际BasePosition/法线轴。"},
        "show_motion": {"description": "显示MaxDistance与Backstop约束。"},
        "show_angle_restoration": {"description": "粉色箭头显示Angle Restoration目标。"},
        "show_angle_limit": {"description": "黄色锥体显示每个父子段允许的Angle Limit范围。\n刚度为0时不绘制。"},
        "show_center": {"description": "显示Center/Teleport/变换抵消"},
        "show_collision": {"description": "显示当前真正参与外碰的双方。\n绿色=Point粒子球\n橙色=Edge布料形状\n灰色=外部碰撞体。"},
        "show_radii": {"description": "参数审计：显示全部粒子半径。\n不表示当前一定参与碰撞。"},
        "show_self_primitives": {"description": "自碰阶段1：几何单元\n紫色点/边/三角形\n表示实际参与检测的primitive。"},
        "show_self_grid": {"description": "自碰阶段2：空间网格\n灰色方格表示broadphase占用单元\n用于检查分桶尺度与密度。"},
        "show_self_candidates": {"description": "自碰阶段3：候选配对\n黄色连线表示网格筛出的潜在碰撞对\n候选不等于真实接触。"},
        "show_self_contacts": {"description": "自碰阶段4：接触结果\n红色=启用接触和法线\n灰色=未启用接触\n洋红=穿插记录。"},
        "show_output": {"description": "显示实际写回的最终输出偏移。"},
        "task_filter": {"description": "任务名/task id。\n换行/逗号分隔，空=全部。"},
        "max_items": {"min_value": 1, "max_value": 100000, "description": "每种可视化最多绘制的项目数。"},
    },
    _OUTPUT_NAME=["物理世界"],
    mute_passthrough={"_OUTPUT0": "world"},
    omni_description="从冻结的native快照绘制MC2真实中间态。自碰1到4对应检测流水线，不是四种算法。",
)
def physicsMC2DebugDraw(
    world: PhysicsWorldCache,
    task_filter: str = "",
    max_items: int = 2000,
    show_topology: bool = True,
    show_attributes: bool = True,
    show_step_basic: bool = False,
    show_gravity: bool = False,
    show_velocity: bool = False,
    show_distance: bool = False,
    show_tether: bool = False,
    show_bending: bool = False,
    show_motion_base: bool = True,
    show_motion: bool = True,
    show_angle_restoration: bool = True,
    show_angle_limit: bool = False,
    show_center: bool = True,
    show_collision: bool = True,
    show_radii: bool = False,
    show_self_primitives: bool = False,
    show_self_grid: bool = False,
    show_self_candidates: bool = False,
    show_self_contacts: bool = True,
    show_output: bool = True,
) -> PhysicsWorldCache:
    update_mc2_debug_draw_store(
        str(id(world)),
        world,
        True,
        show_topology=show_topology,
        show_attributes=show_attributes,
        show_step_basic=show_step_basic,
        show_gravity=show_gravity,
        show_velocity=show_velocity,
        show_distance=show_distance,
        show_tether=show_tether,
        show_bending=show_bending,
        show_motion_base=show_motion_base,
        show_motion=show_motion,
        show_angle_restoration=show_angle_restoration,
        show_angle_limit=show_angle_limit,
        show_center=show_center,
        show_collision=show_collision,
        show_radii=show_radii,
        show_self_primitives=show_self_primitives,
        show_self_grid=show_self_grid,
        show_self_candidates=show_self_candidates,
        show_self_contacts=show_self_contacts,
        show_output=show_output,
        task_filter=task_filter,
        max_items=max_items,
    )
    return world
