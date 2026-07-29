import importlib.util
import sys
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
                "ho.placeobjectbottom",
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
