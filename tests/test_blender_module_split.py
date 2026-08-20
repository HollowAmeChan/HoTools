"""Blender-level regression checks for the split module registration."""

import sys
import unittest
from pathlib import Path

import bpy
import gpu


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))


class ModuleSplitRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # VertexGroupTools creates a shader at import time; background Blender
        # has no GPU context, so replace that lookup for this registration test.
        cls._shader_factory = gpu.shader.from_builtin
        gpu.shader.from_builtin = lambda _name: None
        result = bpy.ops.preferences.addon_enable(module="HoTools")
        if result != {"FINISHED"}:
            raise RuntimeError(f"Unable to enable HoTools: {result}")

    @classmethod
    def tearDownClass(cls):
        bpy.ops.preferences.addon_disable(module="HoTools")
        gpu.shader.from_builtin = cls._shader_factory

    def test_migrated_operator_ids_are_registered(self):
        for operator_id in (
            "restart_blender",
            "sync_render_visibility",
            "quick_add_lattice",
            "mesh_to_image_empty",
            "custom_splitnormal_export",
            "custom_splitnormal_import",
            "merge_overlapping_vertexnormals",
            "copyall_modifiers_to_selected",
            "curve_bevel",
            "repair_curve_path",
        ):
            self.assertTrue(hasattr(bpy.ops.ho, operator_id), operator_id)


if __name__ == "__main__":
    unittest.main()
