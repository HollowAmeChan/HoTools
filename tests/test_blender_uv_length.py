"""Actual UV edges and 3D metric tests in Blender 4.5 / 5.2."""

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
from test_blender_uv_straighten import select_edges, vertex_uv
from Utils.mesh_uv import collect_uv_islands
length_module = importlib.import_module(operators.__package__ + '.length')

POINTS = ((0, 0), (.4, .2), (3.1, -.1), (8, 0), (0, 1), (.4, 1.2), (3.1, .9), (8, 1))
FACES = ((0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6))
CHAIN = ((0, 1), (1, 2), (2, 3))


class UVLengthTests(unittest.TestCase):
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

    def strip(self, name='Strip', copies=1):
        obj = create_object(name, [(POINTS, FACES)]*copies)
        for index, vertex in enumerate(obj.data.vertices):
            i = index % 8
            vertex.co = ((0, 1, 3, 4)[i % 4], i//4, index//8*3)
        return obj

    def assert_chain(self, obj, offset=0, expected=(2, 6)):
        points = vertex_uv(obj)
        self.assertAlmostEqual(points[offset+1][0], expected[0], places=5)
        self.assertAlmostEqual(points[offset+2][0], expected[1], places=5)
        self.assertEqual(points[offset+1][1], 0)
        self.assertEqual(points[offset+2][1], 0)

    def test_sync_modes_fixed_endpoints_3d_ratios_and_user_state(self):
        for sync in (False, True):
            with self.subTest(sync=sync):
                clear_scene()
                obj = self.strip()
                edit([obj], sync, 'EDGE')
                select_edges(obj, CHAIN, sync)
                bm = bmesh.from_edit_mesh(obj.data)
                for face in bm.faces:
                    for loop in face.loops:
                        if loop.vert.index == 1:
                            loop[bm.loops.layers.uv.active].pin_uv = True
                for edge in bm.edges:
                    edge.seam = edge.index % 2 == 0
                before = vertex_uv(obj), state(obj), coords(obj, 'OtherUV')
                self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'FINISHED'})
                self.assert_chain(obj)
                after = vertex_uv(obj)
                for index in (0, 3, 4, 5, 6, 7):
                    self.assertEqual(after[index], before[0][index])
                self.assertEqual((state(obj), coords(obj, 'OtherUV')), before[1:])
                # Shared face-corner copies of each redistributed point agree.
                for face in bm.faces:
                    for loop in face.loops:
                        self.assertEqual(tuple(loop[bm.loops.layers.uv.active].uv), after[loop.vert.index])

    def test_nonuniform_object_scale_and_bent_3d_chain(self):
        obj = self.strip()
        positions = ((0, 0, 0), (1, 0, 0), (1, 2, 0), (1, 2, 1))
        for index, vertex in enumerate(obj.data.vertices):
            x, y, z = positions[index % 4]
            vertex.co = x, y, z+(3 if index >= 4 else 0)
        obj.scale = (2, 3, 4)
        obj.location = (100000, -200000, 50000)
        edit([obj], True, 'EDGE')
        select_edges(obj, CHAIN, True)
        self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'FINISHED'})
        self.assert_chain(obj, expected=(8*2/12, 8*8/12))

    def test_multiple_objects_chains_and_islands(self):
        first, second = self.strip('A', 2), self.strip('B')
        edit([first, second], False, 'EDGE')
        select_edges(first, CHAIN+tuple((a+8, b+8) for a, b in CHAIN), False)
        select_edges(second, CHAIN, False)
        before = [state(o) for o in (first, second)]
        self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'FINISHED'})
        self.assert_chain(first)
        self.assert_chain(first, 8)
        self.assert_chain(second)
        self.assertEqual([state(o) for o in (first, second)], before)

    def test_same_island_two_disjoint_chains(self):
        obj = self.strip()
        edit([obj], True, 'EDGE')
        select_edges(obj, CHAIN+tuple((a+4, b+4) for a, b in CHAIN), True)
        ends = vertex_uv(obj)
        self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'FINISHED'})
        self.assert_chain(obj)
        points = vertex_uv(obj)
        self.assertEqual(points[5], (2, 1))
        self.assertEqual(points[6], (6, 1))
        for i in (0, 3, 4, 7):
            self.assertEqual(points[i], ends[i])

    def test_uv_seam_sides_are_independent(self):
        obj = self.strip()
        # Cut the upper/lower UV edge at x=1 by translating only its right face.
        for face in obj.data.polygons[1:]:
            for index in face.loop_indices:
                obj.data.uv_layers[0].data[index].uv.x += 10
        edit([obj], False, 'EDGE')
        select_edges(obj, ((1, 2), (2, 3)), False)
        before = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'FINISHED'})
        after = coords(obj)
        self.assertEqual(after[:4], before[:4])
        self.assertEqual(after[4], before[4])
        self.assertEqual(after[9], before[9])
        # The two selected 3D segments are 2:1 between the same fixed endpoints.
        x = before[4][0]+(before[9][0]-before[4][0])*2/3
        self.assertAlmostEqual(after[5][0], x, places=5)
        self.assertEqual(after[5], after[8])

    def test_hidden_faces_and_unshown_uv_corners_untouched(self):
        for sync in (False, True):
            with self.subTest(sync=sync):
                clear_scene()
                obj = self.strip()
                edit([obj], sync, 'EDGE')
                select_edges(obj, ((0, 1), (1, 2)), sync)
                bm = bmesh.from_edit_mesh(obj.data)
                if sync:
                    bm.faces[2].hide_set(True)
                else:
                    bm.faces[2].select_set(False)
                before = coords(obj), state(obj)
                self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'FINISHED'})
                self.assertEqual(coords(obj)[8:], before[0][8:])
                self.assertEqual(state(obj), before[1])

    def test_only_actual_selected_edge_flags_are_used(self):
        obj = self.strip()
        edit([obj], False, 'EDGE')
        select_edges(obj, ((0, 1),), False)
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        for face in bm.faces:
            for loop in face.loops:
                if loop.vert.index == 2:
                    if hasattr(loop, 'uv_select_vert_set'):
                        loop.uv_select_vert_set(True)
                    else:
                        loop[uv].select = True
        before = coords(obj), state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'CANCELLED'})
        self.assertEqual((coords(obj), state(obj)), before)

    def test_branches_closed_chains_and_invalid_metric_cancel_before_any_write(self):
        for invalid in ('BRANCH', 'CLOSED', 'ZERO', 'ENDPOINTS'):
            with self.subTest(invalid=invalid):
                clear_scene()
                good, bad = self.strip('A'), self.strip('B')
                edit([good, bad], True, 'EDGE')
                select_edges(good, CHAIN, True)
                chosen = ((0, 1), (1, 2), (1, 5)) if invalid == 'BRANCH' else (
                    ((0, 1), (1, 5), (5, 4), (4, 0)) if invalid == 'CLOSED' else CHAIN)
                select_edges(bad, chosen, True)
                bm = bmesh.from_edit_mesh(bad.data)
                if invalid == 'ZERO':
                    for vert in bm.verts:
                        vert.co = (0, 0, 0)
                elif invalid == 'ENDPOINTS':
                    uv = bm.loops.layers.uv.active
                    for face in bm.faces:
                        for loop in face.loops:
                            if loop.vert.index == 3:
                                loop[uv].uv = (0, 0)
                before = [(coords(o), state(o)) for o in (good, bad)]
                self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'CANCELLED'})
                self.assertEqual([(coords(o), state(o)) for o in (good, bad)], before)

    def test_single_zero_3d_edge_collapses_only_that_uv_segment(self):
        obj = self.strip()
        obj.data.vertices[1].co = obj.data.vertices[0].co
        edit([obj], True, 'EDGE')
        select_edges(obj, CHAIN, True)
        self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'FINISHED'})
        points = vertex_uv(obj)
        self.assertEqual(points[0], points[1])
        self.assertEqual(points[2], (6, 0))

    def test_shared_mesh_uses_active_instance_metric_and_writes_once(self):
        obj = self.strip('A')
        positions = ((0, 0, 0), (1, 0, 0), (1, 2, 0), (1, 2, 1))
        for index, vertex in enumerate(obj.data.vertices):
            vertex.co = positions[index % 4]
        linked = bpy.data.objects.new('Z_Active', obj.data)
        bpy.context.collection.objects.link(linked)
        linked.select_set(True)
        linked.scale = (2, 3, 4)
        edit([linked, obj], True, 'EDGE')
        select_edges(linked, CHAIN, True)
        actual, calls = bmesh.update_edit_mesh, []
        def update(mesh, **kwargs):
            calls.append(mesh.as_pointer())
            actual(mesh, **kwargs)
        with patch.object(bmesh, 'update_edit_mesh', side_effect=update):
            self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'FINISHED'})
        self.assertEqual(calls, [obj.data.as_pointer()])
        self.assert_chain(linked, expected=(8*2/12, 8*8/12))

    def test_failure_rolls_back_every_actual_corner_and_state(self):
        first, second = self.strip('A'), self.strip('B')
        edit([first, second], True, 'EDGE')
        for obj in (first, second):
            select_edges(obj, CHAIN, True)
        before = [(coords(o), state(o)) for o in (first, second)]
        actual, calls = bmesh.update_edit_mesh, []
        def fail_once(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError('injected length update failure')
            return actual(*args, **kwargs)
        with patch.object(bmesh, 'update_edit_mesh', side_effect=fail_once):
            self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'CANCELLED'})
        self.assertEqual([(coords(o), state(o)) for o in (first, second)], before)

    def test_undo_redo(self):
        obj = self.strip()
        edit([obj], True, 'EDGE')
        select_edges(obj, CHAIN, True)
        name, before = obj.name, coords(obj)
        bpy.ops.ed.undo_push(message='Before UV length')
        self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'FINISHED'})
        after = coords(obj)
        bpy.ops.ed.undo_push(message='After UV length')
        self.assertEqual(bpy.ops.ed.undo(), {'FINISHED'})
        self.assertEqual(coords(bpy.data.objects[name]), before)
        self.assertEqual(bpy.ops.ed.redo(), {'FINISHED'})
        self.assertEqual(coords(bpy.data.objects[name]), after)

    def test_immediate_menu_and_requires_uv_edge_mode(self):
        obj = self.strip()
        edit([obj], False, 'VERTEX')
        before = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'CANCELLED'})
        self.assertEqual(coords(obj), before)
        bpy.context.scene.tool_settings.uv_select_mode = 'EDGE'
        select_edges(obj, CHAIN, False)
        self.assertEqual(bpy.ops.ho.uvtools_uniformize_length('INVOKE_DEFAULT'), {'FINISHED'})
        self.assert_chain(obj)
        records = []
        class Layout:
            def operator(self, idname, **kwargs):
                records.append(idname)
                return types.SimpleNamespace()
        operators.IMAGE_MT_uvs_context_hotools.draw(types.SimpleNamespace(layout=Layout()), bpy.context)
        self.assertIn('ho.uvtools_uniformize_length', records)

    def test_modern_precise_sync_and_invalid_sync_fallback(self):
        if not hasattr(bmesh.types.BMesh, 'uv_select_sync_valid'):
            self.skipTest('requires modern UV selection')
        for precise in (True, False):
            with self.subTest(precise=precise):
                clear_scene()
                obj = self.strip()
                edit([obj], True, 'EDGE')
                select_edges(obj, CHAIN, True)
                bm = bmesh.from_edit_mesh(obj.data)
                if precise:
                    # Mesh retains extra edges; precise UV selection wins.
                    for edge in bm.edges:
                        edge.select = True
                    bm.uv_select_sync_valid = True
                else:
                    select_uv_faces(bm, set())
                    for edge in bm.edges:
                        edge.select = tuple(sorted(v.index for v in edge.verts)) in CHAIN
                    bm.uv_select_sync_valid = False
                before = state(obj)
                self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'FINISHED'})
                self.assert_chain(obj)
                self.assertEqual(state(obj), before)

    def test_modern_uv_edge_mode_independent_of_mesh_face_mode(self):
        if not hasattr(bmesh.types.BMesh, 'uv_select_sync_valid'):
            self.skipTest('requires modern independent UV selection')
        obj = self.strip()
        edit([obj], True, 'EDGE')
        select_edges(obj, CHAIN, True)
        settings = bpy.context.scene.tool_settings
        settings.mesh_select_mode = (False, False, True)
        settings.uv_select_mode = 'EDGE'
        bm = bmesh.from_edit_mesh(obj.data)
        # Switching mesh mode flushes the earlier UV flags. Select the UV line
        # AFTER that switch, as the UV editor's independent selection does.
        select_uv_faces(bm, set())
        for face in bm.faces:
            for loop in face.loops:
                if tuple(sorted((loop.vert.index, loop.link_loop_next.vert.index))) in CHAIN:
                    loop.uv_select_edge_set(True)
                    loop.uv_select_vert_set(True)
                    loop.link_loop_next.uv_select_vert_set(True)
        bm.uv_select_sync_valid = True
        before = state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_uniformize_length(), {'FINISHED'})
        self.assert_chain(obj)
        self.assertEqual(state(obj), before)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(UVLengthTests))
    if not result.wasSuccessful():
        raise RuntimeError('UV length integration tests failed')
