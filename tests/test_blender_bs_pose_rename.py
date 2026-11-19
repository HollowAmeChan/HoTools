"""Run with Blender --background --factory-startup --enable-autoexec --python-exit-code 1."""
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Euler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from HoTools.Rbf import bs_corrective as bs

bs.register()


def mesh_object(name):
    data = bpy.data.meshes.new(name)
    data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


data = bpy.data.armatures.new("RenameRig")
arm = bpy.data.objects.new("RenameRig", data)
bpy.context.scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
bone = data.edit_bones.new("Main")
bone.head, bone.tail = (0, 0, 0), (0, 1, 0)
bpy.ops.object.mode_set(mode="OBJECT")

coat, trim = mesh_object("RenameCoat"), mesh_object("RenameTrim")
settings = arm.hotools_bs_corrective
rule = settings.rules.add()
rule.id, rule.bone = "rename-rule", "Main"
for mesh in (coat, trim):
    rule.influence_objects.add().mesh = mesh
bs._add_point(arm, rule, (math.radians(60), 0, 0))
bs._add_point(arm, rule, (math.radians(-60), 0, 0))
point, neighbor = rule.pose_points[1], rule.pose_points[2]
point_id, original_name = point.id, point.bs_name
assert bs.reset_correctives(arm) == 4

keys = coat.data.shape_keys
key = keys.key_blocks[original_name]
trim_key = trim.data.shape_keys.key_blocks[original_name]
key.data[0].co.z, trim_key.data[0].co.z = 0.25, 0.5
keys.key_blocks[neighbor.bs_name].relative_key = key
driver = next(fc for fc in keys.animation_data.drivers if fc.data_path == key.path_from_id("value"))
driver_pointer, expression = driver.as_pointer(), driver.driver.expression
key.keyframe_insert(data_path="value", frame=1)
action = keys.animation_data.action
assert action.fcurves.find(key.path_from_id("value"))
foreign = coat.shape_key_add(name="Foreign")
foreign_driver = foreign.driver_add("value").driver
variable = foreign_driver.variables.new()
variable.name, variable.type = "source", "SINGLE_PROP"
variable.targets[0].id_type = "KEY"
variable.targets[0].id = keys
variable.targets[0].data_path = key.path_from_id("value")
foreign_driver.expression = "source * 0.5"

# Shared mesh data must be renamed once, even if several scope objects use it.
shared = bpy.data.objects.new("SharedCoat", coat.data)
bpy.context.scene.collection.objects.link(shared)
rule.influence_objects.add().mesh = shared
name = '袖口"抬臂\\修型'
assert bs.rename_corrective_pose(arm, rule, point, name) == 2
assert point.id == point_id and point.bs_name == name
assert key.name == trim_key.name == name
assert original_name not in keys.key_blocks
assert abs(key.data[0].co.z - 0.25) < 1e-6
assert abs(trim_key.data[0].co.z - 0.5) < 1e-6
assert keys.key_blocks[neighbor.bs_name].relative_key == key
assert driver.as_pointer() == driver_pointer and driver.driver.expression == expression
assert driver.data_path == key.path_from_id("value")
assert variable.targets[0].data_path == key.path_from_id("value")
assert action.fcurves.find(key.path_from_id("value"))
rule.influence_objects.remove(2)

# Real dependency-graph values, parameter updates and enable state survive rename.
arm.pose.bones["Main"].rotation_quaternion = Euler((point.x, point.y, point.z), "XYZ").to_quaternion()
bpy.context.view_layer.update()
assert abs(key.value - 1.0) < 1e-5 and abs(foreign.value - 0.5) < 1e-5
point.weight = 0.65
assert abs(key.value - 0.65) < 1e-5 and abs(trim_key.value - 0.65) < 1e-5
point.enabled = False
assert bs.rename_corrective_pose(arm, rule, point, "DisabledPose") == 2
assert key.mute and trim_key.mute and driver.mute
point.enabled = True
assert abs(key.value - 0.65) < 1e-5 and not driver.mute
assert all(fc.driver.is_valid for fc in keys.animation_data.drivers)

# Preflight every mesh: a conflict on the last target cannot rename the first.
conflict = trim.shape_key_add(name="Taken")
for invalid in ("", "  ", neighbor.bs_name, "Taken", "Basis", "x" * 64, "修" * 22):
    before = point.bs_name
    try:
        bs.rename_corrective_pose(arm, rule, point, invalid)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Accepted invalid name: {invalid!r}")
    assert point.bs_name == key.name == trim_key.name == before
    assert driver.data_path == key.path_from_id("value")
trim.shape_key_remove(conflict)
try:
    bs.rename_corrective_pose(arm, rule, rule.pose_points[0], "Neutral")
except ValueError:
    pass
else:
    raise AssertionError("Renamed the fixed base point")
assert bs.rename_corrective_pose(arm, rule, point, point.bs_name) == 0

# A missing old key is skipped; rename must neither create nor clear geometry.
trim.shape_key_remove(trim_key)
assert bs.rename_corrective_pose(arm, rule, point, "MissingTarget") == 1
assert "MissingTarget" not in trim.data.shape_keys.key_blocks
assert abs(key.data[0].co.z - 0.25) < 1e-6
assert bs.reset_correctives(arm) == 4
assert abs(key.data[0].co.z - 0.25) < 1e-6
config = bs.build_export_config(arm)
task = next(task for task in config["rules"][0]["tasks"] if task["pointId"] == point_id)
assert task["id"] == point_id and task["bsName"] == "MissingTarget"
assert {target["shapeKey"] for target in task["targets"]} == {"MissingTarget"}

# The clicked row stays the target when the active rule/pose selection changes.
other = settings.rules.add()
other.id, other.bone = "other-rule", "Main"
bs._add_point(arm, other, (0, 0.5, 0))
settings.active_index = 1
target = dict(armature_name=arm.name, rule_id="rename-rule", point_id=point_id)
assert bpy.ops.hotools.bs_corrective_pose_rename(**target, new_name="OperatorRename") == {"FINISHED"}
rule = settings.rules[0]
point = next(point for point in rule.pose_points if point.id == point_id)
assert point.bs_name == key.name == "OperatorRename"
assert settings.active_index == 1
assert settings.rules[1].pose_points[1].bs_name != "OperatorRename"
assert all(fc.driver.is_valid for fc in keys.animation_data.drivers)

# A stale popup must not redirect itself to a different current armature/pose.
stale = SimpleNamespace(armature_name="DeletedRig", rule_id="rename-rule", point_id=point_id)
try:
    bs._PoseTargetOperator.target(stale, bpy.context)
except ValueError:
    pass
else:
    raise AssertionError("Stale popup fell back to another armature")
rule.pose_points.remove(1)
stale.armature_name = arm.name
try:
    bs._PoseTargetOperator.target(stale, bpy.context)
except ValueError:
    pass
else:
    raise AssertionError("Stale popup fell back to another pose")

bs.unregister()
print("BS_POSE_RENAME_OK")
