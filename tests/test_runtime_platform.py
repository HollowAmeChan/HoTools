from pathlib import Path
import sys
import unittest

from Utils.runtime_platform import (
    UnsupportedRuntimeError,
    configure_runtime_paths,
    resolve_runtime_target,
)


class RuntimePlatformTests(unittest.TestCase):
    def test_linux_py311_uses_platform_directory_only(self):
        target = resolve_runtime_target(
            Path("/addon/HoTools"),
            python_version=(3, 11),
            sys_platform="linux",
            machine="x86_64",
        )

        self.assertEqual(target.abi, "py311")
        self.assertEqual(target.platform_id, "linux-x86_64")
        self.assertEqual(
            target.dependency_dir,
            Path("/addon/HoTools/_Lib/py311/linux-x86_64"),
        )
        self.assertIsNone(target.legacy_dependency_dir)
        self.assertEqual(
            target.native_dir,
            target.dependency_dir / "HotoolsPackage",
        )

    def test_linux_amd64_alias_normalizes(self):
        target = resolve_runtime_target(
            Path("/addon/HoTools"),
            python_version=(3, 13),
            sys_platform="linux",
            machine="AMD64",
        )

        self.assertEqual(target.platform_id, "linux-x86_64")

    def test_windows_keeps_legacy_dependency_fallback(self):
        target = resolve_runtime_target(
            Path("C:/HoTools"),
            python_version=(3, 13),
            sys_platform="win32",
            machine="AMD64",
        )

        self.assertEqual(target.platform_id, "windows-x86_64")
        self.assertEqual(
            target.legacy_dependency_dir,
            Path("C:/HoTools/_Lib/py313"),
        )

    def test_unsupported_python_is_rejected(self):
        with self.assertRaisesRegex(UnsupportedRuntimeError, "Python 3.12"):
            resolve_runtime_target(
                Path("/addon"),
                python_version=(3, 12),
                sys_platform="linux",
                machine="x86_64",
            )

    def test_unsupported_architecture_is_rejected(self):
        with self.assertRaisesRegex(UnsupportedRuntimeError, "aarch64"):
            resolve_runtime_target(
                Path("/addon"),
                python_version=(3, 11),
                sys_platform="linux",
                machine="aarch64",
            )

    def test_linux_never_inserts_legacy_directory(self):
        target = resolve_runtime_target(
            Path("/addon"),
            python_version=(3, 11),
            sys_platform="linux",
            machine="x86_64",
        )
        before = list(sys.path)
        try:
            inserted = configure_runtime_paths(target)
            self.assertNotIn(Path("/addon/_Lib/py311"), inserted)
        finally:
            sys.path[:] = before


if __name__ == "__main__":
    unittest.main()
