"""UV-only Shift+S routing, menu slots and native snap actions in 4.5/5.2."""

import sys
import types
import unittest
from pathlib import Path

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_blender_pies import HoPie
from test_blender_uv_topology_stack import clear_scene, coords, create_object, edit, select_uv_faces

SQUARE = ((.25, .25), (.75, .25), (.75, .75), (.25, .75))
FACES = ((0, 1, 2, 3),)
MENU = HoPie.CursorPie.HO_MT_uv_cursor_pie


class UVCursorPieTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        HoPie.register()
        HoPie.set_pie_enabled('cursor', True)
        cls.area = bpy.context.screen.areas[0]
        cls.old_type = cls.area.type
        cls.area.type = 'IMAGE_EDITOR'
        cls.area.ui_type = 'UV'

    @classmethod
    def tearDownClass(cls):
        cls.area.type = cls.old_type
        HoPie.unregister()

    def setUp(self):
        clear_scene()
        self.override = bpy.context.temp_override(area=self.area, region=next(r for r in self.area.regions if r.type == 'WINDOW'))
        self.override.__enter__()
        bpy.context.scene.cursor.location = (7, 8, 9)
        bpy.context.scene.cursor.rotation_euler = (.2, .3, .4)
        self.cursor_3d = tuple(tuple(row) for row in bpy.context.scene.cursor.matrix)

    def tearDown(self):
        clear_scene()
        self.override.__exit__(None, None, None)

    def fixture(self, sync=False, mode='VERTEX'):
        obj = create_object('CursorUV', [(SQUARE, FACES)])
        edit([obj], sync, mode)
        return obj

    def assert_3d_cursor_unchanged(self):
        self.assertEqual(tuple(tuple(row) for row in bpy.context.scene.cursor.matrix), self.cursor_3d)

    def test_uv_menu_poll_only_in_uv_mesh_editor(self):
        self.fixture()
        self.assertTrue(MENU.poll(bpy.context))
        self.area.ui_type = 'IMAGE_EDITOR'
        self.assertFalse(MENU.poll(bpy.context))
        self.area.ui_type = 'UV'
        bpy.ops.object.mode_set(mode='OBJECT')
        self.assertFalse(MENU.poll(bpy.context))

    def test_independent_shift_s_routes_and_no_duplicate_registration(self):
        bindings = {keymap.name: (keymap, item) for keymap, item in HoPie.cursor_pie_keymaps}
        self.assertEqual(set(bindings), {'3D View Generic', 'UV Editor'})
        for name, expected in (('3D View Generic', 'HO_MT_cursor_pie'), ('UV Editor', 'HO_MT_uv_cursor_pie')):
            keymap, item = bindings[name]
            self.assertEqual((item.type, item.value, item.shift, item.ctrl, item.alt), ('S', 'PRESS', True, False, False))
            self.assertEqual(item.properties.name, expected)
        HoPie.set_pie_enabled('cursor', True)
        self.assertEqual(len(HoPie.cursor_pie_keymaps), 2)

    def test_uv_draw_has_eight_slots_and_only_uv_operations(self):
        records, properties = [], []
        class Layout:
            def __init__(self, root=False):
                self.root = root
            def menu_pie(self):
                return self
            def operator(self, idname, **kwargs):
                op = types.SimpleNamespace(idname=idname)
                if self.root:
                    records.append(op)
                return op
            def split(self, **kwargs):
                if self.root:
                    records.append(None)
                return Layout()
            def column(self, **kwargs):
                return Layout()
            def row(self, **kwargs):
                return Layout()
            def prop(self, owner, name, **kwargs):
                properties.append((owner, name))
            def label(self, **kwargs):
                pass
        self.fixture()
        MENU.draw(types.SimpleNamespace(layout=Layout(True)), bpy.context)
        self.assertEqual(len(records), 8)
        self.assertEqual([(r.idname, r.target) for r in records if r is not None], [
            ('uv.snap_cursor', 'SELECTED'), ('uv.snap_selected', 'CURSOR'),
            ('uv.snap_selected', 'PIXELS'), ('uv.snap_cursor', 'ORIGIN'),
            ('uv.snap_selected', 'CURSOR_OFFSET'), ('uv.snap_selected', 'ADJACENT_UNSELECTED'),
            ('uv.snap_cursor', 'PIXELS'),
        ])
        self.assertEqual(properties, [(bpy.context.space_data, 'cursor_location')])

    def test_cursor_to_selection_and_selection_to_cursor_mode_matrix(self):
        for sync in (False, True):
            for mode in ('VERTEX', 'EDGE', 'FACE', 'ISLAND'):
                if sync and mode == 'ISLAND':
                    continue
                with self.subTest(sync=sync, mode=mode):
                    clear_scene()
                    obj = self.fixture(sync, mode)
                    original, other = coords(obj), coords(obj, 'OtherUV')
                    self.assertEqual(bpy.ops.uv.snap_cursor(target='SELECTED'), {'FINISHED'})
                    self.assertEqual(tuple(bpy.context.space_data.cursor_location), (.5, .5))
                    self.assertEqual(coords(obj), original)
                    bpy.context.space_data.cursor_location = (2, 3)
                    self.assertEqual(bpy.ops.uv.snap_selected(target='CURSOR'), {'FINISHED'})
                    self.assertEqual(coords(obj), ((2, 3),)*4)
                    self.assertEqual(coords(obj, 'OtherUV'), other)
                    self.assert_3d_cursor_unchanged()

    def test_offset_snap_translates_selection_as_a_group(self):
        obj = self.fixture(True)
        before = coords(obj)
        bpy.context.space_data.cursor_location = (2, 3)
        self.assertEqual(bpy.ops.uv.snap_selected(target='CURSOR_OFFSET'), {'FINISHED'})
        self.assertEqual(coords(obj), tuple((x+1.5, y+2.5) for x, y in before))
        self.assert_3d_cursor_unchanged()

    def test_uv_cursor_origin_does_not_reset_3d_cursor(self):
        self.fixture()
        bpy.context.space_data.cursor_location = (2, 3)
        self.assertEqual(bpy.ops.uv.snap_cursor(target='ORIGIN'), {'FINISHED'})
        self.assertEqual(tuple(bpy.context.space_data.cursor_location), (0, 0))
        self.assert_3d_cursor_unchanged()

    def test_pixel_snaps_with_rectangular_image(self):
        points = ((.21, .15), (.55, .15), (.55, .43), (.21, .43))
        obj = create_object('PixelCursor', [(points, FACES)])
        edit([obj])
        image = bpy.data.images.new('UVSnapPixels', width=64, height=32)
        self.area.spaces.active.image = image
        try:
            self.assertEqual(bpy.ops.uv.snap_selected(target='PIXELS'), {'FINISHED'})
            for x, y in coords(obj):
                self.assertAlmostEqual(x*128, round(x*128), places=5)
                self.assertAlmostEqual(y*64, round(y*64), places=5)
            self.area.spaces.active.cursor_location = (.21, .15)
            self.assertEqual(bpy.ops.uv.snap_cursor(target='PIXELS'), {'FINISHED'})
            x, y = tuple(self.area.spaces.active.cursor_location)
            self.assertAlmostEqual(x*128, round(x*128), places=5)
            self.assertAlmostEqual(y*64, round(y*64), places=5)
            self.assert_3d_cursor_unchanged()
        finally:
            self.area.spaces.active.image = None
            bpy.data.images.remove(image)

    def test_adjacent_unselected_uv_action(self):
        mesh = bpy.data.meshes.new('AdjacentCursor')
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)], [], [(0, 1, 2), (1, 0, 3)])
        uv = mesh.uv_layers.new(name='UVMap')
        points = ((.25, .25), (.75, .25), (.25, .75), (2.75, .25), (2.25, .25), (2.75, .75))
        for loop, coordinate in zip(uv.data, points):
            loop.uv = coordinate
        obj = bpy.data.objects.new('AdjacentCursor', mesh)
        bpy.context.collection.objects.link(obj)
        obj.select_set(True)
        edit([obj])
        bm = bmesh.from_edit_mesh(mesh)
        select_uv_faces(bm, {0})
        before = coords(obj)
        self.assertEqual(bpy.ops.uv.snap_selected(target='ADJACENT_UNSELECTED'), {'FINISHED'})
        self.assertEqual(coords(obj)[:2], (points[4], points[3]))
        self.assertEqual(coords(obj)[2:], before[2:])
        self.assert_3d_cursor_unchanged()

    def test_precise_sync_selection_stays_uv_scoped(self):
        if bpy.app.version < (5, 0, 0):
            self.skipTest('5.x precise UV selection')
        obj = self.fixture(True)
        bm = bmesh.from_edit_mesh(obj.data)
        select_uv_faces(bm, set())
        bm.faces[0].loops[0].uv_select_vert_set(True)
        bm.uv_select_sync_to_mesh()
        self.assertEqual(bpy.ops.uv.snap_cursor(target='SELECTED'), {'FINISHED'})
        self.assertEqual(tuple(bpy.context.space_data.cursor_location), SQUARE[0])
        bpy.context.space_data.cursor_location = (2, 3)
        before = coords(obj)
        self.assertEqual(bpy.ops.uv.snap_selected(target='CURSOR'), {'FINISHED'})
        self.assertEqual(coords(obj)[0], (2, 3))
        self.assertEqual(coords(obj)[1:], before[1:])
        self.assert_3d_cursor_unchanged()


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(UVCursorPieTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
