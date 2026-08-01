"""Mesh XPBD 对象/任务节点的真实 Blender PropertyGroup 验收。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import numpy as np


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
node_core = importlib.import_module("HoTools.OmniNode.FunctionNodeCore")
world_types = importlib.import_module("HoTools.OmniNode.PhysicsWorld.types")
xpbd_names = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mesh_xpbd.names")
xpbd_debug = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mesh_xpbd.debug")
xpbd_debug_draw = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.debug_draw"
)


def test_node_socket_annotations_are_resolved():
    _, object_inputs, object_outputs, _, object_multi, _ = node_core.CheckMetaInfo(
        nodes.physicsMeshXpbdObject
    )
    assert object_inputs["mesh_objects"]["type"] == "NodeSocketObject"
    assert object_inputs["mesh_objects"]["use_multi_input"] is True
    assert object_outputs["_OUTPUT0"]["type"] == "OmniNodeSocketAny"
    assert object_multi["_OUTPUT0"] is True
    assert object_outputs["_OUTPUT1"]["type"] == "NodeSocketInt"

    _, task_inputs, task_outputs, _, task_multi, _ = node_core.CheckMetaInfo(
        nodes.physicsMeshXpbdTask
    )
    assert task_inputs["mesh_objects"]["type"] == "OmniNodeSocketAny"
    assert task_inputs["mesh_objects"]["use_multi_input"] is True
    assert task_inputs["collision_enabled"]["type"] == "NodeSocketBool"
    assert task_inputs["collision_radius"]["type"] == "NodeSocketFloat"
    assert task_inputs["iterations"]["type"] == "NodeSocketInt"
    assert task_inputs["gravity_direction"]["type"] == "NodeSocketVector"
    assert task_outputs["_OUTPUT0"]["type"] == "OmniNodeSocketAny"
    assert task_multi["_OUTPUT0"] is True

    _, solver_inputs, solver_outputs, _, solver_multi, _ = node_core.CheckMetaInfo(
        nodes.physicsMeshXpbdSolver
    )
    assert solver_inputs["world"]["type"] == "OmniNodeSocketAny"
    assert solver_inputs["mesh_tasks"]["type"] == "OmniNodeSocketAny"
    assert solver_inputs["mesh_tasks"]["use_multi_input"] is True
    assert solver_inputs["debug_capture"]["type"] == "NodeSocketBool"
    assert solver_outputs["_OUTPUT0"]["type"] == "OmniNodeSocketAny"
    assert solver_outputs["_OUTPUT1"]["type"] == "NodeSocketInt"
    assert solver_outputs["_OUTPUT2"]["type"] == "NodeSocketFloat"
    assert solver_multi["mesh_tasks"] is True

    _, debug_inputs, debug_outputs, _, _, _ = node_core.CheckMetaInfo(
        nodes.physicsMeshXpbdDebugDraw
    )
    assert debug_inputs["world"]["type"] == "OmniNodeSocketAny"
    assert debug_inputs["show_particles"]["type"] == "NodeSocketBool"
    assert debug_inputs["constraint_tolerance"]["type"] == "NodeSocketFloat"
    assert debug_outputs["_OUTPUT0"]["type"] == "OmniNodeSocketAny"
    assert debug_outputs["_OUTPUT1"]["type"] == "NodeSocketString"


def test_debug_draw_node_builds_all_view_batches_and_clears_on_disable():
    world = world_types.PhysicsWorldCache()
    world.frame_context.frame = 12
    slot = world.ensure_solver_slot("mesh_xpbd:test:debug", xpbd_names.MESH_XPBD_SLOT_KIND)
    slot.data["source_name"] = "DebugMesh"
    slot.data["debug_summary"] = {"decision": "step"}
    slot.data["debug_capture"] = {
        "world_positions": np.asarray(
            ((0, 0, 0), (1.2, 0, 0), (0, 1, 0), (1, 1, 0)),
            dtype=np.float32,
        ),
        "rest_world_positions": np.asarray(
            ((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)),
            dtype=np.float32,
        ),
        "local_offsets": np.asarray(
            ((0, 0, 0), (0.2, 0, 0), (0, 0, 0), (0, 0, 0)),
            dtype=np.float32,
        ),
        "stretch_indices": np.asarray(((0, 1), (0, 2), (1, 3), (2, 3)), dtype=np.int32),
        "loop_triangles": np.asarray(((0, 1, 2), (1, 3, 2)), dtype=np.int32),
        "bend_indices": np.asarray(((1, 2),), dtype=np.int32),
        "inverse_masses": np.asarray((0, 1, 1, 1), dtype=np.float32),
        "world_collision_radii": np.asarray((0.1, 0.1, 0.1, 0.1), dtype=np.float32),
        "collider_types": np.asarray((0, 1, 2, 3), dtype=np.int32),
        "collider_group_bits": np.asarray((1, 1, 1, 1), dtype=np.int32),
        "collider_keys": ("sphere", "capsule", "plane", "box"),
        "collider_centers": np.asarray(
            ((0, 0, 0), (2, 0, 0), (0, 0, -0.1), (3, 0, 0)),
            dtype=np.float32,
        ),
        "collider_segment_a": np.asarray(
            ((0, 0, 0), (2, -0.5, 0), (0, 0, 1), (0.25, 0, 0)),
            dtype=np.float32,
        ),
        "collider_segment_b": np.asarray(
            ((0, 0, 0), (2, 0.5, 0), (0, 0, 0), (0, 0.25, 0)),
            dtype=np.float32,
        ),
        "collider_radii": np.asarray((0.2, 0.1, 0.0, 0.25), dtype=np.float32),
        "task": {"gravity_direction": (0, 0, -1), "gravity_power": 9.8},
    }
    slot.data[xpbd_debug.MESH_XPBD_DEBUG_CAPTURE_SOURCE_KEY] = "draw"
    returned_world, status = nodes.physicsMeshXpbdDebugDraw(
        world,
        show_particles=True,
        show_surface=True,
        show_stretch=True,
        show_bend=True,
        show_offsets=True,
        show_normals=True,
        show_gravity=True,
        show_radii=True,
        show_colliders=True,
        show_contacts=True,
    )
    assert returned_world is world
    assert "DebugMesh" in status
    snapshot = xpbd_debug_draw.mesh_xpbd_debug_draw_store_snapshot(str(id(world)))
    assert snapshot["line_batch_count"] >= 8
    assert snapshot["point_batch_count"] >= 3
    assert snapshot["triangle_batch_count"] == 1
    assert snapshot["triangle_count"] == 2
    assert xpbd_debug.mesh_xpbd_debug_capture_requested(slot) is True

    nodes.physicsMeshXpbdDebugDraw(world)
    assert xpbd_debug_draw.mesh_xpbd_debug_draw_store_snapshot(str(id(world))) is None
    assert xpbd_debug.mesh_xpbd_debug_capture_requested(slot) is False
    assert "debug_capture" not in slot.data


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
        assert panel.enabled is False
        disabled_objects, disabled_count = nodes.physicsMeshXpbdObject([source])
        assert disabled_objects == [] and disabled_count == 0
        panel.enabled = True
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
    test_node_socket_annotations_are_resolved()
    test_debug_draw_node_builds_all_view_batches_and_clears_on_disable()
    test_real_blender_panel_custom_and_task_nodes()
    print("PASS test_node_socket_annotations_are_resolved")
    print("PASS test_debug_draw_node_builds_all_view_batches_and_clears_on_disable")
    print("PASS test_real_blender_panel_custom_and_task_nodes")
