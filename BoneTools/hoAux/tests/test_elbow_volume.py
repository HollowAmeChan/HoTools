import sys
from pathlib import Path

import bpy
from bpy.props import PointerProperty
from bpy.types import PropertyGroup


BONE_TOOLS_DIR = Path(__file__).resolve().parents[2]
if str(BONE_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(BONE_TOOLS_DIR))

import hoAux
from hoAux.ir.blender_reader import snapshot_armature
from hoAux.joint_frame import build_joint_frame
from hoAux.module_base import get_definition
from hoAux.modules import elbow_volume
from hoAux.generation import iter_hoaux_bones
from hoAux.operations import remove_scope
from hoAux.properties import PG_HoAuxBoneInfo


class _TestBoneProps(PropertyGroup):
    hoAux: PointerProperty(type=PG_HoAuxBoneInfo)


hoAux.register()
bpy.utils.register_class(_TestBoneProps)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=_TestBoneProps)

armature = bpy.data.armatures.new("ElbowVolumeArmature")
obj = bpy.data.objects.new("ElbowVolume", armature)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
upper = armature.edit_bones.new("UpperArm_L")
upper.head = (0.0, 0.0, 0.0)
upper.tail = (0.0, 1.0, 0.0)
upper.roll = 0.31
lower = armature.edit_bones.new("LowerArm_L")
lower.head = upper.tail
lower.tail = (0.8, 1.65, 0.35)
lower.roll = -0.47
bpy.ops.object.mode_set(mode="OBJECT")

armature.bones["UpperArm_L"].use_deform = False
armature.bones["LowerArm_L"].use_deform = True
main_deform_before = {
    name: armature.bones[name].use_deform
    for name in ("UpperArm_L", "LowerArm_L")
}

frame = build_joint_frame(
    armature.bones["UpperArm_L"], armature.bones["LowerArm_L"]
)
assert frame.uses_bend_plane
assert frame.bend_angle_degrees > 5.0

root = bpy.context.scene.hoaux_settings
root.upperArmBone = "UpperArm_L"
root.lowerArmBone = "LowerArm_L"
definition = get_definition("ELBOW_VOLUME")
assert definition is elbow_volume.DEFINITION
preview_scene = definition.build_preview_scene(bpy.context)
assert len(preview_scene.lines) == 5
assert len(preview_scene.points) == 1
assert len(preview_scene.labels) == 5

result = definition.generate_from_context(bpy.context)
generated = list(iter_hoaux_bones(armature))
assert result["createdDir"] is True
assert len(result["bones"]) == 4
assert len(generated) == 5
assert sum(bone.use_deform for bone in generated) == 2
assert main_deform_before == {
    name: armature.bones[name].use_deform
    for name in ("UpperArm_L", "LowerArm_L")
}

dir_pose = obj.pose.bones[result["dir"]]
dir_constraint = dir_pose.constraints["HoAux Half Rotation"]
assert dir_constraint.owner_space == "WORLD"
assert dir_constraint.target_space == "WORLD"
assert dir_constraint.subtarget == "LowerArm_L"
assert abs(dir_constraint.influence - 0.5) < 1e-8

constraint_count = sum(
    len(obj.pose.bones[bone.name].constraints) for bone in generated
)
assert constraint_count == 7
assert len(obj.animation_data.drivers) == 2
for bone in generated:
    info = bone.hotools_boneprops.hoAux
    pose = obj.pose.bones[bone.name]
    if info.roleTag == "TRK":
        constraint = pose.constraints["HoAux Copy Rotation"]
        assert constraint.owner_space == "LOCAL"
        assert constraint.target_space == "LOCAL_OWNER_ORIENT"
    elif info.roleTag == "DEF":
        rotation = pose.constraints["HoAux Copy Rotation"]
        location = pose.constraints["HoAux Copy Location"]
        assert rotation.target_space == "LOCAL_WITH_PARENT"
        assert location.target_space == "WORLD"
        assert location.owner_space == "WORLD"
        assert abs(location.head_tail - 1.0) < 1e-8

for fcurve in obj.animation_data.drivers:
    assert fcurve.driver.expression == "abs(asin(var)*4/pi)"
    target = fcurve.driver.variables[0].targets[0]
    assert target.bone_target.startswith("TRK_Elbow_Volume_Z")
    assert target.transform_type == "ROT_Z"
    assert target.transform_space == "LOCAL_SPACE"
    assert target.rotation_mode == "QUATERNION"

snapshot = snapshot_armature(obj)
assert all(
    resource.status == "RESOLVED"
    for resource in snapshot.resources
    if resource.resource_kind in {"CONSTRAINT", "DRIVER_VARIABLE"}
)

removed = remove_scope(obj, "ARM.L", "ELBOW_VOLUME.L")
assert removed["bones"] == 5
assert "UpperArm_L" in armature.bones
assert "LowerArm_L" in armature.bones
assert main_deform_before == {
    name: armature.bones[name].use_deform
    for name in ("UpperArm_L", "LowerArm_L")
}

print(
    "HOAUX_ELBOW_OK "
    f"constraints={constraint_count} drivers=2 bend={frame.bend_angle_degrees:.3f}"
)
