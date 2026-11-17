"""Exercise RBF corrective drivers, including Blender's short RNA field."""

import math
import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON_DIR))
bpy.ops.preferences.addon_enable(module="HoTools")

from HoTools.Rbf.bs_corrective import (  # noqa: E402
    build_export_config,
    generate_native_drivers,
    remove_native_drivers,
)


def build_scene():
    arm_data = bpy.data.armatures.new("BsCorrectiveTestRigData")
    armature = bpy.data.objects.new("BsCorrectiveTestRig", arm_data)
    bpy.context.scene.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = arm_data.edit_bones.new("Main")
    bone.head = (0, 0, 0)
    bone.tail = (0, 1, 0)
    bpy.ops.object.mode_set(mode="OBJECT")

    mesh_data = bpy.data.meshes.new("BsCorrectiveTestMeshData")
    mesh_data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    mesh = bpy.data.objects.new("BsCorrectiveTestMesh", mesh_data)
    bpy.context.scene.collection.objects.link(mesh)
    mesh.shape_key_add(name="Basis")
    mesh.shape_key_add(name="_BSC_pose1")
    return armature, mesh


armature, mesh = build_scene()
settings = armature.hotools_bs_corrective
rule = settings.rules.add()
rule.id = "test-rbf"
rule.bone = "Main"
rule.mesh = mesh
rule.shape_key = "_BSC_pose1"
rule.bs_name = "_BSC_pose1"
rule.mode = "RBF"
rule.rbf_radius = 0.5
for index in range(12):
    point = rule.pose_points.add()
    point.x = math.radians(index + 1)
    point.y = math.radians(index % 3 - 1)
    point.z = math.radians(index % 4 - 2)
    point.weight = (index % 4) / 3

assert generate_native_drivers(armature) == 1
driver = mesh.data.shape_keys.animation_data.drivers[0].driver
assert len(driver.expression) < 256
helper_objects = [
    obj for obj in bpy.data.objects if obj.name.startswith(".HoToolsBSDriverCache.")
]
assert helper_objects and helper_objects[0].animation_data.drivers

armature.pose.bones["Main"].rotation_mode = "XYZ"
armature.pose.bones["Main"].rotation_euler = (
    math.radians(2),
    math.radians(0),
    math.radians(-1),
)
bpy.context.view_layer.update()
assert math.isfinite(mesh.data.shape_keys.key_blocks["_BSC_pose1"].value)

config = build_export_config(armature, measurement_bones={"Main": "MCH_Main"})
exported = config["rules"][0]
assert exported["mode"] == "RBF"
assert exported["bsName"] == "_BSC_pose1"
assert exported["measurementBone"] == "MCH_Main"
assert len(exported["rbfPoints"]) == 12

remove_native_drivers(armature)
assert not [obj for obj in bpy.data.objects if obj.name.startswith(".HoToolsBSDriverCache.")]
assert not mesh.data.shape_keys.animation_data.drivers
print("BS_CORRECTIVE_OK")
