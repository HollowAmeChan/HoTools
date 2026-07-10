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


def _publish(world, obj, offsets, *, solver="mc2", slot_id="mc2:mesh:one"):
    return commands.publish_gn_offset_writeback(
        world,
        solver=solver,
        slot_id=slot_id,
        object_ptr=int(obj.as_pointer()),
        object_data_ptr=int(obj.data.as_pointer()),
        frame=int(world.frame_context.frame),
        generation=int(world.generation),
        local_offsets=offsets,
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


def main():
    test_shared_gn_final_offset_contract()
    print("Physics World shared GN final offset writeback: PASS")


if __name__ == "__main__":
    main()
