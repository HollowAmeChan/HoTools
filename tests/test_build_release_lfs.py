"""Ensure install packages contain animation data rather than LFS pointers."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hotools_build_release_lfs", ROOT / "tools" / "build_release_zip.py"
)
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class ReleaseLfsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.root.mkdir()
        for relative in (
            ".releaseignore",
            "__init__.py",
            "version_info.json",
            "ShapekeyTools/shapekey_catalog.csv",
            "_Lib/py311/PIL/__init__.py",
            "_Lib/py311/cffi/__init__.py",
            "_Lib/py311/pyoidn/__init__.py",
            "_Lib/py311/_cffi_backend.cp311-win_amd64.pyd",
            "_Lib/py311/HotoolsPackage/hotools_native.cp311-win_amd64.pyd",
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
        (self.root / ".releaseignore").write_bytes(
            (ROOT / ".releaseignore").read_bytes()
        )
        self.animation = (
            self.root / "BoneTools/HumanoidDebug/animations/example.anim"
        )
        self.animation.parent.mkdir(parents=True)
        self.output = Path(self.temporary.name) / "install.zip"

    def test_package_contains_original_animation_bytes(self):
        content = b"%YAML 1.1\r\nAnimationClip:\r\n  m_Name: example\r\n"
        self.animation.write_bytes(content)

        BUILD.build_zip(self.root, self.output, "py311")

        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(
                archive.read(
                    "HoTools/BoneTools/HumanoidDebug/animations/example.anim"
                ),
                content,
            )

    def test_unresolved_pointer_prevents_package_creation(self):
        for newline in (b"\n", b"\r\n"):
            with self.subTest(newline=newline):
                self.animation.write_bytes(newline.join((
                    b"version https://git-lfs.github.com/spec/v1",
                    b"oid sha256:" + b"a" * 64,
                    b"size 177700571",
                    b"",
                )))

                with self.assertRaisesRegex(
                    ValueError, "Unresolved Git LFS pointer:.*git lfs pull"
                ):
                    BUILD.build_zip(self.root, self.output, "py311")
                self.assertFalse(self.output.exists())

    def test_local_research_checkout_is_excluded(self):
        self.animation.write_bytes(b"AnimationClip:\n  m_Name: example\n")
        for folder in ("_research", ".research"):
            research = self.root / folder / "reference/.git/objects/local.pack"
            research.parent.mkdir(parents=True)
            research.write_bytes(b"Local research repository data")

        BUILD.build_zip(self.root, self.output, "py311")

        with zipfile.ZipFile(self.output) as archive:
            self.assertFalse(any(
                name.startswith(("HoTools/_research/", "HoTools/.research/"))
                for name in archive.namelist()
            ))

    def test_nested_git_metadata_is_rejected(self):
        with zipfile.ZipFile(self.output, "w") as archive:
            archive.writestr("HoTools/SomeFolder/.git/config", b"local git config")

        with self.assertRaisesRegex(ValueError, "Git repository metadata"):
            BUILD.validate_archive(self.output, "py311")


if __name__ == "__main__":
    unittest.main()
