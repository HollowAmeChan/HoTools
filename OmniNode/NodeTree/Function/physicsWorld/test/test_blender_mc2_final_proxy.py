# -*- coding: utf-8 -*-
"""Blender adapter regression tests for MC2 MeshCloth final-proxy extraction."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy


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


base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.base_pose"
)
final_proxy = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.final_proxy"
)
mc2_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names"
)
mc2_native = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.native_context"
)
mc2_parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
mc2_solver = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver"
)
mc2_specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)


def _register_mesh_collision_properties():
    properties = importlib.import_module(
        "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.properties"
    )
    cls = properties.PG_Hotools_MeshCollision
    registered_class = not hasattr(bpy.types, cls.__name__)
    if registered_class:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            registered_class = False
    registered_binding = not hasattr(bpy.types.Object, "hotools_mesh_collision")
    if registered_binding:
        bpy.types.Object.hotools_mesh_collision = bpy.props.PointerProperty(type=cls)

    def cleanup():
        if registered_binding and hasattr(bpy.types.Object, "hotools_mesh_collision"):
            del bpy.types.Object.hotools_mesh_collision
        if registered_class and hasattr(bpy.types, cls.__name__):
            bpy.utils.unregister_class(cls)

    return cleanup


def _assign_identity_uvs(mesh) -> None:
    uv_layer = mesh.uv_layers.new(name="MC2_UV")
    coords = {
        0: (0.0, 0.0),
        1: (1.0, 0.0),
        2: (1.0, 1.0),
        3: (0.0, 1.0),
    }
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = coords[vertex_index]


def _make_object(name: str, faces) -> object:
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ),
        (),
        faces,
    )
    mesh.update()
    _assign_identity_uvs(mesh)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _remove_object(obj) -> None:
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def test_ngon_proxy_keeps_original_vertices() -> None:
    obj = _make_object("MC2_FinalProxyNgon", ((0, 1, 2, 3),))
    try:
        topology_signature = base_pose.mesh_topology_signature(obj)
        result = final_proxy.build_blender_mesh_final_proxy(
            obj,
            task_id="mc2:mesh_cloth:blender_ngon",
            expected_mesh_topology_signature=topology_signature,
        )

        assert result.proxy.vertex_count == 4
        assert len(result.proxy.triangles) == 2
        assert max(max(triangle) for triangle in result.proxy.triangles) == 3
        assert tuple(result.proxy.vertex_identities) == (
            "mesh:v0",
            "mesh:v1",
            "mesh:v2",
            "mesh:v3",
        )
    finally:
        _remove_object(obj)


def test_vertex_group_pin_uses_same_vertex_indices() -> None:
    obj = _make_object("MC2_FinalProxyPin", ((0, 1, 2, 3),))
    try:
        group = obj.vertex_groups.new(name="Pin")
        group.add((1, 3), 1.0, "REPLACE")

        result = final_proxy.build_blender_mesh_final_proxy(
            obj,
            task_id="mc2:mesh_cloth:blender_pin",
            pin_enabled=True,
            pin_vertex_group="Pin",
        )

        assert list(result.proxy.vertex_attributes) == [0x82, 0x81, 0x82, 0x81]
    finally:
        _remove_object(obj)


def test_shared_vertex_with_multiple_loop_uvs_is_rejected() -> None:
    obj = _make_object("MC2_FinalProxyUvSeam", ((0, 1, 2), (0, 2, 3)))
    try:
        uv_layer = obj.data.uv_layers.active
        for polygon in obj.data.polygons:
            for loop_index in polygon.loop_indices:
                if obj.data.loops[loop_index].vertex_index == 0 and polygon.index == 1:
                    uv_layer.data[loop_index].uv = (0.25, 0.25)

        try:
            final_proxy.build_blender_mesh_final_proxy(
                obj,
                task_id="mc2:mesh_cloth:blender_uv_seam",
            )
        except ValueError as exc:
            assert "multiple loop UVs" in str(exc)
            assert "split the proxy vertex" in str(exc)
        else:
            raise AssertionError("UV seam on one Blender vertex must be rejected")
    finally:
        _remove_object(obj)


def test_mc2_slot_rebuild_caches_mesh_static_data() -> None:
    obj = _make_object("MC2_FinalProxySlot", ((0, 1, 2, 3),))
    try:
        world = world_types.PhysicsWorldCache()
        task = mc2_specs.make_mc2_task_spec(mc2_names.MC2_SETUP_MESH_CLOTH, [obj])

        returned, ready, _status = mc2_solver.step_mc2(world, [task])
        slot = world.solver_slots[task.task_id]
        mesh_static = slot.data.get("mesh_static")

        assert returned is world
        assert ready is False
        assert mesh_static is not None
        assert mesh_static.final_proxy.vertex_count == 4
        assert len(mesh_static.final_proxy.triangles) == 2
        assert mesh_static.distance.vertex_count == 4
        assert mesh_static.distance.record_count > 0
        assert mesh_static.bending is not None
        assert mesh_static.bending.vertex_count == 4
        assert mesh_static.bending.record_count > 0
        assert mesh_static.finalizer.finalizer.native_owned is True
        assert mesh_static.finalizer.finalizer.every_vertex_has_triangle is True
        assert not hasattr(mesh_static.finalizer.finalizer, "vertex_to_vertex_data")
        native_info = slot.data["native_context"].inspect()
        assert native_info["tether_enabled"] is True
        assert native_info["tether_solve_count"] == 0
        snapshot = slot.debug_snapshot()["mesh_static"]
        assert snapshot["vertex_count"] == 4
        assert snapshot["distance_record_count"] == mesh_static.distance.record_count
        assert snapshot["distance_signature"] == mesh_static.distance.distance_signature
        assert snapshot["bending_record_count"] == mesh_static.bending.record_count
        assert snapshot["bending_signature"] == mesh_static.bending.bending_signature
    finally:
        _remove_object(obj)


def test_mc2_slot_rebuilds_when_pin_or_uv_static_input_changes() -> None:
    cleanup_properties = _register_mesh_collision_properties()
    obj = _make_object("MC2_FinalProxyStaticDirty", ((0, 1, 2, 3),))
    world = None
    latest_native = None
    try:
        group = obj.vertex_groups.new(name="Pin")
        group.add((0,), 1.0, "REPLACE")
        properties = obj.hotools_mesh_collision
        properties.pin_enabled = True
        properties.pin_vertex_group = "Pin"

        world = world_types.PhysicsWorldCache()
        task = mc2_specs.make_mc2_task_spec(mc2_names.MC2_SETUP_MESH_CLOTH, [obj])
        mc2_solver.step_mc2(world, [task])
        slot = world.solver_slots[task.task_id]
        first_static = slot.data["mesh_static"]
        first_native = slot.data["native_context"]
        first_input_signature = slot.data["static_input_fingerprint"].overall
        assert slot.data["last_static_change_mask"] == mc2_native.MC2_STATIC_CHANGE_ALL
        assert sum(
            bool(value & 0x01) for value in first_static.final_proxy.vertex_attributes
        ) == 1

        mc2_solver.step_mc2(world, [task])
        slot = world.solver_slots[task.task_id]
        assert slot.data["native_context"] is first_native
        assert slot.data["last_static_change_mask"] == 0

        group.add((2,), 1.0, "REPLACE")
        _world, _ready, status = mc2_solver.step_mc2(world, [task])
        slot = world.solver_slots[task.task_id]
        second_static = slot.data["mesh_static"]
        second_native = slot.data["native_context"]
        second_input_signature = slot.data["static_input_fingerprint"].overall
        assert "重建 1" in status
        assert second_native is not first_native
        assert first_native.inspect()["released"] is True
        assert second_native.inspect()["tether_enabled"] is True
        assert slot.data["runtime_state"].allocation_reason == "static_input_changed"
        assert slot.data["runtime_state"].last_reset_reason == "allocation_pending"
        assert slot.data["last_static_change_mask"] == mc2_native.MC2_STATIC_CHANGE_SURFACE
        assert second_input_signature != first_input_signature
        assert second_static.distance.distance_signature != first_static.distance.distance_signature
        assert second_static.bending is not None
        assert first_static.bending is not None
        assert second_static.bending.bending_signature != first_static.bending.bending_signature
        assert sum(
            bool(value & 0x01) for value in second_static.final_proxy.vertex_attributes
        ) == 2

        uv_layer = obj.data.uv_layers.active
        for item in uv_layer.data:
            item.uv.x += 0.125
        _world, _ready, status = mc2_solver.step_mc2(world, [task])
        slot = world.solver_slots[task.task_id]
        latest_native = slot.data["native_context"]
        assert "重建 1" in status
        assert latest_native is not second_native
        assert second_native.inspect()["released"] is True
        assert latest_native.inspect()["tether_enabled"] is True
        assert slot.data["runtime_state"].allocation_reason == "static_input_changed"
        assert slot.data["runtime_state"].last_reset_reason == "allocation_pending"
        assert slot.data["last_static_change_mask"] == mc2_native.MC2_STATIC_CHANGE_SURFACE
        assert slot.data["static_input_fingerprint"].overall != second_input_signature
        assert slot.data["mesh_static"].bending.bending_signature != second_static.bending.bending_signature

        topology_token = slot.data["mesh_static"].mesh_topology_signature
        previous_signature = slot.data["static_input_fingerprint"].overall
        previous_native = latest_native
        mesh = obj.data
        mesh.clear_geometry()
        mesh.from_pydata(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
                (0.0, 1.0, 0.0),
            ),
            (),
            ((0, 1, 3), (1, 2, 3)),
        )
        mesh.update()
        while mesh.uv_layers:
            mesh.uv_layers.remove(mesh.uv_layers[0])
        _assign_identity_uvs(mesh)
        group = obj.vertex_groups.get("Pin") or obj.vertex_groups.new(name="Pin")
        group.add((0, 2), 1.0, "REPLACE")
        _world, _ready, status = mc2_solver.step_mc2(world, [task])
        slot = world.solver_slots[task.task_id]
        latest_native = slot.data["native_context"]
        assert "重建 1" in status
        assert previous_native.inspect()["released"] is True
        assert slot.data["static_input_fingerprint"].overall != previous_signature
        assert slot.data["mesh_static"].mesh_topology_signature != topology_token
        assert slot.data["last_static_change_mask"] & mc2_native.MC2_STATIC_CHANGE_TOPOLOGY
    finally:
        if world is not None:
            world.omni_cache_dispose("test_complete")
        if latest_native is not None:
            assert latest_native.inspect()["released"] is True
        _remove_object(obj)
        cleanup_properties()


def test_active_world_mesh_step_requires_configured_base_pose() -> None:
    cleanup_properties = _register_mesh_collision_properties()
    obj = _make_object("MC2_MissingBasePose", ((0, 1, 2, 3),))
    world = world_types.PhysicsWorldCache()
    try:
        world.generation = 1
        world.frame_context.frame = 1
        world.frame_context.generation = 1
        task = mc2_specs.make_mc2_task_spec(mc2_names.MC2_SETUP_MESH_CLOTH, [obj])
        try:
            mc2_solver.step_mc2(world, [task])
        except ValueError as exc:
            assert "BasePose proxy" in str(exc)
        else:
            raise AssertionError("active MC2 Mesh step accepted a missing BasePose proxy")
        assert world.solver_slots == {}
        assert world.result_streams == {}
    finally:
        world.omni_cache_dispose("test_complete")
        _remove_object(obj)
        cleanup_properties()


def test_mc2_static_config_change_reuses_topology() -> None:
    obj = _make_object("MC2_StaticConfigDirty", ((0, 1, 2, 3),))
    world = world_types.PhysicsWorldCache()
    try:
        task = mc2_specs.make_mc2_task_spec(mc2_names.MC2_SETUP_MESH_CLOTH, [obj])
        mc2_solver.step_mc2(world, [task])
        slot = world.solver_slots[task.task_id]
        first_topology = slot.data["topology"]
        first_native = slot.data["native_context"]

        changed_task = mc2_specs.make_mc2_task_spec(
            mc2_names.MC2_SETUP_MESH_CLOTH,
            [obj],
            profile=mc2_parameters.make_mc2_particle_profile(
                gravity_direction=(0.0, -1.0, 0.0),
            ),
        )
        mc2_solver.step_mc2(world, [changed_task])
        slot = world.solver_slots[task.task_id]
        assert slot.data["topology"] is first_topology
        assert slot.data["native_context"] is not first_native
        assert first_native.inspect()["released"] is True
        assert slot.data["runtime_state"].allocation_reason == "static_input_changed"
        assert slot.data["last_static_change_mask"] == mc2_native.MC2_STATIC_CHANGE_CONFIG
        config_info = slot.data["native_context"].inspect()
        assert config_info["static_clone_count"] == 5
        assert config_info["center_static_rebuild_count"] == 1
        assert config_info["owned_static_take_count"] == 0

        cold_world = world_types.PhysicsWorldCache()
        try:
            mc2_solver.step_mc2(cold_world, [changed_task])
            cold_static = cold_world.solver_slots[task.task_id].data["mesh_static"]
            incremental_static = slot.data["mesh_static"]
            assert incremental_static.center == cold_static.center
            assert incremental_static.debug_dict() == cold_static.debug_dict()
        finally:
            cold_world.omni_cache_dispose("config_cold_compare")
    finally:
        world.omni_cache_dispose("test_complete")
        _remove_object(obj)


TESTS = (
    ("n-gon final proxy keeps original vertices", test_ngon_proxy_keeps_original_vertices),
    ("vertex group pin uses same indices", test_vertex_group_pin_uses_same_vertex_indices),
    ("shared vertex UV seam is rejected", test_shared_vertex_with_multiple_loop_uvs_is_rejected),
    ("MC2 slot caches mesh static data", test_mc2_slot_rebuild_caches_mesh_static_data),
    ("MC2 slot rebuilds for Pin/UV static changes", test_mc2_slot_rebuilds_when_pin_or_uv_static_input_changes),
    ("MC2 static config reuses topology", test_mc2_static_config_change_reuses_topology),
    ("active MC2 Mesh step requires BasePose", test_active_world_mesh_step_requires_configured_base_pose),
)


def main() -> None:
    passed = 0
    for name, test in TESTS:
        test()
        passed += 1
        print(f"[PASS] {name}")
    print(f"{passed}/{len(TESTS)} passed")


if __name__ == "__main__":
    main()
