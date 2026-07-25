import importlib.util
import os
import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(
    os.environ.get("HOTOOLS_ADDON_DIR", Path(__file__).resolve().parents[1])
).resolve()
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

module_path = ADDON_DIR / "BoneTools" / "boneRename.py"
spec = importlib.util.spec_from_file_location("hotools_deployed_bone_rename", module_path)
bone_rename = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bone_rename)

from Utils.bone_selection import select_bones


armature = bpy.data.armatures.new("RenameRuleDeployedData")
obj = bpy.data.objects.new("RenameRuleDeployed", armature)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)

bpy.ops.object.mode_set(mode="EDIT")
bone = armature.edit_bones.new("Source")
bone.head = (0.0, 0.0, 0.0)
bone.tail = (0.0, 1.0, 0.0)
bpy.ops.object.mode_set(mode="POSE")
select_bones(obj, ["Source"], extend=False)

bone_rename.register()
try:
    rule = bpy.context.scene.ho_boneRename_change_rules.add()
    rule.type = "MOD_HEAD"
    rule.targetStr = "Changed_"
    result = bpy.ops.ho.rename_rulechangenameboneselected(index=0)
    assert result == {"FINISHED"}
    assert obj.mode == "POSE"
    assert obj.data.bones.get("Changed_Source") is not None
finally:
    bone_rename.unregister()

print("RENAME_RULE_DEPLOYED_OK", bpy.app.version_string, ADDON_DIR)
