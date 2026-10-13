"""Real Blender 4.5/5.2 point-transform and Alt+A operator regressions."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_blender_uv_topology_stack import (
    POINTS, FACES, clear_scene, coords, create_object, edit, operators, select_uv_faces, state, transformed,
)
from Utils.mesh_uv import selected_uv_edge_loops, selected_uv_point_groups, write_uv_points

package = types.ModuleType('hotools_uv_transform_pie')
package.__path__ = [str(ROOT / 'HoPie')]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location(package.__name__ + '.AlignPie', ROOT / 'HoPie' / 'AlignPie.py')
align_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = align_module
spec.loader.exec_module(align_module)


class UVTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        operators.register()
        bpy.utils.register_class(align_module.AlignUV)
        cls.area = bpy.context.screen.areas[0]
        cls.previous_type = cls.area.type
        cls.area.type = 'IMAGE_EDITOR'
        cls.area.ui_type = 'UV'

    @classmethod
    def tearDownClass(cls):
        cls.area.type = cls.previous_type
        bpy.utils.unregister_class(align_module.AlignUV)
        operators.unregister()

    def setUp(self):
        clear_scene()
        self.override = bpy.context.temp_override(area=self.area, region=next(r for r in self.area.regions if r.type == 'WINDOW'))
        self.override.__enter__()

    def tearDown(self):
        clear_scene()
        self.override.__exit__(None, None, None)

    def pair(self, sync=False, mode='VERTEX'):
        a = create_object('A', [(POINTS, FACES)])
        b = create_object('B', [(transformed(POINTS, offset=(3, 3)), FACES)])
        edit([a, b], sync, mode)
        return a, b

    def test_selection_mode_matrix_mirror_and_translate_preserve_state(self):
        for sync in (False, True):
            for mode in ('VERTEX', 'EDGE', 'FACE', 'ISLAND'):
                if sync and mode == 'ISLAND':
                    continue
                with self.subTest(sync=sync, mode=mode):
                    clear_scene()
                    objects = self.pair(sync, mode)
                    before_state = [state(obj) for obj in objects]
                    before = [coords(obj) for obj in objects]
                    self.assertEqual(bpy.ops.ho.uvtools_mirror(axis='U', center_mode='ORIGIN'), {'FINISHED'})
                    for obj, original in zip(objects, before):
                        self.assertEqual(coords(obj), tuple((-x, y) for x, y in original))
                    self.assertEqual(bpy.ops.ho.uvtools_translate(direction='POS_V', distance=2), {'FINISHED'})
                    for obj, original in zip(objects, before):
                        for point, (x, y) in zip(coords(obj), original):
                            self.assertAlmostEqual(point[0], -x, places=6)
                            self.assertAlmostEqual(point[1], y + 2, places=6)
                    self.assertEqual([state(obj) for obj in objects], before_state)

    def test_mirror_is_independent_of_editor_pivot(self):
        obj = create_object('Pivot', [(POINTS, FACES)])
        edit([obj])
        # RNA's static enum includes 3D-only ACTIVE_ELEMENT and old identifiers;
        # the editor's dynamic enum differs between the two supported versions.
        pivots = ('CENTER', 'MEDIAN', 'CURSOR', 'INDIVIDUAL_ORIGINS') if bpy.app.version < (5, 0, 0) else (
            'BOUNDING_BOX_CENTER', 'MEDIAN_POINT', 'CURSOR', 'INDIVIDUAL_ORIGINS')
        for pivot in pivots:
            with self.subTest(pivot=pivot):
                self.area.spaces.active.pivot_point = pivot
                before = coords(obj)
                self.assertEqual(bpy.ops.ho.uvtools_mirror(axis='V'), {'FINISHED'})
                self.assertEqual(bpy.ops.ho.uvtools_mirror(axis='V'), {'FINISHED'})
                for a, b in zip(coords(obj), before):
                    self.assertAlmostEqual(a[0], b[0], places=6)
                    self.assertAlmostEqual(a[1], b[1], places=6)

    def test_global_and_per_island_centers(self):
        objects = self.pair()
        before = [coords(obj) for obj in objects]
        self.assertEqual(bpy.ops.ho.uvtools_mirror(axis='U', per_island=True), {'FINISHED'})
        for obj, original in zip(objects, before):
            center = (min(x for x, _ in original) + max(x for x, _ in original)) / 2
            for actual, (x, y) in zip(coords(obj), original):
                self.assertAlmostEqual(actual[0], 2 * center - x, places=6)
                self.assertEqual(actual[1], y)

    def test_cursor_and_custom_mirror_centers(self):
        obj = create_object('Centers', [(POINTS, FACES)])
        edit([obj])
        self.area.spaces.active.cursor_location = (2, -1)
        before = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_mirror(axis='U', center_mode='CURSOR'), {'FINISHED'})
        for actual, (x, y) in zip(coords(obj), before):
            self.assertAlmostEqual(actual[0], 4-x, places=6)
        self.assertEqual(bpy.ops.ho.uvtools_mirror(axis='U', center_mode='CUSTOM', center=(2, -1)), {'FINISHED'})
        for a, b in zip(coords(obj), before):
            self.assertAlmostEqual(a[0], b[0], places=6)

    def test_pixel_translation_with_non_square_image(self):
        obj = create_object('Pixels', [(POINTS, FACES)])
        edit([obj])
        image = bpy.data.images.new('UVPixelTest', width=1024, height=512)
        self.area.spaces.active.image = image
        before = coords(obj)
        try:
            self.assertEqual(bpy.ops.ho.uvtools_translate(direction='POS_U', distance=128, unit='PIXELS'), {'FINISHED'})
            self.assertEqual(bpy.ops.ho.uvtools_translate(direction='NEG_V', distance=128, unit='PIXELS'), {'FINISHED'})
            for actual, (x, y) in zip(coords(obj), before):
                self.assertAlmostEqual(actual[0], x + .125, places=6)
                self.assertAlmostEqual(actual[1], y - .25, places=6)
        finally:
            self.area.spaces.active.image = None
            bpy.data.images.remove(image)

    def test_missing_image_cancels_pixel_translation(self):
        objects = self.pair()
        self.area.spaces.active.image = None
        before = [coords(obj) for obj in objects]
        self.assertEqual(bpy.ops.ho.uvtools_translate(unit='PIXELS'), {'CANCELLED'})
        self.assertEqual([coords(obj) for obj in objects], before)

    def test_legacy_align_multimesh_and_unique_uv_vertex_average(self):
        for sync in (False, True):
            with self.subTest(sync=sync):
                clear_scene()
                objects = self.pair(sync)
                expected = sum(p[0] for p in POINTS + transformed(POINTS, offset=(3, 3))) / 10
                self.assertEqual(bpy.ops.ho.align_uv(axis='U', type='AVERAGE'), {'FINISHED'})
                for obj in objects:
                    for x, y in coords(obj):
                        self.assertAlmostEqual(x, expected, places=6)

    def test_new_and_legacy_align_share_cursor_behavior(self):
        for operation in (bpy.ops.ho.align_uv, bpy.ops.ho.uvtools_align):
            clear_scene()
            objects = self.pair()
            before = [coords(obj) for obj in objects]
            self.area.spaces.active.cursor_location = (7, 9)
            self.assertEqual(operation(axis='V', type='CURSOR'), {'FINISHED'})
            for obj, original in zip(objects, before):
                self.assertEqual(coords(obj), tuple((x, 9) for x, _ in original))

    def test_hidden_faces_and_unselected_corners_are_preserved(self):
        for sync in (False, True):
            clear_scene()
            obj = create_object('Hidden', [(POINTS, FACES)])
            edit([obj], sync)
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces[0].hide_set(True)
            before = coords(obj)
            self.assertEqual(bpy.ops.ho.align_uv(axis='U', type='ZERO'), {'FINISHED'})
            self.assertEqual(coords(obj)[:3], before[:3])

    def test_precise_synced_selection_is_not_expanded_by_align(self):
        if bpy.app.version < (5, 0, 0):
            self.skipTest('5.x precise UV selection')
        obj = create_object('Partial', [(POINTS, FACES)])
        edit([obj], True)
        bm = bmesh.from_edit_mesh(obj.data)
        select_uv_faces(bm, set())
        bm.faces[0].loops[1].uv_select_vert_set(True)
        bm.uv_select_sync_to_mesh()
        before = coords(obj)
        before_state = state(obj)
        self.assertEqual(bpy.ops.ho.align_uv(axis='U', type='ZERO'), {'FINISHED'})
        after = coords(obj)
        self.assertEqual([i for i, (a, b) in enumerate(zip(before, after)) if a != b], [1])
        self.assertEqual(state(obj), before_state)

    def test_empty_selection_and_missing_uv_do_not_create_layers(self):
        obj = create_object('NoUV', [(POINTS, FACES)], with_uv=False)
        edit([obj], True)
        for operation in (bpy.ops.ho.align_uv, bpy.ops.ho.uvtools_mirror, bpy.ops.ho.uvtools_translate):
            self.assertEqual(operation(), {'CANCELLED'})
        self.assertIsNone(bmesh.from_edit_mesh(obj.data).loops.layers.uv.active)

    def test_partial_selection_moves_only_selected_visible_loops(self):
        obj = create_object('Partial', [(POINTS, FACES)])
        edit([obj])
        bm = bmesh.from_edit_mesh(obj.data)
        select_uv_faces(bm, {0})
        before = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_translate(distance=1), {'FINISHED'})
        self.assertEqual(coords(obj)[3:], before[3:])

    def test_atomic_write_failure_and_float32_overflow(self):
        objects = self.pair()
        before = [coords(obj) for obj in objects]
        points = selected_uv_point_groups(bpy.context)[0]
        with self.assertRaises(ValueError):
            write_uv_points([(points[0], (1e100, 0))])
        actual_update, calls = bmesh.update_edit_mesh, []
        def fail_once(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('injected transform update failure')
            return actual_update(*args, **kwargs)
        with patch.object(bmesh, 'update_edit_mesh', side_effect=fail_once):
            self.assertEqual(bpy.ops.ho.uvtools_translate(), {'CANCELLED'})
        self.assertEqual([coords(obj) for obj in objects], before)

    def test_transform_undo_redo(self):
        objects = self.pair(True)
        names = [obj.name for obj in objects]
        before = [coords(obj) for obj in objects]
        bpy.ops.ed.undo_push(message='Before UV transform')
        self.assertEqual(bpy.ops.ho.uvtools_mirror(), {'FINISHED'})
        after = [coords(obj) for obj in objects]
        bpy.ops.ed.undo_push(message='After UV transform')
        self.assertEqual(bpy.ops.ed.undo(), {'FINISHED'})
        self.assertEqual([coords(bpy.data.objects[name]) for name in names], before)
        self.assertEqual(bpy.ops.ed.redo(), {'FINISHED'})
        self.assertEqual([coords(bpy.data.objects[name]) for name in names], after)

    def test_view_pie_horizontal_and_vertical_cursor_buttons(self):
        records = []
        class Builder:
            def operator(self, idname, text=''):
                item = types.SimpleNamespace(text=text)
                records.append(item)
                return item
            def separator(self):
                pass
            def split(self, **kwargs):
                return self
            def column(self, **kwargs):
                return self
            def row(self, **kwargs):
                return self
            def prop(self, *args, **kwargs):
                pass
            def label(self, **kwargs):
                pass
        context = types.SimpleNamespace(scene=types.SimpleNamespace(ho_align_pie_mode='VIEW'))
        menu = types.SimpleNamespace(layout=types.SimpleNamespace(menu_pie=lambda: None))
        with patch.object(align_module.HoPie, 'from_pie_layout', return_value=Builder()):
            align_module.HO_MT_uv_align_pie.draw(menu, context)
        self.assertEqual({r.text: r.axis for r in records if r.text in {'水平', '垂直'}}, {'水平': 'V', '垂直': 'U'})

    def test_tile_mirror_both_axes_multiobjects_and_sync_modes(self):
        tile_points = ((.125, .125), (.375, .125), (.375, .375), (.125, .375))
        faces = ((0, 1, 2, 3),)
        for sync in (False, True):
            for axis in ('U', 'V'):
                with self.subTest(sync=sync, axis=axis):
                    clear_scene()
                    objects = [create_object(str(i), [([(x+u, y+v) for x, y in tile_points], faces)])
                               for i, (u, v) in enumerate(((0, 0), (2, 1), (-1, -1)))]
                    edit(objects, sync)
                    before = [coords(obj) for obj in objects]
                    before_state = [state(obj) for obj in objects]
                    self.assertEqual(bpy.ops.ho.uvtools_mirror_in_tile(axis=axis), {'FINISHED'})
                    for obj, original, (u, v) in zip(objects, before, ((0, 0), (2, 1), (-1, -1))):
                        expected = tuple((2*u+1-x, y) if axis == 'U' else (x, 2*v+1-y) for x, y in original)
                        self.assertEqual(coords(obj), expected)
                    self.assertEqual([state(obj) for obj in objects], before_state)

    def test_tile_mirror_expands_partial_uv_selection_to_whole_island(self):
        points = ((.125, .125), (.375, .125), (.375, .375), (.125, .375), (.25, .25))
        obj = create_object('WholeIsland', [(points, FACES)])
        edit([obj])
        bm = bmesh.from_edit_mesh(obj.data)
        select_uv_faces(bm, {0})
        before = coords(obj)
        before_state = state(obj)
        self.assertEqual(bpy.ops.ho.uvtools_mirror_in_tile(), {'FINISHED'})
        self.assertEqual(coords(obj), tuple((1-x, y) for x, y in before))
        self.assertEqual(state(obj), before_state)

    def test_tile_mirror_skips_crossing_and_hidden_islands(self):
        square = ((.125, .125), (.375, .125), (.375, .375), (.125, .375))
        faces = ((0, 1, 2, 3),)
        obj = create_object('Mixed', [(square, faces), ([(x+.75, y) for x, y in square], faces),
                                     ([(x+2, y) for x, y in square], faces)])
        edit([obj])
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces[2].hide_set(True)
        before = coords(obj)
        self.assertEqual(bpy.ops.ho.uvtools_mirror_in_tile(), {'FINISHED'})
        self.assertEqual(coords(obj)[:4], tuple((1-x, y) for x, y in before[:4]))
        self.assertEqual(coords(obj)[4:], before[4:])

    def test_tile_mirror_partial_mesh_face_selection_is_allowed(self):
        points = ((.125, .125), (.375, .125), (.375, .375), (.125, .375), (.25, .25))
        for axis in ('U', 'V'):
            with self.subTest(axis=axis):
                clear_scene()
                obj = create_object('VisiblePart', [(points, FACES)])
                edit([obj])
                bm = bmesh.from_edit_mesh(obj.data)
                for face in bm.faces:
                    face.select_set(face.index == 0)
                before_state, before = state(obj), coords(obj)
                self.assertEqual(bpy.ops.ho.uvtools_mirror_in_tile(axis=axis), {'FINISHED'})
                expected = tuple((1-x, y) if axis == 'U' else (x, 1-y) for x, y in before[:3])
                self.assertEqual(coords(obj)[:3], expected)
                self.assertEqual(coords(obj)[3:], before[3:])
                self.assertEqual(state(obj), before_state)

    def test_edge_reader_does_not_invent_edges_between_selected_uv_points(self):
        obj = create_object('EdgeFlags', [(POINTS, FACES)])
        edit([obj], mode='EDGE')
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        select_uv_faces(bm, set())
        for face in bm.faces:
            for loop in face.loops:
                if hasattr(loop, 'uv_select_vert_set'):
                    loop.uv_select_vert_set(True)
                else:
                    loop[uv].select = True
        settings = bpy.context.scene.tool_settings
        self.assertEqual(selected_uv_edge_loops(bm, uv, settings), set())
        first = bm.faces[0].loops[0]
        if hasattr(first, 'uv_select_edge_set'):
            first.uv_select_edge_set(True)
        else:
            first[uv].select_edge = True
        self.assertEqual(selected_uv_edge_loops(bm, uv, settings), {first})


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(UVTransformTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
