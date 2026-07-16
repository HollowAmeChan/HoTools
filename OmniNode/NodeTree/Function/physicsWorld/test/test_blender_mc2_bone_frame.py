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
parent = None
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
        assert frame_input.native_producer_kind == "bone"
        assert frame_input.world_positions.flags.writeable is False
        assert frame_input.world_rotations_xyzw.flags.writeable is False
        assert frame_input.world_rotations_xyzw.shape == (0, 4)
        assert frame_input.raw_pose_matrices.shape == (2, 3, 3)
        assert frame_input.raw_pose_matrices.flags.writeable is False
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
            slot.data["native_context"].read()[0],
            frame_input.world_positions,
        )

    task = specs.make_mc2_task_spec(
        names.MC2_SETUP_BONE_CLOTH,
        [{"armature": armature, "root_bone": "Root"}],
    )
    topology = topology_module.build_mc2_topology_spec(task)
    armature.scale = (-1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    negative_frame = bone_frame.build_mc2_bone_frame_input(
        task, topology, frame=13, generation=4
    )
    assert negative_frame.negative_scale_sign == -1.0
    assert negative_frame.center_frame_pose is not None
    np.testing.assert_allclose(
        negative_frame.center_frame_pose.component_world_scale,
        (-1.0, 1.0, 1.0),
        atol=1.0e-6,
    )
    assert negative_frame.native_producer_kind == "bone"
    assert negative_frame.raw_pose_matrices.shape == (2, 3, 3)

    armature.scale = (0.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    try:
        bone_frame.build_mc2_bone_frame_input(task, topology, frame=13, generation=4)
    except ValueError as exc:
        assert "cannot contain zero scale" in str(exc)
    else:
        raise AssertionError("zero-scale Bone source produced a frame snapshot")

    armature.scale = (1.5, 0.75, 2.0)
    bpy.context.view_layer.update()
    positive_frame = bone_frame.build_mc2_bone_frame_input(
        task, topology, frame=13, generation=4
    )
    assert positive_frame.particle_count == 2
    np.testing.assert_allclose(
        positive_frame.center_frame_pose.component_world_scale,
        (1.5, 0.75, 2.0),
        atol=1.0e-6,
    )

    armature.scale = (1.0, 1.0, 1.0)
    armature.pose.bones["Child"].scale = (-1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    invalid_pose_frame = bone_frame.build_mc2_bone_frame_input(
        task, topology, frame=14, generation=4
    )
    invalid_world = world_types.PhysicsWorldCache()
    try:
        try:
            solver.step_mc2(
                invalid_world,
                [task],
                frame_inputs={task.task_id: invalid_pose_frame},
            )
        except ValueError as exc:
            assert "proper and shear-free" in str(exc)
        else:
            raise AssertionError("negative PoseBone scale reached the native frame producer")
    finally:
        invalid_world.omni_cache_dispose("test")
    armature.pose.bones["Child"].scale = (1.0, 1.0, 1.0)

    parent = bpy.data.objects.new("MC2_N3_BoneFrameParent", None)
    bpy.context.scene.collection.objects.link(parent)
    armature.parent = parent
    armature.matrix_parent_inverse.identity()
    armature.scale = (1.0, 1.0, 1.0)
    parent.scale = (-1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    try:
        bone_frame.build_mc2_bone_frame_input(task, topology, frame=14, generation=4)
    except ValueError as exc:
        assert "negative scale inherited from a parent" in str(exc)
    else:
        raise AssertionError("parent-inherited negative scale reached Bone frame input")

    parent.scale = (2.0, 1.0, 0.5)
    armature.rotation_mode = "XYZ"
    armature.rotation_euler.y = 0.5
    bpy.context.view_layer.update()
    try:
        bone_frame.build_mc2_bone_frame_input(task, topology, frame=14, generation=4)
    except ValueError as exc:
        assert "shear-free" in str(exc)
    else:
        raise AssertionError("sheared Bone component reached frame input")
finally:
    if parent is not None:
        armature.parent = None
        bpy.data.objects.remove(parent, do_unlink=True)
    data = armature.data
    bpy.data.objects.remove(armature, do_unlink=True)
    if data.users == 0:
        bpy.data.armatures.remove(data)

print("MC2 BoneCloth/BoneSpring frame input: PASS")
