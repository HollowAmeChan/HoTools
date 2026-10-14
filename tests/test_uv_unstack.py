import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Utils.uv_math import unstack_offsets


class UnstackMathTests(unittest.TestCase):
    def test_horizontal_uses_each_aabb_width_and_preserves_other_axis(self):
        islands = (((.25, .5), (1.25, 1.5)), ((-3, 8), (-1, 9)), ((7, -2), (7.5, -1)))
        self.assertEqual(unstack_offsets(islands, gap=.25), ((0, 0), (4.5, 0), (-3.25, 0)))

    def test_vertical_uses_aabb_height(self):
        islands = (((.25, .5), (1.25, 1.5)), ((-3, 8), (-1, 9)), ((7, -2), (7.5, -1)))
        self.assertEqual(unstack_offsets(islands, 'VERTICAL', .25), ((0, 0), (0, -6.25), (0, 5)))

    def test_tile_moves_every_remaining_island_by_exactly_one(self):
        islands = (((.1, .2), (.3, .4)),)*4
        self.assertEqual(unstack_offsets(islands, 'TILE', .5), ((0, 0), (1, 0), (1, 0), (1, 0)))

    def test_zero_gap_and_single_island(self):
        islands = (((0, 0), (1, 1)),)*3
        self.assertEqual(unstack_offsets(islands, gap=0), ((0, 0), (1, 0), (2, 0)))
        self.assertEqual(unstack_offsets(islands[:1]), ((0, 0),))

    def test_invalid_inputs_rejected(self):
        for call in (
            lambda: unstack_offsets(()),
            lambda: unstack_offsets((((0, 0),),), 'BAD'),
            lambda: unstack_offsets((((0, 0),),), gap=-.1),
            lambda: unstack_offsets((((float('nan'), 0),),)),
        ):
            with self.assertRaises(ValueError):
                call()


if __name__ == '__main__':
    unittest.main()
