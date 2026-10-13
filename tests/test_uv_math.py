import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Utils.uv_math import align_points, bounds_center, mirror_points, translate_points


class UVMathTests(unittest.TestCase):
    def test_mirror_twice_restores_points_at_arbitrary_center(self):
        points = ((-2, 3), (4, -1), (0, .25))
        for axis in (0, 1):
            result = mirror_points(mirror_points(points, axis, (1, 2)), axis, (1, 2))
            self.assertEqual(result, points)

    def test_bounds_center_allows_points_and_zero_extent(self):
        self.assertEqual(bounds_center(((2, -3),)), (2, -3))
        self.assertEqual(bounds_center(((2, -3), (2, 1))), (2, -1))

    def test_mirror_keeps_other_axis_and_pivot(self):
        self.assertEqual(mirror_points(((1, 2), (4, 5)), 0, (1, 2)), ((1, 2), (-2, 5)))

    def test_translate_four_directions_and_back(self):
        points = ((-2, 3), (4, -1))
        for positive, negative in (('POS_U', 'NEG_U'), ('POS_V', 'NEG_V')):
            self.assertEqual(translate_points(translate_points(points, positive, 3), negative, 3), points)

    def test_pixel_translation_uses_axis_resolution(self):
        self.assertEqual(translate_points(((0, 0),), 'POS_U', 128, (1024, 512)), ((.125, 0),))
        self.assertEqual(translate_points(((0, 0),), 'NEG_V', 128, (1024, 512)), ((0, -.25),))

    def test_alignment_methods_and_unchanged_axis(self):
        points = ((-2, 3), (4, 5), (1, -7))
        for method, value in (('MIN', -2), ('MAX', 4), ('AVERAGE', 1), ('ZERO', 0), ('CURSOR', 9)):
            self.assertEqual(align_points(points, 0, method, 9), tuple((value, p[1]) for p in points))

    def test_horizontal_fixes_v_and_vertical_fixes_u(self):
        self.assertEqual(align_points(((1, 2), (3, 4)), 1, 'AVERAGE'), ((1, 3), (3, 3)))

    def test_invalid_inputs_are_rejected(self):
        calls = (
            lambda: bounds_center(()), lambda: bounds_center(((float('nan'), 0),)),
            lambda: mirror_points(((0, 0),), 2, (0, 0)),
            lambda: translate_points(((0, 0),), 'POS_U', -1),
            lambda: translate_points(((0, 0),), 'POS_U', 1, (0, 512)),
            lambda: align_points(((0, 0),), 0, 'CURSOR'),
        )
        for call in calls:
            with self.assertRaises(ValueError):
                call()


if __name__ == '__main__':
    unittest.main()
