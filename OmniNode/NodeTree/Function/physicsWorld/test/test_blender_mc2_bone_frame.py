"""BoneCloth/BoneSpring N3 world-pose adapter regression."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import numpy as np


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")

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
topology_module = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology")
bone_frame = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_frame_input"
)
solver = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver")
world_types = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.types")


def _armature():
    data = bpy.data.armatures.new("MC2_N3_BoneFrameData")
    obj = bpy.data.objects.new("MC2_N3_BoneFrame", data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root = data.edit_bones.new("Root")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, 0.0, 1.0)
    child = data.edit_bones.new("Child")
    child.head = root.tail
    child.tail = (0.0, 0.0, 2.0)
    child.parent = root
    child.use_connect = True
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


armature = _armature()
try:
    armature.location = (2.0, -1.0, 0.5)
    armature.pose.bones["Root"].location = (0.25, 0.0, 0.0)
    armature.pose.bones["Root"].rotation_mode = "XYZ"
    armature.pose.bones["Root"].rotation_euler.z = 0.4
    bpy.context.view_layer.update()

    for setup_type, source in (
        (names.MC2_SETUP_BONE_CLOTH, {"armature": armature, "root_bone": "Root"}),
        (names.MC2_SETUP_BONE_SPRING, {"armature": armature, "bones": ("Root", "Child")}),
    ):
        task = specs.make_mc2_task_spec(setup_type, [source])
        topology = topology_module.build_mc2_topology_spec(task)
        frame_input = bone_frame.build_mc2_bone_frame_input(
            task, topology, frame=12, generation=4
        )
        assert frame_input.particle_count == 2
        assert frame_input.world_positions.flags.writeable is False
        assert frame_input.world_rotations_xyzw.flags.writeable is False
        assert np.allclose(np.linalg.norm(frame_input.world_rotations_xyzw, axis=1), 1.0)
        expected_root = armature.matrix_world @ armature.pose.bones["Root"].head
        np.testing.assert_allclose(
            frame_input.world_positions[0],
            (expected_root.x, expected_root.y, expected_root.z),
            rtol=1.0e-6,
            atol=1.0e-6,
        )

        world = world_types.PhysicsWorldCache()
        solver.step_mc2(
            world, [task], frame_inputs={task.task_id: frame_input}
        )
        slot = world.solver_slots[task.task_id]
        assert slot.data["runtime_state"].initialized is True
        assert slot.data["runtime_state"].last_reset_reason == "first_valid_pose"
        np.testing.assert_array_equal(
            slot.data["particle_buffer"].next_positions,
            frame_input.world_positions,
        )
finally:
    data = armature.data
    bpy.data.objects.remove(armature, do_unlink=True)
    if data.users == 0:
        bpy.data.armatures.remove(data)

print("MC2 BoneCloth/BoneSpring frame input: PASS")
