"""Keep upgrades reviewable: unchanged upstream dependencies and one small hook."""

import ast
import hashlib
import json
from pathlib import Path
import unittest


PACKAGE = Path(__file__).resolve().parents[1] / "Exporter" / "FbxExporter"
HOOK = (
    "    # HoTools: always normalize the completed tree before encoding (see ../UPSTREAM.md).\n"
    "    from ..cleanup import optimize_fbx_tree\n"
    "    optimize_fbx_tree(root)\n\n"
)


class UpstreamSnapshotTests(unittest.TestCase):
    def test_dependencies_match_recorded_upstream_text(self):
        manifest = json.loads((PACKAGE / "upstream.json").read_text(encoding="utf-8"))
        for name, expected in manifest["upstream_lf_sha256"].items():
            if name == "export_fbx_bin.py":
                continue
            with self.subTest(name=name):
                source = (PACKAGE / "_vendor" / name).read_text(encoding="utf-8")
                self.assertEqual(hashlib.sha256(source.encode("utf-8")).hexdigest(), expected)

    def test_exporter_diff_is_only_the_prewrite_hook(self):
        manifest = json.loads((PACKAGE / "upstream.json").read_text(encoding="utf-8"))
        source = (PACKAGE / "_vendor" / "export_fbx_bin.py").read_text(encoding="utf-8")
        self.assertEqual(source.count(HOOK), 1)
        restored = source.replace(HOOK, "")
        self.assertEqual(hashlib.sha256(restored.encode("utf-8")).hexdigest(),
                         manifest["upstream_lf_sha256"]["export_fbx_bin.py"])
        self.assertLess(source.index(HOOK), source.index("    encode_bin.write(filepath, root, FBX_VERSION)"))

    def test_metadata_package_does_not_register_another_operator(self):
        tree = ast.parse((PACKAGE / "_vendor" / "__init__.py").read_text(encoding="utf-8"))
        self.assertFalse(any(isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)) for n in tree.body))
        info = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign))
        self.assertEqual(info["version"], (5, 13, 1))
        self.assertTrue((PACKAGE / "_vendor" / "LICENSE.txt").is_file())


if __name__ == "__main__":
    unittest.main()
