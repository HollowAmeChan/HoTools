import importlib.util
from math import radians
import sys
from types import SimpleNamespace
import unittest
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector


ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

MESH_TOOLS = ADDON_ROOT / "MeshTools"
PACKAGE_NAME = "hotools_mesh_tools_registration_test"


def load_mesh_tools():
    if PACKAGE_NAME in sys.modules:
        return sys.modules[PACKAGE_NAME]
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        MESH_TOOLS / "__init__.py",
        submodule_search_locations=[str(MESH_TOOLS)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


class MeshToolsRegistrationTests(unittest.TestCase):
    def test_edge_constraint_clamps_real_topology_tracks(self):
        mesh_tools = load_mesh_tools()
        operator_type = mesh_tools.TransformEdgeConstrained
        bm = bmesh.new()
        try:
            bottom_left = bm.verts.new((0.0, 0.0, 0.0))
            bottom_right = bm.verts.new((1.0, 0.0, 0.0))
            top_right = bm.verts.new((1.0, 1.0, 0.0))
            top_left = bm.verts.new((0.0, 1.0, 0.0))
            bm.faces.new((bottom_left, bottom_right, top_right, top_left))
            bm.normal_update()

            selected_edge = bm.edges.get((bottom_left, bottom_right))
            selected_edge.select = True
            bottom_left.select = True
            bottom_right.select = True
            sequences = mesh_tools.edge_constraint.get_selected_vert_sequences(
                [bottom_left, bottom_right],
                ensure_seq_len=True,
            )

            op = SimpleNamespace(
                mx=Matrix.Identity(4),
                original_edge_coords=[],
                draw_face_align=False,
            )
            op.data = operator_type.get_data(op, bm, sequences)
            op.rotation = Quaternion((0.0, 0.0, 1.0), radians(100.0))
            op.origin = Vector((0.5, 0.0, 0.0))
            op.origin_dir = Vector((0.0, 0.0, 1.0))
            op.init_intersection = Vector((1.5, 0.0, 0.0))
            op.scale = Vector((1.0, 0.0, 0.0))
            op.transform_mode = 'ROTATE'
            op.constrain_mode = 'DIRECT_PLANE_INTERSECTION'
            op.is_zero_scaling = False
            op.individual_origins = False
            op.end_align = True
            op.face_align = False
            op.slide_coords = []
            op.draw_end_align = False

            bmesh.ops.rotate(
                bm,
                cent=op.origin,
                matrix=op.rotation.to_matrix(),
                verts=[bottom_left, bottom_right],
            )
            op.tdata = operator_type.get_transformed_data(op)

            candidates_outside_tracks = 0
            fallback_keys = (
                'direct_plane_intersection_co',
                'projected_plane_intersection_co',
                'direct_co',
                'proximity_co',
            )
            for selection in op.tdata.values():
                for vert in selection['verts']:
                    data = selection[vert]
                    segment = data['edge_segment']
                    self.assertIsNotNone(segment)
                    candidate = next(
                        data[key] for key in fallback_keys if data[key] is not None
                    )
                    direction = segment[1] - segment[0]
                    factor = (
                        (candidate - segment[0]).dot(direction)
                        / direction.length_squared
                    )
                    if factor < 0.0 or factor > 1.0:
                        candidates_outside_tracks += 1

            self.assertGreater(candidates_outside_tracks, 0)
            operator_type.constrain_verts_to_edges(op)

            for selection in op.tdata.values():
                for vert in selection['verts']:
                    segment = selection[vert]['edge_segment']
                    clamped = mesh_tools.edge_constraint.clamp_point_to_segment(
                        vert.co,
                        segment,
                    )
                    self.assertLess((vert.co - clamped).length, 1e-6)
        finally:
            bm.free()

    def test_registers_and_unregisters_all_edit_mesh_tools(self):
        mesh_tools = load_mesh_tools()
        mesh_tools.register()
        try:
            registered_ids = {
                cls.bl_idname
                for cls in mesh_tools.cls
                if issubclass(cls, bpy.types.Operator)
            }
            self.assertEqual(registered_ids, {
                "ho.auto_place_object_bottom",
                "ho.auto_snap_face_orthogonal",
                "ho.placeobjectbottom",
                "ho.snap_selected_face_orthogonal",
                "ho.align_to_avg_normal",
                "ho.create_bone_chain_by_meshflow",
                "ho.modal_fill_mesh_hole",
                "ho.transform_edge_constrained",
                "ho.visual_boolean_cut",
            })
            self.assertIsNotNone(
                getattr(
                    bpy.types,
                    mesh_tools.VIEW3D_MT_edit_mesh_hotools.__name__,
                    None,
                )
            )
            class RecordingLayout:
                def __init__(self):
                    self.menu_ids = []
                    self.operator_ids = []
                    self.property_ids = []

                def menu(self, menu_id):
                    self.menu_ids.append(menu_id)

                def prop(self, data, property_id, **kwargs):
                    self.property_ids.append(property_id)
                    return None

                def operator(self, operator_id, **kwargs):
                    self.operator_ids.append(operator_id)
                    return SimpleNamespace()

            callback_layout = RecordingLayout()
            mesh_tools.draw_in_VIEW3D_MT_edit_mesh_context_menu(
                SimpleNamespace(layout=callback_layout),
                bpy.context,
            )
            self.assertEqual(
                callback_layout.menu_ids,
                ["VIEW3D_MT_edit_mesh_hotools"],
            )

            menu_layout = RecordingLayout()
            mesh_tools.VIEW3D_MT_edit_mesh_hotools.draw(
                SimpleNamespace(layout=menu_layout),
                bpy.context,
            )
            self.assertIn(
                "ho.auto_place_object_bottom",
                menu_layout.operator_ids,
            )
            self.assertIn(
                "ho.placeobjectbottom",
                menu_layout.operator_ids,
            )
            self.assertIn(
                "ho.auto_snap_face_orthogonal",
                menu_layout.operator_ids,
            )
            self.assertIn(
                "ho.snap_selected_face_orthogonal",
                menu_layout.operator_ids,
            )
            self.assertIn(
                "ho.transform_edge_constrained",
                menu_layout.operator_ids,
            )
            keymap_items = [
                keymap_item
                for _, keymap_item in mesh_tools.addon_keymaps
                if keymap_item.idname == "ho.transform_edge_constrained"
            ]
            self.assertEqual(len(keymap_items), 1)
            self.assertEqual(keymap_items[0].type, 'R')
            self.assertTrue(keymap_items[0].alt)
            segment = (Vector((0.0, 0.0, 0.0)), Vector((2.0, 0.0, 0.0)))
            clamped = mesh_tools.edge_constraint.clamp_point_to_segment(
                Vector((5.0, 0.0, 0.0)),
                segment,
            )
            self.assertLess((clamped - segment[1]).length, 1e-6)
            clamped = mesh_tools.edge_constraint.clamp_point_to_segment(
                Vector((-3.0, 0.0, 0.0)),
                segment,
            )
            self.assertLess((clamped - segment[0]).length, 1e-6)
            self.assertEqual(menu_layout.property_ids, [])

            operator_layout = RecordingLayout()
            mesh_tools.OP_AutoPlaceObjectBottom.draw(
                SimpleNamespace(layout=operator_layout),
                bpy.context,
            )
            self.assertEqual(
                operator_layout.property_ids,
                ["keep_origin_transform"],
            )
            manual_operator_layout = RecordingLayout()
            mesh_tools.OP_PlaceObjectBottom.draw(
                SimpleNamespace(layout=manual_operator_layout),
                bpy.context,
            )
            self.assertEqual(
                manual_operator_layout.property_ids,
                ["keep_origin_transform"],
            )
            auto_snap_layout = RecordingLayout()
            mesh_tools.OP_AutoSnapFaceOrthogonal.draw(
                SimpleNamespace(layout=auto_snap_layout),
                bpy.context,
            )
            self.assertEqual(
                auto_snap_layout.property_ids,
                ["keep_origin_transform"],
            )
            selected_snap_layout = RecordingLayout()
            mesh_tools.OP_SnapSelectedFaceOrthogonal.draw(
                SimpleNamespace(layout=selected_snap_layout),
                bpy.context,
            )
            self.assertEqual(
                selected_snap_layout.property_ids,
                ["keep_origin_transform"],
            )

            poll_context = SimpleNamespace(
                area=SimpleNamespace(type='VIEW_3D'),
                active_object=SimpleNamespace(type='MESH'),
                mode='OBJECT',
            )
            self.assertFalse(
                mesh_tools.OP_AutoPlaceObjectBottom.poll(poll_context)
            )
            self.assertFalse(
                mesh_tools.OP_AutoSnapFaceOrthogonal.poll(poll_context)
            )
            poll_context.mode = 'EDIT_MESH'
            self.assertTrue(
                mesh_tools.OP_AutoPlaceObjectBottom.poll(poll_context)
            )
            self.assertTrue(
                mesh_tools.OP_AutoSnapFaceOrthogonal.poll(poll_context)
            )
        finally:
            mesh_tools.unregister()

        self.assertIsNone(
            getattr(
                bpy.types,
                mesh_tools.VIEW3D_MT_edit_mesh_hotools.__name__,
                None,
            )
        )
        self.assertEqual(mesh_tools.addon_keymaps, [])


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        MeshToolsRegistrationTests
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
