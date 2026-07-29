import importlib
import math
import sys
import types
import unittest
from pathlib import Path

import bpy
from mathutils import Euler, Vector


MESH_TOOLS = Path(__file__).resolve().parents[1] / "MeshTools"
PACKAGE_NAME = "hotools_auto_placement_test"


def load_modules():
    if PACKAGE_NAME not in sys.modules:
        package = types.ModuleType(PACKAGE_NAME)
        package.__path__ = [str(MESH_TOOLS)]
        sys.modules[PACKAGE_NAME] = package
    auto_placement = importlib.import_module(
        f"{PACKAGE_NAME}.auto_placement"
    )
    placement = importlib.import_module(f"{PACKAGE_NAME}.placement")
    return auto_placement, placement


class AutoPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auto_placement, cls.placement = load_modules()

    def setUp(self):
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)

    def _build_candidates(self, obj):
        return self.auto_placement.build_candidates(
            obj,
            bpy.context.evaluated_depsgraph_get(),
            math.radians(2.5),
            0.002,
            math.radians(12.0),
            0.006,
        )

    def test_transformed_cube_produces_six_planes(self):
        bpy.ops.mesh.primitive_cube_add(location=(2.0, -1.0, 4.0))
        obj = bpy.context.object
        obj.rotation_euler = Euler((0.62, -0.37, 0.91))
        obj.scale = (2.0, 0.65, 1.4)
        bpy.context.view_layer.update()

        candidates = self._build_candidates(obj)
        self.assertEqual(len(candidates), 6)

    def test_place_candidate_preserves_mesh_and_origin_relationship(self):
        bpy.ops.mesh.primitive_cube_add(location=(2.0, -1.0, 4.0))
        obj = bpy.context.object
        obj.rotation_euler = Euler((0.62, -0.37, 0.91))
        obj.scale = (2.0, 0.65, 1.4)
        bpy.context.view_layer.update()
        local_vertices_before = [
            vertex.co.copy()
            for vertex in obj.data.vertices
        ]
        old_world_matrix = obj.matrix_world.copy()

        candidate = self._build_candidates(obj)[0]
        self.placement.place_object_on_ground(
            obj,
            candidate.points,
            candidate.normal,
            bpy.context.view_layer,
        )

        for before, vertex in zip(local_vertices_before, obj.data.vertices):
            self.assertLess((before - vertex.co).length, 1e-8)

        world_delta = obj.matrix_world @ old_world_matrix.inverted_safe()
        placed_normal = (
            world_delta.to_3x3() @ candidate.normal
        ).normalized()
        self.assertGreater(
            placed_normal.dot(Vector((0.0, 0.0, -1.0))),
            0.99999,
        )
        placed_points = [
            world_delta @ point
            for point in candidate.points
        ]
        self.assertLess(
            max(abs(point.z) for point in placed_points),
            1e-5,
        )

    def test_bevelled_cube_filters_small_hull_faces(self):
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.object
        modifier = obj.modifiers.new("Bevel", 'BEVEL')
        modifier.width = 0.18
        modifier.segments = 3
        bpy.context.view_layer.update()

        world_vertices, patches, diagonal = (
            self.auto_placement.evaluated_surface_data(
                obj,
                bpy.context.evaluated_depsgraph_get(),
            )
        )
        raw_candidates = self.auto_placement.convex_hull_candidates(
            world_vertices,
            math.radians(2.5),
        )
        filtered = self.auto_placement.filter_hull_candidates(
            raw_candidates,
            patches,
            diagonal,
            0.002,
            math.radians(12.0),
            0.006,
        )

        self.assertGreater(len(raw_candidates), 6)
        self.assertGreaterEqual(len(filtered), 6)
        self.assertLess(len(filtered), len(raw_candidates))
        axis_aligned = [
            candidate
            for candidate in filtered
            if max(abs(component) for component in candidate.normal) > 0.999
        ]
        self.assertGreaterEqual(len(axis_aligned), 6)

    def test_ray_selects_nearest_candidate(self):
        candidate_type = self.auto_placement.HullFaceCandidate
        near = candidate_type(
            points=[
                Vector((-1.0, -1.0, 1.0)),
                Vector((1.0, -1.0, 1.0)),
                Vector((1.0, 1.0, 1.0)),
                Vector((-1.0, 1.0, 1.0)),
            ],
            normal=Vector((0.0, 0.0, 1.0)),
            area=4.0,
        )
        far = candidate_type(
            points=[
                Vector((-1.0, -1.0, 0.0)),
                Vector((1.0, -1.0, 0.0)),
                Vector((1.0, 1.0, 0.0)),
                Vector((-1.0, 1.0, 0.0)),
            ],
            normal=Vector((0.0, 0.0, 1.0)),
            area=4.0,
        )
        hit_index = self.auto_placement.ray_hit_candidate(
            [far, near],
            Vector((0.0, 0.0, 5.0)),
            Vector((0.0, 0.0, -1.0)),
        )
        self.assertEqual(hit_index, 1)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        AutoPlacementTests
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
