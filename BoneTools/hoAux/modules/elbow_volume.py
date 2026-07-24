"""Elbow Volume module reconstructed from WholeLeftArm_Constraint_Driver."""

from dataclasses import dataclass
from math import radians
from uuid import uuid4

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from bpy.types import PropertyGroup
from mathutils import Quaternion, Vector

from ..collection_registry import assign_bone
from ..generation import (
    add_copy_location,
    add_copy_rotation,
    add_transform_driver,
    create_edit_bone,
    response_expression,
    write_bone_metadata,
)
from ..joint_frame import build_joint_frame
from ..module_spec import PlannedBone
from ..module_base import ModuleDefinition, preview_toggle, refresh_preview
from ..name_registry import allocate_bone_name, iter_hoaux_bones
from ..properties import ensure_rig_id
from ..shared_direction import (
    SharedDirectionSpec,
    find_shared_direction,
    validate_shared_direction,
)
from ..transaction import GenerationTransaction


MODULE_TYPE = "ELBOW_VOLUME"
DIR_SHARED_KEY = "ROTATION_HALF:LOWER_ARM:{side}"
SETTINGS_ATTR = "hoaux_elbow_volume_settings"


_toggle_preview = preview_toggle(MODULE_TYPE)


class PG_HoAuxElbowVolumeSettings(PropertyGroup):
    ui_expanded: BoolProperty(default=True)  # type: ignore
    preview_enabled: BoolProperty(default=False, update=_toggle_preview)  # type: ignore
    track_length: FloatProperty(
        name="TRK Length", default=0.35, min=0.05, max=2.0, update=refresh_preview
    )  # type: ignore
    deform_length: FloatProperty(
        name="DEF Length", default=0.21, min=0.05, max=2.0, update=refresh_preview
    )  # type: ignore
    dir_length: FloatProperty(
        name="DIR Length", default=0.17, min=0.005, max=0.5, update=refresh_preview
    )  # type: ignore
    half_influence: FloatProperty(
        name="Half Influence", default=0.5, min=0.0, max=1.0
    )  # type: ignore
    track_rotation_influence: FloatProperty(
        name="TRK Rotation", default=1.0, min=0.0, max=1.0, subtype="FACTOR"
    )  # type: ignore
    deform_rotation_influence: FloatProperty(
        name="DEF Rotation", default=1.0, min=0.0, max=1.0, subtype="FACTOR"
    )  # type: ignore
    response_angle: FloatProperty(
        name="Full Response Angle", default=90.0, min=1.0, max=180.0
    )  # type: ignore
    head_tail: FloatProperty(
        name="Target Point", default=1.0, min=0.0, max=1.0, subtype="FACTOR"
    )  # type: ignore
    convex_axis: EnumProperty(
        name="Convex Axis",
        items=(
            ("X", "Local X", "Map joint convexity to frame X"),
            ("Z", "Local Z", "Map joint convexity to frame Z"),
        ),
        default="X",
        update=refresh_preview,
    )  # type: ignore
    roll_follow: FloatProperty(
        name="Roll Follow", default=1.0, min=0.0, max=1.0, subtype="FACTOR", update=refresh_preview
    )  # type: ignore
    twist_offset: FloatProperty(
        name="Twist Offset", default=0.0, min=-180.0, max=180.0, update=refresh_preview
    )  # type: ignore
    straight_threshold: FloatProperty(
        name="Straight Threshold", default=5.0, min=0.0, max=45.0, update=refresh_preview
    )  # type: ignore
    track_head_along: FloatProperty(
        name="TRK Head Along", default=0.0, min=-1.0, max=1.0, update=refresh_preview
    )  # type: ignore
    track_head_convex: FloatProperty(
        name="TRK Head Convex", default=0.0, min=-1.0, max=1.0, update=refresh_preview
    )  # type: ignore
    deform_head_along: FloatProperty(
        name="DEF Head Along", default=0.0, min=-1.0, max=1.0, update=refresh_preview
    )  # type: ignore
    deform_head_convex: FloatProperty(
        name="DEF Head Convex", default=0.0, min=-1.0, max=1.0, update=refresh_preview
    )  # type: ignore
    z1_angle: FloatProperty(
        name="Z1 Angle", default=0.0, min=-180.0, max=180.0, update=refresh_preview
    )  # type: ignore
    z0_angle: FloatProperty(
        name="Z0 Angle", default=0.0, min=-180.0, max=180.0, update=refresh_preview
    )  # type: ignore
    z1_scale: FloatProperty(
        name="Z1 Scale", default=1.0, min=0.05, max=3.0, update=refresh_preview
    )  # type: ignore
    z0_scale: FloatProperty(
        name="Z0 Scale", default=1.0, min=0.05, max=3.0, update=refresh_preview
    )  # type: ignore


@dataclass(frozen=True)
class Parameters:
    track_length_ratio: float = 0.35
    deform_length_ratio: float = 0.21
    dir_length_ratio: float = 0.17
    half_influence: float = 0.5
    track_rotation_influence: float = 1.0
    deform_rotation_influence: float = 1.0
    response_angle_degrees: float = 90.0
    copy_location_head_tail: float = 1.0
    convex_axis: str = "X"
    roll_follow: float = 1.0
    twist_offset_degrees: float = 0.0
    straight_threshold_degrees: float = 5.0
    track_head_along: float = 0.0
    track_head_convex: float = 0.0
    deform_head_along: float = 0.0
    deform_head_convex: float = 0.0
    z1_angle_degrees: float = 0.0
    z0_angle_degrees: float = 0.0
    z1_scale: float = 1.0
    z0_scale: float = 1.0


def parameters_from_settings(settings):
    return Parameters(
        track_length_ratio=settings.track_length,
        deform_length_ratio=settings.deform_length,
        dir_length_ratio=settings.dir_length,
        half_influence=settings.half_influence,
        track_rotation_influence=settings.track_rotation_influence,
        deform_rotation_influence=settings.deform_rotation_influence,
        response_angle_degrees=settings.response_angle,
        copy_location_head_tail=settings.head_tail,
        convex_axis=settings.convex_axis,
        roll_follow=settings.roll_follow,
        twist_offset_degrees=settings.twist_offset,
        straight_threshold_degrees=settings.straight_threshold,
        track_head_along=settings.track_head_along,
        track_head_convex=settings.track_head_convex,
        deform_head_along=settings.deform_head_along,
        deform_head_convex=settings.deform_head_convex,
        z1_angle_degrees=settings.z1_angle,
        z0_angle_degrees=settings.z0_angle,
        z1_scale=settings.z1_scale,
        z0_scale=settings.z0_scale,
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
    if lower_arm.parent != upper_arm:
        raise ValueError("LowerArm 必须直接以 UpperArm 为父级")
    if upper_arm.length <= 1e-8 or lower_arm.length <= 1e-8:
        raise ValueError("肘关节主骨长度无效")
    if any(
        bone.hotools_boneprops.hoAux.moduleId == _module_id(side)
        for bone in iter_hoaux_bones(armature_data)
    ):
        raise ValueError(f"{_module_id(side)} 已存在")
    return upper_arm, lower_arm


def _direction(frame, sign, angle_degrees):
    direction = frame.x_axis * sign
    if abs(angle_degrees) > 1e-8:
        direction = Quaternion(frame.y_axis, radians(angle_degrees)) @ direction
    return direction.normalized()


def build_plan(armature_object, upper_arm_name, lower_arm_name, side, parameters=None):
    upper_arm, lower_arm = validate_roles(
        armature_object, upper_arm_name, lower_arm_name, side
    )
    parameters = parameters or Parameters()
    frame = build_joint_frame(
        upper_arm,
        lower_arm,
        convex_axis=parameters.convex_axis,
        roll_follow=parameters.roll_follow,
        twist_offset_degrees=parameters.twist_offset_degrees,
        straight_threshold_degrees=parameters.straight_threshold_degrees,
    )
    result = []
    marker_specs = (
        ("Z1", 1.0, parameters.z1_angle_degrees, parameters.z1_scale),
        ("Z0", -1.0, parameters.z0_angle_degrees, parameters.z0_scale),
    )
    role_specs = (
        (
            "TRK",
            parameters.track_length_ratio,
            parameters.track_head_along,
            parameters.track_head_convex,
        ),
        (
            "DEF",
            parameters.deform_length_ratio,
            parameters.deform_head_along,
            parameters.deform_head_convex,
        ),
    )
    for role_tag, length_ratio, head_along, head_convex in role_specs:
        head = (
            frame.origin
            + frame.y_axis * lower_arm.length * head_along
            + frame.x_axis * lower_arm.length * head_convex
        )
        for marker, sign, angle, scale in marker_specs:
            direction = _direction(frame, sign, angle)
            result.append(
                PlannedBone(
                    resource_key=f"ARM.{side}.ELBOW_VOLUME.{role_tag}.{marker}",
                    preferred_name=f"{role_tag}_Elbow_Volume_{marker}_{side}",
                    role_tag=role_tag,
                    marker=marker,
                    head=head.copy(),
                    tail=head + direction * lower_arm.length * length_ratio * scale,
                    roll_reference=frame.z_axis,
                    parent_name=upper_arm.name,
                )
            )
    return result


def generate(armature_object, upper_arm_name, lower_arm_name, side, parameters=None):
    parameters = parameters or Parameters()
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
        lower_head + lower_direction * lower_length * parameters.dir_length_ratio
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
                influence=parameters.half_influence,
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
                influence=parameters.half_influence,
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
                influence=parameters.track_rotation_influence,
            )
            def_pose = armature_object.pose.bones[def_name]
            add_copy_rotation(
                def_pose,
                armature_object,
                trk_name,
                transaction,
                target_space="LOCAL_WITH_PARENT",
                influence=parameters.deform_rotation_influence,
            )
            copy_location = add_copy_location(
                def_pose,
                armature_object,
                trk_name,
                transaction,
                head_tail=parameters.copy_location_head_tail,
            )
            add_transform_driver(
                copy_location,
                "influence",
                armature_object,
                trk_name,
                "ROT_Z",
                response_expression(parameters.response_angle_degrees),
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
    label = "Elbow Volume"
    order = 40
    settings_class = PG_HoAuxElbowVolumeSettings
    settings_attr = SETTINGS_ATTR
    required_roles = (
        ("upperArmBone", "UpperArm"),
        ("lowerArmBone", "LowerArm"),
    )
    parameter_rows = (
        ("track_length", "deform_length"),
        ("dir_length", "half_influence"),
        ("track_rotation_influence", "deform_rotation_influence"),
        ("response_angle", "head_tail"),
        ("convex_axis", "roll_follow"),
        ("twist_offset", "straight_threshold"),
        ("track_head_along", "track_head_convex"),
        ("deform_head_along", "deform_head_convex"),
        ("z1_angle", "z0_angle"),
        ("z1_scale", "z0_scale"),
    )

    def generate_from_context(self, context):
        root = context.scene.hoaux_settings
        return generate(
            context.object,
            root.upperArmBone,
            root.lowerArmBone,
            root.side,
            parameters_from_settings(self.settings(context.scene)),
        )

    def build_preview_scene(self, context):
        from ..preview_draw import PreviewScene, ROLE_LINE_STYLES

        obj = context.object
        root = context.scene.hoaux_settings
        parameters = parameters_from_settings(self.settings(context.scene))
        plans = build_plan(
            obj,
            root.upperArmBone,
            root.lowerArmBone,
            root.side,
            parameters,
        )
        lower_arm = obj.data.bones[root.lowerArmBone]
        direction_tail = lower_arm.head_local + (
            lower_arm.tail_local - lower_arm.head_local
        ).normalized() * lower_arm.length * parameters.dir_length_ratio
        scene = PreviewScene(obj.name, title=self.label)
        scene.add_planned_bones(plans, labels=True)
        scene.add_segment(
            lower_arm.head_local,
            direction_tail,
            ROLE_LINE_STYLES["DIR"],
        )
        scene.add_label(direction_tail, f"DIR LowerArm HALF ({parameters.half_influence:.2f})")
        scene.add_point(lower_arm.head_local)
        return scene

DEFINITION = ElbowVolumeDefinition()
