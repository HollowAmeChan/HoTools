import importlib
import math
import os
import sys
import unittest

import numpy as np


PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
PACKAGE_DIR = os.environ.get(
    "HOTOOLS_NATIVE_TEST_DIR",
    os.path.join(PLUGIN_ROOT, "_Lib", PY_LIB, "HotoolsPackage"),
)
if PACKAGE_DIR not in sys.path:
    sys.path.insert(0, PACKAGE_DIR)


def cube(origin, size=1.0):
    ox, oy, oz = origin
    vertices = np.asarray(
        [
            [ox, oy, oz],
            [ox + size, oy, oz],
            [ox + size, oy + size, oz],
            [ox, oy + size, oz],
            [ox, oy, oz + size],
            [ox + size, oy, oz + size],
            [ox + size, oy + size, oz + size],
            [ox, oy + size, oz + size],
        ],
        dtype=np.float64,
    )
    polygons = [
        [0, 3, 2, 1],
        [4, 5, 6, 7],
        [0, 1, 5, 4],
        [1, 2, 6, 5],
        [2, 3, 7, 6],
        [3, 0, 4, 7],
    ]
    return vertices, polygons


def pentagonal_prism():
    ring = [
        (math.cos(2.0 * math.pi * index / 5.0),
         math.sin(2.0 * math.pi * index / 5.0))
        for index in range(5)
    ]
    vertices = np.asarray(
        [(x, y, 0.0) for x, y in ring] + [(x, y, 1.0) for x, y in ring],
        dtype=np.float64,
    )
    polygons = [list(reversed(range(5))), list(range(5, 10))]
    polygons.extend(
        [[index, (index + 1) % 5, (index + 1) % 5 + 5, index + 5]
         for index in range(5)]
    )
    return vertices, polygons


def combine_meshes(meshes):
    vertices = []
    polygons = []
    vertex_base = 0
    for mesh_vertices, mesh_polygons in meshes:
        vertices.append(mesh_vertices)
        polygons.extend(
            [[index + vertex_base for index in polygon] for polygon in mesh_polygons]
        )
        vertex_base += len(mesh_vertices)

    triangles = []
    triangle_polygons = []
    flat_polygons = []
    offsets = [0]
    for polygon_index, polygon in enumerate(polygons):
        flat_polygons.extend(polygon)
        offsets.append(len(flat_polygons))
        for corner in range(1, len(polygon) - 1):
            triangles.append([polygon[0], polygon[corner], polygon[corner + 1]])
            triangle_polygons.append(polygon_index)

    return (
        np.ascontiguousarray(np.concatenate(vertices), dtype=np.float64),
        np.ascontiguousarray(triangles, dtype=np.int32),
        np.ascontiguousarray(triangle_polygons, dtype=np.int32),
        np.ascontiguousarray(flat_polygons, dtype=np.int32),
        np.ascontiguousarray(offsets, dtype=np.int32),
    )


def unpack_faces(result):
    indices = result["face_vertices"]
    offsets = result["face_offsets"]
    return [indices[offsets[i]:offsets[i + 1]] for i in range(len(offsets) - 1)]


def signed_volume(vertices, faces):
    volume = 0.0
    for face in faces:
        a = vertices[face[0]]
        for corner in range(1, len(face) - 1):
            b = vertices[face[corner]]
            c = vertices[face[corner + 1]]
            volume += np.dot(a, np.cross(b, c)) / 6.0
    return volume


class OuterHullTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.native = importlib.import_module("hotools_boolean")
        except ImportError as exc:
            raise unittest.SkipTest(f"hotools_boolean is not built: {exc}")

    def test_untouched_cube_restores_quads(self):
        result = self.native.outer_hull(*combine_meshes([cube((0, 0, 0))]))
        faces = unpack_faces(result)
        self.assertEqual(result["restored_polygons"], 6)
        self.assertEqual(result["seam_triangles"], 0)
        self.assertEqual([len(face) for face in faces], [4] * 6)
        self.assertAlmostEqual(
            abs(signed_volume(result["vertices"], faces)), 1.0, places=9
        )

    def test_nested_shell_is_removed(self):
        result = self.native.outer_hull(
            *combine_meshes([cube((0, 0, 0), 3.0), cube((1, 1, 1), 1.0)])
        )
        faces = unpack_faces(result)
        self.assertEqual(len(faces), 6)
        self.assertTrue(all(len(face) == 4 for face in faces))
        self.assertTrue(np.all(result["face_sources"] < 6))
        self.assertAlmostEqual(
            abs(signed_volume(result["vertices"], faces)), 27.0, places=8
        )

    def test_untouched_ngons_are_restored(self):
        result = self.native.outer_hull(*combine_meshes([pentagonal_prism()]))
        face_sizes = sorted(len(face) for face in unpack_faces(result))
        self.assertEqual(result["restored_polygons"], 7)
        self.assertEqual(result["seam_triangles"], 0)
        self.assertEqual(face_sizes, [4, 4, 4, 4, 4, 5, 5])

    def test_intersecting_cubes_produce_union_volume(self):
        result = self.native.outer_hull(
            *combine_meshes([cube((0, 0, 0)), cube((0.5, 0.5, 0.5))])
        )
        faces = unpack_faces(result)
        self.assertGreater(result["restored_polygons"], 0)
        self.assertGreater(result["seam_triangles"], 0)
        self.assertAlmostEqual(
            abs(signed_volume(result["vertices"], faces)), 1.875, places=8
        )


if __name__ == "__main__":
    unittest.main()
