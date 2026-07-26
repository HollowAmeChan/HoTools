from pathlib import Path
import importlib
import sys
import types

import bpy


HOTOOLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HOTOOLS.parent))

hotools_package = types.ModuleType("HoTools")
hotools_package.__path__ = [str(HOTOOLS)]
hotools_package.__package__ = "HoTools"
sys.modules["HoTools"] = hotools_package
OmniNode = importlib.import_module("HoTools.OmniNode")
mc2_native = importlib.import_module("HoTools.OmniNode.Function.physicsWorld.mc2.native")
native_backend = mc2_native.native_module()
assert Path(native_backend.__file__).resolve().is_relative_to(HOTOOLS / "_Lib")


for cycle in range(2):
    OmniNode.register()
    tree = bpy.data.node_groups.new(f"OmniNodeMigrationSmoke{cycle}", "OmniNodeTree")
    node = tree.nodes.new("HO_OmniNode_floatAdd")
    assert node.bl_idname == "HO_OmniNode_floatAdd"
    assert type(tree).__module__ == "HoTools.OmniNode.OmniNodeTree"
    assert node._func.__module__ == "HoTools.OmniNode.Function.Math"
    assert not any(name.startswith("HoTools.OmniNode.NodeTree") for name in sys.modules)
    bpy.data.node_groups.remove(tree)
    OmniNode.unregister()

print("OmniNode migration register smoke: PASS")
