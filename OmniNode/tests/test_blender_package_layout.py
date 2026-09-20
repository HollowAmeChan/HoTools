from pathlib import Path
import importlib
import sys
import types

import bpy


HOTOOLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HOTOOLS.parent))
# 合成包不做插件注册，因此没有把插件目录挂上；物理扩展里有 `from Utils...`
# 的历史写法，注册其生命周期时需要顶层可解析，补上与真实注册环境一致。
if str(HOTOOLS) not in sys.path:
    sys.path.insert(0, str(HOTOOLS))

hotools_package = types.ModuleType("HoTools")
hotools_package.__path__ = [str(HOTOOLS)]
hotools_package.__package__ = "HoTools"
sys.modules["HoTools"] = hotools_package
OmniNode = importlib.import_module("HoTools.OmniNode")
nodeColors = importlib.import_module("HoTools.OmniNode.config.nodeColors")
assert nodeColors.colorCat["Math"] == nodeColors.hsv2rgb(0.58, 0.35, 0.3)
assert (HOTOOLS / "OmniNode" / "PhysicsWorld").is_dir()
assert not (HOTOOLS / "OmniNode" / "Function" / "physicsWorld").exists()

# 物理原生模块由扩展自持，必须落在 PhysicsWorld/native/runtime/<abi>/，
# 而不是父仓的 _Lib（那是 PropertyCurve 采样内核的位置）。
mc2_native = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mc2.native")
native_backend = mc2_native.native_module()
native_path = Path(native_backend.__file__).resolve()
runtime_root = (HOTOOLS / "OmniNode" / "PhysicsWorld" / "native" / "runtime").resolve()
assert native_path.is_relative_to(runtime_root), native_path
assert native_backend.__name__ == "hotools_physics", native_backend.__name__

# PropertyCurve 的采样内核仍由父仓产出。
property_curve_backend = importlib.import_module(
    "HoTools.PropertyCurve._native_backend"
).native_module()
assert Path(property_curve_backend.__file__).resolve().is_relative_to(HOTOOLS / "_Lib")
assert property_curve_backend.__name__ == "hotools_native"


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
