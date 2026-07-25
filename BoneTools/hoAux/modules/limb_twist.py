"""Upper-arm and forearm Twist modules from the research armature."""

from dataclasses import dataclass
from math import pow, radians
from uuid import uuid4

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.types import PropertyGroup
from mathutils import Quaternion, Vector

from ..collection_registry import assign_bone
from ..generation import (
    add_copy_rotation,
    add_stretch_to,
    create_edit_bone,
    write_bone_metadata,
)
from ..module_base import ModuleDefinition, preview_toggle, refresh_preview
from ..module_spec import PlannedBone
from ..name_registry import allocate_bone_name, iter_hoaux_bones
from ..properties import ensure_rig_id
from ..transaction import GenerationTransaction


def _settings_annotations(module_type):
    return {
        "ui_expanded": BoolProperty(name="扭转设置", default=False),
        "preview_enabled": BoolProperty(
            name="预览", default=False, update=preview_toggle(module_type)
        ),
        "segment_count": IntProperty(
            name="分段数", default=3, min=1, max=12, update=refresh_preview
        ),
        "distribution_exponent": FloatProperty(
            name="分布曲线", default=1.0, min=0.05, max=8.0, update=refresh_preview
        ),
        "influence_start": FloatProperty(
            name="起始旋转影响", default=0.1, min=-2.0, max=2.0
        ),
        "influence_end": FloatProperty(
            name="末端旋转影响", default=0.8, min=-2.0, max=2.0
        ),
        "influence_exponent": FloatProperty(
            name="旋转影响曲线", default=1.0, min=0.05, max=8.0
        ),
        "roll_offset": FloatProperty(
            name="骨骼扭转偏移", default=0.0, min=-180.0, max=180.0, update=refresh_preview
        ),
        "stretch_influence": FloatProperty(
            name="拉伸影响", default=1.0, min=0.0, max=1.0, subtype="FACTOR"
        ),
        "target_head_tail": FloatProperty(
            name="目标位置", default=0.0, min=0.0, max=1.0, subtype="FACTOR", update=refresh_preview
        ),
        "volume": EnumProperty(
            name="体积保持",
            items=(
                ("NO_VOLUME", "不保持", "不保持体积"),
                ("VOLUME_XZX", "X与Z", "在X与Z轴上平均保持体积"),
                ("VOLUME_X", "X轴", "在X轴上保持体积"),
                ("VOLUME_Z", "Z轴", "在Z轴上保持体积"),
            ),
            default="NO_VOLUME",
        ),
        "keep_axis": EnumProperty(
            name="旋转方式",
            items=(
                ("SWING_Y", "摆动Y", "绕Y轴摆动"),
                ("PLANE_X", "X平面", "保持在X平面内旋转"),
                ("PLANE_Z", "Z平面", "保持在Z平面内旋转"),
            ),
            default="SWING_Y",
        ),
        "bulge": FloatProperty(name="膨胀", default=1.0, min=0.0, max=100.0),
        "use_bulge_min": BoolProperty(name="限制最小膨胀", default=False),
        "use_bulge_max": BoolProperty(name="限制最大膨胀", default=False),
        "bulge_min": FloatProperty(name="最小值", default=1.0, min=0.0, max=100.0),
        "bulge_max": FloatProperty(name="最大值", default=1.0, min=0.0, max=100.0),
        "bulge_smooth": FloatProperty(
            name="膨胀平滑", default=0.0, min=0.0, max=1.0, subtype="FACTOR"
        ),
    }


def _settings_class(name, module_type):
    return type(
        name,
        (PropertyGroup,),
        {"__module__": __name__, "__annotations__": _settings_annotations(module_type)},
    )


PG_HoAuxForearmTwistSettings = _settings_class(
    "PG_HoAuxForearmTwistSettings", "FOREARM_TWIST"
)
PG_HoAuxUpperArmTwistSettings = _settings_class(
    "PG_HoAuxUpperArmTwistSettings", "UPPER_ARM_TWIST"
)


@dataclass(frozen=True)
class Parameters:
    segment_count: int = 3
    distribution_exponent: float = 1.0
    influence_start: float = 0.1
    influence_end: float = 0.8
    influence_exponent: float = 1.0
    roll_offset_degrees: float = 0.0
    stretch_influence: float = 1.0
    target_head_tail: float = 0.0
    volume: str = "NO_VOLUME"
    keep_axis: str = "SWING_Y"
    bulge: float = 1.0
    use_bulge_min: bool = False
    use_bulge_max: bool = False
    bulge_min: float = 1.0
    bulge_max: float = 1.0
    bulge_smooth: float = 0.0


@dataclass(frozen=True)
class TwistConfig:
    module_type: str
    label: str
    order: int
    settings_attr: str
    settings_class: type
    main_role: str
    main_label: str
    target_role: str
    target_label: str
    part: str


FOREARM_CONFIG = TwistConfig(
    module_type="FOREARM_TWIST",
    label="小臂扭转",
    order=30,
    settings_attr="hoaux_forearm_twist_settings",
    settings_class=PG_HoAuxForearmTwistSettings,
    main_role="lowerArmBone",
    main_label="小臂骨",
    target_role="handBone",
    target_label="手骨",
    part="LowerArm",
)
UPPER_ARM_CONFIG = TwistConfig(
    module_type="UPPER_ARM_TWIST",
    label="大臂扭转",
    order=60,
    settings_attr="hoaux_upper_arm_twist_settings",
    settings_class=PG_HoAuxUpperArmTwistSettings,
    main_role="upperArmBone",
    main_label="大臂骨",
    target_role="lowerArmBone",
    target_label="小臂骨",
    part="UpperArm",
)


def parameters_from_settings(settings):
    return Parameters(
        segment_count=settings.segment_count,
        distribution_exponent=settings.distribution_exponent,
        influence_start=settings.influence_start,
        influence_end=settings.influence_end,
        influence_exponent=settings.influence_exponent,
        roll_offset_degrees=settings.roll_offset,
        stretch_influence=settings.stretch_influence,
        target_head_tail=settings.target_head_tail,
        volume=settings.volume,
        keep_axis=settings.keep_axis,
        bulge=settings.bulge,
        use_bulge_min=settings.use_bulge_min,
        use_bulge_max=settings.use_bulge_max,
        bulge_min=settings.bulge_min,
        bulge_max=settings.bulge_max,
        bulge_smooth=settings.bulge_smooth,
    )


def _module_id(config, side):
    return f"{config.module_type}.{side}"


def validate_roles(armature_object, main_name, target_name, config, side):
    if armature_object is None or armature_object.type != "ARMATURE":
        raise ValueError("请选择骨架")
    armature_data = armature_object.data
    main = armature_data.bones.get(main_name)
    target = armature_data.bones.get(target_name)
    if main is None or target is None:
        raise ValueError(f"请设置 {config.main_label} 和 {config.target_label} 主骨")
    if target.parent != main:
        raise ValueError(f"{config.target_label} 必须直接以 {config.main_label} 为父级")
    if main.length <= 1e-8:
        raise ValueError(f"{config.main_label} 骨长无效")
    if any(
        bone.hotools_boneprops.hoAux.moduleId == _module_id(config, side)
        for bone in iter_hoaux_bones(armature_data)
    ):
        raise ValueError(f"{_module_id(config, side)} 已存在")
    return main, target


def _influence(index, count, parameters):
    if count <= 1:
        return parameters.influence_end
    factor = pow(index / (count - 1), parameters.influence_exponent)
    return parameters.influence_start + (
        parameters.influence_end - parameters.influence_start
    ) * factor


def build_plan(
    armature_object,
    main_name,
    target_name,
    config,
    side,
    parameters=None,
):
    main, _target = validate_roles(
        armature_object, main_name, target_name, config, side
    )
    parameters = parameters or Parameters()
    count = parameters.segment_count
    main_vector = main.tail_local - main.head_local
    direction = main_vector.normalized()
    roll_reference = main.matrix_local.to_3x3() @ Vector((0.0, 0.0, 1.0))
    if abs(parameters.roll_offset_degrees) > 1e-8:
        roll_reference = Quaternion(
            direction, radians(parameters.roll_offset_degrees)
        ) @ roll_reference
    padding = max(2, len(str(count)))
    plans = []
    for index in range(count):
        start = pow(index / count, parameters.distribution_exponent)
        end = pow((index + 1) / count, parameters.distribution_exponent)
        marker = str(count - index).zfill(padding)
        head = main.head_local.lerp(main.tail_local, start)
        segment_tail = main.head_local.lerp(main.tail_local, end)
        tail = segment_tail
        plans.append(
            PlannedBone(
                resource_key=(
                    f"ARM.{side}.{config.module_type}.DEF.{marker}"
                ),
                preferred_name=f"DEF_{config.part}_Twist_{marker}_{side}",
                role_tag="DEF",
                marker=marker,
                head=head,
                tail=tail,
                roll_reference=roll_reference,
                parent_name=main.name,
            )
        )
    return plans


def generate(
    armature_object,
    main_name,
    target_name,
    config,
    side,
    parameters=None,
):
    parameters = parameters or Parameters()
    plans = build_plan(
        armature_object, main_name, target_name, config, side, parameters
    )
    armature_data = armature_object.data
    target_bone = armature_data.bones[target_name]
    target_point = target_bone.head_local.lerp(
        target_bone.tail_local, parameters.target_head_tail
    )
    rig_id = ensure_rig_id(armature_data)
    generation_id = uuid4().hex
    pipeline_id = f"ARM.{side}"
    module_id = _module_id(config, side)
    actual_names = {
        plan.resource_key: allocate_bone_name(armature_data, plan.preferred_name)
        for plan in plans
    }

    with GenerationTransaction(armature_object) as transaction:
        bpy.context.view_layer.objects.active = armature_object
        armature_object.select_set(True)
        if armature_object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            edit_bones = armature_data.edit_bones
            for plan in plans:
                actual_name = actual_names[plan.resource_key]
                create_edit_bone(edit_bones, plan, actual_name)
                transaction.track_bone(actual_name)
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")

        for plan in plans:
            actual_name = actual_names[plan.resource_key]
            bone = armature_data.bones[actual_name]
            write_bone_metadata(
                bone,
                rig_id=rig_id,
                pipeline_id=pipeline_id,
                module_id=module_id,
                module_type=config.module_type,
                generation_id=generation_id,
                role_tag="DEF",
                part=config.part,
                function="Twist",
                marker=plan.marker,
                side=side,
                name_key=plan.resource_key,
            )
            assign_bone(armature_data, bone)

        for index, plan in enumerate(plans):
            actual_name = actual_names[plan.resource_key]
            pose_bone = armature_object.pose.bones[actual_name]
            add_copy_rotation(
                pose_bone,
                armature_object,
                target_name,
                transaction,
                name="HoAux Twist Copy Rotation",
                influence=_influence(index, len(plans), parameters),
            )
            add_stretch_to(
                pose_bone,
                armature_object,
                target_name,
                transaction,
                name="HoAux Twist Stretch To",
                head_tail=parameters.target_head_tail,
                rest_length=(target_point - plan.head).length,
                influence=parameters.stretch_influence,
                volume=parameters.volume,
                keep_axis=parameters.keep_axis,
                bulge=parameters.bulge,
                use_bulge_min=parameters.use_bulge_min,
                use_bulge_max=parameters.use_bulge_max,
                bulge_min=parameters.bulge_min,
                bulge_max=parameters.bulge_max,
                bulge_smooth=parameters.bulge_smooth,
            )

        transaction.commit()
    return {
        "dir": "",
        "bones": [actual_names[plan.resource_key] for plan in plans],
        "createdDir": False,
        "generationId": generation_id,
    }


class TwistDefinition(ModuleDefinition):
    parameter_rows = (
        ("segment_count", "distribution_exponent"),
        ("influence_start", "influence_end"),
        ("influence_exponent",),
        ("roll_offset", "stretch_influence"),
        ("target_head_tail",),
        ("volume", "keep_axis"),
        ("bulge", "bulge_smooth"),
        ("use_bulge_min", "bulge_min"),
        ("use_bulge_max", "bulge_max"),
    )

    def __init__(self, config):
        self.config = config
        self.type_id = config.module_type
        self.label = config.label
        self.order = config.order
        self.settings_class = config.settings_class
        self.settings_attr = config.settings_attr
        self.required_roles = (
            (config.main_role, config.main_label),
            (config.target_role, config.target_label),
        )

    def generate_from_context(self, context):
        root = context.scene.hoaux_settings
        return generate(
            context.object,
            getattr(root, self.config.main_role),
            getattr(root, self.config.target_role),
            self.config,
            root.side,
            parameters_from_settings(self.settings(context.scene)),
        )

    def build_preview_scene(self, context):
        from ..preview_draw import LineStyle, PreviewScene, ROLE_LINE_STYLES

        root = context.scene.hoaux_settings
        obj = context.object
        main_name = getattr(root, self.config.main_role)
        target_name = getattr(root, self.config.target_role)
        parameters = parameters_from_settings(self.settings(context.scene))
        plans = build_plan(
            obj,
            main_name,
            target_name,
            self.config,
            root.side,
            parameters,
        )
        main = obj.data.bones[main_name]
        direction = (main.tail_local - main.head_local).normalized()
        ring_style = LineStyle((0.2, 0.9, 1.0, 0.95), 2.0)
        scene = PreviewScene(obj.name, title=self.label)
        scene.add_segment(main.head_local, main.tail_local, ROLE_LINE_STYLES["GUIDE"])
        for index, plan in enumerate(plans):
            scene.add_segment(plan.head, plan.tail, ROLE_LINE_STYLES["DEF"])
            scene.add_circle(
                plan.head,
                direction,
                main.length * 0.08,
                ring_style,
            )
            scene.add_point(plan.head)
            scene.add_label(
                plan.head,
                f"{plan.preferred_name}  {_influence(index, len(plans), parameters):.2f}",
            )
        return scene


FOREARM_DEFINITION = TwistDefinition(FOREARM_CONFIG)
UPPER_ARM_DEFINITION = TwistDefinition(UPPER_ARM_CONFIG)
