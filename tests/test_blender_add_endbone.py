import sys
from pathlib import Path

import bpy
from bpy.props import BoolProperty, PointerProperty
from bpy.types import PropertyGroup


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools import boneOperators
from Utils import bone_utils


class TestBoneProps(PropertyGroup):
    endBone: BoolProperty(default=False)


bpy.utils.register_class(TestBoneProps)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=TestBoneProps)
bpy.utils.register_class(boneOperators.OP_AddEndBone)

armature_data = bpy.data.armatures.new("AddEndBoneContractData")
armature = bpy.data.objects.new("AddEndBoneContract", armature_data)
bpy.context.scene.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")

root = armature_data.edit_bones.new("root")
root.head = (0.0, 0.0, 0.0)
root.tail = (0.0, 0.0, 1.0)

tip_a = armature_data.edit_bones.new("tip_a")
tip_a.head = (-0.5, 0.0, 1.2)
tip_a.tail = (-0.5, 0.0, 2.2)
tip_a.parent = root
tip_a.use_connect = False

tip_b = armature_data.edit_bones.new("tip_b")
tip_b.head = (0.5, 0.0, 1.2)
tip_b.tail = (0.5, 0.0, 2.2)
tip_b.parent = root
tip_b.use_connect = False

# 只选中父骨时，不能遍历并处理未选中的末端骨。
bone_utils.select_bones(armature, ["root"])
assert bpy.ops.ho.add_endbone(length_factor=0.1) == {"FINISHED"}
assert armature_data.edit_bones.get("tip_a_end") is None
assert armature_data.edit_bones.get("tip_b_end") is None

# 只选中一个断连末端时，仅它获得叶骨。
bone_utils.select_bones(armature, ["tip_a"])
assert bpy.ops.ho.add_endbone(length_factor=0.1) == {"FINISHED"}
assert armature_data.edit_bones.get("tip_a_end") is not None
assert armature_data.edit_bones.get("tip_b_end") is None
assert bone_utils.selected_bone_names(bpy.context, armature) == ["tip_a_end"]
assert armature_data.edit_bones.active.name == "tip_a_end"

print("ADD_ENDBONE_CONTRACT_OK", bpy.app.version_string)
