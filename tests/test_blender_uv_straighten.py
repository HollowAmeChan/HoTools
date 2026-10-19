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
from test_uv_quad import hair_fixture
from Utils.mesh_uv import collect_uv_islands
from Utils.uv_chains import trace_open_chains
from Utils.uv_state import UVSceneState
unwrap_module = importlib.import_module(operators.__package__ + '.unwrap')
straighten_module = importlib.import_module(operators.__package__ + '.straighten')


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
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(algorithm='THRESHOLD', angle_threshold=0, deviation_threshold=0), {'CANCELLED'})
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

    def make_curved_quad_grid(self, name='CurvedQuads', mirror=False, rotate=False, faces=None):
        points = tuple((x+.035*y*y, y+.18*x*x) for y in range(4) for x in range(4))
        if mirror:
            points = tuple((-x, y) for x, y in points)
        if rotate:
            points = tuple((.8*x-.6*y+4, .6*x+.8*y-2) for x, y in points)
        polygons = grid()[1] if faces is None else faces
        obj = create_object(name, [(points, polygons)])
        for i, vertex in enumerate(obj.data.vertices):
            vertex.co = i % 4, i//4, 0
        return obj

    def assert_quad_rectangles(self, obj):
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        for face in bm.faces:
            if len(face.loops) != 4:
                continue
            a, b, c, d = [loop[uv].uv.copy() for loop in face.loops]
            edge, side = b-a, d-a
            self.assertLess(abs(edge.dot(side))/(edge.length*side.length), 2e-6)
            self.assertLess((c-(b+d-a)).length, max(edge.length, side.length)*2e-6)

    def test_quad_priority_fixes_curvature_missed_by_default_threshold(self):
        obj = self.make_curved_quad_grid()
        edit([obj], False, 'FACE')
        before = state(obj), self.settings_state(), coords(obj, 'OtherUV')
        original = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(algorithm='THRESHOLD'), {'CANCELLED'})
        self.assertEqual(coords(obj), original)
        with patch.object(unwrap_module, '_unwrap', side_effect=AssertionError('quad path must not unwrap')):
            self.assertEqual(bpy.ops.ho.uvtools_straighten_island(direction='AUTO'), {'FINISHED'})
        self.assert_quad_rectangles(obj)
        points = vertex_uv(obj)
        for y in range(4):
            self.assertEqual(len({points[y*4+x][1] for x in range(4)}), 1)
        for x in range(4):
            self.assertEqual(len({points[y*4+x][0] for y in range(4)}), 1)
        self.assertEqual((state(obj), self.settings_state(), coords(obj, 'OtherUV')), before)

    def test_quad_sync_selection_matrix_preserves_state(self):
        for sync in (False, True):
            for selection in ('VERTEX', 'EDGE', 'FACE', 'ISLAND'):
                if sync and selection == 'ISLAND':
                    continue
                with self.subTest(sync=sync, selection=selection):
                    clear_scene()
                    obj = self.make_curved_quad_grid()
                    edit([obj], sync, selection)
                    bm = bmesh.from_edit_mesh(obj.data)
                    for edge in bm.edges:
                        edge.seam = edge.index % 2 == 0
                    if sync and hasattr(bm, 'uv_select_sync_valid'):
                        bm.uv_select_sync_valid = False
                    before = state(obj), self.settings_state(), coords(obj, 'OtherUV')
                    self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'FINISHED'})
                    self.assert_quad_rectangles(obj)
                    self.assertEqual((state(obj), self.settings_state(), coords(obj, 'OtherUV')), before)

    def test_quad_mirrors_rotations_and_area_preserved(self):
        for mirror in (False, True):
            clear_scene()
            obj = self.make_curved_quad_grid(mirror=mirror, rotate=True)
            edit([obj], True, 'FACE')
            before = vertex_uv(obj), state(obj)
            self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'FINISHED'})
            self.assert_quad_rectangles(obj)
            after = vertex_uv(obj)
            old_area, new_area = 0, 0
            for face in grid()[1]:
                old = sum(unwrap_module._area(before[0][face[0]], before[0][face[i]], before[0][face[i+1]]) for i in (1, 2))
                new = sum(unwrap_module._area(after[face[0]], after[face[i]], after[face[i+1]]) for i in (1, 2))
                self.assertGreater(old*new, 0)
                old_area += abs(old)
                new_area += abs(new)
            self.assertAlmostEqual(old_area, new_area, places=4)
            self.assertEqual(state(obj), before[1])

    def test_quad_average_3d_spacing_includes_nonuniform_object_scale(self):
        obj = self.make_curved_quad_grid()
        for i, vertex in enumerate(obj.data.vertices):
            vertex.co = (0, 1, 3, 6)[i % 4], i//4*2, 0
        obj.scale = (2, 3, 1)
        edit([obj], False, 'FACE')
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(direction='AUTO'), {'FINISHED'})
        points = vertex_uv(obj)
        widths = [points[x+1][0]-points[x][0] for x in range(3)]
        self.assertAlmostEqual(widths[1]/widths[0], 2, places=5)
        self.assertAlmostEqual(widths[2]/widths[0], 3, places=5)
        self.assertAlmostEqual((points[4][1]-points[0][1])/widths[0], 3, places=5)
        self.assert_quad_rectangles(obj)

    def test_quad_hole_l_shape_and_reversed_faces(self):
        faces = grid()[1]
        for polygons in (tuple(face for i, face in enumerate(faces) if i != 4),
                         tuple(face for i, face in enumerate(faces) if i//3 == 0 or i % 3 == 0),
                         tuple(face[::-1] if i % 2 else face for i, face in enumerate(faces))):
            clear_scene()
            obj = self.make_curved_quad_grid(faces=polygons)
            edit([obj], True, 'FACE')
            before = state(obj)
            self.assertEqual(bpy.ops.ho.uvtools_straighten_island(algorithm='QUAD'), {'FINISHED'})
            self.assert_quad_rectangles(obj)
            self.assertEqual(state(obj), before)

    def test_quad_single_pin_kept_and_incompatible_pins_explicitly_rejected(self):
        obj = self.make_curved_quad_grid()
        edit([obj], False, 'FACE')
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        for face in bm.faces:
            for loop in face.loops:
                loop[uv].pin_uv = loop.vert.index == 5
        before = vertex_uv(obj)[5], state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'FINISHED'})
        self.assertEqual(vertex_uv(obj)[5], before[0])
        self.assertEqual(state(obj), before[1])
        self.assert_quad_rectangles(obj)
        clear_scene()
        obj = self.make_curved_quad_grid()
        edit([obj], False, 'FACE')
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        for face in bm.faces:
            for loop in face.loops:
                loop[uv].pin_uv = loop.vert.index in (0, 3, 12)
        before = coords(obj), state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'CANCELLED'})
        self.assertEqual((coords(obj), state(obj)), before)
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(respect_pins=False), {'FINISHED'})
        self.assertEqual(state(obj), before[1])
        self.assert_quad_rectangles(obj)

    def test_quad_and_triangle_islands_in_one_run_keep_both_results(self):
        a = self.make_curved_quad_grid('A_Quad')
        points, quads = grid(noise=.01)
        faces = tuple(tri for face in quads for tri in ((face[0], face[1], face[2]), (face[0], face[2], face[3])))
        b = create_object('B_Tri', [(points, faces)])
        for i, vertex in enumerate(b.data.vertices):
            vertex.co = i % 4, i//4, 0
        empty = create_object('NoUV', [(points, faces)], with_uv=False)
        edit([a, b, empty], True, 'FACE')
        before = [(state(obj), coords(obj, 'OtherUV')) for obj in (a, b)]
        original = coords(a), coords(b)
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(deviation_threshold=.02), {'FINISHED'})
        self.assert_quad_rectangles(a)
        self.assertNotEqual(coords(a), original[0])
        self.assertNotEqual(coords(b), original[1])
        self.assertEqual([(state(obj), coords(obj, 'OtherUV')) for obj in (a, b)], before)
        self.assertIsNone(bmesh.from_edit_mesh(empty.data).loops.layers.uv.active)

    def test_quad_write_failure_restores_all_actual_corners(self):
        obj = self.make_curved_quad_grid()
        edit([obj], True, 'FACE')
        before = coords(obj), state(obj)
        actual, calls = bmesh.update_edit_mesh, []
        def fail_once(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('injected quad write failure')
            return actual(*args, **kwargs)
        with patch.object(bmesh, 'update_edit_mesh', side_effect=fail_once):
            self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'CANCELLED'})
        self.assertEqual((coords(obj), state(obj)), before)

    def test_mixed_quad_failure_restores_already_solved_triangle_island(self):
        a = self.make_curved_quad_grid('A_Quad')
        points, quads = grid(noise=.01)
        faces = tuple(tri for face in quads for tri in ((face[0], face[1], face[2]), (face[0], face[2], face[3])))
        b = create_object('B_Tri', [(points, faces)])
        for i, vertex in enumerate(b.data.vertices):
            vertex.co = i % 4, i//4, 0
        edit([a, b], True, 'FACE')
        before = [(coords(obj), state(obj)) for obj in (a, b)]
        with patch.object(straighten_module, 'write_uv_points', side_effect=RuntimeError('injected final quad write failure')):
            self.assertEqual(bpy.ops.ho.uvtools_straighten_island(deviation_threshold=.02), {'CANCELLED'})
        self.assertEqual([(coords(obj), state(obj)) for obj in (a, b)], before)

    def test_quad_skips_hidden_or_unshown_island(self):
        for sync in (False, True):
            clear_scene()
            obj = self.make_curved_quad_grid()
            edit([obj], sync, 'FACE')
            bm = bmesh.from_edit_mesh(obj.data)
            if sync:
                bm.faces[8].hide_set(True)
            else:
                bm.faces[8].select_set(False)
            before = coords(obj), state(obj)
            self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'CANCELLED'})
            self.assertEqual((coords(obj), state(obj)), before)

    def test_quad_single_face_and_explicit_nonquad_mode(self):
        obj = create_object('SingleQuad', [(((0, 0), (3, .2), (2.8, 1.2), (.1, 1)), ((0, 1, 2, 3),))])
        for i, vertex in enumerate(obj.data.vertices):
            vertex.co = ((0, 0, 0), (3, 0, 0), (3, 1, 0), (0, 1, 0))[i]
        edit([obj])
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'FINISHED'})
        self.assert_quad_rectangles(obj)
        clear_scene()
        obj = create_object('Triangle', [(((0, 0), (1, 0), (0, 1)), ((0, 1, 2),))])
        edit([obj])
        before = coords(obj), state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(algorithm='QUAD'), {'CANCELLED'})
        self.assertEqual((coords(obj), state(obj)), before)

    def test_quad_undo_redo(self):
        obj = self.make_curved_quad_grid()
        edit([obj], True, 'FACE')
        name, before = obj.name, coords(obj)
        bpy.ops.ed.undo_push(message='Before quadrify')
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'FINISHED'})
        after = coords(obj)
        bpy.ops.ed.undo_push(message='After quadrify')
        self.assertEqual(bpy.ops.ed.undo(), {'FINISHED'})
        self.assertEqual(coords(bpy.data.objects[name]), before)
        self.assertEqual(bpy.ops.ed.redo(), {'FINISHED'})
        self.assertEqual(coords(bpy.data.objects[name]), after)

    def test_quad_stacked_mirror_charts_with_shared_border_are_rectified_independently(self):
        mesh_points = ((0, 0), (1, 0), (1, 1), (0, 1), (2, 0), (2, 1))
        faces = ((0, 1, 2, 3), (1, 4, 5, 2))
        square = ((.1, .2), (.8, .23), (.75, .9), (.15, .85))
        for sync in (False, True):
            clear_scene()
            obj = create_object('StackedMirror', [(mesh_points, faces)])
            for i, vert in enumerate(obj.data.vertices):
                vert.co = (*mesh_points[i], 0)
            uv = obj.data.uv_layers[0]
            for loop, point in zip(uv.data, square+(square[1], square[0], square[3], square[2])):
                loop.uv = point
            edit([obj], sync, 'FACE')
            before = state(obj), coords(obj, 'OtherUV')
            self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'FINISHED'})
            self.assert_quad_rectangles(obj)
            self.assertEqual((state(obj), coords(obj, 'OtherUV')), before)
            after = coords(obj)
            for point in after[:4]:
                self.assertLess(min(((point[0]-x)**2+(point[1]-y)**2)**.5 for x, y in after[4:]), 2e-6)

    def test_default_orients_long_uneven_quad_strips_to_uv_axes(self):
        from math import cos, sin
        levels = (0, .01, .03, .07, .15, .3, .7, 1.2, 2.1, 3.5, 5.5, 8)
        faces = tuple((2*y, 2*y+1, 2*y+3, 2*y+2) for y in range(len(levels)-1))
        for sync in (False, True):
            for angle in (-.13, .07, .6):
                clear_scene()
                points = tuple((cos(angle)*x-sin(angle)*y+3, sin(angle)*x+cos(angle)*y-2)
                               for y in levels for x in (0, .3))
                obj = create_object('LeaningStrip', [(points, faces)])
                for i, vertex in enumerate(obj.data.vertices):
                    vertex.co = (i % 2*.3, levels[i//2], 0)
                edit([obj], sync, 'FACE')
                before = state(obj), coords(obj, 'OtherUV')
                self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'FINISHED'})
                result = vertex_uv(obj)
                self.assertEqual(len({result[2*y][0] for y in range(len(levels))}), 1)
                self.assertEqual(len({result[2*y+1][0] for y in range(len(levels))}), 1)
                self.assertTrue(all(result[2*y][1] == result[2*y+1][1] for y in range(len(levels))))
                self.assertEqual((state(obj), coords(obj, 'OtherUV')), before)

    def test_invocation_does_not_inherit_old_keep_direction_from_redo_cache(self):
        obj = self.make_curved_quad_grid(rotate=True)
        edit([obj], False, 'FACE')
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island('INVOKE_DEFAULT', direction='KEEP'), {'FINISHED'})
        last = bpy.context.window_manager.operator_properties_last('ho.uvtools_straighten_island')
        last.direction = 'KEEP'  # emulate a value saved by the preceding version
        clear_scene()
        obj = self.make_curved_quad_grid(rotate=True)
        edit([obj], False, 'FACE')
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island('INVOKE_DEFAULT'), {'FINISHED'})
        points = vertex_uv(obj)
        # Axis snapping may rotate rows to U or V depending on the nearest frame.
        for chain in ((0, 1, 2, 3), (0, 4, 8, 12)):
            self.assertTrue(any(len({points[v][axis] for v in chain}) == 1 for axis in (0, 1)))

    def make_hair(self, columns=1, double_tip=False, tip_first=False, mirror=False):
        from math import cos, sin
        topology, mesh, lengths, caps = hair_fixture(columns, double_tip, tip_first)
        sign = -1 if mirror else 1
        points = tuple((2+cos(.27)*x-sin(.27)*sign*y, -1+sin(.27)*x+cos(.27)*sign*y)
                       for x, y in topology.coordinates)
        obj = create_object('HairTip', [(points, topology.polygons)])
        for vertex, coordinate in zip(obj.data.vertices, mesh):
            vertex.co = coordinate
        return obj, caps

    def assert_hair_tip_centers(self, obj, caps):
        from math import hypot
        points = vertex_uv(obj)
        for tip, base in caps:
            a, b = points[base[0]], points[base[-1]]
            x, y = points[tip]
            along = (x-(a[0]+b[0])/2)*(b[0]-a[0])+(y-(a[1]+b[1])/2)*(b[1]-a[1])
            self.assertLess(abs(along)/hypot(b[0]-a[0], b[1]-a[1]), 2e-6)
        self.assert_quad_rectangles(obj)

    def test_hair_single_triangle_and_fan_center_in_both_sync_modes_and_mirrors(self):
        for sync in (False, True):
            for columns in (1, 3):
                for mirror in (False, True):
                    with self.subTest(sync=sync, columns=columns, mirror=mirror):
                        clear_scene()
                        obj, caps = self.make_hair(columns, mirror=mirror)
                        edit([obj], sync, 'FACE')
                        bm = bmesh.from_edit_mesh(obj.data)
                        bm.faces.active = next(face for face in bm.faces if len(face.loops) == 3)
                        before = state(obj), self.settings_state(), coords(obj, 'OtherUV')
                        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'FINISHED'})
                        self.assert_hair_tip_centers(obj, caps)
                        self.assertEqual((state(obj), self.settings_state(), coords(obj, 'OtherUV')), before)
                        uv = bm.loops.layers.uv.active
                        for face in bm.faces:
                            if len(face.loops) == 4:
                                for loop in face.loops:
                                    delta = loop[uv].uv-loop.link_loop_next[uv].uv
                                    self.assertTrue(delta.x == 0 or delta.y == 0)

    def test_hair_fan_height_uses_world_3d_altitude(self):
        from math import hypot
        obj, caps = self.make_hair(columns=3)
        obj.scale = (2, 3, 4)
        edit([obj], True, 'FACE')
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'FINISHED'})
        self.assert_hair_tip_centers(obj, caps)
        points = vertex_uv(obj)
        tip, base = caps[0]
        a, b = points[base[0]], points[base[-1]]
        height = hypot(points[tip][0]-(a[0]+b[0])/2, points[tip][1]-(a[1]+b[1])/2)
        self.assertAlmostEqual(height/hypot(b[0]-a[0], b[1]-a[1]), hypot(1.7*3, .8*4)/(3*.4*2), places=5)

    def test_hair_double_ended_fan_with_active_triangle_and_explicit_quad_mode(self):
        obj, caps = self.make_hair(columns=2, double_tip=True, tip_first=True)
        edit([obj], False, 'FACE')
        before = state(obj), coords(obj, 'OtherUV')
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(algorithm='QUAD'), {'FINISHED'})
        self.assert_hair_tip_centers(obj, caps)
        self.assertEqual((state(obj), coords(obj, 'OtherUV')), before)

    def test_hair_pinned_apex_and_incompatible_body_pins(self):
        obj, caps = self.make_hair()
        edit([obj], False, 'FACE')
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        tip, base = caps[0]
        for face in bm.faces:
            for loop in face.loops:
                loop[uv].pin_uv = loop.vert.index == tip
        before = vertex_uv(obj)[tip], state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'FINISHED'})
        self.assertEqual(vertex_uv(obj)[tip], before[0])
        self.assert_hair_tip_centers(obj, caps)
        self.assertEqual(state(obj), before[1])
        clear_scene()
        obj, caps = self.make_hair()
        edit([obj], False, 'FACE')
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        tip, base = caps[0]
        for face in bm.faces:
            for loop in face.loops:
                loop[uv].pin_uv = loop.vert.index in (tip, base[0], base[-1])
        before = coords(obj), state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'CANCELLED'})
        self.assertEqual((coords(obj), state(obj)), before)
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(respect_pins=False), {'FINISHED'})
        self.assert_hair_tip_centers(obj, caps)
        self.assertEqual(state(obj), before[1])

    def test_hair_tip_write_failure_restores_whole_island(self):
        obj, caps = self.make_hair(columns=3)
        edit([obj], True, 'FACE')
        before = coords(obj), state(obj)
        actual, calls = bmesh.update_edit_mesh, []
        def fail_once(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('injected hair tip write failure')
            return actual(*args, **kwargs)
        with patch.object(bmesh, 'update_edit_mesh', side_effect=fail_once):
            self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'CANCELLED'})
        self.assertEqual((coords(obj), state(obj)), before)

    def test_hair_tip_degenerate_3d_triangle_keeps_original_uvs(self):
        obj, caps = self.make_hair()
        tip, base = caps[0]
        obj.data.vertices[tip].co = (obj.data.vertices[base[0]].co+obj.data.vertices[base[-1]].co)/2
        edit([obj], True, 'FACE')
        before = coords(obj), state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'CANCELLED'})
        self.assertEqual((coords(obj), state(obj)), before)

    def test_hair_selected_tip_only_processes_its_complete_visible_island(self):
        obj, caps = self.make_hair(columns=3)
        edit([obj], False, 'FACE')
        bm = bmesh.from_edit_mesh(obj.data)
        select_uv_faces(bm, {face.index for face in bm.faces if len(face.loops) == 3})
        before = state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'FINISHED'})
        self.assert_hair_tip_centers(obj, caps)
        self.assertEqual(state(obj), before)

    def test_hair_tip_undo_redo(self):
        obj, caps = self.make_hair(columns=3)
        edit([obj], True, 'FACE')
        name, before = obj.name, coords(obj)
        bpy.ops.ed.undo_push(message='Before hair tip straightening')
        self.assertEqual(bpy.ops.ho.uvtools_straighten_island(), {'FINISHED'})
        after = coords(obj)
        bpy.ops.ed.undo_push(message='After hair tip straightening')
        self.assertEqual(bpy.ops.ed.undo(), {'FINISHED'})
        self.assertEqual(coords(bpy.data.objects[name]), before)
        self.assertEqual(bpy.ops.ed.redo(), {'FINISHED'})
        self.assertEqual(coords(bpy.data.objects[name]), after)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StraightenTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
