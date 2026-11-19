"""Regression for BS mesh references after HoFBX applies the armature rest pose.

Run with --background --factory-startup --enable-autoexec --python this_file.py.
"""
import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON_DIR))

from HoTools.Exporter.FbxExporter import FBXExporter
from HoTools.Rbf import bs_corrective as bs


bs.register()
data = bpy.data.armatures.new("ExportTargetsRigData")
armature = bpy.data.objects.new("ExportTargetsRig", data)
bpy.context.scene.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
bone = data.edit_bones.new("Main")
bone.head = (0, 0, 0)
bone.tail = (0, 1, 0)
bpy.ops.object.mode_set(mode="OBJECT")


def make_mesh(name):
    mesh_data = bpy.data.meshes.new(name + "Data")
    mesh_data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(obj)
    obj.shape_key_add(name="Basis")
    obj.shape_key_add(name="_BSC_pose1")
    return obj


old_mesh = make_mesh("ExportTargetsMesh")
rule = armature.hotools_bs_corrective.rules.add()
rule.id = "export-target-regression"
rule.bone = "Main"
rule.influence_objects.add().mesh = old_mesh
bs._add_point(armature, rule, (0.6, 0.2, -0.1))

state = FBXExporter.capture_bs_corrective_mesh_names([armature])
assert state == [(rule.influence_objects[0], "ExportTargetsMesh")]
bpy.data.objects.remove(old_mesh, do_unlink=True)
replacement = make_mesh("ExportTargetsMesh")
assert rule.influence_objects[0].mesh is None
assert FBXExporter.restore_bs_corrective_mesh_references(state) == 1
assert rule.influence_objects[0].mesh == replacement

config = bs.build_export_config(armature)
targets = config["rules"][0]["tasks"][0]["targets"]
assert targets == [{"mesh": "ExportTargetsMesh", "shapeKey": "_BSC_pose1"}]
print("BS_EXPORT_TARGET_RESTORE_OK")
