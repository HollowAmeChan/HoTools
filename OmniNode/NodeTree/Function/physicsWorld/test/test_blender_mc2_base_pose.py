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
world_writeback = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback"
)
base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.base_pose"
)
frame_input = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.frame_input"
)
mc2_specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)
mc2_parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
mc2_topology = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
mc2_static = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.static_build"
)
mc2_solver = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver"
)
mc2_nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
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
    uv_layer = mesh.uv_layers.new(name="UVMap")
    uv_by_vertex = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = uv_by_vertex[loop.vertex_index]
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
    world = None
    auto_world = None
    native_owner = None
    recovered_native_owner = None
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
        assert first.source_world_linear.flags.writeable is False
        assert np.allclose(first.component_world_position, source.matrix_world.translation)
        assert np.allclose(first.component_world_scale, (1.0, 1.0, 1.0))
        assert np.allclose(first.animated_base_world_positions[:, 0], (0.5, 1.5, 0.5))

        task = mc2_specs.make_mc2_task_spec("mesh_cloth", [source])
        topology = mc2_topology.build_mc2_topology_spec(task)
        static_signature = mc2_static.mesh_cloth_static_input_signature_for_task(
            task, topology
        )
        gravity_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                gravity_direction=(1.0, 0.0, 0.0)
            ),
        )
        assert mc2_static.mesh_cloth_static_input_signature_for_task(
            gravity_task, topology
        ) != static_signature
        static = mc2_static.build_mc2_mesh_cloth_static_for_task(task, topology)
        first_input = frame_input.build_mc2_mesh_frame_input(
            first,
            static,
            topology_signature=topology.topology_signature,
        )
        assert first_input.world_rotations_xyzw.shape == (3, 4)
        assert first_input.world_rotations_xyzw.flags.writeable is False
        assert first_input.center_frame_pose is not None
        assert first_input.center_frame_pose.frame == first_input.frame
        assert first_input.center_frame_pose.component_identity == f"object:{source.as_pointer()}"
        assert np.allclose(
            np.linalg.norm(first_input.world_rotations_xyzw, axis=1),
            1.0,
        )

        world = world_types.PhysicsWorldCache()
        world.generation = 1
        world.frame_context.frame = 1
        _, ready, _ = mc2_solver.step_mc2(
            world,
            [task],
            frame_inputs={task.task_id: first_input},
        )
        assert ready is True
        slot = world.solver_slots[task.task_id]
        runtime_state = slot.data["runtime_state"]
        particle_buffer = slot.data["particle_buffer"]
        center_runtime = slot.data["center_state"]
        native_owner = slot.data["native_context"]
        native_info = native_owner.inspect()
        assert native_info["proxy_static_ready"] is True
        assert native_info["baseline_static_ready"] is True
        assert native_info["proxy_static_revision"] == 1
        assert native_info["baseline_static_revision"] == 1
        assert native_info["edge_count"] == 3
        assert native_info["triangle_count"] == 1
        assert native_info["baseline_count"] == len(
            static.baseline.baseline.baseline_ranges
        )
        assert native_info["distance_static_ready"] is True
        assert native_info["bending_static_ready"] is True
        assert native_info["center_static_ready"] is True
        assert native_info["center_static_revision"] == 1
        assert native_info["center_fixed_count"] == len(static.center.fixed_indices)
        assert native_info["distance_record_count"] == len(
            static.distance.distance_targets
        )
        assert native_info["bending_record_count"] == (
            static.bending.record_count if static.bending is not None else 0
        )
        assert native_info["parameter_revision"] == 1
        assert native_info["dynamic_revision"] == 1
        assert native_info["reset_count"] == 1
        assert native_info["step_count"] == 0
        assert center_runtime.initialized is True
        assert center_runtime.reset_count == 1
        assert center_runtime.last_frame == first_input.frame
        assert slot.data["center_step_result"] is None
        candidate = slot.data["result_candidate"]
        assert candidate.ready is False
        assert candidate.revision == 1
        assert candidate.frame == first_input.frame
        assert candidate.generation == first_input.generation
        assert candidate.world_generation == world.generation
        assert candidate.world_positions.flags.writeable is False
        assert candidate.world_rotations_xyzw.flags.writeable is False
        np.testing.assert_allclose(candidate.mesh_object_local_offsets, 0.0, atol=1.0e-6)
        public_results = world.consume_results(
            world_names.GN_ATTRIBUTE_CHANNEL,
            solver="mc2",
            frame=1,
            generation=1,
        )
        assert len(public_results) == 1
        assert public_results[0]["ready"] is True
        assert public_results[0]["revision"] == 1
        assert public_results[0]["frame_generation"] == first_input.generation
        assert public_results[0]["local_offsets"].flags.writeable is False
        assert world_writeback.writeback_gn_attributes(world) == 1
        written_offsets = source.data.attributes[world_names.GN_OFFSET_ATTRIBUTE_NAME]
        written_values = np.empty(len(source.data.vertices) * 3, dtype=np.float32)
        written_offsets.data.foreach_get("vector", written_values)
        np.testing.assert_allclose(written_values, 0.0, atol=1.0e-6)
        snapshot = slot.debug_snapshot()
        assert snapshot["result_candidate"]["revision"] == 1
        assert snapshot["result_candidate"]["ready"] is False
        assert runtime_state.initialized is True
        assert runtime_state.last_reset_reason == "first_valid_pose"
        assert runtime_state.reset_count == particle_buffer.reset_count == 1
        np.testing.assert_array_equal(
            particle_buffer.next_positions,
            first.animated_base_world_positions,
        )
        mc2_solver.step_mc2(
            world,
            [task],
            frame_inputs={task.task_id: first_input},
        )
        assert runtime_state.frame_revision == 1
        assert runtime_state.reset_count == 1
        assert native_owner.inspect()["dynamic_revision"] == 1
        assert slot.data["result_candidate"] is candidate
        assert slot.data["result_candidate_revision"] == 1
        same_frame_results = world.consume_results(
            world_names.GN_ATTRIBUTE_CHANNEL,
            solver="mc2",
        )
        assert len(same_frame_results) == 1
        assert same_frame_results[0]["revision"] == 1

        history_before_parameter_update = particle_buffer.next_positions.copy()
        soft_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(damping=0.2),
        )
        mc2_solver.step_mc2(
            world,
            [soft_task],
            frame_inputs={soft_task.task_id: first_input},
        )
        assert slot.data["runtime_state"] is runtime_state
        assert runtime_state.parameter_revision == 1
        assert runtime_state.reset_count == 1
        native_info = native_owner.inspect()
        assert native_info["parameter_revision"] == 2
        assert native_info["dynamic_revision"] == 1
        assert native_info["reset_count"] == 1
        np.testing.assert_array_equal(
            particle_buffer.next_positions,
            history_before_parameter_update,
        )
        assert slot.data["result_candidate"] is candidate

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
        second_input = frame_input.build_mc2_mesh_frame_input(
            second,
            static,
            topology_signature=topology.topology_signature,
        )
        world.frame_context.frame = 2
        mc2_solver.step_mc2(
            world,
            [soft_task],
            frame_inputs={soft_task.task_id: second_input},
        )
        assert runtime_state.last_reset_reason == "frame_generation_changed"
        assert runtime_state.reset_count == particle_buffer.reset_count == 2
        native_info = native_owner.inspect()
        assert native_info["dynamic_revision"] == 2
        assert native_info["reset_count"] == 2
        assert native_info["step_count"] == 0
        assert center_runtime.reset_count == 2
        assert center_runtime.last_frame == second_input.frame
        second_candidate = slot.data["result_candidate"]
        assert second_candidate.revision == 2
        assert second_candidate.frame == second_input.frame
        assert second_candidate is not candidate
        second_results = world.consume_results(
            world_names.GN_ATTRIBUTE_CHANNEL,
            solver="mc2",
        )
        assert len(second_results) == 1
        assert second_results[0]["revision"] == 2
        assert second_results[0]["frame_generation"] == second_input.generation
        np.testing.assert_array_equal(
            particle_buffer.next_positions,
            second.animated_base_world_positions,
        )
        third_input = frame_input.make_mc2_frame_input(
            task_id=second_input.task_id,
            topology_signature=second_input.topology_signature,
            frame=3,
            generation=second_input.generation,
            world_positions=second_input.world_positions,
            world_rotations_xyzw=second_input.world_rotations_xyzw,
            source_world_linear=second_input.source_world_linear,
            center_frame_pose=type(second_input.center_frame_pose)(
                frame=3,
                generation=second_input.generation,
                component_identity=second_input.center_frame_pose.component_identity,
                component_world_position=(
                    second_input.center_frame_pose.component_world_position[0] + 0.25,
                    second_input.center_frame_pose.component_world_position[1],
                    second_input.center_frame_pose.component_world_position[2],
                ),
                component_world_rotation_xyzw=(
                    second_input.center_frame_pose.component_world_rotation_xyzw
                ),
                component_world_scale=second_input.center_frame_pose.component_world_scale,
            ),
        )
        world.frame_context.frame = 3
        mc2_solver.step_mc2(
            world,
            [soft_task],
            frame_inputs={soft_task.task_id: third_input},
            dt=1.0 / 60.0,
        )
        native_info = native_owner.inspect()
        assert native_info["dynamic_revision"] == 3
        assert native_info["reset_count"] == 2
        assert native_info["step_count"] == 1
        assert native_info["center_dynamic_revision"] == 1
        assert native_info["center_step_count"] == 1
        assert native_info["distance_solve_count"] == 1
        center_result = slot.data["center_step_result"]
        assert center_result is not None
        np.testing.assert_allclose(center_result.step_vector, (0.25, 0.0, 0.0), atol=1.0e-6)
        assert center_runtime.last_frame == third_input.frame
        assert center_runtime.old_world_position == center_result.now_world_position
        assert slot.debug_snapshot()["center_step_result"] is not None
        third_candidate = slot.data["result_candidate"]
        assert third_candidate.revision == 3
        assert third_candidate.frame == third_input.frame
        assert third_candidate.native_step_count == 1
        third_results = world.consume_results(
            world_names.GN_ATTRIBUTE_CHANNEL,
            solver="mc2",
        )
        assert len(third_results) == 1
        assert third_results[0]["revision"] == 3
        assert third_results[0]["native_step_count"] == 1

        native_owner.dispose()
        _, _, status = mc2_solver.step_mc2(
            world,
            [soft_task],
            frame_inputs={soft_task.task_id: third_input},
            dt=1.0 / 60.0,
        )
        assert "重建 1" in status
        recovered_native_owner = world.solver_slots[soft_task.task_id].data["native_context"]
        assert recovered_native_owner is not native_owner
        recovered_info = recovered_native_owner.inspect()
        assert recovered_info["dynamic_revision"] == 1
        assert recovered_info["reset_count"] == 1
        assert recovered_info["step_count"] == 0
        recovered_candidate = world.solver_slots[soft_task.task_id].data["result_candidate"]
        assert recovered_candidate.revision == 1
        assert recovered_candidate.frame == third_input.frame
        recovered_results = world.consume_results(
            world_names.GN_ATTRIBUTE_CHANNEL,
            solver="mc2",
        )
        assert len(recovered_results) == 1
        assert recovered_results[0]["revision"] == 1

        auto_world = world_types.PhysicsWorldCache()
        auto_world.generation = 9
        auto_world.frame_context.frame = 10
        auto_world.frame_context.generation = 9
        auto_world.frame_context.dt = 1.0 / 60.0
        _, auto_ready, _ = mc2_nodes.physicsMC2Step(auto_world, [task])
        assert auto_ready is True
        auto_slot = auto_world.solver_slots[task.task_id]
        auto_native = auto_slot.data["native_context"]
        auto_candidate = auto_slot.data["result_candidate"]
        assert auto_candidate.frame == 10
        assert auto_candidate.generation == 9
        assert auto_candidate.world_generation == 9
        assert auto_candidate.revision == 1
        assert auto_native.inspect()["reset_count"] == 1
        assert auto_world.runtime_caches

        mc2_nodes.physicsMC2Step(auto_world, [task])
        assert auto_slot.data["result_candidate"] is auto_candidate
        assert auto_native.inspect()["dynamic_revision"] == 1
        assert auto_native.inspect()["step_count"] == 0

        armature_obj.pose.bones["BasePoseBone"].location.x += 0.25
        _update_depsgraph()
        auto_world.frame_context.frame = 11
        _, auto_ready, _ = mc2_nodes.physicsMC2Step(auto_world, [task])
        assert auto_ready is True
        auto_next_candidate = auto_slot.data["result_candidate"]
        assert auto_next_candidate.revision == 2
        assert auto_next_candidate.frame == 11
        assert auto_native.inspect()["dynamic_revision"] == 2
        assert auto_native.inspect()["step_count"] == 1
        auto_results = auto_world.consume_results(
            world_names.GN_ATTRIBUTE_CHANNEL,
            solver="mc2",
            frame=11,
            generation=9,
        )
        assert len(auto_results) == 1
        assert auto_results[0]["revision"] == 2

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
        if world is not None:
            world.omni_cache_dispose("test_complete")
        if auto_world is not None:
            auto_world.omni_cache_dispose("test_complete")
        if native_owner is not None:
            assert native_owner.inspect()["released"] is True
        if recovered_native_owner is not None:
            assert recovered_native_owner.inspect()["released"] is True
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
