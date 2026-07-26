import sys
from pathlib import Path

import bpy
from bpy.props import BoolProperty, PointerProperty
from bpy.types import PropertyGroup


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools.boneDissolve import DissolveBoneCore
from BoneTools.boneOperators import OP_MergeArmatures
from BoneTools.boneSplit import BoneSplitCore
from Exporter.FbxExporter import FBXExporter, MCH_BONE_COLLECTION_NAME


class TestBoneProps(PropertyGroup):
    generateMCH: BoolProperty(default=False)


bpy.utils.register_class(TestBoneProps)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=TestBoneProps)


def create_armature(name):
    active = bpy.context.view_layer.objects.active
    if active is not None and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")

    data = bpy.data.armatures.new(name + "Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    return obj, data


def set_source_collections(data, bone, prefix):
    first = data.collections.new(prefix + " A")
    second = data.collections.new(prefix + " B")
    creation = data.collections.new(prefix + " Creation")
    first.assign(bone)
    second.assign(bone)
    for collection in list(bone.collections):
        if collection not in {first, second}:
            collection.unassign(bone)
    data.collections.active = creation
    return {first.name, second.name}


def collection_names(bone):
    return {collection.name for collection in bone.collections}


# 拆分出的每个骨段都精确继承原骨的多集合归属。
split_obj, split_data = create_armature("CollectionSplit")
split_source = split_data.edit_bones.new("SplitSource")
split_source.head = (0.0, 0.0, 0.0)
split_source.tail = (0.0, 0.0, 2.0)
split_expected = set_source_collections(split_data, split_source, "Split")
split_names = BoneSplitCore.split_bone(split_obj, split_source.name, 2)
assert len(split_names) == 2
assert all(collection_names(split_data.bones[name]) == split_expected for name in split_names)


# 融并骨继承骨链最浅根骨的集合，不残留创建时的活动集合。
dissolve_obj, dissolve_data = create_armature("CollectionDissolve")
dissolve_root = dissolve_data.edit_bones.new("DissolveRoot")
dissolve_root.head = (0.0, 0.0, 0.0)
dissolve_root.tail = (0.0, 0.0, 1.0)
dissolve_tip = dissolve_data.edit_bones.new("DissolveTip")
dissolve_tip.head = dissolve_root.tail
dissolve_tip.tail = (0.0, 0.0, 2.0)
dissolve_tip.parent = dissolve_root
dissolve_tip.use_connect = True
dissolve_expected = set_source_collections(dissolve_data, dissolve_root, "Dissolve")
dissolved_name = DissolveBoneCore.addNewBone(
    dissolve_obj,
    [dissolve_root.name, dissolve_tip.name],
)
assert collection_names(dissolve_data.bones[dissolved_name]) == dissolve_expected


# FBX 叶骨复用公共继承逻辑，结果必须与源骨集合完全一致。
leaf_obj, leaf_data = create_armature("CollectionExportLeaf")
leaf_source = leaf_data.edit_bones.new("ExportLeafSource")
leaf_source.head = (0.0, 0.0, 0.0)
leaf_source.tail = (0.0, 1.0, 0.0)
leaf_expected = set_source_collections(leaf_data, leaf_source, "ExportLeaf")
FBXExporter.build_leaf_bones(leaf_obj, {leaf_source.name})
assert collection_names(leaf_data.edit_bones["ExportLeafSource_end"]) == leaf_expected


# MCH 有明确的专用输出集合，因此应清除活动集合而只保留 HoRig_MCH。
mch_obj, mch_data = create_armature("CollectionMCH")
mch_source = mch_data.edit_bones.new("MCHSource")
mch_source.head = (0.0, 0.0, 0.0)
mch_source.tail = (0.0, 1.0, 0.0)
mch_data.collections.new("MCH Creation")
mch_data.collections.active = mch_data.collections["MCH Creation"]
bpy.ops.object.mode_set(mode="OBJECT")
mch_data.bones["MCHSource"].hotools_boneprops.generateMCH = True
bpy.ops.object.mode_set(mode="EDIT")
name_map = FBXExporter.build_mch_and_clear(mch_obj)
assert name_map == {"MCHSource": "MCH_MCHSource"}
assert collection_names(mch_data.edit_bones["MCH_MCHSource"]) == {
    MCH_BONE_COLLECTION_NAME,
}


# 跨骨架复制按集合名映射，并清除目标骨原有的活动集合。
source_obj, source_data = create_armature("CollectionMergeSource")
source_bone = source_data.edit_bones.new("MergeSource")
source_bone.head = (0.0, 0.0, 0.0)
source_bone.tail = (0.0, 1.0, 0.0)
merge_expected = set_source_collections(source_data, source_bone, "Merge")
bpy.ops.object.mode_set(mode="OBJECT")

target_obj, target_data = create_armature("CollectionMergeTarget")
target_creation = target_data.collections.new("Merge Target Creation")
target_data.collections.active = target_creation
target_bone = target_data.edit_bones.new("MergeTarget")
target_bone.head = (0.0, 0.0, 0.0)
target_bone.tail = (0.0, 1.0, 0.0)
bpy.ops.object.mode_set(mode="OBJECT")
OP_MergeArmatures._copy_bone_collections(
    target_obj,
    source_data.bones["MergeSource"],
    target_data.bones["MergeTarget"],
    set(),
)
assert collection_names(target_data.bones["MergeTarget"]) == merge_expected


print("BONE_COLLECTION_INHERITANCE_OK", bpy.app.version_string)
