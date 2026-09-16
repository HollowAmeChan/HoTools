import sys
from pathlib import Path
from types import SimpleNamespace

ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from Utils.bone_selection import (
    select_bones,
    selected_bone_names,
    selected_edit_bones,
    selected_pose_bones,
)


class BoneCollection(list):
    active = None

    def get(self, name):
        return next((bone for bone in self if bone.name == name), None)


class DataBone45:
    def __init__(self, name, selected=False):
        self.name = name
        self.select = selected
        self.select_head = selected
        self.select_tail = selected


class DataBone52:
    def __init__(self, name):
        self.name = name


class EditBone:
    def __init__(self, name, *, selected=False, head=False, tail=False,
                 parent=None, use_connect=False):
        self.name = name
        self.select = selected
        self.select_head = head
        self.select_tail = tail
        self.id_data = None
        self.parent = parent
        self.use_connect = use_connect
        self.children = []
        if parent is not None:
            parent.children.append(self)


class PoseBone45:
    def __init__(self, bone):
        self.name = bone.name
        self.bone = bone
        self.id_data = None


class PoseBone52:
    def __init__(self, bone, selected=False):
        self.name = bone.name
        self.bone = bone
        self.select = selected
        self.id_data = None


def make_armature(data_bones, pose_bones, edit_bones=()):
    armature_data = SimpleNamespace(
        bones=BoneCollection(data_bones),
        edit_bones=BoneCollection(edit_bones),
    )
    armature = SimpleNamespace(
        type="ARMATURE",
        mode="OBJECT",
        data=armature_data,
        pose=SimpleNamespace(bones=BoneCollection(pose_bones)),
    )
    for bone in edit_bones:
        bone.id_data = armature_data
    for bone in pose_bones:
        bone.id_data = armature
    return armature


empty_context = SimpleNamespace(
    selected_editable_bones=[],
    selected_bones=[],
    selected_pose_bones_from_active_object=[],
    selected_pose_bones=[],
)


# Blender 4.5：选择状态位于 Bone，且 Object 模式下仍应可读取。
data45_a = DataBone45("A", selected=True)
data45_b = DataBone45("B", selected=False)
arm45 = make_armature(
    [data45_a, data45_b],
    [PoseBone45(data45_a), PoseBone45(data45_b)],
)
assert selected_bone_names(empty_context, arm45) == ["A"]
select_bones(arm45, ["B"], extend=False)
assert selected_bone_names(empty_context, arm45) == ["B"]
assert not data45_a.select and data45_b.select


# Blender 5.2：Bone 不再有 select，选择状态位于 PoseBone。
data52_a = DataBone52("A")
data52_b = DataBone52("B")
pose52_a = PoseBone52(data52_a, selected=True)
pose52_b = PoseBone52(data52_b, selected=False)
arm52 = make_armature([data52_a, data52_b], [pose52_a, pose52_b])
assert not hasattr(data52_a, "select")
assert selected_bone_names(empty_context, arm52) == ["A"]
select_bones(arm52, ["B"], extend=False)
assert selected_bone_names(empty_context, arm52) == ["B"]
assert not pose52_a.select and pose52_b.select


# context 可能包含其它骨架的选择，读取时必须按所属骨架过滤。
other_data = DataBone52("Other")
other_pose = PoseBone52(other_data, selected=True)
other_armature = make_armature([other_data], [other_pose])
foreign_context = SimpleNamespace(
    selected_editable_bones=[],
    selected_bones=[],
    selected_pose_bones_from_active_object=[],
    selected_pose_bones=[other_pose, pose52_b],
)
arm52.mode = "POSE"
assert [bone.name for bone in selected_pose_bones(foreign_context, arm52)] == ["B"]
assert other_armature is not arm52


# 编辑模式还要识别只选择了端点的 EditBone。
edit_a = EditBone("A", head=True)
edit_b = EditBone("B")
arm_edit = make_armature([], [], [edit_a, edit_b])
arm_edit.mode = "EDIT"
assert [bone.name for bone in selected_edit_bones(empty_context, arm_edit)] == ["A"]
select_bones(arm_edit, ["B"], extend=False)
assert selected_bone_names(empty_context, arm_edit) == ["B"]
assert not edit_a.select_head and edit_b.select and edit_b.select_head and edit_b.select_tail


# 相连骨的共享关节不能算作父级被选中：Blender 选中相连子骨骼时会同时点亮父级尾端。
joint_root = EditBone("Root")
joint_mid = EditBone("Mid", parent=joint_root, use_connect=True)
joint_leaf = EditBone("Leaf", parent=joint_mid, use_connect=True)
arm_joint = make_armature([], [], [joint_root, joint_mid, joint_leaf])
arm_joint.mode = "EDIT"

select_bones(arm_joint, ["Mid"], extend=False)
joint_root.select_tail = True  # Blender 的共享关节标记
assert selected_bone_names(empty_context, arm_joint) == ["Mid"]

# 只点亮共享关节（父级尾端 + 子骨骼头端）时，双方都不算被选中。
select_bones(arm_joint, [], extend=False)
joint_root.select_tail = True
joint_mid.select_head = True
assert selected_edit_bones(empty_context, arm_joint) == []

# 未共享的端点仍然可以单独作为选中依据。
joint_root.select_tail = False
joint_mid.select_head = False
joint_leaf.select_tail = True  # Leaf 没有相连子骨骼，尾端属于自己
assert [bone.name for bone in selected_edit_bones(empty_context, arm_joint)] == ["Leaf"]
free_root = EditBone("FreeRoot")
free_tip = EditBone("FreeTip", parent=free_root)  # 未开启相连项的子骨骼
arm_free = make_armature([], [], [free_root, free_tip])
arm_free.mode = "EDIT"
select_bones(arm_free, [], extend=False)
free_root.select_tail = True  # 尾端没有相连子骨骼共享，仍算父级被选中
assert [bone.name for bone in selected_edit_bones(empty_context, arm_free)] == ["FreeRoot"]

print("BONE_SELECTION_UNIT_OK")
