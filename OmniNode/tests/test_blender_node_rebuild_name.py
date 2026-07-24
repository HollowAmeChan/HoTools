"""OmniNode重建时的可选节点名称刷新验收。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy


TESTS = os.path.dirname(os.path.abspath(__file__))
OMNINODE = os.path.dirname(TESTS)
HOTOOLS = os.path.dirname(OMNINODE)
NODETREE = os.path.join(OMNINODE, "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PHYSICS_WORLD = os.path.join(FUNCTION, "physicsWorld")

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
    (
        "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2",
        os.path.join(PHYSICS_WORLD, "mc2"),
    ),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


from HoTools import PropertyCurve
from HoTools.OmniNode.NodeTree import OmniNodeDraw
from HoTools.OmniNode.NodeTree import OmniNodeOperator
from HoTools.OmniNode.NodeTree import OmniNodeRegister
from HoTools.OmniNode.NodeTree import OmniNodeSocket
from HoTools.OmniNode.NodeTree import OmniNodeTree


registered = []
registered_operator_classes = []
tree = None
try:
    OmniNodeDraw.register()
    registered.append(OmniNodeDraw)

    for operator_class in OmniNodeOperator.clss:
        bpy.utils.register_class(operator_class)
        registered_operator_classes.append(operator_class)

    for module in (OmniNodeTree, PropertyCurve, OmniNodeSocket, OmniNodeRegister):
        module.register()
        registered.append(module)

    rebuild = OmniNodeOperator.OmniNodeRebuild
    operator_rna = bpy.ops.ho.rebuild_node.get_rna_type()
    assert operator_rna.properties["refresh_node_name"].default is True

    tree = bpy.data.node_groups.new("NodeRebuildNameRegression", "OmniNodeTree")

    refreshed = tree.nodes.new("HO_OmniNode_physicsMC2MeshClothTask")
    step = tree.nodes.new("HO_OmniNode_physicsMC2Step")
    tree.links.new(refreshed.outputs["_OUTPUT0"], step.inputs["mc2_tasks"])
    refreshed.name = "MC2 MeshCloth任务"
    rebuild.rebuild_single_node(tree, refreshed, refresh_node_name=True)
    assert refreshed.name == "MC2 MeshCloth域"
    assert refreshed.outputs["_OUTPUT0"].name == "MC2域"
    assert refreshed.outputs["_OUTPUT1"].name == "域标识"
    assert step.inputs["mc2_tasks"].is_linked
    assert step.inputs["mc2_tasks"].links[0].from_node == refreshed

    preserved = tree.nodes.new("HO_OmniNode_physicsMC2MeshClothTask")
    preserved.name = "用户自定义节点名"
    rebuild.rebuild_single_node(tree, preserved, refresh_node_name=False)
    assert preserved.name == "用户自定义节点名"

    print("PASS test_blender_node_rebuild_name")
finally:
    if tree is not None:
        bpy.data.node_groups.remove(tree)
    for module in reversed(registered):
        try:
            module.unregister()
        except Exception:
            pass
    for operator_class in reversed(registered_operator_classes):
        try:
            bpy.utils.unregister_class(operator_class)
        except Exception:
            pass
