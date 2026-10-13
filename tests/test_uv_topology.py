"""Pure topology/shape tests; executable without bpy or numpy."""

import sys
import unittest
from math import cos, sin
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Utils.uv_topology import IslandTopology, MatchBudgetExceeded, TopologyError, match_islands


POINTS = ((0, 0), (2, 0), (.9, 1.2), (.1, .65), (.4, .4))
FACES = ((0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4))


def transformed(points, angle=0, scale=1, mirror=False, offset=(3, -2)):
    c, s = cos(angle), sin(angle)
    return tuple((scale*(c*x - s*(-y if mirror else y)) + offset[0],
                  scale*(s*x + c*(-y if mirror else y)) + offset[1]) for x, y in points)


def permuted(points, faces, order):
    inverse = {old: new for new, old in enumerate(order)}
    return IslandTopology([points[old] for old in order],
                          [tuple(inverse[v] for v in face[1:] + face[:1]) for face in reversed(faces)])


class TopologyTests(unittest.TestCase):
    def setUp(self):
        self.master = IslandTopology(POINTS, FACES)

    def test_rotated_scaled_and_translated(self):
        source = IslandTopology(transformed(POINTS, angle=1.1, scale=2.4), FACES)
        match = match_islands(source, self.master, tolerance=0)
        self.assertIsNotNone(match)
        self.assertEqual(match.mapping, tuple(range(len(POINTS))))
        self.assertFalse(match.reflected)
        self.assertLess(match.error, 1e-12)

    def test_mirrored_and_reindexed_including_interior_vertex(self):
        order = (2, 4, 0, 3, 1)
        source = permuted(transformed(POINTS, mirror=True, angle=.4), FACES, order)
        match = match_islands(source, self.master, tolerance=0)
        self.assertEqual(match.mapping, order)
        self.assertTrue(match.reflected)

    def test_interior_errors_are_forcibly_corrected_even_at_zero_shape_tolerance(self):
        points = list(transformed(POINTS))
        points[4] = (points[4][0] + .35, points[4][1] - .15)
        match = match_islands(IslandTopology(points, FACES), self.master, tolerance=0)
        self.assertIsNotNone(match)
        self.assertGreater(match.vertex_error, .05)
        self.assertEqual(tuple(self.master.coordinates[i] for i in match.mapping), POINTS)

    def test_border_tolerance_controls_shape_identification(self):
        points = list(transformed(POINTS))
        points[2] = (points[2][0] + .04, points[2][1] - .015)
        self.assertIsNotNone(match_islands(IslandTopology(points, FACES), self.master))
        self.assertIsNone(match_islands(IslandTopology(points, FACES), self.master, tolerance=0))

    def test_same_counts_different_shape_is_rejected(self):
        points = [(x*3, y) for x, y in POINTS]
        self.assertIsNone(match_islands(IslandTopology(points, FACES), self.master))

    def test_same_bbox_and_counts_different_connectivity_is_rejected(self):
        # Two disks with identical V/E/F counts and face sizes but a different
        # placement of the interior node cannot preserve both geometry and faces.
        other_faces = ((0, 1, 2), (0, 2, 4), (2, 3, 4), (3, 0, 4))
        self.assertIsNone(match_islands(IslandTopology(POINTS, other_faces), self.master, tolerance=0))

    def test_different_vertex_counts_are_rejected(self):
        source = IslandTopology(POINTS[:4], ((0, 1, 2, 3),))
        self.assertIsNone(match_islands(source, self.master))

    def test_symmetric_square_uses_deterministic_minimum_rotation(self):
        points = ((0, 0), (1, 0), (1, 1), (0, 1))
        master = IslandTopology(points, ((0, 1, 2, 3),))
        source = permuted(transformed(points), ((0, 1, 2, 3),), (2, 0, 3, 1))
        matches = [match_islands(source, master, tolerance=0) for _ in range(3)]
        self.assertTrue(all(match == matches[0] for match in matches))
        self.assertEqual(matches[0].mapping, (2, 0, 3, 1))
        self.assertLess(abs(matches[0].rotation), 1e-12)

    def test_island_with_hole(self):
        points = ((0, 0), (3, 0), (3, 2), (0, 2), (.5, .4), (2, .4), (2, 1.2), (.5, 1.2))
        faces = tuple((i, (i+1) % 4, 4+(i+1) % 4, 4+i) for i in range(4))
        master = IslandTopology(points, faces)
        order = (7, 3, 1, 4, 5, 0, 6, 2)
        source = permuted(transformed(points, mirror=True), faces, order)
        self.assertEqual(match_islands(source, master, tolerance=0).mapping, order)

    def test_mixed_triangles_and_quads_with_reversed_winding(self):
        points = ((0, 0), (1, 0), (1, 1), (0, 1), (2, .4))
        faces = ((0, 1, 2, 3), (1, 4, 2))
        source = IslandTopology(transformed(points), [tuple(reversed(f)) for f in reversed(faces)])
        match = match_islands(source, IslandTopology(points, faces), tolerance=0)
        self.assertEqual(match.mapping, tuple(range(5)))

    def test_quad_grid(self):
        points = tuple((x, y + .025*x*x) for y in range(6) for x in range(7))
        faces = tuple((y*7+x, y*7+x+1, (y+1)*7+x+1, (y+1)*7+x) for y in range(5) for x in range(6))
        source = permuted(transformed(points, mirror=True, angle=.7), faces, tuple(reversed(range(len(points)))))
        match = match_islands(source, IslandTopology(points, faces), tolerance=0)
        self.assertEqual(match.mapping, tuple(reversed(range(len(points)))))

    def test_work_budget_is_reported(self):
        with self.assertRaises(MatchBudgetExceeded):
            match_islands(self.master, self.master, max_work=1)

    def test_collapsed_coordinates_do_not_match(self):
        source = IslandTopology(((0, 0),)*5, FACES)
        self.assertIsNone(match_islands(source, self.master))

    def test_nonmanifold_is_rejected(self):
        with self.assertRaises(TopologyError):
            IslandTopology(POINTS, ((0, 1, 2), (1, 0, 3), (0, 1, 4)))

    def test_disconnected_faces_are_rejected(self):
        with self.assertRaises(TopologyError):
            IslandTopology(POINTS + ((2, 2),), ((0, 1, 2), (3, 4, 5)))

    def test_nonfinite_coordinates_are_rejected(self):
        with self.assertRaises(TopologyError):
            IslandTopology(((float('nan'), 0),) + POINTS[1:], FACES)

    def test_invalid_tolerance_is_rejected(self):
        with self.assertRaises(ValueError):
            match_islands(self.master, self.master, tolerance=float('inf'))


if __name__ == '__main__':
    unittest.main()
