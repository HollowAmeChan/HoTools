import sys
from pathlib import Path

import bpy
from bpy.props import PointerProperty
from bpy.types import PropertyGroup


BONE_TOOLS_DIR = Path(__file__).resolve().parents[2]
if str(BONE_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(BONE_TOOLS_DIR))

import hoAux
from hoAux.collection_registry import assign_all, find_collection
from hoAux.ir.blender_reader import snapshot_armature
from hoAux.ir.parser import parse_json
from hoAux.ir.writer import to_dict, to_json
from hoAux.properties import PG_HoAuxBoneInfo
from hoAux.operations import remove_scope, set_scope_enabled


class _TestBoneProps(PropertyGroup):
    hoAux: PointerProperty(type=PG_HoAuxBoneInfo)


hoAux.register()
bpy.utils.register_class(_TestBoneProps)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=_TestBoneProps)

armature = bpy.data.armatures.new("HoAuxTestArmature")
obj = bpy.data.objects.new("HoAuxTest", armature)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)

bpy.ops.object.mode_set(mode="EDIT")
main = armature.edit_bones.new("Main_L")
main.head = (0.0, 0.0, 0.0)
main.tail = (0.0, 1.0, 0.0)
direction = armature.edit_bones.new("DIR_Test_L")
direction.head = main.tail
direction.tail = (0.0, 2.0, 0.0)
direction.parent = main
deform = armature.edit_bones.new("DEF_Test_L")
deform.head = main.tail
deform.tail = (0.3, 1.6, 0.0)
deform.parent = main
direction_name = direction.name
deform_name = deform.name
bpy.ops.object.mode_set(mode="OBJECT")

direction_info = armature.bones[direction_name].hotools_boneprops.hoAux
direction_info.isHoAuxBone = True
direction_info.rigId = "test-rig"
direction_info.pipelineId = "ARM.L"
direction_info.moduleId = "INFRA"
direction_info.moduleType = "ROTATION_HALF"
direction_info.roleTag = "DIR"
direction_info.part = "Elbow"
direction_info.side = "L"
direction_info.sharedKey = "ROTATION_HALF:LOWER_ARM:L"
direction_info.nameKey = "ARM.L.DIR.TEST"
armature.bones[direction_name].use_deform = False

deform_info = armature.bones[deform_name].hotools_boneprops.hoAux
deform_info.isHoAuxBone = True
deform_info.rigId = "test-rig"
deform_info.pipelineId = "ARM.L"
deform_info.moduleId = "ELBOW_VOLUME.L"
deform_info.moduleType = "ELBOW_VOLUME"
deform_info.roleTag = "DEF"
deform_info.part = "Elbow"
deform_info.side = "L"
deform_info.nameKey = "ARM.L.ELBOW.DEF.TEST"
armature.bones[deform_name].use_deform = True

direction_constraint = obj.pose.bones[direction_name].constraints.new("COPY_ROTATION")
direction_constraint.name = "HoAux Test Half Rotation"
direction_constraint.target = obj
direction_constraint.subtarget = "Main_L"
direction_constraint.owner_space = "WORLD"
direction_constraint.target_space = "WORLD"
direction_constraint.influence = 0.5

user_collection = armature.collections.new("User Collection")
user_collection.assign(armature.bones[deform_name])

assigned = assign_all(armature)
assert assigned == 2
assert deform_name in user_collection.bones
assert find_collection(armature, "HOAUX:ROOT") is not None
assert find_collection(armature, "HOAUX:FILTER:ROLE:DEF") is not None
assert find_collection(armature, "HOAUX:INFRASTRUCTURE:SHARED_DIR") is not None

copy_rotation = obj.pose.bones[deform_name].constraints.new("COPY_ROTATION")
copy_rotation.name = "HoAux Test Copy Rotation"
copy_rotation.target = obj
copy_rotation.subtarget = direction_name
copy_rotation.owner_space = "LOCAL"
copy_rotation.target_space = "LOCAL_OWNER_ORIENT"

copy_location = obj.pose.bones[deform_name].constraints.new("COPY_LOCATION")
copy_location.name = "HoAux Test Driven Location"
copy_location.target = obj
copy_location.subtarget = direction_name
copy_location.head_tail = 1.0
fcurve = copy_location.driver_add("influence")
driver = fcurve.driver
driver.type = "SCRIPTED"
driver.expression = "abs(var*2/pi)"
variable = driver.variables.new()
variable.name = "var"
variable.type = "TRANSFORMS"
target = variable.targets[0]
target.id = obj
target.bone_target = direction_name
target.transform_type = "ROT_Z"
target.transform_space = "LOCAL_SPACE"

snapshot = snapshot_armature(obj)
encoded = to_json(snapshot)
decoded = parse_json(encoded)
assert to_dict(decoded) == to_dict(snapshot)
assert any(item.resource_kind == "CONSTRAINT" for item in snapshot.resources)
assert any(item.resource_kind == "DRIVER" for item in snapshot.resources)
assert any(item.resource_kind == "DRIVER_VARIABLE" for item in snapshot.resources)
assert any(
    item.resource_kind == "BONE" and item.provenance.get("external")
    for item in snapshot.resources
)
assert all(
    item.status == "RESOLVED"
    for item in snapshot.resources
    if item.resource_kind in {"CONSTRAINT", "DRIVER_VARIABLE"}
)

disabled = set_scope_enabled(obj, "ARM.L", "ELBOW_VOLUME.L", False)
assert disabled["constraints"] == 2
assert all(constraint.mute for constraint in obj.pose.bones[deform_name].constraints)
assert fcurve.mute
enabled = set_scope_enabled(obj, "ARM.L", "ELBOW_VOLUME.L", True)
assert enabled["drivers"] == 1
assert not fcurve.mute

removed = remove_scope(obj, "ARM.L", "ELBOW_VOLUME.L")
assert removed["bones"] == 1
assert deform_name not in armature.bones
assert direction_name in armature.bones
assert "Main_L" in armature.bones
assert armature.collections.get("User Collection") is not None

print(f"HOAUX_PHASE1_OK resources={len(snapshot.resources)}")
