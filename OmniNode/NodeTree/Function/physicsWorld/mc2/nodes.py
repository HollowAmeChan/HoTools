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
    make_mc2_task_parameters,
)
from .presets import MC2_PARTICLE_PRESETS
from .specs import make_mc2_task_spec


def _task_name_output(tasks) -> str:
    return "\n".join(str(task.task_id) for task in tasks)


def _mesh_cloth_tasks(
    mesh_objects, anchor_object, profile, task_parameters, enabled: bool
):
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
            task_parameters=task_parameters,
            anchor_object=anchor_object,
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


def _hotools_bone_tasks(
    control_bones,
    anchor_object,
    profile,
    task_parameters,
    enabled: bool,
    **setup_values,
):
    if profile is None:
        profile = make_mc2_particle_profile(spring_enabled=False)
    setup_values["self_collision_radius_model"] = "derived_radius"
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
            task_parameters=task_parameters,
            anchor_object=anchor_object,
            enabled=enabled,
        )
        for group in groups
    ]


def _bone_spring_tasks(
    root_bones,
    anchor_object,
    profile,
    task_parameters,
    enabled: bool,
    **setup_values,
):
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
            task_parameters=task_parameters,
            anchor_object=anchor_object,
            enabled=enabled,
        )
        for group in grouped.values()
    ]


def _profile_input(description: str, **settings) -> dict:
    return {"description": description, **settings}


_PROFILE_LABELS = {
    "blend_weight": "混合权重", "gravity_direction": "重力方向", "gravity": "重力强度",
    "gravity_falloff": "重力衰减", "stabilization_time_after_reset": "重置稳定时间",
    "animation_pose_ratio": "动画姿态比例", "particle_speed_limit": "粒子限速",
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
    "self_collision_interaction": "跨物体自碰撞",
}

_PROFILE_INPUT_INIT = {
    "blend_weight": _profile_input("物理混合\n0:动画  1:完整物理", min_value=0.0, max_value=1.0),
    "gravity_direction": _profile_input("世界空间重力方向；仅MeshCloth/BoneCloth消费。"),
    "gravity": _profile_input("重力加速度强度；BoneSpring强制为0。", min_value=0.0, max_value=20.0),
    "gravity_falloff": _profile_input(
        "Center朝向重力衰减\n0=关闭  1=完全",
        min_value=0.0,
        max_value=1.0,
    ),
    "stabilization_time_after_reset": _profile_input("Reset或Teleport后的稳定时间。\n单位：秒", min_value=0.0, max_value=1.0),
    "animation_pose_ratio": _profile_input("约束参考姿态中动画姿态所占比例。", min_value=0.0, max_value=1.0),
    "particle_speed_limit": _profile_input("粒子速度上限；负值禁用。", min_value=-1.0, max_value=10.0),
    "damping": _profile_input("粒子速度阻尼基础值。", min_value=0.0, max_value=1.0),
    "damping_curve": _profile_input("按粒子深度乘到阻尼基础值上的曲线。"),
    "radius": _profile_input("粒子碰撞半径基础值。", min_value=0.001, max_value=1.0),
    "radius_curve": _profile_input("按粒子深度乘到半径基础值上的曲线。"),
    "tether_compression": _profile_input("Tether允许压缩的比例。\nBoneSpring使用固定值。", min_value=0.0, max_value=1.0),
    "distance_stiffness": _profile_input("相邻粒子距离刚度\nBoneSpring固定", min_value=0.0, max_value=1.0),
    "distance_stiffness_curve": _profile_input("按粒子深度乘到距离刚度上的曲线。"),
    "bending_stiffness": _profile_input("三角弯曲刚度；0关闭。", min_value=0.0, max_value=1.0),
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
    "collision_mode": _profile_input("0:None  1:Point  2:Edge\nEdge使用代理边。", min_value=0, max_value=2),
    "collision_friction": _profile_input("外部碰撞摩擦系数。\nBoneSpring使用固定值。", min_value=0.0, max_value=0.5),
    "collision_limit_distance": _profile_input("BoneSpring soft-sphere碰撞限制距离。", min_value=0.0, max_value=1.0),
    "collision_limit_curve": _profile_input("BoneSpring碰撞距离的深度曲线"),
    "self_collision_enabled": _profile_input("启用FullMesh自碰撞；内部转换为MC2模式2。"),
    "self_collision_interaction": _profile_input("跨任务自碰撞\n范围：同一Physics World"),
}

_MESH_CLOTH_PROFILE_FIELDS = tuple(name for name in _PROFILE_LABELS if name not in {
    "collision_limit_distance", "collision_limit_curve",
})
_BONE_CLOTH_PROFILE_FIELDS = tuple(
    name for name in _MESH_CLOTH_PROFILE_FIELDS
    if name != "self_collision_interaction"
)
_SPRING_PROFILE_FIELDS = tuple(name for name in _PROFILE_LABELS if name not in {
    "gravity_direction", "gravity", "gravity_falloff", "tether_compression",
    "distance_stiffness", "distance_stiffness_curve", "bending_stiffness",
    "max_distance_enabled", "max_distance",
    "max_distance_curve", "backstop_enabled", "backstop_radius", "backstop_distance",
    "backstop_distance_curve", "collision_mode", "collision_friction", "self_collision_enabled",
    "self_collision_interaction",
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
    _MESH_CLOTH_PROFILE_FIELDS,
    label="MC2 MeshCloth粒子配置",
    description="只显示MeshCloth实际可调字段；输出统一MC2ParticleProfileSpec。Spring字段不进入本节点。",
))
def physicsMC2MeshClothProfile(
    blend_weight: float = 1.0,
    gravity_direction: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity: float = 5.0,
    gravity_falloff: float = 0.0,
    stabilization_time_after_reset: float = 0.1,
    animation_pose_ratio: float = 0.0,
    particle_speed_limit: float = 4.0,
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
) -> typing.Any:
    profile_values = dict(locals())
    return _make_profile(profile_values, MC2_SETUP_MESH_CLOTH)


@omni(**_profile_meta(
    _BONE_CLOTH_PROFILE_FIELDS,
    label="MC2 BoneCloth粒子配置",
    description="只显示BoneCloth实际可调字段；输出统一MC2ParticleProfileSpec。Spring字段不进入本节点。",
))
def physicsMC2BoneClothProfile(
    blend_weight: float = 1.0,
    gravity_direction: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity: float = 5.0,
    gravity_falloff: float = 0.0,
    stabilization_time_after_reset: float = 0.1,
    animation_pose_ratio: float = 0.0,
    particle_speed_limit: float = 4.0,
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
    animation_pose_ratio: float = 0.0,
    particle_speed_limit: float = 4.0,
    damping: float = 0.05,
    damping_curve: _OmniFloatCurve = None,
    radius: float = 0.02,
    radius_curve: _OmniFloatCurve = None,
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


_TASK_PARAMETER_LABELS = {
    "normal_axis": "法线轴",
    "anchor_inertia": "Anchor惯性",
    "world_inertia": "World惯性",
    "movement_inertia_smoothing": "惯性平滑",
    "movement_speed_limit": "World移动限速",
    "rotation_speed_limit": "World旋转限速",
    "local_inertia": "Local惯性",
    "local_movement_speed_limit": "Local移动限速",
    "local_rotation_speed_limit": "Local旋转限速",
    "depth_inertia": "深度惯性",
    "teleport_mode": "Teleport模式",
    "teleport_distance": "Teleport距离",
    "teleport_rotation": "Teleport旋转",
    "cloth_mass": "自碰交互质量",
}

_TASK_PARAMETER_INPUT_INIT = {
    "normal_axis": {
        "description": "Motion/Backstop法线轴\n0:+X 1:+Y 2:+Z 3:-X 4:-Y 5:-Z",
        "min_value": 0,
        "max_value": 5,
    },
    "anchor_inertia": {
        "description": "Anchor运动保留为惯性的比例",
        "min_value": 0.0,
        "max_value": 1.0,
    },
    "world_inertia": {
        "description": "组件World运动保留为惯性的比例",
        "min_value": 0.0,
        "max_value": 1.0,
    },
    "movement_inertia_smoothing": {
        "description": "组件World移动惯性平滑",
        "min_value": 0.0,
        "max_value": 1.0,
    },
    "movement_speed_limit": {
        "description": "World移动补偿限速；负值关闭",
        "min_value": -1.0,
        "max_value": 10.0,
    },
    "rotation_speed_limit": {
        "description": "World旋转补偿限速（度/秒）；负值关闭",
        "min_value": -1.0,
        "max_value": 1440.0,
    },
    "local_inertia": {
        "description": "Fixed step内Local运动惯性比例",
        "min_value": 0.0,
        "max_value": 1.0,
    },
    "local_movement_speed_limit": {
        "description": "Local移动惯性限速；负值关闭",
        "min_value": -1.0,
        "max_value": 10.0,
    },
    "local_rotation_speed_limit": {
        "description": "Local旋转惯性限速（度/秒）；负值关闭",
        "min_value": -1.0,
        "max_value": 1440.0,
    },
    "depth_inertia": {
        "description": "按深度保留末端惯性\n权重=1-depth^1.5",
        "min_value": 0.0,
        "max_value": 1.0,
    },
    "teleport_mode": {
        "description": "0:None  1:Reset  2:Keep",
        "min_value": 0,
        "max_value": 2,
    },
    "teleport_distance": {
        "description": "Task基准位移阈值；实际值乘组件Scale",
        "min_value": 0.0,
    },
    "teleport_rotation": {
        "description": "Task基准旋转阈值（度）；与位移条件为OR",
        "min_value": 0.0,
    },
    "cloth_mass": {
        "description": "自碰接触相对质量；影响双方修正比例",
        "min_value": 0.0,
        "max_value": 1.0,
    },
}

_TASK_INERTIA_FIELDS = (
    "anchor_inertia",
    "world_inertia",
    "movement_inertia_smoothing",
    "movement_speed_limit",
    "rotation_speed_limit",
    "local_inertia",
    "local_movement_speed_limit",
    "local_rotation_speed_limit",
    "depth_inertia",
)
_TASK_TELEPORT_FIELDS = (
    "teleport_mode",
    "teleport_distance",
    "teleport_rotation",
)
_TASK_CLOTH_PARAMETER_FIELDS = (
    "normal_axis",
    *_TASK_INERTIA_FIELDS,
    *_TASK_TELEPORT_FIELDS,
    "cloth_mass",
)
_TASK_SPRING_PARAMETER_FIELDS = (*_TASK_INERTIA_FIELDS, *_TASK_TELEPORT_FIELDS)


def _task_parameter_inputs(fields: tuple[str, ...]) -> dict:
    return {name: _TASK_PARAMETER_INPUT_INIT[name] for name in fields}


def _task_parameter_presets(fields: tuple[str, ...]) -> tuple[dict, ...]:
    return tuple({
        **preset,
        "values": {
            name: preset["values"][name]
            for name in fields
            if name in preset["values"]
        },
    } for preset in MC2_PARTICLE_PRESETS)


def _make_task_parameters(values: dict):
    return make_mc2_task_parameters(**{
        name: values[name]
        for name in _TASK_PARAMETER_LABELS
        if name in values
    })


@omni(
    enable=True,
    bl_label="MC2 MeshCloth任务",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "代理网格", "粒子配置", "Anchor",
        *(_TASK_PARAMETER_LABELS[name] for name in _TASK_CLOTH_PARAMETER_FIELDS),
        "启用",
    ],
    input_init={
        "mesh_objects": {"description": "MeshCloth网格列表\n每对象一个任务"},
        "anchor_object": {"description": "消除平台等非物理运动\n留空则不使用"},
        "profile": {"description": "MC2 MeshCloth配置\n留空使用默认值"},
        **_task_parameter_inputs(_TASK_CLOTH_PARAMETER_FIELDS),
        "enabled": {"description": "保留任务但不参与模拟"},
    },
    omni_presets=_task_parameter_presets(_TASK_CLOTH_PARAMETER_FIELDS),
    _OUTPUT_NAME=["MC2任务", "任务名称"],
    mute_passthrough=False,
)
def physicsMC2MeshClothTask(
    mesh_objects: list[bpy.types.Object],
    profile: typing.Any = None,
    anchor_object: bpy.types.Object = None,
    normal_axis: int = 1,
    anchor_inertia: float = 0.0,
    world_inertia: float = 1.0,
    movement_inertia_smoothing: float = 0.4,
    movement_speed_limit: float = 5.0,
    rotation_speed_limit: float = 720.0,
    local_inertia: float = 1.0,
    local_movement_speed_limit: float = -1.0,
    local_rotation_speed_limit: float = -1.0,
    depth_inertia: float = 0.0,
    teleport_mode: int = 0,
    teleport_distance: float = 0.5,
    teleport_rotation: float = 90.0,
    cloth_mass: float = 0.0,
    enabled: bool = True,
) -> tuple[list[typing.Any], str]:
    task_parameters = _make_task_parameters(locals())
    tasks = _mesh_cloth_tasks(
        mesh_objects,
        anchor_object,
        profile,
        task_parameters,
        enabled,
    )
    return tasks, _task_name_output(tasks)


@omni(
    enable=True,
    bl_label="MC2 BoneCloth任务",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "中控骨", "粒子配置", "Anchor",
        *(_TASK_PARAMETER_LABELS[name] for name in _TASK_CLOTH_PARAMETER_FIELDS),
        "连接模式", "旋转插值", "根旋转", "被碰撞组", "启用",
    ],
    input_init={
        "control_bones": {"description": "直接子骨生成模拟链\n每个中控骨独立横连"},
        "anchor_object": {"description": "消除平台等非物理运动\n留空则不使用"},
        "profile": {"description": "MC2 BoneCloth配置\n留空使用默认值"},
        **_task_parameter_inputs(_TASK_CLOTH_PARAMETER_FIELDS),
        "connection_mode": {
            "min_value": 0,
            "max_value": 2,
            "description": "横连：0 Line / 1 Seq / 2 SeqLoop",
        },
        "rotational_interpolation": {
            "min_value": 0.0,
            "max_value": 1.0,
            "description": "Move父骨方向比例\nTriangle会覆盖",
        },
        "root_rotation": {
            "min_value": 0.0,
            "max_value": 1.0,
            "description": "Fixed根骨方向比例\nTriangle会覆盖",
        },
        "collided_by_groups": {"mask_length": 16, "description": "被碰撞组Mask\n0:不筛选"},
        "enabled": {"description": "保留任务但不参与模拟"},
    },
    omni_presets=_task_parameter_presets(_TASK_CLOTH_PARAMETER_FIELDS),
    _OUTPUT_NAME=["MC2任务", "任务名称"],
    mute_passthrough=False,
)
def physicsMC2BoneClothTask(
    control_bones: list[_OmniBone],
    profile: typing.Any = None,
    anchor_object: bpy.types.Object = None,
    normal_axis: int = 1,
    anchor_inertia: float = 0.0,
    world_inertia: float = 1.0,
    movement_inertia_smoothing: float = 0.4,
    movement_speed_limit: float = 5.0,
    rotation_speed_limit: float = 720.0,
    local_inertia: float = 1.0,
    local_movement_speed_limit: float = -1.0,
    local_rotation_speed_limit: float = -1.0,
    depth_inertia: float = 0.0,
    teleport_mode: int = 0,
    teleport_distance: float = 0.5,
    teleport_rotation: float = 90.0,
    cloth_mass: float = 0.0,
    connection_mode: int = 1,
    rotational_interpolation: float = 0.5,
    root_rotation: float = 0.5,
    collided_by_groups: _OmniBitMask = 0,
    enabled: bool = True,
) -> tuple[list[typing.Any], str]:
    task_parameters = _make_task_parameters(locals())
    tasks = _hotools_bone_tasks(
        control_bones,
        anchor_object,
        profile,
        task_parameters,
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
    _INPUT_NAME=[
        "根骨", "粒子配置", "Anchor",
        *(_TASK_PARAMETER_LABELS[name] for name in _TASK_SPRING_PARAMETER_FIELDS),
        "旋转插值", "根旋转", "被碰撞组", "启用",
    ],
    input_init={
        "root_bones": {"description": "BoneSpring根骨列表\n递归收集后代"},
        "anchor_object": {"description": "消除平台等非物理运动\n留空则不使用"},
        "profile": {"description": "MC2 BoneSpring配置\n留空使用默认值"},
        **_task_parameter_inputs(_TASK_SPRING_PARAMETER_FIELDS),
        "rotational_interpolation": {"min_value": 0.0, "max_value": 1.0, "description": "Move父骨方向比例\n仅影响骨骼旋转"},
        "root_rotation": {"min_value": 0.0, "max_value": 1.0, "description": "Fixed根骨方向比例\n仅影响骨骼旋转"},
        "collided_by_groups": {"mask_length": 16, "description": "被碰撞组Mask\n0:不筛选"},
        "enabled": {"description": "保留任务但不参与模拟"},
    },
    omni_presets=_task_parameter_presets(_TASK_SPRING_PARAMETER_FIELDS),
    _OUTPUT_NAME=["MC2任务", "任务名称"],
    mute_passthrough=False,
)
def physicsMC2BoneSpringTask(
    root_bones: list[_OmniBone],
    profile: typing.Any = None,
    anchor_object: bpy.types.Object = None,
    anchor_inertia: float = 0.0,
    world_inertia: float = 1.0,
    movement_inertia_smoothing: float = 0.4,
    movement_speed_limit: float = 5.0,
    rotation_speed_limit: float = 720.0,
    local_inertia: float = 1.0,
    local_movement_speed_limit: float = -1.0,
    local_rotation_speed_limit: float = -1.0,
    depth_inertia: float = 0.0,
    teleport_mode: int = 0,
    teleport_distance: float = 0.5,
    teleport_rotation: float = 90.0,
    rotational_interpolation: float = 0.5,
    root_rotation: float = 0.5,
    collided_by_groups: _OmniBitMask = 0,
    enabled: bool = True,
) -> tuple[list[typing.Any], str]:
    task_parameters = _make_task_parameters(locals())
    tasks = _bone_spring_tasks(
        root_bones,
        anchor_object,
        profile,
        task_parameters,
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
        "物理世界", "任务筛选", "最大显示项", "拓扑连接", "Fixed/Move", "粒子深度",
        "StepBasic参考姿态", "有效重力", "粒子速度", "Distance误差", "Tether范围",
        "Bending约束", "Motion BasePosition", "Motion约束",
        "Angle恢复目标", "Angle限制范围", "Center", "Teleport阈值与方向",
        "Teleport触发状态", "碰撞情况", "粒子半径",
        "自碰1 几何单元", "自碰2 空间网格", "自碰3 候选配对",
        "自碰4 接触结果", "最终输出偏移",
    ],
    input_init={
        "world": {"description": "包含MC2 slot和隐式debug快照的Physics World。"},
        "show_topology": {"description": "显示真实纵向/横向拓扑连接。"},
        "show_attributes": {"description": "显示Fixed/Move等粒子属性。"},
        "show_depth": {"description": "蓝=近根 橙=远端\n红=非法 粉=Fixed"},
        "show_step_basic": {"description": "结构约束的StepBasic姿态。\n不同于Motion基准。"},
        "show_gravity": {"description": "绿箭头=有效重力。\n长度=加速度x0.02。"},
        "show_velocity": {"description": "青=保存速度  橙=真实速度\n长度=速度x0.03"},
        "show_distance": {"description": "Distance：绿=正常 红=拉长 蓝=压缩"},
        "show_tether": {"description": "Tether：灰=当前 蓝=最短 黄=最长"},
        "show_bending": {"description": "Bending：紫=角度 青=体积 红=误差"},
        "show_motion_base": {"description": "Motion实际BasePosition/法线轴。"},
        "show_motion": {"description": "显示MaxDistance与Backstop约束。"},
        "show_angle_restoration": {"description": "粉色箭头显示Angle Restoration目标。"},
        "show_angle_limit": {"description": "黄锥=Angle Limit范围。\n方向为层级目标。"},
        "show_center": {"description": "显示组件、Anchor、frame shift与惯性量。"},
        "show_teleport_threshold": {
            "description": "Teleport阈值与方向\n球=阈值  线=旧到新"
        },
        "show_teleport_status": {
            "description": "Teleport触发状态。\n绿=未触发  黄=Keep  红=Reset"
        },
        "show_collision": {"description": "碰撞：绿=Point 橙=Edge 蓝=外部体"},
        "show_radii": {"description": "全部粒子半径（仅参数审计）。"},
        "show_self_primitives": {"description": "自碰1：紫=实际点/边/三角形"},
        "show_self_grid": {"description": "自碰2：灰=空间网格占用"},
        "show_self_candidates": {"description": "自碰3：黄=宽相候选（非接触）"},
        "show_self_contacts": {"description": "自碰4：红=接触 灰=禁用\n洋红=确认穿插"},
        "show_output": {"description": "显示实际写回的最终输出偏移。"},
        "task_filter": {"description": "任务名/task id。\n换行/逗号分隔，空=全部。"},
        "max_items": {"min_value": 1, "max_value": 100000, "description": "每种可视化最多绘制的项目数。"},
    },
    _OUTPUT_NAME=["物理世界"],
    mute_passthrough={"_OUTPUT0": "world"},
    omni_description=(
        "从冻结的native快照绘制MC2真实中间态。\n\n"
        "粒子深度：显示约束、半径、阻尼和惯性曲线实际采样的baseline depth。"
        "蓝色接近0（近根），经青/绿/黄过渡到橙色1（远端）；粉色是Fixed根，"
        "紫色是root=-1的无根Move粒子，黄色点是ZeroDistance。白线分隔不同Fixed根，"
        "橙线表示异常大的局部深度跳变，红线表示深度逆序或parent/root不一致。"
        "该模式只显示当前真实baseline，不代表Motion距离或骨链层级。\n\n"
        "自碰1到4对应检测流水线，不是四种算法。自碰4中红色是实际厚度接触，"
        "灰色是禁用接触，洋红只表示final线段-三角形测试确认的几何穿插。"
        "独立穿插检测把排序后的Edge分成奇偶两组跨帧扫描，因此真实命中也只在"
        "对应分片帧显示；这种规律切换不是普通EE/PT接触停止，也不是浮点随机。"
    ),
)
def physicsMC2DebugDraw(
    world: PhysicsWorldCache,
    task_filter: str = "",
    max_items: int = 2000,
    show_topology: bool = True,
    show_attributes: bool = True,
    show_depth: bool = False,
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
    show_teleport_threshold: bool = False,
    show_teleport_status: bool = False,
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
        show_depth=show_depth,
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
        show_teleport_threshold=show_teleport_threshold,
        show_teleport_status=show_teleport_status,
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
