"""Curve symmetrize regressions; run with Blender --background --python."""

import importlib.util
from pathlib import Path
import unittest

import bpy


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hotools_curve_symmetrize_test", ROOT / "CurveTools" / "symmetrize.py"
)
symmetrize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(symmetrize)


def _points(spline):
    return spline.bezier_points if spline.type == "BEZIER" else spline.points


def _coords(spline):
    return [tuple(round(value, 5) for value in point.co[:3])
            for point in _points(spline)]


class CurveSymmetrizeTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        curve = bpy.data.curves.new("CurveSymmetrizeRegression", "CURVE")
        curve.dimensions = "3D"
        self.obj = bpy.data.objects.new("CurveSymmetrizeRegression", curve)
        bpy.context.collection.objects.link(self.obj)
        self.obj.select_set(True)
        bpy.context.view_layer.objects.active = self.obj

    def tearDown(self):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.data.objects.remove(self.obj, do_unlink=True)

    def add_spline(self, coordinates, spline_type="POLY"):
        spline = self.obj.data.splines.new(spline_type)
        points = _points(spline)
        points.add(len(coordinates) - 1)
        for point, coordinate in zip(points, coordinates):
            point.co = coordinate if spline_type == "BEZIER" else (*coordinate, 1.0)
            if spline_type == "BEZIER":
                point.handle_left_type = point.handle_right_type = "FREE"
        return spline

    def run_symmetrize(self, direction="POSITIVE_X"):
        bpy.ops.object.mode_set(mode="EDIT")
        result = symmetrize._curve_symmetrize(
            self.obj, direction, threshold=0.0001, partial=False, remove=False
        )
        self.assertTrue(result["curve"])
        bpy.ops.object.mode_set(mode="OBJECT")

    def test_existing_target_controls_are_replaced_with_reflected_source(self):
        # The stale target controls intentionally have a different count and
        # wrong shape; full symmetry must replace them rather than skip them.
        self.add_spline([
            (-0.5, 90.0, 0.0), (-1.5, 80.0, 0.0),
            (1.0, 1.0, 0.0), (2.0, 2.0, 0.0), (3.0, 3.0, 0.0),
        ])
        self.run_symmetrize()
        self.assertEqual(_coords(self.obj.data.splines[0]), [
            (-3.0, 3.0, 0.0), (-2.0, 2.0, 0.0), (-1.0, 1.0, 0.0),
            (1.0, 1.0, 0.0), (2.0, 2.0, 0.0), (3.0, 3.0, 0.0),
        ])

    def test_bezier_target_handles_are_replaced_and_mirrored(self):
        spline = self.add_spline([
            (-1.0, 50.0, 0.0), (1.0, 1.0, 0.0), (2.0, 2.0, 0.0),
        ], "BEZIER")
        source = spline.bezier_points[1]
        source.handle_left = (0.6, 0.7, 0.0)
        source.handle_right = (1.4, 1.3, 0.0)
        source.radius = 2.0
        self.run_symmetrize()
        points = self.obj.data.splines[0].bezier_points
        self.assertEqual(_coords(self.obj.data.splines[0]), [
            (-2.0, 2.0, 0.0), (-1.0, 1.0, 0.0),
            (1.0, 1.0, 0.0), (2.0, 2.0, 0.0),
        ])
        self.assertEqual(tuple(round(value, 5) for value in points[1].handle_left),
                         (-1.4, 1.3, 0.0))
        self.assertEqual(tuple(round(value, 5) for value in points[1].handle_right),
                         (-0.6, 0.7, 0.0))
        self.assertAlmostEqual(points[1].radius, 2.0)

    def test_repeated_symmetrize_does_not_grow_control_count(self):
        self.add_spline([
            (-2.0, 2.0, 0.0), (-1.0, 1.0, 0.0),
            (1.0, 1.0, 0.0), (2.0, 2.0, 0.0),
        ])
        self.run_symmetrize()
        first = _coords(self.obj.data.splines[0])
        self.run_symmetrize()
        self.assertEqual(_coords(self.obj.data.splines[0]), first)


if __name__ == "__main__":
    unittest.main(argv=[__file__])
