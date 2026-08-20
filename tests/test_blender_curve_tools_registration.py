"""Blender-level registration and ownership checks for CurveTools."""

import importlib.util
import sys
import unittest
from pathlib import Path

import bpy


ADDON_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "hotools_curve_tools_isolated_test"
CURVE_ROOT = ADDON_ROOT / "CurveTools"


def load_curve_tools():
    if PACKAGE_NAME in sys.modules:
        return sys.modules[PACKAGE_NAME]
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        CURVE_ROOT / "__init__.py",
        submodule_search_locations=[str(CURVE_ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


class CurveToolsRegistrationTests(unittest.TestCase):
    def test_registers_curve_operators_and_shortcuts(self):
        curve_tools = load_curve_tools()
        curve_tools.register()
        try:
            registered_ids = {
                operator_class.bl_idname
                for operator_class in curve_tools._CLASSES
                if issubclass(operator_class, bpy.types.Operator)
            }
            self.assertEqual(
                registered_ids,
                {
                    "ho.curve_bevel",
                    "ho.repair_curve_path",
                    "ho.curve_symmetrize",
                },
            )
            keymap_items = [
                item
                for _, item in curve_tools.addon_keymaps
                if item.idname in {"ho.curve_bevel", "ho.curve_symmetrize"}
            ]
            self.assertEqual(
                {item.idname for item in keymap_items},
                {"ho.curve_bevel", "ho.curve_symmetrize"},
            )
            self.assertTrue(
                curve_tools.OP_Symmetrize.poll(
                    type(
                        "Context",
                        (),
                        {
                            "active_object": type("Object", (), {"type": "CURVE"})(),
                            "area": type("Area", (), {"type": "VIEW_3D"})(),
                            "mode": "EDIT_CURVE",
                        },
                    )()
                )
            )
        finally:
            curve_tools.unregister()
        self.assertEqual(curve_tools.addon_keymaps, [])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
