import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import MeshTools  # noqa: E402
import HoPie  # noqa: E402


class PieRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        MeshTools.register()
        HoPie.register()

    @classmethod
    def tearDownClass(cls):
        MeshTools.unregister()
        HoPie.unregister()

    def tearDown(self):
        HoPie.set_pie_enabled('align', False)
        HoPie.set_pie_enabled('cursor', False)
        if hasattr(bpy.types.Scene, 'ho_align_pie_mode'):
            bpy.context.scene.ho_align_pie_mode = 'VIEW'

    def test_align_pie_is_independently_toggleable(self):
        HoPie.set_pie_enabled('align', True)
        self.assertIsNotNone(getattr(bpy.types, 'HO_MT_align_pie', None))
        self.assertIsNotNone(getattr(bpy.types, 'HO_MT_uv_align_pie', None))
        ids = [item.idname for _, item in HoPie.align_pie_keymaps]
        self.assertEqual(
            ids,
            ['wm.call_menu_pie', 'wm.call_menu_pie', 'wm.call_menu_pie'],
        )
        self.assertEqual({item.properties.name for _, item in HoPie.align_pie_keymaps}, {'HO_MT_align_pie', 'HO_MT_uv_align_pie'})
        uv_keymap = next(
            keymap
            for keymap, item in HoPie.align_pie_keymaps
            if item.properties.name == 'HO_MT_uv_align_pie'
        )
        self.assertEqual(uv_keymap.name, 'UV Editor')
        self.assertEqual(uv_keymap.space_type, 'EMPTY')
        curve_keymap = next(
            keymap
            for keymap, item in HoPie.align_pie_keymaps
            if keymap.name == 'Curve'
            and item.properties.name == 'HO_MT_align_pie'
        )
        self.assertEqual(curve_keymap.space_type, 'EMPTY')
        for keymap, item in HoPie.align_pie_keymaps:
            self.assertEqual(keymap.keymap_items[0].id, item.id)
        HoPie.set_pie_enabled('align', False)
        self.assertIsNone(getattr(bpy.types, 'HO_MT_align_pie', None))
        self.assertEqual(HoPie.align_pie_keymaps, [])

    def test_pies_are_disabled_by_default(self):
        self.assertFalse(HoPie._align_pie_enabled)
        self.assertFalse(HoPie._cursor_pie_enabled)
        self.assertIsNone(getattr(bpy.types, 'HO_MT_align_pie', None))
        self.assertIsNone(getattr(bpy.types, 'HO_MT_cursor_pie', None))
        self.assertEqual(bpy.context.scene.ho_align_pie_mode, 'VIEW')

    def test_cursor_pie_is_independently_toggleable(self):
        HoPie.set_pie_enabled('cursor', True)
        self.assertIsNotNone(getattr(bpy.types, 'HO_MT_cursor_pie', None))
        self.assertEqual(len(HoPie.cursor_pie_keymaps), 1)
        keymap, item = HoPie.cursor_pie_keymaps[0]
        self.assertEqual(keymap.name, '3D View Generic')
        self.assertEqual((item.type, item.shift, item.properties.name), ('S', True, 'HO_MT_cursor_pie'))
        self.assertEqual(keymap.keymap_items[0].id, item.id)
        HoPie.set_pie_enabled('cursor', False)
        self.assertIsNone(getattr(bpy.types, 'HO_MT_cursor_pie', None))
        self.assertEqual(HoPie.cursor_pie_keymaps, [])

    def test_mesh_alignment_and_cursor_operations_execute(self):
        HoPie.set_pie_enabled('align', True)
        mesh = bpy.data.meshes.new('PieMesh')
        mesh.from_pydata([(-1, 0, 0), (2, 0, 0), (4, 0, 0)], [(0, 1), (1, 2)], [])
        obj = bpy.data.objects.new('PieObject', mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        self.assertEqual(bpy.ops.ho.align_editmesh(type='AVERAGE', axis='X'), {'FINISHED'})
        bpy.ops.object.mode_set(mode='OBJECT')
        self.assertTrue(all(abs(vertex.co.x - 5.0 / 3.0) < 1e-6 for vertex in mesh.vertices))
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.scene.cursor.location = (3, 4, 5)
        HoPie.set_pie_enabled('cursor', True)
        self.assertEqual(bpy.ops.ho.selected_to_cursor('INVOKE_DEFAULT'), {'FINISHED'})
        self.assertLess((obj.location - bpy.context.scene.cursor.location).length, 1e-6)
        self.assertEqual(bpy.ops.ho.cursor_to_origin('INVOKE_DEFAULT'), {'FINISHED'})
        self.assertLess(bpy.context.scene.cursor.location.length, 1e-6)

    def test_axes_center_uses_requested_axis(self):
        HoPie.set_pie_enabled('align', True)
        mesh = bpy.data.meshes.new('CenterMesh')
        mesh.from_pydata([(0, 1, 0), (4, 3, 0), (8, 5, 0)], [(0, 1), (1, 2)], [])
        obj = bpy.data.objects.new('CenterObject', mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.context.scene.ho_align_pie_mode = 'AXES'
        result = bpy.ops.ho.center_editmesh(axis='Y', direction='HORIZONTAL')
        self.assertEqual(result, {'FINISHED'})
        bpy.ops.object.mode_set(mode='OBJECT')
        self.assertTrue(all(abs(vertex.co.y - 3.0) < 1e-6 for vertex in mesh.vertices))

    def test_curve_control_point_alignment_preserves_handles_and_weights(self):
        HoPie.set_pie_enabled('align', True)
        curve = bpy.data.curves.new('AlignCurve', 'CURVE')
        curve.dimensions = '3D'

        bezier = curve.splines.new('BEZIER')
        bezier.bezier_points.add(2)
        for point, coordinate in zip(
                bezier.bezier_points,
                ((0, 0, 0), (2, 2, 1), (4, 0, 2))):
            point.co = coordinate
            point.handle_left = Vector(coordinate) + Vector((-0.5, 0.25, 0))
            point.handle_right = Vector(coordinate) + Vector((0.5, -0.25, 0))
            point.select_control_point = True

        poly = curve.splines.new('POLY')
        poly.points.add(2)
        weights = (0.5, 1.5, 2.5)
        for point, coordinate, weight in zip(
                poly.points,
                ((10, 0, 3), (14, 2, 4), (12, 0, 5)),
                weights):
            point.co = (*coordinate, weight)
            point.select = True

        obj = bpy.data.objects.new('AlignCurveObject', curve)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        handle_offsets = [
            (point.handle_left - point.co, point.handle_right - point.co)
            for point in bezier.bezier_points
        ]
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.context.scene.ho_align_pie_mode = 'AXES'
            self.assertEqual(
                bpy.ops.ho.center_editmesh(axis='Z'),
                {'FINISHED'},
            )
            self.assertEqual(bpy.ops.ho.straighten(), {'FINISHED'})
            result = bpy.ops.ho.align_editmesh(
                mode='AXES',
                type='AVERAGE',
                axis='X',
                align_each=True,
            )
            self.assertEqual(result, {'FINISHED'})
            bpy.ops.object.mode_set(mode='OBJECT')

            bezier = curve.splines[0]
            poly = curve.splines[1]
            self.assertTrue(all(abs(point.co.x - 2.0) < 1e-6 for point in bezier.bezier_points))
            poly_x = poly.points[0].co.x
            self.assertTrue(all(abs(point.co.x - poly_x) < 1e-6 for point in poly.points))
            self.assertGreater(abs(poly_x - 2.0), 1.0)
            self.assertTrue(all(abs(point.co.z - 2.5) < 1e-6 for point in bezier.bezier_points))
            self.assertTrue(all(abs(point.co.z - 2.5) < 1e-6 for point in poly.points))
            self.assertLess(abs(bezier.bezier_points[1].co.y), 1e-6)
            self.assertEqual(tuple(point.co.w for point in poly.points), weights)
            for point, (left_offset, right_offset) in zip(
                    bezier.bezier_points,
                    handle_offsets):
                self.assertLess((point.handle_left - point.co - left_offset).length, 1e-6)
                self.assertLess((point.handle_right - point.co - right_offset).length, 1e-6)
        finally:
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(obj, do_unlink=True)

    def test_cursor_to_selected_supports_curve_points_and_handles(self):
        HoPie.set_pie_enabled('cursor', True)
        curve = bpy.data.curves.new('CursorCurve', 'CURVE')
        curve.dimensions = '3D'

        bezier = curve.splines.new('BEZIER')
        bezier.bezier_points.add(1)
        bezier.bezier_points[0].co = (0.0, 0.0, 0.0)
        bezier.bezier_points[1].co = (2.0, 0.0, 0.0)
        bezier.bezier_points[1].handle_right = (4.0, 0.0, 0.0)

        poly = curve.splines.new('POLY')
        poly.points.add(0)
        poly.points[0].co = (8.0, 0.0, 0.0, 2.0)

        for point in bezier.bezier_points:
            point.select_control_point = False
            point.select_left_handle = False
            point.select_right_handle = False
        poly.points[0].select = False
        bezier.bezier_points[0].select_control_point = True
        bezier.bezier_points[1].select_right_handle = True
        poly.points[0].select = True

        obj = bpy.data.objects.new('CursorCurveObject', curve)
        bpy.context.collection.objects.link(obj)
        obj.location = (1.0, 2.0, 3.0)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        try:
            bpy.ops.object.mode_set(mode='EDIT')

            expected = obj.matrix_world @ Vector((4.0, 0.0, 0.0))
            self.assertTrue(bpy.ops.ho.cursor_to_selected.poll())
            self.assertEqual(bpy.ops.ho.cursor_to_selected(), {'FINISHED'})
            self.assertLess((bpy.context.scene.cursor.location - expected).length, 1e-6)
        finally:
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(obj, do_unlink=True)

    def test_cursor_to_selected_supports_bone_heads_tails_and_pose_bones(self):
        from Utils.bone_selection import select_bones
        from Utils.bone_utils import bone_head_tail

        HoPie.set_pie_enabled('cursor', True)
        armature_data = bpy.data.armatures.new('CursorArmature')
        obj = bpy.data.objects.new('CursorArmatureObject', armature_data)
        bpy.context.collection.objects.link(obj)
        obj.location = (3.0, 4.0, 5.0)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            bone = armature_data.edit_bones.new('CursorBone')
            bone.head = (1.0, 0.0, 0.0)
            bone.tail = (1.0, 4.0, 0.0)

            bone.select = bone.select_head = bone.select_tail = False
            bone.select_head = True
            self.assertTrue(bpy.ops.ho.cursor_to_selected.poll())
            self.assertEqual(bpy.ops.ho.cursor_to_selected(), {'FINISHED'})
            expected = obj.matrix_world @ bone.head
            self.assertLess((bpy.context.scene.cursor.location - expected).length, 1e-6)

            bone.select = bone.select_head = bone.select_tail = False
            bone.select_tail = True
            self.assertEqual(bpy.ops.ho.cursor_to_selected(), {'FINISHED'})
            expected = obj.matrix_world @ bone.tail
            self.assertLess((bpy.context.scene.cursor.location - expected).length, 1e-6)

            bone.select = bone.select_head = bone.select_tail = False
            bone.select = True
            self.assertEqual(bpy.ops.ho.cursor_to_selected(), {'FINISHED'})
            expected = obj.matrix_world @ ((bone.head + bone.tail) * 0.5)
            self.assertLess((bpy.context.scene.cursor.location - expected).length, 1e-6)

            bpy.ops.object.mode_set(mode='POSE')
            select_bones(obj, ['CursorBone'])
            pose_bone = obj.pose.bones['CursorBone']
            pose_bone.location = (0.0, 1.0, 0.0)
            bpy.context.view_layer.update()
            head, tail = bone_head_tail(pose_bone)
            expected = obj.matrix_world @ ((head + tail) * 0.5)
            self.assertEqual(bpy.ops.ho.cursor_to_selected(), {'FINISHED'})
            self.assertLess((bpy.context.scene.cursor.location - expected).length, 1e-6)
        finally:
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(obj, do_unlink=True)

    def test_bottom_origin_uses_local_bounds_for_rotated_object(self):
        HoPie.set_pie_enabled('cursor', True)
        mesh = bpy.data.meshes.new('BoundsMesh')
        mesh.from_pydata([(-1, -1, -1), (1, -1, -1), (1, 1, 1), (-1, 1, 1)], [], [(0, 1, 2, 3)])
        obj = bpy.data.objects.new('BoundsObject', mesh)
        bpy.context.collection.objects.link(obj)
        obj.rotation_euler[2] = 0.7
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        expected = obj.matrix_world @ Vector((0, 0, -1))
        self.assertEqual(bpy.ops.ho.origin_to_bottom_bounds(), {'FINISHED'})
        self.assertLess((obj.location - expected).length, 1e-6)

    def test_pie_draws_in_axes_view_and_cursor_contexts(self):
        class Layout:
            def menu_pie(self):
                return self

            def split(self, **kwargs):
                return self

            def column(self, **kwargs):
                return self

            def row(self, **kwargs):
                return self

            def separator(self):
                return None

            def label(self, **kwargs):
                return None

            def prop(self, *args, **kwargs):
                return self

            def operator(self, *args, **kwargs):
                return SimpleNamespace()

        context = SimpleNamespace(
            scene=bpy.context.scene,
            active_object=None,
            selected_objects=[],
            mode='EDIT_MESH',
        )
        for mode in ('AXES', 'VIEW'):
            bpy.context.scene.ho_align_pie_mode = mode
            context.layout = Layout()
            context.mode = 'EDIT_MESH'
            from HoPie.AlignPie import HO_MT_align_pie, HO_MT_uv_align_pie
            align_menu = SimpleNamespace(
                layout=context.layout,
                configure=HO_MT_align_pie.configure,
                draw_axes=HO_MT_align_pie.draw_axes,
                draw_view=HO_MT_align_pie.draw_view,
            )
            if mode == 'AXES':
                HO_MT_align_pie.draw_axes(align_menu, context.layout, context, [])
            else:
                HO_MT_align_pie.draw_view(align_menu, context.layout, context, [])
            HO_MT_uv_align_pie.draw(SimpleNamespace(layout=context.layout), context)
        from HoPie.CursorPie import HO_MT_cursor_pie
        context.mode = 'OBJECT'
        HO_MT_cursor_pie.draw(SimpleNamespace(layout=Layout()), context)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PieRegistrationTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
