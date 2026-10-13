"""Native unwrap integration, UV selection state restoration and flip guards."""

import sys
import importlib
import unittest
from pathlib import Path
from unittest.mock import patch

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_blender_uv_topology_stack import clear_scene, coords, create_object, edit, operators, select_uv_faces, state
from test_uv_chains import grid
from Utils.mesh_uv import collect_uv_islands
from Utils.uv_chains import trace_open_chains
from Utils.uv_state import UVSceneState
unwrap_module = importlib.import_module(operators.__package__ + '.unwrap')


def select_edges(obj, edges, sync):
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.index_update()
    uv = bm.loops.layers.uv.active
    selected = {tuple(sorted(edge)) for edge in edges}
    select_uv_faces(bm, set())
    if sync:
        for v in bm.verts:
            v.select = False
        for e in bm.edges:
            e.select = False
        for f in bm.faces:
            f.select = False
        for e in bm.edges:
            if tuple(sorted(v.index for v in e.verts)) in selected:
                e.select_set(True)
    modern = hasattr(bm, 'uv_select_sync_valid')
    for face in bm.faces:
        for loop in face.loops:
            value = tuple(sorted((loop.vert.index, loop.link_loop_next.vert.index))) in selected
            if value:
                if modern:
                    loop.uv_select_edge_set(True)
                    loop.uv_select_vert_set(True)
                    loop.link_loop_next.uv_select_vert_set(True)
                else:
                    loop[uv].select_edge = True
                    loop[uv].select = True
                    loop.link_loop_next[uv].select = True
    if modern and sync:
        bm.uv_select_sync_to_mesh()


def vertex_uv(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.index_update()
    uv = bm.loops.layers.uv.active
    return {loop.vert.index: tuple(loop[uv].uv) for face in bm.faces for loop in face.loops}


class StraightenTests(unittest.TestCase):
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

    def make_grid(self, name='Grid', noise=.04, mirror=False, rotate=False):
        points, faces = grid(noise=noise)
        if mirror:
            points = tuple((-x, y) for x, y in points)
        if rotate:
            points = tuple((.8*x-.6*y, .6*x+.8*y) for x, y in points)
        obj = create_object(name, [(points, faces)])
        # Geometry is a flat grid; UVs are noisy, rotated or reflected.
        for i, vertex in enumerate(obj.data.vertices):
            vertex.co = (i % 4, i // 4, 0)
        return obj

    def settings_state(self):
        s = bpy.context.scene.tool_settings
        return (s.use_uv_select_sync, tuple(s.mesh_select_mode), s.uv_select_mode,
                s.uv_sticky_select_mode, getattr(s, 'use_uv_select_island', None))

    def assert_horizontal(self, obj, indices):
        points = vertex_uv(obj)
        self.assertLess(max(points[i][1] for i in indices)-min(points[i][1] for i in indices), 1e-5)

    def test_native_methods_and_sync_switch_preserve_all_user_state(self):
        for sync in (False, True):
            for method in ('ANGLE_BASED', 'CONFORMAL'):
                with self.subTest(sync=sync, method=method):
                    clear_scene()
                    obj = self.make_grid()
                    edit([obj], sync, 'EDGE')
                    select_edges(obj, ((4, 5), (5, 6), (6, 7)), sync)
                    before_state = state(obj), self.settings_state(), coords(obj, 'OtherUV')
                    before = coords(obj)
                    self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(method=method, direction='U'), {'FINISHED'})
                    self.assert_horizontal(obj, (4, 5, 6, 7))
                    self.assertNotEqual(coords(obj), before)
                    self.assertEqual((state(obj), self.settings_state(), coords(obj, 'OtherUV')), before_state)

    def test_same_island_multiple_internal_lines(self):
        obj = self.make_grid()
        edit([obj], False, 'EDGE')
        select_edges(obj, ((4, 5), (5, 6), (6, 7), (8, 9), (9, 10), (10, 11)), False)
        self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(direction='U'), {'FINISHED'})
        self.assert_horizontal(obj, (4, 5, 6, 7))
        self.assert_horizontal(obj, (8, 9, 10, 11))

    def test_mirrored_and_rotated_islands_do_not_flip(self):
        for mirror in (False, True):
            clear_scene()
            obj = self.make_grid(mirror=mirror, rotate=True)
            edit([obj], False, 'EDGE')
            select_edges(obj, ((4, 5), (5, 6), (6, 7)), False)
            before = vertex_uv(obj)
            self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(), {'FINISHED'})
            after = vertex_uv(obj)
            _, faces = grid()
            for face in faces:
                old_area = unwrap_module._area(*(before[i] for i in face[:3]))
                new_area = unwrap_module._area(*(after[i] for i in face[:3]))
                self.assertGreater(old_area*new_area, 0)

    def test_pin_conflict_preserves_state_and_explicit_override(self):
        obj = self.make_grid()
        edit([obj], True, 'EDGE')
        select_edges(obj, ((4, 5), (5, 6), (6, 7)), True)
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        for face in bm.faces:
            for loop in face.loops:
                if loop.vert.index == 5:
                    loop[uv].pin_uv = True
        before_state, before = state(obj), coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(direction='U'), {'CANCELLED'})
        self.assertEqual(coords(obj), before)
        self.assertEqual(state(obj), before_state)
        self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(direction='U', respect_pins=False), {'FINISHED'})
        self.assertEqual(state(obj), before_state)

    def test_offline_original_pin_retains_coordinate(self):
        obj = self.make_grid()
        edit([obj], False, 'EDGE')
        select_edges(obj, ((4, 5), (5, 6), (6, 7)), False)
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        bm.faces[0].loops[0][uv].pin_uv = True
        before = vertex_uv(obj)[0]
        self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(direction='U'), {'FINISHED'})
        self.assertEqual(vertex_uv(obj)[0], before)

    def test_failure_after_temporary_selection_restores_exact_state(self):
        for sync in (False, True):
            clear_scene()
            obj = self.make_grid()
            edit([obj], sync, 'EDGE')
            select_edges(obj, ((4, 5), (5, 6), (6, 7)), sync)
            before = coords(obj), state(obj), self.settings_state()
            with patch.object(unwrap_module, '_unwrap', side_effect=RuntimeError('injected native unwrap failure')):
                self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(), {'CANCELLED'})
            self.assertEqual((coords(obj), state(obj), self.settings_state()), before)

    def test_hidden_partial_and_closed_or_branched_chains_cancel(self):
        patterns = (((0, 1), (1, 5), (5, 4), (4, 0)), ((4, 5), (5, 6), (5, 9)))
        for edges in patterns:
            clear_scene()
            obj = self.make_grid()
            edit([obj], False, 'EDGE')
            select_edges(obj, edges, False)
            before = coords(obj), state(obj)
            self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(), {'CANCELLED'})
            self.assertEqual((coords(obj), state(obj)), before)
        clear_scene()
        obj = self.make_grid()
        edit([obj], False, 'EDGE')
        select_edges(obj, ((4, 5), (5, 6), (6, 7)), False)
        bmesh.from_edit_mesh(obj.data).faces[8].hide_set(True)
        before = coords(obj), state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(), {'CANCELLED'})
        self.assertEqual((coords(obj), state(obj)), before)

    def test_multimesh_and_missing_uv_mesh_are_preserved(self):
        a, b = self.make_grid('A'), self.make_grid('B', mirror=True)
        points, faces = grid()
        empty = create_object('NoUV', [(points, faces)], with_uv=False)
        edit([a, b, empty], True, 'EDGE')
        for obj in (a, b):
            select_edges(obj, ((4, 5), (5, 6), (6, 7)), True)
        before = [state(obj) for obj in (a, b)]
        self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(direction='U'), {'FINISHED'})
        self.assertEqual([state(obj) for obj in (a, b)], before)
        self.assertIsNone(bmesh.from_edit_mesh(empty.data).loops.layers.uv.active)
        self.assert_horizontal(a, (4, 5, 6, 7))
        self.assert_horizontal(b, (4, 5, 6, 7))

    def test_auto_straightens_boundary_and_internal_grid_lines(self):
        for sync in (False, True):
            clear_scene()
            obj = self.make_grid(noise=.01)
            edit([obj], sync, 'FACE')
            before = state(obj), self.settings_state()
            self.assertEqual(bpy.ops.ho.uvtools_straighten_island(direction='AUTO', deviation_threshold=.02), {'FINISHED'})
            points = vertex_uv(obj)
            for y in range(4):
                self.assertLess(max(points[y*4+x][1] for x in range(4))-min(points[y*4+x][1] for x in range(4)), 1e-5)
            for x in range(4):
                self.assertLess(max(points[y*4+x][0] for y in range(4))-min(points[y*4+x][0] for y in range(4)), 1e-5)
            self.assertEqual((state(obj), self.settings_state()), before)

    def test_auto_zero_threshold_cancels_noisy_grid(self):
        obj = self.make_grid(noise=.03)
        edit([obj])
        before = coords(obj), state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(angle_threshold=0, deviation_threshold=0), {'CANCELLED'})
        self.assertEqual((coords(obj), state(obj)), before)

    def test_guard_rejects_flips_and_nonfinite_coordinates(self):
        before = ((0, 0), (1, 0), (0, 1))
        for after in (((0, 0), (1, 0), (0, -1)), ((0, 0), (1, 0), (float('nan'), 1))):
            with self.assertRaises(ValueError):
                unwrap_module._validate(before, after, ((0, 1, 2),), {})

    def test_undo_redo_and_shared_data(self):
        obj = self.make_grid()
        instance = bpy.data.objects.new('Instance', obj.data)
        bpy.context.collection.objects.link(instance)
        instance.select_set(True)
        edit([obj, instance], True, 'EDGE')
        select_edges(obj, ((4, 5), (5, 6), (6, 7)), True)
        name = obj.name
        before = coords(obj)
        bpy.ops.ed.undo_push(message='Before line unwrap')
        self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(direction='U'), {'FINISHED'})
        after = coords(obj)
        bpy.ops.ed.undo_push(message='After line unwrap')
        self.assertEqual(bpy.ops.ed.undo(), {'FINISHED'})
        self.assertEqual(coords(bpy.data.objects[name]), before)
        self.assertEqual(bpy.ops.ed.redo(), {'FINISHED'})
        self.assertEqual(coords(bpy.data.objects[name]), after)

    def test_triangle_mixed_ngon_and_hole_topology(self):
        base_points, base_faces = grid(noise=.01)
        triangles = tuple(tri for face in base_faces for tri in (
            (face[0], face[1], face[2]), (face[0], face[2], face[3])))
        mixed = tuple(tri for i, face in enumerate(base_faces) for tri in (
            ((face[0], face[1], face[2]), (face[0], face[2], face[3])) if i % 2 else (face,)))
        # Remove the center face to create a hole; boundary row remains available.
        hole_faces = tuple(face for i, face in enumerate(base_faces) if i != 4)
        # A quad+pentagon island with a three-edge boundary chain.
        ngon_points = ((0, 0), (1, .01), (2, 0), (3, .01), (3, 1), (1.5, 1), (0, 1))
        ngon_faces = ((0, 1, 5, 6), (1, 2, 3, 4, 5))
        for label, points, faces, line in (
            ('Triangle', base_points, triangles, ((0, 1), (1, 2), (2, 3))),
            ('Mixed', base_points, mixed, ((0, 1), (1, 2), (2, 3))),
            ('Hole', base_points, hole_faces, ((0, 1), (1, 2), (2, 3))),
            ('Ngon', ngon_points, ngon_faces, ((0, 1), (1, 2), (2, 3))),
        ):
            with self.subTest(topology=label):
                clear_scene()
                obj = create_object(label, [(points, faces)])
                for i, vertex in enumerate(obj.data.vertices):
                    vertex.co = (points[i][0], points[i][1], 0)
                edit([obj], False, 'EDGE')
                select_edges(obj, line, False)
                before = state(obj), coords(obj, 'OtherUV')
                self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(direction='U'), {'FINISHED'})
                self.assert_horizontal(obj, (0, 1, 2, 3))
                self.assertEqual((state(obj), coords(obj, 'OtherUV')), before)

    def test_vertical_and_keep_direction_methods(self):
        for method in ('ANGLE_BASED', 'CONFORMAL'):
            for direction in ('V', 'KEEP'):
                with self.subTest(method=method, direction=direction):
                    clear_scene()
                    obj = self.make_grid(rotate=True, mirror=True)
                    edit([obj], True, 'EDGE')
                    select_edges(obj, ((4, 5), (5, 6), (6, 7)), True)
                    self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(method=method, direction=direction), {'FINISHED'})
                    points = vertex_uv(obj)
                    if direction == 'V':
                        self.assertLess(max(points[v][0] for v in (4, 5, 6, 7))-min(points[v][0] for v in (4, 5, 6, 7)), 1e-5)
                    else:
                        a, b = points[4], points[7]
                        for v in (5, 6):
                            self.assertAlmostEqual(unwrap_module._area(a, b, points[v]), 0, places=5)

    def test_auto_boundary_only_and_keep_direction(self):
        for direction in ('AUTO', 'KEEP'):
            clear_scene()
            obj = self.make_grid(noise=.01, rotate=True, mirror=True)
            edit([obj])
            before = state(obj)
            self.assertEqual(bpy.ops.ho.uvtools_straighten_island(
                include_internal=False, direction=direction, deviation_threshold=.02), {'FINISHED'})
            points = vertex_uv(obj)
            for chain in ((0, 1, 2, 3), (12, 13, 14, 15), (0, 4, 8, 12), (3, 7, 11, 15)):
                for v in chain[1:-1]:
                    self.assertAlmostEqual(unwrap_module._area(points[chain[0]], points[chain[-1]], points[v]), 0, places=5)
            self.assertEqual(state(obj), before)

    def test_restore_noop_and_invalid_modern_sync_state(self):
        obj = self.make_grid()
        edit([obj], True, 'EDGE')
        select_edges(obj, ((4, 5), (5, 6), (6, 7)), True)
        bm = bmesh.from_edit_mesh(obj.data)
        if hasattr(bm, 'uv_select_sync_valid'):
            bm.uv_select_sync_valid = False
        before = coords(obj), state(obj), self.settings_state()
        UVSceneState(bpy.context).restore()
        self.assertEqual((coords(obj), state(obj), self.settings_state()), before)
        self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(direction='U'), {'FINISHED'})
        self.assertEqual((state(obj), self.settings_state()), before[1:])

    def test_unselected_island_and_other_layer_flags_untouched(self):
        points, faces = grid(noise=.01)
        obj = create_object('TwoIslands', [(points, faces), ([(x+7, y+7) for x, y in points], faces)])
        edit([obj], False, 'EDGE')
        select_edges(obj, ((4, 5), (5, 6), (6, 7)), False)
        bm = bmesh.from_edit_mesh(obj.data)
        other = bm.loops.layers.uv.get('OtherUV')
        if bpy.app.version < (5, 0, 0):
            bm.faces[0].loops[0][other].select = True
            bm.faces[0].loops[0][other].select_edge = True
        bm.faces[1].loops[0][other].pin_uv = True
        def other_state():
            bm = bmesh.from_edit_mesh(obj.data)
            layer = bm.loops.layers.uv.get('OtherUV')
            return tuple((tuple(l[layer].uv), l[layer].pin_uv,
                          l[layer].select if hasattr(l[layer], 'select') else None,
                          l[layer].select_edge if hasattr(l[layer], 'select_edge') else None)
                         for f in bm.faces for l in f.loops)
        before = coords(obj)[36:], other_state()
        self.assertEqual(bpy.ops.ho.uvtools_line_unwrap(direction='U'), {'FINISHED'})
        self.assertEqual((coords(obj)[36:], other_state()), before)

    def test_auto_straightens_triangulated_rows_columns_and_diagonals(self):
        points, quads = grid(noise=.01)
        faces = tuple(tri for face in quads for tri in (
            (face[0], face[1], face[2]), (face[0], face[2], face[3])))
        obj = create_object('TriAuto', [(points, faces)])
        for i, vertex in enumerate(obj.data.vertices):
            vertex.co = (i % 4, i // 4, 0)
        edit([obj])
        before_state = state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(deviation_threshold=.02), {'FINISHED'})
        result = vertex_uv(obj)
        for chain in tuple(tuple(y*4+x for x in range(4)) for y in range(4)) + tuple(
                tuple(y*4+x for y in range(4)) for x in range(4)) + ((0, 5, 10, 15),):
            for v in chain[1:-1]:
                self.assertAlmostEqual(unwrap_module._area(result[chain[0]], result[chain[-1]], result[v]), 0, places=5)
        self.assertEqual(state(obj), before_state)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StraightenTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
