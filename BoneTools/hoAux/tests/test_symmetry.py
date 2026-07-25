import sys
from pathlib import Path

import bpy
from bpy.props import PointerProperty
from bpy.types import PropertyGroup


BONE_TOOLS_DIR = Path(__file__).resolve().parents[2]
if str(BONE_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(BONE_TOOLS_DIR))

import hoAux
from boneUtils import BoneUtils
from hoAux.module_registry import get_definition
from hoAux.name_registry import iter_hoaux_bones
from hoAux.operations import remove_scope
from hoAux.properties import PG_HoAuxBoneInfo


class _TestBoneProps(PropertyGroup):
    hoAux: PointerProperty(type=PG_HoAuxBoneInfo)


hoAux.register()
bpy.utils.register_class(_TestBoneProps)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=_TestBoneProps)

armature = bpy.data.armatures.new("HoAuxSymmetryArmature")
obj = bpy.data.objects.new("HoAuxSymmetry", armature)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
for side, sign in (("L", 1.0), ("R", -1.0)):
    shoulder = armature.edit_bones.new(f"Shoulder_{side}")
    shoulder.head = (sign * 0.1, 0.0, 0.0)
    shoulder.tail = (sign * 0.4, 0.35, 0.15)
    shoulder.roll = sign * 0.21
    upper = armature.edit_bones.new(f"UpperArm_{side}")
    upper.head = shoulder.tail
    upper.tail = (sign * 1.25, 0.95, -0.1)
    upper.roll = sign * -0.38

unpaired = armature.edit_bones.new("Unpaired_L")
unpaired.head = (0.0, 0.0, 0.0)
unpaired.tail = (0.0, 0.2, 0.0)
bpy.ops.object.mode_set(mode="OBJECT")

try:
    BoneUtils.mirrored_role_names(armature, "Unpaired_L", "UpperArm_L")
except ValueError as exc:
    assert "Unpaired_R" in str(exc)
else:
    raise AssertionError("missing mirror role was accepted")

root = bpy.context.scene.hoaux_settings
root.shoulderBone = "Shoulder_L"
root.upperArmBone = "UpperArm_L"
root.processSymmetry = True
definition = get_definition("SHOULDER_VOLUME")
preview = definition.build_preview_scene(bpy.context)
assert len(preview.lines) == 18
assert len(preview.points) == 2
assert len(preview.labels) == 18

bpy.ops.object.mode_set(mode="POSE")
result = definition.generate_from_context(bpy.context)
assert obj.mode == "POSE"
assert len(result["bones"]) == 16
assert result["createdDirCount"] == 2
generated = list(iter_hoaux_bones(armature))
assert len(generated) == 18
assert sum(bone.hotools_boneprops.hoAux.side == "L" for bone in generated) == 9
assert sum(bone.hotools_boneprops.hoAux.side == "R" for bone in generated) == 9
assert all(
    len(
        [
            collection
            for collection in bone.collections
            if collection.get("hoaux_key")
        ]
    )
    == 1
    for bone in generated
)
assert all(
    target.rotation_mode == "QUATERNION"
    for fcurve in obj.animation_data.drivers
    for variable in fcurve.driver.variables
    for target in variable.targets
)

removed = remove_scope(obj)
assert removed["bones"] == 18
assert "Shoulder_L" in armature.bones
assert "Shoulder_R" in armature.bones
print("HOAUX_SYMMETRY_OK bones=18 drivers=8 mode=POSE")
