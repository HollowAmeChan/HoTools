"""Run with Blender --background --factory-startup --python this_file."""

import importlib.util
import inspect
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch

import bmesh
import bpy
from mathutils import Euler, Matrix, Quaternion, Vector


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location(
    "hotools_edge_constraint_scale_test", ROOT / "MeshTools" / "edge_constraint.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
OP = module.OP_TransformEdgeConstrained


class EdgeConstraintScaleTests(unittest.TestCase):
    def setUp(self):
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)

    def tearDown(self):
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

    def make_operator(self, mx, applied=False, centers=((0, 0, 0),)):
        coords, faces, sequences, rails = [], [], [], []
        for center in centers:
            center = Vector(center)
            inner = [center + Vector((x, y, 0)) for x, y in
                     ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            outer = [center + Vector((v.x * 3, v.y * 2, 0))
                     for v in (co - center for co in inner)]
            base = len(coords)
            coords.extend(inner + outer)
            sequences.append(list(range(base, base + 4)))
            rails.extend((mx @ a, mx @ b) for a, b in zip(inner, outer))
            for i in range(4):
                j = (i + 1) % 4
                faces.append((base + i, base + i + 4, base + j + 4, base + j))
        mesh = bpy.data.meshes.new("EdgeConstraintScaleTest")
        mesh.from_pydata([mx @ co if applied else co for co in coords], [], faces)
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.normal_update()
        op = SimpleNamespace(
            mx=Matrix.Identity(4) if applied else mx.copy(), active=obj, bm=bm,
            original_edge_coords=[], slide_coords=[], draw_face_align=False,
            draw_end_align=False, rotation=Quaternion(), transform_mode='SCALE',
            transform_axis='VIEW', is_zero_scaling=False, is_axis_locking=False,
            is_direction_locking=False, locked_intersection=None,
            individual_origins=len(centers) > 1, end_align=True, face_align=False,
            limit_to_edge_segment=False, origin_dir=Vector((0, 0, 1)),
            constrain_mode='DIRECT_PLANE_INTERSECTION', scale=Vector(),
        )
        for name, func in vars(OP).items():
            if inspect.isfunction(func):
                setattr(op, name, MethodType(func, op))
        seqs = [([bm.verts[i] for i in indices], True) for indices in sequences]
        op.data = op.get_data(bm, seqs)
        op.origin = mx @ module.average_locations(Vector(c) for c in centers)
        return op, rails

    def run_scale(self, mx, amount=1.6, applied=False, centers=((0, 0, 0),),
                  direction=None, axis=None, locked=False, zero=False):
        op, rails = self.make_operator(mx, applied, centers)
        direction = (direction or Vector((0.9, 0.45, 0.2))).normalized()
        op.init_intersection = op.origin + direction * 2
        op.intersection = op.origin + direction * (2 * amount)
        op.is_zero_scaling = zero
        if axis:
            op.transform_axis = axis
            op.is_axis_locking = True
            direction = mx.col[module.axis_mapping_dict[axis]].xyz.normalized()
            op.init_intersection = op.origin + direction * 2
            op.intersection = op.origin + direction * (2 * amount)
        if locked:
            op.is_direction_locking = True
            op.locked_intersection = op.init_intersection.copy()
        op.transform(bpy.context)
        actual, expected = [], []
        index = 0
        for seq in op.data.values():
            pivot = seq['origin'] if op.individual_origins else op.origin
            for vert in seq['verts']:
                start, end = rails[index]
                rail = end - start
                effective_amount = 0 if zero else amount
                factor = ((effective_amount - 1) * direction.dot(start - pivot)
                          / direction.dot(rail))
                expected.append(start + rail * factor)
                actual.append(op.mx @ vert.co)
                index += 1
        return actual, expected, op

    def assert_coords(self, actual, expected):
        for a, e in zip(actual, expected):
            self.assertLess((a - e).length, 2e-4, f"{tuple(a)} != {tuple(e)}")

    def matrices(self):
        rot = Euler((0.4, -0.7, 0.9)).to_matrix().to_4x4()
        loc = Matrix.Translation((3, -2, 4))
        return [Matrix.Identity(4), loc @ rot,
                loc @ rot @ Matrix.Diagonal((2.5, 0.6, 1.7, 1)),
                loc @ rot @ Matrix.Diagonal((-2.5, 0.6, 1.7, 1)),
                loc @ rot @ Matrix(((2, 0.5, 0, 0), (0, 0.7, 0.3, 0),
                                   (0, 0, 1.2, 0), (0, 0, 0, 1)))]

    def test_world_scale_matches_plane_rail_intersection(self):
        for i, mx in enumerate(self.matrices()):
            with self.subTest(matrix=i):
                actual, expected, _ = self.run_scale(mx)
                self.assert_coords(actual, expected)

    def test_applying_object_transform_preserves_result(self):
        for i, mx in enumerate(self.matrices()):
            with self.subTest(matrix=i):
                actual, _, _ = self.run_scale(mx)
                applied, _, _ = self.run_scale(mx, applied=True)
                self.assert_coords(actual, applied)

    def test_axis_and_direction_lock_use_world_scale(self):
        mx = self.matrices()[2]
        for axis, locked in ((None, True), ('X', False), ('Y', False)):
            with self.subTest(axis=axis, locked=locked):
                actual, expected, _ = self.run_scale(mx, axis=axis, locked=locked)
                self.assert_coords(actual, expected)

    def test_zero_scale_and_individual_origins(self):
        for zero in (False, True):
            with self.subTest(zero=zero):
                actual, expected, _ = self.run_scale(
                    self.matrices()[2], centers=((-4, 0, 0), (4, 0, 0)), zero=zero
                )
                self.assert_coords(actual, expected)

    def test_mouse_at_pivot_collapses_without_losing_scale_direction(self):
        actual, expected, _ = self.run_scale(Matrix.Identity(4), amount=0)
        self.assert_coords(actual, expected)

    def test_axis_projection_at_pivot_does_not_divide_by_zero(self):
        op, _ = self.make_operator(Matrix.Identity(4))
        op.is_axis_locking = True
        op.transform_axis = 'X'
        op.init_intersection = op.origin + Vector((0, 2, 0))
        op.intersection = op.origin + Vector((0, 3, 0))
        before = [v.co.copy() for seq in op.data.values() for v in seq['verts']]
        op.transform(bpy.context)
        self.assert_coords([v.co for seq in op.data.values() for v in seq['verts']], before)

    def test_parallel_slide_rail_keeps_original_vertex(self):
        op, _ = self.make_operator(Matrix.Identity(4))
        # The first rail is (-2, -1, 0), perpendicular to (1, -2, 0).
        direction = Vector((1, -2, 0)).normalized()
        op.init_intersection = op.origin + direction * 2
        op.intersection = op.origin + direction * 3
        vert = op.data[0]['verts'][0]
        before = vert.co.copy()
        op.transform(bpy.context)
        self.assert_coords([vert.co], [before])

    def test_locked_direction_survives_mouse_at_pivot(self):
        op, rails = self.make_operator(Matrix.Identity(4))
        direction = Vector((0.6, 0.8, 0))
        op.is_direction_locking = True
        op.init_intersection = op.origin + Vector((2, 0, 0))
        op.locked_intersection = op.origin + direction * 2
        op.intersection = op.origin.copy()
        op.transform(bpy.context)
        expected = [a - (b - a) * (direction.dot(a - op.origin)
                    / direction.dot(b - a)) for a, b in rails]
        self.assert_coords([v.co for v in op.data[0]['verts']], expected)

    def test_pivot_start_establishes_reference_on_first_movement(self):
        op, rails = self.make_operator(Matrix.Identity(4))
        direction = Vector((0.9, 0.45, 0.2)).normalized()
        op.init_intersection = op.origin.copy()
        op.intersection = op.origin.copy()
        op.transform(bpy.context)
        self.assertEqual(op.amount, 1)
        op.intersection = op.origin + direction * 2
        op.transform(bpy.context)
        self.assert_coords([v.co for v in op.data[0]['verts']], [a for a, _ in rails])
        op.intersection = op.origin + direction * 4
        op.transform(bpy.context)
        expected = [a + (b - a) * (direction.dot(a - op.origin)
                    / direction.dot(b - a)) for a, b in rails]
        self.assert_coords([v.co for v in op.data[0]['verts']], expected)

    def test_segment_limit_still_clamps_scaled_vertices(self):
        _, _, op = self.run_scale(self.matrices()[2], amount=4)
        op.limit_to_edge_segment = True
        op.transform(bpy.context)
        for seq in op.tdata.values():
            for vert in seq['verts']:
                segment = seq[vert]['edge_segment']
                self.assertIsNotNone(segment)
                clamped = module.clamp_point_to_segment(vert.co, segment)
                self.assert_coords([vert.co], [clamped])

    def test_small_object_scale_does_not_clear_axis_lock(self):
        op, _ = self.make_operator(Matrix.Diagonal((0.001, 0.002, 0.003, 1)))
        op.is_axis_locking = True
        op.transform_axis = 'X'
        op.mousepos = Vector((10, 10))
        context = SimpleNamespace(
            region=SimpleNamespace(width=100, height=100), region_data=None,
            scene=bpy.context.scene,
        )
        with patch.object(module, 'region_2d_to_origin_3d', return_value=Vector((2, 1, 10))), \
             patch.object(module, 'region_2d_to_vector_3d', return_value=Vector((0, 0, -1))):
            op.update_transform_plane(context, init=True)
        self.assertTrue(op.is_axis_locking)
        self.assertEqual(op.transform_axis, 'X')
        self.assert_coords([op.intersection], [Vector((2, 1, 0))])

    def test_modal_mode_and_axis_changes_refresh_alt_lock(self):
        op, _ = self.make_operator(Matrix.Identity(4))
        op.transform_mode = 'ROTATE'
        op.init_intersection = op.origin + Vector((2, 1, 0))
        op.intersection = op.init_intersection.copy()
        op.update_transform_plane = lambda context, init=False: None
        context = SimpleNamespace(area=SimpleNamespace(tag_redraw=lambda: None))
        event = SimpleNamespace(type='S', value='PRESS', alt=True, ctrl=False, shift=False)
        op.modal(context, event)
        self.assertTrue(op.is_direction_locking)
        self.assertIsNotNone(op.locked_intersection)
        event.type = 'X'
        op.modal(context, event)
        self.assertTrue(op.is_axis_locking)
        self.assertFalse(op.is_direction_locking)
        self.assertIsNone(op.locked_intersection)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(EdgeConstraintScaleTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
