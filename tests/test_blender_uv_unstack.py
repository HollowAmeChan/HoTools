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
from Utils.mesh_uv import collect_uv_islands
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

    def test_ctrl_l_overlapping_shared_border_can_be_unstacked_in_both_sync_modes(self):
        for sync in (False, True):
            with self.subTest(sync=sync):
                clear_scene()
                mesh = bpy.data.meshes.new('FoldedStack')
                mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0), (2, 1, 0)],
                                 [], [(0, 1, 2, 3), (1, 4, 5, 2)])
                uv = mesh.uv_layers.new(name='UVMap')
                points = SQUARE + (SQUARE[1], SQUARE[0], SQUARE[3], SQUARE[2])
                for loop, coordinate in zip(uv.data, points):
                    loop.uv = coordinate
                obj = bpy.data.objects.new('FoldedStack', mesh)
                bpy.context.collection.objects.link(obj)
                obj.select_set(True)
                edit([obj], sync, 'FACE')
                bm = bmesh.from_edit_mesh(mesh)
                select_uv_faces(bm, {0})
                if sync:
                    if hasattr(bm, 'uv_select_sync_to_mesh'):
                        bm.uv_select_sync_to_mesh()
                    else:
                        bm.faces[1].select_set(False)
                        bm.faces[0].select_set(True)
                self.assertEqual(bpy.ops.uv.select_linked(), {'FINISHED'})
                bm = bmesh.from_edit_mesh(mesh)
                self.assertTrue(bm.faces[1].uv_select if hasattr(bm.faces[1], 'uv_select') else
                                bm.faces[1].select if sync else all(l[bm.loops.layers.uv.active].select for l in bm.faces[1].loops))
                before = coords(obj), state(obj)
                self.assertEqual(bpy.ops.ho.uvtools_unstack(mode='TILE'), {'FINISHED'})
                self.assertEqual(coords(obj)[:4], before[0][:4])
                self.assertEqual(coords(obj)[4:], tuple((x+1, y) for x, y in before[0][4:]))
                self.assertEqual(state(obj), before[1])

    def test_multiple_face_stacks_recover_after_native_ctrl_l_for_all_layouts(self):
        vertices = [(x, y, 0) for y in range(3) for x in range(3)]
        faces = ((0, 1, 4, 3), (3, 4, 7, 6), (1, 2, 5, 4), (4, 5, 8, 7))
        for sync in (False, True):
            for selection in ('VERTEX', 'FACE'):
                for layout in ('HORIZONTAL', 'VERTICAL', 'TILE'):
                    with self.subTest(sync=sync, selection=selection, layout=layout):
                        clear_scene()
                        mesh = bpy.data.meshes.new('MultiFaceStack')
                        mesh.from_pydata(vertices, [], faces)
                        uv = mesh.uv_layers.new(name='UVMap')
                        for polygon in mesh.polygons:
                            for index in polygon.loop_indices:
                                v = mesh.loops[index].vertex_index
                                x, y, z = vertices[v]
                                uv.data[index].uv = .125+(x if polygon.index < 2 else 2-x)*.5, .125+y*.25
                        obj = bpy.data.objects.new('MultiFaceStack', mesh)
                        bpy.context.collection.objects.link(obj)
                        obj.select_set(True)
                        edit([obj], sync, selection)
                        bm = bmesh.from_edit_mesh(mesh)
                        select_uv_faces(bm, {0, 1})
                        if sync:
                            if hasattr(bm, 'uv_select_sync_to_mesh'):
                                bm.uv_select_sync_to_mesh()
                            else:
                                bm.faces[2].select_set(False)
                                bm.faces[3].select_set(False)
                                bm.faces[0].select_set(True)
                                bm.faces[1].select_set(True)
                        self.assertEqual(bpy.ops.uv.select_linked(), {'FINISHED'})
                        bm = bmesh.from_edit_mesh(mesh)
                        layer = bm.loops.layers.uv.active
                        self.assertEqual(len(collect_uv_islands(obj, bm, layer, bpy.context.scene.tool_settings)), 1)
                        islands = collect_uv_islands(obj, bm, layer, bpy.context.scene.tool_settings, split_overlaps=True)
                        self.assertEqual([len(island.faces) for island in islands], [2, 2])
                        before = coords(obj), state(obj)
                        # Repeat topology stacking on already coincident charts.
                        self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'FINISHED'})
                        self.assertEqual(coords(obj), before[0])
                        self.assertEqual(bpy.ops.ho.uvtools_unstack(mode=layout, gap=.125), {'FINISHED'})
                        dx, dy = (.625, 0) if layout == 'HORIZONTAL' else ((0, .625) if layout == 'VERTICAL' else (1, 0))
                        self.assertEqual(coords(obj)[:8], before[0][:8])
                        self.assertEqual(coords(obj)[8:], tuple((x+dx, y+dy) for x, y in before[0][8:]))
                        self.assertEqual(state(obj), before[1])

    def test_overlap_detector_does_not_split_normal_or_reflected_charts(self):
        points = ((0, 0), (1, 0), (1, 1), (0, 1), (2, 0), (2, 1))
        for reflected in (False, True):
            for reverse_second in (False, True):
                with self.subTest(reflected=reflected, reverse_second=reverse_second):
                    clear_scene()
                    faces = ((0, 1, 2, 3), (1, 4, 5, 2))
                    if reverse_second:
                        faces = (faces[0], tuple(reversed(faces[1])))
                    coordinates = tuple((-x, y) if reflected else (x, y) for x, y in points)
                    obj = create_object('Continuous', [(coordinates, faces)])
                    edit([obj])
                    bm = bmesh.from_edit_mesh(obj.data)
                    for edge in bm.edges:
                        edge.seam = True
                    islands = collect_uv_islands(obj, bm, bm.loops.layers.uv.active,
                                                 bpy.context.scene.tool_settings, split_overlaps=True)
                    self.assertEqual(len(islands), 1)
                    self.assertEqual(len(islands[0].coordinates), 6)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(UnstackTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
