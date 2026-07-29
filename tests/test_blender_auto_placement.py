import importlib
import math
import sys
import types
import unittest
from pathlib import Path

import bpy
import bmesh
from mathutils import Euler, Vector


MESH_TOOLS = Path(__file__).resolve().parents[1] / "MeshTools"
PACKAGE_NAME = "hotools_auto_placement_test"


def load_placement():
    if PACKAGE_NAME not in sys.modules:
        package = types.ModuleType(PACKAGE_NAME)
        package.__path__ = [str(MESH_TOOLS)]
        sys.modules[PACKAGE_NAME] = package
    placement = importlib.import_module(f"{PACKAGE_NAME}.placement")
    return placement


class AutoPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.placement = load_placement()

    def setUp(self):
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)

    def _build_candidates(self, obj):
        return self.placement.build_candidates(
            obj,
            bpy.context.evaluated_depsgraph_get(),
            math.radians(2.5),
            True,
        )

    def test_transformed_cube_produces_six_planes(self):
        bpy.ops.mesh.primitive_cube_add(location=(2.0, -1.0, 4.0))
        obj = bpy.context.object
        obj.rotation_euler = Euler((0.62, -0.37, 0.91))
        obj.scale = (2.0, 0.65, 1.4)
        bpy.context.view_layer.update()

        candidates = self._build_candidates(obj)
        self.assertEqual(len(candidates), 6)

    def test_place_candidate_keeps_origin_transform(self):
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
            bpy.context,
            True,
        )

        self.assertLess(
            sum(
                abs(value)
                for row in (obj.matrix_world - old_world_matrix)
                for value in row
            ),
            1e-7,
        )
        self.assertTrue(any(
            (before - vertex.co).length > 1e-5
            for before, vertex in zip(local_vertices_before, obj.data.vertices)
        ))

        target_world_matrix = self.placement.ground_alignment_matrix(
            old_world_matrix,
            candidate.points,
            candidate.normal,
        )
        world_delta = target_world_matrix @ old_world_matrix.inverted_safe()
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

    def test_bevelled_cube_keeps_every_hull_face(self):
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.object
        modifier = obj.modifiers.new("Bevel", 'BEVEL')
        modifier.width = 0.18
        modifier.segments = 3
        bpy.context.view_layer.update()

        world_vertices, _patches, _diagonal = (
            self.placement.evaluated_surface_data(
                obj,
                bpy.context.evaluated_depsgraph_get(),
                True,
            )
        )
        raw_candidates = self.placement.convex_hull_candidates(
            world_vertices,
            math.radians(2.5),
        )
        built_candidates = self.placement.build_candidates(
            obj,
            bpy.context.evaluated_depsgraph_get(),
            math.radians(2.5),
            True,
        )

        self.assertGreater(len(raw_candidates), 6)
        self.assertEqual(len(built_candidates), len(raw_candidates))
        self.assertEqual(
            sorted(round(candidate.area, 8) for candidate in built_candidates),
            sorted(round(candidate.area, 8) for candidate in raw_candidates),
        )

    def test_candidate_source_can_ignore_modifiers(self):
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.object
        modifier = obj.modifiers.new("Bevel", 'BEVEL')
        modifier.width = 0.18
        modifier.segments = 3
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()

        base_candidates = self.placement.build_candidates(
            obj,
            depsgraph,
            math.radians(2.5),
            False,
        )
        evaluated_candidates = self.placement.build_candidates(
            obj,
            depsgraph,
            math.radians(2.5),
            True,
        )

        self.assertEqual(len(base_candidates), 6)
        self.assertGreater(len(evaluated_candidates), len(base_candidates))

    def test_ray_selects_nearest_candidate(self):
        candidate_type = self.placement.HullFaceCandidate
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
        hit_index = self.placement.ray_hit_candidate(
            [far, near],
            Vector((0.0, 0.0, 5.0)),
            Vector((0.0, 0.0, -1.0)),
        )
        self.assertEqual(hit_index, 1)

    def test_modal_shortcuts_update_hull_settings(self):
        operator = types.SimpleNamespace(
            merge_coplanar=True,
            use_evaluated_mesh=True,
            keep_origin_transform=True,
            coplanar_angle=math.radians(2.5),
            rebuild_count=0,
        )

        def rebuild(_context):
            operator.rebuild_count += 1

        operator._rebuild_candidates = rebuild
        operator._tag_redraw = lambda _context: None
        context = types.SimpleNamespace()

        result = self.placement.OP_AutoPlaceObjectBottom.modal(
            operator,
            context,
            types.SimpleNamespace(type='M', value='PRESS'),
        )
        self.assertEqual(result, {'RUNNING_MODAL'})
        self.assertFalse(operator.merge_coplanar)
        self.assertEqual(operator.rebuild_count, 1)

        self.placement.OP_AutoPlaceObjectBottom.modal(
            operator,
            context,
            types.SimpleNamespace(type='E', value='PRESS'),
        )
        self.assertFalse(operator.use_evaluated_mesh)
        self.assertEqual(operator.rebuild_count, 2)

        self.placement.OP_AutoPlaceObjectBottom.modal(
            operator,
            context,
            types.SimpleNamespace(type='O', value='PRESS'),
        )
        self.assertFalse(operator.keep_origin_transform)
        self.assertEqual(operator.rebuild_count, 2)

        old_angle = operator.coplanar_angle
        self.placement.OP_AutoPlaceObjectBottom.modal(
            operator,
            context,
            types.SimpleNamespace(type='WHEELUPMOUSE', value='PRESS'),
        )
        self.assertTrue(operator.merge_coplanar)
        self.assertAlmostEqual(
            operator.coplanar_angle,
            old_angle + math.radians(0.5),
        )
        self.assertEqual(operator.rebuild_count, 3)

    def test_modal_result_can_execute_from_stored_plane_parameters(self):
        bpy.ops.mesh.primitive_cube_add(location=(1.0, -2.0, 3.0))
        obj = bpy.context.object
        obj.rotation_euler = Euler((0.44, -0.31, 0.72))
        bpy.context.view_layer.update()
        world_matrix_before = obj.matrix_world.copy()
        candidate = self._build_candidates(obj)[0]
        face_center = sum(
            candidate.points,
            Vector((0.0, 0.0, 0.0)),
        ) / len(candidate.points)
        point_local = (
            world_matrix_before.inverted_safe() @ face_center
        )
        normal_local = (
            world_matrix_before.to_3x3().transposed() @ candidate.normal
        ).normalized()

        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        vertices_before = [vert.co.copy() for vert in bm.verts]
        operator = types.SimpleNamespace(
            has_placement_plane=True,
            placement_point_local=point_local,
            placement_normal_local=normal_local,
            keep_origin_transform=True,
        )

        result = self.placement.OP_AutoPlaceObjectBottom.execute(
            operator,
            bpy.context,
        )
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertLess(
            sum(
                abs(value)
                for row in (obj.matrix_world - world_matrix_before)
                for value in row
            ),
            1e-7,
        )
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        self.assertTrue(any(
            (before - vert.co).length > 1e-5
            for before, vert in zip(vertices_before, bm.verts)
        ))


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        AutoPlacementTests
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
