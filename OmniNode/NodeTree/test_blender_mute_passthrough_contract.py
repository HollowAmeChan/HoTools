"""Registration-level regression for explicit OmniNode mute passthrough contracts."""

from __future__ import annotations

import importlib
import os
import sys
import types
import uuid

import bpy


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
OMNINODE = os.path.join(HOTOOLS, "OmniNode")
NODETREE = os.path.join(OMNINODE, "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PHYSICS_WORLD = os.path.join(FUNCTION, "physicsWorld")

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2", os.path.join(PHYSICS_WORLD, "mc2")),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.rigid", os.path.join(PHYSICS_WORLD, "rigid")),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.spring_vrm", os.path.join(PHYSICS_WORLD, "spring_vrm")),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


core = importlib.import_module("HoTools.OmniNode.NodeTree.FunctionNodeCore")
data = importlib.import_module("HoTools.OmniNode.NodeTree.Function.Data")
image = importlib.import_module("HoTools.OmniNode.NodeTree.Function.Image")
modifier = importlib.import_module("HoTools.OmniNode.NodeTree.Function.Modifier")
uv = importlib.import_module("HoTools.OmniNode.NodeTree.Function.UV")
vertex_color = importlib.import_module("HoTools.OmniNode.NodeTree.Function.VertexColor")
vertex_group = importlib.import_module("HoTools.OmniNode.NodeTree.Function.VertexGroup")
physics_nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.nodes"
)
mc2_nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
)
rigid_nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.rigid.nodes"
)
spring_nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.spring_vrm.nodes"
)


def _mapping(func) -> dict[str, str]:
    return dict(core.CreateNodeClass(func)._omni_mute_passthrough)


expected = {
    modifier.objectAddModifier: {"_OUTPUT0": "obj", "_OUTPUT1": "modifier_name"},
    uv.objectCreateUVLayer: {"_OUTPUT0": "obj", "_OUTPUT2": "uv_name"},
    uv.uvLayerRename: {"_OUTPUT0": "uv_layer", "_OUTPUT1": "new_name"},
    vertex_color.objectCreateColorAttribute: {
        "_OUTPUT0": "obj",
        "_OUTPUT2": "attribute_name",
    },
    vertex_color.colorAttributeRename: {
        "_OUTPUT0": "color_attribute",
        "_OUTPUT1": "new_name",
    },
    vertex_group.objectCreateVertexGroup: {
        "_OUTPUT0": "obj",
        "_OUTPUT2": "group_name",
    },
    vertex_group.vertexGroupRename: {
        "_OUTPUT0": "vertex_group",
        "_OUTPUT1": "new_name",
    },
    image.uv_reprojectionTransfer: {
        "_OUTPUT0": "img",
        "_OUTPUT1": "file_path",
    },
    image.adjustNormalMapStrength: {
        "_OUTPUT0": "img",
        "_OUTPUT1": "file_path",
    },
    image.splitImageChannels: {
        "_OUTPUT0": "img",
        "_OUTPUT1": "img",
        "_OUTPUT2": "img",
        "_OUTPUT3": "img",
    },
    data.curvePreviewStackTest: {
        "_OUTPUT0": "float_a",
        "_OUTPUT1": "color_a",
    },
}
for func, mapping in expected.items():
    assert _mapping(func) == mapping, (func.__name__, _mapping(func), mapping)


for module in (physics_nodes, mc2_nodes, rigid_nodes, spring_nodes):
    for value in vars(module).values():
        meta = getattr(value, "__meta", None)
        if not isinstance(meta, dict) or not meta.get("enable", False):
            continue
        assert "mute_passthrough" in meta, (
            f"{module.__name__}.{value.__name__} must declare its mute contract"
        )


assert _mapping(physics_nodes.physicsWorldBegin) == {}
assert _mapping(physics_nodes.physicsBake) == {"_OUTPUT0": "world"}
assert _mapping(physics_nodes.clearPhysicsBake) == {"_OUTPUT0": "world"}
assert _mapping(physics_nodes.physicsWorldCommit) == {"_OUTPUT1": "world"}
assert _mapping(mc2_nodes.physicsMC2Step) == {"_OUTPUT0": "world"}
assert _mapping(spring_nodes.physicsSpringVRMSolver) == {"_OUTPUT0": "world"}
assert _mapping(rigid_nodes.physicsRigidSolver) == {"_OUTPUT0": "world"}


from HoTools import PropertyCurve
from HoTools.OmniNode.NodeTree import OmniNodeDraw
from HoTools.OmniNode.NodeTree import OmniNodeOperator
from HoTools.OmniNode.NodeTree import OmniNodeRegister
from HoTools.OmniNode.NodeTree import OmniNodeSocket
from HoTools.OmniNode.NodeTree import OmniNodeTree
from HoTools.OmniNode.NodeTree.OmniCompiler import OmniCompiler


registered = []
tree = None
try:
    for module in (
        OmniNodeDraw,
        OmniNodeOperator,
        OmniNodeTree,
        PropertyCurve,
        OmniNodeSocket,
        OmniNodeRegister,
    ):
        module.register()
        registered.append(module)

    physics_world_ids = {
        node_class.bl_idname
        for node_class in OmniNodeRegister.node_cls_physics_world
    }
    physics_world_menu_ids = {
        node_class.bl_idname
        for node_class in OmniNodeRegister._pw_lifecycle
    }
    bake_node_ids = {
        "HO_OmniNode_physicsBake",
        "HO_OmniNode_clearPhysicsBake",
    }
    assert bake_node_ids <= physics_world_ids
    assert bake_node_ids <= physics_world_menu_ids

    tree = bpy.data.node_groups.new("MuteCompileRegression", "OmniNodeTree")
    bake_node = tree.nodes.new("HO_OmniNode_physicsBake")
    clear_node = tree.nodes.new("HO_OmniNode_clearPhysicsBake")
    assert [socket.identifier for socket in bake_node.inputs] == [
        "world", "cache_directory", "file_prefix", "frame_start", "frame_end",
        "bake_bones", "bake_mesh", "use_mesh_cache", "enabled",
    ]
    assert [socket.identifier for socket in clear_node.inputs] == [
        "world", "cache_directory", "file_prefix", "clear_frame",
        "animation_clear_mode", "mesh_cache_policy", "finalize_cache_policy",
        "clear_live_output", "pause_timeline", "enabled",
    ]
    output_io = tree.group_outputs.add()
    output_io.name = "Name"
    output_io.uid = uuid.uuid4().hex
    output_io.socket_type = "NodeSocketString"

    source = tree.nodes.new("HO_OmniNode_stringInput")
    muted = tree.nodes.new("HO_OmniNode_uvLayerRename")
    output = tree.nodes.new("HO_OmniNode_GroupNode_Outputs")
    output.syncGroupIO()
    source.inputs["v"].default_value = "BypassedName"
    muted.mute = True
    tree.links.new(source.outputs["_OUTPUT0"], muted.inputs["new_name"])
    tree.links.new(muted.outputs["_OUTPUT1"], output.inputs[output_io.uid])

    compiled = OmniCompiler.compile(tree, debug=True)
    instruction_names = tuple(
        getattr(getattr(item, "func", None), "__name__", "")
        for item in compiled.instructions
    )
    assert "uvLayerRename" not in instruction_names
    assert "stringInput" in instruction_names
    assert len(compiled.output_regs) == 1
finally:
    if tree is not None:
        bpy.data.node_groups.remove(tree)
    for module in reversed(registered):
        try:
            module.unregister()
        except Exception:
            pass


print("OmniNode explicit mute passthrough contract: PASS")
