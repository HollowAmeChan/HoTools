"""Blender integration for staged MC2 BoneCloth Line static registration."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")

for path in (HOTOOLS, os.path.dirname(HOTOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PW_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


names = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names")
specs = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs")
topology_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
static_build = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_cloth.static_build"
)
solver = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver")
world_types = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.types")


def _armature():
    data = bpy.data.armatures.new("MC2_BoneStaticData")
    obj = bpy.data.objects.new("MC2_BoneStatic", data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root = data.edit_bones.new("Root")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, 1.0, 0.0)
    mid = data.edit_bones.new("Mid")
    mid.head = root.tail
    mid.tail = (0.25, 2.0, 0.0)
    mid.parent = root
    mid.use_connect = True
    tip = data.edit_bones.new("Tip")
    tip.head = mid.tail
    tip.tail = (0.5, 3.0, 0.25)
    tip.parent = mid
    tip.use_connect = True
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


armature = _armature()
world = None
try:
    source = {"armature": armature, "root_bone": "Root"}
    task = specs.make_mc2_task_spec(names.MC2_SETUP_BONE_CLOTH, [source])
    topology = topology_module.build_mc2_topology_spec(task)
    static = static_build.build_mc2_bone_cloth_static_for_task(task, topology)
    assert static is not None
    assert static.final_proxy.vertex_identities == ("Root", "Mid", "Tip")
    assert static.final_proxy.vertex_attributes == (0x01, 0x02, 0x02)
    assert static.final_proxy.edges == ((0, 1), (1, 2))
    assert static.final_proxy.triangles == ()
    assert static.baseline.parent_indices == (-1, 0, 1)
    assert static.finalizer.vertex_to_vertex_data == (1, 2, 0, 1)
    assert len(static.distance.distance_targets) == 4
    assert static.center.fixed_indices == (0,)

    world = world_types.PhysicsWorldCache()
    returned, ready, status = solver.step_mc2(world, [task])
    assert returned is world and ready is False
    assert "新建 1" in status
    slot = world.solver_slots[task.task_id]
    assert slot.data["mesh_static"] is None
    assert slot.data["bone_static"] is not None
    assert slot.data["result_candidate"] is None
    info = slot.data["native_context"].inspect()
    assert info["proxy_static_ready"] is True
    assert info["baseline_static_ready"] is True
    assert info["bone_static_ready"] is True
    assert info["distance_static_ready"] is True
    assert info["center_static_ready"] is True
    assert info["bone_vertex_adjacency_count"] == 4
    snapshot = slot.debug_snapshot()
    assert snapshot["mesh_static"] is None
    assert snapshot["bone_static"]["vertex_count"] == 3
    assert snapshot["bone_static"]["static_signature"] == static.static_signature

    world.omni_cache_dispose("static_only_complete")
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    world.frame_context.frame = 1
    world.frame_context.generation = 1
    world.frame_context.dt = 1.0 / 60.0
    returned, ready, _status = solver.step_mc2(world, [task])
    assert returned is world and ready is False
    slot = world.solver_slots[task.task_id]
    candidate = slot.data["result_candidate"]
    assert candidate is not None
    assert candidate.setup_type == names.MC2_SETUP_BONE_CLOTH
    assert candidate.ready is False
    assert candidate.mesh_object_local_offsets is None
    assert candidate.world_positions.flags.writeable is False
    assert candidate.world_rotations_xyzw.flags.writeable is False
    assert slot.data["native_context"].inspect()["bone_line_output_count"] == 1
    assert world.result_streams == {}

    armature.pose.bones["Root"].rotation_mode = "XYZ"
    armature.pose.bones["Root"].rotation_euler.z = 0.2
    bpy.context.view_layer.update()
    world.frame_context.frame = 2
    solver.step_mc2(world, [task])
    slot = world.solver_slots[task.task_id]
    second_candidate = slot.data["result_candidate"]
    second_info = slot.data["native_context"].inspect()
    assert second_candidate.revision == 2
    assert second_info["step_count"] == 1
    assert second_info["bone_line_output_count"] == 2
    solver.step_mc2(world, [task])
    assert slot.data["result_candidate"] is second_candidate
    assert slot.data["native_context"].inspect()["bone_line_output_count"] == 2
    assert world.result_streams == {}
finally:
    if world is not None:
        world.omni_cache_dispose("test_cleanup")
    data = armature.data
    bpy.data.objects.remove(armature, do_unlink=True)
    if data.users == 0:
        bpy.data.armatures.remove(data)

print("MC2 BoneCloth Line static slot/native: PASS")
