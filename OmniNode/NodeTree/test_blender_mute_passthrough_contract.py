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
assert _mapping(physics_nodes.physicsBake) == {
    "_OUTPUT0": "world",
    "_OUTPUT1": "cache_directory",
    "_OUTPUT2": "file_prefix",
}
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
from HoTools.OmniNode.NodeTree import OmniRuntimeState
from HoTools.OmniNode.NodeTree.OmniTiming import OmniRuntimeTiming
from HoTools.OmniNode.NodeTree.OmniCompiler import OmniCompiler
from HoTools.OmniNode.NodeTree.OmniIR import (
    CacheReadCall,
    CacheWriteCall,
    CompiledGraph,
    OpCall,
)


registered = []
tree = None
cache_tree = None
mc2_contract_tree = None
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
    assert [socket.identifier for socket in bake_node.outputs] == [
        "_OUTPUT0", "_OUTPUT1", "_OUTPUT2", "_OUTPUT3", "_OUTPUT4", "_OUTPUT5",
    ]
    assert bake_node.outputs["_OUTPUT1"].name == "缓存目录"
    assert bake_node.outputs["_OUTPUT2"].name == "文件前缀"
    assert bake_node.outputs["_OUTPUT3"].name == "Bone数量"
    assert [socket.identifier for socket in clear_node.inputs] == [
        "world", "cache_directory", "file_prefix", "clear_frame",
        "animation_clear_mode", "mesh_cache_policy", "finalize_cache_policy",
        "clear_live_output", "pause_timeline", "enabled",
    ]
    for output_identifier, input_identifier in (
        ("_OUTPUT0", "world"),
        ("_OUTPUT1", "cache_directory"),
        ("_OUTPUT2", "file_prefix"),
    ):
        link = tree.links.new(
            bake_node.outputs[output_identifier],
            clear_node.inputs[input_identifier],
        )
        assert link.from_socket == bake_node.outputs[output_identifier]
        assert link.to_socket == clear_node.inputs[input_identifier]
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

    def state_owner(value, amount):
        return value, amount

    def dynamic_key_owner():
        return "world"

    def contract_graph(amount, *, owner_uid="state-owner", dynamic_key=False):
        graph = CompiledGraph()
        instructions = []
        if dynamic_key:
            key_node = types.SimpleNamespace(
                omni_runtime_uid="dynamic-key",
                bl_idname="HO_TestDynamicKey",
            )
            key_call = OpCall(dynamic_key_owner, [], [0], key_node)
            instructions.append(key_call)
        else:
            instructions.append(("CONST", 0, "world"))
        read_node = types.SimpleNamespace(
            omni_runtime_uid="cache-read",
            bl_idname="HO_OmniNode_CacheRead",
        )
        owner_node = types.SimpleNamespace(
            omni_runtime_uid=owner_uid,
            bl_idname="HO_TestStateOwner",
        )
        write_node = types.SimpleNamespace(
            omni_runtime_uid="cache-write",
            bl_idname="HO_OmniNode_CacheWrite",
        )
        instructions.extend((
            CacheReadCall(0, [1], read_node),
            ("CONST", 2, amount),
            OpCall(state_owner, [1, 2], [3], owner_node),
            CacheWriteCall(0, 3, None, [4], write_node),
        ))
        graph.instructions = tuple(instructions)
        graph.reg_count = 5
        graph.output_regs = {"result": 4}
        from HoTools.OmniNode.NodeTree.OmniCompiler import CompilerContext
        CompilerContext._build_runtime_cache_contract(graph)
        return graph

    numeric_a = contract_graph(1.0)
    numeric_b = contract_graph(9.0)
    replaced_owner = contract_graph(1.0, owner_uid="replacement-owner")
    dynamic_key = contract_graph(1.0, dynamic_key=True)
    assert (
        numeric_a.runtime_cache_contract["signature"]
        == numeric_b.runtime_cache_contract["signature"]
    )
    assert (
        numeric_a.runtime_cache_contract["signature"]
        != replaced_owner.runtime_cache_contract["signature"]
    )
    assert numeric_a.runtime_cache_contract["preservable"] is True
    assert dynamic_key.runtime_cache_contract["preservable"] is False

    cache_tree = bpy.data.node_groups.new(
        "RuntimeCacheContractRegression", "OmniNodeTree"
    )
    cache_output_io = cache_tree.group_outputs.add()
    cache_output_io.name = "Cache"
    cache_output_io.uid = uuid.uuid4().hex
    cache_output_io.socket_type = "OmniNodeSocketCache"
    unrelated_output_io = cache_tree.group_outputs.add()
    unrelated_output_io.name = "Unrelated"
    unrelated_output_io.uid = uuid.uuid4().hex
    unrelated_output_io.socket_type = "NodeSocketFloat"
    cache_output = cache_tree.nodes.new("HO_OmniNode_GroupNode_Outputs")
    cache_output.syncGroupIO()
    cache_read = cache_tree.nodes.new("HO_OmniNode_CacheRead")
    cache_write = cache_tree.nodes.new("HO_OmniNode_CacheWrite")
    unrelated = cache_tree.nodes.new("HO_OmniNode_floatInput")
    cache_read.inputs["cache_key"].default_value = "world"
    cache_write.inputs["cache_key"].default_value = "world"
    unrelated.inputs["v"].default_value = 1.0
    cache_tree.links.new(cache_read.outputs["cache"], cache_write.inputs["value"])
    cache_tree.links.new(
        cache_write.outputs["value"], cache_output.inputs[cache_output_io.uid]
    )
    cache_tree.links.new(
        unrelated.outputs["_OUTPUT0"],
        cache_output.inputs[unrelated_output_io.uid],
    )
    cache_tree.compile_cached(force=True)

    assert cache_tree.debug_runtime_timing is False
    assert cache_tree.show_runtime_timing is False
    assert cache_tree.runtime_timing_sample_interval == 3.0
    cache_tree.runtime_timing_sample_interval = 4.0
    assert cache_tree.runtime_timing_sample_interval == 4.0
    cache_tree.show_runtime_timing = True
    assert OmniRuntimeTiming.is_enabled(cache_tree)
    original_take_overlay_sample = OmniRuntimeTiming.take_overlay_sample.__func__
    overlay_gate_calls = []

    def count_overlay_gate(cls, target_tree, now=None, gate=None):
        overlay_gate_calls.append(target_tree)
        return original_take_overlay_sample(cls, target_tree, now=now, gate=gate)

    OmniRuntimeTiming.take_overlay_sample = classmethod(count_overlay_gate)
    try:
        OmniRuntimeTiming.reset_overlay_schedule(cache_tree)
        cache_tree.run_frame_cached()
        cache_tree.run_frame_cached()
    finally:
        OmniRuntimeTiming.take_overlay_sample = classmethod(original_take_overlay_sample)
    assert overlay_gate_calls == [cache_tree, cache_tree]
    cache_tree.run_compiled()
    timing_payload = OmniNodeDraw._RUNTIME_TIMING_TREES.get(int(cache_tree.as_pointer()))
    assert timing_payload
    assert cache_read.name in timing_payload
    cache_tree.show_runtime_timing = False
    assert int(cache_tree.as_pointer()) not in OmniNodeDraw._RUNTIME_TIMING_TREES

    cache_tree.debug_runtime_timing = True
    assert OmniRuntimeTiming.is_enabled(cache_tree)
    cache_tree.run_compiled()
    console_snapshots = [
        snapshot
        for snapshot in OmniRuntimeTiming.flush(force=True)
        if snapshot.consumer == OmniRuntimeTiming.CONSOLE
    ]
    assert console_snapshots
    assert console_snapshots[0].totals.get("total", 0.0) > 0.0
    cache_tree.debug_runtime_timing = False
    assert not OmniRuntimeTiming.is_enabled(cache_tree)

    class DisposableOwner:
        def __init__(self):
            self.reasons = []

        def omni_cache_dispose(self, reason):
            self.reasons.append(reason)

    owner = DisposableOwner()
    context = OmniRuntimeState.begin_run(cache_tree)
    OmniRuntimeState.write_cache(context, "world", owner)
    OmniRuntimeState.finish_run(context)
    unrelated.inputs["v"].default_value = 9.0
    cache_tree.compile_cached(force=True)
    context = OmniRuntimeState.begin_run(cache_tree)
    hit, preserved_owner = OmniRuntimeState.read_cache(context, "world")
    OmniRuntimeState.finish_run(context)
    assert hit and preserved_owner is owner
    assert owner.reasons == []

    cache_tree.nodes.remove(cache_write)
    replacement_write = cache_tree.nodes.new("HO_OmniNode_CacheWrite")
    replacement_write.inputs["cache_key"].default_value = "world"
    cache_tree.links.new(
        cache_read.outputs["cache"], replacement_write.inputs["value"]
    )
    cache_tree.links.new(
        replacement_write.outputs["value"],
        cache_output.inputs[cache_output_io.uid],
    )
    cache_tree.compile_cached(force=True)
    context = OmniRuntimeState.begin_run(cache_tree)
    hit, _value = OmniRuntimeState.read_cache(context, "world")
    OmniRuntimeState.finish_run(context)
    assert not hit
    assert owner.reasons == ["recompile_incompatible"]

    mc2_contract_tree = bpy.data.node_groups.new(
        "MC2RuntimeOwnerContractRegression", "OmniNodeTree"
    )
    mc2_output_io = mc2_contract_tree.group_outputs.add()
    mc2_output_io.name = "Cache"
    mc2_output_io.uid = uuid.uuid4().hex
    mc2_output_io.socket_type = "OmniNodeSocketCache"
    mc2_output = mc2_contract_tree.nodes.new("HO_OmniNode_GroupNode_Outputs")
    mc2_output.syncGroupIO()
    mc2_read = mc2_contract_tree.nodes.new("HO_OmniNode_CacheRead")
    world_begin = mc2_contract_tree.nodes.new("HO_OmniNode_physicsWorldBegin")
    mc2_task = mc2_contract_tree.nodes.new("HO_OmniNode_physicsMC2MeshClothTask")
    mc2_step = mc2_contract_tree.nodes.new("HO_OmniNode_physicsMC2Step")
    world_commit = mc2_contract_tree.nodes.new("HO_OmniNode_physicsWorldCommit")
    mc2_write = mc2_contract_tree.nodes.new("HO_OmniNode_CacheWrite")
    mc2_read.inputs["cache_key"].default_value = "physics-world"
    mc2_write.inputs["cache_key"].default_value = "physics-world"
    mc2_contract_tree.links.new(
        mc2_read.outputs["cache"], world_begin.inputs["cache_state"]
    )
    mc2_contract_tree.links.new(
        world_begin.outputs["_OUTPUT0"], mc2_step.inputs["world"]
    )
    mc2_contract_tree.links.new(
        mc2_task.outputs["_OUTPUT0"], mc2_step.inputs["mc2_tasks"]
    )
    mc2_contract_tree.links.new(
        mc2_step.outputs["_OUTPUT0"], world_commit.inputs["world"]
    )
    mc2_contract_tree.links.new(
        world_commit.outputs["_OUTPUT0"], mc2_write.inputs["value"]
    )
    mc2_contract_tree.links.new(
        mc2_write.outputs["value"], mc2_output.inputs[mc2_output_io.uid]
    )
    mc2_contract_a = OmniCompiler.compile(mc2_contract_tree)
    mc2_task.inputs["teleport_distance"].default_value = 3.0
    mc2_contract_b = OmniCompiler.compile(mc2_contract_tree)
    assert (
        mc2_contract_a.runtime_cache_contract["signature"]
        == mc2_contract_b.runtime_cache_contract["signature"]
    )
    mc2_contract_tree.nodes.remove(mc2_step)
    replacement_step = mc2_contract_tree.nodes.new("HO_OmniNode_physicsMC2Step")
    mc2_contract_tree.links.new(
        world_begin.outputs["_OUTPUT0"], replacement_step.inputs["world"]
    )
    mc2_contract_tree.links.new(
        mc2_task.outputs["_OUTPUT0"], replacement_step.inputs["mc2_tasks"]
    )
    mc2_contract_tree.links.new(
        replacement_step.outputs["_OUTPUT0"], world_commit.inputs["world"]
    )
    mc2_contract_c = OmniCompiler.compile(mc2_contract_tree)
    assert (
        mc2_contract_b.runtime_cache_contract["signature"]
        != mc2_contract_c.runtime_cache_contract["signature"]
    )
finally:
    if mc2_contract_tree is not None:
        bpy.data.node_groups.remove(mc2_contract_tree)
    if cache_tree is not None:
        OmniRuntimeState.clear_root_tree(cache_tree)
        bpy.data.node_groups.remove(cache_tree)
    if tree is not None:
        bpy.data.node_groups.remove(tree)
    for module in reversed(registered):
        try:
            module.unregister()
        except Exception:
            pass


print("OmniNode explicit mute passthrough contract: PASS")
