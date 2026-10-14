"""Fixed endpoint and proportional chain distribution without Blender."""

import sys
import unittest
from math import hypot
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Utils.uv_chains import distribute_chain_by_lengths


class UVLengthTests(unittest.TestCase):
    def test_unequal_lengths_fixed_endpoints_and_curve_straightening(self):
        points = ((2, 3), (7, 9), (-1, 4), (10, 3))
        result = distribute_chain_by_lengths(points, (1, 2, 1))
        self.assertEqual(result, ((2, 3), (4, 3), (8, 3), (10, 3)))

    def test_diagonal_reflected_translated_and_reversed(self):
        points = ((-3, -2), (8, -1), (-5, 4), (-9, 6))
        weights = (1, 3, 2)
        result = distribute_chain_by_lengths(points, weights)
        reverse = distribute_chain_by_lengths(points[::-1], weights[::-1])[::-1]
        for a, b in zip(result, reverse):
            self.assertAlmostEqual(a[0], b[0])
            self.assertAlmostEqual(a[1], b[1])
        lengths = [hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(result, result[1:])]
        self.assertAlmostEqual(lengths[1]/lengths[0], 3)
        self.assertAlmostEqual(lengths[2]/lengths[0], 2)
        self.assertEqual(result[0], points[0])
        self.assertEqual(result[-1], points[-1])

    def test_large_small_3d_scales_preserve_ratios(self):
        points = ((0, 0), (1, 9), (12, 0))
        for scale in (1e-250, 1, 1e250, 1e308):
            self.assertEqual(distribute_chain_by_lengths(points, (scale, scale)), ((0, 0), (6, 0), (12, 0)))

    def test_zero_length_segments_collapse_only_their_segments(self):
        points = ((0, 0), (1, 8), (2, 8), (3, 8), (10, 0))
        result = distribute_chain_by_lengths(points, (0, 2, 0, 3))
        self.assertEqual(result, ((0, 0), (0, 0), (4, 0), (4, 0), (10, 0)))

    def test_single_edge_is_unchanged(self):
        points = ((.13, .97), (.82, -.41))
        self.assertEqual(distribute_chain_by_lengths(points, (3.7,)), points)

    def test_invalid_inputs_and_degenerate_endpoints_rejected(self):
        for points, lengths in (
                (((0, 0),), ()), (((0, 0), (1, 1)), ()),
                (((0, 0), (1, 1)), (0,)), (((0, 0), (1, 1)), (-1,)),
                (((0, 0), (1, 1)), (float('inf'),)), (((0, 0), (1, 1)), (float('nan'),)),
                (((0, 0), (1, 1), (0, 0)), (1, 1)),
                (((0, 0), (float('nan'), 1)), (1,))):
            with self.subTest(points=points, lengths=lengths), self.assertRaises(ValueError):
                distribute_chain_by_lengths(points, lengths)


if __name__ == '__main__':
    unittest.main()
