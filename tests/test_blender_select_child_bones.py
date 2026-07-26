import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools import boneOperators
from Utils import bone_utils


bpy.utils.register_class(boneOperators.OP_SelectAllChildBones)

armature_data = bpy.data.armatures.new("SelectChildBonesData")
armature = bpy.data.objects.new("SelectChildBones", armature_data)
bpy.context.scene.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")


def add_bone(name, head, tail, parent=None):
    bone = armature_data.edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    bone.parent = parent
    bone.use_connect = False
    return bone


root_a = add_bone("root_a", (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
child_a = add_bone("child_a", (0.2, 1.2, 0.0), (0.2, 2.2, 0.0), root_a)
grandchild_a = add_bone(
    "grandchild_a",
    (0.4, 2.4, 0.0),
    (0.4, 3.4, 0.0),
    child_a,
)
root_b = add_bone("root_b", (2.0, 0.0, 0.0), (2.0, 1.0, 0.0))
child_b = add_bone("child_b", (2.2, 1.2, 0.0), (2.2, 2.2, 0.0), root_b)
add_bone("unrelated", (4.0, 0.0, 0.0), (4.0, 1.0, 0.0))

expected = {"root_a", "child_a", "grandchild_a", "root_b", "child_b"}

# 编辑模式下多选两个根骨，并显式清空活动骨。
bone_utils.select_bones(armature, ["root_a", "root_b"])
armature_data.edit_bones.active = None
assert bpy.context.active_bone is None
assert boneOperators.OP_SelectAllChildBones.poll(bpy.context)
assert bpy.ops.ho.select_all_child_bones() == {"FINISHED"}
assert set(bone_utils.selected_bone_names(bpy.context, armature)) == expected

# 姿态模式下重复多选和无活动骨场景。
bpy.ops.object.mode_set(mode="POSE")
bone_utils.select_bones(armature, ["root_a", "root_b"])
armature_data.bones.active = None
assert bpy.context.active_bone is None
assert boneOperators.OP_SelectAllChildBones.poll(bpy.context)
assert bpy.ops.ho.select_all_child_bones() == {"FINISHED"}
assert set(bone_utils.selected_bone_names(bpy.context, armature)) == expected

# 祖先与子骨同时作为入口时，重叠子树应去重且不能漏掉孙级。
bone_utils.select_bones(armature, ["root_a", "child_a", "root_b"])
armature_data.bones.active = None
assert bpy.ops.ho.select_all_child_bones() == {"FINISHED"}
assert set(bone_utils.selected_bone_names(bpy.context, armature)) == expected

# 只选中末端骨时安全取消，并保留当前选择。
bone_utils.select_bones(armature, ["grandchild_a"])
armature_data.bones.active = None
assert bpy.ops.ho.select_all_child_bones() == {"CANCELLED"}
assert bone_utils.selected_bone_names(bpy.context, armature) == ["grandchild_a"]

print("SELECT_CHILD_BONES_OK", bpy.app.version_string)
