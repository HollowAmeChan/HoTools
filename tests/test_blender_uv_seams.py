"""Native active-UV seam append and state preservation tests on 4.5 / 5.2."""

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
from Utils.mesh_uv import collect_uv_islands, uv_boundary_edges
seams = importlib.import_module(operators.__package__ + '.seams')

POINTS = ((0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1))
FACES = ((0, 1, 4, 3), (1, 2, 5, 4))
CENTER = frozenset((1, 4))


def seam_keys(obj):
    if obj.data.is_editmode:
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.index_update()
        return {frozenset(v.index for v in edge.verts) for edge in bm.edges if edge.seam}
    return {frozenset(edge.vertices) for edge in obj.data.edges if edge.use_seam}


def perimeter(obj):
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.index_update()
        return {frozenset(v.index for v in edge.verts) for edge in bm.edges if len(edge.link_faces) == 1}
    finally:
        bm.free()


def object_state(obj):
    mesh = obj.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        modern = hasattr(bm, 'uv_select_sync_valid')
        uv_state = tuple(
            (uv.name, uv.active_render, tuple(
                (tuple(loop[bm.loops.layers.uv[uv.name]].uv), loop[bm.loops.layers.uv[uv.name]].pin_uv,
                 loop.uv_select_vert if modern else loop[bm.loops.layers.uv[uv.name]].select,
                 loop.uv_select_edge if modern else loop[bm.loops.layers.uv[uv.name]].select_edge)
                for face in bm.faces for loop in face.loops))
            for uv in mesh.uv_layers)
        uv_faces = tuple(face.uv_select for face in bm.faces) if modern else None
    finally:
        bm.free()
    return (tuple((tuple(v.co), v.select, v.hide) for v in mesh.vertices),
            tuple((tuple(e.vertices), e.select, e.hide) for e in mesh.edges),
            tuple((tuple(p.vertices), p.select, p.hide, p.material_index) for p in mesh.polygons),
            mesh.uv_layers.active_index,
            uv_state, uv_faces,
            obj.select_get(), bpy.context.view_layer.objects.active.name,
            tuple(tuple(v.co) for key in mesh.shape_keys.key_blocks for v in key.data) if mesh.shape_keys else None)


def edit_state_without_seams(obj):
    result = list(state(obj))
    result[1] = tuple((selected, hidden) for selected, hidden, seam in result[1])
    return tuple(result), tuple((layer.name, coords(obj, layer.name)) for layer in obj.data.uv_layers)


class UVSeamTests(unittest.TestCase):
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

    def pair(self, name='Pair', split=False):
        obj = create_object(name, [(POINTS, FACES)])
        bpy.context.view_layer.objects.active = obj
        if split:
            for index in obj.data.polygons[1].loop_indices:
                obj.data.uv_layers[0].data[index].uv.x += 3
        return obj

    def test_object_mode_all_selected_meshes_use_their_own_active_layer(self):
        first = self.pair('A', split=True)
        second = self.pair('B')
        second.data.uv_layers.active_index = 1
        unselected = self.pair('Unselected', split=True)
        unselected.select_set(False)
        missing = create_object('NoUV', [(POINTS, FACES)], with_uv=False)
        empty = bpy.data.objects.new('NonMesh', None)
        bpy.context.collection.objects.link(empty)
        empty.select_set(True)
        bpy.context.view_layer.objects.active = empty
        before = [object_state(o) for o in (first, second, unselected, missing)]
        expected = [perimeter(o) | {CENTER} for o in (first, second)]
        self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
        self.assertEqual([seam_keys(o) for o in (first, second)], expected)
        self.assertFalse(seam_keys(unselected))
        self.assertFalse(seam_keys(missing))
        self.assertFalse(missing.data.uv_layers)
        self.assertEqual([object_state(o) for o in (first, second, unselected, missing)], before)

    def test_edit_mode_hidden_and_unselected_faces_sync_selection_matrix(self):
        for sync in (False, True):
            for mode in ('VERTEX', 'EDGE', 'FACE', 'ISLAND'):
                if sync and mode == 'ISLAND':
                    continue
                with self.subTest(sync=sync, mode=mode):
                    clear_scene()
                    first, second = self.pair('A', True), self.pair('B', True)
                    expected = [perimeter(o) | {CENTER} for o in (first, second)]
                    edit([first, second], sync, mode)
                    for obj in (first, second):
                        bm = bmesh.from_edit_mesh(obj.data)
                        select_uv_faces(bm, set())
                        bm.faces[1].hide_set(True)
                        for face in bm.faces:
                            face.select_set(False)
                        for vert in bm.verts:
                            vert.select_set(False)
                        bm.select_history.clear()
                        bm.faces[0].loops[0][bm.loops.layers.uv.active].pin_uv = True
                        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
                    before = [edit_state_without_seams(o) for o in (first, second)]
                    self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
                    self.assertEqual([seam_keys(o) for o in (first, second)], expected)
                    self.assertEqual([edit_state_without_seams(o) for o in (first, second)], before)
                    self.assertEqual(bpy.context.mode, 'EDIT_MESH')
                    self.assertEqual(bpy.context.scene.tool_settings.use_uv_select_sync, sync)

    def test_existing_internal_and_loose_seams_preserved_without_creating_loose_seams(self):
        obj = self.pair()
        for edge in obj.data.edges:
            if frozenset(edge.vertices) == CENTER:
                edge.use_seam = True
        edit([obj])
        bm = bmesh.from_edit_mesh(obj.data)
        a, b, c = [bm.verts.new((x, 9, 0)) for x in (0, 1, 2)]
        old, bare = bm.edges.new((a, b)), bm.edges.new((b, c))
        old.seam = True
        bmesh.update_edit_mesh(obj.data)
        self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
        self.assertTrue(old.seam)
        self.assertFalse(bare.seam)
        self.assertTrue(all(edge.seam for edge in bm.edges if edge.link_faces))

    def test_edit_objects_with_different_active_layers(self):
        first, second = self.pair('A'), self.pair('B')
        second.data.uv_layers.active_index = 1
        expected = perimeter(first), perimeter(second) | {CENTER}
        edit([first, second], True)
        before = [edit_state_without_seams(o) for o in (first, second)]
        self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
        self.assertEqual((seam_keys(first), seam_keys(second)), expected)
        self.assertEqual([edit_state_without_seams(o) for o in (first, second)], before)

    def test_switching_active_uv_adds_different_cuts(self):
        points = tuple((x, y) for y in (0, 1) for x in range(4))
        faces = ((0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6))
        obj = create_object('SwitchUV', [(points, faces)])
        bpy.context.view_layer.objects.active = obj
        for layer_index, cut in ((0, 0), (1, 1)):
            layer = obj.data.uv_layers[layer_index]
            for face in obj.data.polygons:
                for index in face.loop_indices:
                    x, y = points[obj.data.loops[index].vertex_index]
                    layer.data[index].uv = x+(4 if face.index > cut else 0), y
        edge_a, edge_b = frozenset((1, 5)), frozenset((2, 6))
        before = object_state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
        self.assertIn(edge_a, seam_keys(obj))
        self.assertNotIn(edge_b, seam_keys(obj))
        obj.data.uv_layers.active_index = 1
        self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
        self.assertTrue({edge_a, edge_b}.issubset(seam_keys(obj)))
        obj.data.uv_layers.active_index = 0
        self.assertEqual(object_state(obj), before)

    def test_single_endpoint_split_marks_shared_edge(self):
        obj = self.pair()
        index = obj.data.polygons[1].loop_indices[0]
        obj.data.uv_layers[0].data[index].uv.x += .25
        self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
        self.assertEqual(seam_keys(obj), perimeter(obj) | {CENTER})

    def test_internal_uv_cut_reconnecting_elsewhere_is_still_a_boundary(self):
        points = tuple((x, y) for y in range(3) for x in range(3))
        faces = ((0, 1, 4, 3), (1, 2, 5, 4), (3, 4, 7, 6), (4, 5, 8, 7))
        obj = create_object('ConnectedCut', [(points, faces)])
        bpy.context.view_layer.objects.active = obj
        obj.data.uv_layers[0].data[obj.data.polygons[3].loop_indices[2]].uv.x += .25
        # Split just one endpoint on an outer corner first: no new internal cut.
        edit([obj])
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        bm.faces[3].loops[1][uv].uv.x += .25
        self.assertEqual(len(collect_uv_islands(obj, bm, uv, bpy.context.scene.tool_settings)), 1)
        self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
        cut = next(edge for edge in bm.edges if {v.index for v in edge.verts} == {4, 5})
        self.assertTrue(cut.seam)
        self.assertFalse(next(edge for edge in bm.edges if {v.index for v in edge.verts} == {4, 7}).seam)

    def test_mirrored_stack_shared_boundary_is_marked(self):
        obj = self.pair()
        for index in obj.data.polygons[1].loop_indices:
            loop = obj.data.uv_layers[0].data[index]
            loop.uv.x = 2-loop.uv.x
        self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
        self.assertIn(CENTER, seam_keys(obj))

    def test_normal_reflected_and_reversed_faces_remain_continuous(self):
        for reflected in (False, True):
            for reversed_face in (False, True):
                with self.subTest(reflected=reflected, reversed_face=reversed_face):
                    clear_scene()
                    points = tuple((-x, y) if reflected else (x, y) for x, y in POINTS)
                    faces = (FACES[0], tuple(reversed(FACES[1])) if reversed_face else FACES[1])
                    obj = create_object('Continuous', [(points, faces)])
                    bpy.context.view_layer.objects.active = obj
                    self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
                    self.assertEqual(seam_keys(obj), perimeter(obj))

    def test_nonmanifold_uv_discontinuity_and_coordinate_tolerance(self):
        obj = create_object('Radial', [(((0, 0), (1, 0), (0, 1), (0, -1), (1, 1)),
                                     ((0, 1, 2), (1, 0, 3), (0, 1, 4)))])
        bpy.context.view_layer.objects.active = obj
        obj.data.uv_layers[0].data[obj.data.polygons[2].loop_indices[0]].uv.x = .25
        self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
        self.assertIn(frozenset((0, 1)), seam_keys(obj))
        clear_scene()
        obj = self.pair()
        edit([obj])
        bm = bmesh.from_edit_mesh(obj.data)
        layer = bm.loops.layers.uv.active
        for face in bm.faces:
            for loop in face.loops:
                loop[layer].uv.x -= 1
        corner = bm.faces[1].loops[0]
        center = next(edge for edge in bm.edges if {v.index for v in edge.verts} == {1, 4})
        corner[layer].uv.x = .5e-7
        self.assertNotIn(center, uv_boundary_edges(bm, layer))
        corner[layer].uv.x = 2e-7
        self.assertIn(center, uv_boundary_edges(bm, layer))

    def test_shared_mesh_deduplicated_and_repeat_is_noop(self):
        obj = self.pair(split=True)
        linked = bpy.data.objects.new('Linked', obj.data)
        bpy.context.collection.objects.link(linked)
        linked.select_set(True)
        actual, calls = seams._update_mesh, []
        def update(mesh):
            calls.append(mesh.as_pointer())
            actual(mesh)
        with patch.object(seams, '_update_mesh', side_effect=update):
            self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
            self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
        self.assertEqual(calls, [obj.data.as_pointer()])
        self.assertEqual(seam_keys(obj), seam_keys(linked))

    def test_shape_keys_custom_attributes_and_object_state_unchanged(self):
        obj = self.pair(split=True)
        obj.shape_key_add(name='Basis')
        key = obj.shape_key_add(name='Shape')
        key.data[0].co.z += .4
        attribute = obj.data.attributes.new('TestEdge', 'FLOAT', 'EDGE')
        for index, item in enumerate(attribute.data):
            item.value = .25+index
        before = object_state(obj), tuple(item.value for item in attribute.data)
        self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
        self.assertEqual((object_state(obj), tuple(item.value for item in attribute.data)), before)

    def test_update_failure_restores_all_meshes_in_both_modes(self):
        for editing in (False, True):
            with self.subTest(editing=editing):
                clear_scene()
                first, second = self.pair('A', True), self.pair('B', True)
                if editing:
                    edit([first, second])
                before = [seam_keys(o) for o in (first, second)]
                actual, calls = seams._update_mesh, []
                def fail_once(mesh):
                    calls.append(mesh)
                    if len(calls) == 2:
                        raise RuntimeError('injected seam update failure')
                    actual(mesh)
                with patch.object(seams, '_update_mesh', side_effect=fail_once):
                    with self.assertRaisesRegex(RuntimeError, 'injected seam update failure'):
                        bpy.ops.ho.uvtools_seams_from_islands()
                self.assertEqual([seam_keys(o) for o in (first, second)], before)

    def test_undo_redo_in_object_and_edit_modes(self):
        for editing in (False, True):
            with self.subTest(editing=editing):
                clear_scene()
                obj = self.pair(split=True)
                name = obj.name
                if editing:
                    edit([obj], True)
                before = seam_keys(obj)
                bpy.ops.ed.undo_push(message='Before UV seams')
                self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands(), {'FINISHED'})
                after = seam_keys(obj)
                bpy.ops.ed.undo_push(message='After UV seams')
                self.assertEqual(bpy.ops.ed.undo(), {'FINISHED'})
                self.assertEqual(seam_keys(bpy.data.objects[name]), before)
                self.assertEqual(bpy.ops.ed.redo(), {'FINISHED'})
                self.assertEqual(seam_keys(bpy.data.objects[name]), after)

    def test_menu_property_button_and_immediate_execution(self):
        self.pair(split=True)
        self.assertEqual(bpy.ops.ho.uvtools_seams_from_islands('INVOKE_DEFAULT'), {'FINISHED'})
        records = []
        class Layout:
            alignment = ''
            def row(self, **kwargs):
                return self
            def operator(self, idname, **kwargs):
                records.append(idname)
                return types.SimpleNamespace()
            def prop(self, *args, **kwargs):
                pass
        layout = types.SimpleNamespace(layout=Layout())
        operators.IMAGE_MT_uvs_context_hotools.draw(layout, bpy.context)
        self.assertIn(seams.OP_UVTools_SeamsFromIslands.bl_idname, records)
        records.clear()
        operators.draw_in_DATA_PT_uv_texture(layout, bpy.context)
        self.assertIn(seams.OP_UVTools_SeamsFromIslands.bl_idname, records)

    def test_missing_uv_poll_does_not_create_layers(self):
        obj = create_object('Missing', [(POINTS, FACES)], with_uv=False)
        bpy.context.view_layer.objects.active = obj
        self.assertFalse(bpy.ops.ho.uvtools_seams_from_islands.poll())
        self.assertFalse(obj.data.uv_layers)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(UVSeamTests))
    if not result.wasSuccessful():
        raise RuntimeError('UV seam integration tests failed')
