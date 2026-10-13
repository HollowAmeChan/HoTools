import sys
import unittest
from math import cos, hypot, pi, sin
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Utils.uv_chains import ensure_orientation_anchor, ensure_region_anchors, find_straight_chains, line_constraints, trace_open_chains
from Utils.uv_topology import IslandTopology


def grid(width=4, height=4, noise=.0):
    points = tuple((x + (noise if y % 2 else -noise), y + (noise if x % 2 else -noise))
                   for y in range(height) for x in range(width))
    faces = tuple((y*width+x, y*width+x+1, (y+1)*width+x+1, (y+1)*width+x)
                  for y in range(height-1) for x in range(width-1))
    return points, faces


class UVChainTests(unittest.TestCase):
    def test_trace_multiple_open_chains_deduplicates_face_sides(self):
        self.assertEqual(trace_open_chains(((0, 1), (1, 0), (1, 2), (4, 5))), ((0, 1, 2), (4, 5)))

    def test_cycles_and_branches_rejected(self):
        for edges in (((0, 1), (1, 2), (2, 0)), ((0, 1), (1, 2), (1, 3))):
            with self.assertRaises(ValueError):
                trace_open_chains(edges)

    def test_manual_chain_preserves_arc_length_and_orientation(self):
        points = ((0, 0), (1, .1), (2, 0), (0, 1))
        frame, pins = line_constraints(points, ((0, 1, 2),), 'U')
        self.assertAlmostEqual(pins[0][1], pins[1][1])
        self.assertAlmostEqual(pins[1][1], pins[2][1])
        self.assertAlmostEqual(hypot(pins[2][0]-pins[0][0], pins[2][1]-pins[0][1]), 2*hypot(1, .1))
        self.assertLess(pins[0][0], pins[2][0])
        self.assertIn(3, ensure_orientation_anchor(frame, pins))

    def test_reversing_chain_does_not_flip_result(self):
        points = ((0, 0), (.8, .9), (1.8, 2), (0, 2))
        a = line_constraints(points, ((0, 1, 2),), 'AUTO')[1]
        b = line_constraints(points, ((2, 1, 0),), 'AUTO')[1]
        for v in a:
            self.assertAlmostEqual(a[v][0], b[v][0])
            self.assertAlmostEqual(a[v][1], b[v][1])

    def test_constraints_all_collinear_fail_without_offline_vertex(self):
        with self.assertRaises(ValueError):
            ensure_orientation_anchor(((0, 0), (1, 0), (2, 0)), {0: (0, 0), 2: (2, 0)})

    def test_grid_rows_columns_detected_and_jointly_straightened(self):
        points, faces = grid(noise=.01)
        topology = IslandTopology(points, faces)
        chains = find_straight_chains(topology, 10, .01, True)
        self.assertEqual(len(chains), 8)
        frame, pins = line_constraints(points, chains, 'AUTO', False)
        for chain in chains:
            coordinates = [pins[v] for v in chain]
            self.assertTrue(max(p[0] for p in coordinates)-min(p[0] for p in coordinates) < 1e-8 or
                            max(p[1] for p in coordinates)-min(p[1] for p in coordinates) < 1e-8)

    def test_boundary_only_excludes_internal_grid_lines(self):
        points, faces = grid()
        chains = find_straight_chains(IslandTopology(points, faces), include_internal=False)
        self.assertEqual(len(chains), 4)

    def test_threshold_and_scale_invariance(self):
        points, faces = grid(noise=.02)
        topology = IslandTopology(points, faces)
        self.assertEqual(find_straight_chains(topology, 0, 0), ())
        chains = find_straight_chains(topology, 15, .02)
        larger = IslandTopology([(x*10, y*10) for x, y in points], faces)
        self.assertEqual(find_straight_chains(larger, 15, .02), chains)

    def test_dense_circular_border_is_not_a_straight_line(self):
        points = tuple((cos(i*2*pi/120), sin(i*2*pi/120)) for i in range(120))
        topology = IslandTopology(points, (tuple(range(120)),))
        self.assertEqual(find_straight_chains(topology, 10, .01), ())

    def test_keep_direction_does_not_rotate_uv_frame(self):
        points = ((0, 0), (1, 1.02), (2, 2), (-1, 1))
        frame, pins = line_constraints(points, ((0, 1, 2),), 'KEEP')
        for a, b in zip(points, frame):
            self.assertAlmostEqual(a[0], b[0])
            self.assertAlmostEqual(a[1], b[1])

    def test_internal_line_anchors_both_free_sides(self):
        points, faces = grid()
        chains = ((4, 5, 6, 7),)
        frame, pins = line_constraints(points, chains)
        result = ensure_region_anchors(frame, pins, faces, chains)
        self.assertTrue(any(v < 4 for v in result))
        self.assertTrue(any(v >= 8 for v in result))

    def test_joint_triangular_grid_lines_stay_straight_without_axis_snapping(self):
        points, quads = grid(noise=.01)
        faces = tuple(tri for face in quads for tri in (
            (face[0], face[1], face[2]), (face[0], face[2], face[3])))
        chains = find_straight_chains(IslandTopology(points, faces), 10, .02)
        frame, pins = line_constraints(points, chains, 'KEEP', False)
        for chain in chains:
            a, b = pins[chain[0]], pins[chain[-1]]
            for v in chain[1:-1]:
                p = pins[v]
                self.assertAlmostEqual((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]), 0, places=6)

    def test_invalid_coordinates_indices_and_thresholds_rejected(self):
        points, faces = grid()
        invalid = (
            lambda: line_constraints(((float('nan'), 0), (1, 1)), ((0, 1),)),
            lambda: line_constraints(points, ((-1, 0),)),
            lambda: line_constraints(points, ((0, 100),)),
            lambda: find_straight_chains(IslandTopology(points, faces), float('inf')),
        )
        for call in invalid:
            with self.assertRaises(ValueError):
                call()


if __name__ == '__main__':
    unittest.main()
