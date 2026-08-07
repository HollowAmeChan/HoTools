"""Focused Blender regression for BoneCloth terminal particles and writeback."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import numpy as np


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(NODETREE, "PhysicsWorld")
PYTHON_ABI = "py313" if sys.version_info >= (3, 13) else "py311"
NATIVE_PACKAGE = os.environ.get(
    "HOTOOLS_NATIVE_TEST_DIR",
    os.path.join(HOTOOLS, "_Lib", PYTHON_ABI, "HotoolsPackage"),
)

for module_name in tuple(sys.modules):
    if (
        module_name == "HoTools"
        or module_name.startswith("HoTools.")
        or module_name == "hotools_native"
    ):
        sys.modules.pop(module_name, None)
os.environ["HOTOOLS_NATIVE_TEST_DIR"] = NATIVE_PACKAGE
sys.path.insert(0, NATIVE_PACKAGE)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", NODETREE),
    ("HoTools.OmniNode.Function", FUNCTION),
    ("HoTools.OmniNode.PhysicsWorld", PW_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module

mc2_nodes = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mc2.nodes")
parameters = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.parameters"
)
product_slot = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.product_slot"
)
physics_nodes = importlib.import_module("HoTools.OmniNode.PhysicsWorld.nodes")
world_types = importlib.import_module("HoTools.OmniNode.PhysicsWorld.types")


def make_armature():
    data = bpy.data.armatures.new("MC2TerminalWritebackData")
    armature = bpy.data.objects.new("MC2TerminalWriteback", data)
    bpy.context.scene.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    control = data.edit_bones.new("Control")
    control.head = (0.0, 0.0, 0.0)
    control.tail = (0.0, 0.0, 0.2)
    parent = control
    for index in range(3):
        bone = data.edit_bones.new(f"Chain{index}")
        bone.head = (0.0, index * 0.25, 0.2)
        bone.tail = (0.0, (index + 1) * 0.25, 0.2)
        bone.parent = parent
        bone.use_connect = index == 2
        parent = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)
    return armature


def set_frame(world, frame):
    context = world.frame_context
    context.previous_frame = frame - 1 if frame > 1 else None
    context.frame = frame
    context.same_frame = False
    context.continuous = frame > 1
    context.restart_required = frame == 1
    context.reset_requested = False
    context.raw_dt = 1.0 / 30.0
    context.dt = 1.0 / 30.0
    context.time_scale = 1.0
    context.generation = 1
    world.generation = 1
    world.collider_snapshot = {"frame": frame, "colliders": []}


def slot_id(request):
    return product_slot.make_mc2_product_slot_id(
        request.setup_type,
        request.domain_signature,
    )


armature = make_armature()
world = world_types.PhysicsWorldCache()
try:
    objects, count = mc2_nodes.physicsMC2BoneClothCustomObject(
        [{"armature": armature, "bone": "Control"}]
    )
    assert count == 1
    partitions, _partition_names = mc2_nodes.physicsMC2BoneClothTask(
        objects,
        profile=parameters.make_mc2_particle_profile(
            gravity_direction=(1.0, 0.0, 0.0),
            stabilization_time_after_reset=0.0,
        ),
        connection_mode=0,
    )
    requests, _report = mc2_nodes.physicsMC2BoneCollector(partitions)
    assert len(requests) == 1
    request = requests[0]

    changed = False
    for frame in range(1, 9):
        set_frame(world, frame)
        returned, ready, status = mc2_nodes.physicsMC2Step(world, list(requests))
        assert returned is world and ready is True, status
        slot = world.solver_slots[slot_id(request)]
        fragment = slot.data["owner"].compiled.fragments[0]
        assert fragment.final_proxy.vertex_count == 4
        assert fragment.output_bone_identities == (
            "Chain0",
            "Chain1",
            "Chain2",
        )
        assert fragment.output_source_elements.tolist() == [0, 1, 2]
        assert fragment.output_endpoint_source_elements.tolist() == [1, 2, 3]
        assert set(fragment.topology.bone_connection.lines) == {
            (0, 1),
            (1, 2),
            (2, 3),
        }
        result = world.result_streams["bone_transform"][0]
        assert result["bone_count"] == 3
        assert result["rotation_only_connected_count"] == 1
        assert result["position_rotation_count"] == 2

        plan = slot.data["writeback_plan"]
        records = tuple(
            record for batch in plan["batches"] for record in batch["records"]
        )
        matrix_bases = tuple(
            matrix for batch in plan["batches"] for matrix in batch["matrix_bases"]
        )
        pose_bones = tuple(record["pose_bone"] for record in records)
        before = tuple(
            np.asarray(pose_bone.matrix_basis, dtype=np.float64).copy()
            for pose_bone in pose_bones
        )
        world.frame_context.same_frame = True
        returned, written = physics_nodes.physicsWriteback(world)
        assert returned is world and written == 3
        after = tuple(
            np.asarray(pose_bone.matrix_basis, dtype=np.float64).copy()
            for pose_bone in pose_bones
        )
        assert records[1]["motion_mode"] == "position_rotation"
        assert records[2]["motion_mode"] == "rotation_only_connected"
        assert np.allclose(
            tuple(float(value) for value in matrix_bases[2].translation),
            (0.0, 0.0, 0.0),
            rtol=0.0,
            atol=1.0e-8,
        )
        if frame > 1:
            assert np.linalg.norm(
                np.asarray(matrix_bases[1].translation, dtype=np.float64)
            ) > 1.0e-6
            bpy.context.view_layer.update()
            connected = pose_bones[2]
            assert (connected.head - connected.parent.tail).length < 1.0e-6
            assert abs(
                (connected.tail - connected.head).length - connected.bone.length
            ) < 1.0e-6
        changed = changed or any(
            not np.allclose(left, right, rtol=1.0e-7, atol=1.0e-8)
            for left, right in zip(before, after)
        )

    assert changed
    world.clear_results()
    world.frame_context.restart_required = True
    returned, written = physics_nodes.physicsWriteback(world)
    assert returned is world and written == 0
    identity = np.eye(4, dtype=np.float64)
    assert all(
        np.allclose(
            np.asarray(pose_bone.matrix_basis, dtype=np.float64),
            identity,
            rtol=0.0,
            atol=1.0e-8,
        )
        for pose_bone in pose_bones
    )
finally:
    world.omni_cache_dispose("MC2 terminal writeback regression cleanup")
    data = armature.data
    bpy.data.objects.remove(armature, do_unlink=True)
    if not data.users:
        bpy.data.armatures.remove(data)


print("MC2 Bone terminal/writeback integration: PASS")
