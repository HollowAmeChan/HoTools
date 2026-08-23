import sys
import unittest
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))


class NameMappingLinuxTests(unittest.TestCase):
    def test_copy_does_not_spawn_windows_clip_command(self):
        from HoTools import NameMapping

        bpy.context.window_manager.clipboard = ""
        NameMapping.copy_to_clipboard("骨骼.A\n骨骼.B")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
