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
from hoAux.module_registry import get_definition
from hoAux.modules import limb_twist
from hoAux.name_registry import iter_hoaux_bones
from hoAux.operations import remove_scope
from hoAux.properties import PG_HoAuxBoneInfo


class _TestBoneProps(PropertyGroup):
    hoAux: PointerProperty(type=PG_HoAuxBoneInfo)


hoAux.register()
bpy.utils.register_class(_TestBoneProps)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=_TestBoneProps)

armature = bpy.data.armatures.new("LimbTwistArmature")
obj = bpy.data.objects.new("LimbTwist", armature)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
upper = armature.edit_bones.new("UpperArm_L")
upper.head = (0.0, 0.0, 0.0)
upper.tail = (0.0, 1.2, 0.0)
upper.roll = 0.27
lower = armature.edit_bones.new("LowerArm_L")
lower.head = upper.tail
lower.tail = (0.65, 2.0, 0.25)
lower.roll = -0.36
lower.parent = upper
hand = armature.edit_bones.new("Hand_L")
hand.head = lower.tail
hand.tail = (1.0, 2.35, 0.35)
hand.roll = 0.14
hand.parent = lower
bpy.ops.object.mode_set(mode="OBJECT")

armature.bones["UpperArm_L"].use_deform = False
armature.bones["LowerArm_L"].use_deform = True
armature.bones["Hand_L"].use_deform = False
main_deform_before = {
    name: armature.bones[name].use_deform
    for name in ("UpperArm_L", "LowerArm_L", "Hand_L")
}

root = bpy.context.scene.hoaux_settings
root.side = "L"
root.upperArmBone = "UpperArm_L"
root.lowerArmBone = "LowerArm_L"
root.handBone = "Hand_L"
forearm_definition = get_definition("FOREARM_TWIST")
upper_definition = get_definition("UPPER_ARM_TWIST")
assert forearm_definition is limb_twist.FOREARM_DEFINITION
assert upper_definition is limb_twist.UPPER_ARM_DEFINITION
assert forearm_definition.settings(bpy.context.scene) != upper_definition.settings(
    bpy.context.scene
)

forearm_preview = forearm_definition.build_preview_scene(bpy.context)
upper_preview = upper_definition.build_preview_scene(bpy.context)
assert len(forearm_preview.points) == 3
assert len(upper_preview.points) == 3
assert len(forearm_preview.labels) == 3
assert len(upper_preview.labels) == 3

upper_result = upper_definition.generate_from_context(bpy.context)
forearm_result = forearm_definition.generate_from_context(bpy.context)
assert len(upper_result["bones"]) == 3
assert len(forearm_result["bones"]) == 3
generated = list(iter_hoaux_bones(armature))
assert len(generated) == 6
assert all(bone.use_deform for bone in generated)
assert main_deform_before == {
    name: armature.bones[name].use_deform
    for name in ("UpperArm_L", "LowerArm_L", "Hand_L")
}

for module_type, target_name in (
    ("UPPER_ARM_TWIST", "LowerArm_L"),
    ("FOREARM_TWIST", "Hand_L"),
):
    module_bones = sorted(
        (
            bone
            for bone in generated
            if bone.hotools_boneprops.hoAux.moduleType == module_type
        ),
        key=lambda bone: bone.hotools_boneprops.hoAux.marker,
        reverse=True,
    )
    assert [bone.hotools_boneprops.hoAux.marker for bone in module_bones] == [
        "03",
        "02",
        "01",
    ]
    expected_influences = (0.1, 0.45, 0.8)
    for bone, expected_influence in zip(module_bones, expected_influences):
        pose = obj.pose.bones[bone.name]
        copy_rotation = pose.constraints["HoAux Twist Copy Rotation"]
        stretch = pose.constraints["HoAux Twist Stretch To"]
        assert copy_rotation.subtarget == target_name
        assert copy_rotation.owner_space == "LOCAL"
        assert copy_rotation.target_space == "LOCAL_OWNER_ORIENT"
        assert abs(copy_rotation.influence - expected_influence) < 1e-6
        assert stretch.subtarget == target_name
        assert stretch.owner_space == "WORLD"
        assert stretch.target_space == "WORLD"
        assert stretch.volume == "NO_VOLUME"
        assert stretch.keep_axis == "SWING_Y"
        assert stretch.rest_length > 0.0

assert sum(len(obj.pose.bones[bone.name].constraints) for bone in generated) == 12
assert obj.animation_data is None or len(obj.animation_data.drivers) == 0

snapshot = snapshot_armature(obj)
stretch_resources = [
    resource
    for resource in snapshot.resources
    if resource.resource_kind == "CONSTRAINT"
    and resource.payload.get("type") == "STRETCH_TO"
]
assert len(stretch_resources) == 6
assert all(resource.status == "RESOLVED" for resource in stretch_resources)
for resource in stretch_resources:
    assert resource.payload["volume"] == "NO_VOLUME"
    assert resource.payload["keepAxis"] == "SWING_Y"
    assert "bulgeSmooth" in resource.payload

removed_upper = remove_scope(obj, "ARM.L", "UPPER_ARM_TWIST.L")
assert removed_upper["bones"] == 3
assert len(list(iter_hoaux_bones(armature))) == 3
removed_forearm = remove_scope(obj, "ARM.L", "FOREARM_TWIST.L")
assert removed_forearm["bones"] == 3
assert not list(iter_hoaux_bones(armature))
assert main_deform_before == {
    name: armature.bones[name].use_deform
    for name in ("UpperArm_L", "LowerArm_L", "Hand_L")
}

print("HOAUX_TWIST_OK bones=6 constraints=12 stretch=6")
