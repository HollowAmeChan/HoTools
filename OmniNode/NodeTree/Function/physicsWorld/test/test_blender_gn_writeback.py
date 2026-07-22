# -*- coding: utf-8 -*-
"""共享 GN 最终 offset 写回契约测试。

用法：blender.exe --factory-startup --background --python test_blender_gn_writeback.py
"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import numpy as np


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NATIVE_PACKAGE = os.path.join(HOTOOLS, "_Lib", "py313", "HotoolsPackage")
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")

for module_name in tuple(sys.modules):
    if (
        module_name == "hotools_native"
        or module_name == "HoTools"
        or module_name.startswith("HoTools.")
    ):
        sys.modules.pop(module_name, None)
os.environ["HOTOOLS_NATIVE_TEST_DIR"] = NATIVE_PACKAGE
for path in (NATIVE_PACKAGE, HOTOOLS, os.path.dirname(HOTOOLS)):
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


world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)
world_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.names"
)
commands = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback_commands"
)
writeback = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback"
)
print("GN_WRITEBACK_SOURCE", writeback.__file__)
gn_offset = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.gn_offset"
)


def _make_mesh_object():
    mesh = bpy.data.meshes.new("GNWritebackMesh")
    mesh.from_pydata(
        [(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)],
        [],
        [(0, 1, 2)],
    )
    obj = bpy.data.objects.new("GNWritebackObject", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _offset_values(obj):
    attribute = obj.data.attributes.get(world_names.GN_OFFSET_ATTRIBUTE_NAME)
    assert attribute is not None
    values = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
    attribute.data.foreach_get("vector", values)
    return values.reshape((-1, 3))


def _evaluated_positions(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        values = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", values)
        return values.reshape((-1, 3)).copy()
    finally:
        evaluated.to_mesh_clear()


def _base_positions(obj):
    values = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
    obj.data.vertices.foreach_get("co", values)
    return values.reshape((-1, 3))


def _publish(
    world,
    obj,
    offsets,
    *,
    solver="mc2",
    slot_id="mc2:mesh:one",
    transaction_id=None,
    transaction_index=None,
    transaction_size=None,
):
    return commands.publish_gn_offset_writeback(
        world,
        solver=solver,
        slot_id=slot_id,
        object_ptr=int(obj.as_pointer()),
        object_data_ptr=int(obj.data.as_pointer()),
        frame=int(world.frame_context.frame),
        generation=int(world.generation),
        local_offsets=offsets,
        transaction_id=transaction_id,
        transaction_index=transaction_index,
        transaction_size=transaction_size,
    )


def test_shared_gn_final_offset_contract():
    obj = _make_mesh_object()
    foreign_obj = None
    foreign_copy = None
    world = world_types.PhysicsWorldCache()
    world.frame_context.frame = 7
    world.generation = 3
    first = np.asarray(
        [(0.1, 0.0, 0.0), (0.0, 0.2, 0.0), (0.0, 0.0, -0.3)],
        dtype=np.float32,
    )
    second = first * 2.0

    try:
        item = _publish(world, obj, first)
        assert item["channel"] == world_names.GN_ATTRIBUTE_CHANNEL
        assert item["writeback_type"] == world_names.GN_OFFSET_WRITEBACK_TYPE
        assert item["offset_space"] == world_names.GN_OFFSET_SPACE
        assert item["target_key"] == f"{int(obj.as_pointer())}:{int(obj.data.as_pointer())}"
        assert item["local_offsets"].flags.writeable is False
        assert "attribute_name" not in item and "blend_mode" not in item

        assert writeback.writeback_gn_attributes(world) == 1
        assert np.allclose(_offset_values(obj), first)
        assert obj.data.attributes.get(world_names.GN_OFFSET_ATTRIBUTE_NAME) is not None
        modifier = obj.modifiers.get(world_names.GN_OFFSET_MODIFIER_NAME)
        assert modifier is not None and modifier.type == "NODES"
        assert modifier == obj.modifiers[-1]
        assert modifier.node_group.name == world_names.GN_OFFSET_NODE_GROUP_NAME
        assert not any(
            node.bl_idname == "GeometryNodeBake"
            for node in modifier.node_group.nodes
        )

        # 实际结构是刷新权威：schema 不变时，节点/socket/default/link 的差异也必须
        # 被 register 使用的统一 refresh 检出并原位修复，不能依赖开发者记得升版本号。
        managed_group = modifier.node_group
        managed_pointer = int(managed_group.as_pointer())
        original_contract = str(managed_group["hotools_physics_offset_contract"])
        named_attribute = next(
            node for node in managed_group.nodes
            if node.bl_idname == "GeometryNodeInputNamedAttribute"
        )
        output_node = next(
            node for node in managed_group.nodes
            if node.bl_idname == "NodeGroupOutput"
        )
        named_attribute.inputs["Name"].default_value = "broken_offset_name"
        for link in tuple(output_node.inputs["Geometry"].links):
            managed_group.links.remove(link)
        managed_group.nodes.new("GeometryNodeJoinGeometry")
        managed_group.interface.new_socket(
            name="Unexpected",
            in_out="INPUT",
            socket_type="NodeSocketFloat",
        )
        assert managed_group["hotools_physics_offset_schema"] == 3

        refresh = gn_offset.refresh_managed_gn_node_groups()
        assert refresh["refreshed_group_count"] == 1, refresh
        assert int(managed_group.as_pointer()) == managed_pointer
        assert str(managed_group["hotools_physics_offset_contract"]) == original_contract
        assert len(managed_group.nodes) == 4
        assert [item.name for item in managed_group.interface.items_tree] == [
            "Geometry", "Geometry"
        ]
        named_attribute = next(
            node for node in managed_group.nodes
            if node.bl_idname == "GeometryNodeInputNamedAttribute"
        )
        assert named_attribute.inputs["Name"].default_value == world_names.GN_OFFSET_ATTRIBUTE_NAME
        np.testing.assert_allclose(
            _evaluated_positions(obj),
            _base_positions(obj) + first,
            rtol=0.0,
            atol=1.0e-6,
        )
        repeated_refresh = gn_offset.refresh_managed_gn_node_groups()
        assert repeated_refresh["refreshed_group_count"] == 0, repeated_refresh

        # 模拟开发者修改 builder 但忘记提升 schema：期望 contract 必须随当前
        # builder 自动变化，并把已有同 schema 数据块原位刷新到新结构。
        original_builder = gn_offset._build_node_group
        try:
            def changed_builder(group):
                original_builder(group)
                group.nodes.new("GeometryNodeJoinGeometry")

            gn_offset._build_node_group = changed_builder
            gn_offset._EXPECTED_GROUP_CONTRACTS.clear()
            builder_refresh = gn_offset.refresh_managed_gn_node_groups()
            assert builder_refresh["refreshed_group_count"] == 1, builder_refresh
            assert managed_group["hotools_physics_offset_schema"] == 3
            assert any(
                node.bl_idname == "GeometryNodeJoinGeometry"
                for node in managed_group.nodes
            )
        finally:
            gn_offset._build_node_group = original_builder
            gn_offset._EXPECTED_GROUP_CONTRACTS.clear()
        restore_refresh = gn_offset.refresh_managed_gn_node_groups()
        assert restore_refresh["refreshed_group_count"] == 1, restore_refresh
        assert len(managed_group.nodes) == 4
        assert str(managed_group["hotools_physics_offset_contract"]) == original_contract

        # Modifier 引用也由同一刷新入口修复，不要求等到下一次 solver writeback。
        wrong_group = bpy.data.node_groups.new("GNWritebackWrongGroup", "GeometryNodeTree")
        modifier.node_group = wrong_group
        modifier_refresh = gn_offset.refresh_managed_gn_node_groups()
        assert modifier_refresh["refreshed_modifier_count"] == 1, modifier_refresh
        assert modifier.node_group == managed_group
        bpy.data.node_groups.remove(wrong_group)

        # 构造已提交版本的 schema 2 组合组，迁移必须保留 Bake node/bake_id。
        legacy_group = modifier.node_group
        set_position = next(
            node for node in legacy_group.nodes
            if node.bl_idname == "GeometryNodeSetPosition"
        )
        output_node = next(
            node for node in legacy_group.nodes
            if node.bl_idname == "NodeGroupOutput"
        )
        for link in tuple(output_node.inputs["Geometry"].links):
            legacy_group.links.remove(link)
        bake_node = legacy_group.nodes.new("GeometryNodeBake")
        if not bake_node.inputs.get("Geometry"):
            bake_node.bake_items.new("GEOMETRY", "Geometry")
        bake_node.name = "HoTools Physics Bake"
        legacy_group.links.new(set_position.outputs["Geometry"], bake_node.inputs["Geometry"])
        legacy_group.links.new(bake_node.outputs["Geometry"], output_node.inputs["Geometry"])
        legacy_group["hotools_physics_offset_schema"] = 2
        legacy_entry = gn_offset.get_gn_offset_bake_entry(modifier)
        original_bake_pointer = int(bake_node.as_pointer())
        original_bake_id = int(legacy_entry.bake_id)

        migrated_group = gn_offset.ensure_gn_offset_node_group()
        live_modifier = obj.modifiers.get(world_names.GN_OFFSET_MODIFIER_NAME)
        cache_modifier = obj.modifiers.get(world_names.GN_CACHE_MODIFIER_NAME)
        assert migrated_group == live_modifier.node_group
        assert cache_modifier == modifier
        assert obj.modifiers.find(live_modifier.name) + 1 == obj.modifiers.find(cache_modifier.name)
        bake_node = gn_offset.get_gn_offset_bake_node(cache_modifier.node_group)
        migrated_entry = gn_offset.get_gn_offset_bake_entry(cache_modifier)
        assert int(bake_node.as_pointer()) == original_bake_pointer
        assert int(migrated_entry.bake_id) == original_bake_id

        cache_group = cache_modifier.node_group
        cache_group.nodes.new("GeometryNodeJoinGeometry")
        bake_node.label = "Broken label"
        cache_refresh = gn_offset.refresh_managed_gn_node_groups()
        assert cache_refresh["refreshed_group_count"] == 1, cache_refresh
        refreshed_bake_node = gn_offset.get_gn_offset_bake_node(cache_group)
        refreshed_entry = gn_offset.get_gn_offset_bake_entry(cache_modifier)
        assert int(refreshed_bake_node.as_pointer()) == original_bake_pointer
        assert int(refreshed_entry.bake_id) == original_bake_id
        assert refreshed_bake_node.label == "Physics Post-Displacement Cache"
        assert not any(
            node.bl_idname == "GeometryNodeJoinGeometry"
            for node in cache_group.nodes
        )

        gn_offset.set_gn_offset_cache_enabled(obj, False)
        assert gn_offset.is_gn_offset_cache_enabled(obj) is False
        assert gn_offset.set_gn_offset_cache_enabled(obj, True) == cache_modifier
        assert gn_offset.is_gn_offset_cache_enabled(obj) is True
        assert cache_modifier.show_viewport is True and cache_modifier.show_render is True
        gn_offset.set_gn_offset_cache_enabled(obj, False)
        assert cache_modifier.show_viewport is False and cache_modifier.show_render is False
        configured_modifier, bake_entry = gn_offset.configure_gn_offset_disk_bake(
            obj,
            "//physics_bake",
            3,
            9,
        )
        assert configured_modifier == cache_modifier
        assert bake_entry.node == bake_node
        assert bake_entry.bake_mode == "ANIMATION"
        assert bake_entry.bake_target == "DISK"
        assert bake_entry.frame_start == 3 and bake_entry.frame_end == 9
        assert bake_entry.directory == "//physics_bake"
        assert not any(
            attribute.name.startswith("mc2_") or attribute.name.startswith("spring_")
            for attribute in obj.data.attributes
        )

        # 同一个最终 writer 的同帧重发是 replace 语义，取最后一个快照。
        _publish(world, obj, second)
        repeated_count = writeback.writeback_gn_attributes(world)
        assert repeated_count == 1, writeback.get_gn_writeback_diagnostics(world)
        assert np.allclose(_offset_values(obj), second)
        diagnostics = writeback.get_gn_writeback_diagnostics(world)
        assert diagnostics["superseded_count"] == 1
        assert diagnostics["conflict_count"] == 0

        # 不同 writer 不允许在 result stream 里隐式叠加，冲突目标必须清零。
        world.clear_results(world_names.GN_ATTRIBUTE_CHANNEL)
        _publish(world, obj, first, solver="mc2", slot_id="mc2:mesh:one")
        _publish(world, obj, second, solver="other", slot_id="other:mesh:one")
        assert writeback.writeback_gn_attributes(world) == 0
        assert np.allclose(_offset_values(obj), 0.0)
        diagnostics = writeback.get_gn_writeback_diagnostics(world)
        assert diagnostics["conflict_count"] == 1
        assert any("world.exchange" in error["message"] for error in diagnostics["errors"])

        # exchange 可以保存分量，但 writeback 只消费最终 result。
        world.clear_results(world_names.GN_ATTRIBUTE_CHANNEL)
        world.publish_exchange({
            "channel": "gn_offset_parts",
            "producer": "test-part",
            "target_key": item["target_key"],
            "local_offsets": first,
        })
        assert writeback.writeback_gn_attributes(world) == 0
        assert len(world.consume_exchange("gn_offset_parts")) == 1
        assert np.allclose(_offset_values(obj), 0.0)

        # 本帧没有最终结果时，不能残留上一帧 offset。
        _publish(world, obj, first)
        assert writeback.writeback_gn_attributes(world) == 1
        world.clear_results(world_names.GN_ATTRIBUTE_CHANNEL)
        world.frame_context.frame += 1
        assert writeback.writeback_gn_attributes(world) == 0
        assert np.allclose(_offset_values(obj), 0.0)
        assert writeback.get_gn_writeback_diagnostics(world)["cleared_count"] == 1

        # result 拓扑与目标不一致时拒绝写入，不截断也不填充。
        _publish(world, obj, first[:2])
        assert writeback.writeback_gn_attributes(world) == 0
        diagnostics = writeback.get_gn_writeback_diagnostics(world)
        assert any("拓扑已变化" in error["message"] for error in diagnostics["errors"])

        # cache dispose 将共享 offset 归零，但保留可复用的属性/修改器结构。
        world.clear_results(world_names.GN_ATTRIBUTE_CHANNEL)
        _publish(world, obj, second)
        assert writeback.apply_all_writebacks(world, restart=True) == 1
        world.omni_cache_dispose("test")
        assert np.allclose(_offset_values(obj), 0.0)
        assert obj.modifiers.get(world_names.GN_OFFSET_MODIFIER_NAME) is not None

        # HoTools 保留名采用强所有权：同名用户属性直接接管并刷新输出结构。
        foreign_mesh = bpy.data.meshes.new("GNWritebackForeignMesh")
        foreign_mesh.from_pydata([(0.0, 0.0, 0.0)], [], [])
        foreign_obj = bpy.data.objects.new("GNWritebackForeignObject", foreign_mesh)
        bpy.context.scene.collection.objects.link(foreign_obj)
        foreign_mesh.attributes.new(
            world_names.GN_OFFSET_ATTRIBUTE_NAME,
            "FLOAT",
            "POINT",
        )
        foreign_obj.modifiers.new(world_names.GN_OFFSET_MODIFIER_NAME, "SUBSURF")
        shared_group = bpy.data.node_groups[world_names.GN_OFFSET_NODE_GROUP_NAME]
        shared_group["hotools_physics_offset_owner"] = "foreign"
        shared_group.nodes.clear()
        attribute, modifier = gn_offset.ensure_gn_offset_output(foreign_obj)
        assert attribute.name == world_names.GN_OFFSET_ATTRIBUTE_NAME
        assert attribute.data_type == "FLOAT_VECTOR" and attribute.domain == "POINT"
        assert modifier is not None and modifier.node_group is not None
        assert modifier.type == "NODES"
        assert modifier.node_group.name == world_names.GN_OFFSET_NODE_GROUP_NAME
        assert modifier.node_group["hotools_physics_offset_owner"] == "physicsWorld.writeback"
        assert any(node.bl_idname == "GeometryNodeSetPosition" for node in modifier.node_group.nodes)
        assert not any(node.bl_idname == "GeometryNodeBake" for node in modifier.node_group.nodes)
        assert gn_offset.is_gn_offset_cache_enabled(foreign_obj) is False

        foreign_copy = bpy.data.objects.new("GNWritebackForeignCopy", foreign_mesh)
        bpy.context.scene.collection.objects.link(foreign_copy)
        try:
            gn_offset.write_gn_local_offsets(foreign_obj, [(0.0, 0.0, 0.0)])
        except ValueError as exc:
            assert "单用户" in str(exc)
        else:
            raise AssertionError("shared Mesh data must not receive object-specific GN offsets")
    finally:
        if foreign_copy is not None:
            bpy.data.objects.remove(foreign_copy, do_unlink=True)
        if foreign_obj is not None:
            foreign_mesh = foreign_obj.data
            bpy.data.objects.remove(foreign_obj, do_unlink=True)
            if foreign_mesh.users == 0:
                bpy.data.meshes.remove(foreign_mesh)
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def test_multi_target_gn_transaction_is_all_or_nothing():
    objects = (_make_mesh_object(), _make_mesh_object())
    objects[0].name = "GNTransactionA"
    objects[1].name = "GNTransactionB"
    world = world_types.PhysicsWorldCache()
    world.frame_context.frame = 18
    world.generation = 6
    first = np.asarray(
        ((0.1, 0.0, 0.0), (0.0, 0.2, 0.0), (0.0, 0.0, 0.3)),
        dtype=np.float32,
    )
    second = first * np.float32(2.0)
    try:
        for index, (obj, values) in enumerate(zip(objects, (first, second))):
            _publish(
                world,
                obj,
                values,
                slot_id="mc2.domain.mesh.product.v1",
                transaction_id="mc2-domain-frame-18",
                transaction_index=index,
                transaction_size=2,
            )
        assert writeback.writeback_gn_attributes(world) == 2
        np.testing.assert_allclose(_offset_values(objects[0]), first)
        np.testing.assert_allclose(_offset_values(objects[1]), second)
        diagnostics = writeback.get_gn_writeback_diagnostics(world)
        assert diagnostics["committed_transaction_count"] == 1
        assert diagnostics["failed_transaction_count"] == 0
        assert len(diagnostics["receipts"]) == 2

        world.clear_results(world_names.GN_ATTRIBUTE_CHANNEL)
        world.frame_context.frame = 19
        for index, (obj, values) in enumerate(zip(objects, (second, first))):
            _publish(
                world,
                obj,
                values,
                slot_id="mc2.domain.mesh.product.v1",
                transaction_id="mc2-domain-frame-19",
                transaction_index=index,
                transaction_size=2,
            )
        original_write = writeback.write_gn_local_offsets
        write_count = 0

        def fail_second_target(obj, values):
            nonlocal write_count
            write_count += 1
            if write_count == 2:
                raise RuntimeError("injected second target write failure")
            return original_write(obj, values)

        writeback.write_gn_local_offsets = fail_second_target
        try:
            assert writeback.writeback_gn_attributes(world) == 0
        finally:
            writeback.write_gn_local_offsets = original_write
        np.testing.assert_allclose(_offset_values(objects[0]), 0.0)
        np.testing.assert_allclose(_offset_values(objects[1]), 0.0)
        diagnostics = writeback.get_gn_writeback_diagnostics(world)
        assert diagnostics["failed_transaction_count"] == 1
        assert diagnostics["rollback_count"] == 2
        assert not diagnostics["receipts"]
        assert any(
            "injected second target write failure" in item["message"]
            for item in diagnostics["errors"]
        )

        world.clear_results(world_names.GN_ATTRIBUTE_CHANNEL)
        world.frame_context.frame = 20
        for index, (obj, values) in enumerate(zip(objects, (first, second))):
            _publish(
                world,
                obj,
                values,
                slot_id="mc2.domain.mesh.product.v1",
                transaction_id="mc2-domain-frame-20",
                transaction_index=index,
                transaction_size=2,
            )
        assert writeback.writeback_gn_attributes(world) == 2

        world.clear_results(world_names.GN_ATTRIBUTE_CHANNEL)
        world.frame_context.frame = 21
        for index, (obj, values) in enumerate(zip(objects, (second, first))):
            _publish(
                world,
                obj,
                values,
                slot_id="mc2.domain.mesh.product.v1",
                transaction_id="mc2-domain-frame-21",
                transaction_index=index,
                transaction_size=2,
            )
        objects[1].data.vertices.add(1)
        objects[1].data.update()
        assert writeback.writeback_gn_attributes(world) == 0
        np.testing.assert_allclose(_offset_values(objects[0]), 0.0)
        np.testing.assert_allclose(_offset_values(objects[1]), 0.0)
        diagnostics = writeback.get_gn_writeback_diagnostics(world)
        assert diagnostics["committed_transaction_count"] == 0
        assert diagnostics["failed_transaction_count"] == 1
        assert not diagnostics["receipts"]
        assert any("拓扑已变化" in item["message"] for item in diagnostics["errors"])
    finally:
        world.omni_cache_dispose("multi-target GN transaction cleanup")
        for obj in reversed(objects):
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)


def main():
    test_shared_gn_final_offset_contract()
    test_multi_target_gn_transaction_is_all_or_nothing()
    print("Physics World shared GN final offset writeback: PASS")


if __name__ == "__main__":
    main()
