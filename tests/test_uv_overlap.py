"""Pure UV workspace grouping, including partial overlap and polygon holes."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Utils.uv_overlap import overlap_workspaces


def rectangle(x=0, y=0, width=1, height=1):
    a, b, c, d = (x, y), (x+width, y), (x+width, y+height), (x, y+height)
    return ((a, b, c), (a, c, d))


class UVOverlapTests(unittest.TestCase):
    def test_exact_stacks_independent_workspaces_and_standalone(self):
        groups = (rectangle(), rectangle(4, 2), rectangle(), rectangle(4, 2), rectangle(10, 0))
        self.assertEqual(overlap_workspaces(groups), ((0, 2), (1, 3), (4,)))

    def test_partial_overlap_chain_is_transitive(self):
        self.assertEqual(overlap_workspaces([rectangle(x) for x in (0, .75, 1.5)]), ((0, 1, 2),))

    def test_touching_border_or_corner_is_not_overlap(self):
        self.assertEqual(overlap_workspaces((rectangle(), rectangle(1, 0), rectangle(2, 1))), ((0,), (1,), (2,)))

    def test_overlapping_aabbs_do_not_merge_separate_triangles(self):
        a = (((0, 0), (2, 0), (0, 2)),)
        b = (((2, 2), (2, .75), (.75, 2)),)
        self.assertEqual(overlap_workspaces((a, b)), ((0,), (1,)))

    def test_concave_island_and_hole_keep_empty_regions_independent(self):
        concave = rectangle(0, 0, 1, 3)+rectangle(1, 0, 2, 1)
        square = rectangle(1.5, 1.5)
        self.assertEqual(overlap_workspaces((concave, square)), ((0,), (1,)))
        ring = rectangle(0, 0, 3, 1)+rectangle(0, 2, 3, 1)+rectangle(0, 1, 1, 1)+rectangle(2, 1, 1, 1)
        self.assertEqual(overlap_workspaces((ring, rectangle(1.25, 1.25, .5, .5))), ((0,), (1,)))

    def test_containment_reflection_and_face_winding(self):
        inner = rectangle(.25, .25, .5, .5)
        reflected = tuple(tuple((1-x, y) for x, y in triangle[::-1]) for triangle in rectangle())
        self.assertEqual(overlap_workspaces((rectangle(), inner, reflected)), ((0, 1, 2),))

    def test_small_large_scales_and_distant_tiles(self):
        for scale, offset in ((1e-7, 0), (1e7, 0), (1, 1e7)):
            groups = tuple(tuple(tuple((offset+scale*x, -offset+scale*y) for x, y in triangle)
                                 for triangle in rectangle(position)) for position in (0, .75, 3))
            self.assertEqual(overlap_workspaces(groups), ((0, 1), (2,)))

    def test_empty_single_and_degenerate_are_valid_workspaces(self):
        self.assertEqual(overlap_workspaces(()), ())
        self.assertEqual(overlap_workspaces((rectangle(),)), ((0,),))
        self.assertEqual(overlap_workspaces(((), (((0, 0), (1, 0), (2, 0)),))), ((0,), (1,)))

    def test_invalid_triangles_and_tolerance_rejected(self):
        for groups, epsilon in (([(((0, 0), (1, 0)),)], 0),
                                ([(((float('nan'), 0), (1, 0), (0, 1)),)], 0),
                                ([], -1), ([], float('inf'))):
            with self.assertRaises(ValueError):
                overlap_workspaces(groups, epsilon)


if __name__ == '__main__':
    unittest.main()
