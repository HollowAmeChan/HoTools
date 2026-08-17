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
        HoPie.set_align_pie_enabled(False)
        HoPie.set_cursor_pie_enabled(False)
        if hasattr(bpy.types.Scene, 'ho_align_pie_mode'):
            bpy.context.scene.ho_align_pie_mode = 'VIEW'

    def test_align_pie_is_independently_toggleable(self):
        HoPie.set_align_pie_enabled(True)
        self.assertIsNotNone(getattr(bpy.types, 'HO_MT_align_pie', None))
        self.assertIsNotNone(getattr(bpy.types, 'HO_MT_uv_align_pie', None))
        ids = [item.idname for _, item in HoPie.align_pie_keymaps]
        self.assertEqual(ids, ['wm.call_menu_pie', 'wm.call_menu_pie'])
        self.assertEqual({item.properties.name for _, item in HoPie.align_pie_keymaps}, {'HO_MT_align_pie', 'HO_MT_uv_align_pie'})
        HoPie.set_align_pie_enabled(False)
        self.assertIsNone(getattr(bpy.types, 'HO_MT_align_pie', None))
        self.assertEqual(HoPie.align_pie_keymaps, [])

    def test_pies_are_disabled_by_default(self):
        self.assertFalse(HoPie._align_pie_enabled)
        self.assertFalse(HoPie._cursor_pie_enabled)
        self.assertIsNone(getattr(bpy.types, 'HO_MT_align_pie', None))
        self.assertIsNone(getattr(bpy.types, 'HO_MT_cursor_pie', None))
        self.assertEqual(bpy.context.scene.ho_align_pie_mode, 'VIEW')

    def test_cursor_pie_is_independently_toggleable(self):
        HoPie.set_cursor_pie_enabled(True)
        self.assertIsNotNone(getattr(bpy.types, 'HO_MT_cursor_pie', None))
        self.assertEqual(len(HoPie.cursor_pie_keymaps), 1)
        keymap, item = HoPie.cursor_pie_keymaps[0]
        self.assertEqual(keymap.name, '3D View Generic')
        self.assertEqual((item.type, item.shift, item.properties.name), ('S', True, 'HO_MT_cursor_pie'))
        HoPie.set_cursor_pie_enabled(False)
        self.assertIsNone(getattr(bpy.types, 'HO_MT_cursor_pie', None))
        self.assertEqual(HoPie.cursor_pie_keymaps, [])

    def test_mesh_alignment_and_cursor_operations_execute(self):
        HoPie.set_align_pie_enabled(True)
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
        HoPie.set_cursor_pie_enabled(True)
        self.assertEqual(bpy.ops.ho.selected_to_cursor('INVOKE_DEFAULT'), {'FINISHED'})
        self.assertLess((obj.location - bpy.context.scene.cursor.location).length, 1e-6)
        self.assertEqual(bpy.ops.ho.cursor_to_origin('INVOKE_DEFAULT'), {'FINISHED'})
        self.assertLess(bpy.context.scene.cursor.location.length, 1e-6)

    def test_axes_center_uses_requested_axis(self):
        HoPie.set_align_pie_enabled(True)
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

    def test_bottom_origin_uses_local_bounds_for_rotated_object(self):
        HoPie.set_cursor_pie_enabled(True)
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
            from HoPie.align_pie import HO_MT_align_pie, HO_MT_uv_align_pie
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
        from HoPie.cursor_pie import HO_MT_cursor_pie
        context.mode = 'OBJECT'
        HO_MT_cursor_pie.draw(SimpleNamespace(layout=Layout()), context)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PieRegistrationTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
