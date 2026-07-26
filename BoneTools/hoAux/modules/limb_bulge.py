"""Forearm and upper-arm longitudinal bulge modules."""

from dataclasses import dataclass
from uuid import uuid4

import bpy
from bpy.props import BoolProperty, FloatProperty
from bpy.types import PropertyGroup
from mathutils import Vector

from Utils import bone_utils

from ..generation import (
    GenerationTransaction,
    SharedDirectionSpec,
    add_copy_location,
    add_copy_rotation,
    add_transform_driver,
    allocate_bone_name,
    assign_bone,
    create_edit_bone,
    delayed_response_expression,
    find_shared_direction,
    iter_hoaux_bones,
    validate_shared_direction,
    write_bone_metadata,
)
from ..joint_frame import build_joint_frame
from ..module_base import (
    ModuleDefinition,
    PlannedBone,
    generate_role_sets,
    preview_toggle,
    refresh_preview,
    require_side,
    role_name_sets,
)
from ..properties import ensure_rig_id


DIR_SHARED_KEY = "ROTATION_HALF:LOWER_ARM:{side}"
DIR_LENGTH_RATIO = 0.17
HALF_INFLUENCE = 0.5
RESPONSE_ANGLE_DEGREES = 90.0
HEAD_OFFSET_RATIO = 0.0375
CONVEX_AXIS = "X"
ROLL_FOLLOW = 1.0
STRAIGHT_THRESHOLD_DEGREES = 5.0


def _settings_annotations(module_type):
    return {
        "ui_expanded": BoolProperty(name="膨胀设置", default=False),
        "preview_enabled": BoolProperty(
            name="预览", default=False, update=preview_toggle(module_type)
        ),
        "track_length": FloatProperty(
            name="TRK长度",
            default=0.03,
            min=0.01,
            max=1.0,
            update=refresh_preview,
        ),
        "deform_length": FloatProperty(
            name="DEF长度",
            default=0.11,
            min=0.01,
            max=1.0,
            update=refresh_preview,
        ),
        "twist_offset": FloatProperty(
            name="扭转偏移",
            default=0.0,
            min=-180.0,
            max=180.0,
            update=refresh_preview,
        ),
    }


def _settings_class(name, module_type):
    return type(
        name,
        (PropertyGroup,),
        {"__module__": __name__, "__annotations__": _settings_annotations(module_type)},
    )


PG_HoAuxForearmBulgeSettings = _settings_class(
    "PG_HoAuxForearmBulgeSettings", "FOREARM_BULGE"
)
PG_HoAuxUpperArmBulgeSettings = _settings_class(
    "PG_HoAuxUpperArmBulgeSettings", "UPPER_ARM_LONGITUDINAL_BULGE"
)


@dataclass(frozen=True)
class Parameters:
    track_length_ratio: float = 0.03
    deform_length_ratio: float = 0.11
    twist_offset_degrees: float = 0.0


@dataclass(frozen=True)
class BulgeConfig:
    module_type: str
    label: str
    order: int
    settings_attr: str
    settings_class: type
    part: str
    name_part: str
    position_ratio: float
    use_lower_arm: bool


FOREARM_CONFIG = BulgeConfig(
    module_type="FOREARM_BULGE",
    label="小臂膨胀",
    order=20,
    settings_attr="hoaux_forearm_bulge_settings",
    settings_class=PG_HoAuxForearmBulgeSettings,
    part="LowerArm",
    name_part="LowerArm",
    position_ratio=0.26,
    use_lower_arm=True,
)
UPPER_ARM_CONFIG = BulgeConfig(
    module_type="UPPER_ARM_LONGITUDINAL_BULGE",
    label="大臂纵向膨胀",
    order=50,
    settings_attr="hoaux_upper_arm_bulge_settings",
    settings_class=PG_HoAuxUpperArmBulgeSettings,
    part="UpperArm",
    name_part="UpperArm",
    position_ratio=0.58,
    use_lower_arm=False,
)


def parameters_from_settings(settings):
    return Parameters(
        track_length_ratio=settings.track_length,
        deform_length_ratio=settings.deform_length,
        twist_offset_degrees=settings.twist_offset,
    )


def _module_id(config, side):
    return f"{config.module_type}.{side}"


def validate_roles(
    armature_object,
    upper_arm_name,
    lower_arm_name,
    config,
    side,
):
    if armature_object is None or armature_object.type != "ARMATURE":
        raise ValueError("请选择骨架")
    armature_data = armature_object.data
    upper_arm = armature_data.bones.get(upper_arm_name)
    lower_arm = armature_data.bones.get(lower_arm_name)
    if upper_arm is None or lower_arm is None:
        raise ValueError("请设置大臂骨和小臂骨")
    if upper_arm == lower_arm:
        raise ValueError("大臂骨和小臂骨不能相同")
    side = require_side(side, upper_arm_name, lower_arm_name)
    if upper_arm.length <= 1e-8 or lower_arm.length <= 1e-8:
        raise ValueError("大臂骨或小臂骨长度无效")
    if any(
        bone.hotools_boneprops.hoAux.moduleId == _module_id(config, side)
        for bone in iter_hoaux_bones(armature_data)
    ):
        raise ValueError(f"{_module_id(config, side)} 已存在")
    return upper_arm, lower_arm, side


def build_plan(
    armature_object,
    upper_arm_name,
    lower_arm_name,
    config,
    side,
    parameters=None,
):
    upper_arm, lower_arm, side = validate_roles(
        armature_object, upper_arm_name, lower_arm_name, config, side
    )
    parameters = parameters or Parameters()
    frame = build_joint_frame(
        upper_arm,
        lower_arm,
        convex_axis=CONVEX_AXIS,
        roll_follow=ROLL_FOLLOW,
        twist_offset_degrees=parameters.twist_offset_degrees,
        straight_threshold_degrees=STRAIGHT_THRESHOLD_DEGREES,
    )
    main = lower_arm if config.use_lower_arm else upper_arm
    center = main.head_local.lerp(main.tail_local, config.position_ratio)
    plans = []
    for role_tag, length_ratio in (
        ("TRK", parameters.track_length_ratio),
        ("DEF", parameters.deform_length_ratio),
    ):
        for marker, sign in (("UP", 1.0), ("DOWN", -1.0)):
            direction = frame.z_axis * sign
            head = center + direction * main.length * HEAD_OFFSET_RATIO
            plans.append(
                PlannedBone(
                    resource_key=(
                        f"ARM.{side}.{config.module_type}.{role_tag}.{marker}"
                    ),
                    preferred_name=(
                        f"{role_tag}_{config.name_part}_Raise_{marker}_{side}"
                    ),
                    role_tag=role_tag,
                    marker=marker,
                    head=head,
                    tail=head + direction * main.length * length_ratio,
                    roll_reference=frame.x_axis,
                    parent_name=main.name,
                )
            )
    return plans


def generate(
    armature_object,
    upper_arm_name,
    lower_arm_name,
    config,
    side,
    parameters=None,
):
    parameters = parameters or Parameters()
    side = require_side(side, upper_arm_name, lower_arm_name)
    plans = build_plan(
        armature_object,
        upper_arm_name,
        lower_arm_name,
        config,
        side,
        parameters,
    )
    armature_data = armature_object.data
    lower_arm = armature_data.bones[lower_arm_name]
    lower_head = lower_arm.head_local.copy()
    lower_direction = (lower_arm.tail_local - lower_arm.head_local).normalized()
    lower_roll = lower_arm.matrix_local.to_3x3() @ Vector((0.0, 0.0, 1.0))
    dir_tail = lower_head + lower_direction * lower_arm.length * DIR_LENGTH_RATIO
    rig_id = ensure_rig_id(armature_data)
    generation_id = uuid4().hex
    pipeline_id = f"ARM.{side}"
    module_id = _module_id(config, side)
    shared_key = DIR_SHARED_KEY.format(side=side)
    existing_dir = find_shared_direction(armature_data, shared_key)
    if existing_dir is not None:
        validate_shared_direction(
            armature_object,
            existing_dir,
            SharedDirectionSpec(
                parent_name=upper_arm_name,
                source_name=lower_arm_name,
                head=lower_head,
                tail=dir_tail,
                roll_reference=lower_roll,
                owner_space="WORLD",
                target_space="WORLD",
                influence=HALF_INFLUENCE,
            ),
        )

    actual_names = {
        plan.resource_key: allocate_bone_name(armature_data, plan.preferred_name)
        for plan in plans
    }
    dir_name = existing_dir.name if existing_dir else allocate_bone_name(
        armature_data, f"DIR_LowerArm_Rotation_HALF_{side}"
    )
    with GenerationTransaction(armature_object) as transaction:
        bpy.context.view_layer.objects.active = armature_object
        armature_object.select_set(True)
        if armature_object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            edit_bones = armature_data.edit_bones
            if existing_dir is None:
                direction = edit_bones.new(dir_name)
                direction.head = lower_head
                direction.tail = dir_tail
                direction.parent = edit_bones.get(upper_arm_name)
                direction.use_connect = False
                direction.align_roll(lower_roll)
                bone_utils.inherit_bone_collections(direction.parent, direction)
                transaction.track_bone(dir_name)
            for plan in plans:
                create_edit_bone(edit_bones, plan, actual_names[plan.resource_key])
                transaction.track_bone(actual_names[plan.resource_key])
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")

        if existing_dir is None:
            direction_bone = armature_data.bones[dir_name]
            write_bone_metadata(
                direction_bone,
                rig_id=rig_id,
                pipeline_id=pipeline_id,
                module_id="INFRASTRUCTURE",
                module_type="ROTATION_HALF",
                generation_id=generation_id,
                role_tag="DIR",
                part="LowerArm",
                function="RotationHalf",
                marker="LOWER_ARM_HALF",
                side=side,
                name_key=f"ARM.{side}.ROTATION_HALF.DIR.LOWER_ARM",
                shared_key=shared_key,
            )
            assign_bone(armature_data, direction_bone)
            add_copy_rotation(
                armature_object.pose.bones[dir_name],
                armature_object,
                lower_arm_name,
                transaction,
                name="HoAux Half Rotation",
                owner_space="WORLD",
                target_space="WORLD",
                influence=HALF_INFLUENCE,
            )

        for plan in plans:
            bone = armature_data.bones[actual_names[plan.resource_key]]
            write_bone_metadata(
                bone,
                rig_id=rig_id,
                pipeline_id=pipeline_id,
                module_id=module_id,
                module_type=config.module_type,
                generation_id=generation_id,
                role_tag=plan.role_tag,
                part=config.part,
                function="Bulge",
                marker=plan.marker,
                side=side,
                name_key=plan.resource_key,
            )
            assign_bone(armature_data, bone)

        by_role_marker = {
            (plan.role_tag, plan.marker): actual_names[plan.resource_key]
            for plan in plans
        }
        for marker in ("UP", "DOWN"):
            copy_location = add_copy_location(
                armature_object.pose.bones[by_role_marker[("DEF", marker)]],
                armature_object,
                by_role_marker[("TRK", marker)],
                transaction,
                head_tail=1.0,
            )
            add_transform_driver(
                copy_location,
                "influence",
                armature_object,
                dir_name,
                "ROT_Z",
                delayed_response_expression(RESPONSE_ANGLE_DEGREES),
                transaction,
            )

        transaction.commit()
    return {
        "dir": dir_name,
        "bones": [actual_names[plan.resource_key] for plan in plans],
        "createdDir": existing_dir is None,
        "generationId": generation_id,
    }


class BulgeDefinition(ModuleDefinition):
    parameter_rows = (
        ("track_length", "deform_length"),
        ("twist_offset",),
    )

    def __init__(self, config):
        self.config = config
        self.type_id = config.module_type
        self.label = config.label
        self.order = config.order
        self.settings_class = config.settings_class
        self.settings_attr = config.settings_attr
        self.required_roles = (
            ("upperArmBone", "大臂骨"),
            ("lowerArmBone", "小臂骨"),
        )

    def generate_from_context(self, context):
        root = context.scene.hoaux_settings
        parameters = parameters_from_settings(self.settings(context.scene))
        bone_names = (root.upperArmBone, root.lowerArmBone)
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
        from ..preview import PreviewScene, ROLE_LINE_STYLES

        obj = context.object
        root = context.scene.hoaux_settings
        parameters = parameters_from_settings(self.settings(context.scene))
        scene = PreviewScene(obj.name, title=self.label)
        for names, side in role_name_sets(
            context, root.upperArmBone, root.lowerArmBone
        ):
            plans = build_plan(
                obj, *names, self.config, side, parameters
            )
            lower_arm = obj.data.bones[names[1]]
            dir_tail = lower_arm.head_local + (
                lower_arm.tail_local - lower_arm.head_local
            ).normalized() * lower_arm.length * DIR_LENGTH_RATIO
            scene.add_planned_bones(plans, labels=True)
            scene.add_segment(
                lower_arm.head_local, dir_tail, ROLE_LINE_STYLES["DIR"]
            )
            scene.add_label(dir_tail, f"DIR 小臂半旋转 {side}（0.50）")
            scene.add_point(plans[0].head)
            scene.add_point(plans[1].head)
        return scene


FOREARM_DEFINITION = BulgeDefinition(FOREARM_CONFIG)
UPPER_ARM_DEFINITION = BulgeDefinition(UPPER_ARM_CONFIG)
