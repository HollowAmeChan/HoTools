from types import SimpleNamespace
import unittest

from Utils.desktop import copy_text, open_path


class DesktopOperationTests(unittest.TestCase):
    def test_copy_text_updates_window_manager_clipboard(self):
        window_manager = SimpleNamespace(clipboard="old")

        copy_text(window_manager, "骨骼.A\n骨骼.B")

        self.assertEqual(window_manager.clipboard, "骨骼.A\n骨骼.B")

    def test_open_path_passes_absolute_path_to_blender_operator(self):
        calls = []

        def opener(*, filepath):
            calls.append(filepath)
            return {"FINISHED"}

        result = open_path("/tmp/HoTools/MappingTemplate.csv", opener)

        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(calls, ["/tmp/HoTools/MappingTemplate.csv"])


if __name__ == "__main__":
    unittest.main()
