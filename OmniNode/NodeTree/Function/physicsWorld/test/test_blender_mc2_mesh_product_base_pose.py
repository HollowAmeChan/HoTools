"""Armature-driven MeshCloth base-pose contract on the product path."""

from __future__ import annotations

import importlib
import os
import sys

import bpy
import numpy as np


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import test_blender_mc2_bone_product_constraint_soak as product_helpers


physics_blender = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender"
)
world_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.names"
)
gn_offset = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.gn_offset"
)
base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.base_pose"
)
frame_input = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.frame_input"
)
nodes = product_helpers.nodes
product_slot = product_helpers.product_slot
world_types = product_helpers.world_types
writeback = product_helpers.writeback


def _make_armature():
    data = bpy.data.armatures.new("MC2ProductBasePoseArmatureData")
    obj = bpy.data.objects.new("MC2ProductBasePoseArmature", data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = data.edit_bones.new("BasePoseBone")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _make_source(armature):
    mesh = bpy.data.meshes.new("MC2ProductBasePoseSourceMesh")
    mesh.from_pydata(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        (),
        ((0, 1, 2),),
    )
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = (
            (0.0, 0.0), (1.0, 0.0), (0.0, 1.0)
        )[loop.vertex_index]
    obj = bpy.data.objects.new("MC2ProductBasePoseSource", mesh)
    bpy.context.scene.collection.objects.link(obj)
    group = obj.vertex_groups.new(name="BasePoseBone")
    group.add((0, 1, 2), 1.0, "REPLACE")
    modifier = obj.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    return obj


def _remove_object(obj) -> None:
    if obj is None:
        return
    try:
        name = obj.name
        data = obj.data
        object_type = obj.type
    except ReferenceError:
        return
    if name not in bpy.data.objects:
        return
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        if object_type == "ARMATURE":
            bpy.data.armatures.remove(data)
        else:
            bpy.data.meshes.remove(data)


def _set_frame(world, frame: int) -> None:
    product_helpers._set_frame(world, frame, 1900)
    world.collider_snapshot = {"frame": frame, "colliders": []}


def test_mesh_product_base_pose_contract() -> None:
    physics_blender.register()
    armature = source = base_proxy = None
    world = world_types.PhysicsWorldCache()
    try:
        armature = _make_armature()
        source = _make_source(armature)
        gn_offset.write_gn_local_offsets(
            source, np.zeros((len(source.data.vertices), 3), dtype=np.float32)
        )
        assert source.modifiers[-1].name == world_names.GN_OFFSET_MODIFIER_NAME
        assert source.hotools_mesh_collision.mc2_base_pose_proxy is None

        topology_signature = base_pose.mesh_topology_signature(source)
        base_proxy = base_pose.ensure_base_pose_proxy(
            source,
            expected_mesh_topology_signature=topology_signature,
        )
        assert base_proxy is not source
        assert base_proxy.data is not source.data
        assert base_proxy.modifiers.get("Armature") is not None
        assert base_proxy.modifiers.get(world_names.GN_OFFSET_MODIFIER_NAME) is None
        assert base_proxy.data.attributes.get(world_names.GN_OFFSET_ATTRIBUTE_NAME) is None
        assert base_proxy[base_pose.CACHE_TOPOLOGY_SIGNATURE_KEY] == topology_signature

        base_proxy[base_pose.CACHE_TOPOLOGY_SIGNATURE_KEY] = "stale-token"
        base_pose.validate_base_pose_proxy(source, base_proxy, topology_signature)
        assert base_proxy[base_pose.CACHE_TOPOLOGY_SIGNATURE_KEY] == topology_signature

        armature.pose.bones["BasePoseBone"].location = (0.5, 0.0, 0.0)
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        snapshot = frame_input.read_base_pose_frame_snapshot(
            source,
            base_proxy,
            mesh_topology_signature=topology_signature,
            frame=1,
            generation=1900,
            depsgraph=depsgraph,
            cache={},
        )
        assert snapshot.vertex_count == 3
        assert snapshot.animated_base_world_positions.flags.writeable is False
        assert snapshot.animated_base_world_normals.flags.writeable is False
        assert snapshot.source_world_linear.flags.writeable is False
        np.testing.assert_allclose(
            snapshot.animated_base_world_positions[:, 0], (0.5, 1.5, 0.5)
        )
        np.testing.assert_allclose(snapshot.component_world_scale, (1.0, 1.0, 1.0))

        source.scale = (-1.0, 1.0, 1.0)
        bpy.context.view_layer.update()
        negative = frame_input.read_base_pose_frame_snapshot(
            source,
            base_proxy,
            mesh_topology_signature=topology_signature,
            frame=2,
            generation=1900,
            depsgraph=bpy.context.evaluated_depsgraph_get(),
            cache={},
        )
        np.testing.assert_allclose(
            negative.component_world_scale, (-1.0, 1.0, 1.0), atol=1.0e-6
        )
        source.scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()

        entries, count = nodes.physicsMC2MeshObject([source])
        assert count == 1 and len(entries) == 1
        requests, report = nodes.physicsMC2MeshCollector(
            world, entries, include_implicit=False
        )
        assert len(requests) == 1 and report
        request = requests[0]
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        _set_frame(world, 1)
        returned, ready, status = nodes.physicsMC2Step(world, [request])
        assert returned is world and ready is True, status
        slot = world.solver_slots[slot_id]
        owner = slot.data["owner"]
        assert "native_context" not in slot.data
        assert owner.compiled.program.setup_type == "mesh_cloth"
        assert owner.compiled.program.particle_count == 3
        assert np.all(np.isfinite(owner.read_output().world_positions))
        assert writeback.writeback_gn_attributes(world) == 1
        print("PASS test_mesh_product_base_pose_contract")
    finally:
        world.omni_cache_dispose("mesh_product_base_pose_contract")
        _remove_object(base_proxy)
        _remove_object(source)
        _remove_object(armature)
        if physics_blender.is_registered():
            physics_blender.unregister()


if __name__ == "__main__":
    test_mesh_product_base_pose_contract()
