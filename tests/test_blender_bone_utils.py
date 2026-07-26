import sys
from pathlib import Path

import bpy
from mathutils import Vector


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from Utils import bone_utils
from Utils.bone_selection import (
    select_bones,
    selected_bone_names,
    selected_mode_bones,
)
from Exporter.FbxExporter import FBXExporter


# 公共模块直接重导出选择兼容层的函数对象，不再包装转发。
assert bone_utils.select_bones is select_bones
assert bone_utils.selected_bone_names is selected_bone_names
assert bone_utils.selected_bones is selected_mode_bones
assert FBXExporter.clean_export_weights([]) == 0


def assert_raises(error_type, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except error_type:
        return
    raise AssertionError(f"{function.__name__} did not raise {error_type.__name__}")


# 命名与对称算法的输入边界。
assert bone_utils.aux_constraint_name("FAN", "CopyRotation") == "HoTools_FAN_CopyRotation"
assert bone_utils.split_side_suffix("UpperArm.L") == ("UpperArm", ".L")
assert bone_utils.split_side_suffix("UpperArm_r") == ("UpperArm", "_r")
assert bone_utils.split_side_suffix("UpperArm-R") == ("UpperArm", "-R")
assert bone_utils.split_side_suffix("UpperArmL") == ("UpperArmL", "")
assert bone_utils.has_side_suffix("UpperArm.L")
assert not bone_utils.has_side_suffix("UpperArm")
assert bone_utils.pair_side_suffix("Spine", "UpperArm_R") == "_R"
assert bone_utils.pair_side_suffix("Spine", "Chest") == ""
assert bone_utils.require_same_side("UpperArm.L", "LowerArm_L") == "L"
assert bone_utils.require_same_side("UpperArm.r", "LowerArm-R", expected="R") == "R"
assert_raises(ValueError, bone_utils.require_same_side, "UpperArm.L")
assert_raises(ValueError, bone_utils.require_same_side, "UpperArm", "LowerArm.L")
assert_raises(ValueError, bone_utils.require_same_side, "UpperArm.L", "LowerArm.R")
assert_raises(
    ValueError,
    bone_utils.require_same_side,
    "UpperArm.L",
    "LowerArm.L",
    expected="R",
)
assert bone_utils.find_suffixless(["Spine", "UpperArm.L", "Chest", "Hand_R"]) == [
    "Spine",
    "Chest",
]


armature_data = bpy.data.armatures.new("BoneUtilsContractData")
armature = bpy.data.objects.new("BoneUtilsContract", armature_data)
bpy.context.scene.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")

for name, x in (
    ("UpperArm.L", 1.0),
    ("UpperArm.R", -1.0),
    ("LowerArm.L", 2.0),
    ("LowerArm.R", -2.0),
    ("Center", 0.0),
):
    bone = armature_data.edit_bones.new(name)
    bone.head = (x, 0.0, 0.0)
    bone.tail = (x, 1.0, 0.0)

edit_head, edit_tail = bone_utils.bone_head_tail(armature_data.edit_bones["UpperArm.L"])
assert edit_head == Vector((1.0, 0.0, 0.0))
assert edit_tail == Vector((1.0, 1.0, 0.0))

collection = bone_utils.ensure_bone_collection(armature, "ContractCollection")
assert collection.name == bone_utils.ensure_bone_collection(
    armature,
    "ContractCollection",
).name
assert bone_utils.ensure_bone_collection(armature, "") is None
bone_utils.assign_bones_to_collection(
    armature,
    ["UpperArm.L", "MissingBone"],
    "ContractCollection",
)
assert "ContractCollection" in {
    item.name for item in armature_data.edit_bones["UpperArm.L"].collections
}

assert bone_utils.mirror_pair(
    armature,
    ["UpperArm.L", "LowerArm.L"],
) == ["UpperArm.R", "LowerArm.R"]
assert bone_utils.mirror_pair(armature, ["UpperArm.L", "Center"]) is None

bone_utils.set_object_mode(armature, "OBJECT")
assert armature.mode == "OBJECT"
assert bone_utils.get_mirrored_bone("UpperArm.L", armature_data) == [
    "UpperArm.L",
    "UpperArm.R",
]
assert bone_utils.get_mirrored_bone("Center", armature_data) == ["Center"]
assert bone_utils.mirrored_role_names(
    armature_data,
    "UpperArm.L",
    "LowerArm.L",
) == ("UpperArm.R", "LowerArm.R")
assert_raises(
    ValueError,
    bone_utils.mirrored_role_names,
    armature_data,
    "UpperArm.L",
    "Missing.L",
)
assert bone_utils.mirror_pair(
    armature,
    ["UpperArm.L", "LowerArm.L"],
) == ["UpperArm.R", "LowerArm.R"]

bone_utils.set_object_mode(armature, "POSE")
pose_bone = armature.pose.bones["UpperArm.L"]
pose_head, pose_tail = bone_utils.bone_head_tail(pose_bone)
assert (pose_head - pose_bone.matrix.translation).length < 1e-6
expected_tail = pose_bone.matrix @ Vector((0.0, pose_bone.bone.length, 0.0))
assert (pose_tail - expected_tail).length < 1e-6
assert_raises(Exception, bone_utils.bone_head_tail, object())
bone_utils.set_object_mode(armature, "OBJECT")


# 使用真实 Blender 数据块验证绑定收集与镜像状态往返。
mesh_data = bpy.data.meshes.new("BoneUtilsContractMeshData")
mesh_data.from_pydata([(0.0, 0.0, 0.0)], [], [])
mesh = bpy.data.objects.new("BoneUtilsContractMesh", mesh_data)
bpy.context.scene.collection.objects.link(mesh)
modifier = mesh.modifiers.new("Armature", "ARMATURE")
modifier.object = armature

other_armature_data = bpy.data.armatures.new("BoneUtilsOtherData")
other_armature = bpy.data.objects.new("BoneUtilsOther", other_armature_data)
bpy.context.scene.collection.objects.link(other_armature)
other_mesh_data = bpy.data.meshes.new("BoneUtilsOtherMeshData")
other_mesh = bpy.data.objects.new("BoneUtilsOtherMesh", other_mesh_data)
bpy.context.scene.collection.objects.link(other_mesh)
other_modifier = other_mesh.modifiers.new("Armature", "ARMATURE")
other_modifier.object = other_armature

assert bone_utils.collect_mesh_objects_for_armature(armature) == [mesh]

# Armature Parenting 是真实形变关系；指向同一骨架的重复修改器只返回一个候选。
parented_mesh_data = bpy.data.meshes.new("BoneUtilsParentedMeshData")
parented_mesh = bpy.data.objects.new("BoneUtilsParentedMesh", parented_mesh_data)
bpy.context.scene.collection.objects.link(parented_mesh)
parented_mesh.parent = armature
parented_mesh.parent_type = "ARMATURE"
assert bone_utils.find_deforming_armatures_for_object(parented_mesh) == (armature,)
assert bone_utils.find_deforming_armature_for_object(parented_mesh) == armature
parent_conflict = parented_mesh.modifiers.new("ParentConflict", "ARMATURE")
parent_conflict.object = other_armature
assert bone_utils.find_deforming_armatures_for_object(parented_mesh) == (
    other_armature,
    armature,
)
assert bone_utils.find_deforming_armature_for_object(parented_mesh) is None
parented_mesh.modifiers.remove(parent_conflict)
duplicate_modifier = mesh.modifiers.new("DuplicateArmature", "ARMATURE")
duplicate_modifier.object = armature
assert bone_utils.find_deforming_armatures_for_object(mesh) == (armature,)
assert bone_utils.collect_mesh_objects_for_armature(armature) == [mesh, parented_mesh]

# 内置 find_armature 不会穿过 LOD Empty，公共函数必须覆盖真实游戏资产层级。
lod_root = bpy.data.objects.new("BoneUtilsLOD0", None)
lod_group = bpy.data.objects.new("BoneUtilsLODGroup", None)
bpy.context.scene.collection.objects.link(lod_root)
bpy.context.scene.collection.objects.link(lod_group)
lod_root.parent = armature
lod_group.parent = lod_root
lod_mesh_data = bpy.data.meshes.new("BoneUtilsLODMeshData")
lod_mesh = bpy.data.objects.new("BoneUtilsLODMesh", lod_mesh_data)
bpy.context.scene.collection.objects.link(lod_mesh)
lod_mesh.parent = lod_group

assert lod_mesh.find_armature() is None
assert bone_utils.find_armatures_for_object(armature) == (armature,)
assert bone_utils.find_armatures_for_object(lod_mesh) == (armature,)
assert bone_utils.find_armature_for_object(lod_mesh) == armature
assert bone_utils.object_uses_armature(lod_mesh, armature)
assert bone_utils.find_deforming_armatures_for_object(lod_mesh) == ()
assert bone_utils.find_deforming_armature_for_object(lod_mesh) is None
assert not bone_utils.object_is_deformed_by_armature(lod_mesh, armature)
assert bone_utils.collect_mesh_objects_for_armature(armature) == [mesh, parented_mesh]

# 显式修改器优先于层级；多个不同目标必须暴露歧义，不能静默取第一个。
explicit_modifier = lod_mesh.modifiers.new("ExplicitOtherRig", "ARMATURE")
explicit_modifier.object = other_armature
assert bone_utils.find_armatures_for_object(lod_mesh) == (other_armature,)
assert bone_utils.find_armature_for_object(lod_mesh) == other_armature
second_modifier = lod_mesh.modifiers.new("SecondRig", "ARMATURE")
second_modifier.object = armature
assert bone_utils.find_armatures_for_object(lod_mesh) == (
    other_armature,
    armature,
)
assert bone_utils.find_armature_for_object(lod_mesh) is None
assert bone_utils.find_deforming_armature_for_object(lod_mesh) is None
assert bone_utils.object_uses_armature(lod_mesh, armature)
assert bone_utils.object_uses_armature(lod_mesh, other_armature)
assert bone_utils.object_is_deformed_by_armature(lod_mesh, armature)
assert bone_utils.object_is_deformed_by_armature(lod_mesh, other_armature)
assert bone_utils.find_armatures_for_object(None) == ()

mesh_mirror_owners = []
for property_name in ("use_mesh_mirror_x", "use_mesh_mirror_y", "use_mesh_mirror_z"):
    owner = mesh if hasattr(mesh, property_name) else mesh_data
    if hasattr(owner, property_name):
        setattr(owner, property_name, True)
        mesh_mirror_owners.append((owner, property_name))
mesh_state = bone_utils.set_temp_mesh_mirror_off(mesh)
assert mesh_state
assert all(not getattr(owner, name) for owner, name in mesh_mirror_owners)
bone_utils.restore_mesh_mirror_state(mesh_state)
assert all(getattr(owner, name) for owner, name in mesh_mirror_owners)

armature_data.use_mirror_x = True
if hasattr(armature.pose, "use_mirror_x"):
    armature.pose.use_mirror_x = True
armature_state = bone_utils.set_temp_armature_mirror_off(armature)
assert armature_state
assert armature_data.use_mirror_x is False
if hasattr(armature.pose, "use_mirror_x"):
    assert armature.pose.use_mirror_x is False
bone_utils.restore_armature_mirror_state(armature_state)
assert armature_data.use_mirror_x is True
if hasattr(armature.pose, "use_mirror_x"):
    assert armature.pose.use_mirror_x is True

print("BONE_UTILS_CONTRACT_OK", bpy.app.version_string)
