"""Wrist volume system from WholeLeftArm_Constraint_Driver."""

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
    signed_response_expression,
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


MODULE_TYPE = "WRIST_VOLUME"
SETTINGS_ATTR = "hoaux_wrist_volume_settings"
DIR_SHARED_KEY = "ROTATION_HALF:HAND:{side}"
DIR_LENGTH_RATIO = 0.05
SECONDARY_LENGTH_RATIO = 0.13
HALF_INFLUENCE = 0.5
RESPONSE_ANGLE_DEGREES = 90.0
CONVEX_AXIS = "X"
ROLL_FOLLOW = 1.0
STRAIGHT_THRESHOLD_DEGREES = 5.0


_toggle_preview = preview_toggle(MODULE_TYPE)


class PG_HoAuxWristVolumeSettings(PropertyGroup):
    ui_expanded: BoolProperty(name="手腕体积保持设置", default=False)  # type: ignore
    preview_enabled: BoolProperty(
        name="预览", default=False, update=_toggle_preview
    )  # type: ignore
    track_length: FloatProperty(
        name="TRK长度", default=0.22, min=0.05, max=2.0, update=refresh_preview
    )  # type: ignore
    deform_length: FloatProperty(
        name="DEF长度", default=0.18, min=0.05, max=2.0, update=refresh_preview
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
    track_length_ratio: float = 0.22
    deform_length_ratio: float = 0.18
    twist_offset_degrees: float = 0.0


def parameters_from_settings(settings):
    return Parameters(
        track_length_ratio=settings.track_length,
        deform_length_ratio=settings.deform_length,
        twist_offset_degrees=settings.twist_offset,
    )


def _module_id(side):
    return f"WRIST_VOLUME.{side}"


def _pipeline_id(side):
    return f"ARM.{side}"


def _direction_specs():
    return (
        ("X1", Vector((0.0, 0.0, 1.0)), Vector((1.0, 0.0, 0.0))),
        ("X0", Vector((0.0, 0.0, -1.0)), Vector((1.0, 0.0, 0.0))),
        ("Y0", Vector((-1.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0))),
        ("Y1", Vector((1.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0))),
    )


def _existing_module_bones(armature_data, side):
    module_id = _module_id(side)
    return [
        bone
        for bone in iter_hoaux_bones(armature_data)
        if bone.hotools_boneprops.hoAux.moduleId == module_id
    ]


def validate_roles(armature_object, lower_arm_name, hand_name, side):
    if armature_object is None or armature_object.type != "ARMATURE":
        raise ValueError("请选择骨架")
    armature_data = armature_object.data
    lower_arm = armature_data.bones.get(lower_arm_name)
    hand = armature_data.bones.get(hand_name)
    if lower_arm is None or hand is None:
        raise ValueError("请设置小臂骨和手骨")
    if lower_arm == hand:
        raise ValueError("小臂骨和手骨不能相同")
    side = require_side(side, lower_arm_name, hand_name)
    if lower_arm.length <= 1e-8 or hand.length <= 1e-8:
        raise ValueError("小臂骨或手骨长度无效")
    if _existing_module_bones(armature_data, side):
        raise ValueError(f"{_module_id(side)} 已存在")
    return lower_arm, hand, side


def build_plan(
    armature_object,
    lower_arm_name,
    hand_name,
    side,
    parameters=None,
):
    lower_arm, hand, side = validate_roles(
        armature_object, lower_arm_name, hand_name, side
    )
    parameters = parameters or Parameters()
    frame = build_joint_frame(
        lower_arm,
        hand,
        convex_axis=CONVEX_AXIS,
        roll_follow=ROLL_FOLLOW,
        twist_offset_degrees=parameters.twist_offset_degrees,
        straight_threshold_degrees=STRAIGHT_THRESHOLD_DEGREES,
    )
    plans = []
    for role_tag, ratio in (
        ("TRK", parameters.track_length_ratio),
        ("DEF", parameters.deform_length_ratio),
    ):
        for marker, local_direction, local_roll in _direction_specs():
            plans.append(
                PlannedBone(
                    resource_key=f"ARM.{side}.WRIST_VOLUME.{role_tag}.{marker}",
                    preferred_name=f"{role_tag}_Wrist_Volume_{marker}_{side}",
                    role_tag=role_tag,
                    marker=marker,
                    head=frame.origin.copy(),
                    tail=(
                        frame.origin
                        + frame.transform_direction(local_direction)
                        * hand.length
                        * ratio
                    ),
                    roll_reference=frame.transform_direction(local_roll),
                    parent_name=lower_arm.name,
                )
            )
    plans.append(
        PlannedBone(
            resource_key=f"ARM.{side}.WRIST_VOLUME.TRK.X0_SECONDARY",
            preferred_name=f"TRK_Wrist_Volume2_X0_{side}",
            role_tag="TRK",
            marker="X0_SECONDARY",
            head=frame.origin.copy(),
            tail=frame.origin + frame.y_axis * hand.length * SECONDARY_LENGTH_RATIO,
            roll_reference=frame.z_axis,
            parent_name=lower_arm.name,
        )
    )
    return plans


def generate(
    armature_object,
    lower_arm_name,
    hand_name,
    side,
    parameters=None,
):
    parameters = parameters or Parameters()
    side = require_side(side, lower_arm_name, hand_name)
    plans = build_plan(
        armature_object, lower_arm_name, hand_name, side, parameters
    )
    armature_data = armature_object.data
    hand = armature_data.bones[hand_name]
    hand_head = hand.head_local.copy()
    hand_direction = (hand.tail_local - hand.head_local).normalized()
    hand_roll = hand.matrix_local.to_3x3() @ Vector((0.0, 0.0, 1.0))
    expected_dir_tail = hand_head + hand_direction * hand.length * DIR_LENGTH_RATIO
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
                parent_name=lower_arm_name,
                source_name=hand_name,
                head=hand_head,
                tail=expected_dir_tail,
                roll_reference=hand_roll,
                influence=HALF_INFLUENCE,
            ),
        )

    actual_names = {
        plan.resource_key: allocate_bone_name(armature_data, plan.preferred_name)
        for plan in plans
    }
    dir_name = existing_dir.name if existing_dir else allocate_bone_name(
        armature_data, f"DIR_Hand_Rotation_HALF_{side}"
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
                direction.head = hand_head
                direction.tail = expected_dir_tail
                direction.parent = edit_bones.get(lower_arm_name)
                direction.use_connect = False
                direction.align_roll(hand_roll)
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
                part="Hand",
                function="RotationHalf",
                marker="HAND_HALF",
                side=side,
                name_key=f"ARM.{side}.ROTATION_HALF.DIR.HAND",
                shared_key=shared_key,
            )
            assign_bone(armature_data, direction_bone)
            add_copy_rotation(
                armature_object.pose.bones[dir_name],
                armature_object,
                hand_name,
                transaction,
                name="HoAux Half Rotation",
                owner_space="LOCAL",
                target_space="LOCAL",
                influence=HALF_INFLUENCE,
            )

        for plan in plans:
            data_bone = armature_data.bones[actual_names[plan.resource_key]]
            write_bone_metadata(
                data_bone,
                rig_id=rig_id,
                pipeline_id=pipeline_id,
                module_id=module_id,
                module_type=MODULE_TYPE,
                generation_id=generation_id,
                role_tag=plan.role_tag,
                part="Wrist",
                function="Volume",
                marker=plan.marker,
                side=side,
                name_key=plan.resource_key,
            )
            assign_bone(armature_data, data_bone)

        by_marker = {
            (plan.role_tag, plan.marker): actual_names[plan.resource_key]
            for plan in plans
        }
        for marker, _direction, _roll in _direction_specs():
            trk_name = by_marker[("TRK", marker)]
            def_name = by_marker[("DEF", marker)]
            add_copy_rotation(
                armature_object.pose.bones[trk_name],
                armature_object,
                dir_name,
                transaction,
            )
            def_pose = armature_object.pose.bones[def_name]
            add_copy_rotation(def_pose, armature_object, dir_name, transaction)
            target_marker = {"Y0": "Y1", "Y1": "Y0"}.get(marker, marker)
            copy_location = add_copy_location(
                def_pose,
                armature_object,
                by_marker[("TRK", target_marker)],
                transaction,
                head_tail=1.0,
            )
            expression = (
                signed_response_expression(
                    RESPONSE_ANGLE_DEGREES, sign=-1.0
                )
                if marker == "X0"
                else response_expression(RESPONSE_ANGLE_DEGREES)
            )
            add_transform_driver(
                copy_location,
                "influence",
                armature_object,
                dir_name,
                f"ROT_{marker[0] if marker.startswith('X') else 'Z'}",
                expression,
                transaction,
            )

        secondary_name = by_marker[("TRK", "X0_SECONDARY")]
        secondary_pose = armature_object.pose.bones[secondary_name]
        add_copy_rotation(
            secondary_pose, armature_object, dir_name, transaction
        )
        secondary_location = add_copy_location(
            secondary_pose,
            armature_object,
            by_marker[("TRK", "X0")],
            transaction,
            head_tail=1.0,
        )
        add_transform_driver(
            secondary_location,
            "influence",
            armature_object,
            dir_name,
            "ROT_X",
            signed_response_expression(RESPONSE_ANGLE_DEGREES, sign=-1.0),
            transaction,
        )
        x0_secondary = add_copy_location(
            armature_object.pose.bones[by_marker[("DEF", "X0")]],
            armature_object,
            secondary_name,
            transaction,
            head_tail=1.0,
        )
        add_transform_driver(
            x0_secondary,
            "influence",
            armature_object,
            dir_name,
            "ROT_X",
            signed_response_expression(
                RESPONSE_ANGLE_DEGREES, multiplier=2.0
            ),
            transaction,
        )

        transaction.commit()
    return {
        "dir": dir_name,
        "bones": [actual_names[plan.resource_key] for plan in plans],
        "createdDir": existing_dir is None,
        "generationId": generation_id,
    }


class WristVolumeDefinition(ModuleDefinition):
    type_id = MODULE_TYPE
    label = "手腕体积保持"
    order = 10
    settings_class = PG_HoAuxWristVolumeSettings
    settings_attr = SETTINGS_ATTR
    required_roles = (
        ("lowerArmBone", "小臂骨"),
        ("handBone", "手骨"),
    )
    parameter_rows = (
        ("track_length", "deform_length"),
        ("twist_offset",),
    )

    def generate_from_context(self, context):
        root = context.scene.hoaux_settings
        parameters = parameters_from_settings(self.settings(context.scene))
        bone_names = (root.lowerArmBone, root.handBone)
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
            context, root.lowerArmBone, root.handBone
        ):
            plans = build_plan(obj, *names, side, parameters)
            hand = obj.data.bones[names[1]]
            direction_tail = hand.head_local + (
                hand.tail_local - hand.head_local
            ).normalized() * hand.length * DIR_LENGTH_RATIO
            scene.add_planned_bones(plans, labels=True)
            scene.add_segment(
                hand.head_local, direction_tail, ROLE_LINE_STYLES["DIR"]
            )
            scene.add_label(direction_tail, f"DIR 手部半旋转 {side}（0.50）")
            scene.add_point(hand.head_local)
        return scene


DEFINITION = WristVolumeDefinition()
