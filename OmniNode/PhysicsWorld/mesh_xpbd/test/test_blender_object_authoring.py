"""Mesh XPBD 对象/任务节点的真实 Blender PropertyGroup 验收。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy


MESH_XPBD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(MESH_XPBD_ROOT)
OMNINODE = os.path.dirname(PHYSICS_WORLD)
HOTOOLS = os.path.dirname(OMNINODE)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.Function", os.path.join(OMNINODE, "Function")),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

registry = importlib.import_module("HoTools.OmniNode.PhysicsWorld.registry")
nodes = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mesh_xpbd.nodes")


def test_real_blender_panel_custom_and_task_nodes():
    registry.register_physics_world_blender_properties()
    mesh = bpy.data.meshes.new("MeshXpbdObjectAuthoringMesh")
    mesh.from_pydata(((0, 0, 0), (1, 0, 0)), ((0, 1),), ())
    mesh.update()
    source = bpy.data.objects.new("MeshXpbdObjectAuthoring", mesh)
    bpy.context.scene.collection.objects.link(source)
    try:
        pin = source.vertex_groups.new(name="Pin")
        pin.add((0,), 1.0, "REPLACE")
        radius = source.vertex_groups.new(name="Radius")
        radius.add((1,), 0.5, "REPLACE")
        panel = source.hotools_mesh_collision
        panel.pin_enabled = True
        panel.pin_vertex_group = pin.name
        panel.radius_vertex_group = radius.name
        panel.collided_by_groups = 0x0004

        panel_objects, panel_count = nodes.physicsMeshXpbdObject([source])
        assert panel_count == 1
        assert panel_objects[0].property_origin == "panel"
        assert panel_objects[0].properties.pin_vertex_group == "Pin"
        assert panel_objects[0].properties.collided_by_groups == 0x0004

        custom_objects, custom_count = nodes.physicsMeshXpbdCustomObject([source])
        assert custom_count == 1
        assert custom_objects[0].property_origin == "socket"
        assert custom_objects[0].properties.pin_enabled is False
        assert custom_objects[0].properties.collided_by_groups == 0

        tasks, task_count = nodes.physicsMeshXpbdTask(
            panel_objects,
            collision_enabled=True,
            collision_radius=0.1,
            iterations=8,
        )
        assert task_count == 1
        assert tasks[0].source_object is source
        assert tasks[0].pin_enabled is True
        assert tasks[0].radius_vertex_group == "Radius"
        assert tasks[0].collided_by_groups == 0x0004
        assert tasks[0].collision_radius == 0.1
        assert tasks[0].iterations == 8
    finally:
        bpy.data.objects.remove(source, do_unlink=True)
        bpy.data.meshes.remove(mesh)


if __name__ == "__main__":
    test_real_blender_panel_custom_and_task_nodes()
    print("PASS test_real_blender_panel_custom_and_task_nodes")
