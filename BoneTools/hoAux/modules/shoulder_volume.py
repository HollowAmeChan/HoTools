"""Shoulder Volume module based on the research armature."""

from uuid import uuid4
from dataclasses import dataclass
from math import cos, radians, sin

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


MODULE_TYPE = "SHOULDER_VOLUME"
DIR_SHARED_KEY = "ROTATION_HALF:UPPER_ARM:{side}"
SETTINGS_ATTR = "hoaux_shoulder_volume_settings"
DIR_LENGTH_RATIO = 0.05
HALF_INFLUENCE = 0.5
RESPONSE_ANGLE_DEGREES = 90.0
COPY_LOCATION_HEAD_TAIL = 1.0
CONVEX_AXIS = "X"
ROLL_FOLLOW = 1.0
STRAIGHT_THRESHOLD_DEGREES = 5.0


_toggle_preview = preview_toggle(MODULE_TYPE)


class PG_HoAuxShoulderVolumeSettings(PropertyGroup):
    ui_expanded: BoolProperty(name="肩部体积保持设置", default=False)  # type: ignore
    preview_enabled: BoolProperty(name="预览", default=False, update=_toggle_preview)  # type: ignore
    track_length: FloatProperty(
        name="TRK长度", default=0.5, min=0.05, max=2.0, update=refresh_preview
    )  # type: ignore
    deform_length: FloatProperty(
        name="DEF长度", default=0.28, min=0.05, max=2.0, update=refresh_preview
    )  # type: ignore
    x0_angle: FloatProperty(
        name="X0方向角度", default=45.0, min=-180.0, max=180.0, update=refresh_preview
    )  # type: ignore
    twist_offset: FloatProperty(
        name="扭转偏移", default=0.0, min=-180.0, max=180.0, update=refresh_preview
    )  # type: ignore


@dataclass(frozen=True)
class Parameters:
    track_length_ratio: float = 0.5
    deform_length_ratio: float = 0.28
    x0_angle_degrees: float = 45.0
    twist_offset_degrees: float = 0.0


def parameters_from_settings(settings):
    return Parameters(
        track_length_ratio=settings.track_length,
        deform_length_ratio=settings.deform_length,
        x0_angle_degrees=settings.x0_angle,
        twist_offset_degrees=settings.twist_offset,
    )


def _direction_specs(parameters):
    angle = radians(parameters.x0_angle_degrees)
    return (
        ("X1", Vector((0.0, 0.0, 1.0)), Vector((1.0, 0.0, 0.0))),
        (
            "X0",
            Vector((0.0, sin(angle), -cos(angle))),
            Vector((1.0, 0.0, 0.0)),
        ),
        ("Z1", Vector((-1.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0))),
        ("Z0", Vector((1.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0))),
    )


def _module_id(side):
    return f"SHOULDER_VOLUME.{side}"


def _pipeline_id(side):
    return f"ARM.{side}"


def _existing_module_bones(armature_data, side):
    module_id = _module_id(side)
    return [
        bone
        for bone in iter_hoaux_bones(armature_data)
        if bone.hotools_boneprops.hoAux.moduleId == module_id
    ]


def validate_roles(armature_object, shoulder_name, upper_arm_name, side):
    if armature_object is None or armature_object.type != "ARMATURE":
        raise ValueError("请选择骨架")
    armature_data = armature_object.data
    shoulder = armature_data.bones.get(shoulder_name)
    upper_arm = armature_data.bones.get(upper_arm_name)
    if shoulder is None or upper_arm is None:
        raise ValueError("请设置 Shoulder 和 UpperArm 主骨")
    if shoulder == upper_arm:
        raise ValueError("Shoulder 和 UpperArm 不能是同一根骨")
    side = require_side(side, shoulder_name, upper_arm_name)
    if upper_arm.length <= 1e-8:
        raise ValueError("UpperArm 骨长无效")
    if _existing_module_bones(armature_data, side):
        raise ValueError(f"{_module_id(side)} 已存在")
    return shoulder, upper_arm, side


def build_plan(
    armature_object,
    shoulder_name,
    upper_arm_name,
    side,
    parameters=None,
):
    shoulder, upper_arm, side = validate_roles(
        armature_object, shoulder_name, upper_arm_name, side
    )
    parameters = parameters or Parameters()
    frame = build_joint_frame(
        shoulder,
        upper_arm,
        convex_axis=CONVEX_AXIS,
        roll_follow=ROLL_FOLLOW,
        twist_offset_degrees=parameters.twist_offset_degrees,
        straight_threshold_degrees=STRAIGHT_THRESHOLD_DEGREES,
    )
    head = frame.origin
    result = []
    for role_tag, ratio in (
        ("TRK", parameters.track_length_ratio),
        ("DEF", parameters.deform_length_ratio),
    ):
        for marker, local_direction, local_roll in _direction_specs(parameters):
            direction = frame.transform_direction(local_direction.normalized())
            roll_reference = frame.transform_direction(local_roll)
            result.append(
                PlannedBone(
                    resource_key=(
                        f"ARM.{side}.SHOULDER_VOLUME.{role_tag}.{marker}"
                    ),
                    preferred_name=(
                        f"{role_tag}_Shoulder_Volume_{marker}_{side}"
                    ),
                    role_tag=role_tag,
                    marker=marker,
                    head=head.copy(),
                    tail=head + direction * upper_arm.length * ratio,
                    roll_reference=roll_reference,
                    parent_name=shoulder.name,
                )
            )
    return result


def generate(
    armature_object,
    shoulder_name,
    upper_arm_name,
    side,
    parameters=None,
):
    parameters = parameters or Parameters()
    side = require_side(side, shoulder_name, upper_arm_name)
    plans = build_plan(
        armature_object,
        shoulder_name,
        upper_arm_name,
        side,
        parameters,
    )
    armature_data = armature_object.data
    shoulder = armature_data.bones[shoulder_name]
    upper_arm = armature_data.bones[upper_arm_name]
    upper_head = upper_arm.head_local.copy()
    upper_direction = (upper_arm.tail_local - upper_arm.head_local).normalized()
    upper_length = upper_arm.length
    upper_roll_reference = upper_arm.matrix_local.to_3x3() @ Vector((0, 0, 1))
    rig_id = ensure_rig_id(armature_data)
    generation_id = uuid4().hex
    pipeline_id = _pipeline_id(side)
    module_id = _module_id(side)
    shared_key = DIR_SHARED_KEY.format(side=side)
    existing_dir = find_shared_direction(armature_data, shared_key)
    expected_dir_tail = (
        upper_head
        + upper_direction * upper_length * DIR_LENGTH_RATIO
    )
    if existing_dir is not None:
        validate_shared_direction(
            armature_object,
            existing_dir,
            SharedDirectionSpec(
                parent_name=shoulder_name,
                source_name=upper_arm_name,
                head=upper_head,
                tail=expected_dir_tail,
                roll_reference=upper_roll_reference,
                influence=HALF_INFLUENCE,
            ),
        )

    actual_names = {
        plan.resource_key: allocate_bone_name(
            armature_data, plan.preferred_name
        )
        for plan in plans
    }
    dir_name = existing_dir.name if existing_dir is not None else allocate_bone_name(
        armature_data, f"DIR_UpperArm_Rotation_HALF_{side}"
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
                direction.head = upper_head
                direction.tail = expected_dir_tail
                direction.parent = edit_bones.get(shoulder_name)
                direction.use_connect = False
                direction.align_roll(upper_roll_reference)
                bone_utils.inherit_bone_collections(direction.parent, direction)
                transaction.track_bone(dir_name)
            for plan in plans:
                actual_name = actual_names[plan.resource_key]
                create_edit_bone(edit_bones, plan, actual_name)
                transaction.track_bone(actual_name)
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")

        if existing_dir is None:
            direction_bone = armature_data.bones[dir_name]
            write_bone_metadata(
                direction_bone,
                rig_id=rig_id,
                pipeline_id=pipeline_id,
                module_id="INFRASTRUCTURE",
                generation_id=generation_id,
                role_tag="DIR",
                part="UpperArm",
                function="RotationHalf",
                marker="UPPER_ARM_HALF",
                side=side,
                name_key=f"ARM.{side}.ROTATION_HALF.DIR.UPPER_ARM",
                shared_key=shared_key,
                module_type="ROTATION_HALF",
            )
            assign_bone(armature_data, direction_bone)
            direction_pose = armature_object.pose.bones[dir_name]
            direction_constraint = direction_pose.constraints.new("COPY_ROTATION")
            direction_constraint.name = "HoAux Half Rotation"
            direction_constraint.target = armature_object
            direction_constraint.subtarget = upper_arm_name
            direction_constraint.owner_space = "LOCAL"
            direction_constraint.target_space = "LOCAL"
            direction_constraint.mix_mode = "REPLACE"
            direction_constraint.influence = HALF_INFLUENCE
            transaction.track_constraint(dir_name, direction_constraint)

        for plan in plans:
            actual_name = actual_names[plan.resource_key]
            data_bone = armature_data.bones[actual_name]
            write_bone_metadata(
                data_bone,
                rig_id=rig_id,
                pipeline_id=pipeline_id,
                module_id=module_id,
                module_type=MODULE_TYPE,
                generation_id=generation_id,
                role_tag=plan.role_tag,
                part="Shoulder",
                function="Volume",
                marker=plan.marker,
                side=side,
                name_key=plan.resource_key,
            )
            assign_bone(armature_data, data_bone)

        plan_name_by_role_marker = {
            (plan.role_tag, plan.marker): actual_names[plan.resource_key]
            for plan in plans
        }
        for marker, _direction, _roll in _direction_specs(parameters):
            trk_name = plan_name_by_role_marker[("TRK", marker)]
            def_name = plan_name_by_role_marker[("DEF", marker)]
            add_copy_rotation(
                armature_object.pose.bones[trk_name],
                armature_object,
                dir_name,
                transaction,
            )
            def_pose = armature_object.pose.bones[def_name]
            add_copy_rotation(
                def_pose, armature_object, dir_name, transaction
            )
            copy_location = add_copy_location(
                def_pose,
                armature_object,
                trk_name,
                transaction,
                head_tail=COPY_LOCATION_HEAD_TAIL,
            )
            add_transform_driver(
                copy_location,
                "influence",
                armature_object,
                dir_name,
                f"ROT_{marker[0]}",
                response_expression(RESPONSE_ANGLE_DEGREES),
                transaction,
            )

        transaction.commit()
    return {
        "dir": dir_name,
        "bones": [actual_names[plan.resource_key] for plan in plans],
        "createdDir": existing_dir is None,
        "generationId": generation_id,
    }


class ShoulderVolumeDefinition(ModuleDefinition):
    type_id = MODULE_TYPE
    label = "肩部体积保持"
    order = 80
    settings_class = PG_HoAuxShoulderVolumeSettings
    settings_attr = SETTINGS_ATTR
    required_roles = (
        ("shoulderBone", "肩骨"),
        ("upperArmBone", "大臂骨"),
    )
    parameter_rows = (
        ("track_length", "deform_length"),
        ("twist_offset",),
        ("x0_angle",),
    )

    def generate_from_context(self, context):
        root = context.scene.hoaux_settings
        parameters = parameters_from_settings(self.settings(context.scene))
        bone_names = (root.shoulderBone, root.upperArmBone)
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
            context, root.shoulderBone, root.upperArmBone
        ):
            plans = build_plan(obj, *names, side, parameters)
            upper_arm = obj.data.bones[names[1]]
            direction_tail = upper_arm.head_local + (
                upper_arm.tail_local - upper_arm.head_local
            ).normalized() * upper_arm.length * DIR_LENGTH_RATIO
            scene.add_planned_bones(plans, labels=True)
            scene.add_segment(
                upper_arm.head_local,
                direction_tail,
                ROLE_LINE_STYLES["DIR"],
            )
            scene.add_label(direction_tail, f"DIR 大臂半旋转 {side}（0.50）")
            scene.add_point(upper_arm.head_local)
        return scene

DEFINITION = ShoulderVolumeDefinition()
