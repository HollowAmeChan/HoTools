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
    "HoTools.OmniNode.PhysicsWorld.blender"
)
world_names = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.names"
)
gn_offset = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.gn_offset"
)
base_pose = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.simple_cloth.base_pose"
)
blender_scene = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.utils.blender_scene"
)
frame_input = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.setups.mesh_cloth.frame_input"
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


def test_automatic_base_pose_uses_source_scene() -> None:
    physics_blender.register()
    context_scene = bpy.context.scene
    context_cache = base_pose.ensure_cache_collection(context_scene)
    source_scene = bpy.data.scenes.new("MC2AutoBasePoseSourceScene")
    source_scene.view_layers.new("MC2AutoBasePoseSecondaryLayer")
    source = base_proxy = source_cache = None
    try:
        mesh = bpy.data.meshes.new("MC2AutoBasePoseSourceMesh")
        mesh.from_pydata(
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            (),
            ((0, 1, 2),),
        )
        mesh.update()
        source = bpy.data.objects.new("MC2AutoBasePoseSource", mesh)
        source_scene.collection.objects.link(source)
        source.hotools_mesh_collision.enabled = True

        objects, count = nodes.physicsMC2MeshObject([source])
        assert count == 1 and objects[0].source_object == source
        base_proxy = source.hotools_mesh_collision.mc2_base_pose_proxy
        source_cache = base_pose.ensure_cache_collection(source_scene)
        assert source_cache != context_cache
        assert source_cache in tuple(source_scene.collection.children)
        assert source_cache not in tuple(context_scene.collection.children)
        assert source_scene.objects.get(base_proxy.name) == base_proxy
        assert context_scene.objects.get(base_proxy.name) is None
        for view_layer in source_scene.view_layers:
            layer_collection = view_layer.layer_collection.children.get(
                source_cache.name
            )
            assert layer_collection is not None
            assert layer_collection.exclude is False
            assert layer_collection.hide_viewport is False
            assert blender_scene.view_layer_contains_collection(
                view_layer, source_cache
            )
            assert blender_scene.view_layer_contains_object(
                view_layer, base_proxy
            )
            assert view_layer.objects.get(base_proxy.name_full) == base_proxy
            assert base_proxy.hide_get(view_layer=view_layer) is True
            assert base_proxy.visible_get(view_layer=view_layer) is False
        assert base_proxy.hide_viewport is False
        print("PASS test_automatic_base_pose_uses_source_scene")
    finally:
        _remove_object(base_proxy)
        _remove_object(source)
        bpy.data.scenes.remove(source_scene)
        if source_cache is not None and not source_cache.objects:
            bpy.data.collections.remove(source_cache)
        if context_cache is not None and not context_cache.objects:
            bpy.data.collections.remove(context_cache)
        if physics_blender.is_registered():
            physics_blender.unregister()


def test_custom_object_reuses_public_resources_without_panel_mutation() -> None:
    physics_blender.register()
    source = base_proxy = None
    cache_collection = cache_parent = None
    try:
        mesh = bpy.data.meshes.new("MC2CustomBasePoseResourceMesh")
        mesh.from_pydata(
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            (),
            ((0, 1, 2),),
        )
        mesh.update()
        source = bpy.data.objects.new("MC2CustomBasePoseResource", mesh)
        bpy.context.scene.collection.objects.link(source)
        assert source.hotools_mesh_collision.mc2_base_pose_proxy is None

        first, first_count = nodes.physicsMC2MeshCustomObject([source])
        second, second_count = nodes.physicsMC2MeshCustomObject([source])
        assert first_count == second_count == 1
        base_proxy = first[0].explicit_properties.mc2_base_pose_proxy
        assert base_proxy is second[0].explicit_properties.mc2_base_pose_proxy
        source.name = "MC2CustomBasePoseResourceRenamed"
        renamed, renamed_count = nodes.physicsMC2MeshCustomObject([source])
        assert renamed_count == 1
        assert renamed[0].explicit_properties.mc2_base_pose_proxy is base_proxy
        assert source.hotools_mesh_collision.mc2_base_pose_proxy is None
        assert source.data.attributes.get(
            world_names.GN_OFFSET_ATTRIBUTE_NAME
        ) is not None
        assert source.modifiers.get(world_names.GN_OFFSET_MODIFIER_NAME) is not None

        cache_collection = base_pose.ensure_cache_collection(bpy.context.scene)
        generated = tuple(
            item
            for item in cache_collection.objects
            if bool(item.get(base_pose.CACHE_OBJECT_FLAG, False))
            and item.get(base_pose.CACHE_SOURCE_KEY) == base_proxy.get(
                base_pose.CACHE_SOURCE_KEY
            )
        )
        assert generated == (base_proxy,)
        cache_parent = bpy.data.collections.new("MC2CustomBasePoseCacheParent")
        bpy.context.scene.collection.children.link(cache_parent)
        bpy.context.scene.collection.children.unlink(cache_collection)
        cache_parent.children.link(cache_collection)
        nested, nested_count = nodes.physicsMC2MeshCustomObject([source])
        assert nested_count == 1
        assert nested[0].explicit_properties.mc2_base_pose_proxy is base_proxy
        assert base_pose.ensure_cache_collection(
            bpy.context.scene
        ) is cache_collection
        assert blender_scene.view_layer_contains_object(
            bpy.context.view_layer, base_proxy
        )
        assert base_proxy.visible_get(view_layer=bpy.context.view_layer) is False

        old_proxy = base_proxy
        source.data.clear_geometry()
        source.data.from_pydata(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
                (0.0, 1.0, 0.0),
            ),
            (),
            ((0, 1, 2), (0, 2, 3)),
        )
        source.data.update()
        refreshed, refreshed_count = nodes.physicsMC2MeshCustomObject([source])
        assert refreshed_count == 1
        base_proxy = refreshed[0].explicit_properties.mc2_base_pose_proxy
        assert base_proxy is not old_proxy
        assert len(base_proxy.data.vertices) == 4
        generated = tuple(
            item
            for item in cache_collection.objects
            if bool(item.get(base_pose.CACHE_OBJECT_FLAG, False))
            and item.get(base_pose.CACHE_SOURCE_KEY) == base_proxy.get(
                base_pose.CACHE_SOURCE_KEY
            )
        )
        assert generated == (base_proxy,)
        print("PASS test_custom_object_reuses_public_resources_without_panel_mutation")
    finally:
        _remove_object(base_proxy)
        _remove_object(source)
        if cache_collection is not None and not cache_collection.objects:
            bpy.data.collections.remove(cache_collection)
        if cache_parent is not None:
            bpy.data.collections.remove(cache_parent)
        if physics_blender.is_registered():
            physics_blender.unregister()


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
        source.hotools_mesh_collision.enabled = True

        cache_collection = base_pose.ensure_cache_collection(bpy.context.scene)
        layer_collection = bpy.context.view_layer.layer_collection.children.get(
            cache_collection.name
        )
        assert layer_collection is not None
        cache_collection.hide_viewport = True
        layer_collection.hide_viewport = True
        layer_collection.exclude = True

        topology_signature = base_pose.mesh_topology_signature(source)
        panel_objects, panel_count = nodes.physicsMC2MeshObject([source])
        assert panel_count == 1 and panel_objects[0].source_object == source
        base_proxy = source.hotools_mesh_collision.mc2_base_pose_proxy
        assert cache_collection.hide_viewport is False
        assert layer_collection.hide_viewport is False
        assert layer_collection.exclude is False
        assert base_proxy.hide_viewport is False
        assert blender_scene.view_layer_contains_collection(
            bpy.context.view_layer, cache_collection
        )
        assert blender_scene.view_layer_contains_object(
            bpy.context.view_layer, base_proxy
        )
        assert bpy.context.view_layer.objects.get(base_proxy.name_full) == base_proxy
        assert base_proxy.hide_get(view_layer=bpy.context.view_layer) is True
        assert base_proxy.visible_get(view_layer=bpy.context.view_layer) is False
        assert base_pose.ensure_base_pose_proxy(
            source,
            expected_mesh_topology_signature=topology_signature,
        ) == base_proxy
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
        source.location = (2.0, 0.0, 0.0)
        assert tuple(base_proxy.location) == (0.0, 0.0, 0.0)
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
            snapshot.animated_base_world_positions[:, 0], (2.5, 3.5, 2.5)
        )
        np.testing.assert_allclose(snapshot.component_world_position, (2.0, 0.0, 0.0))
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

        properties = source.hotools_mesh_collision
        objects, count = nodes.physicsMC2MeshCustomObject(
            [source],
            mc2_base_pose_proxy=base_proxy,
            radius_vertex_group=properties.radius_vertex_group,
            pin_enabled=properties.pin_enabled,
            pin_vertex_group=properties.pin_vertex_group,
            primary_collision_group=7,
            collided_by_groups=2,
        )
        assert count == 1 and len(objects) == 1
        properties.mc2_base_pose_proxy = None
        entries, _domain_ids = nodes.physicsMC2MeshClothTask(objects)
        assert entries[0].source_properties.mc2_base_pose_proxy is base_proxy
        assert entries[0].collision_group == 64
        assert entries[0].collision_mask == 66
        requests, report = nodes.physicsMC2MeshCollector(entries)
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
    test_automatic_base_pose_uses_source_scene()
    test_custom_object_reuses_public_resources_without_panel_mutation()
    test_mesh_product_base_pose_contract()
