import importlib.util
import sys
import types
import unittest
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


ADDON_ROOT = Path(__file__).resolve().parents[1]


def load_placement():
    package_name = "hotools_orthogonal_snap_test"
    module_name = f"{package_name}.placement"
    if module_name in sys.modules:
        return sys.modules[module_name]

    package = types.ModuleType(package_name)
    package.__path__ = [str(ADDON_ROOT / "ObjectTools")]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(
        module_name,
        ADDON_ROOT / "ObjectTools" / "placement.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class OrthogonalSnapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.placement = load_placement()
        bpy.utils.register_class(cls.placement.OP_PlaceObjectBottom)
        bpy.utils.register_class(cls.placement.OP_SnapSelectedFaceOrthogonal)

    @classmethod
    def tearDownClass(cls):
        bpy.utils.unregister_class(cls.placement.OP_SnapSelectedFaceOrthogonal)
        bpy.utils.unregister_class(cls.placement.OP_PlaceObjectBottom)

    def setUp(self):
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)

    def _make_selected_cube(self):
        bpy.ops.mesh.primitive_cube_add(location=(2.5, -1.75, 4.25))
        obj = bpy.context.object
        obj.rotation_euler = (0.43, -0.31, 0.68)
        obj.scale = (1.4, 0.75, 1.9)
        bpy.context.view_layer.update()

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        selected_face = max(
            bm.faces,
            key=lambda face: face.calc_center_median().x,
        )
        selected_face.select = True
        bmesh.update_edit_mesh(obj.data, destructive=False)
        return obj

    def _selected_world_normal(self, obj):
        if bpy.context.mode == 'EDIT_MESH':
            bm = bmesh.from_edit_mesh(obj.data)
            bm.normal_update()
            normal = next(face.normal for face in bm.faces if face.select)
        else:
            obj.data.update()
            normal = next(
                polygon.normal
                for polygon in obj.data.polygons
                if polygon.select
            )
        normal_matrix = obj.matrix_world.to_3x3().inverted_safe().transposed()
        return (normal_matrix @ normal).normalized()

    def _world_vertex_distances(self, obj):
        origin = obj.matrix_world.translation
        if bpy.context.mode == 'EDIT_MESH':
            vertices = bmesh.from_edit_mesh(obj.data).verts
        else:
            vertices = obj.data.vertices
        return [
            ((obj.matrix_world @ vertex.co) - origin).length
            for vertex in vertices
        ]

    def test_nearest_world_axis_uses_signed_dominant_component(self):
        cases = (
            ((0.9, 0.2, -0.1), (1.0, 0.0, 0.0)),
            ((-0.9, 0.2, 0.1), (-1.0, 0.0, 0.0)),
            ((0.1, 0.9, 0.2), (0.0, 1.0, 0.0)),
            ((0.1, -0.9, 0.2), (0.0, -1.0, 0.0)),
            ((0.2, 0.1, 0.9), (0.0, 0.0, 1.0)),
            ((0.2, 0.1, -0.9), (0.0, 0.0, -1.0)),
        )
        for normal, expected in cases:
            with self.subTest(normal=normal):
                actual = self.placement.nearest_world_axis(Vector(normal))
                self.assertLess((actual - Vector(expected)).length, 1e-7)
                self.assertEqual(
                    self.placement.world_axis_label(actual),
                    f"{'+' if max(expected) > 0.0 else '-'}"
                    f"{'XYZ'[next(i for i, value in enumerate(expected) if value)]}",
                )

    def test_selected_snap_keeps_origin_transform_and_location(self):
        obj = self._make_selected_cube()
        matrix_before = obj.matrix_world.copy()
        normal_before = self._selected_world_normal(obj)
        target_axis = self.placement.nearest_world_axis(normal_before)
        distances_before = self._world_vertex_distances(obj)

        result = bpy.ops.ho.snap_selected_face_orthogonal(
            keep_origin_transform=True,
        )

        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertLess(
            sum(
                abs(value)
                for row in (obj.matrix_world - matrix_before)
                for value in row
            ),
            1e-7,
        )
        self.assertGreater(
            self._selected_world_normal(obj).dot(target_axis),
            0.999999,
        )
        for before, after in zip(
            distances_before,
            self._world_vertex_distances(obj),
        ):
            self.assertAlmostEqual(before, after, places=5)

    def test_selected_snap_is_undoable_in_edit_mode(self):
        obj = self._make_selected_cube()
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        vertices_before = [vertex.co.copy() for vertex in bm.verts]
        bpy.ops.ed.undo_push(message="before orthogonal face snap")

        result = bpy.ops.ho.snap_selected_face_orthogonal(
            keep_origin_transform=True,
        )
        self.assertEqual(result, {'FINISHED'})

        bpy.ops.ed.undo_push(message="orthogonal face snap")
        self.assertEqual(bpy.ops.ed.undo(), {'FINISHED'})
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        for before, vertex in zip(vertices_before, bm.verts):
            self.assertLess((before - vertex.co).length, 1e-6)

    def test_snap_completes_bottom_placement_alignment(self):
        obj = self._make_selected_cube()
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            face.select = False
        bottom_face = min(
            bm.faces,
            key=lambda face: face.calc_center_median().z,
        )
        bottom_index = bottom_face.index
        bottom_face.select = True
        bmesh.update_edit_mesh(obj.data, destructive=False)

        self.assertEqual(
            bpy.ops.ho.placeobjectbottom(keep_origin_transform=True),
            {'FINISHED'},
        )

        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.normal_update()
        for face in bm.faces:
            face.select = False
        normal_matrix = obj.matrix_world.to_3x3().inverted_safe().transposed()
        side_face = min(
            (
                face for face in bm.faces
                if face.index != bottom_index
            ),
            key=lambda face: abs(
                (normal_matrix @ face.normal).normalized().z
            ),
        )
        side_face.select = True
        side_normal_before = (
            normal_matrix @ side_face.normal
        ).normalized()
        target_axis = self.placement.nearest_world_axis(side_normal_before)
        bmesh.update_edit_mesh(obj.data, destructive=False)

        self.assertEqual(
            bpy.ops.ho.snap_selected_face_orthogonal(
                keep_origin_transform=True,
            ),
            {'FINISHED'},
        )

        self.assertGreater(
            self._selected_world_normal(obj).dot(target_axis),
            0.999999,
        )
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.normal_update()
        bottom_face = bm.faces[bottom_index]
        bottom_normal = (
            obj.matrix_world.to_3x3().inverted_safe().transposed() @
            bottom_face.normal
        ).normalized()
        self.assertGreater(
            bottom_normal.dot(Vector((0.0, 0.0, -1.0))),
            0.999999,
        )
        for vertex in bottom_face.verts:
            world_point = obj.matrix_world @ vertex.co
            self.assertAlmostEqual(world_point.z, 0.0, places=5)

    def test_selected_snap_can_change_only_object_rotation(self):
        obj = self._make_selected_cube()
        location_before = obj.matrix_world.translation.copy()
        matrix_before = obj.matrix_world.copy()
        normal_before = self._selected_world_normal(obj)
        target_axis = self.placement.nearest_world_axis(normal_before)
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        vertices_before = [vertex.co.copy() for vertex in bm.verts]

        result = bpy.ops.ho.snap_selected_face_orthogonal(
            keep_origin_transform=False,
        )

        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(bpy.context.mode, 'OBJECT')
        self.assertLess(
            (obj.matrix_world.translation - location_before).length,
            1e-7,
        )
        self.assertGreater(
            sum(
                abs(value)
                for row in (obj.matrix_world - matrix_before)
                for value in row
            ),
            1e-5,
        )
        self.assertGreater(
            self._selected_world_normal(obj).dot(target_axis),
            0.999999,
        )
        for before, vertex in zip(vertices_before, obj.data.vertices):
            self.assertLess((before - vertex.co).length, 1e-7)

    def test_auto_snap_execute_reuses_stored_face_normal(self):
        obj = self._make_selected_cube()
        matrix_before = obj.matrix_world.copy()
        location_before = matrix_before.translation.copy()
        normal_before = self._selected_world_normal(obj)
        target_axis = self.placement.nearest_world_axis(normal_before)
        normal_local = (
            matrix_before.to_3x3().transposed() @ normal_before
        ).normalized()
        operator = types.SimpleNamespace(
            has_placement_plane=True,
            placement_normal_local=normal_local,
            keep_origin_transform=True,
        )

        result = self.placement.OP_AutoSnapFaceOrthogonal.execute(
            operator,
            bpy.context,
        )

        self.assertEqual(result, {'FINISHED'})
        self.assertLess(
            (obj.matrix_world.translation - location_before).length,
            1e-7,
        )
        self.assertGreater(
            self._selected_world_normal(obj).dot(target_axis),
            0.999999,
        )


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        OrthogonalSnapTests
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
