"""Upper-arm and forearm Twist modules from the research armature."""

from dataclasses import dataclass
from uuid import uuid4

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty
from bpy.types import PropertyGroup
from mathutils import Vector

from ..collection_registry import assign_bone
from ..generation import (
    add_copy_rotation,
    add_stretch_to,
    create_edit_bone,
    write_bone_metadata,
)
from ..module_base import (
    ModuleDefinition,
    generate_role_sets,
    preview_toggle,
    refresh_preview,
    require_side,
    role_name_sets,
)
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
        "influence_start": FloatProperty(
            name="起始旋转影响", default=0.1, min=-2.0, max=2.0
        ),
        "influence_end": FloatProperty(
            name="末端旋转影响", default=0.8, min=-2.0, max=2.0
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
    influence_start: float = 0.1
    influence_end: float = 0.8


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
        influence_start=settings.influence_start,
        influence_end=settings.influence_end,
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
    side = require_side(side, main_name, target_name)
    if main.length <= 1e-8:
        raise ValueError(f"{config.main_label} 骨长无效")
    if any(
        bone.hotools_boneprops.hoAux.moduleId == _module_id(config, side)
        for bone in iter_hoaux_bones(armature_data)
    ):
        raise ValueError(f"{_module_id(config, side)} 已存在")
    return main, target, side


def _influence(index, count, parameters):
    if count <= 1:
        return parameters.influence_end
    factor = index / (count - 1)
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
    main, _target, side = validate_roles(
        armature_object, main_name, target_name, config, side
    )
    parameters = parameters or Parameters()
    count = parameters.segment_count
    roll_reference = main.matrix_local.to_3x3() @ Vector((0.0, 0.0, 1.0))
    padding = max(2, len(str(count)))
    plans = []
    for index in range(count):
        start = index / count
        end = (index + 1) / count
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
    side = require_side(side, main_name, target_name)
    plans = build_plan(
        armature_object, main_name, target_name, config, side, parameters
    )
    armature_data = armature_object.data
    target_bone = armature_data.bones[target_name]
    target_point = target_bone.head_local
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
                head_tail=0.0,
                rest_length=(target_point - plan.head).length,
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
        ("segment_count",),
        ("influence_start", "influence_end"),
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
        parameters = parameters_from_settings(self.settings(context.scene))
        bone_names = (
            getattr(root, self.config.main_role),
            getattr(root, self.config.target_role),
        )
        return generate_role_sets(
            context,
            self.type_id,
            bone_names,
            lambda names, side: build_plan(
                context.object, *names, self.config, side, parameters
            ),
            lambda names, side: generate(
                context.object, *names, self.config, side, parameters
            ),
        )

    def build_preview_scene(self, context):
        from ..preview_draw import LineStyle, PreviewScene, ROLE_LINE_STYLES

        root = context.scene.hoaux_settings
        obj = context.object
        main_name = getattr(root, self.config.main_role)
        target_name = getattr(root, self.config.target_role)
        parameters = parameters_from_settings(self.settings(context.scene))
        ring_style = LineStyle((0.2, 0.9, 1.0, 0.95), 2.0)
        scene = PreviewScene(obj.name, title=self.label)
        for names, side in role_name_sets(context, main_name, target_name):
            plans = build_plan(
                obj, *names, self.config, side, parameters
            )
            main = obj.data.bones[names[0]]
            direction = (main.tail_local - main.head_local).normalized()
            scene.add_segment(
                main.head_local, main.tail_local, ROLE_LINE_STYLES["GUIDE"]
            )
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
