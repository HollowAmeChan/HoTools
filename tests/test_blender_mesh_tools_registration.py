import importlib.util
from math import radians
import sys
from types import MethodType, SimpleNamespace
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
        operator_type = mesh_tools.OP_TransformEdgeConstrained
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
                "ho.align",
                "ho.align_relative",
                "ho.auto_place_object_bottom",
                "ho.auto_snap_face_orthogonal",
                "ho.placeobjectbottom",
                "ho.snap_selected_face_orthogonal",
                "ho.align_to_avg_normal",
                "ho.create_bone_chain_by_meshflow",
                "ho.modal_fill_mesh_hole",
                "ho.transform_edge_constrained",
                "ho.symmetrize",
                "ho.select",
                "ho.vselect",
                "ho.sselect",
                "ho.lselect",
                "ho.fill_selection",
                "ho.addselect_sideringloops",
                "ho.removeselect_sideringloops",
                "ho.visual_boolean_cut",
                "ho.curve_bevel",
                "ho.repair_curve_path",
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

                def separator(self):
                    return None

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
            self.assertNotIn("ho.symmetrize", menu_layout.operator_ids)
            keymap_items = [
                keymap_item
                for _, keymap_item in mesh_tools.addon_keymaps
                if keymap_item.idname == "ho.transform_edge_constrained"
            ]
            self.assertEqual(len(keymap_items), 1)
            self.assertEqual(keymap_items[0].type, 'R')
            self.assertTrue(keymap_items[0].alt)
            symmetrize_keymaps = [
                (keymap, keymap_item)
                for keymap, keymap_item in mesh_tools.addon_keymaps
                if keymap_item.idname == "ho.symmetrize"
            ]
            self.assertEqual(len(symmetrize_keymaps), 2)
            symmetrize_keymaps_by_name = {
                keymap.name: keymap_item
                for keymap, keymap_item in symmetrize_keymaps
            }
            self.assertEqual(set(symmetrize_keymaps_by_name), {"Mesh", "Curve"})
            for keymap_item in symmetrize_keymaps_by_name.values():
                self.assertEqual(keymap_item.type, 'X')
                self.assertTrue(keymap_item.alt)
            selection_keymaps = {
                keymap_item.idname: (keymap.name, keymap_item)
                for keymap, keymap_item in mesh_tools.addon_keymaps
                if keymap_item.idname in {
                    "ho.fill_selection",
                    "ho.addselect_sideringloops",
                    "ho.removeselect_sideringloops",
                }
            }
            self.assertEqual(
                set(selection_keymaps),
                {
                    "ho.fill_selection",
                    "ho.addselect_sideringloops",
                    "ho.removeselect_sideringloops",
                },
            )
            self.assertEqual(selection_keymaps["ho.fill_selection"][0], "Window")
            self.assertEqual(selection_keymaps["ho.fill_selection"][1].type, 'RIGHTMOUSE')
            self.assertTrue(selection_keymaps["ho.fill_selection"][1].ctrl)
            self.assertTrue(selection_keymaps["ho.fill_selection"][1].shift)
            self.assertEqual(selection_keymaps["ho.addselect_sideringloops"][1].type, 'NUMPAD_PLUS')
            self.assertEqual(selection_keymaps["ho.removeselect_sideringloops"][1].type, 'NUMPAD_MINUS')
            align_keymaps = {
                keymap.name: keymap_item
                for keymap, keymap_item in mesh_tools.addon_keymaps
                if keymap_item.idname == "ho.align"
            }
            self.assertEqual(set(align_keymaps), {"Object Mode", "Pose"})
            for keymap_item in align_keymaps.values():
                self.assertEqual(keymap_item.type, 'A')
                self.assertTrue(keymap_item.alt)
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

            curve_menu_layout = RecordingLayout()
            mesh_tools.HO_MT_curve.draw(
                SimpleNamespace(layout=curve_menu_layout),
                SimpleNamespace(active_object=SimpleNamespace(type='CURVE')),
            )
            self.assertEqual(
                curve_menu_layout.operator_ids,
                ["ho.repair_curve_path"],
            )
            curve_context_layout = RecordingLayout()
            mesh_tools.draw_in_VIEW3D_MT_edit_curve_context_menu(
                SimpleNamespace(layout=curve_context_layout),
                SimpleNamespace(active_object=SimpleNamespace(type='CURVE')),
            )
            self.assertEqual(curve_context_layout.menu_ids, ["HO_MT_curve"])

            curve_keymaps = [
                (keymap, keymap_item)
                for keymap, keymap_item in mesh_tools.preference_keymaps()
                if keymap_item.idname == "ho.curve_bevel"
            ]
            self.assertEqual(len(curve_keymaps), 1)
            curve_keymap, curve_keymap_item = curve_keymaps[0]
            self.assertEqual(curve_keymap.name, "Curve")
            self.assertEqual(curve_keymap.space_type, "EMPTY")
            self.assertEqual(curve_keymap_item.type, "B")
            self.assertTrue(curve_keymap_item.ctrl)
            self.assertEqual(curve_keymap.keymap_items[0].id, curve_keymap_item.id)

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

    def test_curve_repair_restores_configured_nurbs_path_order(self):
        mesh_tools = load_mesh_tools()
        mesh_tools.register()
        curve = bpy.data.curves.new("CurveRepairTest", "CURVE")
        curve.dimensions = "3D"
        spline = curve.splines.new("NURBS")
        spline.points.add(3)
        for point, coordinate in zip(
            spline.points,
            ((0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 0.0, 0.0), (3.0, 1.0, 0.0)),
        ):
            point.co = (*coordinate, 1.0)
        spline.order_u = 4
        obj = bpy.data.objects.new("CurveRepairObject", curve)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        try:
            result, count = mesh_tools.curve_repair.repair_curve(obj)
            self.assertEqual(result, "INSUFFICIENT_POINTS")
            self.assertEqual(count, 4)
            self.assertEqual(len(curve.splines[0].points), 4)
            result, count = mesh_tools.curve_repair.repair_curve(obj, order_u=4)
            self.assertEqual(result, "FINISHED")
            self.assertEqual(count, 4)
            self.assertEqual(curve.splines[0].order_u, 4)
        finally:
            bpy.data.objects.remove(obj, do_unlink=True)
            mesh_tools.unregister()

    def test_curve_symmetrize_mirrors_bezier_controls_and_handles(self):
        mesh_tools = load_mesh_tools()
        mesh_tools.register()
        curve = bpy.data.curves.new("CurveSymmetrizeTest", "CURVE")
        curve.dimensions = "3D"
        spline = curve.splines.new("BEZIER")
        spline.bezier_points.add(3)
        coordinates = (
            (-2.0, 1.0, 0.0),
            (-1.0, 0.0, 0.0),
            (1.0, 0.5, 0.0),
            (2.0, 1.0, 0.0),
        )
        for point, coordinate in zip(spline.bezier_points, coordinates):
            point.co = coordinate
            point.handle_left_type = "FREE"
            point.handle_right_type = "FREE"
        spline.bezier_points[2].co = (1.0, 0.75, 0.0)
        spline.bezier_points[2].handle_left = (0.5, 0.25, 0.0)
        spline.bezier_points[2].handle_right = (1.5, 1.25, 0.0)
        obj = bpy.data.objects.new("CurveSymmetrizeObject", curve)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            self.assertEqual(len(obj.data.splines), 1)
            self.assertEqual(len(obj.data.splines[0].bezier_points), 4)
            result = mesh_tools.symmetrize._curve_symmetrize(
                obj,
                direction="POSITIVE_X",
                threshold=0.0001,
                partial=False,
                remove=False,
            )
            self.assertTrue(result["curve"])
            bpy.ops.object.mode_set(mode="OBJECT")
            mirrored = obj.data.splines[0].bezier_points[1]
            self.assertLess((mirrored.co - Vector((-1.0, 0.75, 0.0))).length, 1e-6)
            self.assertLess(
                (mirrored.handle_left - Vector((-1.5, 1.25, 0.0))).length,
                1e-6,
            )
            self.assertLess(
                (mirrored.handle_right - Vector((-0.5, 0.25, 0.0))).length,
                1e-6,
            )
        finally:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.data.objects.remove(obj, do_unlink=True)
            mesh_tools.unregister()

    def test_curve_symmetrize_creates_mirror_for_single_sided_path(self):
        mesh_tools = load_mesh_tools()
        mesh_tools.register()
        curve = bpy.data.curves.new("PathSymmetrizeTest", "CURVE")
        curve.dimensions = "3D"
        spline = curve.splines.new("POLY")
        spline.points.add(2)
        for point, coordinate in zip(
            spline.points,
            ((1.0, -1.0, 0.0), (2.0, 0.0, 0.0), (3.0, 1.0, 0.0)),
        ):
            point.co = (*coordinate, 1.0)
        obj = bpy.data.objects.new("PathSymmetrizeObject", curve)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            result = mesh_tools.symmetrize._curve_symmetrize(
                obj,
                direction="POSITIVE_X",
                threshold=0.0001,
                partial=False,
                remove=False,
            )
            self.assertTrue(result["curve"])
            bpy.ops.object.mode_set(mode="OBJECT")
            self.assertEqual(len(obj.data.splines), 2)
            mirrored = obj.data.splines[1]
            coordinates = [point.co.xyz.copy() for point in mirrored.points]
            self.assertEqual(
                [tuple(round(value, 6) for value in coordinate) for coordinate in coordinates],
                [(-3.0, 1.0, 0.0), (-2.0, 0.0, 0.0), (-1.0, -1.0, 0.0)],
            )
        finally:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.data.objects.remove(obj, do_unlink=True)
            mesh_tools.unregister()

    def test_curve_symmetrize_preserves_nurbs_order_on_mirrored_path(self):
        mesh_tools = load_mesh_tools()
        mesh_tools.register()
        curve = bpy.data.curves.new("NurbsPathSymmetrizeTest", "CURVE")
        curve.dimensions = "3D"
        spline = curve.splines.new("NURBS")
        spline.points.add(4)
        spline.order_u = 5
        spline.use_endpoint_u = True
        spline.resolution_u = 16
        for point, coordinate in zip(
            spline.points,
            ((1.0, -2.0, 0.0), (2.0, -1.0, 0.0), (3.0, 0.0, 0.0),
             (4.0, 1.0, 0.0), (5.0, 2.0, 0.0)),
        ):
            point.co = (*coordinate, 1.0)
        obj = bpy.data.objects.new("NurbsPathSymmetrizeObject", curve)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            result = mesh_tools.symmetrize._curve_symmetrize(
                obj,
                direction="POSITIVE_X",
                threshold=0.0001,
                partial=False,
                remove=False,
            )
            self.assertTrue(result["curve"])
            bpy.ops.object.mode_set(mode="OBJECT")
            self.assertEqual(len(curve.splines), 2)
            mirrored = curve.splines[1]
            self.assertEqual(mirrored.type, "NURBS")
            self.assertEqual(mirrored.order_u, 5)
            self.assertTrue(mirrored.use_endpoint_u)
            self.assertEqual(mirrored.resolution_u, 16)
        finally:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.data.objects.remove(obj, do_unlink=True)
            mesh_tools.unregister()

    def test_curve_repair_repairs_all_path_splines(self):
        mesh_tools = load_mesh_tools()
        mesh_tools.register()
        curve = bpy.data.curves.new("MultiPathRepairTest", "CURVE")
        curve.dimensions = "3D"
        for offset in (0.0, 10.0):
            spline = curve.splines.new("NURBS")
            spline.points.add(4)
            for index, point in enumerate(spline.points):
                point.co = (offset + index + 1.0, float(index), 0.0, 1.0)
        obj = bpy.data.objects.new("MultiPathRepairObject", curve)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        try:
            result, count = mesh_tools.curve_repair.repair_curve(obj, order_u=5)
            self.assertEqual(result, "FINISHED")
            self.assertEqual(count, 5)
            self.assertEqual([spline.order_u for spline in curve.splines], [5, 5])
            self.assertTrue(all(spline.use_endpoint_u for spline in curve.splines))
        finally:
            bpy.data.objects.remove(obj, do_unlink=True)
            mesh_tools.unregister()

    def test_curve_bevel_chamfers_selected_control_points(self):
        mesh_tools = load_mesh_tools()
        mesh_tools.register()
        curve = bpy.data.curves.new("CurveBevelTest", "CURVE")
        curve.dimensions = "3D"
        spline = curve.splines.new("NURBS")
        spline.points.add(2)
        spline.order_u = 3
        spline.use_endpoint_u = True
        for point, coordinate in zip(
                spline.points,
                ((0.0, 0.0, 0.0), (2.0, 2.0, 0.0), (4.0, 0.0, 0.0))):
            point.co = (*coordinate, 1.0)
            point.select = coordinate == (2.0, 2.0, 0.0)
        obj = bpy.data.objects.new("CurveBevelObject", curve)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            self.assertEqual(
                bpy.ops.ho.curve_bevel(width=1.0, segments=1),
                {"FINISHED"},
            )
            bpy.ops.object.mode_set(mode="OBJECT")
            self.assertEqual(len(curve.splines[0].points), 4)
            coordinates = [point.co.xyz.copy() for point in curve.splines[0].points]
            self.assertLess(
                (coordinates[1] - Vector((1.2928932, 1.2928932, 0.0))).length,
                1e-6,
            )
            self.assertLess(
                (coordinates[2] - Vector((2.7071068, 1.2928932, 0.0))).length,
                1e-6,
            )
            self.assertTrue(curve.splines[0].points[1].select)
            self.assertTrue(curve.splines[0].points[2].select)
        finally:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.data.objects.remove(obj, do_unlink=True)
            mesh_tools.unregister()

    def test_curve_bevel_rounds_bezier_control_points(self):
        mesh_tools = load_mesh_tools()
        mesh_tools.register()
        curve = bpy.data.curves.new("BezierBevelTest", "CURVE")
        curve.dimensions = "3D"
        spline = curve.splines.new("BEZIER")
        spline.bezier_points.add(2)
        for point, coordinate in zip(
                spline.bezier_points,
                ((0.0, 0.0, 0.0), (2.0, 2.0, 0.0), (4.0, 0.0, 0.0))):
            point.co = coordinate
            point.handle_left_type = "VECTOR"
            point.handle_right_type = "VECTOR"
            point.select_control_point = coordinate == (2.0, 2.0, 0.0)
        obj = bpy.data.objects.new("BezierBevelObject", curve)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            self.assertEqual(
                bpy.ops.ho.curve_bevel(width=1.0, segments=3),
                {"FINISHED"},
            )
            bpy.ops.object.mode_set(mode="OBJECT")
            self.assertEqual(len(curve.splines[0].bezier_points), 6)
            generated = curve.splines[0].bezier_points[1:-1]
            self.assertTrue(all(point.select_control_point for point in generated))
            self.assertTrue(all(point.handle_left_type == "AUTO" for point in generated))
            self.assertTrue(all(point.handle_right_type == "AUTO" for point in generated))
        finally:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.data.objects.remove(obj, do_unlink=True)
            mesh_tools.unregister()

    def test_curve_bevel_modal_wheel_and_cancel_restore_original(self):
        mesh_tools = load_mesh_tools()
        mesh_tools.register()
        curve = bpy.data.curves.new("CurveBevelModalTest", "CURVE")
        curve.dimensions = "3D"
        spline = curve.splines.new("NURBS")
        spline.points.add(2)
        spline.order_u = 3
        spline.use_endpoint_u = True
        for point, coordinate in zip(
                spline.points,
                ((0.0, 0.0, 0.0), (2.0, 2.0, 0.0), (4.0, 0.0, 0.0))):
            point.co = (*coordinate, 1.0)
            point.select = coordinate == (2.0, 2.0, 0.0)
        obj = bpy.data.objects.new("CurveBevelModalObject", curve)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        class Area:
            def __init__(self):
                self.header = None

            def header_text_set(self, text):
                self.header = text

            def tag_redraw(self):
                return None

        try:
            bpy.ops.object.mode_set(mode="EDIT")
            operator = SimpleNamespace(width=0.75, segments=1)
            for method_name in (
                    "_apply",
                    "_update_preview",
                    "_restore_original",
                    "_update_header",
                    "_finish"):
                setattr(
                    operator,
                    method_name,
                    MethodType(
                        getattr(mesh_tools.OP_CurveBevel, method_name),
                        operator,
                    ),
                )
            operator._curve_snapshot = mesh_tools.curve_bevel._snapshot_curve(curve)
            operator._preview_changed = False
            context = SimpleNamespace(active_object=obj, area=Area())

            result = mesh_tools.OP_CurveBevel.modal(
                operator,
                context,
                SimpleNamespace(type="WHEELUPMOUSE", value="PRESS"),
            )
            self.assertEqual(result, {"RUNNING_MODAL"})
            self.assertEqual(operator.segments, 2)
            self.assertEqual(len(curve.splines[0].points), 5)
            self.assertIn("段数: 2", context.area.header)

            result = mesh_tools.OP_CurveBevel.modal(
                operator,
                context,
                SimpleNamespace(type="ESC", value="PRESS"),
            )
            self.assertEqual(result, {"CANCELLED"})
            self.assertEqual(len(curve.splines[0].points), 3)
            self.assertEqual(context.area.header, None)
            self.assertTrue(curve.splines[0].points[1].select)
            self.assertEqual(curve.splines[0].type, "NURBS")
            self.assertEqual(curve.splines[0].order_u, 3)
            self.assertTrue(curve.splines[0].use_endpoint_u)
            self.assertEqual(curve.splines.active, curve.splines[0])
        finally:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.data.objects.remove(obj, do_unlink=True)
            mesh_tools.unregister()


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        MeshToolsRegistrationTests
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
