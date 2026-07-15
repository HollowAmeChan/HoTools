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
mc2_center = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.center_state"
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
    fixed_world = None
    scheduler_world = None
    keep_world = None
    reset_world = None
    reset_negative_world = None
    keep_negative_world = None
    baseline_negative_world = None
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

        source.scale = (-1.0, 1.0, 1.0)
        negative_depsgraph = _update_depsgraph()
        negative_snapshot = frame_input.read_base_pose_frame_snapshot(
            source,
            base_obj,
            mesh_topology_signature=topology_signature,
            frame=12,
            generation=3,
            depsgraph=negative_depsgraph,
            cache={},
        )
        np.testing.assert_allclose(
            negative_snapshot.component_world_scale,
            (-1.0, 1.0, 1.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            negative_snapshot.component_world_rotation_xyzw,
            (0.0, 0.0, 0.0, 1.0),
            atol=1.0e-6,
        )
        source.scale = (1.0, 1.0, 1.0)
        depsgraph = _update_depsgraph()

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

        main_settings = mc2_parameters.make_mc2_solver_settings(
            simulation_frequency=60,
            max_simulation_count_per_frame=3,
        )
        half_time_settings = mc2_parameters.make_mc2_solver_settings(
            simulation_frequency=120,
            max_simulation_count_per_frame=3,
        )
        fixed_settings = mc2_parameters.make_mc2_solver_settings(
            simulation_frequency=30,
            max_simulation_count_per_frame=3,
        )
        world = world_types.PhysicsWorldCache()
        world.generation = 1
        world.frame_context.frame = 1
        world.frame_context.raw_dt = float(
            np.nextafter(np.float32(1.0 / 60.0), np.float32(np.inf))
        )
        _, ready, _ = mc2_solver.step_mc2(
            world,
            [task],
            settings=main_settings,
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
            settings=main_settings,
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
            profile=mc2_parameters.make_mc2_particle_profile(
                damping=0.2,
                animation_pose_ratio=0.25,
                stabilization_time_after_reset=0.0,
                world_inertia=0.25,
                movement_inertia_smoothing=0.0,
                movement_speed_limit=0.1,
                rotation_speed_limit=90.0,
            ),
        )
        mc2_solver.step_mc2(
            world,
            [soft_task],
            settings=main_settings,
            frame_inputs={soft_task.task_id: first_input},
        )
        assert slot.data["runtime_state"] is runtime_state
        assert runtime_state.parameter_revision == 1
        assert runtime_state.reset_count == 1
        native_info = native_owner.inspect()
        assert native_info["parameter_revision"] == 2
        assert native_info["animation_pose_ratio"] == 0.25
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
            settings=main_settings,
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
                    0.0,
                    float(np.sin(np.pi * 0.25)),
                    0.0,
                    float(np.cos(np.pi * 0.25)),
                ),
                component_world_scale=second_input.center_frame_pose.component_world_scale,
            ),
        )
        world.frame_context.frame = 3
        mc2_solver.step_mc2(
            world,
            [soft_task],
            settings=main_settings,
            frame_inputs={soft_task.task_id: third_input},
            dt=1.0 / 60.0,
        )
        native_info = native_owner.inspect()
        assert native_info["dynamic_revision"] == 3
        assert native_info["reset_count"] == 2
        assert native_info["step_count"] == 1
        assert native_info["center_dynamic_revision"] == 1
        assert native_info["center_step_count"] == 1
        assert native_info["center_frame_shift_count"] == 1
        assert native_info["distance_solve_count"] == 2
        assert native_info["angle_solve_count"] == 0
        center_result = slot.data["center_step_result"]
        assert center_result is not None
        np.testing.assert_allclose(
            center_result.step_vector,
            (1.0 / 600.0, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            center_result.step_rotation_xyzw,
            (
                0.0,
                float(np.sin(np.radians(0.75))),
                0.0,
                float(np.cos(np.radians(0.75))),
            ),
            atol=1.0e-6,
        )
        frame_shift_result = slot.data["center_frame_shift_result"]
        assert frame_shift_result is not None
        np.testing.assert_allclose(
            frame_shift_result.frame_component_shift_vector,
            (149.0 / 600.0, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            frame_shift_result.frame_component_shift_rotation_xyzw,
            (
                0.0,
                float(np.sin(np.radians(44.25))),
                0.0,
                float(np.cos(np.radians(44.25))),
            ),
            atol=1.0e-6,
        )
        assert center_runtime.last_frame == third_input.frame
        assert center_runtime.old_world_position == center_result.now_world_position
        assert slot.debug_snapshot()["center_step_result"] is not None
        assert slot.debug_snapshot()["center_frame_shift_result"] is not None
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

        anchor_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                damping=0.2,
                stabilization_time_after_reset=0.0,
                anchor_inertia=0.25,
                world_inertia=1.0,
                movement_inertia_smoothing=0.0,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
            ),
        )
        fourth_input = frame_input.make_mc2_frame_input(
            task_id=third_input.task_id,
            topology_signature=third_input.topology_signature,
            frame=4,
            generation=third_input.generation,
            world_positions=third_input.world_positions,
            world_rotations_xyzw=third_input.world_rotations_xyzw,
            source_world_linear=third_input.source_world_linear,
            center_frame_pose=type(third_input.center_frame_pose)(
                frame=4,
                generation=third_input.generation,
                component_identity=third_input.center_frame_pose.component_identity,
                component_world_position=third_input.center_frame_pose.component_world_position,
                component_world_rotation_xyzw=(
                    0.0,
                    float(np.sin(np.pi * 0.25)),
                    0.0,
                    float(np.cos(np.pi * 0.25)),
                ),
                component_world_scale=third_input.center_frame_pose.component_world_scale,
                anchor_identity="anchor:test",
                anchor_world_position=(0.0, 0.0, 0.0),
                anchor_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
            ),
        )
        world.frame_context.frame = 4
        mc2_solver.step_mc2(
            world,
            [anchor_task],
            settings=main_settings,
            frame_inputs={anchor_task.task_id: fourth_input},
            dt=1.0 / 60.0,
        )
        native_info = native_owner.inspect()
        assert native_info["dynamic_revision"] == 4
        assert native_info["step_count"] == 2
        assert native_info["center_dynamic_revision"] == 2
        assert native_info["center_step_count"] == 2
        assert native_info["center_frame_shift_count"] == 1
        assert slot.data["center_frame_shift_result"] is None
        assert center_runtime.anchor_identity == "anchor:test"
        np.testing.assert_allclose(
            center_runtime.anchor_component_local_position,
            (0.25, 0.0, 0.0),
            atol=1.0e-6,
        )
        anchor_world_limit_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                damping=0.2,
                stabilization_time_after_reset=0.0,
                anchor_inertia=0.25,
                world_inertia=0.25,
                movement_inertia_smoothing=0.0,
                movement_speed_limit=0.5,
                rotation_speed_limit=90.0,
            ),
        )

        fifth_input = frame_input.make_mc2_frame_input(
            task_id=fourth_input.task_id,
            topology_signature=fourth_input.topology_signature,
            frame=5,
            generation=fourth_input.generation,
            world_positions=fourth_input.world_positions,
            world_rotations_xyzw=fourth_input.world_rotations_xyzw,
            source_world_linear=fourth_input.source_world_linear,
            center_frame_pose=type(fourth_input.center_frame_pose)(
                frame=5,
                generation=fourth_input.generation,
                component_identity=fourth_input.center_frame_pose.component_identity,
                component_world_position=(0.0, 0.0, 0.0),
                component_world_rotation_xyzw=(0.0, 1.0, 0.0, 0.0),
                component_world_scale=fourth_input.center_frame_pose.component_world_scale,
                anchor_identity=fourth_input.center_frame_pose.anchor_identity,
                anchor_world_position=(0.0, 0.0, 0.25),
                anchor_world_rotation_xyzw=(
                    0.0,
                    float(np.sin(np.pi * 0.25)),
                    0.0,
                    float(np.cos(np.pi * 0.25)),
                ),
            ),
        )
        world.frame_context.frame = 5
        mc2_solver.step_mc2(
            world,
            [anchor_world_limit_task],
            settings=main_settings,
            frame_inputs={anchor_world_limit_task.task_id: fifth_input},
            dt=1.0 / 60.0,
        )
        native_info = native_owner.inspect()
        assert native_info["dynamic_revision"] == 5
        assert native_info["step_count"] == 3
        assert native_info["center_dynamic_revision"] == 3
        assert native_info["center_step_count"] == 3
        assert native_info["center_frame_shift_count"] == 2
        center_result = slot.data["center_step_result"]
        assert center_result is not None
        np.testing.assert_allclose(
            center_result.step_vector,
            (-1.0 / 120.0, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            center_result.step_rotation_xyzw,
            (
                0.0,
                float(np.sin(np.radians(0.75))),
                0.0,
                float(np.cos(np.radians(0.75))),
            ),
            atol=1.0e-6,
        )
        frame_shift_result = slot.data["center_frame_shift_result"]
        assert frame_shift_result is not None
        np.testing.assert_allclose(
            frame_shift_result.frame_component_shift_vector,
            (-29.0 / 120.0, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            frame_shift_result.frame_component_shift_rotation_xyzw,
            (
                0.0,
                float(np.sin(np.radians(44.25))),
                0.0,
                float(np.cos(np.radians(44.25))),
            ),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            frame_shift_result.frame_moving_direction,
            (-1.0, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            frame_shift_result.frame_moving_speed,
            0.5,
            atol=1.0e-6,
        )
        fifth_candidate = slot.data["result_candidate"]
        assert fifth_candidate.revision == 5
        assert fifth_candidate.frame == fifth_input.frame

        smoothing_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                damping=0.2,
                stabilization_time_after_reset=0.0,
                anchor_inertia=1.0,
                world_inertia=1.0,
                movement_inertia_smoothing=0.5,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
            ),
        )
        sixth_input = frame_input.make_mc2_frame_input(
            task_id=fifth_input.task_id,
            topology_signature=fifth_input.topology_signature,
            frame=6,
            generation=fifth_input.generation,
            world_positions=fifth_input.world_positions,
            world_rotations_xyzw=fifth_input.world_rotations_xyzw,
            source_world_linear=fifth_input.source_world_linear,
            center_frame_pose=type(fifth_input.center_frame_pose)(
                frame=6,
                generation=fifth_input.generation,
                component_identity=fifth_input.center_frame_pose.component_identity,
                component_world_position=(1.0, 0.0, 0.0),
                component_world_rotation_xyzw=(0.0, 1.0, 0.0, 0.0),
                component_world_scale=fifth_input.center_frame_pose.component_world_scale,
            ),
        )
        world.frame_context.frame = 6
        mc2_solver.step_mc2(
            world,
            [smoothing_task],
            settings=main_settings,
            frame_inputs={smoothing_task.task_id: sixth_input},
            dt=1.0 / 60.0,
        )
        native_info = native_owner.inspect()
        assert native_info["dynamic_revision"] == 6
        assert native_info["step_count"] == 4
        assert native_info["center_dynamic_revision"] == 4
        assert native_info["center_step_count"] == 4
        assert native_info["center_frame_shift_count"] == 3
        frame_shift_result = slot.data["center_frame_shift_result"]
        assert frame_shift_result is not None
        np.testing.assert_allclose(
            frame_shift_result.frame_component_shift_vector,
            (0.86625, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            frame_shift_result.smoothing_velocity,
            (8.025, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            frame_shift_result.frame_moving_speed,
            8.025,
            atol=1.0e-6,
        )
        center_result = slot.data["center_step_result"]
        assert center_result is not None
        np.testing.assert_allclose(
            center_result.step_vector,
            (0.13375, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            center_runtime.smoothing_velocity,
            frame_shift_result.smoothing_velocity,
            atol=1.0e-6,
        )
        sixth_candidate = slot.data["result_candidate"]
        assert sixth_candidate.revision == 6
        assert sixth_candidate.frame == sixth_input.frame

        time_scale_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                damping=0.2,
                stabilization_time_after_reset=0.0,
                anchor_inertia=1.0,
                world_inertia=0.75,
                movement_inertia_smoothing=0.0,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
            ),
        )
        seventh_input = frame_input.make_mc2_frame_input(
            task_id=sixth_input.task_id,
            topology_signature=sixth_input.topology_signature,
            frame=7,
            generation=sixth_input.generation,
            world_positions=sixth_input.world_positions,
            world_rotations_xyzw=sixth_input.world_rotations_xyzw,
            source_world_linear=sixth_input.source_world_linear,
            center_frame_pose=type(sixth_input.center_frame_pose)(
                frame=7,
                generation=sixth_input.generation,
                component_identity=sixth_input.center_frame_pose.component_identity,
                component_world_position=(2.0, 0.0, 0.0),
                component_world_rotation_xyzw=(
                    0.0,
                    float(np.sin(np.radians(135.0))),
                    0.0,
                    float(np.cos(np.radians(135.0))),
                ),
                component_world_scale=sixth_input.center_frame_pose.component_world_scale,
            ),
        )
        world.frame_context.frame = 7
        world.frame_context.time_scale = 0.5
        mc2_solver.step_mc2(
            world,
            [time_scale_task],
            settings=half_time_settings,
            frame_inputs={time_scale_task.task_id: seventh_input},
            dt=1.0 / 120.0,
        )
        native_info = native_owner.inspect()
        assert native_info["dynamic_revision"] == 7
        assert native_info["step_count"] == 5
        assert native_info["center_dynamic_revision"] == 5
        assert native_info["center_step_count"] == 5
        assert native_info["center_frame_shift_count"] == 4
        frame_shift_result = slot.data["center_frame_shift_result"]
        assert frame_shift_result is not None
        np.testing.assert_allclose(
            frame_shift_result.frame_component_shift_vector,
            (0.625, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            frame_shift_result.frame_component_shift_rotation_xyzw,
            (
                0.0,
                float(np.sin(np.radians(28.125))),
                0.0,
                float(np.cos(np.radians(28.125))),
            ),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            frame_shift_result.frame_moving_speed,
            45.0,
            atol=1.0e-5,
        )
        center_result = slot.data["center_step_result"]
        assert center_result is not None
        np.testing.assert_allclose(
            center_result.step_vector,
            (0.375, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            center_result.step_rotation_xyzw,
            (
                0.0,
                float(np.sin(np.radians(16.875))),
                0.0,
                float(np.cos(np.radians(16.875))),
            ),
            atol=1.0e-6,
        )
        seventh_candidate = slot.data["result_candidate"]
        assert seventh_candidate.revision == 7
        assert seventh_candidate.frame == seventh_input.frame

        zero_time_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=time_scale_task.profile,
        )
        eighth_input = frame_input.make_mc2_frame_input(
            task_id=seventh_input.task_id,
            topology_signature=seventh_input.topology_signature,
            frame=8,
            generation=seventh_input.generation,
            world_positions=seventh_input.world_positions,
            world_rotations_xyzw=seventh_input.world_rotations_xyzw,
            source_world_linear=seventh_input.source_world_linear,
            center_frame_pose=type(seventh_input.center_frame_pose)(
                frame=8,
                generation=seventh_input.generation,
                component_identity=seventh_input.center_frame_pose.component_identity,
                component_world_position=(3.0, 0.0, 0.0),
                component_world_rotation_xyzw=(0.0, 0.0, 0.0, -1.0),
                component_world_scale=seventh_input.center_frame_pose.component_world_scale,
            ),
        )
        world.frame_context.frame = 8
        world.frame_context.raw_dt = float(
            np.nextafter(np.float32(1.0 / 60.0), np.float32(np.inf))
        )
        world.frame_context.dt = 0.0
        world.frame_context.time_scale = 0.0
        mc2_solver.step_mc2(
            world,
            [zero_time_task],
            settings=half_time_settings,
            frame_inputs={zero_time_task.task_id: eighth_input},
            dt=0.0,
        )
        native_info = native_owner.inspect()
        assert native_info["dynamic_revision"] == 8
        assert native_info["step_count"] == 5
        assert native_info["center_dynamic_revision"] == 5
        assert native_info["center_step_count"] == 5
        assert native_info["center_frame_shift_count"] == 5
        assert slot.data["center_step_result"] is None
        frame_shift_result = slot.data["center_frame_shift_result"]
        assert frame_shift_result is not None
        np.testing.assert_allclose(
            frame_shift_result.frame_component_shift_vector,
            (1.0, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            frame_shift_result.frame_component_shift_rotation_xyzw,
            (
                0.0,
                float(np.sin(np.radians(45.0))),
                0.0,
                float(np.cos(np.radians(45.0))),
            ),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            frame_shift_result.frame_moving_speed,
            0.0,
            atol=1.0e-6,
        )
        assert center_runtime.old_component_world_position == (3.0, 0.0, 0.0)
        assert center_runtime.last_frame == eighth_input.frame
        eighth_candidate = slot.data["result_candidate"]
        assert eighth_candidate.revision == 8
        assert eighth_candidate.frame == eighth_input.frame

        negative_scale_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                damping=0.2,
                animation_pose_ratio=1.0,
                stabilization_time_after_reset=0.0,
                anchor_inertia=1.0,
                world_inertia=1.0,
                movement_inertia_smoothing=0.0,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
            ),
        )
        negative_scale_input = frame_input.make_mc2_frame_input(
            task_id=eighth_input.task_id,
            topology_signature=eighth_input.topology_signature,
            frame=9,
            generation=eighth_input.generation,
            world_positions=eighth_input.world_positions,
            world_rotations_xyzw=eighth_input.world_rotations_xyzw,
            source_world_linear=np.diag((-1.0, 1.0, 1.0)).astype(np.float32),
            center_frame_pose=type(eighth_input.center_frame_pose)(
                frame=9,
                generation=eighth_input.generation,
                component_identity=eighth_input.center_frame_pose.component_identity,
                component_world_position=(3.0, 0.0, 0.0),
                component_world_rotation_xyzw=(0.0, 0.0, 0.0, -1.0),
                component_world_scale=(-1.0, 1.0, 1.0),
            ),
        )
        world.frame_context.frame = 9
        world.frame_context.raw_dt = float(
            np.nextafter(np.float32(1.0 / 60.0), np.float32(np.inf))
        )
        world.frame_context.dt = 1.0 / 60.0
        world.frame_context.time_scale = 1.0
        mc2_solver.step_mc2(
            world,
            [negative_scale_task],
            settings=main_settings,
            frame_inputs={negative_scale_task.task_id: negative_scale_input},
            dt=1.0 / 60.0,
        )
        native_info = native_owner.inspect()
        assert native_info["dynamic_revision"] == 9
        assert native_info["step_count"] == 6
        assert native_info["center_dynamic_revision"] == 6
        assert native_info["center_step_count"] == 6
        assert native_info["center_frame_shift_count"] == 5
        assert native_info["center_negative_scale_teleport_count"] == 1
        assert native_info["animation_pose_ratio"] == 1.0
        assert native_info["baseline_count"] == 0
        assert native_info["baseline_pose_rebuild_count"] == 0
        negative_scale_result = slot.data["center_negative_scale_result"]
        assert negative_scale_result is not None
        assert negative_scale_result.active is True
        assert negative_scale_result.negative_scale_direction == (-1.0, 1.0, 1.0)
        assert np.linalg.det(
            np.asarray(negative_scale_result.center_negative_matrix, dtype=np.float32)
        ) < 0.0
        assert slot.data["center_frame_shift_result"] is None
        assert slot.data["center_step_result"] is not None
        assert center_runtime.negative_scale_direction == (-1.0, 1.0, 1.0)
        negative_candidate = slot.data["result_candidate"]
        assert negative_candidate.revision == 9
        assert negative_candidate.frame == negative_scale_input.frame

        native_owner.dispose()
        _, _, status = mc2_solver.step_mc2(
            world,
            [negative_scale_task],
            settings=main_settings,
            frame_inputs={negative_scale_task.task_id: negative_scale_input},
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
        assert recovered_candidate.frame == negative_scale_input.frame
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
        assert world_writeback.writeback_gn_attributes(auto_world) == 1

        source.scale = (-1.0, 1.0, 1.0)
        _update_depsgraph()
        auto_world.frame_context.frame = 12
        _, auto_ready, _ = mc2_nodes.physicsMC2Step(auto_world, [task])
        assert auto_ready is True
        auto_negative_candidate = auto_slot.data["result_candidate"]
        assert auto_negative_candidate.revision == 3
        assert auto_negative_candidate.frame == 12
        auto_negative_info = auto_native.inspect()
        assert auto_negative_info["dynamic_revision"] == 3
        assert auto_negative_info["step_count"] == 3
        assert auto_negative_info["center_dynamic_revision"] == 2
        assert auto_negative_info["step_interpolation_revision"] == 1
        assert auto_negative_info["center_negative_scale_teleport_count"] == 1
        auto_negative_result = auto_slot.data["center_negative_scale_result"]
        assert auto_negative_result.active is True
        assert auto_negative_result.negative_scale_direction == (-1.0, 1.0, 1.0)
        source.scale = (1.0, 1.0, 1.0)
        _update_depsgraph()
        auto_world.frame_context.frame = 11

        valid_result = auto_results[0]
        invalid_result = dict(valid_result)
        invalid_offsets = np.zeros((len(source.data.vertices) + 1, 3), dtype=np.float32)
        invalid_offsets.flags.writeable = False
        invalid_result["vertex_count"] = len(invalid_offsets)
        invalid_result["local_offsets"] = invalid_offsets
        auto_world.clear_results(world_names.GN_ATTRIBUTE_CHANNEL, solver="mc2")
        auto_world.publish_result(
            invalid_result,
            channel=world_names.GN_ATTRIBUTE_CHANNEL,
            solver="mc2",
        )
        assert world_writeback.writeback_gn_attributes(auto_world) == 0
        assert "拓扑已变化" in auto_slot.data["_writeback_error"]
        diagnostics = world_writeback.get_gn_writeback_diagnostics(auto_world)
        assert diagnostics["written_count"] == 0
        assert diagnostics["cleared_count"] == 1
        assert any("拓扑已变化" in item["message"] for item in diagnostics["errors"])
        failed_values = np.empty(len(source.data.vertices) * 3, dtype=np.float32)
        source.data.attributes[world_names.GN_OFFSET_ATTRIBUTE_NAME].data.foreach_get(
            "vector",
            failed_values,
        )
        np.testing.assert_allclose(failed_values, 0.0, atol=1.0e-6)

        auto_world.clear_results(world_names.GN_ATTRIBUTE_CHANNEL, solver="mc2")
        auto_world.publish_result(
            valid_result,
            channel=world_names.GN_ATTRIBUTE_CHANNEL,
            solver="mc2",
        )
        assert world_writeback.writeback_gn_attributes(auto_world) == 1
        assert "_writeback_error" not in auto_slot.data

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

        source.hotools_mesh_collision.pin_enabled = True
        fixed_group = source.vertex_groups.new(name="MC2FixedCenter")
        fixed_group.add([0], 1.0, "REPLACE")
        source.hotools_mesh_collision.pin_vertex_group = fixed_group.name
        fixed_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                damping=0.2,
                animation_pose_ratio=0.25,
                stabilization_time_after_reset=0.0,
                anchor_inertia=1.0,
                world_inertia=0.25,
                movement_inertia_smoothing=0.0,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
                max_distance_enabled=True,
                max_distance=5.0,
                motion_stiffness=0.5,
            ),
        )
        fixed_topology = mc2_topology.build_mc2_topology_spec(fixed_task)
        fixed_static = mc2_static.build_mc2_mesh_cloth_static_for_task(
            fixed_task,
            fixed_topology,
        )
        assert tuple(fixed_static.center.fixed_indices) == (0,), (
            fixed_static.center.fixed_indices,
            source.hotools_mesh_collision.pin_enabled,
            source.hotools_mesh_collision.pin_vertex_group,
        )
        fixed_identity_rotations = np.tile(
            np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32),
            (3, 1),
        )
        fixed_first_positions = np.tile(
            np.asarray((1.0, 0.0, 0.0), dtype=np.float32),
            (3, 1),
        )
        component_identity = f"object:{source.as_pointer()}"
        fixed_first_input = frame_input.make_mc2_frame_input(
            task_id=fixed_task.task_id,
            topology_signature=fixed_topology.topology_signature,
            frame=20,
            generation=12,
            world_positions=fixed_first_positions,
            world_rotations_xyzw=fixed_identity_rotations,
            source_world_linear=np.eye(3, dtype=np.float32),
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=20,
                generation=12,
                component_identity=component_identity,
                component_world_position=(0.0, 0.0, 0.0),
                component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
                component_world_scale=(1.0, 1.0, 1.0),
            ),
        )
        fixed_world = world_types.PhysicsWorldCache()
        fixed_world.generation = 12
        fixed_world.frame_context.frame = 20
        fixed_world.frame_context.raw_dt = float(
            np.nextafter(np.float32(0.1), np.float32(np.inf))
        )
        mc2_solver.step_mc2(
            fixed_world,
            [fixed_task],
            settings=fixed_settings,
            frame_inputs={fixed_task.task_id: fixed_first_input},
        )
        fixed_rotation = np.asarray(
            (
                0.0,
                float(np.sin(np.radians(45.0))),
                0.0,
                float(np.cos(np.radians(45.0))),
            ),
            dtype=np.float32,
        )
        fixed_second_input = frame_input.make_mc2_frame_input(
            task_id=fixed_task.task_id,
            topology_signature=fixed_topology.topology_signature,
            frame=21,
            generation=12,
            world_positions=np.tile(
                np.asarray((12.0, 2.0, 0.0), dtype=np.float32),
                (3, 1),
            ),
            world_rotations_xyzw=np.tile(fixed_rotation, (3, 1)),
            source_world_linear=np.eye(3, dtype=np.float32),
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=21,
                generation=12,
                component_identity=component_identity,
                component_world_position=(10.0, 0.0, 0.0),
                component_world_rotation_xyzw=tuple(float(value) for value in fixed_rotation),
                component_world_scale=(1.0, 1.0, 1.0),
            ),
        )
        fixed_world.frame_context.frame = 21
        mc2_solver.step_mc2(
            fixed_world,
            [fixed_task],
            settings=fixed_settings,
            frame_inputs={fixed_task.task_id: fixed_second_input},
            dt=0.1,
        )
        fixed_slot = fixed_world.solver_slots[fixed_task.task_id]
        fixed_native_info = fixed_slot.data["native_context"].inspect()
        assert fixed_native_info["center_fixed_count"] == 1
        assert fixed_native_info["center_frame_shift_count"] == 1
        assert fixed_native_info["baseline_count"] > 0
        assert fixed_native_info["step_count"] == 3
        assert fixed_native_info["angle_solve_count"] == 3
        assert fixed_native_info["motion_solve_count"] == 3
        assert fixed_native_info["center_dynamic_revision"] == 1
        assert fixed_native_info["step_interpolation_revision"] == 2
        assert fixed_native_info["center_step_count"] == 3
        assert fixed_native_info["baseline_pose_rebuild_count"] == 3
        assert fixed_native_info["animation_pose_ratio"] == 0.25
        fixed_step_positions, _ = fixed_slot.data["native_context"].read_step_basic()
        np.testing.assert_allclose(
            fixed_step_positions[0],
            fixed_second_input.world_positions[0],
            atol=1.0e-6,
        )
        assert not np.allclose(
            fixed_step_positions[1:],
            fixed_second_input.world_positions[1:],
            atol=1.0e-6,
        )
        fixed_shift = fixed_slot.data["center_frame_shift_result"]
        assert fixed_shift is not None
        fixed_center_pose = mc2_center.derive_mc2_center_world_pose(
            fixed_static.center,
            fixed_second_input.center_frame_pose,
            world_positions=fixed_second_input.world_positions,
            world_rotations_xyzw=fixed_second_input.world_rotations_xyzw,
            vertex_bind_pose_rotations=fixed_static.finalizer.vertex_bind_pose_rotations,
        )
        np.testing.assert_allclose(
            fixed_shift.frame_component_shift_vector,
            (7.5, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            fixed_shift.frame_component_shift_rotation_xyzw,
            (
                0.0,
                float(np.sin(np.radians(33.75))),
                0.0,
                float(np.cos(np.radians(33.75))),
            ),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            fixed_shift.frame_world_position,
            (12.0, 2.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            fixed_shift.frame_world_rotation_xyzw,
            fixed_center_pose.rotation_xyzw,
            atol=1.0e-6,
        )

        fixed_animated_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                damping=0.2,
                animation_pose_ratio=1.0,
                stabilization_time_after_reset=0.0,
                anchor_inertia=1.0,
                world_inertia=0.25,
                movement_inertia_smoothing=0.0,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
            ),
        )
        fixed_third_input = frame_input.make_mc2_frame_input(
            task_id=fixed_animated_task.task_id,
            topology_signature=fixed_topology.topology_signature,
            frame=22,
            generation=12,
            world_positions=fixed_second_input.world_positions,
            world_rotations_xyzw=fixed_second_input.world_rotations_xyzw,
            source_world_linear=np.eye(3, dtype=np.float32),
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=22,
                generation=12,
                component_identity=component_identity,
                component_world_position=(10.0, 0.0, 0.0),
                component_world_rotation_xyzw=tuple(float(value) for value in fixed_rotation),
                component_world_scale=(1.0, 1.0, 1.0),
            ),
        )
        fixed_world.frame_context.frame = 22
        mc2_solver.step_mc2(
            fixed_world,
            [fixed_animated_task],
            settings=fixed_settings,
            frame_inputs={fixed_animated_task.task_id: fixed_third_input},
            dt=0.1,
        )
        fixed_hot_info = fixed_slot.data["native_context"].inspect()
        assert fixed_hot_info["step_count"] == 6
        assert fixed_hot_info["center_dynamic_revision"] == 2
        assert fixed_hot_info["step_interpolation_revision"] == 4
        assert fixed_hot_info["baseline_pose_rebuild_count"] == 3, fixed_hot_info
        assert fixed_hot_info["animation_pose_ratio"] == 1.0
        fixed_step_positions, fixed_step_rotations = fixed_slot.data[
            "native_context"
        ].read_step_basic()
        np.testing.assert_allclose(
            fixed_step_positions,
            fixed_third_input.world_positions,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            np.abs(np.sum(
                fixed_step_rotations * fixed_third_input.world_rotations_xyzw,
                axis=1,
            )),
            1.0,
            atol=1.0e-6,
        )

        skip_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                damping=0.0,
                animation_pose_ratio=0.0,
                stabilization_time_after_reset=0.0,
                anchor_inertia=1.0,
                world_inertia=1.0,
                movement_inertia_smoothing=0.0,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
            ),
        )
        skip_settings = mc2_parameters.make_mc2_solver_settings(
            simulation_frequency=50,
            max_simulation_count_per_frame=3,
        )
        skip_first_input = frame_input.make_mc2_frame_input(
            task_id=skip_task.task_id,
            topology_signature=fixed_topology.topology_signature,
            frame=30,
            generation=13,
            world_positions=fixed_first_input.world_positions,
            world_rotations_xyzw=fixed_first_input.world_rotations_xyzw,
            source_world_linear=np.eye(3, dtype=np.float32),
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=30,
                generation=13,
                component_identity=component_identity,
                component_world_position=(0.0, 0.0, 0.0),
                component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
                component_world_scale=(1.0, 1.0, 1.0),
            ),
        )
        skip_second_input = frame_input.make_mc2_frame_input(
            task_id=skip_task.task_id,
            topology_signature=fixed_topology.topology_signature,
            frame=31,
            generation=13,
            world_positions=fixed_second_input.world_positions,
            world_rotations_xyzw=fixed_second_input.world_rotations_xyzw,
            source_world_linear=np.eye(3, dtype=np.float32),
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=31,
                generation=13,
                component_identity=component_identity,
                component_world_position=(10.0, 0.0, 0.0),
                component_world_rotation_xyzw=tuple(float(value) for value in fixed_rotation),
                component_world_scale=(1.0, 1.0, 1.0),
            ),
        )
        scheduler_world = world_types.PhysicsWorldCache()
        scheduler_world.generation = 13
        scheduler_world.frame_context.frame = 30
        mc2_solver.step_mc2(
            scheduler_world,
            [skip_task],
            settings=skip_settings,
            frame_inputs={skip_task.task_id: skip_first_input},
        )
        scheduler_world.frame_context.frame = 31
        mc2_solver.step_mc2(
            scheduler_world,
            [skip_task],
            settings=skip_settings,
            frame_inputs={skip_task.task_id: skip_second_input},
            dt=0.1,
        )
        scheduler_slot = scheduler_world.solver_slots[skip_task.task_id]
        schedule = scheduler_slot.data["frame_schedule"]
        assert schedule.planned_update_count == 5
        assert schedule.update_count == 3
        assert schedule.skip_count == 2
        np.testing.assert_allclose(schedule.time, 0.0600000024, atol=1.0e-8)
        scheduler_info = scheduler_slot.data["native_context"].inspect()
        assert scheduler_info["step_count"] == 3
        assert scheduler_info["center_dynamic_revision"] == 1
        assert scheduler_info["step_interpolation_revision"] == 2
        assert scheduler_info["center_step_count"] == 3
        assert scheduler_info["center_frame_shift_count"] == 1
        scheduler_shift = scheduler_slot.data["center_frame_shift_result"]
        np.testing.assert_allclose(
            scheduler_shift.frame_component_shift_vector,
            (4.0, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            scheduler_shift.frame_component_shift_rotation_xyzw,
            (
                0.0,
                float(np.sin(np.radians(18.0))),
                0.0,
                float(np.cos(np.radians(18.0))),
            ),
            atol=1.0e-6,
        )
        scheduler_step_positions, _ = scheduler_slot.data[
            "native_context"
        ].read_step_basic()
        np.testing.assert_allclose(
            scheduler_step_positions[0],
            skip_second_input.world_positions[0],
            atol=1.0e-6,
        )
        assert scheduler_slot.data["result_candidate"].native_step_count == 3

        source.hotools_mesh_collision.pin_enabled = False
        keep_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                gravity=0.0,
                damping=0.0,
                animation_pose_ratio=0.0,
                stabilization_time_after_reset=0.0,
                anchor_inertia=1.0,
                world_inertia=1.0,
                movement_inertia_smoothing=0.5,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
                teleport_mode=2,
                teleport_distance=5.0,
                teleport_rotation=180.0,
            ),
        )
        keep_topology = mc2_topology.build_mc2_topology_spec(keep_task)
        keep_first_positions = np.asarray(
            first_input.world_positions,
            dtype=np.float32,
        )
        keep_rotation_matrix = np.asarray(
            (
                (0.0, 0.0, 1.0),
                (0.0, 1.0, 0.0),
                (-1.0, 0.0, 0.0),
            ),
            dtype=np.float32,
        )
        keep_second_positions = np.asarray(
            keep_first_positions @ keep_rotation_matrix.T
            + np.asarray((10.0, 0.0, 0.0), dtype=np.float32),
            dtype=np.float32,
        )
        keep_first_rotations = np.tile(
            np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32),
            (keep_topology.particle_count, 1),
        )
        keep_second_rotations = np.tile(
            fixed_rotation,
            (keep_topology.particle_count, 1),
        )
        keep_first_input = frame_input.make_mc2_frame_input(
            task_id=keep_task.task_id,
            topology_signature=keep_topology.topology_signature,
            frame=40,
            generation=14,
            world_positions=keep_first_positions,
            world_rotations_xyzw=keep_first_rotations,
            source_world_linear=np.eye(3, dtype=np.float32),
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=40,
                generation=14,
                component_identity=component_identity,
                component_world_position=(0.0, 0.0, 0.0),
                component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
                component_world_scale=(1.0, 1.0, 1.0),
            ),
        )
        keep_second_input = frame_input.make_mc2_frame_input(
            task_id=keep_task.task_id,
            topology_signature=keep_topology.topology_signature,
            frame=41,
            generation=14,
            world_positions=keep_second_positions,
            world_rotations_xyzw=keep_second_rotations,
            source_world_linear=keep_rotation_matrix,
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=41,
                generation=14,
                component_identity=component_identity,
                component_world_position=(10.0, 0.0, 0.0),
                component_world_rotation_xyzw=tuple(float(value) for value in fixed_rotation),
                component_world_scale=(1.0, 1.0, 1.0),
            ),
        )
        keep_world = world_types.PhysicsWorldCache()
        keep_world.generation = 14
        keep_world.frame_context.frame = 40
        keep_world.frame_context.raw_dt = float(
            np.nextafter(np.float32(0.1), np.float32(np.inf))
        )
        mc2_solver.step_mc2(
            keep_world,
            [keep_task],
            settings=fixed_settings,
            frame_inputs={keep_task.task_id: keep_first_input},
        )
        keep_slot = keep_world.solver_slots[keep_task.task_id]
        keep_slot.data["center_state"].smoothing_velocity = (2.0, 0.0, 0.0)
        keep_world.frame_context.frame = 41
        mc2_solver.step_mc2(
            keep_world,
            [keep_task],
            settings=fixed_settings,
            frame_inputs={keep_task.task_id: keep_second_input},
            dt=0.1,
        )
        keep_info = keep_slot.data["native_context"].inspect()
        assert keep_info["center_fixed_count"] == 0
        assert keep_info["step_count"] == 3
        assert keep_info["center_frame_shift_count"] == 1
        keep_shift = keep_slot.data["center_frame_shift_result"]
        assert keep_shift.keep_teleport is True
        assert keep_shift.reset_teleport is False
        np.testing.assert_allclose(
            keep_shift.frame_component_shift_vector,
            (10.0, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            keep_shift.frame_component_shift_rotation_xyzw,
            fixed_rotation,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            keep_shift.smoothing_velocity,
            (2.0, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            keep_shift.frame_moving_speed,
            0.0,
            atol=1.0e-6,
        )
        keep_candidate = keep_slot.data["result_candidate"]
        np.testing.assert_allclose(
            keep_candidate.world_positions,
            keep_second_positions,
            atol=1.0e-5,
        )
        assert keep_candidate.native_step_count == 3

        reset_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                gravity=0.0,
                damping=0.0,
                animation_pose_ratio=0.0,
                stabilization_time_after_reset=0.0,
                anchor_inertia=1.0,
                world_inertia=1.0,
                movement_inertia_smoothing=0.5,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
                teleport_mode=1,
                teleport_distance=5.0,
                teleport_rotation=180.0,
            ),
        )
        reset_topology = mc2_topology.build_mc2_topology_spec(reset_task)
        reset_first_input = frame_input.make_mc2_frame_input(
            task_id=reset_task.task_id,
            topology_signature=reset_topology.topology_signature,
            frame=50,
            generation=16,
            world_positions=keep_first_positions,
            world_rotations_xyzw=keep_first_rotations,
            source_world_linear=np.eye(3, dtype=np.float32),
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=50,
                generation=16,
                component_identity=component_identity,
                component_world_position=(0.0, 0.0, 0.0),
                component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
                component_world_scale=(1.0, 1.0, 1.0),
            ),
        )
        reset_second_input = frame_input.make_mc2_frame_input(
            task_id=reset_task.task_id,
            topology_signature=reset_topology.topology_signature,
            frame=51,
            generation=16,
            world_positions=keep_second_positions,
            world_rotations_xyzw=keep_second_rotations,
            source_world_linear=keep_rotation_matrix,
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=51,
                generation=16,
                component_identity=component_identity,
                component_world_position=(10.0, 0.0, 0.0),
                component_world_rotation_xyzw=tuple(float(value) for value in fixed_rotation),
                component_world_scale=(1.0, 1.0, 1.0),
            ),
        )
        reset_world = world_types.PhysicsWorldCache()
        reset_world.generation = 16
        reset_world.frame_context.frame = 50
        reset_world.frame_context.raw_dt = float(
            np.nextafter(np.float32(0.1), np.float32(np.inf))
        )
        mc2_solver.step_mc2(
            reset_world,
            [reset_task],
            settings=fixed_settings,
            frame_inputs={reset_task.task_id: reset_first_input},
        )
        reset_slot = reset_world.solver_slots[reset_task.task_id]
        reset_slot.data["center_state"].smoothing_velocity = (2.0, 0.0, 0.0)
        reset_world.frame_context.frame = 51
        mc2_solver.step_mc2(
            reset_world,
            [reset_task],
            settings=fixed_settings,
            frame_inputs={reset_task.task_id: reset_second_input},
            dt=0.1,
        )
        reset_info = reset_slot.data["native_context"].inspect()
        assert reset_info["reset_count"] == 2
        assert reset_info["step_count"] == 3
        assert reset_info["center_dynamic_revision"] == 1
        assert reset_info["center_step_count"] == 3
        assert reset_info["center_frame_shift_count"] == 0
        reset_shift = reset_slot.data["center_frame_shift_result"]
        assert reset_shift.keep_teleport is False
        assert reset_shift.reset_teleport is True
        np.testing.assert_allclose(
            reset_shift.frame_component_shift_vector,
            (0.0, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            reset_shift.smoothing_velocity,
            (0.0, 0.0, 0.0),
            atol=1.0e-6,
        )
        reset_center_state = reset_slot.data["center_state"]
        assert reset_center_state.reset_count == 2
        assert reset_center_state.old_component_world_position == (10.0, 0.0, 0.0)
        np.testing.assert_allclose(
            reset_center_state.smoothing_velocity,
            (0.0, 0.0, 0.0),
            atol=1.0e-6,
        )
        reset_runtime_state = reset_slot.data["runtime_state"]
        reset_particle_buffer = reset_slot.data["particle_buffer"]
        assert reset_runtime_state.last_reset_reason == "configured_teleport"
        assert reset_runtime_state.reset_count == reset_particle_buffer.reset_count == 2
        reset_candidate = reset_slot.data["result_candidate"]
        np.testing.assert_allclose(
            reset_candidate.world_positions,
            keep_second_positions,
            atol=1.0e-5,
        )
        assert reset_candidate.native_step_count == 3

        reset_negative_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                gravity=0.0,
                damping=0.0,
                animation_pose_ratio=0.0,
                stabilization_time_after_reset=0.0,
                anchor_inertia=1.0,
                world_inertia=1.0,
                movement_inertia_smoothing=0.5,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
                teleport_mode=1,
                teleport_distance=1000.0,
                teleport_rotation=30.0,
            ),
        )
        reset_negative_topology = mc2_topology.build_mc2_topology_spec(
            reset_negative_task
        )
        reset_negative_half_angle = np.float32(np.radians(45.0) * 0.5)
        reset_negative_rotation = np.asarray(
            (
                0.0,
                float(np.sin(reset_negative_half_angle)),
                0.0,
                float(np.cos(reset_negative_half_angle)),
            ),
            dtype=np.float32,
        )
        reset_negative_rotation_matrix = np.asarray(
            (
                (float(np.cos(np.radians(45.0))), 0.0, float(np.sin(np.radians(45.0)))),
                (0.0, 1.0, 0.0),
                (-float(np.sin(np.radians(45.0))), 0.0, float(np.cos(np.radians(45.0)))),
            ),
            dtype=np.float32,
        )
        reset_negative_linear = np.asarray(
            reset_negative_rotation_matrix @ np.diag((-1.0, 1.0, 1.0)),
            dtype=np.float32,
        )
        reset_negative_second_positions = np.asarray(
            keep_first_positions @ reset_negative_linear.T,
            dtype=np.float32,
        )
        reset_negative_second_rotations = np.tile(
            reset_negative_rotation,
            (reset_negative_topology.particle_count, 1),
        )
        reset_negative_first_input = frame_input.make_mc2_frame_input(
            task_id=reset_negative_task.task_id,
            topology_signature=reset_negative_topology.topology_signature,
            frame=60,
            generation=18,
            world_positions=keep_first_positions,
            world_rotations_xyzw=keep_first_rotations,
            source_world_linear=np.eye(3, dtype=np.float32),
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=60,
                generation=18,
                component_identity=component_identity,
                component_world_position=(0.0, 0.0, 0.0),
                component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
                component_world_scale=(1.0, 1.0, 1.0),
            ),
        )
        reset_negative_second_input = frame_input.make_mc2_frame_input(
            task_id=reset_negative_task.task_id,
            topology_signature=reset_negative_topology.topology_signature,
            frame=61,
            generation=18,
            world_positions=reset_negative_second_positions,
            world_rotations_xyzw=reset_negative_second_rotations,
            source_world_linear=reset_negative_linear,
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=61,
                generation=18,
                component_identity=component_identity,
                component_world_position=(0.0, 0.0, 0.0),
                component_world_rotation_xyzw=tuple(
                    float(value) for value in reset_negative_rotation
                ),
                component_world_scale=(-1.0, 1.0, 1.0),
            ),
        )
        reset_negative_world = world_types.PhysicsWorldCache()
        reset_negative_world.generation = 18
        reset_negative_world.frame_context.frame = 60
        reset_negative_world.frame_context.raw_dt = float(
            np.nextafter(np.float32(0.1), np.float32(np.inf))
        )
        mc2_solver.step_mc2(
            reset_negative_world,
            [reset_negative_task],
            settings=fixed_settings,
            frame_inputs={reset_negative_task.task_id: reset_negative_first_input},
        )
        reset_negative_slot = reset_negative_world.solver_slots[
            reset_negative_task.task_id
        ]
        reset_negative_slot.data["center_state"].smoothing_velocity = (2.0, 0.0, 0.0)
        reset_negative_world.frame_context.frame = 61
        mc2_solver.step_mc2(
            reset_negative_world,
            [reset_negative_task],
            settings=fixed_settings,
            frame_inputs={reset_negative_task.task_id: reset_negative_second_input},
            dt=0.1,
        )
        reset_negative_info = reset_negative_slot.data["native_context"].inspect()
        assert reset_negative_info["reset_count"] == 2
        assert reset_negative_info["step_count"] == 3
        assert reset_negative_info["center_step_count"] == 3
        assert reset_negative_info["center_frame_shift_count"] == 0
        assert reset_negative_info["center_negative_scale_teleport_count"] == 0
        reset_negative_shift = reset_negative_slot.data["center_frame_shift_result"]
        assert reset_negative_shift.reset_teleport is True
        assert reset_negative_slot.data["center_negative_scale_result"] is None
        reset_negative_center = reset_negative_slot.data["center_state"]
        assert reset_negative_center.reset_count == 2
        assert reset_negative_center.negative_scale_direction == (-1.0, 1.0, 1.0)
        assert reset_negative_center.smoothing_velocity == (0.0, 0.0, 0.0)
        reset_negative_runtime = reset_negative_slot.data["runtime_state"]
        assert reset_negative_runtime.last_reset_reason == "configured_teleport"
        reset_negative_candidate = reset_negative_slot.data["result_candidate"]
        np.testing.assert_allclose(
            reset_negative_candidate.world_positions,
            reset_negative_second_positions,
            atol=1.0e-5,
        )
        assert reset_negative_candidate.native_step_count == 3

        keep_negative_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                gravity=0.0,
                damping=0.0,
                animation_pose_ratio=0.0,
                stabilization_time_after_reset=0.0,
                anchor_inertia=1.0,
                world_inertia=0.25,
                movement_inertia_smoothing=0.5,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
                teleport_mode=2,
                teleport_distance=1000.0,
                teleport_rotation=30.0,
            ),
        )
        keep_negative_topology = mc2_topology.build_mc2_topology_spec(
            keep_negative_task
        )
        keep_negative_first_input = frame_input.make_mc2_frame_input(
            task_id=keep_negative_task.task_id,
            topology_signature=keep_negative_topology.topology_signature,
            frame=70,
            generation=20,
            world_positions=keep_first_positions,
            world_rotations_xyzw=keep_first_rotations,
            source_world_linear=np.eye(3, dtype=np.float32),
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=70,
                generation=20,
                component_identity=component_identity,
                component_world_position=(0.0, 0.0, 0.0),
                component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
                component_world_scale=(1.0, 1.0, 1.0),
            ),
        )
        keep_negative_second_input = frame_input.make_mc2_frame_input(
            task_id=keep_negative_task.task_id,
            topology_signature=keep_negative_topology.topology_signature,
            frame=71,
            generation=20,
            world_positions=reset_negative_second_positions,
            world_rotations_xyzw=reset_negative_second_rotations,
            source_world_linear=reset_negative_linear,
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=71,
                generation=20,
                component_identity=component_identity,
                component_world_position=(0.0, 0.0, 0.0),
                component_world_rotation_xyzw=tuple(
                    float(value) for value in reset_negative_rotation
                ),
                component_world_scale=(-1.0, 1.0, 1.0),
            ),
        )
        keep_negative_world = world_types.PhysicsWorldCache()
        keep_negative_world.generation = 20
        keep_negative_world.frame_context.frame = 70
        keep_negative_world.frame_context.raw_dt = float(
            np.nextafter(np.float32(0.1), np.float32(np.inf))
        )
        mc2_solver.step_mc2(
            keep_negative_world,
            [keep_negative_task],
            settings=fixed_settings,
            frame_inputs={keep_negative_task.task_id: keep_negative_first_input},
        )
        keep_negative_slot = keep_negative_world.solver_slots[
            keep_negative_task.task_id
        ]
        keep_negative_world.frame_context.frame = 71
        mc2_solver.step_mc2(
            keep_negative_world,
            [keep_negative_task],
            settings=fixed_settings,
            frame_inputs={keep_negative_task.task_id: keep_negative_second_input},
            dt=0.1,
        )
        keep_negative_info = keep_negative_slot.data["native_context"].inspect()
        assert keep_negative_info["reset_count"] == 1
        assert keep_negative_info["step_count"] == 3
        assert keep_negative_info["center_step_count"] == 3
        assert keep_negative_info["center_frame_shift_count"] == 1
        assert keep_negative_info["center_negative_scale_teleport_count"] == 1
        keep_negative_schedule = keep_negative_slot.data["frame_schedule"]
        assert keep_negative_schedule.update_count == 3
        assert keep_negative_schedule.skip_count == 0
        keep_negative_shift = keep_negative_slot.data["center_frame_shift_result"]
        assert keep_negative_shift.keep_teleport is True
        assert keep_negative_shift.reset_teleport is False
        np.testing.assert_allclose(
            keep_negative_shift.frame_component_shift_vector,
            (0.0, 0.0, 0.0),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            keep_negative_shift.frame_component_shift_rotation_xyzw,
            reset_negative_rotation,
            atol=1.0e-6,
        )
        keep_negative_transition = keep_negative_slot.data[
            "center_negative_scale_result"
        ]
        assert keep_negative_transition is not None
        assert keep_negative_transition.active is True
        keep_negative_candidate = keep_negative_slot.data["result_candidate"]
        assert np.all(np.isfinite(keep_negative_candidate.world_positions))
        assert not np.allclose(
            keep_negative_candidate.world_positions,
            reset_negative_second_positions,
            atol=1.0e-5,
        )
        assert keep_negative_candidate.native_step_count == 3
        keep_negative_step = keep_negative_slot.data["center_step_result"]
        assert keep_negative_step is not None
        assert np.all(np.isfinite(keep_negative_step.inertia_vector))
        keep_negative_center = keep_negative_slot.data["center_state"]
        assert keep_negative_center.negative_scale_direction == (-1.0, 1.0, 1.0)
        assert keep_negative_center.last_frame == keep_negative_second_input.frame
        np.testing.assert_allclose(
            keep_negative_center.old_frame_world_rotation_xyzw,
            reset_negative_rotation,
            atol=1.0e-6,
        )

        source.hotools_mesh_collision.pin_enabled = True
        baseline_negative_task = mc2_specs.make_mc2_task_spec(
            "mesh_cloth",
            [source],
            profile=mc2_parameters.make_mc2_particle_profile(
                gravity=0.0,
                damping=0.0,
                animation_pose_ratio=0.25,
                stabilization_time_after_reset=0.0,
                anchor_inertia=1.0,
                world_inertia=1.0,
                movement_inertia_smoothing=0.0,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
            ),
        )
        baseline_negative_topology = mc2_topology.build_mc2_topology_spec(
            baseline_negative_task
        )
        baseline_negative_first_input = frame_input.make_mc2_frame_input(
            task_id=baseline_negative_task.task_id,
            topology_signature=baseline_negative_topology.topology_signature,
            frame=80,
            generation=22,
            world_positions=keep_first_positions,
            world_rotations_xyzw=keep_first_rotations,
            source_world_linear=np.eye(3, dtype=np.float32),
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=80,
                generation=22,
                component_identity=component_identity,
                component_world_position=(0.0, 0.0, 0.0),
                component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
                component_world_scale=(1.0, 1.0, 1.0),
            ),
        )
        baseline_negative_second_input = frame_input.make_mc2_frame_input(
            task_id=baseline_negative_task.task_id,
            topology_signature=baseline_negative_topology.topology_signature,
            frame=81,
            generation=22,
            world_positions=reset_negative_second_positions,
            world_rotations_xyzw=reset_negative_second_rotations,
            source_world_linear=reset_negative_linear,
            center_frame_pose=type(first_input.center_frame_pose)(
                frame=81,
                generation=22,
                component_identity=component_identity,
                component_world_position=(0.0, 0.0, 0.0),
                component_world_rotation_xyzw=tuple(
                    float(value) for value in reset_negative_rotation
                ),
                component_world_scale=(-1.0, 1.0, 1.0),
            ),
        )
        baseline_negative_world = world_types.PhysicsWorldCache()
        baseline_negative_world.generation = 22
        baseline_negative_world.frame_context.frame = 80
        baseline_negative_world.frame_context.raw_dt = float(
            np.nextafter(np.float32(0.1), np.float32(np.inf))
        )
        mc2_solver.step_mc2(
            baseline_negative_world,
            [baseline_negative_task],
            settings=fixed_settings,
            frame_inputs={
                baseline_negative_task.task_id: baseline_negative_first_input
            },
        )
        baseline_negative_slot = baseline_negative_world.solver_slots[
            baseline_negative_task.task_id
        ]
        baseline_negative_world.frame_context.frame = 81
        mc2_solver.step_mc2(
            baseline_negative_world,
            [baseline_negative_task],
            settings=fixed_settings,
            frame_inputs={
                baseline_negative_task.task_id: baseline_negative_second_input
            },
            dt=0.1,
        )
        baseline_negative_info = baseline_negative_slot.data[
            "native_context"
        ].inspect()
        assert baseline_negative_info["center_fixed_count"] == 1
        assert baseline_negative_info["baseline_count"] > 0
        assert baseline_negative_info["step_count"] == 3
        assert baseline_negative_info["center_step_count"] == 3
        assert baseline_negative_info["center_negative_scale_teleport_count"] == 1
        assert baseline_negative_info["baseline_pose_rebuild_count"] == 3
        assert baseline_negative_info["animation_pose_ratio"] == 0.25
        baseline_negative_center = baseline_negative_slot.data["center_state"]
        assert baseline_negative_center.negative_scale_direction == (-1.0, 1.0, 1.0)
        baseline_negative_step_positions, baseline_negative_step_rotations = (
            baseline_negative_slot.data["native_context"].read_step_basic()
        )
        assert np.all(np.isfinite(baseline_negative_step_positions))
        assert np.all(np.isfinite(baseline_negative_step_rotations))
        assert not np.allclose(
            baseline_negative_step_positions[1:],
            baseline_negative_second_input.world_positions[1:],
            atol=1.0e-6,
        )
        baseline_negative_candidate = baseline_negative_slot.data["result_candidate"]
        assert np.all(np.isfinite(baseline_negative_candidate.world_positions))
        assert baseline_negative_candidate.native_step_count == 3
    finally:
        if world is not None:
            world.omni_cache_dispose("test_complete")
        if auto_world is not None:
            auto_world.omni_cache_dispose("test_complete")
        if fixed_world is not None:
            fixed_world.omni_cache_dispose("test_complete")
        if scheduler_world is not None:
            scheduler_world.omni_cache_dispose("test_complete")
        if keep_world is not None:
            keep_world.omni_cache_dispose("test_complete")
        if reset_world is not None:
            reset_world.omni_cache_dispose("test_complete")
        if reset_negative_world is not None:
            reset_negative_world.omni_cache_dispose("test_complete")
        if keep_negative_world is not None:
            keep_negative_world.omni_cache_dispose("test_complete")
        if baseline_negative_world is not None:
            baseline_negative_world.omni_cache_dispose("test_complete")
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
