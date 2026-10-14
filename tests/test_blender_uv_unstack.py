"""Native 4.5/5.2 unstack registration, layout and user-state tests."""

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_blender_uv_topology_stack import clear_scene, coords, create_object, edit, operators, select_uv_faces, state
unstack = importlib.import_module(operators.__package__ + '.unstack')

SQUARE = ((.125, .125), (.625, .125), (.625, .625), (.125, .625))
FACE = ((0, 1, 2, 3),)


class UnstackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        operators.register()
        cls.area = bpy.context.screen.areas[0]
        cls.previous_type = cls.area.type
        cls.area.type = 'IMAGE_EDITOR'
        cls.area.ui_type = 'UV'

    @classmethod
    def tearDownClass(cls):
        cls.area.type = cls.previous_type
        operators.unregister()

    def setUp(self):
        clear_scene()
        self.override = bpy.context.temp_override(area=self.area, region=next(r for r in self.area.regions if r.type == 'WINDOW'))
        self.override.__enter__()

    def tearDown(self):
        clear_scene()
        self.override.__exit__(None, None, None)

    def triple(self, sync=False, mode='VERTEX'):
        obj = create_object('Stacked', [(SQUARE, FACE)]*3)
        edit([obj], sync, mode)
        return obj

    def test_modes_sync_and_selection_matrix(self):
        for sync in (False, True):
            for selection in ('VERTEX', 'EDGE', 'FACE', 'ISLAND'):
                if sync and selection == 'ISLAND':
                    continue
                for layout in ('HORIZONTAL', 'VERTICAL', 'TILE'):
                    with self.subTest(sync=sync, selection=selection, layout=layout):
                        clear_scene()
                        obj = self.triple(sync, selection)
                        before = coords(obj), state(obj), coords(obj, 'OtherUV')
                        self.assertEqual(bpy.ops.ho.uvtools_unstack(mode=layout, gap=.125), {'FINISHED'})
                        shifts = ((0, 0), (.625, 0), (1.25, 0)) if layout == 'HORIZONTAL' else (
                            ((0, 0), (0, .625), (0, 1.25)) if layout == 'VERTICAL' else ((0, 0), (1, 0), (1, 0)))
                        expected = tuple((x+dx, y+dy) for dx, dy in shifts for x, y in SQUARE)
                        self.assertEqual(coords(obj), expected)
                        self.assertEqual((state(obj), coords(obj, 'OtherUV')), before[1:])

    def test_tile_keeps_first_in_1001_and_remaining_overlapping_in_1002(self):
        obj = self.triple()
        before = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_unstack(mode='TILE'), {'FINISHED'})
        after = coords(obj)
        self.assertEqual(after[:4], before[:4])
        self.assertEqual(after[4:8], after[8:])
        self.assertTrue(all(0 <= x <= 1 and 0 <= y <= 1 for x, y in after[:4]))
        self.assertTrue(all(1 <= x <= 2 and 0 <= y <= 1 for x, y in after[4:]))

    def test_active_face_is_retained_first(self):
        obj = self.triple()
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.active = bm.faces[2]
        before = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_unstack(mode='TILE'), {'FINISHED'})
        after = coords(obj)
        self.assertEqual(after[8:], before[8:])
        self.assertEqual(after[:8], tuple((x+1, y) for x, y in before[:8]))

    def test_variable_sizes_no_overlap_and_shape_is_only_translated(self):
        other = ((3, 2), (4.25, 2), (4.25, 2.25), (3, 2.25))
        obj = create_object('DifferentSizes', [(SQUARE, FACE), (other, FACE), (SQUARE, FACE)])
        edit([obj])
        before = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_unstack(gap=.125), {'FINISHED'})
        after = coords(obj)
        self.assertEqual(after[:4], before[:4])
        self.assertEqual(min(x for x, y in after[4:8]), .75)
        self.assertEqual(min(x for x, y in after[8:]), 2.125)
        for start in (4, 8):
            delta = after[start][0]-before[start][0]
            for a, b in zip(after[start:start+4], before[start:start+4]):
                self.assertEqual(a[0]-b[0], delta)
                self.assertEqual(a[1], b[1])

    def test_multiobjects_active_object_first_and_shared_data(self):
        first = create_object('Z_Active', [(SQUARE, FACE)])
        second = create_object('A_Other', [(SQUARE, FACE)]*2)
        instance = bpy.data.objects.new('B_Shared', second.data)
        bpy.context.collection.objects.link(instance)
        instance.select_set(True)
        edit([first, second, instance], True, 'FACE')
        self.assertEqual(bpy.ops.ho.uvtools_unstack(mode='TILE'), {'FINISHED'})
        self.assertEqual(coords(first), SQUARE)
        self.assertEqual(coords(second), tuple((x+1, y) for _ in range(2) for x, y in SQUARE))

    def test_hidden_unselected_and_unshown_uv_stay_put(self):
        obj = create_object('Protected', [(SQUARE, FACE)]*5)
        edit([obj])
        bm = bmesh.from_edit_mesh(obj.data)
        select_uv_faces(bm, {0, 1, 3, 4})
        bm.faces[3].select_set(False)
        bm.faces[4].hide_set(True)
        before = coords(obj), state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_unstack(mode='TILE'), {'FINISHED'})
        self.assertEqual(coords(obj)[8:], before[0][8:])
        self.assertEqual(state(obj), before[1])

    def test_empty_single_and_missing_layer_cancel(self):
        for specs, uv in (([(SQUARE, FACE)], True), ([(SQUARE, FACE)]*2, False)):
            clear_scene()
            obj = create_object('Nothing', specs, with_uv=uv)
            edit([obj])
            self.assertEqual(bpy.ops.ho.uvtools_unstack(), {'CANCELLED'})
            if not uv:
                self.assertIsNone(bmesh.from_edit_mesh(obj.data).loops.layers.uv.active)

    def test_update_failure_rolls_back(self):
        obj = self.triple(True)
        before = coords(obj), state(obj)
        actual_update, calls = bmesh.update_edit_mesh, []
        def fail_once(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('injected unstack update failure')
            return actual_update(*args, **kwargs)
        with patch.object(bmesh, 'update_edit_mesh', side_effect=fail_once):
            self.assertEqual(bpy.ops.ho.uvtools_unstack(), {'CANCELLED'})
        self.assertEqual((coords(obj), state(obj)), before)

    def test_undo_redo(self):
        obj = self.triple(True)
        name, before = obj.name, coords(obj)
        bpy.ops.ed.undo_push(message='Before unstack')
        self.assertEqual(bpy.ops.ho.uvtools_unstack(mode='TILE'), {'FINISHED'})
        after = coords(obj)
        bpy.ops.ed.undo_push(message='After unstack')
        self.assertEqual(bpy.ops.ed.undo(), {'FINISHED'})
        self.assertEqual(coords(bpy.data.objects[name]), before)
        self.assertEqual(bpy.ops.ed.redo(), {'FINISHED'})
        self.assertEqual(coords(bpy.data.objects[name]), after)

    def test_dialog_default_and_menu_position(self):
        self.assertEqual(bpy.ops.ho.uvtools_unstack.get_rna_type().properties['mode'].default, 'HORIZONTAL')
        operator = types.SimpleNamespace()
        calls = []
        window_manager = types.SimpleNamespace(invoke_props_dialog=lambda op, **kwargs: calls.append((op, kwargs)) or {'RUNNING_MODAL'})
        self.assertEqual(unstack.OP_UVTools_Unstack.invoke(operator, types.SimpleNamespace(window_manager=window_manager), None), {'RUNNING_MODAL'})
        self.assertEqual(calls[0][0], operator)
        records = []
        class Layout:
            def operator(self, idname, **kwargs):
                records.append(idname)
                return types.SimpleNamespace()
            def separator(self):
                pass
            def menu(self, *args, **kwargs):
                pass
        operators.IMAGE_MT_uvs_context_hotools.draw(types.SimpleNamespace(layout=Layout()), bpy.context)
        index = records.index('ho.uvtools_topology_stack')
        self.assertEqual(records[index+1], 'ho.uvtools_unstack')

    def test_tile_translates_each_actual_corner_without_normalizing_uv_values(self):
        from mathutils import Vector
        from test_uv_topology import FACES
        points = SQUARE + ((.375, .375),)
        obj = create_object('ExactCorners', [(points, FACES)]*2)
        edit([obj])
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        bm.faces[4].loops[0][uv].uv.x += 8e-8
        before = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_unstack(mode='TILE'), {'FINISHED'})
        self.assertEqual(coords(obj)[:12], before[:12])
        self.assertEqual(coords(obj)[12:], tuple(tuple(Vector((x+1, y))) for x, y in before[12:]))


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(UnstackTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
