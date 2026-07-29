import importlib.util
import sys
from types import SimpleNamespace
import unittest
from pathlib import Path

import bpy


MESH_TOOLS = Path(__file__).resolve().parents[1] / "MeshTools"
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


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        MeshToolsRegistrationTests
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
