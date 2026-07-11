# -*- coding: utf-8 -*-
"""Armature-driven dual-object MC2 BasePose regression test."""

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


def _make_armature():
    armature_data = bpy.data.armatures.new("MC2_BasePoseArmatureData")
    armature_obj = bpy.data.objects.new("MC2_BasePoseArmature", armature_data)
    bpy.context.scene.collection.objects.link(armature_obj)
    bpy.context.view_layer.objects.active = armature_obj
    armature_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature_data.edit_bones.new("BasePoseBone")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    armature_obj.select_set(False)
    return armature_obj


def _make_source(armature_obj):
    mesh = bpy.data.meshes.new("MC2_BasePoseSourceMesh")
    mesh.from_pydata(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        (),
        ((0, 1, 2),),
    )
    source = bpy.data.objects.new("MC2_BasePoseSource", mesh)
    bpy.context.scene.collection.objects.link(source)
    group = source.vertex_groups.new(name="BasePoseBone")
    group.add((0, 1, 2), 1.0, "REPLACE")
    modifier = source.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature_obj
    return source


def _evaluated_world_positions(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    if mesh is None:
        raise AssertionError("evaluated mesh unavailable")
    try:
        return np.asarray(
            [tuple(evaluated.matrix_world @ vertex.co) for vertex in mesh.vertices],
            dtype=np.float32,
        )
    finally:
        evaluated.to_mesh_clear()


def _update_depsgraph():
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return depsgraph


def test_armature_base_pose_isolated_from_shared_gn_output():
    physics_blender.register()
    armature_obj = None
    source = None
    base_obj = None
    try:
        armature_obj = _make_armature()
        source = _make_source(armature_obj)
        gn_offset.write_gn_local_offsets(source, np.zeros((3, 3), dtype=np.float32))
        assert source.modifiers[-1].name == world_names.GN_OFFSET_MODIFIER_NAME

        topology_signature = base_pose.mesh_topology_signature(source)
        base_obj = base_pose.ensure_base_pose_proxy(
            source,
            expected_mesh_topology_signature=topology_signature,
        )
        assert base_obj != source
        assert base_obj.modifiers.get("Armature") is not None
        assert base_obj.modifiers.get(world_names.GN_OFFSET_MODIFIER_NAME) is None
        assert base_obj.data.attributes.get(world_names.GN_OFFSET_ATTRIBUTE_NAME) is None
        assert base_obj[base_pose.CACHE_TOPOLOGY_SIGNATURE_KEY] == topology_signature

        armature_obj.pose.bones["BasePoseBone"].location = (0.5, 0.0, 0.0)
        depsgraph = _update_depsgraph()
        cache = {}
        first = frame_input.read_base_pose_frame_snapshot(
            source,
            base_obj,
            mesh_topology_signature=topology_signature,
            frame=1,
            generation=3,
            depsgraph=depsgraph,
            cache=cache,
        )
        assert first.vertex_count == 3
        assert first.animated_base_world_positions.flags.writeable is False
        assert first.animated_base_world_normals.flags.writeable is False
        assert np.allclose(first.animated_base_world_positions[:, 0], (0.5, 1.5, 0.5))

        offsets = np.full((3, 3), (0.0, 0.0, 0.25), dtype=np.float32)
        gn_offset.write_gn_local_offsets(source, offsets)
        depsgraph = _update_depsgraph()
        source_display = _evaluated_world_positions(source, depsgraph)
        assert np.allclose(
            source_display,
            first.animated_base_world_positions + offsets,
        )

        same_frame = frame_input.read_base_pose_frame_snapshot(
            source,
            base_obj,
            mesh_topology_signature=topology_signature,
            frame=1,
            generation=3,
            depsgraph=depsgraph,
            cache=cache,
        )
        assert same_frame is first
        fresh_same_pose = frame_input.read_base_pose_frame_snapshot(
            source,
            base_obj,
            mesh_topology_signature=topology_signature,
            frame=1,
            generation=4,
            depsgraph=depsgraph,
            cache=cache,
        )
        assert np.allclose(
            fresh_same_pose.animated_base_world_positions,
            first.animated_base_world_positions,
        )

        armature_obj.pose.bones["BasePoseBone"].location = (1.0, 0.0, 0.0)
        depsgraph = _update_depsgraph()
        second = frame_input.read_base_pose_frame_snapshot(
            source,
            base_obj,
            mesh_topology_signature=topology_signature,
            frame=2,
            generation=4,
            depsgraph=depsgraph,
            cache=cache,
        )
        assert np.allclose(second.animated_base_world_positions[:, 0], (1.0, 2.0, 1.0))
        assert np.allclose(
            second.animated_base_world_positions - fresh_same_pose.animated_base_world_positions,
            (0.5, 0.0, 0.0),
        )

        try:
            frame_input.read_base_pose_frame_snapshot(
                source,
                base_obj,
                mesh_topology_signature="0" * 64,
                frame=2,
                generation=4,
                depsgraph=depsgraph,
            )
        except ValueError as exc:
            assert "拓扑签名" in str(exc)
        else:
            raise AssertionError("mismatched Mesh topology signature must be rejected")
    finally:
        if base_obj is not None:
            base_mesh = base_obj.data
            bpy.data.objects.remove(base_obj, do_unlink=True)
            if base_mesh is not None and base_mesh.users == 0:
                bpy.data.meshes.remove(base_mesh)
        if source is not None:
            source_mesh = source.data
            bpy.data.objects.remove(source, do_unlink=True)
            if source_mesh is not None and source_mesh.users == 0:
                bpy.data.meshes.remove(source_mesh)
        if armature_obj is not None:
            armature_data = armature_obj.data
            bpy.data.objects.remove(armature_obj, do_unlink=True)
            if armature_data is not None and armature_data.users == 0:
                bpy.data.armatures.remove(armature_data)
        if physics_blender.is_registered():
            physics_blender.unregister()


def main():
    test_armature_base_pose_isolated_from_shared_gn_output()
    print("MC2 dual-object Armature BasePose: PASS")


if __name__ == "__main__":
    main()
