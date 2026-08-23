from pathlib import Path
import unittest

from Utils.optional_dependencies import (
    LazyOptionalModule,
    OptionalDependencyError,
)
from Utils.runtime_platform import RuntimeTarget


TARGET = RuntimeTarget(
    abi="py311",
    platform_id="linux-x86_64",
    dependency_dir=Path("/addon/_Lib/py311/linux-x86_64"),
    native_dir=Path(
        "/addon/_Lib/py311/linux-x86_64/HotoolsPackage"
    ),
    legacy_dependency_dir=None,
)


class OptionalDependencyTests(unittest.TestCase):
    def test_construction_does_not_import(self):
        calls = []

        LazyOptionalModule(
            "PIL.Image",
            "Pillow",
            TARGET,
            lambda name: calls.append(name),
        )

        self.assertEqual(calls, [])

    def test_first_attribute_loads_module_once(self):
        module = type("Module", (), {"marker": 7})()
        calls = []
        proxy = LazyOptionalModule(
            "PIL.Image",
            "Pillow",
            TARGET,
            lambda name: calls.append(name) or module,
        )

        self.assertEqual(proxy.marker, 7)
        self.assertEqual(proxy.marker, 7)
        self.assertEqual(calls, ["PIL.Image"])

    def test_import_failure_has_target_context(self):
        def missing(_name):
            raise ModuleNotFoundError("no module")

        proxy = LazyOptionalModule(
            "PIL.Image",
            "Pillow",
            TARGET,
            missing,
        )

        with self.assertRaisesRegex(
            OptionalDependencyError,
            "Pillow.*PIL.Image.*py311.*linux-x86_64.*linux-x86_64",
        ):
            proxy.open

    def test_unavailable_result_is_cached(self):
        calls = []

        def missing(name):
            calls.append(name)
            raise OSError("wrong ELF class")

        proxy = LazyOptionalModule(
            "hotools_native",
            "hotools_native",
            TARGET,
            missing,
        )

        self.assertFalse(proxy.is_available())
        self.assertFalse(proxy.is_available())
        self.assertEqual(calls, ["hotools_native"])

    def test_programming_error_is_not_masked(self):
        def broken(_name):
            raise RuntimeError("module bug")

        proxy = LazyOptionalModule("bad", "Bad", TARGET, broken)

        with self.assertRaisesRegex(RuntimeError, "module bug"):
            proxy.value


if __name__ == "__main__":
    unittest.main()
