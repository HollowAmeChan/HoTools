"""Run with Blender 4.5/5.2 --background --factory-startup --python-exit-code 1.

Tests real registration, native operator dispatch and BMesh data/state. No user's
scene or preferences are loaded. This file is not a regular CPython test.
"""

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from test_uv_topology import POINTS, FACES, transformed, permuted
from Utils.mesh_uv import collect_uv_islands, iter_edit_uv_meshes, selected_uv_loops
from Utils.uv_topology import IslandTopology, MatchBudgetExceeded

package = types.ModuleType('hotools_uv_stack_tests')
package.__path__ = [str(ROOT / 'UvTools')]
sys.modules[package.__name__] = package
operators = importlib.import_module(package.__name__ + '.operators')
stack = importlib.import_module(package.__name__ + '.stack')


def clear_scene():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if not mesh.users:
            bpy.data.meshes.remove(mesh)


def create_object(name, specs, with_uv=True):
    vertices, faces, uv_points = [], [], []
    for points, polygons in specs:
        offset = len(vertices)
        # Deliberately unrelated 3D axes/tangents: matching must use UV topology.
        vertices.extend((x, i * .31, y * 1.7) for i, (x, y) in enumerate(points))
        uv_points.extend(points)
        faces.extend(tuple(v + offset for v in face) for face in polygons)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    if with_uv:
        uv = mesh.uv_layers.new(name='UVMap')
        for loop in mesh.loops:
            uv.data[loop.index].uv = uv_points[loop.vertex_index]
        other = mesh.uv_layers.new(name='OtherUV')
        for index, loop in enumerate(mesh.loops):
            other.data[index].uv = (.03 * index, -.02 * index)
        mesh.uv_layers.active_index = 0
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    return obj


def edit(objects, sync=False, mode='VERTEX'):
    bpy.context.view_layer.objects.active = objects[0]
    settings = bpy.context.scene.tool_settings
    settings.use_uv_select_sync = sync
    settings.mesh_select_mode = tuple(mode == item for item in ('VERTEX', 'EDGE', 'FACE')) if mode != 'ISLAND' else (True, False, False)
    if hasattr(settings, 'use_uv_select_island'):
        settings.use_uv_select_island = mode == 'ISLAND'
    settings.uv_select_mode = 'VERTEX' if mode == 'ISLAND' and hasattr(settings, 'use_uv_select_island') else mode
    bpy.ops.object.mode_set(mode='EDIT')
    for obj in objects:
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            face.select_set(True)
        bm.select_flush_mode()
        uv = bm.loops.layers.uv.active
        if uv is not None:
            if hasattr(bm, 'uv_select_sync_from_mesh'):
                bm.uv_select_sync_from_mesh()
            else:
                for face in bm.faces:
                    for loop in face.loops:
                        loop[uv].select = True
                        loop[uv].select_edge = True
        bm.faces.active = bm.faces[0]
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)


def coords(obj, layer=None):
    bm = bmesh.from_edit_mesh(obj.data)
    uv = bm.loops.layers.uv.get(layer) if layer else bm.loops.layers.uv.active
    return tuple(tuple(loop[uv].uv) for face in bm.faces for loop in face.loops)


def state(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    uv = bm.loops.layers.uv.active
    modern = hasattr(bm, 'uv_select_sync_valid')
    return (
        tuple((tuple(v.co), v.select, v.hide) for v in bm.verts),
        tuple((e.select, e.hide, e.seam) for e in bm.edges),
        tuple((f.select, f.hide, f.uv_select if modern else None) for f in bm.faces),
        tuple((l.uv_select_vert, l.uv_select_edge, l[uv].pin_uv) if modern else
              (l[uv].select, l[uv].select_edge, l[uv].pin_uv) for f in bm.faces for l in f.loops),
        bm.uv_select_sync_valid if modern else None,
        tuple((type(item).__name__, item.index) for item in bm.select_history),
        bm.faces.active.index if bm.faces.active is not None else None,
    )


def select_uv_faces(bm, face_indices):
    uv = bm.loops.layers.uv.active
    modern = hasattr(bm, 'uv_select_sync_valid')
    for face in bm.faces:
        value = face.index in face_indices
        if modern:
            face.uv_select_set(value)
        for loop in face.loops:
            if modern:
                loop.uv_select_vert_set(value)
                loop.uv_select_edge_set(value)
            else:
                loop[uv].select = value
                loop[uv].select_edge = value


class BlenderTopologyStackTests(unittest.TestCase):
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
        region = next(r for r in self.area.regions if r.type == 'WINDOW')
        self.override = bpy.context.temp_override(area=self.area, region=region)
        self.override.__enter__()

    def tearDown(self):
        clear_scene()
        self.override.__exit__(None, None, None)

    def pair(self, sync=False, mode='VERTEX'):
        master = create_object('Master', [(POINTS, FACES)])
        order = (2, 4, 0, 3, 1)
        source_topology = permuted(transformed(POINTS, mirror=True, angle=.5, scale=1.7), FACES, order)
        source = create_object('Source', [(source_topology.coordinates, source_topology.polygons)])
        edit([master, source], sync, mode)
        return master, source, source_topology, order

    def assert_exact_pair(self, source, topology, order):
        expected = tuple(POINTS[order[v]] for face in topology.polygons for v in face)
        # Compare actual stored Blender float32, not Python's float64 literals.
        from mathutils import Vector
        expected = tuple(tuple(Vector(point)) for point in expected)
        self.assertEqual(coords(source), expected)

    def test_selection_modes_sync_matrix(self):
        for sync in (False, True):
            for mode in ('VERTEX', 'EDGE', 'FACE', 'ISLAND'):
                if sync and mode == 'ISLAND':
                    continue
                with self.subTest(sync=sync, mode=mode):
                    clear_scene()
                    master, source, topology, order = self.pair(sync, mode)
                    self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'FINISHED'})
                    self.assert_exact_pair(source, topology, order)

    def test_master_pins_seams_selection_other_layer_and_geometry_unchanged(self):
        master, source, topology, order = self.pair()
        for obj in (master, source):
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces[0].loops[0][bm.loops.layers.uv.active].pin_uv = True
            bm.edges.ensure_lookup_table()
            bm.edges[0].seam = True
        before = {obj: (state(obj), coords(obj, 'OtherUV')) for obj in (master, source)}
        master_uv = coords(master)
        settings = bpy.context.scene.tool_settings
        settings_before = (settings.use_uv_select_sync, tuple(settings.mesh_select_mode), settings.uv_select_mode, settings.uv_sticky_select_mode, getattr(settings, 'use_uv_select_island', None))
        self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'FINISHED'})
        self.assertEqual(coords(master), master_uv)
        for obj in (master, source):
            self.assertEqual((state(obj), coords(obj, 'OtherUV')), before[obj])
        self.assertEqual((settings.use_uv_select_sync, tuple(settings.mesh_select_mode), settings.uv_select_mode, settings.uv_sticky_select_mode, getattr(settings, 'use_uv_select_island', None)), settings_before)
        self.assert_exact_pair(source, topology, order)

    def test_shape_tolerance_controls_identification_and_forces_interior_vertex(self):
        points = list(transformed(POINTS))
        points[2] = (points[2][0] + .04, points[2][1] - .015)
        points[4] = (points[4][0] + .35, points[4][1] - .15)
        obj = create_object('Pair', [(POINTS, FACES), (points, FACES)])
        edit([obj])
        before = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_topology_stack(shape_tolerance=0), {'CANCELLED'})
        self.assertEqual(coords(obj), before)
        self.assertEqual(bpy.ops.ho.uvtools_topology_stack(shape_tolerance=.05), {'FINISHED'})
        self.assertEqual(coords(obj)[:12], coords(obj)[12:])

    def test_multiple_shape_groups_stack_independently(self):
        quad = ((0, 0), (2, 0), (1.8, .5), (0, 1))
        qfaces = ((0, 1, 2, 3),)
        triangle = ((7, 7), (9, 7), (7, 9))
        obj = create_object('Groups', [(POINTS, FACES), (transformed(POINTS), FACES),
                                     (quad, qfaces), (transformed(quad, mirror=True), qfaces),
                                     (triangle, ((0, 1, 2),))])
        edit([obj])
        before = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'FINISHED'})
        after = coords(obj)
        self.assertEqual(after[:12], after[12:24])
        self.assertEqual(set(after[24:28]), set(after[28:32]))
        self.assertEqual(after[32:], before[32:])

    def test_active_face_in_second_island_becomes_master(self):
        obj = create_object('Pair', [(POINTS, FACES), (transformed(POINTS), FACES)])
        edit([obj])
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.active = bm.faces[4]
        before = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'FINISHED'})
        self.assertEqual(coords(obj)[12:], before[12:])
        self.assertEqual(coords(obj)[:12], before[12:])

    def test_unselected_island_is_not_touched(self):
        obj = create_object('Triple', [(POINTS, FACES), (transformed(POINTS), FACES), (transformed(POINTS, offset=(8, 8)), FACES)])
        edit([obj])
        bm = bmesh.from_edit_mesh(obj.data)
        select_uv_faces(bm, set(range(8)))
        before = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'FINISHED'})
        self.assertEqual(coords(obj)[24:], before[24:])

    def test_hidden_or_incomplete_island_is_not_touched(self):
        for sync, hidden in ((False, True), (True, True), (False, False)):
            with self.subTest(sync=sync, hidden=hidden):
                clear_scene()
                obj = create_object('Triple', [(POINTS, FACES), (transformed(POINTS), FACES), (transformed(POINTS, offset=(8, 8)), FACES)])
                edit([obj], sync)
                bm = bmesh.from_edit_mesh(obj.data)
                if hidden:
                    bm.faces[8].hide_set(True)
                else:
                    bm.faces[8].select_set(False)
                before = coords(obj)
                self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'FINISHED'})
                self.assertEqual(coords(obj)[24:], before[24:])

    def test_sync_invalid_falls_back_to_mesh_selection(self):
        master, source, topology, order = self.pair(True, 'EDGE')
        for obj in (master, source):
            bm = bmesh.from_edit_mesh(obj.data)
            if hasattr(bm, 'uv_select_sync_valid'):
                bm.uv_select_sync_valid = False
        before = [state(obj) for obj in (master, source)]
        self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'FINISHED'})
        self.assert_exact_pair(source, topology, order)
        self.assertEqual([state(obj) for obj in (master, source)], before)

    def test_sync_valid_keeps_unselected_side_of_seam(self):
        if bpy.app.version < (5, 0, 0):
            self.skipTest('Precise synced UV selection is a 5.x feature')
        points = ((0, 0), (1.3, 0), (.2, .8))
        obj = create_object('Precise', [(points, ((0, 1, 2),)), (points, ((0, 1, 2),)), (points, ((0, 1, 2),))])
        # Rebuild two triangles sharing actual mesh vertices, with split UVs.
        mesh = obj.data
        mesh.clear_geometry()
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 0, 0), (3, 0, 0), (2, 1, 0)], [], [(0, 1, 2), (1, 0, 3), (4, 5, 6)])
        uv = mesh.uv_layers.new(name='UVMap')
        all_uv = list(points) + list(transformed(points, offset=(4, 0))) + list(transformed(points, mirror=True, offset=(7, 0)))
        for loop, coordinate in zip(uv.data, all_uv):
            loop.uv = coordinate
        edit([obj], True)
        bm = bmesh.from_edit_mesh(obj.data)
        select_uv_faces(bm, {0, 2})
        bm.uv_select_sync_to_mesh()
        before = coords(obj)
        before_state = state(obj)
        self.assertTrue(bm.uv_select_sync_valid)
        self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'FINISHED'})
        self.assertEqual(coords(obj)[3:6], before[3:6])
        self.assertEqual(coords(obj)[:3], coords(obj)[6:])
        self.assertEqual(state(obj), before_state)

    def test_missing_uv_is_not_created(self):
        master, source, _, _ = self.pair()
        bpy.ops.object.mode_set(mode='OBJECT')
        empty = create_object('NoUV', [(POINTS, FACES)], with_uv=False)
        edit([master, source, empty])
        self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'FINISHED'})
        self.assertIsNone(bmesh.from_edit_mesh(empty.data).loops.layers.uv.active)

    def test_shared_mesh_datablock_is_processed_once(self):
        obj = create_object('SharedA', [(POINTS, FACES), (transformed(POINTS), FACES)])
        instance = bpy.data.objects.new('SharedB', obj.data)
        bpy.context.collection.objects.link(instance)
        instance.select_set(True)
        edit([obj, instance])
        self.assertEqual(len(list(iter_edit_uv_meshes(bpy.context))), 1)
        self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'FINISHED'})
        self.assertEqual(coords(obj)[:12], coords(obj)[12:])

    def test_budget_cancellation_is_atomic(self):
        master, source, _, _ = self.pair()
        before = [coords(obj) for obj in (master, source)]
        with patch.object(stack, 'match_islands', side_effect=MatchBudgetExceeded('test budget')):
            self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'CANCELLED'})
        self.assertEqual([coords(obj) for obj in (master, source)], before)

    def test_write_failure_rolls_back_coordinates_and_state(self):
        master, source, _, _ = self.pair()
        before = [coords(obj) for obj in (master, source)]
        before_state = [state(obj) for obj in (master, source)]
        actual_update = bmesh.update_edit_mesh
        calls = []
        def fail_once(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('injected update failure')
            return actual_update(*args, **kwargs)
        with patch.object(bmesh, 'update_edit_mesh', side_effect=fail_once):
            # An ERROR report is converted to RuntimeError by native dispatch.
            with self.assertRaises(RuntimeError):
                bpy.ops.ho.uvtools_topology_stack()
        self.assertEqual([coords(obj) for obj in (master, source)], before)
        self.assertEqual([state(obj) for obj in (master, source)], before_state)

    def test_uv_topology_respects_continuity_instead_of_seam_flag(self):
        points = ((0, 0), (1, 0), (1, 1), (0, 1), (2, 0), (2, 1))
        faces = ((0, 1, 2, 3), (1, 4, 5, 2))
        obj = create_object('Connected', [(points, faces)])
        edit([obj])
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        for edge in bm.edges:
            edge.seam = True
        self.assertEqual(len(collect_uv_islands(obj, bm, uv, bpy.context.scene.tool_settings)), 1)
        for loop in bm.faces[1].loops:
            loop[uv].uv.x += 3
        self.assertEqual(len(collect_uv_islands(obj, bm, uv, bpy.context.scene.tool_settings)), 2)

    def test_identical_coordinates_on_unconnected_geometry_do_not_weld(self):
        obj = create_object('Overlapping', [(POINTS, FACES), (POINTS, FACES)])
        edit([obj])
        bm = bmesh.from_edit_mesh(obj.data)
        islands = collect_uv_islands(obj, bm, bm.loops.layers.uv.active, bpy.context.scene.tool_settings)
        self.assertEqual(len(islands), 2)
        self.assertEqual([len(i.coordinates) for i in islands], [5, 5])

    def test_edge_selection_uses_actual_edge_flags(self):
        obj = create_object('Edges', [(POINTS, FACES)])
        edit([obj], mode='EDGE')
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        select_uv_faces(bm, set())
        loop = bm.faces[0].loops[0]
        if hasattr(loop, 'uv_select_edge_set'):
            loop.uv_select_edge_set(True)
        else:
            loop[uv].select_edge = True
        self.assertEqual(selected_uv_loops(bm, uv, bpy.context.scene.tool_settings), {loop, loop.link_loop_next})

    def test_empty_selection_cancels_without_coordinate_changes(self):
        master, source, _, _ = self.pair()
        for obj in (master, source):
            select_uv_faces(bmesh.from_edit_mesh(obj.data), set())
        before = [coords(obj) for obj in (master, source)]
        self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'CANCELLED'})
        self.assertEqual([coords(obj) for obj in (master, source)], before)

    def test_undo_redo_restores_uv_coordinates(self):
        master, source, topology, order = self.pair(True)
        names = master.name, source.name
        before = [coords(obj) for obj in (master, source)]
        bpy.ops.ed.undo_push(message='Before topology stack')
        self.assertEqual(bpy.ops.ho.uvtools_topology_stack(), {'FINISHED'})
        after = [coords(obj) for obj in (master, source)]
        bpy.ops.ed.undo_push(message='After topology stack')
        self.assertEqual(bpy.ops.ed.undo(), {'FINISHED'})
        self.assertEqual([coords(bpy.data.objects[name]) for name in names], before)
        self.assertEqual(bpy.ops.ed.redo(), {'FINISHED'})
        self.assertEqual([coords(bpy.data.objects[name]) for name in names], after)

    def test_poll_rejects_image_view_and_object_mode(self):
        master, source, _, _ = self.pair()
        self.assertTrue(bpy.ops.ho.uvtools_topology_stack.poll())
        self.area.ui_type = 'IMAGE_EDITOR'
        self.assertFalse(bpy.ops.ho.uvtools_topology_stack.poll())
        self.area.ui_type = 'UV'
        bpy.ops.object.mode_set(mode='OBJECT')
        self.assertFalse(bpy.ops.ho.uvtools_topology_stack.poll())


if __name__ == '__main__':
    print('Testing topology stack in', bpy.app.version_string)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BlenderTopologyStackTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
