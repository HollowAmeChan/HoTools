"""Blender 4.5 integration tests for the pose-centric BS corrective workflow.

Run with --background --factory-startup --enable-autoexec --python this_file.py.
The tests create their own rig, meshes and .blend; they never touch a user scene.
"""
import json
import math
import sys
import tempfile
import time
from types import SimpleNamespace
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Quaternion

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
view_context = SimpleNamespace(object=coat, scene=bpy.context.scene)
bpy.context.scene.hotools_bs_corrective_view_armature = arm
assert bs._context_armature(view_context) is arm
assert bs._operator_armature(SimpleNamespace(armature_name=arm.name), view_context) is arm
assert list_edit("RULES", "ADD") == {"FINISHED"}
settings = arm.hotools_bs_corrective
rule = settings.rules[0]
assert bs._owner_armature(settings, view_context) is arm
assert bs._owner_armature(rule, view_context) is arm
assert bs.BsCorrectivePreview._color(0.0, True, 0.8)[3] > bs.BsCorrectivePreview._color(0.0, True, 0.1)[3]
rule.bone = "Main"
for mesh in (coat, trim):
    assert list_edit("OBJECTS", "ADD") == {"FINISHED"}
    rule.influence_objects[-1].mesh = mesh
assert list_edit("OBJECTS", "UP") == {"FINISHED"}
assert list_edit("OBJECTS", "DOWN") == {"FINISHED"}
assert len(rule.pose_points) == 1 and rule.pose_points[0].id == bs._BASE_POINT
p1 = bs._add_point(arm, rule, (0.8, 0.15, -0.1))
p2 = bs._add_point(arm, rule, (-0.5, 0.4, 0.2))
first_id, second_id, rule_id = p1.id, p2.id, rule.id
assert p1.bs_name == "_BSC_pose1" and p2.bs_name == "_BSC_pose2"
assert abs(p1.radius - math.radians(30.0)) < 1e-6
assert abs(p2.radius - math.radians(30.0)) < 1e-6
rule.pose_active_index = 2
assert rule.pose_active_index == 2
assert bs.reset_correctives(arm) == 4
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
                close(mesh.data.shape_keys.key_blocks[rule.pose_points[index + 1].bs_name].value, value)
            assert all(fc.driver.is_valid for fc in mesh.data.shape_keys.animation_data.drivers)

arm.pose.bones["Main"].rotation_quaternion = Euler((p1.x, p1.y, p1.z), "XYZ").to_quaternion()
bpy.context.view_layer.update()
assert bs._display_rbf_weight(rule, p1, arm) > 0.99
assert bs._display_rbf_weight(rule, p2, arm) < 0.01

# Same input, different output drivers: one solve/evaluation of the complete rule.
bs._RBF_CACHE.clear()
original_evaluate = bs._evaluate_rbf_outputs
calls = []
def count_evaluate(item, current):
    calls.append(current)
    return original_evaluate(item, current)
bs._evaluate_rbf_outputs = count_evaluate
for _ in range(3):
    for point in bs._authored_points(rule):
        bs._driver_namespace_rbf(rule_id, point.id, 0.4, 0.1, 0)
assert len(calls) == 1, calls
previous = bs._driver_namespace_rbf(rule_id, first_id, 0.4, 0.1, 0)
p1.radius = 1.0
updated = bs._driver_namespace_rbf(rule_id, first_id, 0.4, 0.1, 0)
assert abs(updated - previous) > 1e-4, (updated, previous)
# Radius and weight edits update the live driver snapshot without manual refresh.
p1.radius, p2.radius = math.radians(12), math.radians(42)
local_payload = bs._decode_rbf_payload(rule.driver_payload)
assert abs(local_payload[2][0] - p1.radius) < 1e-8
local_value = bs._driver_namespace_rbf(rule_id, first_id, 0.4, 0.1, 0)
p1.radius = math.radians(25)
changed_local_value = bs._driver_namespace_rbf(rule_id, first_id, 0.4, 0.1, 0)
assert abs(changed_local_value - local_value) > 1e-4, (changed_local_value, local_value)
bs._evaluate_rbf_outputs = original_evaluate
bs._RBF_RUNTIME["wrap-test"] = bs._compiled_poses(
    [bs.euler_xyz_quaternion((math.radians(179), 0, 0))], ["wrap-task"], [math.radians(10)], [1],
)
assert bs._driver_namespace_rbf("wrap-test", "wrap-task", math.radians(-179), 0, 0) > 0.89
bs._RBF_RUNTIME.pop("wrap-test")
bs._RBF_CACHE.pop("wrap-test")

# Native toggles mute live drivers and restore evaluation when re-enabled.
settings.enabled = False
assert all(fc.mute for fc in coat.data.shape_keys.animation_data.drivers)
assert all(coat.data.shape_keys.key_blocks[name].mute for name in (p1.bs_name, p2.bs_name))
settings.enabled = True
assert not any(fc.mute for fc in coat.data.shape_keys.animation_data.drivers)
assert not any(coat.data.shape_keys.key_blocks[name].mute for name in (p1.bs_name, p2.bs_name))
rule.enabled = False
assert all(fc.mute for fc in coat.data.shape_keys.animation_data.drivers)
assert all(coat.data.shape_keys.key_blocks[name].mute for name in (p1.bs_name, p2.bs_name))
assert not p1.enabled and not p2.enabled
rule.enabled = True
assert not any(coat.data.shape_keys.key_blocks[name].mute for name in (p1.bs_name, p2.bs_name))
assert p1.enabled and p2.enabled

# Pose-level switches mute only their own output, and the authored weight is
# compiled into that pose's RBF output channel.
p1.enabled = False
assert coat.data.shape_keys.key_blocks[p1.bs_name].mute
assert all(fc.mute for fc in coat.data.shape_keys.animation_data.drivers
           if bs._owned_driver(fc, arm, {rule.id}) and bs._driver_owns_pose(fc, p1.id))
assert bs.generate_native_drivers(arm) == 4
assert all(fc.mute for fc in coat.data.shape_keys.animation_data.drivers
           if bs._owned_driver(fc, arm, {rule.id}) and bs._driver_owns_pose(fc, p1.id))
p1.enabled = True
p1.weight = 0.25
assert bs.generate_native_drivers(arm) == 4
assert all("*0.25" not in fc.driver.expression for fc in coat.data.shape_keys.animation_data.drivers
           if bs._owned_driver(fc, arm, {rule.id}) and bs._driver_owns_pose(fc, p1.id))
arm.pose.bones["Main"].rotation_quaternion = Euler((p1.x, p1.y, p1.z), "XYZ").to_quaternion()
bpy.context.view_layer.update()
close(coat.data.shape_keys.key_blocks[p1.bs_name].value, 0.25)
p1.weight = 1.0
assert bs.generate_native_drivers(arm) == 4

# Reset preserves sculpted keys by default, regardless of current BS value.
key = coat.data.shape_keys.key_blocks[p1.bs_name]
key.data[1].co.x = 1.4
trim_key = trim.data.shape_keys.key_blocks[p1.bs_name]
trim_key.data[1].co.x = 1.6
pointer = key.as_pointer()
key.value = trim_key.value = 0
assert not bs._shape_key_is_empty(key)

# Empty means zero delta to the relative key, not Basis or current weight.
reference = coat.shape_key_add(name="ResetReference")
reference.data[1].co.x = 1.2
empty_key = coat.data.shape_keys.key_blocks[p2.bs_name]
empty_key.relative_key = reference
empty_key.data.foreach_set("co", bs.read_shape_key_positions(reference).ravel())
assert bs._shape_key_is_empty(empty_key)

# The dialog scans every existing target without modifying any shape key.
class ResetChoices(list):
    def add(self):
        item = SimpleNamespace(
            mesh_name="", mesh_data_name="", key_name="", is_empty=False, overwrite=False,
        )
        self.append(item)
        return item


dialogs = []
dialog = SimpleNamespace(
    all_rules=False, armature_name=arm.name, existing_keys=ResetChoices(),
    existing_active_index=0, missing_count=0, scanned_all_rules=False, scan_error="",
)
dialog.indices = lambda context: bs._BatchRuleOperator.indices(dialog, context)
dialog._scan_existing_keys = lambda context: bs.OP_BsCorrectiveReset._scan_existing_keys(dialog, context)
dialog_context = SimpleNamespace(
    object=coat, scene=bpy.context.scene,
    window_manager=SimpleNamespace(
        invoke_props_dialog=lambda op, **kw: dialogs.append(op.all_rules) or {"RUNNING_MODAL"},
    ),
)
assert bs.OP_BsCorrectiveReset.invoke(dialog, dialog_context, SimpleNamespace(shift=False)) == {"RUNNING_MODAL"}
assert len(dialog.existing_keys) == 4 and dialog.missing_count == 0 and not dialog.scan_error
assert sum(item.is_empty for item in dialog.existing_keys) == 2
assert all(item.overwrite == item.is_empty for item in dialog.existing_keys)
close(key.data[1].co.x, 1.4)
close(trim_key.data[1].co.x, 1.6)

# Reopening discards earlier approvals; choosing a row never changes geometry
# until execute. The real operator collection supports per-mesh approvals.
approved = next(item for item in dialog.existing_keys if item.mesh_name == coat.name and item.key_name == p1.bs_name)
approved.overwrite = True
assert bs.OP_BsCorrectiveReset.invoke(dialog, dialog_context, SimpleNamespace(shift=False)) == {"RUNNING_MODAL"}
assert all(item.overwrite == item.is_empty for item in dialog.existing_keys)
assert bs.reset_correctives(arm) == 4
key = coat.data.shape_keys.key_blocks[p1.bs_name]
assert key.as_pointer() == pointer
close(key.data[1].co.x, 1.4)
close(trim_key.data[1].co.x, 1.6)
assert empty_key.relative_key == coat.data.shape_keys.reference_key
close(empty_key.data[1].co.x, 1)
close(reference.data[1].co.x, 1.2)
coat.shape_key_remove(reference)

# Tiny nonzero offsets are authored data too; a zero-valued key must survive.
empty_key.data[0].co.z = 1e-8
assert not bs._shape_key_is_empty(empty_key)
assert bs.reset_correctives(arm) == 4
assert empty_key.data[0].co.z > 0
assert bpy.ops.hotools.bs_corrective_reset(existing_keys=[{
    "name": "ResetCoatPose1",
    "mesh_name": coat.name, "mesh_data_name": coat.data.name, "key_name": p1.bs_name,
    "is_empty": False, "overwrite": True,
}]) == {"FINISHED"}
assert key.as_pointer() == pointer
close(key.data[1].co.x, 1)
close(trim_key.data[1].co.x, 1.6)

# Preserving sculpted coordinates must still replace the target's driver and
# compile the current rule weight, including an existing foreign driver.
bs._remove_shape_key_drivers(trim_key)
trim_key.driver_add("value").driver.expression = "0.125"
p1.weight = 0.35
assert bpy.ops.hotools.bs_corrective_reset() == {"FINISHED"}
close(trim_key.data[1].co.x, 1.6)
bpy.context.view_layer.update()
close(key.value, 0.35)
close(trim_key.value, 0.35)
assert all(fc.driver.is_valid and bs._owned_driver(fc, arm, {rule.id})
           for mesh in (coat, trim) for fc in mesh.data.shape_keys.animation_data.drivers)
# Disabled controls still rebuild their drivers in a muted state, so switching
# them back on works immediately without another refresh.
for controller in (rule, settings):
    controller.enabled = False
    assert bs.reset_correctives(arm) == 4
    assert all(len(mesh.data.shape_keys.animation_data.drivers) == 2 for mesh in (coat, trim))
    assert all(fc.mute for mesh in (coat, trim) for fc in mesh.data.shape_keys.animation_data.drivers)
    close(trim_key.data[1].co.x, 1.6)
    controller.enabled = True
    bpy.context.view_layer.update()
    close(trim_key.value, 0.35)
p1.weight = 1.0
assert bs.reset_correctives(arm, overwrite=True) == 4
close(key.data[1].co.x, 1)
close(trim_key.data[1].co.x, 1)

# Every authored pose drives the same named output on every rule mesh.
assert bs.generate_native_drivers(arm) == 4
assert len(coat.data.shape_keys.animation_data.drivers) == 2

# Conflicting names/points must fail before altering keys or existing drivers.
name = p2.bs_name
p2.bs_name = p1.bs_name
raises(lambda: bs.reset_correctives(arm), "duplicate BS name accepted")
assert len(coat.data.shape_keys.animation_data.drivers) == 2
p2.bs_name = name
pose2 = (p2.x, p2.y, p2.z)
p2.x, p2.y, p2.z = p1.x, p1.y, p1.z
warnings = []
assert bs.generate_native_drivers(arm, warnings=warnings) == 4
assert not warnings, "independent shape keys may share the same sampled pose"
assert len(coat.data.shape_keys.animation_data.drivers) == 2
p2.x, p2.y, p2.z = pose2
# A missing key only skips that target; the other rule meshes still refresh.
broken = mesh_object("Broken")
rule.influence_objects.add().mesh = broken
warnings = []
assert bs.generate_native_drivers(arm, warnings=warnings) == 4
assert any("找不到形态键" in warning for warning in warnings)
rule.influence_objects.remove(len(rule.influence_objects) - 1)
# Refresh protects foreign drivers; reset with overwrite explicitly replaces them.
foreign = coat.shape_key_add(name="Foreign")
foreign.driver_add("value").driver.expression = "0.25"
old_shape = p1.bs_name
p1.bs_name = "Foreign"
warnings = []
assert bs.generate_native_drivers(arm, warnings=warnings) == 2
assert any("其他驱动器" in warning for warning in warnings)
assert bs.reset_correctives(arm, overwrite=True) == 4
p1.bs_name = old_shape
assert bs.reset_correctives(arm, overwrite=True) == 4
# The overwrite reset intentionally removed the old foreign driver. Recreate
# it here so the cleanup assertion still verifies unrelated drivers survive.
foreign.driver_add("value").driver.expression = "0.25"

# Virtual reference sample is a native UIList row but cannot be removed/moved.
rule.pose_active_index = 0
assert list_edit("POINTS", "REMOVE") == {"CANCELLED"}
assert list_edit("POINTS", "DOWN") == {"CANCELLED"}
rule.pose_active_index = 1
assert list_edit("POINTS", "DOWN") == {"FINISHED"}
assert list_edit("POINTS", "UP") == {"FINISHED"}

# Export carries links; the zero baseline is fixed and not duplicated in samples.
p1.enabled = False
p2.weight = 0.4
config = bs.build_export_config(arm, measurement_bones={"Main": "MCH_Main"})
exported = config["rules"][0]
assert config["version"] == 5 and config["poseSpace"] == "LOCAL"
assert exported["measurementBone"] == "MCH_Main"
assert exported["rbf"]["includeBase"] and exported["rbf"]["basePose"] == [0, 0, 0, 1]
assert config["kernel"] == "smoothstep-compact" and config["evaluation"] == "independent"
assert not hasattr(rule, "rbf_radius")
assert len(exported["rbf"]["controlPoints"]) == 2
assert len(exported["tasks"]) == 2
assert {task["pointId"] for task in exported["tasks"]} == {point["id"] for point in exported["rbf"]["controlPoints"]}
assert all("enabled" in task and "weight" in task for task in exported["tasks"])
assert abs(exported["rbf"]["controlPoints"][0]["radius"] - p1.radius) < 1e-6
assert next(task for task in exported["tasks"] if task["pointId"] == p1.id)["enabled"] is False
close(next(task for task in exported["tasks"] if task["pointId"] == p2.id)["weight"], 0.4)
assert len(exported["influenceObjects"]) == 2
p1.enabled = True
p2.weight = 1.0
raises(lambda: bs._decode_rbf_payload('{"version":4}'), "old matrix payload accepted")

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
q = config["rules"][0]["rbf"]["controlPoints"][0]["pose"]
first = Quaternion((q[3], q[0], q[1], q[2])).to_euler("XYZ")
close(bs._driver_namespace_rbf(rule_id, first_id, *first), 1)
arm.pose.bones["Main"].rotation_quaternion = Euler(first, "XYZ").to_quaternion()
bpy.context.view_layer.update()
close(coat.data.shape_keys.key_blocks["_BSC_pose1"].value, 1)
assert all(fc.driver.is_valid for fc in coat.data.shape_keys.animation_data.drivers)
assert "hotools_bs_rbf" in bpy.app.driver_namespace
assert len(rule.pose_points) == 3 and rule.pose_points[0].id == bs._BASE_POINT

# Multiple outputs agree with Blender's own quaternion-distance reference.
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
    def angle(a, b):
        result = a.rotation_difference(b).angle
        return min(result, 2 * math.pi - result)
    def s(v):
        t = min(1.0, max(0.0, v))
        return t*t*(3-2*t)
    current = Euler(tuple(pose), "XYZ").to_quaternion()
    expected = []
    for p, radius, weight in zip(item[0], item[2], item[3]):
        target = Quaternion((p[3], p[0], p[1], p[2]))
        d, b, c = angle(current, target), angle(current, Quaternion()), angle(target, Quaternion())
        expected.append(weight * s(1-d/radius) * s((b+c-d)/(2*c)))
    actual = [bs._driver_namespace_rbf(large.id, point.id, *pose) for point in bs._authored_points(large)]
    assert np.max(np.abs(np.asarray(actual) - expected)) < 5e-6
print("RBF_SHARED_CACHE_24_OUTPUTS_OK", round((time.perf_counter()-start)*1000, 2), "ms including scalar reference")
settings.rules.remove(1)
bs._restore_driver_namespace(None)
assert "large-test" not in bs._RBF_RUNTIME

# Regression for the reported dense-pose cancellation: each real shape key
# keeps its independent support and can be active alongside both neighbors.
dense = settings.rules.add()
dense.id, dense.bone = "dense-independent", "Main"
dense.influence_objects.add().mesh = coat
for angle in (45, 60, 90):
    point = bs._add_point(arm, dense, (math.radians(angle), 0, 0))
    point.radius = math.radians(100)
assert bs.reset_correctives(arm, rule_indices=[1]) == 3
dense_names = [p.bs_name for p in bs._authored_points(dense)]
first_point = dense.pose_points[1]
first_key = coat.data.shape_keys.key_blocks[first_point.bs_name]
for angle, expected in ((0, 0), (45, 1), (60, 0.93925), (90, 0.57475), (120, 0.15625), (145, 0), (170, 0)):
    arm.pose.bones["Main"].rotation_quaternion = Euler((math.radians(angle), 0, 0), "XYZ").to_quaternion()
    bpy.context.view_layer.update()
    close(first_key.value, expected)
    close(bs._display_rbf_weight(dense, first_point, arm), expected)
arm.pose.bones["Main"].rotation_quaternion = Euler((math.radians(60), 0, 0), "XYZ").to_quaternion()
bpy.context.view_layer.update()
assert sum(coat.data.shape_keys.key_blocks[p.bs_name].value for p in bs._authored_points(dense)) > 2
first_point.radius = math.radians(30)
native_before = first_key.value
first_point.radius = math.radians(100)
assert first_key.value > native_before
close(first_key.value, 0.93925)
first_point.weight = 0.4
close(first_key.value, 0.93925 * 0.4)
other_values = [coat.data.shape_keys.key_blocks[p.bs_name].value for p in bs._authored_points(dense)[1:]]
first_point.enabled = False
assert first_key.mute and first_key.value == 0
assert other_values == [coat.data.shape_keys.key_blocks[p.bs_name].value for p in bs._authored_points(dense)[1:]]
first_point.enabled = True
close(first_key.value, 0.93925 * 0.4)
# Removing a neighboring pose does not change this shape's real driver value.
dense.pose_points.remove(3)
assert bs.generate_native_drivers(arm, [1]) == 2
bpy.context.view_layer.update()
close(first_key.value, 0.93925 * 0.4)
slices = bs.BsCorrectivePreview._pose_slices(first_point)
assert sum(len(vertices) for vertices in slices) > 300
assert all(math.isfinite(v) for vertices in slices for vertex in vertices for v in vertex)
bs.remove_native_drivers(arm, [1])
settings.rules.remove(1)
for name in dense_names:
    coat.shape_key_remove(coat.data.shape_keys.key_blocks[name])

# Batch reset and refresh process a second rule; ordinary operations stay local.
batch = settings.rules.add()
batch.id, batch.bone = "batch-test", "Main"
batch.influence_objects.add().mesh = coat
bs._add_point(arm, batch, (0.1, 0.7, -0.5))
assert bs.OP_BsCorrectiveReset.invoke(dialog, dialog_context, SimpleNamespace(shift=True)) == {"RUNNING_MODAL"}
assert dialog.all_rules and dialog.missing_count == 1
assert len(dialog.existing_keys) == 4
dialog.all_rules = False
assert bs.OP_BsCorrectiveReset.check(dialog, dialog_context)
assert dialog.missing_count == 0
assert not bs.OP_BsCorrectiveReset.check(dialog, dialog_context)
assert bpy.ops.hotools.bs_corrective_reset(all_rules=True) == {"FINISHED"}
assert "batch-test" in bs._RBF_RUNTIME
settings.active_index = 0
rule.enabled = False
assert all(fc.mute for fc in coat.data.shape_keys.animation_data.drivers if bs._owned_driver(fc, arm, {rule.id}))
rule.enabled = True
assert not any(fc.mute for fc in coat.data.shape_keys.animation_data.drivers if bs._owned_driver(fc, arm, {rule.id}))
bs.remove_native_drivers(arm, [0])
assert rule.id not in bs._RBF_RUNTIME and "batch-test" in bs._RBF_RUNTIME
assert bpy.ops.hotools.bs_corrective_generate_drivers(all_rules=True) == {"FINISHED"}
assert rule.id in bs._RBF_RUNTIME and "batch-test" in bs._RBF_RUNTIME
dialogs = []
fake_context = SimpleNamespace(window_manager=SimpleNamespace(invoke_props_dialog=lambda op, **kw: dialogs.append(op.all_rules) or {"RUNNING_MODAL"}))
for operator_type in (bs.OP_BsCorrectiveGenerateDrivers,):
    op = SimpleNamespace(bl_idname=operator_type.bl_idname, all_rules=False)
    assert bs._BatchRuleOperator.invoke(op, fake_context, SimpleNamespace(shift=True)) == {"RUNNING_MODAL"}
assert dialogs == [True]

# Remove the second rule and clear authored poses through the native pose list.
bs.remove_native_drivers(arm)
settings.rules.remove(1)
bpy.context.view_layer.objects.active = arm
settings.active_index = 0
assert list_edit("POINTS", "CLEAR") == {"FINISHED"}
assert len(rule.pose_points) == 1
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
