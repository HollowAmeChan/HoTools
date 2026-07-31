"""Random data node regression checks."""

from __future__ import annotations

import importlib
from pathlib import Path
import random as stdlib_random
import sys
import types

import bpy
import mathutils


HOTOOLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HOTOOLS.parent))

hotools_package = types.ModuleType("HoTools")
hotools_package.__path__ = [str(HOTOOLS)]
hotools_package.__package__ = "HoTools"
sys.modules["HoTools"] = hotools_package

OmniNode = importlib.import_module("HoTools.OmniNode")
data = importlib.import_module("HoTools.OmniNode.Function.Data")
node_register = importlib.import_module("HoTools.OmniNode.OmniNodeRegister")


node_register._rebuild_registry()
node_classes = {cls.bl_idname: cls for cls in node_register.cls}
random_node = node_classes["HO_OmniNode_random"]
seeded_node = node_classes["HO_OmniNode_seededRandom"]

assert random_node._meta["always_run"] is True
random_meta = data.random.__meta
assert random_meta["always_run"] is True

core = importlib.import_module("HoTools.OmniNode.FunctionNodeCore")
_, random_inputs, random_outputs, _, _, _ = core.CheckMetaInfo(data.random)
_, seeded_inputs, seeded_outputs, _, _, _ = core.CheckMetaInfo(data.seededRandom)
assert not random_inputs
assert [spec["type"] for spec in seeded_inputs.values()] == [
    "NodeSocketInt",
]

output_names = ["布尔", "整数", "浮点数", "矢量", "颜色"]
output_types = [
    "NodeSocketBool",
    "NodeSocketInt",
    "NodeSocketFloat",
    "NodeSocketVector",
    "NodeSocketColor",
]
for outputs in (random_outputs, seeded_outputs):
    assert [spec["name"] for spec in outputs.values()] == output_names
    assert [spec["type"] for spec in outputs.values()] == output_types

first = data.seededRandom(123456)
second = data.seededRandom(123456)
other = data.seededRandom(123457)

assert first == second
assert first != other
assert isinstance(first[0], bool)
assert isinstance(first[1], int)
assert -(2 ** 31) <= first[1] <= 2 ** 31 - 1
assert isinstance(first[2], float) and 0.0 <= first[2] < 1.0
assert isinstance(first[3], mathutils.Vector) and len(first[3]) == 3
assert all(0.0 <= component < 1.0 for component in first[3])
assert isinstance(first[4], mathutils.Color)
assert all(0.0 <= component < 1.0 for component in first[4])

unseeded_first = data.random()
unseeded_second = data.random()
assert unseeded_first != unseeded_second

stdlib_random.seed(9182)
expected_global_value = stdlib_random.random()
stdlib_random.seed(9182)
data.random()
data.seededRandom(123456)
assert stdlib_random.random() == expected_global_value

OmniNode.register()
tree = None
try:
    tree = bpy.data.node_groups.new("OmniNodeRandomTest", "OmniNodeTree")
    random_instance = tree.nodes.new("HO_OmniNode_random")
    seeded_instance = tree.nodes.new("HO_OmniNode_seededRandom")
    assert not random_instance.inputs
    assert len(random_instance.outputs) == 5
    assert [socket.identifier for socket in seeded_instance.inputs] == ["seed"]
    assert seeded_instance.inputs["seed"].default_value == 0
    assert len(seeded_instance.outputs) == 5
finally:
    if tree is not None:
        bpy.data.node_groups.remove(tree)
    OmniNode.unregister()

print("OmniNode random data nodes: PASS")
