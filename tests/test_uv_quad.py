"""Exact quad rows, strip metrics and UV pose without Blender dependencies."""

import sys
import unittest
from math import cos, hypot, sin
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Utils.uv_quad import QuadLayoutError, quad_lattice, quadrify_coordinates
from Utils.uv_topology import IslandTopology


def make_grid(width=4, height=4, faces_filter=None, reverse=False):
    mesh = tuple((x, y) for y in range(height) for x in range(width))
    uv = tuple((x+.035*y*y, y+.18*x*x) for x, y in mesh)
    faces = [(y*width+x, y*width+x+1, (y+1)*width+x+1, (y+1)*width+x)
             for y in range(height-1) for x in range(width-1) if faces_filter is None or faces_filter(x, y)]
    if reverse:
        faces = [face[::-1] if i % 2 else face for i, face in enumerate(faces)]
    used = sorted({v for face in faces for v in face})
    remap = {v: i for i, v in enumerate(used)}
    topology = IslandTopology([uv[v] for v in used], [tuple(remap[v] for v in face) for face in faces])
    mesh = tuple(mesh[v] for v in used)
    lengths = {edge: hypot(mesh[edge[1]][0]-mesh[edge[0]][0], mesh[edge[1]][1]-mesh[edge[0]][1])
               for edge in topology.edge_faces}
    return topology, mesh, lengths


def area(points):
    return sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(points, points[1:]+points[:1]))/2


class QuadTests(unittest.TestCase):
    def assert_rectangles(self, topology, result):
        for face in topology.polygons:
            a, b, c, d = [result[v] for v in face]
            e, f = (b[0]-a[0], b[1]-a[1]), (d[0]-a[0], d[1]-a[1])
            self.assertAlmostEqual(e[0]*f[0]+e[1]*f[1], 0, places=8)
            self.assertAlmostEqual(c[0], b[0]+d[0]-a[0], places=8)
            self.assertAlmostEqual(c[1], b[1]+d[1]-a[1], places=8)
            self.assertGreater(area([topology.coordinates[v] for v in face])*area([result[v] for v in face]), 0)

    def test_curved_rows_become_exact_rectangles_without_angle_threshold(self):
        topology, mesh, lengths = make_grid()
        result = quadrify_coordinates(topology, lengths, direction='AUTO')
        self.assert_rectangles(topology, result)
        for y in range(4):
            self.assertEqual(len({result[y*4+x][1] for x in range(4)}), 1)
        for x in range(4):
            self.assertEqual(len({result[y*4+x][0] for y in range(4)}), 1)

    def test_area_center_rotation_and_mirror_are_preserved(self):
        base, mesh, lengths = make_grid()
        for reflected in (False, True):
            sign = -1 if reflected else 1
            c, s = cos(.55), sin(.55)
            coordinates = tuple((7+c*x-s*sign*y, -3+s*x+c*sign*y) for x, y in base.coordinates)
            topology = IslandTopology(coordinates, base.polygons)
            result = quadrify_coordinates(topology, lengths)
            self.assert_rectangles(topology, result)
            self.assertAlmostEqual(sum(abs(area([coordinates[v] for v in f])) for f in topology.polygons),
                                   sum(abs(area([result[v] for v in f])) for f in topology.polygons), places=8)
            for axis in (0, 1):
                self.assertAlmostEqual(sum(p[axis] for p in coordinates), sum(p[axis] for p in result), places=8)

    def test_3d_interval_ratios_use_average_of_opposite_edge_strips(self):
        topology, mesh, lengths = make_grid()
        for (a, b) in lengths:
            if mesh[a][0] != mesh[b][0]:
                lengths[(a, b)] = (1, 2, 3)[int(min(mesh[a][0], mesh[b][0]))]*(1+.1*mesh[a][1])
        result = quadrify_coordinates(topology, lengths, direction='AUTO')
        widths = [hypot(result[i+1][0]-result[i][0], result[i+1][1]-result[i][1]) for i in range(3)]
        self.assertAlmostEqual(widths[1]/widths[0], 2)
        self.assertAlmostEqual(widths[2]/widths[0], 3)
        self.assert_rectangles(topology, result)

    def test_seed_face_and_reversed_face_winding_are_supported(self):
        topology, mesh, lengths = make_grid(reverse=True)
        for seed in range(len(topology.polygons)):
            result = quadrify_coordinates(topology, lengths, seed, 'AUTO')
            self.assert_rectangles(topology, result)

    def test_holes_and_l_shaped_quad_charts_keep_their_topology(self):
        for predicate in (lambda x, y: x == 0 or y == 0,
                          lambda x, y: not (x in (1, 2) and y in (1, 2))):
            topology, mesh, lengths = make_grid(5, 5, predicate)
            result = quadrify_coordinates(topology, lengths, direction='AUTO')
            self.assertEqual(len(result), len(topology.coordinates))
            self.assert_rectangles(topology, result)

    def test_single_quad_is_rectified(self):
        coordinates = ((0, 0), (3, .2), (2.8, 1.2), (.1, 1))
        topology = IslandTopology(coordinates, ((0, 1, 2, 3),))
        lengths = {(0, 1): 3, (1, 2): 1, (2, 3): 3, (0, 3): 1}
        result = quadrify_coordinates(topology, lengths)
        self.assert_rectangles(topology, result)
        self.assertAlmostEqual(hypot(result[1][0]-result[0][0], result[1][1]-result[0][1])/
                               hypot(result[3][0]-result[0][0], result[3][1]-result[0][1]), 3)

    def test_single_pin_and_compatible_multiple_pins_remain_exact(self):
        topology, mesh, lengths = make_grid()
        target = topology.coordinates[5]
        result = quadrify_coordinates(topology, lengths, pins={5: target})
        self.assertEqual(result[5], target)
        self.assert_rectangles(topology, result)
        pins = {0: (2, 3), 3: (8, 3), 12: (2, 9)}
        result = quadrify_coordinates(topology, lengths, pins=pins)
        self.assert_rectangles(topology, result)
        for v, point in pins.items():
            self.assertEqual(result[v], point)

    def test_incompatible_pins_are_rejected_instead_of_bending_lines(self):
        topology, mesh, lengths = make_grid()
        with self.assertRaisesRegex(ValueError, '固定点'):
            quadrify_coordinates(topology, lengths, pins={0: (0, 0), 3: (3, 0), 12: (.3, 3)})

    def test_nonquad_and_quad_poles_rejected_explicitly(self):
        with self.assertRaises(QuadLayoutError):
            quad_lattice(IslandTopology(((0, 0), (1, 0), (0, 1)), ((0, 1, 2),)))
        # Three quads meet at one interior pole: cannot become a rectangle grid.
        points = ((0, 0), (1, 0), (.5, .8), (-.5, .8), (-1, 0), (-.5, -.8), (.5, -.8))
        topology = IslandTopology(points, ((0, 1, 2, 3), (0, 3, 4, 5), (0, 5, 6, 1)))
        with self.assertRaises(QuadLayoutError):
            quad_lattice(topology)

    def test_invalid_metrics_and_collapsed_uv_are_rejected(self):
        topology, mesh, lengths = make_grid()
        edge = next(iter(lengths))
        for invalid in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                quadrify_coordinates(topology, lengths | {edge: invalid})
        with self.assertRaises(ValueError):
            quadrify_coordinates(topology, {edge: 0 for edge in lengths})
        collapsed = IslandTopology([(0, 0)]*len(mesh), topology.polygons)
        with self.assertRaises(ValueError):
            quadrify_coordinates(collapsed, lengths)


if __name__ == '__main__':
    unittest.main()
