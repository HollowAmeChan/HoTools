"""Shoulder Volume module based on the research armature."""

from uuid import uuid4
from dataclasses import dataclass
from math import cos, radians, sin

import bpy
from mathutils import Vector

from ..collection_registry import assign_bone
from ..module_spec import PlannedBone
from ..joint_frame import build_joint_frame
from ..name_registry import allocate_bone_name, iter_hoaux_bones
from ..properties import ensure_rig_id
from ..shared_direction import (
    SharedDirectionSpec,
    find_shared_direction,
    validate_shared_direction,
)
from ..transaction import GenerationTransaction


MODULE_TYPE = "SHOULDER_VOLUME"
DIR_SHARED_KEY = "ROTATION_HALF:UPPER_ARM:{side}"


@dataclass(frozen=True)
class Parameters:
    track_length_ratio: float = 0.5
    deform_length_ratio: float = 0.28
    dir_length_ratio: float = 0.05
    half_influence: float = 0.5
    response_angle_degrees: float = 90.0
    copy_location_head_tail: float = 1.0
    x0_angle_degrees: float = 45.0
    convex_axis: str = "X"
    roll_follow: float = 1.0
    twist_offset_degrees: float = 0.0
    straight_threshold_degrees: float = 5.0
    x1_scale: float = 1.0
    x0_scale: float = 1.0
    z1_scale: float = 1.0
    z0_scale: float = 1.0


def parameters_from_settings(settings):
    return Parameters(
        track_length_ratio=settings.shoulderTrackLength,
        deform_length_ratio=settings.shoulderDefLength,
        dir_length_ratio=settings.shoulderDirLength,
        half_influence=settings.shoulderHalfInfluence,
        response_angle_degrees=settings.shoulderResponseAngle,
        copy_location_head_tail=settings.shoulderHeadTail,
        x0_angle_degrees=settings.shoulderX0Angle,
        convex_axis=settings.shoulderConvexAxis,
        roll_follow=settings.shoulderRollFollow,
        twist_offset_degrees=settings.shoulderTwistOffset,
        straight_threshold_degrees=settings.shoulderStraightThreshold,
        x1_scale=settings.shoulderX1Scale,
        x0_scale=settings.shoulderX0Scale,
        z1_scale=settings.shoulderZ1Scale,
        z0_scale=settings.shoulderZ0Scale,
    )


def _direction_specs(parameters):
    angle = radians(parameters.x0_angle_degrees)
    return (
        ("X1", Vector((0.0, 0.0, 1.0)), Vector((1.0, 0.0, 0.0)), parameters.x1_scale),
        (
            "X0",
            Vector((0.0, sin(angle), -cos(angle))),
            Vector((1.0, 0.0, 0.0)),
            parameters.x0_scale,
        ),
        ("Z1", Vector((-1.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0)), parameters.z1_scale),
        ("Z0", Vector((1.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0)), parameters.z0_scale),
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
    if upper_arm.length <= 1e-8:
        raise ValueError("UpperArm 骨长无效")
    if _existing_module_bones(armature_data, side):
        raise ValueError(f"{_module_id(side)} 已存在")
    return shoulder, upper_arm


def build_plan(
    armature_object,
    shoulder_name,
    upper_arm_name,
    side,
    parameters=None,
):
    shoulder, upper_arm = validate_roles(
        armature_object, shoulder_name, upper_arm_name, side
    )
    parameters = parameters or Parameters()
    frame = build_joint_frame(
        shoulder,
        upper_arm,
        convex_axis=parameters.convex_axis,
        roll_follow=parameters.roll_follow,
        twist_offset_degrees=parameters.twist_offset_degrees,
        straight_threshold_degrees=parameters.straight_threshold_degrees,
    )
    head = frame.origin
    result = []
    for role_tag, ratio in (
        ("TRK", parameters.track_length_ratio),
        ("DEF", parameters.deform_length_ratio),
    ):
        for marker, local_direction, local_roll, scale in _direction_specs(parameters):
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
                    tail=head + direction * upper_arm.length * ratio * scale,
                    roll_reference=roll_reference,
                    parent_name=shoulder.name,
                )
            )
    return result


def _create_edit_bone(edit_bones, plan, actual_name):
    bone = edit_bones.new(actual_name)
    bone.head = plan.head
    bone.tail = plan.tail
    bone.parent = edit_bones.get(plan.parent_name)
    bone.use_connect = False
    bone.align_roll(plan.roll_reference)
    return bone


def _write_metadata(
    bone,
    *,
    rig_id,
    pipeline_id,
    module_id,
    generation_id,
    role_tag,
    marker,
    side,
    name_key,
    shared_key="",
    module_type=MODULE_TYPE,
):
    info = bone.hotools_boneprops.hoAux
    info.isHoAuxBone = True
    info.rigId = rig_id
    info.pipelineId = pipeline_id
    info.moduleId = module_id
    info.moduleType = module_type
    info.roleTag = role_tag
    info.part = "Shoulder"
    info.function = "Volume"
    info.marker = marker
    info.side = side
    info.generationId = generation_id
    info.sharedKey = shared_key
    info.nameKey = name_key
    bone.use_deform = role_tag == "DEF"


def _add_copy_rotation(owner, target_object, target_bone, transaction, influence=1.0):
    constraint = owner.constraints.new("COPY_ROTATION")
    constraint.name = "HoAux Copy Rotation"
    constraint.target = target_object
    constraint.subtarget = target_bone
    constraint.owner_space = "LOCAL"
    constraint.target_space = "LOCAL_OWNER_ORIENT"
    constraint.mix_mode = "REPLACE"
    constraint.influence = influence
    transaction.track_constraint(owner.name, constraint)
    return constraint


def _add_driver(
    copy_location,
    armature_object,
    dir_name,
    axis,
    response_angle_degrees,
    transaction,
):
    fcurve = copy_location.driver_add("influence")
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    response_scale = 180.0 / response_angle_degrees
    driver.expression = f"abs(var*{response_scale:.9g}/pi)"
    variable = driver.variables.new()
    variable.name = "var"
    variable.type = "TRANSFORMS"
    target = variable.targets[0]
    target.id = armature_object
    target.bone_target = dir_name
    target.transform_type = f"ROT_{axis}"
    target.transform_space = "LOCAL_SPACE"
    target.rotation_mode = "AUTO"
    transaction.track_driver(fcurve)


def generate(
    armature_object,
    shoulder_name,
    upper_arm_name,
    side,
    parameters=None,
):
    parameters = parameters or Parameters()
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
        + upper_direction * upper_length * parameters.dir_length_ratio
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
                influence=parameters.half_influence,
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
                transaction.track_bone(dir_name)
            for plan in plans:
                actual_name = actual_names[plan.resource_key]
                _create_edit_bone(edit_bones, plan, actual_name)
                transaction.track_bone(actual_name)
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")

        if existing_dir is None:
            direction_bone = armature_data.bones[dir_name]
            _write_metadata(
                direction_bone,
                rig_id=rig_id,
                pipeline_id=pipeline_id,
                module_id="INFRASTRUCTURE",
                generation_id=generation_id,
                role_tag="DIR",
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
            direction_constraint.influence = parameters.half_influence
            transaction.track_constraint(dir_name, direction_constraint)

        for plan in plans:
            actual_name = actual_names[plan.resource_key]
            data_bone = armature_data.bones[actual_name]
            _write_metadata(
                data_bone,
                rig_id=rig_id,
                pipeline_id=pipeline_id,
                module_id=module_id,
                generation_id=generation_id,
                role_tag=plan.role_tag,
                marker=plan.marker,
                side=side,
                name_key=plan.resource_key,
            )
            assign_bone(armature_data, data_bone)

        plan_name_by_role_marker = {
            (plan.role_tag, plan.marker): actual_names[plan.resource_key]
            for plan in plans
        }
        for marker, _direction, _roll, _scale in _direction_specs(parameters):
            trk_name = plan_name_by_role_marker[("TRK", marker)]
            def_name = plan_name_by_role_marker[("DEF", marker)]
            _add_copy_rotation(
                armature_object.pose.bones[trk_name],
                armature_object,
                dir_name,
                transaction,
            )
            def_pose = armature_object.pose.bones[def_name]
            _add_copy_rotation(
                def_pose, armature_object, dir_name, transaction
            )
            copy_location = def_pose.constraints.new("COPY_LOCATION")
            copy_location.name = "HoAux Copy Location"
            copy_location.target = armature_object
            copy_location.subtarget = trk_name
            copy_location.owner_space = "WORLD"
            copy_location.target_space = "WORLD"
            copy_location.head_tail = parameters.copy_location_head_tail
            copy_location.influence = 0.0
            transaction.track_constraint(def_name, copy_location)
            _add_driver(
                copy_location,
                armature_object,
                dir_name,
                marker[0],
                parameters.response_angle_degrees,
                transaction,
            )

        transaction.commit()
    return {
        "dir": dir_name,
        "bones": [actual_names[plan.resource_key] for plan in plans],
        "createdDir": existing_dir is None,
        "generationId": generation_id,
    }
