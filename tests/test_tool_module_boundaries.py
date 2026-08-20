"""Regression tests for the HoTools module split.

These tests intentionally use source inspection so they run without Blender and
still catch accidental reintroduction of the legacy registration boundary.
"""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def class_ids(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "bl_idname":
                        if isinstance(item.value, ast.Constant):
                            result[node.name] = item.value.value
    return result


class ToolModuleBoundaryTests(unittest.TestCase):
    def test_legacy_module_is_removed(self):
        self.assertFalse((ROOT / "FastOperators.py").exists())

    def test_modifier_copy_lives_in_modifier_tools(self):
        ids = class_ids(ROOT / "ModifierTools" / "__init__.py")
        self.assertEqual(ids["OP_CopyALL_modifiers_to_selected"], "ho.copyall_modifiers_to_selected")
        source = (ROOT / "ModifierTools" / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("FastOperators", source)

    def test_migrated_operator_ids_have_single_owner(self):
        owners = {
            "OP_RestartBlender": ROOT / "ProjectTools" / "application.py",
            "OP_sync_render_visibility": ROOT / "ProjectTools" / "visibility.py",
            "OP_MeshToImageEmpty": ROOT / "ObjectTools" / "image_reference.py",
            "HO_OT_QuickAddLattice": ROOT / "ObjectTools" / "lattice.py",
            "OP_CustomSplitNormals_Export": ROOT / "MeshTools" / "custom_normals.py",
            "OP_CustomSplitNormals_Import": ROOT / "MeshTools" / "custom_normals.py",
            "OP_MergeOverlapping_VertexNormals": ROOT / "MeshTools" / "normals.py",
        }
        for class_name, path in owners.items():
            self.assertIn(class_name, path.read_text(encoding="utf-8"))

    def test_root_registers_new_modules(self):
        source = (ROOT / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("ProjectTools.register()", source)
        self.assertIn("ObjectTools.register()", source)
        self.assertIn("CurveTools.register()", source)
        self.assertNotIn("FastOperators.register()", source)

    def test_curve_tools_contain_implementations(self):
        for filename in ("bevel.py", "repair.py", "symmetrize.py"):
            source = (ROOT / "CurveTools" / filename).read_text(encoding="utf-8")
            self.assertIn("class ", source)
            self.assertNotIn("MeshTools.curve_", source)
        curve_init = (ROOT / "CurveTools" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("keymap_items.new", curve_init)

    def test_mesh_tools_do_not_import_curve_tools(self):
        source = (ROOT / "MeshTools" / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("CurveTools", source)

    def test_mesh_and_curve_symmetrize_have_separate_ids(self):
        mesh_source = (ROOT / "MeshTools" / "symmetrize.py").read_text(encoding="utf-8")
        curve_source = (ROOT / "CurveTools" / "symmetrize.py").read_text(encoding="utf-8")
        self.assertIn("bl_idname = 'ho.symmetrize'", mesh_source)
        self.assertIn("bl_idname = 'ho.curve_symmetrize'", curve_source)
        self.assertNotIn("curve_mode", mesh_source)
        self.assertNotIn("mesh_mode", curve_source)


if __name__ == "__main__":
    unittest.main()
