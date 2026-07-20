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
    rows = ["字段 | 功能与实现", "--- | ---"]
    rows.extend(
        f"{_PROFILE_LABELS[name]} | "
        f"{_PROFILE_INPUT_INIT[name]['description'].replace(chr(10), '；')}"
        for name in fields
    )
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
        "omni_description": description + "\n\n" + "\n".join(rows),
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


def _task_long_description(setup_label: str, fields: tuple[str, ...]) -> str:
    rows = ["字段 | 功能与实现", "--- | ---"]
    rows.extend(
        f"{_TASK_PARAMETER_LABELS[name]} | "
        f"{_TASK_PARAMETER_INPUT_INIT[name]['description'].replace(chr(10), '；')}"
        for name in fields
    )
    return (
        f"{setup_label}的对象身份、组件运动修正、Teleport与交互参数。"
        "这些值属于Task并走parameter hot update，不属于粒子Profile，"
        "也不改变task id或拓扑。\n\n" + "\n".join(rows)
    )


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
    omni_description=_task_long_description(
        "MeshCloth", _TASK_CLOTH_PARAMETER_FIELDS
    ),
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
    omni_description=_task_long_description(
        "BoneCloth", _TASK_CLOTH_PARAMETER_FIELDS
    ),
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
    omni_description=_task_long_description(
        "BoneSpring", _TASK_SPRING_PARAMETER_FIELDS
    ),
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


def _mc2_debug_help(purpose, state, normal, parameters, triggers) -> str:
    return (
        f"用途：{purpose} 当前状态：{state} 正常判断：{normal} "
        f"直接影响参数：{parameters} 可能变化或触发它的来源：{triggers}"
    )


_MC2_DEBUG_DESCRIPTION_ITEMS = (
    ("物理世界", _mc2_debug_help(
        "选择要读取的Physics World，并把同一world原样传给下游；本节点只观察，不修改模拟。",
        "“调试状态”输出按task列出上一份冻结快照的捕获帧、记录数、接近数和真实触发数；首次启用通常要等下一次真实substep。",
        "输出帧持续更新且task数量符合预期即正常；状态停在旧帧通常表示暂停、same-frame、zero-substep或任务筛选未命中。",
        "无MC2物理参数；只受上游物理世界、MC2模拟步是否启用以及时间推进影响。",
        "切换world、删除slot、停止时间推进、编译失败或world dispose会让快照消失或停止更新。",
    )),
    ("任务筛选", _mc2_debug_help(
        "只观察指定task id，避免多个布料叠画。MeshCloth、BoneCloth、BoneSpring任务节点的“任务名称”可直接连接。",
        "空值=全部；多个id用换行或逗号分隔；状态输出会明确列出实际命中的task。",
        "命中数量与预期一致即正常；视口完全为空且状态显示等待时先检查task id，而不是先怀疑solver。",
        "仅本节点“任务筛选”，不改变任何Profile/Task参数或模拟结果。",
        "task改名、对象重建导致task id变化、筛选拼写不完整都会改变命中范围。",
    )),
    ("最大显示项", _mc2_debug_help(
        "限制每一种绘制图元的可见数量，保护viewport；默认10000、上限100000。",
        "只截断绘制，不截断solver数据；状态输出中的总数/触发数来自完整冻结快照，不受此值影响。",
        "画面过密时降低，断开组件缺失时提高；碰撞形状会按final proxy连通分量公平分配预算。",
        "仅本节点“最大显示项”。",
        "模型粒子、边、候选或接触数量增加会更早碰到显示上限，但不会改变模拟。",
    )),
    ("拓扑连接", _mc2_debug_help(
        "高级结构诊断：显示solver真正使用的去重final proxy edge，不是约束触发视图。",
        "MeshCloth统一橙色；BoneCloth纵向橙、横向青；蓝色只表示triangle引用了final edge表中不存在的异常边。",
        "边连续、无孤立异常蓝边即正常；线多只说明拓扑密，不代表约束正在工作。",
        "没有直接Profile参数；由源Mesh边/三角形、Mesh固定组、Bone链与Bone连接模式决定。",
        "改拓扑、固定边界、Bone连接关系或重建proxy会改变它；运行时重力/碰撞不会改变static拓扑。",
    )),
    ("Fixed/Move", _mc2_debug_help(
        "高级属性诊断：确认哪些最终粒子固定、哪些允许solver移动。",
        "红点=Fixed，绿点=Move；状态输出给出两类精确数量。这不是本帧触发状态。",
        "固定边界与预期一致、没有意外整片Fixed或Move即正常。",
        "Mesh由对象的Pin启用/Pin顶点组及proxy属性决定；Bone由链根和连接构建决定，没有独立Profile开关。",
        "改Pin组、源拓扑、Bone根或连接模式会改变属性；力和碰撞只移动Move，不会把属性临时改类。",
    )),
    ("粒子深度", _mc2_debug_help(
        "高级参数采样诊断：显示生产baseline depth、root和parent异常；它不是Tether长度或当前变形量。",
        "蓝0近根到橙1远端；粉=Fixed，紫=无根Move，黄=ZeroDistance，白=跨root，橙线=局部突跳，纯红=非法parent/root/逆序。",
        "同一root内沿parent单调、无紫色无根和纯红异常即正常；横向色带应符合产品需要，但不要求等于旧MC2源码。",
        "没有直接公开depth参数；Mesh使用parent链depth与Fixed边界表面距离4:1混合。它会被阻尼曲线、半径曲线、距离刚度曲线、角度曲线、Motion曲线和Depth惯性消费。",
        "源拓扑、Fixed分布、parent/root构建和非均匀减面会改变depth；当前粒子运动不会改变static depth。",
    )),
    ("深度粒子索引", _mc2_debug_help(
        "在“粒子深度”中只高亮一个粒子的真实parent路径，便于追查异常。",
        "-1不选中；有效索引用紫色显示该粒子到root的路径。",
        "路径无循环、最终到达预期Fixed root即正常。",
        "仅本节点“深度粒子索引”，不修改任何模拟参数。",
        "改索引只改变诊断高亮；拓扑或root重建会改变同一索引对应路径。",
    )),
    ("StepBasic参考姿态", _mc2_debug_help(
        "高级参考姿态诊断：显示结构约束使用的基准位置；不是当前粒子、Motion BasePosition或Tether引导线。",
        "淡蓝边连接StepBasic位置，表示Distance、Angle和Bone输出的结构参考。",
        "参考形状稳定且与预期初始/动画混合姿态一致即正常。",
        "动画姿态比例(animation_pose_ratio)直接影响参考；组件scale、static baseline与当前动画输入也参与。",
        "改动画、重建baseline、Teleport/Reset重定基或拓扑重建会改变它。",
    )),
    ("有效重力", _mc2_debug_help(
        "回答每个Move粒子本substep实际收到的重力输入，而不是从最终位移猜受力。",
        "灰箭头=重力方向×重力强度×组件scale的原始量；绿箭头=再乘当前gravity ratio后的有效量；状态输出给出两种强度。",
        "方向符合世界设置、绿色不大于预期原始量即正常；BoneSpring强制重力为0时不画。",
        "重力方向(gravity_direction)、重力强度(gravity)、重力衰减(gravity_falloff)；组件scale和Center姿态会影响gravity ratio。",
        "对象/Anchor旋转、组件scale、重力参数和setup类型会改变它；碰撞或约束不会反向改写重力输入。",
    )),
    ("粒子速度", _mc2_debug_help(
        "比较下一步积分会使用的保存速度与本步真实位移速度，并检查是否被限速。",
        "青=保存速度，橙=真实位移速度，黄=两者差，红=保存速度命中粒子限速；状态输出报告命中数和最大速度。",
        "少量差值是约束/碰撞修正后的正常结果；持续大量红线或静止模型仍有大速度才需要检查。",
        "粒子限速(particle_speed_limit)、阻尼(damping)、阻尼曲线(damping_curve)、重力参数、模拟频率与时间缩放直接影响速度。",
        "动画/Anchor/Center惯性、Distance/Tether/Bending/Angle/Motion修正、外碰、自碰和Teleport都会改变真实位移或保存速度。",
    )),
    ("Distance误差", _mc2_debug_help(
        "判断相邻proxy边是否偏离其有效rest，以及Distance A/B两次真实修正了多少。",
        "蓝=压缩，红=拉伸；真正的修正箭头来自本步两个有序pass。状态输出分开统计压缩/拉伸的接近数和触发数。",
        "未触发表示都在容许/刚度结果内；动态布料少量触发正常，长期整片同方向高触发通常表示刚度、参考姿态或外力不合适。",
        "距离刚度(distance_stiffness)、距离刚度曲线(distance_stiffness_curve)、动画姿态比例(animation_pose_ratio)、组件scale。BoneSpring距离刚度固定。",
        "重力、Center惯性、动画、碰撞、Tether、Bending、Angle和Motion都可能先改变边长而触发Distance。",
    )),
    ("Tether状态", _mc2_debug_help(
        "限制每个Move粒子离自己的baseline root不能过近或过远。baseline root只决定配对；rest是StepBasic粒子与root两点的世界空间直线距离，不是parent链累计长度，也不是depth。",
        "低饱和灰线=哪个root拴住哪个Move粒子，只表达牵引关系，不表达严重程度；浅蓝小点=接近压缩下界，深蓝点+箭头=本步压缩触发；浅橙小点=接近拉伸上界，深橙点+箭头=本步拉伸触发。没有范围圈；状态输出给出记录/接近/触发精确数量。",
        "完全不画=都远离边界；只有小点=接近但未修正；带箭头=本步实际越界并被推回。动态布料少量触发正常，持续大面积触发才需要检查。",
        "Tether压缩(tether_compression)决定最短距离rest×(1-值)；最长距离固定为rest×1.03，没有公开Tether刚度。BoneSpring压缩固定0.8、拉伸仍固定3%。",
        "重力、Center/Anchor惯性、动画、Teleport后的运动、外碰、自碰，以及Tether之前的积分都可能把粒子推过界；后续Distance/Bending/Motion不会造成当前这一次Tether触发，因为本substep顺序中Tether先执行。",
    )),
    ("Bending约束", _mc2_debug_help(
        "判断相邻三角形的弯折/体积记录是否偏离baseline，并显示本步各quad角色的真实修正。",
        "紫=二面角项，青=体积项；实际修正箭头表示本步触发。状态输出报告总记录、二面角/体积数量和触发数。",
        "平直或保持原形时触发应少；折叠、剧烈碰撞时局部触发正常，静止时全片持续触发需检查拓扑或刚度。",
        "弯曲刚度(bending_stiffness)直接控制修正，0关闭；组件scale、负缩放和baseline quad/rest参与。",
        "重力、动画、惯性、Distance/Angle造成的折弯、外碰、自碰和异常三角拓扑都可能触发。",
    )),
    ("Motion BasePosition", _mc2_debug_help(
        "高级参考诊断：显示MaxDistance与Backstop实际使用的动画基准位置和法线轴。",
        "青点/轴是冻结native animated base，不是当前粒子、StepBasic或最终输出；此模式不报告触发。",
        "基准跟随预期动画且法线朝向正确即正常。",
        "Normal Axis(normal_axis)决定Backstop轴；动画输入、对象/骨骼变换和Teleport/Reset重定基决定BasePosition。",
        "动画、负缩放、Normal Axis、setup写入方式和重定基会改变它；物理碰撞不会改写动画基准。",
    )),
    ("Motion约束", _mc2_debug_help(
        "回答粒子是否越过MaxDistance外边界或进入Backstop禁入球，以及本步实际修正。",
        "状态输出分开报告MaxDistance和Backstop的记录、接近和触发数；视口只应把接近/触发区域突出。",
        "未启用的分支不应出现；少量局部触发正常，整片持续触发通常表示动画基准、范围或Motion刚度不合适。",
        "最大距离(max_distance_enabled/max_distance/max_distance_curve)、Backstop(backstop_enabled/backstop_radius/backstop_distance/backstop_distance_curve)、Motion刚度(motion_stiffness)、Normal Axis(normal_axis)。BoneSpring强制关闭MaxDistance/Backstop。",
        "动画/BasePosition移动、重力、Center惯性、所有前序结构约束、外碰和自碰都可能把粒子推到Motion边界。",
    )),
    ("Angle恢复目标", _mc2_debug_help(
        "让父子方向回到StepBasic参考方向，并显示三轮交错迭代中Restoration实际修正。",
        "只显示接近或触发的粒子：低饱和粉线指向恢复目标，浅粉小点=接近，亮粉大点+红箭头=本步真实触发。状态输出报告记录、接近和触发数。",
        "自然摆动时局部触发正常；禁用或刚度为0时不应有修正，静止时高频全链触发需检查目标或刚度。",
        "角度恢复(angle_restoration_enabled)、恢复刚度/曲线(angle_restoration_stiffness/angle_restoration_curve)、恢复速度衰减(angle_restoration_velocity_attenuation)、恢复重力衰减(angle_restoration_gravity_falloff)、动画姿态比例(animation_pose_ratio)。",
        "动画、重力、Center惯性、碰撞、Distance/Bending和父粒子运动都可能使当前方向偏离恢复目标。",
    )),
    ("Angle限制范围", _mc2_debug_help(
        "限制父子方向相对层级目标的最大夹角，防止链条过度折叠。",
        "只为接近或触发的粒子显示局部低亮度黄锥：黄色小点=接近，橙色大点+红箭头=三轮迭代中的真实Limit触发。状态输出报告接近和触发数。",
        "角度在锥内不触发；碰撞或快速运动时局部触发正常，长时间卡在边界需检查上限和刚度。",
        "角度限制(angle_limit_enabled)、限制角度/曲线(angle_limit/angle_limit_curve)、限制刚度(angle_limit_stiffness)、baseline父旋转层级。",
        "父子动画、重力、Center惯性、Distance/Bending、外碰、自碰和Angle Restoration交错迭代都可能把角度推到上限。",
    )),
    ("Center", _mc2_debug_help(
        "解释组件/Anchor运动如何被拆成实际施加给粒子的惯性位移与旋转。",
        "状态输出先报告帧惯性最终位移、fixed-step有效惯性、对象/Anchor/平滑/World各来源贡献和限速结果；视口分层向量只用于随后审计来源。",
        "最终shift等于各实际层组合且限速只在高速运动时出现即正常；静止仍有大shift需检查Anchor或帧连续性。",
        "Anchor惯性(anchor_inertia)、World惯性(world_inertia)、惯性平滑(movement_inertia_smoothing)、移动/旋转限速(movement_speed_limit/rotation_speed_limit)、Local惯性及其限速(local_inertia/local_movement_speed_limit/local_rotation_speed_limit)、Depth惯性(depth_inertia)。",
        "对象与Anchor平移/旋转、负缩放、跳帧/倒放、Reset/Keep Teleport和帧连续性会改变Center状态。",
    )),
    ("Teleport阈值与方向", _mc2_debug_help(
        "检查task唯一Teleport判定基准的实测位移/旋转和阈值；基准是首个Fixed，无Fixed时是对象原点。",
        "旧到新基准的方向、距离阈值球和旋转阈值弧是判定输入，不是粒子范围或速度。状态输出给出当前阈值。",
        "普通连续动画应低于阈值；超过任一阈值会按模式对整个task处理。",
        "Teleport模式(teleport_mode)、Teleport距离(teleport_distance)、Teleport旋转(teleport_rotation)。",
        "首个Fixed或对象原点的帧间平移/旋转、跳帧、瞬移和重定父级会触发；非基准粒子局部运动不会触发。",
    )),
    ("Teleport触发状态", _mc2_debug_help(
        "直接显示本帧task级Teleport结果及真实测量方向。",
        "绿=None/未触发，黄=Keep，红=Reset；位移箭头和旋转弧表示判定输入，不是粒子速度。状态输出明确结果。",
        "连续运动保持绿色；明确瞬移时出现预设的Keep或Reset即正常，不能只有部分粒子触发。",
        "Teleport模式、Teleport距离、Teleport旋转；基准选择由首个Fixed/对象原点规则决定。",
        "基准平移或旋转超过任一阈值触发；Keep保留并旋转已有物理速度，Reset回到当帧动画姿态并清速度。",
    )),
    ("碰撞情况", _mc2_debug_help(
        "高级范围诊断：显示哪些粒子/边和外部collider具备参与外碰的资格；不是实际命中。",
        "Point=绿色真实半径球，Edge=橙色变半径胶囊，蓝色=通过source、group/mask和setup过滤的外部collider。",
        "预期对象和碰撞体都出现、Ignore/组过滤对象不出现即正常；形状重叠也不等于本帧一定接触。",
        "碰撞模式(collision_mode)、粒子半径/曲线(radius/radius_curve)、对象radius权重、碰撞组/mask、collider形状/半径；BoneSpring使用固定Point模式。",
        "改Profile、对象顶点组、collider设置、group/mask、source归属或final proxy会改变资格集合。",
    )),
    ("实际接触", _mc2_debug_help(
        "只回答本帧哪里真的发生外碰或跨task排斥，不重复全部候选形状。",
        "命中的真实半径球/胶囊和对应collider高亮；白点=kernel接触位置，黄=新增，灰=刚失效；黄色箭头把真实推动固定放大8倍。状态输出报告当前/新增/持续/失效和跨task启用数。",
        "少量稳定接触正常；无几何接近却大量新增/失效、或静止时高churn需要检查半径、过滤和运动连续性。箭头放大只为可见，不改变方向和相对强度。",
        "碰撞模式、粒子半径/曲线、对象radius权重、碰撞摩擦(collision_friction)、group/mask和collider形状；BoneSpring还受碰撞限制距离/曲线(collision_limit_distance/collision_limit_curve)。跨task分配受自碰交互质量(cloth_mass)影响。",
        "粒子与collider重叠/扫掠、动画或Center运动、重力/约束把粒子推入collider、两个启用interaction的task相互接近都可能触发。",
    )),
    ("粒子半径", _mc2_debug_help(
        "高级参数诊断：显示生产路径实际外碰半径，不表示本帧命中。",
        "每个线框球是该粒子的最终半径；状态与触发数量请看“实际接触”。",
        "半径沿depth/权重变化符合配置且无零值异常即正常。",
        "粒子半径(radius)、半径曲线(radius_curve)、baseline depth、对象radius顶点组权重和组件scale。",
        "改Profile曲线、depth、对象权重、scale或重建proxy会改变半径；接触本身不会改半径。",
    )),
    ("自碰1 几何单元", _mc2_debug_help(
        "高级结构诊断：显示真正注册进self检测的Point/Edge/Triangle primitive，不是接触。",
        "紫点、边和三角轮廓代表检测几何；状态输出不把它们计作触发。",
        "需要自碰的区域完整、Fixed/Ignore过滤符合预期即正常。",
        "自碰撞(self_collision_enabled)、跨物体自碰撞(self_collision_interaction)、粒子属性、final proxy；self厚度由粒子半径按0.25派生。",
        "改自碰开关、拓扑、粒子属性、半径模型或proxy会改变primitive。",
    )),
    ("自碰2 空间网格", _mc2_debug_help(
        "高级性能诊断：显示self broadphase分桶，不是接触或修正。",
        "灰格只表示primitive占用；格多和重叠多说明候选成本可能升高。",
        "网格覆盖几何且尺度与self半径相称即正常；极端密集格需要结合候选数判断性能。",
        "自碰开关、派生self厚度(粒子半径×0.25)、primitive范围和内部grid size；无单独公开网格参数。",
        "粒子运动、半径、拓扑密度和跨task interaction范围会改变占用。",
    )),
    ("自碰3 候选配对", _mc2_debug_help(
        "高级性能诊断：显示宽相认为值得进入窄相的primitive pair；候选允许false positive。",
        "黄色线=候选，不代表接触、穿插或推动；真实结果看“自碰4”。",
        "候选集中在几何接近区域正常；远距离大量候选或数量随密度失控需要检查grid和半径。",
        "自碰开关、派生self厚度、primitive/grid；无公开候选阈值参数。",
        "粒子相互接近、拓扑密度、self半径、网格占用和跨task范围都会增加候选。",
    )),
    ("自碰4 接触结果", _mc2_debug_help(
        "显示最终self contact的真实推动，以及final线段-三角形几何穿插；这是自碰一级结果视图。",
        "淡红=持续contact，橙=新增，灰=刚失效；两侧黄箭头把真实累计推动固定放大8倍。洋红=持续穿插，亮粉=新增，暗紫=失效。状态输出分开报告contact与穿插的当前/新增/失效。",
        "真实拥挤或双层接近时稳定contact正常；干净单层应收敛且final穿插为0。持续高churn、无几何接近的contact或静止仍有推动需要检查。穿插按同相位的前两帧比较，不把奇偶扫描误报成churn。",
        "自碰撞、跨物体自碰撞、粒子半径/曲线与派生self厚度(×0.25)、对象radius权重；跨task双方修正比例受自碰交互质量(cloth_mass)影响。",
        "布料折叠、层间距离小于厚度、外碰/动画/重力/约束把不同primitive推近、跨task靠近或真正几何穿越都会触发。",
    )),
    ("最终输出偏移", _mc2_debug_help(
        "确认solver最终准备写回Blender的结果，而不是某个中间约束。",
        "Mesh显示base到最终world位置及object-local offset；Bone只显示允许平移的target。状态输出报告记录数和允许平移写回数。",
        "偏移方向与最终可见运动一致、connected rotation-only骨不伪造平移即正常。",
        "混合权重(blend_weight)、setup写回规则以及所有最终粒子状态；没有单独debug参数。",
        "重力、惯性、全部约束、碰撞、Teleport和writeback eligibility共同决定最终输出。",
    )),
)


def _mc2_debug_long_description() -> str:
    introduction = (
        "从冻结的native快照绘制MC2真实中间态。大多数模式在登记后等待下一次真实substep捕获；"
        "same-frame不会立即读取，未推进时可继续看到旧快照。Teleport属于scheduler前新帧状态。"
        "所有开关均为按需readback，关闭debug不生产额外明细。"
        "调试状态输出是上一份冻结快照的用户摘要，可接到调试文本/打印节点；它不修改模拟。"
        "推荐调参顺序：先看调试状态，再只打开一个结果视图（实际接触、自碰4、Tether、Distance或Motion），"
        "最后才打开拓扑、StepBasic、深度、空间网格和候选等高级审计视图。默认关闭的高级开关不会隐藏错误，"
        "只是不让中间线先盖住结果。"
    )
    return introduction + "\n\n" + "\n\n".join(
        f"{label}：{description}" for label, description in _MC2_DEBUG_DESCRIPTION_ITEMS
    )


@omni(
    enable=True,
    always_run=True,
    bl_label="MC2可视化调试",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=[
        "物理世界", "任务筛选", "最大显示项", "拓扑连接", "Fixed/Move", "粒子深度", "深度粒子索引",
        "StepBasic参考姿态", "有效重力", "粒子速度", "Distance误差", "Tether状态",
        "Bending约束", "Motion BasePosition", "Motion约束",
        "Angle恢复目标", "Angle限制范围", "Center", "Teleport阈值与方向",
        "Teleport触发状态", "碰撞情况", "实际接触", "粒子半径",
        "自碰1 几何单元", "自碰2 空间网格", "自碰3 候选配对",
        "自碰4 接触结果", "最终输出偏移",
    ],
    input_init={
        "world": {"description": "MC2物理世界；状态见输出。"},
        "show_topology": {"description": "高级：低亮度拓扑连接（默认关闭）。"},
        "show_attributes": {"description": "显示Fixed/Move等粒子属性。"},
        "show_depth": {"description": "蓝=近根 橙=远端\n红=非法 粉=Fixed"},
        "depth_particle_index": {
            "min_value": -1,
            "max_value": 1000000,
            "description": "-1关闭；指定粒子显示完整parent路径",
        },
        "show_step_basic": {"description": "高级审计：结构参考姿态；不同于Motion基准。"},
        "show_gravity": {"description": "灰=未衰减 绿=有效重力\n每个Move粒子一组"},
        "show_velocity": {"description": "青=保存 橙=真实 黄=差值\n红=命中粒子限速"},
        "show_distance": {"description": "Distance：绿=正常 红=拉长 蓝=压缩"},
        "show_tether": {"description": "Tether：灰=栓绳关系 蓝=压缩 黄=拉伸"},
        "show_bending": {"description": "Bending：仅突出触发项\n紫=角度 青=体积 红箭头=修正"},
        "show_motion_base": {"description": "高级参考：Motion实际BasePosition/法线轴。"},
        "show_motion": {"description": "结果视图：蓝=MaxDistance 橙=Backstop\n小点=接近 大点+箭头=触发"},
        "show_angle_restoration": {"description": "结果视图：粉点=接近/触发\n低亮度线=恢复目标 红箭头=修正"},
        "show_angle_limit": {"description": "结果视图：黄点=接近 橙点=触发\n低亮度锥=局部范围 红箭头=修正"},
        "show_center": {"description": "状态先看最终惯性与来源；视口为高级分层审计。"},
        "show_teleport_threshold": {
            "description": "Teleport阈值与方向\n球=阈值  线=旧到新"
        },
        "show_teleport_status": {
            "description": "位移/旋转线：绿=None\n黄=Keep 红=Reset"
        },
        "show_collision": {"description": "高级范围：绿Point 橙Edge 蓝外部体；非命中。"},
        "show_collision_contacts": {
            "description": "命中球/胶囊+碰撞体\n白=接触 黄=推动×8"
        },
        "show_radii": {"description": "全部粒子半径（仅参数审计）。"},
        "show_self_primitives": {"description": "自碰1：紫=实际点/边/三角形"},
        "show_self_grid": {"description": "自碰2：灰=空间网格占用"},
        "show_self_candidates": {"description": "自碰3：黄=宽相候选（非接触）"},
        "show_self_contacts": {"description": "自碰4：红=持续 橙=新增\n灰=失效 紫=穿插"},
        "show_output": {"description": "高级结果：显示实际写回的最终输出偏移。"},
        "task_filter": {"description": "任务名/task id。\n换行/逗号分隔，空=全部。"},
        "max_items": {"min_value": 1, "max_value": 100000, "description": "每种可视化最多绘制的项目数。"},
    },
    _OUTPUT_NAME=["物理世界", "调试状态"],
    mute_passthrough={"_OUTPUT0": "world"},
    omni_description=_mc2_debug_long_description(),
)
def physicsMC2DebugDraw(
    world: PhysicsWorldCache,
    task_filter: str = "",
    max_items: int = 10000,
    show_topology: bool = False,
    show_attributes: bool = True,
    show_depth: bool = False,
    depth_particle_index: int = -1,
    show_step_basic: bool = False,
    show_gravity: bool = False,
    show_velocity: bool = False,
    show_distance: bool = False,
    show_tether: bool = False,
    show_bending: bool = False,
    show_motion_base: bool = False,
    show_motion: bool = False,
    show_angle_restoration: bool = False,
    show_angle_limit: bool = False,
    show_center: bool = False,
    show_teleport_threshold: bool = False,
    show_teleport_status: bool = False,
    show_collision: bool = False,
    show_collision_contacts: bool = False,
    show_radii: bool = False,
    show_self_primitives: bool = False,
    show_self_grid: bool = False,
    show_self_candidates: bool = False,
    show_self_contacts: bool = True,
    show_output: bool = False,
) -> tuple[PhysicsWorldCache, str]:
    status_text = update_mc2_debug_draw_store(
        str(id(world)),
        world,
        True,
        show_topology=show_topology,
        show_attributes=show_attributes,
        show_depth=show_depth,
        depth_particle_index=depth_particle_index,
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
        show_collision_contacts=show_collision_contacts,
        show_radii=show_radii,
        show_self_primitives=show_self_primitives,
        show_self_grid=show_self_grid,
        show_self_candidates=show_self_candidates,
        show_self_contacts=show_self_contacts,
        show_output=show_output,
        task_filter=task_filter,
        max_items=max_items,
    )
    return world, status_text
