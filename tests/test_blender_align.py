import sys
import unittest
from math import radians
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Vector


ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

import ObjectTools  # noqa: E402


def new_empty(name, location=(0.0, 0.0, 0.0)):
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    return obj


def select_objects(objects, active):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active


class AlignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ObjectTools.register()

    @classmethod
    def tearDownClass(cls):
        ObjectTools.unregister()

    def tearDown(self):
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        for mesh in list(bpy.data.meshes):
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)

    def test_aligns_to_active_object_and_respects_axis_switches(self):
        target = new_empty("Target", (3.0, 4.0, 5.0))
        target.rotation_euler = (0.2, -0.3, 0.6)
        target.scale = (2.0, 3.0, 4.0)
        source = new_empty("Source", (10.0, 20.0, 30.0))
        source.rotation_euler = (-0.4, 0.1, -0.2)
        source.scale = (0.5, 0.75, 1.25)
        select_objects((source, target), target)

        result = bpy.ops.ho.align(
            mode='ACTIVE',
            location=True,
            rotation=True,
            scale=True,
        )
        self.assertEqual(result, {'FINISHED'})
        source_loc, source_rot, source_scale = source.matrix_world.decompose()
        target_loc, target_rot, target_scale = target.matrix_world.decompose()
        self.assertLess((source_loc - target_loc).length, 1e-6)
        self.assertLess(source_rot.rotation_difference(target_rot).angle, 1e-6)
        self.assertLess((source_scale - target_scale).length, 1e-6)

        source.location = (10.0, 20.0, 30.0)
        source.rotation_euler = (0.0, 0.0, 0.0)
        source.scale = (1.0, 1.0, 1.0)
        select_objects((source, target), target)
        bpy.ops.ho.align(
            mode='ACTIVE',
            location=True,
            rotation=False,
            scale=False,
            loc_x=True,
            loc_y=False,
            loc_z=True,
        )
        self.assertLess((source.location - Vector((3.0, 20.0, 5.0))).length, 1e-6)

    def test_floor_and_inbetween_alignment(self):
        mesh = bpy.data.meshes.new("FloorMesh")
        mesh.from_pydata(
            [(-1.0, -1.0, -2.0), (1.0, -1.0, 0.0), (0.0, 1.0, 1.0)],
            [],
            [(0, 1, 2)],
        )
        floor_obj = bpy.data.objects.new("FloorObject", mesh)
        bpy.context.collection.objects.link(floor_obj)
        floor_obj.location.z = 7.0
        select_objects((floor_obj,), floor_obj)
        bpy.ops.ho.align(mode='FLOOR')
        min_world_z = min(
            (floor_obj.matrix_world @ vertex.co).z
            for vertex in floor_obj.data.vertices
        )
        self.assertAlmostEqual(min_world_z, 0.0, places=6)

        endpoint_a = new_empty("EndpointA", (0.0, 0.0, 0.0))
        endpoint_b = new_empty("EndpointB", (4.0, 0.0, 0.0))
        middle = new_empty("Middle", (20.0, 5.0, 1.0))
        select_objects((endpoint_a, endpoint_b, middle), middle)
        bpy.ops.ho.align(inbetween=True)
        self.assertLess((middle.location - Vector((2.0, 0.0, 0.0))).length, 1e-6)

    def test_skip_children_preserves_child_world_transform(self):
        target = new_empty("Target", (8.0, 3.0, 2.0))
        source = new_empty("Source", (1.0, 2.0, 3.0))
        child = new_empty("Child", (4.0, 5.0, 6.0))
        child.parent = source
        child.matrix_parent_inverse = source.matrix_world.inverted_safe()
        child.matrix_world.translation = Vector((4.0, 5.0, 6.0))
        bpy.context.view_layer.update()
        original_child_matrix = child.matrix_world.copy()
        previous_setting = bpy.context.scene.tool_settings.use_transform_skip_children
        bpy.context.scene.tool_settings.use_transform_skip_children = True
        try:
            select_objects((source, target), target)
            bpy.ops.ho.align(
                mode='ACTIVE',
                location=True,
                rotation=False,
                scale=False,
            )
            bpy.context.view_layer.update()
            difference = child.matrix_world.inverted_safe() @ original_child_matrix
            self.assertLess((difference.to_translation()).length, 1e-6)
            self.assertLess(difference.to_quaternion().angle, 1e-6)
        finally:
            bpy.context.scene.tool_settings.use_transform_skip_children = previous_setting

    def test_aligns_selected_object_to_active_pose_bone(self):
        armature_data = bpy.data.armatures.new("AlignArmature")
        armature = bpy.data.objects.new("AlignArmature", armature_data)
        bpy.context.collection.objects.link(armature)
        target = new_empty("BoneTarget", (5.0, 4.0, 3.0))

        select_objects((armature, target), armature)
        bpy.ops.object.mode_set(mode='EDIT')
        edit_bone = armature_data.edit_bones.new("TargetBone")
        edit_bone.head = (0.0, 0.0, 0.0)
        edit_bone.tail = (0.0, 2.0, 0.0)
        bpy.ops.object.mode_set(mode='POSE')

        bone = armature_data.bones["TargetBone"]
        armature_data.bones.active = bone
        bone.select = True
        target.select_set(True)
        bpy.context.view_layer.objects.active = armature
        self.assertIn(target, bpy.context.selected_objects)

        result = bpy.ops.ho.align(
            mode='ACTIVE',
            parent_to_bone=False,
            align_z_to_y=True,
            roll=False,
        )
        self.assertEqual(result, {'FINISHED'})
        expected = (
            armature.matrix_world
            @ armature.pose.bones["TargetBone"].matrix
            @ Matrix.Rotation(radians(-90.0), 4, 'X')
        )
        difference = expected.inverted_safe() @ target.matrix_world
        self.assertLess(difference.to_translation().length, 1e-6)
        self.assertLess(difference.to_quaternion().angle, 1e-6)

    def test_relative_alignment_reparents_duplicate_to_target(self):
        reference = new_empty("Reference", (2.0, 0.0, 0.0))
        aligner = new_empty("Aligner", (4.0, 1.0, 0.0))
        aligner.parent = reference
        aligner.matrix_parent_inverse = reference.matrix_world.inverted_safe()
        bpy.context.view_layer.update()

        target = new_empty("Target", (10.0, 3.0, 0.0))
        duplicate = aligner.copy()
        bpy.context.collection.objects.link(duplicate)
        op = SimpleNamespace(
            active=reference,
            orig_sel=[reference, aligner],
        )
        duplicate_data = {'map': {aligner: duplicate}, 'dups': [duplicate]}

        ObjectTools.OP_AlignRelative.reparent(
            op,
            duplicate_data,
            target,
            duplicate,
        )
        bpy.context.view_layer.update()
        self.assertIs(duplicate.parent, target)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AlignTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
