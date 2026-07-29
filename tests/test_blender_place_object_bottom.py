import importlib.util
import math
import sys
import types
import unittest
from pathlib import Path

import bmesh
import bpy
from mathutils import Euler, Vector


ADDON_ROOT = Path(__file__).resolve().parents[1]


def load_fast_operators():
    package_name = "hotools_place_bottom_test"
    module_name = f"{package_name}.FastOperators"
    if module_name in sys.modules:
        return sys.modules[module_name]

    package = types.ModuleType(package_name)
    package.__path__ = [str(ADDON_ROOT)]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(
        module_name,
        ADDON_ROOT / "FastOperators.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class PlaceObjectBottomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fast_operators = load_fast_operators()
        bpy.utils.register_class(cls.fast_operators.OP_PlaceObjectBottom)

    @classmethod
    def tearDownClass(cls):
        bpy.utils.unregister_class(cls.fast_operators.OP_PlaceObjectBottom)

    def setUp(self):
        bpy.ops.object.mode_set(mode='OBJECT') if bpy.context.object else None
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)

    def _make_cube(self, rotation, scale, location, rotation_mode='XYZ'):
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.object
        obj.rotation_mode = rotation_mode
        if rotation_mode == 'QUATERNION':
            obj.rotation_quaternion = Euler(rotation).to_quaternion()
        else:
            obj.rotation_euler = rotation
        obj.scale = scale
        obj.location = location
        bpy.context.view_layer.update()

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bottom_face = min(
            bm.faces,
            key=lambda face: sum(vert.co.z for vert in face.verts),
        )
        bottom_face.select = True
        bmesh.update_edit_mesh(obj.data, destructive=False)
        return obj

    def _assert_placed(self, obj):
        bm = bmesh.from_edit_mesh(obj.data)
        bm.normal_update()
        selected_faces = [face for face in bm.faces if face.select]
        self.assertEqual(len(selected_faces), 1)
        selected_face = selected_faces[0]
        world_points = [obj.matrix_world @ vert.co for vert in selected_face.verts]
        for point in world_points:
            self.assertAlmostEqual(point.z, 0.0, places=5)

        normal_matrix = obj.matrix_world.to_3x3().inverted_safe().transposed()
        world_normal = (normal_matrix @ selected_face.normal).normalized()
        self.assertGreater(world_normal.dot(Vector((0.0, 0.0, -1.0))), 0.99999)
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')

    def test_rotated_nonuniform_scaled_cube(self):
        obj = self._make_cube(
            rotation=(0.71, -0.38, 1.13),
            scale=(2.5, 0.45, 1.7),
            location=(4.0, -3.0, 6.0),
        )
        result = bpy.ops.ho.placeobjectbottom()
        self.assertEqual(result, {'FINISHED'})
        self._assert_placed(obj)

    def test_quaternion_rotation_mode_is_preserved(self):
        obj = self._make_cube(
            rotation=(-0.46, 0.82, -0.27),
            scale=(0.7, 2.2, 1.1),
            location=(-2.0, 5.0, -1.5),
            rotation_mode='QUATERNION',
        )
        result = bpy.ops.ho.placeobjectbottom()
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(obj.rotation_mode, 'QUATERNION')
        self._assert_placed(obj)

    def test_parented_object_uses_world_ground_plane(self):
        bpy.ops.object.empty_add(
            location=(2.0, -4.0, 3.0),
            rotation=(0.35, -0.25, 0.6),
        )
        parent = bpy.context.object
        parent.scale = (1.3, 0.8, 1.6)

        obj = self._make_cube(
            rotation=(0.43, 0.28, -0.91),
            scale=(1.4, 0.65, 2.0),
            location=(3.0, 1.0, 4.0),
        )
        world_before_parenting = obj.matrix_world.copy()
        obj.parent = parent
        obj.matrix_world = world_before_parenting
        bpy.context.view_layer.update()

        result = bpy.ops.ho.placeobjectbottom()
        self.assertEqual(result, {'FINISHED'})
        self._assert_placed(obj)

    def test_upward_normal_flips_exactly(self):
        obj = self._make_cube(
            rotation=(math.pi, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            location=(0.0, 0.0, 2.0),
        )
        result = bpy.ops.ho.placeobjectbottom()
        self.assertEqual(result, {'FINISHED'})
        self._assert_placed(obj)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        PlaceObjectBottomTests
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
