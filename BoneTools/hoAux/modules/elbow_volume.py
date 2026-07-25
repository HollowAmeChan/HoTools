"""Elbow Volume module reconstructed from WholeLeftArm_Constraint_Driver."""

from dataclasses import dataclass
from uuid import uuid4

import bpy
from bpy.props import BoolProperty, FloatProperty
from bpy.types import PropertyGroup
from mathutils import Vector

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


MODULE_TYPE = "ELBOW_VOLUME"
DIR_SHARED_KEY = "ROTATION_HALF:LOWER_ARM:{side}"
SETTINGS_ATTR = "hoaux_elbow_volume_settings"
DIR_LENGTH_RATIO = 0.17
HALF_INFLUENCE = 0.5
TRACK_ROTATION_INFLUENCE = 1.0
DEFORM_ROTATION_INFLUENCE = 1.0
RESPONSE_ANGLE_DEGREES = 90.0
COPY_LOCATION_HEAD_TAIL = 1.0
CONVEX_AXIS = "X"
ROLL_FOLLOW = 1.0
STRAIGHT_THRESHOLD_DEGREES = 5.0


_toggle_preview = preview_toggle(MODULE_TYPE)


class PG_HoAuxElbowVolumeSettings(PropertyGroup):
    ui_expanded: BoolProperty(name="肘关节体积保持设置", default=False)  # type: ignore
    preview_enabled: BoolProperty(name="预览", default=False, update=_toggle_preview)  # type: ignore
    track_length: FloatProperty(
        name="TRK长度", default=0.35, min=0.05, max=2.0, update=refresh_preview
    )  # type: ignore
    deform_length: FloatProperty(
        name="DEF长度", default=0.21, min=0.05, max=2.0, update=refresh_preview
    )  # type: ignore
    twist_offset: FloatProperty(
        name="扭转偏移", default=0.0, min=-180.0, max=180.0, update=refresh_preview
    )  # type: ignore


@dataclass(frozen=True)
class Parameters:
    track_length_ratio: float = 0.35
    deform_length_ratio: float = 0.21
    twist_offset_degrees: float = 0.0


def parameters_from_settings(settings):
    return Parameters(
        track_length_ratio=settings.track_length,
        deform_length_ratio=settings.deform_length,
        twist_offset_degrees=settings.twist_offset,
    )


def _module_id(side):
    return f"ELBOW_VOLUME.{side}"


def _pipeline_id(side):
    return f"ARM.{side}"


def validate_roles(armature_object, upper_arm_name, lower_arm_name, side):
    if armature_object is None or armature_object.type != "ARMATURE":
        raise ValueError("请选择骨架")
    armature_data = armature_object.data
    upper_arm = armature_data.bones.get(upper_arm_name)
    lower_arm = armature_data.bones.get(lower_arm_name)
    if upper_arm is None or lower_arm is None:
        raise ValueError("请设置 UpperArm 和 LowerArm 主骨")
    if upper_arm == lower_arm:
        raise ValueError("UpperArm 和 LowerArm 不能是同一根骨")
    side = require_side(side, upper_arm_name, lower_arm_name)
    if upper_arm.length <= 1e-8 or lower_arm.length <= 1e-8:
        raise ValueError("肘关节主骨长度无效")
    if any(
        bone.hotools_boneprops.hoAux.moduleId == _module_id(side)
        for bone in iter_hoaux_bones(armature_data)
    ):
        raise ValueError(f"{_module_id(side)} 已存在")
    return upper_arm, lower_arm, side


def _direction(frame, sign):
    return (frame.x_axis * sign).normalized()


def build_plan(armature_object, upper_arm_name, lower_arm_name, side, parameters=None):
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
    result = []
    marker_specs = (
        ("Z1", 1.0),
        ("Z0", -1.0),
    )
    role_specs = (
        (
            "TRK",
            parameters.track_length_ratio,
            0.0,
            0.0,
        ),
        (
            "DEF",
            parameters.deform_length_ratio,
            0.0,
            0.0,
        ),
    )
    for role_tag, length_ratio, head_along, head_convex in role_specs:
        head = (
            frame.origin
            + frame.y_axis * lower_arm.length * head_along
            + frame.x_axis * lower_arm.length * head_convex
        )
        for marker, sign in marker_specs:
            direction = _direction(frame, sign)
            result.append(
                PlannedBone(
                    resource_key=f"ARM.{side}.ELBOW_VOLUME.{role_tag}.{marker}",
                    preferred_name=f"{role_tag}_Elbow_Volume_{marker}_{side}",
                    role_tag=role_tag,
                    marker=marker,
                    head=head.copy(),
                    tail=head + direction * lower_arm.length * length_ratio,
                    roll_reference=frame.z_axis,
                    parent_name=upper_arm.name,
                )
            )
    return result


def generate(armature_object, upper_arm_name, lower_arm_name, side, parameters=None):
    parameters = parameters or Parameters()
    side = require_side(side, upper_arm_name, lower_arm_name)
    plans = build_plan(
        armature_object, upper_arm_name, lower_arm_name, side, parameters
    )
    armature_data = armature_object.data
    upper_arm = armature_data.bones[upper_arm_name]
    lower_arm = armature_data.bones[lower_arm_name]
    lower_head = lower_arm.head_local.copy()
    lower_direction = (lower_arm.tail_local - lower_arm.head_local).normalized()
    lower_length = lower_arm.length
    lower_roll_reference = lower_arm.matrix_local.to_3x3() @ Vector((0, 0, 1))
    expected_dir_tail = (
        lower_head + lower_direction * lower_length * DIR_LENGTH_RATIO
    )
    rig_id = ensure_rig_id(armature_data)
    generation_id = uuid4().hex
    pipeline_id = _pipeline_id(side)
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
                tail=expected_dir_tail,
                roll_reference=lower_roll_reference,
                owner_space="WORLD",
                target_space="WORLD",
                influence=HALF_INFLUENCE,
            ),
        )

    actual_names = {
        plan.resource_key: allocate_bone_name(armature_data, plan.preferred_name)
        for plan in plans
    }
    dir_name = (
        existing_dir.name
        if existing_dir is not None
        else allocate_bone_name(armature_data, f"DIR_LowerArm_Rotation_HALF_{side}")
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
                direction.tail = expected_dir_tail
                direction.parent = edit_bones.get(upper_arm_name)
                direction.use_connect = False
                direction.align_roll(lower_roll_reference)
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
                part="Elbow",
                function="Volume",
                marker=plan.marker,
                side=side,
                name_key=plan.resource_key,
            )
            assign_bone(armature_data, data_bone)

        names_by_role_marker = {
            (plan.role_tag, plan.marker): actual_names[plan.resource_key]
            for plan in plans
        }
        for marker in ("Z1", "Z0"):
            trk_name = names_by_role_marker[("TRK", marker)]
            def_name = names_by_role_marker[("DEF", marker)]
            add_copy_rotation(
                armature_object.pose.bones[trk_name],
                armature_object,
                dir_name,
                transaction,
                influence=TRACK_ROTATION_INFLUENCE,
            )
            def_pose = armature_object.pose.bones[def_name]
            add_copy_rotation(
                def_pose,
                armature_object,
                trk_name,
                transaction,
                target_space="LOCAL_WITH_PARENT",
                influence=DEFORM_ROTATION_INFLUENCE,
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
                trk_name,
                "ROT_Z",
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


class ElbowVolumeDefinition(ModuleDefinition):
    type_id = MODULE_TYPE
    label = "肘关节体积保持"
    order = 40
    settings_class = PG_HoAuxElbowVolumeSettings
    settings_attr = SETTINGS_ATTR
    required_roles = (
        ("upperArmBone", "大臂骨"),
        ("lowerArmBone", "小臂骨"),
    )
    parameter_rows = (
        ("track_length", "deform_length"),
        ("twist_offset",),
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
            direction_tail = lower_arm.head_local + (
                lower_arm.tail_local - lower_arm.head_local
            ).normalized() * lower_arm.length * DIR_LENGTH_RATIO
            scene.add_planned_bones(plans, labels=True)
            scene.add_segment(
                lower_arm.head_local,
                direction_tail,
                ROLE_LINE_STYLES["DIR"],
            )
            scene.add_label(direction_tail, f"DIR 小臂半旋转 {side}（0.50）")
            scene.add_point(lower_arm.head_local)
        return scene

DEFINITION = ElbowVolumeDefinition()
