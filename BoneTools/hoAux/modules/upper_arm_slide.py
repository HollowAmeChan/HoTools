"""Upper-arm muscle slide from WholeLeftArm_Constraint_Driver."""

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
    response_expression,
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


MODULE_TYPE = "UPPER_ARM_MUSCLE_SLIDE"
SETTINGS_ATTR = "hoaux_upper_arm_slide_settings"
DIR_SHARED_KEY = "ROTATION_HALF:LOWER_ARM:{side}"
DIR_LENGTH_RATIO = 0.17
HALF_INFLUENCE = 0.5
RESPONSE_ANGLE_DEGREES = 90.0
POSITION_RATIO = 0.71
LATERAL_OFFSET_RATIO = 0.115
CONVEX_AXIS = "X"
ROLL_FOLLOW = 1.0
STRAIGHT_THRESHOLD_DEGREES = 5.0


_toggle_preview = preview_toggle(MODULE_TYPE)


class PG_HoAuxUpperArmSlideSettings(PropertyGroup):
    ui_expanded: BoolProperty(name="大臂肌肉滑移设置", default=False)  # type: ignore
    preview_enabled: BoolProperty(
        name="预览", default=False, update=_toggle_preview
    )  # type: ignore
    track_length: FloatProperty(
        name="主TRK长度", default=0.20, min=0.02, max=1.0, update=refresh_preview
    )  # type: ignore
    secondary_length: FloatProperty(
        name="二级TRK长度",
        default=0.06,
        min=0.01,
        max=1.0,
        update=refresh_preview,
    )  # type: ignore
    deform_length: FloatProperty(
        name="DEF长度", default=0.185, min=0.02, max=1.0, update=refresh_preview
    )  # type: ignore
    twist_offset: FloatProperty(
        name="扭转偏移",
        default=0.0,
        min=-180.0,
        max=180.0,
        update=refresh_preview,
    )  # type: ignore


@dataclass(frozen=True)
class Parameters:
    track_length_ratio: float = 0.20
    secondary_length_ratio: float = 0.06
    deform_length_ratio: float = 0.185
    twist_offset_degrees: float = 0.0


def parameters_from_settings(settings):
    return Parameters(
        track_length_ratio=settings.track_length,
        secondary_length_ratio=settings.secondary_length,
        deform_length_ratio=settings.deform_length,
        twist_offset_degrees=settings.twist_offset,
    )


def _module_id(side):
    return f"{MODULE_TYPE}.{side}"


def validate_roles(armature_object, upper_arm_name, lower_arm_name, side):
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
        bone.hotools_boneprops.hoAux.moduleId == _module_id(side)
        for bone in iter_hoaux_bones(armature_data)
    ):
        raise ValueError(f"{_module_id(side)} 已存在")
    return upper_arm, lower_arm, side


def build_plan(
    armature_object,
    upper_arm_name,
    lower_arm_name,
    side,
    parameters=None,
):
    upper_arm, lower_arm, side = validate_roles(
        armature_object, upper_arm_name, lower_arm_name, side
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
    center = upper_arm.head_local.lerp(upper_arm.tail_local, POSITION_RATIO)
    plans = []
    for marker, outward_sign, axial_sign in (
        ("OUT", -1.0, 1.0),
        ("IN", 1.0, -1.0),
    ):
        outward = frame.x_axis * outward_sign
        head = center + outward * upper_arm.length * LATERAL_OFFSET_RATIO
        plans.extend(
            (
                PlannedBone(
                    resource_key=f"ARM.{side}.{MODULE_TYPE}.TRK.{marker}",
                    preferred_name=f"TRK_UpperArm_Slide_{marker}_{side}",
                    role_tag="TRK",
                    marker=marker,
                    head=head.copy(),
                    tail=(
                        head
                        + frame.y_axis
                        * axial_sign
                        * upper_arm.length
                        * parameters.track_length_ratio
                    ),
                    roll_reference=frame.z_axis,
                    parent_name=upper_arm.name,
                ),
                PlannedBone(
                    resource_key=(
                        f"ARM.{side}.{MODULE_TYPE}.TRK.{marker}_SECONDARY"
                    ),
                    preferred_name=f"TRK_UpperArm_Slide1_{marker}_{side}",
                    role_tag="TRK",
                    marker=f"{marker}_SECONDARY",
                    head=head.copy(),
                    tail=(
                        head
                        + frame.x_axis
                        * upper_arm.length
                        * parameters.secondary_length_ratio
                    ),
                    roll_reference=frame.z_axis,
                    parent_name=upper_arm.name,
                ),
                PlannedBone(
                    resource_key=f"ARM.{side}.{MODULE_TYPE}.DEF.{marker}",
                    preferred_name=f"DEF_UpperArm_Slide_{marker}_{side}",
                    role_tag="DEF",
                    marker=marker,
                    head=head.copy(),
                    tail=(
                        head
                        + outward
                        * upper_arm.length
                        * parameters.deform_length_ratio
                    ),
                    roll_reference=frame.z_axis,
                    parent_name=upper_arm.name,
                ),
            )
        )
    return plans


def generate(
    armature_object,
    upper_arm_name,
    lower_arm_name,
    side,
    parameters=None,
):
    parameters = parameters or Parameters()
    side = require_side(side, upper_arm_name, lower_arm_name)
    plans = build_plan(
        armature_object, upper_arm_name, lower_arm_name, side, parameters
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
    module_id = _module_id(side)
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
                module_type=MODULE_TYPE,
                generation_id=generation_id,
                role_tag=plan.role_tag,
                part="UpperArm",
                function="MuscleSlide",
                marker=plan.marker,
                side=side,
                name_key=plan.resource_key,
            )
            assign_bone(armature_data, bone)

        by_role_marker = {
            (plan.role_tag, plan.marker): actual_names[plan.resource_key]
            for plan in plans
        }
        for marker in ("OUT", "IN"):
            main_trk = by_role_marker[("TRK", marker)]
            secondary_trk = by_role_marker[("TRK", f"{marker}_SECONDARY")]
            def_pose = armature_object.pose.bones[by_role_marker[("DEF", marker)]]

            secondary_location = add_copy_location(
                armature_object.pose.bones[secondary_trk],
                armature_object,
                main_trk,
                transaction,
                head_tail=1.0,
            )
            primary_location = add_copy_location(
                def_pose,
                armature_object,
                main_trk,
                transaction,
                head_tail=1.0,
            )
            delayed_location = add_copy_location(
                def_pose,
                armature_object,
                secondary_trk,
                transaction,
                head_tail=1.0,
            )
            for constraint in (secondary_location, primary_location):
                add_transform_driver(
                    constraint,
                    "influence",
                    armature_object,
                    dir_name,
                    "ROT_Z",
                    response_expression(RESPONSE_ANGLE_DEGREES),
                    transaction,
                )
            add_transform_driver(
                delayed_location,
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


class UpperArmSlideDefinition(ModuleDefinition):
    type_id = MODULE_TYPE
    label = "大臂肌肉滑移"
    order = 70
    settings_class = PG_HoAuxUpperArmSlideSettings
    settings_attr = SETTINGS_ATTR
    required_roles = (
        ("upperArmBone", "大臂骨"),
        ("lowerArmBone", "小臂骨"),
    )
    parameter_rows = (
        ("track_length", "secondary_length"),
        ("deform_length", "twist_offset"),
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
                context.object, *names, side, parameters
            ),
            lambda names, side: generate(
                context.object, *names, side, parameters
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
            plans = build_plan(obj, *names, side, parameters)
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
            scene.add_point(plans[3].head)
        return scene


DEFINITION = UpperArmSlideDefinition()
