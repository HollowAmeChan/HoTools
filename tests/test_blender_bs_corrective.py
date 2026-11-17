"""Blender 4.5 integration tests for the four-list BS corrective workflow.

Run with --background --factory-startup --enable-autoexec --python this_file.py.
The tests create their own rig, meshes and .blend; they never touch a user scene.
"""
import json
import math
import sys
import tempfile
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler

ADDON_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON_DIR))
from HoTools.Rbf import bs_corrective as bs
bs.register()


def close(actual, expected, epsilon=4e-5):
    assert abs(actual - expected) < epsilon, (actual, expected)


def raises(function, message):
    try:
        function()
    except ValueError:
        return
    raise AssertionError(message)


def mesh_object(name):
    data = bpy.data.meshes.new(name + "Data")
    data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    mesh = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(mesh)
    return mesh


def build_scene():
    arm_data = bpy.data.armatures.new("BsCorrectiveTestRigData")
    armature = bpy.data.objects.new("BsCorrectiveTestRig", arm_data)
    bpy.context.scene.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    parent = arm_data.edit_bones.new("Parent")
    parent.head, parent.tail, parent.roll = (0, 0, 0), (0.4, 0.8, 0.5), 0.2
    bone = arm_data.edit_bones.new("Main")
    bone.head, bone.tail, bone.parent = parent.tail, (1, 1.7, 1.1), parent
    bone.roll = 0.3
    bpy.ops.object.mode_set(mode="OBJECT")
    return armature, mesh_object("Coat"), mesh_object("Trim")


def list_edit(kind, action, **kwargs):
    return bpy.ops.hotools.bs_corrective_list_edit(kind=kind, action=action, **kwargs)


arm, coat, trim = build_scene()
assert list_edit("RULES", "ADD") == {"FINISHED"}
settings = arm.hotools_bs_corrective
rule = settings.rules[0]
rule.bone = "Main"
rule.comment = "Coat corrective · multi-object task"
for mesh in (coat, trim):
    assert list_edit("OBJECTS", "ADD") == {"FINISHED"}
    rule.influence_objects[-1].mesh = mesh
assert list_edit("OBJECTS", "UP") == {"FINISHED"}
assert list_edit("OBJECTS", "DOWN") == {"FINISHED"}
assert len(rule.pose_points) == 1 and rule.pose_points[0].id == bs._BASE_POINT
p1, task1 = bs._add_point(arm, rule, (0.8, 0.15, -0.1))
p2, task2 = bs._add_point(arm, rule, (-0.5, 0.4, 0.2))
first_id, second_id, rule_id = task1.id, task2.id, rule.id
assert p1.task_id == first_id and task1.point_id == p1.id
rule.pose_active_index = 1
assert rule.task_active_index == 0
rule.task_active_index = 1
assert rule.pose_active_index == 2
assert bs.reset_correctives(arm) == 4
assert len(rule.tasks[0].targets) == 2
assert len(arm.data.bones) == 2, "BS must not generate ADIR or other authoring bones"
for mesh in (coat, trim):
    for fcurve in mesh.data.shape_keys.animation_data.drivers:
        assert len(fcurve.driver.expression) < 256
        assert not any(variable.name.startswith("_") for variable in fcurve.driver.variables)
        assert len(fcurve.driver.variables) == 3
        assert all(variable.targets[0].transform_space == "LOCAL_SPACE" for variable in fcurve.driver.variables)
        assert all(variable.targets[0].rotation_mode == "XYZ" for variable in fcurve.driver.variables)

# Check the actual dependency graph, in quaternion rotation mode, with nontrivial
# parent rest orientation and bone roll. Parent/object transforms must not leak.
for pose, expected in [((0, 0, 0), (0, 0)), ((p1.x, p1.y, p1.z), (1, 0)), ((p2.x, p2.y, p2.z), (0, 1))]:
    arm.pose.bones["Main"].rotation_quaternion = Euler(pose, "XYZ").to_quaternion()
    for parent_pose in ((0, 0, 0), (0.7, -0.3, 1.2)):
        arm.pose.bones["Parent"].rotation_quaternion = Euler(parent_pose, "XYZ").to_quaternion()
        arm.rotation_euler = (0.3, -0.1, 0.9)
        bpy.context.view_layer.update()
        for mesh in (coat, trim):
            for index, value in enumerate(expected):
                close(mesh.data.shape_keys.key_blocks[rule.tasks[index].bs_name].value, value)
            assert all(fc.driver.is_valid for fc in mesh.data.shape_keys.animation_data.drivers)

# Same input, different output drivers: one solve/evaluation of the complete rule.
bs._RBF_CACHE.clear()
original_evaluate = bs._evaluate_rbf_outputs
calls = []
def count_evaluate(item, current):
    calls.append(current)
    return original_evaluate(item, current)
bs._evaluate_rbf_outputs = count_evaluate
for _ in range(3):
    for task in rule.tasks:
        bs._driver_namespace_rbf(rule_id, task.id, 0.4, 0.1, 0)
assert len(calls) == 1, calls
previous = bs._driver_namespace_rbf(rule_id, first_id, 0.4, 0.1, 0)
rule.rbf_radius = 1.0
bs.generate_native_drivers(arm)
updated = bs._driver_namespace_rbf(rule_id, first_id, 0.4, 0.1, 0)
assert abs(updated - previous) > 1e-4, (updated, previous)
bs._evaluate_rbf_outputs = original_evaluate
bs._RBF_RUNTIME["wrap-test"] = bs._decode_rbf_payload(json.dumps({
    "positions": [[0, 0, 0], [math.radians(179), 0, 0]],
    "coefficients": {"wrap-task": [0, 1]}, "radius": math.radians(10),
}))
assert bs._driver_namespace_rbf("wrap-test", "wrap-task", math.radians(-179), 0, 0) > 0.95
bs._RBF_RUNTIME.pop("wrap-test")
bs._RBF_CACHE.pop("wrap-test")

# Native toggles mute live drivers and restore evaluation when re-enabled.
settings.enabled = False
assert all(fc.mute for fc in coat.data.shape_keys.animation_data.drivers)
settings.enabled = True
assert not any(fc.mute for fc in coat.data.shape_keys.animation_data.drivers)
rule.enabled = False
assert all(fc.mute for fc in coat.data.shape_keys.animation_data.drivers)
rule.enabled = True

# Reset reuses key identity; unchecked overwrite preserves authored vertex data.
key = coat.data.shape_keys.key_blocks[task1.bs_name]
key.data[1].co.x = 1.4
pointer = key.as_pointer()
assert bs.reset_correctives(arm, overwrite=False) == 4
key = coat.data.shape_keys.key_blocks[task1.bs_name]
assert key.as_pointer() == pointer
close(key.data[1].co.x, 1.4)
assert bs.reset_correctives(arm, overwrite=True) == 4
close(key.data[1].co.x, 1)

# A task can drive multiple keys on the SAME mesh, plus another mesh.
coat.shape_key_add(name='Manual "quoted" \\ extra')
extra = task1.targets.add()
extra.mesh, extra.shape_key = coat, 'Manual "quoted" \\ extra'
assert bs.generate_native_drivers(arm) == 5
assert bs.build_export_config(arm)["rules"][0]["tasks"][0]["targets"][-1]["shapeKey"] == extra.shape_key
# Retargeting then refreshing must remove the old generated driver.
task1.targets.remove(len(task1.targets) - 1)
assert bs.generate_native_drivers(arm) == 4
assert len(coat.data.shape_keys.animation_data.drivers) == 2

# Conflicting names/points must fail before altering keys or existing drivers.
name = task2.bs_name
task2.bs_name = task1.bs_name
raises(lambda: bs.reset_correctives(arm), "duplicate BS name accepted")
assert len(coat.data.shape_keys.animation_data.drivers) == 2
task2.bs_name = name
pose2 = (p2.x, p2.y, p2.z)
p2.x, p2.y, p2.z = p1.x, p1.y, p1.z
raises(lambda: bs.generate_native_drivers(arm), "duplicate RBF point accepted")
assert len(coat.data.shape_keys.animation_data.drivers) == 2
p2.x, p2.y, p2.z = pose2
# Foreign drivers are never overwritten.
foreign = coat.shape_key_add(name="Foreign")
foreign.driver_add("value").driver.expression = "0.25"
old_shape = task1.targets[0].shape_key
task1.targets[0].shape_key = "Foreign"
raises(lambda: bs.generate_native_drivers(arm), "foreign driver accepted")
task1.targets[0].shape_key = old_shape

# Virtual reference sample is a native UIList row but cannot be removed/moved.
rule.pose_active_index = 0
assert rule.task_active_index == -1 and bs._active_task(rule) is None
assert list_edit("POINTS", "REMOVE") == {"CANCELLED"}
assert list_edit("POINTS", "DOWN") == {"CANCELLED"}
rule.pose_active_index = 1
assert list_edit("POINTS", "DOWN") == {"FINISHED"}
assert bs._point_for_task(rule, task1).id == task1.point_id
assert list_edit("POINTS", "UP") == {"FINISHED"}

# Export carries links; the zero baseline is fixed and not duplicated in samples.
config = bs.build_export_config(arm, measurement_bones={"Main": "MCH_Main"})
exported = config["rules"][0]
assert config["version"] == 3 and config["poseSpace"] == "LOCAL"
assert exported["measurementBone"] == "MCH_Main"
assert exported["rbf"]["includeBase"] and exported["rbf"]["basePose"] == [0, 0, 0]
assert len(exported["rbf"]["controlPoints"]) == 2
assert len(exported["tasks"]) == 2
assert {task["pointId"] for task in exported["tasks"]} == {point["id"] for point in exported["rbf"]["controlPoints"]}
assert len(exported["influenceObjects"]) == 2
raises(lambda: bs._decode_rbf_payload('{"positions":[[0,0,0]],"coefficients":{"x":[1,2]},"radius":1}'), "bad coefficient length accepted")

# The namespace and its serialized coefficients survive a real .blend reload.
bs.generate_native_drivers(arm)
folder = Path(tempfile.gettempdir()) / "hotools_bs_corrective_tests"
folder.mkdir(exist_ok=True)
blend_path = folder / "four_list_demo.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
bpy.ops.wm.open_mainfile(filepath=str(blend_path))
arm = bpy.data.objects["BsCorrectiveTestRig"]
coat, trim = bpy.data.objects["Coat"], bpy.data.objects["Trim"]
settings, rule = arm.hotools_bs_corrective, arm.hotools_bs_corrective.rules[0]
assert bs._RBF_RUNTIME
close(bs._driver_namespace_rbf(rule_id, first_id, *tuple(config["rules"][0]["rbf"]["controlPoints"][0]["pose"])), 1)
first = config["rules"][0]["rbf"]["controlPoints"][0]["pose"]
arm.pose.bones["Main"].rotation_quaternion = Euler(first, "XYZ").to_quaternion()
bpy.context.view_layer.update()
close(coat.data.shape_keys.key_blocks["_BSC_pose1"].value, 1)
assert all(fc.driver.is_valid for fc in coat.data.shape_keys.animation_data.drivers)
assert "hotools_bs_rbf" in bpy.app.driver_namespace
assert len(rule.pose_points) == 3 and rule.pose_points[0].id == bs._BASE_POINT

# Vectorized and pure-Python paths must agree with an independent scalar metric.
large = settings.rules.add()
large.id, large.bone = "large-test", "Main"
bs._ensure_base_point(large)
rng = np.random.default_rng(23)
for pose in rng.uniform(-1.2, 1.2, (24, 3)):
    bs._add_point(arm, large, tuple(pose))
item = bs._decode_rbf_payload(bs._encode_rbf_payload(large))
bs._RBF_RUNTIME[large.id] = item
start = time.perf_counter()
for pose in rng.uniform(-math.pi, math.pi, (100, 3)):
    expected = []
    for row in item[2]:
        expected.append(min(max(sum(c * math.exp(-sum(bs._shortest_angle(a-b)**2 for a,b in zip(pose,p)) * item[3])
                                   for p,c in zip(item[0], row)), 0), 1))
    actual = [bs._driver_namespace_rbf(large.id, task.id, *pose) for task in large.tasks]
    assert np.max(np.abs(np.asarray(actual) - expected)) < 1e-10
print("RBF_SHARED_CACHE_24_OUTPUTS_OK", round((time.perf_counter()-start)*1000, 2), "ms including scalar reference")
settings.rules.remove(1)
bs._restore_driver_namespace(None)
assert "large-test" not in bs._RBF_RUNTIME

# Batch controls really process a second rule; ordinary operations stay local.
batch = settings.rules.add()
batch.id, batch.bone = "batch-test", "Main"
batch.influence_objects.add().mesh = coat
bs._add_point(arm, batch, (0.1, 0.7, -0.5))
assert bpy.ops.hotools.bs_corrective_reset(all_rules=True, overwrite_existing=False) == {"FINISHED"}
assert "batch-test" in bs._RBF_RUNTIME
settings.active_index = 0
assert bpy.ops.hotools.bs_corrective_remove_drivers(all_rules=False) == {"FINISHED"}
assert rule.id not in bs._RBF_RUNTIME and "batch-test" in bs._RBF_RUNTIME
assert bpy.ops.hotools.bs_corrective_generate_drivers(all_rules=True) == {"FINISHED"}
assert rule.id in bs._RBF_RUNTIME and "batch-test" in bs._RBF_RUNTIME
from types import SimpleNamespace
dialogs = []
fake_context = SimpleNamespace(window_manager=SimpleNamespace(invoke_props_dialog=lambda op, **kw: dialogs.append(op.all_rules) or {"RUNNING_MODAL"}))
for operator_type in (bs.OP_BsCorrectiveReset, bs.OP_BsCorrectiveGenerateDrivers, bs.OP_BsCorrectiveRemoveDrivers, bs.OP_BsCorrectiveClearControls):
    op = SimpleNamespace(bl_idname=operator_type.bl_idname, all_rules=False)
    assert bs._BatchRuleOperator.invoke(op, fake_context, SimpleNamespace(shift=True)) == {"RUNNING_MODAL"}
assert dialogs == [True] * 4

# Clear points/tasks in a batch; keep sculpted keys and foreign drivers.
bpy.context.view_layer.objects.active = arm
assert bpy.ops.hotools.bs_corrective_clear_controls(all_rules=True) == {"FINISHED"}
assert len(rule.tasks) == 0 and len(rule.pose_points) == 1
assert rule.pose_points[0].id == bs._BASE_POINT
assert not bs._RBF_RUNTIME and not bs._RBF_CACHE
assert len(coat.data.shape_keys.animation_data.drivers) == 1
assert coat.data.shape_keys.animation_data.drivers[0].data_path == coat.data.shape_keys.key_blocks["Foreign"].path_from_id("value")
assert coat.data.shape_keys.key_blocks.get("_BSC_pose1")
assert list_edit("RULES", "CLEAR") == {"FINISHED"}
bs.unregister()
assert "hotools_bs_rbf" not in bpy.app.driver_namespace
assert bs._restore_driver_namespace not in bpy.app.handlers.load_post
bs.register()
print("BS_CORRECTIVE_OK", blend_path)
