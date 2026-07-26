import math
import sys
from pathlib import Path

import bpy
from bpy.props import PointerProperty
from bpy.types import PropertyGroup


ADDON_DIR = Path(__file__).resolve().parents[3]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools import hoAux
from BoneTools.hoAux.ir.blender_reader import snapshot_armature
from BoneTools.hoAux.joint_frame import build_joint_frame
from BoneTools.hoAux.modules import shoulder_volume
from BoneTools.hoAux.generation import (
    GenerationTransaction,
    SharedDirectionSpec,
    iter_hoaux_bones,
    validate_shared_direction,
)
from BoneTools.hoAux.operations import remove_scope
from BoneTools.hoAux.preview import PreviewScene, ROLE_LINE_STYLES
from BoneTools.hoAux.properties import PG_HoAuxBoneInfo


class _TestBoneProps(PropertyGroup):
    hoAux: PointerProperty(type=PG_HoAuxBoneInfo)


hoAux.register()
bpy.utils.register_class(_TestBoneProps)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=_TestBoneProps)

armature = bpy.data.armatures.new("ShoulderVolumeArmature")
obj = bpy.data.objects.new("ShoulderVolume", armature)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
shoulder = armature.edit_bones.new("Shoulder_L")
shoulder.head = (0.1, -0.2, 0.3)
shoulder.tail = (0.8, 0.1, 0.6)
shoulder.roll = 0.37
upper = armature.edit_bones.new("UpperArm_L")
upper.head = shoulder.tail
upper.tail = (1.8, 0.9, 0.2)
upper.roll = -0.42
upper.parent = shoulder
bpy.ops.object.mode_set(mode="OBJECT")

armature.bones["Shoulder_L"].use_deform = False
armature.bones["UpperArm_L"].use_deform = True
main_deform_before = {
    name: armature.bones[name].use_deform
    for name in ("Shoulder_L", "UpperArm_L")
}

shoulder_data = armature.bones["Shoulder_L"]
upper_data = armature.bones["UpperArm_L"]
frame = build_joint_frame(shoulder_data, upper_data)
assert frame.uses_bend_plane
assert frame.bend_angle_degrees > 5.0
assert abs(frame.x_axis.dot(frame.y_axis)) < 1e-6
assert abs(frame.z_axis.dot(frame.y_axis)) < 1e-6
assert abs(frame.x_axis.dot(frame.z_axis)) < 1e-6
assert abs(frame.x_axis.length - 1.0) < 1e-6
assert abs(frame.z_axis.length - 1.0) < 1e-6

plans = shoulder_volume.build_plan(
    obj,
    "Shoulder_L",
    "UpperArm_L",
    "L",
    shoulder_volume.Parameters(),
)
x1_plan = next(
    plan for plan in plans if plan.role_tag == "TRK" and plan.marker == "X1"
)
x1_direction = (x1_plan.tail - x1_plan.head).normalized()
assert x1_direction.dot(frame.z_axis) > 0.999999

preview_scene = PreviewScene(obj.name)
preview_scene.add_planned_bones(plans)
preview_scene.add_polyline(
    ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)),
    ROLE_LINE_STYLES["GUIDE"],
)
preview_scene.add_circle(
    upper_data.head_local,
    frame.y_axis,
    upper_data.length * 0.1,
    ROLE_LINE_STYLES["GUIDE"],
    segments=8,
)
preview_scene.add_point(upper_data.head_local)
assert len(preview_scene.lines) == len(plans) + 2 + 8
assert len(preview_scene.points) == 1

with GenerationTransaction(obj) as transaction:
    bpy.ops.object.mode_set(mode="EDIT")
    rollback_bone = armature.edit_bones.new("HoAux_Rollback_Probe")
    rollback_bone.head = (0.0, 0.0, 0.0)
    rollback_bone.tail = (0.0, 0.1, 0.0)
    transaction.track_bone(rollback_bone.name)
    bpy.ops.object.mode_set(mode="OBJECT")
assert "HoAux_Rollback_Probe" not in armature.bones

bpy.ops.object.mode_set(mode="POSE")
result = shoulder_volume.generate(
    obj,
    "Shoulder_L",
    "UpperArm_L",
    "L",
)
assert obj.mode == "POSE"
generated = list(iter_hoaux_bones(armature))
assert len(generated) == 9
assert len(result["bones"]) == 8
assert {bone.hotools_boneprops.hoAux.roleTag for bone in generated} == {
    "DEF",
    "TRK",
    "DIR",
}
assert sum(bone.use_deform for bone in generated) == 4
assert main_deform_before == {
    name: armature.bones[name].use_deform
    for name in ("Shoulder_L", "UpperArm_L")
}

constraint_count = sum(
    len(obj.pose.bones[bone.name].constraints) for bone in generated
)
assert constraint_count == 13
assert len(obj.animation_data.drivers) == 4
assert all(
    target.rotation_mode == "QUATERNION"
    for fcurve in obj.animation_data.drivers
    for variable in fcurve.driver.variables
    for target in variable.targets
)

dir_bone = armature.bones[result["dir"]]
dir_constraint = obj.pose.bones[result["dir"]].constraints["HoAux Half Rotation"]
upper_data = armature.bones["UpperArm_L"]
dir_spec = SharedDirectionSpec(
    parent_name="Shoulder_L",
    source_name="UpperArm_L",
    head=upper_data.head_local,
    tail=dir_bone.tail_local,
    roll_reference=upper_data.matrix_local.to_3x3().col[2],
    influence=0.5,
)
assert validate_shared_direction(obj, dir_bone, dir_spec) == dir_bone
dir_constraint.influence = 0.4
try:
    validate_shared_direction(obj, dir_bone, dir_spec)
except ValueError as exc:
    assert "influence" in str(exc)
else:
    raise AssertionError("mismatched shared DIR signature was accepted")
dir_constraint.influence = 0.5

upper_pose = obj.pose.bones["UpperArm_L"]
upper_pose.rotation_mode = "XYZ"
upper_pose.rotation_euler.x = math.radians(45.0)
bpy.context.view_layer.update()
x1_name = next(
    bone.name
    for bone in generated
    if bone.hotools_boneprops.hoAux.roleTag == "DEF"
    and bone.hotools_boneprops.hoAux.marker == "X1"
)
influence = obj.pose.bones[x1_name].constraints["HoAux Copy Location"].influence
assert abs(influence - 0.25) < 1e-4, influence

snapshot = snapshot_armature(obj)
assert all(
    item.status == "RESOLVED"
    for item in snapshot.resources
    if item.resource_kind in {"CONSTRAINT", "DRIVER_VARIABLE"}
)

removed = remove_scope(obj)
assert removed["bones"] == 9
assert "Shoulder_L" in armature.bones
assert "UpperArm_L" in armature.bones
assert main_deform_before == {
    name: armature.bones[name].use_deform
    for name in ("Shoulder_L", "UpperArm_L")
}

print(
    "HOAUX_SHOULDER_OK "
    f"constraints={constraint_count} drivers=4 influence={influence:.6f}"
)
