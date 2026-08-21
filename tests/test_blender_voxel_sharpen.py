"""Background-Blender coverage for the selected voxel sharpen operators."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import bpy
import bmesh
import gpu


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))
package = types.ModuleType("HoTools")
package.__path__ = [str(ADDON_DIR)]
sys.modules.setdefault("HoTools", package)
original_shader_from_builtin = gpu.shader.from_builtin
gpu.shader.from_builtin = lambda _name: None
try:
    operators = importlib.import_module(
        "HoTools.VertexGroupTools.vertexGroupOperators"
    )
finally:
    gpu.shader.from_builtin = original_shader_from_builtin


def activate(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


mesh_data = bpy.data.meshes.new("VoxelSharpenTestMeshData")
mesh_data.from_pydata(
    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)],
    [(0, 1), (1, 2), (2, 3)],
    [],
)
mesh_obj = bpy.data.objects.new("VoxelSharpenTestMesh", mesh_data)
bpy.context.scene.collection.objects.link(mesh_obj)
activate(mesh_obj)

group_a = mesh_obj.vertex_groups.new(name="BoneA")
group_b = mesh_obj.vertex_groups.new(name="BoneB")
group_a.add([0, 1, 2], 0.2, "REPLACE")
group_a.add([1], 0.8, "REPLACE")
group_a.add([3], 0.95, "REPLACE")
group_b.add([0, 1, 2], 0.8, "REPLACE")
group_b.add([1], 0.2, "REPLACE")
group_b.add([3], 0.05, "REPLACE")
mesh_obj.vertex_groups.active_index = group_a.index

# A unique armature makes BoneA/B eligible for the all-bone operator.
arm_data = bpy.data.armatures.new("VoxelSharpenTestArmatureData")
armature = bpy.data.objects.new("VoxelSharpenTestArmature", arm_data)
bpy.context.scene.collection.objects.link(armature)
activate(armature)
bpy.ops.object.mode_set(mode="EDIT")
bone_a = arm_data.edit_bones.new("BoneA")
bone_a.head = (0.0, 0.0, 0.0)
bone_a.tail = (0.0, 1.0, 0.0)
bone_b = arm_data.edit_bones.new("BoneB")
bone_b.head = (1.0, 0.0, 0.0)
bone_b.tail = (1.0, 1.0, 0.0)
bpy.ops.object.mode_set(mode="OBJECT")
modifier = mesh_obj.modifiers.new("VoxelSharpenTestArmatureModifier", "ARMATURE")
modifier.object = armature

activate(mesh_obj)
bpy.ops.object.mode_set(mode="EDIT")
edit_bmesh = bmesh.from_edit_mesh(mesh_data)
for vert in edit_bmesh.verts:
    vert.select = vert.index < 3
bmesh.update_edit_mesh(mesh_data, loop_triangles=False, destructive=False)
mesh_obj.vertex_groups.active_index = group_a.index

operators.register()

before_unselected = mesh_obj.vertex_groups[group_a.name].weight(3)
result = bpy.ops.ho.vertexgrouptools_sharpen_weight(
    strength=1.0,
    resolution_mode='MANUAL',
    voxel_resolution=24,
    blur_radius=1,
    iterations=1,
    topology_hops=2,
)
assert result == {'FINISHED'}, result
assert abs(mesh_obj.vertex_groups[group_a.name].weight(3) - before_unselected) < 1e-12

# Lock BoneB and ensure all-bone sharpening leaves it untouched while still
# operating on the selected rows of the free BoneA group.
group_b.lock_weight = True
before_locked = [group_b.weight(index) for index in range(4)]
result = bpy.ops.ho.vertexgrouptools_sharpen_weight_allbone(
    strength=1.0,
    resolution_mode='MANUAL',
    voxel_resolution=24,
    blur_radius=1,
    iterations=1,
    topology_hops=2,
)
assert result == {'FINISHED'}, result
after_locked = [group_b.weight(index) for index in range(4)]
assert after_locked == before_locked
for index in range(3):
    assert abs(group_a.weight(index) + group_b.weight(index) - 1.0) < 1e-6

bpy.ops.object.mode_set(mode="OBJECT")
operators.unregister()
bpy.data.objects.remove(mesh_obj, do_unlink=True)
bpy.data.objects.remove(armature, do_unlink=True)
bpy.data.meshes.remove(mesh_data)
bpy.data.armatures.remove(arm_data)
print("test_blender_voxel_sharpen: PASS")
