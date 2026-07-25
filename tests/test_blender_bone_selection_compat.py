import sys
import importlib
import types
from pathlib import Path
from types import SimpleNamespace

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools import boneRename
from Utils.bone_selection import (
    select_bones,
    selected_armature_bones,
    selected_bone_names,
    selected_edit_bones,
    selected_pose_bones,
)


def make_armature():
    armature = bpy.data.armatures.new("BoneSelectionCompatData")
    obj = bpy.data.objects.new("BoneSelectionCompat", armature)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    bpy.ops.object.mode_set(mode="EDIT")
    first = armature.edit_bones.new("First")
    first.head = (0.0, 0.0, 0.0)
    first.tail = (0.0, 1.0, 0.0)
    second = armature.edit_bones.new("Second")
    second.head = first.tail
    second.tail = (0.0, 2.0, 0.0)
    second.parent = first
    return obj


obj = make_armature()
select_bones(obj, ["First"], extend=False)
assert [bone.name for bone in selected_edit_bones(bpy.context, obj)] == ["First"]
assert selected_bone_names(bpy.context, obj) == ["First"]

bpy.ops.object.mode_set(mode="POSE")
select_bones(obj, ["First"], extend=False)
assert [bone.name for bone in selected_pose_bones(bpy.context, obj)] == ["First"]
assert selected_bone_names(bpy.context, obj) == ["First"]
select_bones(obj, ["Second"], extend=True)
assert set(selected_bone_names(bpy.context, obj)) == {"First", "Second"}
select_bones(obj, ["First"], extend=False)

# 模拟不带区域选择集合的操作器上下文，必须回退到底层选择状态。
empty_context = SimpleNamespace()
assert selected_bone_names(empty_context, obj) == ["First"]

# NameMapping 也必须通过公共层读取选择；构造轻量包环境以避开完整插件在后台模式
# 初始化 GPU 绘制器的限制。
package = types.ModuleType("HoTools")
package.__path__ = [str(ADDON_DIR)]
sys.modules.setdefault("HoTools", package)
name_mapping = importlib.import_module("HoTools.NameMapping")
assert name_mapping.MappingCore.getItemNames_ArmatureBone(obj) == ["First"]

# 切到 Object 模式后 context 选择集合会消失，兼容层仍应从两个版本各自的底层状态
# 恢复姿态选择。
bpy.ops.object.mode_set(mode="OBJECT")
assert selected_bone_names(bpy.context, obj) == ["First"]
assert [bone.name for bone in selected_armature_bones(bpy.context, obj)] == ["First"]
assert name_mapping.MappingCore.getItemNames_ArmatureBone(obj) == ["First"]

boneRename.register()
try:
    rule = bpy.context.scene.ho_boneRename_change_rules.add()
    rule.type = "MOD_HEAD"
    rule.targetStr = "Renamed_"

    bpy.ops.object.mode_set(mode="POSE")
    select_bones(obj, ["First"], extend=False)
    result = bpy.ops.ho.rename_rulechangenameboneselected(index=0)
    assert result == {"FINISHED"}
    assert obj.mode == "POSE"
    assert obj.data.bones.get("Renamed_First") is not None
    assert obj.data.bones.get("First") is None

    edit_rule = bpy.context.scene.ho_boneRename_change_rules.add()
    edit_rule.type = "MOD_TAIL"
    edit_rule.targetStr = "_Edited"
    bpy.ops.object.mode_set(mode="EDIT")
    select_bones(obj, ["Second"], extend=False)
    result = bpy.ops.ho.rename_rulechangenameboneselected(index=1)
    assert result == {"FINISHED"}
    assert obj.mode == "EDIT"
    assert obj.data.edit_bones.get("Second_Edited") is not None
    assert selected_bone_names(bpy.context, obj) == ["Second_Edited"]

    fixed_rule = bpy.context.scene.ho_boneRename_rules.add()
    fixed_rule.type = "MOD_FIXED_STRING"
    fixed_rule.fixedStr = "Rig"
    depth_rule = bpy.context.scene.ho_boneRename_rules.add()
    depth_rule.type = "MOD_DEPTH"
    depth_rule.deepStr = "01"
    bpy.ops.object.mode_set(mode="POSE")
    select_bones(obj, ["Renamed_First", "Second_Edited"], extend=False)
    result = bpy.ops.ho.rename_rulerenameboneselected()
    assert result == {"FINISHED"}
    assert {bone.name for bone in obj.data.bones} == {"Rig_01", "Rig_02"}

    selected = obj.data.bones["Rig_01"]
    selected.name = "Rig_01.L"
    result = bpy.ops.ho.rename_removesidetail()
    assert result == {"FINISHED"}
    assert obj.data.bones.get("Rig_01") is not None
    selected = obj.data.bones["Rig_01"]
    selected.name = "Rig_01.001"
    result = bpy.ops.ho.rename_removenumbertail()
    assert result == {"FINISHED"}
    assert obj.data.bones.get("Rig_01") is not None

    # Checker 原先直接写 PoseBone.bone.select，在 5.2 会报错。
    from HoTools.Checker.objectChecker import fixOperator

    fixOperator.register()
    try:
        bpy.ops.object.mode_set(mode="POSE")
        result = bpy.ops.ho.checker_select_bones(input="['Rig_01']")
        assert result == {"FINISHED"}
        assert selected_bone_names(bpy.context, obj) == ["Rig_01"]
    finally:
        fixOperator.unregister()
finally:
    boneRename.unregister()

print("BONE_SELECTION_COMPAT_OK", bpy.app.version_string)
