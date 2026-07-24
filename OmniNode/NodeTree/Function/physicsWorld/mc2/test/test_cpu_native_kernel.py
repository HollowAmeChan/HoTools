"""E3 Python adapter to native CPU data-path owner integration test."""

from __future__ import annotations

import importlib
import json
import os
import sys
import types
from dataclasses import replace

import numpy as np


MC2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(MC2_ROOT)
FUNCTION = os.path.dirname(PHYSICS_WORLD)
NODETREE = os.path.dirname(FUNCTION)
OMNINODE = os.path.dirname(NODETREE)
HOTOOLS = os.path.dirname(OMNINODE)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2", MC2_ROOT),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups", os.path.join(MC2_ROOT, "setups")),
    (
        "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth",
        os.path.join(MC2_ROOT, "setups", "mesh_cloth"),
    ),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

ir = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_ir")
compiler = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_compile")
fragment_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.static_fragment"
)
parameters = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters")
runtime = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters")
cpu_backend = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.cpu_backend")
native_kernel = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.cpu_native_kernel"
)
native_module_api = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.native"
)
collider_frame = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.collider_frame"
)
reference_step = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.reference_step"
)
scheduler = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.scheduler"
)

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "domain_pipeline", "two_mesh_static", "two_mesh_domain_v1.json",
)


def _compiled(*, profile_overrides=None, task_overrides=None):
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"][0]
    snapshot = ir.make_mc2_mesh_partition_static_snapshot(**payload)
    fragment = fragment_module.build_mc2_mesh_static_fragment(snapshot)
    profile_values = {"self_collision_mode": 2}
    if profile_overrides is not None:
        profile_values.update(profile_overrides)
    effective = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(**profile_values),
        parameters.make_mc2_setup_options("mesh_cloth"),
        parameters.make_mc2_task_parameters(**(task_overrides or {})),
    )
    return compiler.compile_mc2_mesh_static_fragments(
        (fragment,), (effective,)
    )


def _compiled_multi(
    animation_pose_ratios=(0.0, 0.0),
    *,
    collision_groups=None,
    collision_masks=None,
    collision_modes=(1, 1),
    external_collision_masks=None,
    profile_overrides=None,
    task_normal_axes=(1, 1),
    task_overrides=None,
):
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payloads = json.load(handle)["static_snapshots"]
    fragments = tuple(
        fragment_module.build_mc2_mesh_static_fragment(
            ir.make_mc2_mesh_partition_static_snapshot(**payload)
        )
        for payload in payloads
    )
    if profile_overrides is None:
        profile_overrides = ({},) * len(fragments)
    if task_overrides is None:
        task_overrides = ({},) * len(fragments)
    effectives = []
    for animation_pose_ratio, collision_mode, overrides, normal_axis, task_values in zip(
        animation_pose_ratios,
        collision_modes,
        profile_overrides,
        task_normal_axes,
        task_overrides,
        strict=True,
    ):
        profile_values = {
            "self_collision_mode": 2,
            "animation_pose_ratio": animation_pose_ratio,
            "collision_mode": collision_mode,
        }
        profile_values.update(overrides)
        effectives.append(runtime.make_mc2_runtime_parameters(
            parameters.make_mc2_particle_profile(**profile_values),
            parameters.make_mc2_setup_options("mesh_cloth"),
            parameters.make_mc2_task_parameters(
                normal_axis=normal_axis, **task_values
            ),
        ))
    return compiler.compile_mc2_mesh_static_fragments(
        fragments,
        tuple(effectives),
        collision_groups=collision_groups,
        collision_masks=collision_masks,
        external_collision_masks=external_collision_masks,
    )


def _empty_collider_table():
    return {
        "collider_types": np.empty((0,), dtype=np.int32),
        "collider_group_bits": np.empty((0,), dtype=np.int32),
        "collider_centers": np.empty((0, 3), dtype=np.float32),
        "collider_segment_a": np.empty((0, 3), dtype=np.float32),
        "collider_segment_b": np.empty((0, 3), dtype=np.float32),
        "collider_old_centers": np.empty((0, 3), dtype=np.float32),
        "collider_old_segment_a": np.empty((0, 3), dtype=np.float32),
        "collider_old_segment_b": np.empty((0, 3), dtype=np.float32),
        "collider_radii": np.empty((0,), dtype=np.float32),
    }


def _frame(program):
    return ir.make_mc2_domain_frame_packet(
        program,
        frame=6,
        generation=2,
        animated_base_world_positions=program.particle_bind_position + np.float32(2.0),
        animated_base_world_rotations=program.particle_bind_rotation,
        animated_base_world_normals=np.asarray(
            ((0.0, 0.0, 1.0),) * program.particle_count, dtype=np.float32
        ),
        partition_world_position=((2.0, 0.0, 0.0),) * program.partition_count,
        partition_world_rotation=((0.0, 0.0, 0.0, 1.0),) * program.partition_count,
        partition_world_scale=((1.0, 1.0, 1.0),) * program.partition_count,
        partition_world_linear=(
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        ) * program.partition_count,
        frame_delta_time=0.1,
        simulation_delta_time=0.1,
        time_scale=1.0,
        is_running=True,
    )


def test_native_cpu_backend_uses_partitioned_animation_pose_ratio():
    compiled = _compiled_multi((0.0, 1.0))
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    try:
        domain.update_frame(_frame(compiled.program))
        implicit = domain.prepare_step_basic_pose()["positions"]
        reconstructed = domain.prepare_step_basic_pose(0.0)["positions"]
        animated = domain.prepare_step_basic_pose(1.0)["positions"]
        owners = compiled.program.particle_partition_index
        np.testing.assert_allclose(implicit[owners == 0], reconstructed[owners == 0])
        np.testing.assert_allclose(implicit[owners == 1], animated[owners == 1])
    finally:
        domain.dispose()


def test_native_cpu_backend_hot_updates_parameters_without_replacing_history():
    first = _compiled_multi(
        collision_modes=(0, 0),
        profile_overrides=(
            {"gravity": 5.0, "damping": 0.1, "self_collision_mode": 0},
            {"gravity": 8.0, "damping": 0.2, "self_collision_mode": 0},
        ),
    )
    second = _compiled_multi(
        collision_modes=(0, 0),
        profile_overrides=(
            {"gravity": 6.0, "damping": 0.7, "self_collision_mode": 0},
            {"gravity": 8.0, "damping": 0.2, "self_collision_mode": 0},
        ),
    )
    assert first.program.domain_signature == second.program.domain_signature
    assert first.parameters.parameter_signature != second.parameters.parameter_signature
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(first, kernel)
    fresh_kernel = native_kernel.MC2NativeCPUKernelV1()
    fresh = cpu_backend.create_mc2_cpu_backend_domain(second, fresh_kernel)
    committed = []
    try:
        frame = _frame(first.program)
        domain.update_frame(frame)
        fresh.update_frame(frame)
        before = domain.inspect()
        live_before = native_module_api.native_module().mc2_domain_cpu_v1_stats()[
            "live_domain_count"
        ]
        domain.update_parameters(second, commit_host=lambda: committed.append(True))
        after = domain.inspect()
        assert committed == [True]
        assert domain.compiled is second
        assert after["kernel"]["frame"] == before["kernel"]["frame"] == 6
        assert after["kernel"]["generation"] == before["kernel"]["generation"] == 2
        assert after["kernel"]["step_count"] == before["kernel"]["step_count"]
        assert after["partition_history"] == before["partition_history"]
        assert (
            native_module_api.native_module().mc2_domain_cpu_v1_stats()[
                "live_domain_count"
            ]
            == live_before
        )
        plan = scheduler.MC2SubstepPlan(
            update_index=0,
            simulation_delta_time=0.1,
            frame_interpolation=1.0,
            is_final_substep=True,
            powers=scheduler.MC2SimulationPowers(
                distance_bending=1.0, integration=1.0, angle=1.0
            ),
        )
        settings = reference_step.make_mc2_compiled_domain_pipeline_settings(
            second,
            frame,
            plan,
            anchor_component_local_positions=np.zeros(
                (second.program.partition_count, 3), dtype=np.float32
            ),
            step_basic_positions=frame.animated_base_world_positions,
            step_basic_rotations=frame.animated_base_world_rotations,
            distance_weights=np.ones(second.program.partition_count, dtype=np.float32),
            external_collision=_empty_collider_table(),
        )
        domain.step_compiled_domain_pipeline_full(settings)
        fresh.step_compiled_domain_pipeline_full(settings)
        np.testing.assert_array_equal(
            domain.read_output().world_positions,
            fresh.read_output().world_positions,
        )
        np.testing.assert_array_equal(
            domain.read_debug_state()["real_velocities"],
            fresh.read_debug_state()["real_velocities"],
        )
    finally:
        domain.dispose()
        fresh.dispose()


def test_native_cpu_backend_rolls_back_parameters_when_host_commit_fails():
    first = _compiled_multi(
        profile_overrides=({"gravity": 5.0}, {"gravity": 8.0})
    )
    second = _compiled_multi(
        profile_overrides=({"gravity": 6.0}, {"gravity": 8.0})
    )
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(first, kernel)
    try:
        domain.update_frame(_frame(first.program))
        before = domain.inspect()
        live_before = native_module_api.native_module().mc2_domain_cpu_v1_stats()[
            "live_domain_count"
        ]

        def fail_commit():
            raise RuntimeError("injected host commit failure")

        try:
            domain.update_parameters(second, commit_host=fail_commit)
        except RuntimeError as exc:
            assert "injected host commit failure" in str(exc)
        else:
            raise AssertionError("host commit failure was accepted")
        after = domain.inspect()
        assert domain.compiled is first
        assert after["kernel"]["frame"] == before["kernel"]["frame"]
        assert after["kernel"]["generation"] == before["kernel"]["generation"]
        assert after["kernel"]["step_count"] == before["kernel"]["step_count"]
        assert after["partition_history"] == before["partition_history"]
        assert (
            native_module_api.native_module().mc2_domain_cpu_v1_stats()[
                "live_domain_count"
            ]
            == live_before
        )
    finally:
        domain.dispose()


def test_native_cpu_backend_runs_compiled_whole_domain_self_policy():
    compiled = _compiled_multi(collision_groups=(1, 2), collision_masks=(0, 0))
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    positions = np.asarray(frame.animated_base_world_positions, dtype=np.float32).copy()
    edge_midpoint = (positions[0] + positions[1]) / np.float32(2.0)
    positions[3] = edge_midpoint + np.asarray((0.0, -0.5, 0.001), dtype=np.float32)
    positions[4] = edge_midpoint + np.asarray((0.0, 0.5, 0.001), dtype=np.float32)
    positions.flags.writeable = False
    frame = replace(frame, animated_base_world_positions=positions)
    try:
        domain.update_frame(frame)
        np.testing.assert_array_equal(domain.read_output().world_positions, positions)
        domain.begin_constraint_debug(64)
        domain.step_whole_domain_self(positions)
        domain.end_constraint_debug()
        output = domain.read_output().world_positions
        assert np.any(np.abs(output - positions) > np.float32(1.0e-6))
        debug = domain.read_constraint_debug_state()[
            "whole_domain_self_results"
        ]
        primitive_count = (
            debug["point_primitive_count"]
            + debug["edge_primitive_count"]
            + debug["triangle_primitive_count"]
        )
        assert debug["frame"] == frame.frame
        assert debug["generation"] == frame.generation
        assert debug["particle_indices"].shape == (primitive_count, 3)
        assert debug["primitive_grids"].shape == (primitive_count, 3)
        assert debug["candidates"].shape[1:] == (3,)
        assert debug["contact_indices"].shape[1:] == (2,)
        assert debug["contact_corrections"].shape[1:] == (2, 3)
        assert debug["intersect_records"].shape[1:] == (5,)
        assert set(map(int, debug["owner_indices"])) == {0, 1}
        assert np.array_equal(debug["owner_group_bits"], (1, 2))
        assert np.array_equal(debug["owner_collision_masks"], (0, 0))
        np.testing.assert_allclose(
            np.sum(debug["contact_corrections"], axis=(0, 1)),
            np.sum(output - positions, axis=0),
            atol=2.0e-6,
            rtol=0.0,
        )
        domain.clear_constraint_debug()
        state = domain.inspect()["kernel"]
        assert state["whole_domain_self_ready"] is True
        assert state["whole_domain_self_point_count"] == 3
        assert state["whole_domain_self_edge_count"] == 4
        assert state["whole_domain_self_triangle_count"] == 1
        assert state["whole_domain_self_step_count"] == 1
        assert state["whole_domain_self_last_candidate_count"] > 0
        assert state["whole_domain_self_last_contact_count"] > 0
        assert state["step_count"] == 1
        assert state["constraint_debug_active_mask"] == 0
        assert state["constraint_debug_captured_mask"] == 0
    finally:
        domain.dispose()


def test_native_cpu_backend_blocks_compiled_whole_domain_self_pair():
    compiled = _compiled_multi(collision_groups=(1, 2), collision_masks=(2, 2))
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    positions = np.asarray(frame.animated_base_world_positions, dtype=np.float32).copy()
    edge_midpoint = (positions[0] + positions[1]) / np.float32(2.0)
    positions[3] = edge_midpoint + np.asarray((0.0, -0.5, 0.001), dtype=np.float32)
    positions[4] = edge_midpoint + np.asarray((0.0, 0.5, 0.001), dtype=np.float32)
    positions.flags.writeable = False
    frame = replace(frame, animated_base_world_positions=positions)
    try:
        domain.update_frame(frame)
        domain.step_whole_domain_self(positions)
        np.testing.assert_array_equal(domain.read_output().world_positions, positions)
        assert domain.inspect()["kernel"]["whole_domain_self_step_count"] == 1
        assert domain.inspect()["kernel"]["whole_domain_self_last_contact_count"] == 0
    finally:
        domain.dispose()


def test_native_whole_domain_self_debug_reports_intersection():
    compiled = _compiled_multi(collision_groups=(1, 2), collision_masks=(0, 0))
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    positions = np.asarray(
        frame.animated_base_world_positions, dtype=np.float32
    ).copy()
    triangle_center = np.mean(positions[:3], axis=0)
    positions[3] = triangle_center + np.asarray(
        (0.0, 0.0, -0.1), dtype=np.float32
    )
    positions[4] = triangle_center + np.asarray(
        (0.0, 0.0, 0.1), dtype=np.float32
    )
    positions.flags.writeable = False
    frame = replace(frame, animated_base_world_positions=positions)
    try:
        domain.update_frame(frame)
        domain.begin_constraint_debug(64)
        domain.step_whole_domain_self(positions)
        domain.end_constraint_debug()
        records = domain.read_constraint_debug_state()[
            "whole_domain_self_results"
        ]["intersect_records"]
        assert len(records) > 0
        assert any(
            set(map(int, record[:2])) == {3, 4}
            and set(map(int, record[2:])) == {0, 1, 2}
            for record in records
        )
        domain.clear_constraint_debug()
    finally:
        domain.dispose()


def test_native_cpu_kernel_runs_only_explicit_data_path_mode():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    try:
        domain.update_frame(frame)
        try:
            domain.step({"substeps": 1})
        except RuntimeError as exc:
            assert "numerical kernel is not ready" in str(exc)
        else:
            raise AssertionError("native data-path owner accepted a product step")
        domain.step({"data_path_only": True})
        output = domain.read_output()
        assert output.frame == frame.frame and output.generation == frame.generation
        assert np.array_equal(output.world_positions, frame.animated_base_world_positions)
        assert np.array_equal(
            output.world_rotations_xyzw, frame.animated_base_world_rotations
        )
        inspection = domain.inspect()
        assert inspection["kernel"]["numerical_kernel_ready"] is False
        assert inspection["kernel"]["baseline_ready"] is True
        assert inspection["kernel"]["baseline_line_count"] == 1
        assert inspection["kernel"]["baseline_data_count"] == 3
        assert "real_velocities" not in inspection["kernel"]
        debug_state = domain.read_debug_state()
        assert debug_state["velocities"].shape == (
            compiled.program.particle_count, 3
        )
        assert debug_state["real_velocities"].shape == (
            compiled.program.particle_count, 3
        )
        assert inspection["step_count"] == 1
    finally:
        domain.dispose()
    assert domain.disposed


def test_native_debug_off_inspect_does_not_readback_dynamics():
    compiled = _compiled()
    real_module = native_module_api.native_module()

    class _CountingModule:
        def __init__(self):
            self.output_read_count = 0
            self.dynamics_debug_read_count = 0

        def __getattr__(self, name):
            value = getattr(real_module, name)
            counters = {
                "mc2_domain_cpu_v1_read": "output_read_count",
                "mc2_domain_cpu_v1_read_dynamics_debug": (
                    "dynamics_debug_read_count"
                ),
            }
            counter = counters.get(name)
            if counter is None:
                return value

            def counted(*args, **kwargs):
                setattr(self, counter, getattr(self, counter) + 1)
                return value(*args, **kwargs)

            return counted

    module = _CountingModule()
    kernel = native_kernel.MC2NativeCPUKernelV1(module=module)
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    try:
        domain.update_frame(_frame(compiled.program))
        domain.inspect()
        assert module.output_read_count == 0
        assert module.dynamics_debug_read_count == 0
        domain.step({"data_path_only": True})
        domain.inspect()
        assert module.output_read_count == 0
        assert module.dynamics_debug_read_count == 0
        domain.read_debug_state()
        assert module.output_read_count == 0
        assert module.dynamics_debug_read_count == 1
        domain.read_output()
        assert module.output_read_count == 1
        assert module.dynamics_debug_read_count == 1
    finally:
        domain.dispose()


def test_native_cpu_kernel_exposes_distance_slice_only_when_requested():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    try:
        domain.update_frame(frame)
        domain.step({"data_path_only": True, "distance_slice": True})
        output = domain.read_output()
        assert output.world_positions.shape == (compiled.program.particle_count, 3)
        assert domain.inspect()["kernel"]["distance_slice_ready"] is True
        assert domain.inspect()["step_count"] == 1
    finally:
        domain.dispose()


def test_native_cpu_kernel_exposes_tether_slice_with_step_basic_rest_lengths():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    try:
        domain.update_frame(frame)
        before = domain.read_output().world_positions.copy()
        domain.step({
            "data_path_only": True,
            "tether_slice": True,
            "step_basic_positions": np.asarray(
                ((2.0, 2.0, 2.0), (1.5, 2.0, 2.0), (2.0, 1.5, 2.0)),
                dtype=np.float32,
            ),
            "compression": 0.0,
            "stretch": 0.03,
        })
        after = domain.read_output().world_positions
        assert np.array_equal(after[0], before[0])
        assert after[1, 0] > before[1, 0]
        assert after[2, 1] > before[2, 1]
        assert domain.inspect()["kernel"]["tether_slice_ready"] is True
        assert domain.inspect()["step_count"] == 1
    finally:
        domain.dispose()


def test_native_constraint_debug_distance_and_tether_sum_to_pass_delta():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    positions = np.asarray(frame.animated_base_world_positions, dtype=np.float32).copy()
    positions[1] += np.asarray((0.35, 0.1, 0.0), dtype=np.float32)
    positions[2] += np.asarray((-0.1, 0.25, 0.0), dtype=np.float32)
    positions.flags.writeable = False
    frame = replace(frame, animated_base_world_positions=positions)
    try:
        domain.update_frame(frame)
        domain.begin_constraint_debug(4)
        before = domain.read_output().world_positions.copy()
        domain.step({"data_path_only": True, "distance_slice": True})
        after = domain.read_output().world_positions.copy()
        domain.end_constraint_debug()
        distance = domain.read_constraint_debug_state()["distance_results"]
        assert np.any(distance["valid"][0] != 0)
        assert np.any(distance["hit"][0] != 0)
        for vertex in range(compiled.program.particle_count):
            select = (distance["valid"][0] != 0) & (
                distance["vertices"][0] == vertex
            )
            expected = np.sum(distance["corrections"][0, select], axis=0)
            np.testing.assert_allclose(
                after[vertex] - before[vertex], expected, atol=2.0e-7, rtol=0.0
            )
        domain.clear_constraint_debug()

        domain.begin_constraint_debug(8)
        before = domain.read_output().world_positions.copy()
        domain.step({
            "data_path_only": True,
            "tether_slice": True,
            "step_basic_positions": np.asarray(
                ((2.0, 2.0, 2.0), (1.5, 2.0, 2.0), (2.0, 1.5, 2.0)),
                dtype=np.float32,
            ),
            "compression": 0.0,
            "stretch": 0.03,
        })
        after = domain.read_output().world_positions.copy()
        domain.end_constraint_debug()
        tether = domain.read_constraint_debug_state()["tether_results"]
        assert np.any(tether["valid"] != 0)
        assert np.any(tether["hit"] != 0)
        np.testing.assert_allclose(
            after - before, tether["corrections"], atol=2.0e-7, rtol=0.0
        )
        domain.clear_constraint_debug()
        debug_state = domain.inspect()["kernel"]
        assert debug_state["constraint_debug_active_mask"] == 0
        assert debug_state["constraint_debug_captured_mask"] == 0
    finally:
        domain.dispose()


def test_native_cpu_kernel_exposes_angle_slice_with_baseline_transaction():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    try:
        domain.update_frame(frame)
        domain.step({
            "data_path_only": True,
            "angle_slice": True,
            "step_basic_positions": frame.animated_base_world_positions,
            "step_basic_rotations": frame.animated_base_world_rotations,
            "restoration_values": np.ones(compiled.program.particle_count, dtype=np.float32),
            "limit_values": np.ones(compiled.program.particle_count, dtype=np.float32),
            "restoration_velocity_attenuation": 0.0,
            "restoration_gravity_falloff": 0.0,
            "limit_stiffness": 0.2,
            "restoration_enabled": True,
            "limit_enabled": True,
        })
        output = domain.read_output().world_positions
        assert np.isfinite(output).all()
        assert domain.inspect()["kernel"]["angle_solve_count"] == 1
        disabled = {
            "data_path_only": True,
            "angle_slice": True,
            "step_basic_positions": frame.animated_base_world_positions,
            "step_basic_rotations": frame.animated_base_world_rotations,
            "restoration_values": np.ones(compiled.program.particle_count, dtype=np.float32),
            "limit_values": np.ones(compiled.program.particle_count, dtype=np.float32),
            "restoration_velocity_attenuation": 0.0,
            "restoration_gravity_falloff": 0.0,
            "limit_stiffness": 0.2,
            "restoration_enabled": False,
            "limit_enabled": False,
        }
        domain.step(disabled)
        assert domain.inspect()["kernel"]["angle_solve_count"] == 1
        assert domain.inspect()["kernel"]["step_count"] == 2
    finally:
        domain.dispose()


def test_native_cpu_kernel_exposes_motion_slice_with_explicit_base_pose():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    try:
        domain.update_frame(frame)
        domain.step({
            "data_path_only": True,
            "motion_slice": True,
            "base_positions": frame.animated_base_world_positions,
            "base_rotations": frame.animated_base_world_rotations,
            "max_distances": np.zeros(compiled.program.particle_count, dtype=np.float32),
            "stiffness_values": np.ones(compiled.program.particle_count, dtype=np.float32),
            "backstop_radii": np.zeros(compiled.program.particle_count, dtype=np.float32),
            "backstop_distances": np.zeros(compiled.program.particle_count, dtype=np.float32),
            "normal_axis": 1,
            "max_distance_enabled": True,
            "backstop_enabled": False,
        })
        assert np.isfinite(domain.read_output().world_positions).all()
        assert domain.inspect()["kernel"]["motion_solve_count"] == 1
        assert domain.inspect()["kernel"]["step_count"] == 1
    finally:
        domain.dispose()


def test_native_cpu_kernel_exposes_inertia_slice_only_when_requested():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    try:
        domain.update_frame(frame)
        domain.step({
            "data_path_only": True,
            "inertia_slice": True,
            "old_world_position": (0.0, 0.0, 0.0),
            "step_vector": (1.0, 0.0, 0.0),
            "step_rotation": (0.0, 0.0, 0.0, 1.0),
            "inertia_vector": (0.25, 0.0, 0.0),
            "inertia_rotation": (0.0, 0.0, 0.0, 1.0),
            "depth_inertia": 1.0,
        })
        output = domain.read_output()
        assert output.world_positions.shape == (compiled.program.particle_count, 3)
        assert np.array_equal(
            output.world_positions[0], frame.animated_base_world_positions[0]
        )
        assert np.any(
            output.world_positions[1:] != frame.animated_base_world_positions[1:]
        )
        assert domain.inspect()["kernel"]["inertia_slice_ready"] is True
        assert domain.inspect()["step_count"] == 1
    finally:
        domain.dispose()


def test_native_cpu_kernel_exposes_integration_slice_only_when_requested():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    try:
        domain.update_frame(frame)
        domain.step({
            "data_path_only": True,
            "integration_slice": True,
            "dt": 0.5,
            "simulation_power": 1.0,
            "velocity_weight": 1.0,
            "gravity": (0.0, -2.0, 0.0),
        })
        output = domain.read_output()
        assert np.array_equal(
            output.world_positions[0], frame.animated_base_world_positions[0]
        )
        np.testing.assert_allclose(
            output.world_positions[1:, 1],
            frame.animated_base_world_positions[1:, 1] - np.float32(0.5),
        )
        assert domain.inspect()["kernel"]["integration_slice_ready"] is True
        assert domain.inspect()["step_count"] == 1
    finally:
        domain.dispose()


def test_native_cpu_kernel_tracks_multi_partition_frame_history():
    compiled = _compiled_multi()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    count = compiled.program.particle_count
    frame = ir.make_mc2_domain_frame_packet(
        compiled.program,
        frame=9,
        generation=4,
        animated_base_world_positions=compiled.program.particle_bind_position,
        animated_base_world_rotations=compiled.program.particle_bind_rotation,
        animated_base_world_normals=np.asarray(
            ((0.0, 0.0, 1.0),) * count, dtype=np.float32
        ),
        partition_world_position=((1.0, 0.0, 0.0), (8.0, 0.0, 0.0)),
        partition_world_rotation=((0.0, 0.0, 0.0, 1.0),) * 2,
        partition_world_scale=((1.0, 1.0, 1.0),) * 2,
        partition_world_linear=(
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        ) * 2,
        partition_frame_flags=(1, 2),
    )
    try:
        domain.update_frame(frame)
        kernel_state = domain.inspect()["kernel"]
        np.testing.assert_array_equal(kernel_state["partition_reset_counts"], (1, 0))
        np.testing.assert_array_equal(kernel_state["partition_keep_counts"], (0, 1))
        np.testing.assert_allclose(
            kernel_state["partition_world_positions"],
            frame.partition_world_position,
        )
    finally:
        domain.dispose()


def test_native_cpu_kernel_exposes_center_frame_shift_slice():
    kernel = native_kernel.MC2NativeCPUKernelV1()
    identity3 = (0.0, 0.0, 0.0)
    identity4 = (0.0, 0.0, 0.0, 1.0)
    result = kernel.evaluate_center_frame_shift({
        "old_component_position": identity3,
        "component_position": (2.0, 0.0, 0.0),
        "old_component_rotation": identity4,
        "component_rotation": identity4,
        "component_scale": (1.0, 1.0, 1.0),
        "initial_scale": (1.0, 1.0, 1.0),
        "frame_world_position": (2.0, 0.0, 0.0),
        "frame_world_rotation": identity4,
        "old_frame_world_position": (1.0, 0.0, 0.0),
        "old_frame_world_rotation": identity4,
        "now_world_position": (2.0, 0.0, 0.0),
        "now_world_rotation": identity4,
        "old_anchor_position": identity3,
        "old_anchor_rotation": identity4,
        "anchor_position": identity3,
        "anchor_rotation": identity4,
        "anchor_component_local_position": identity3,
        "smoothing_velocity": identity3,
        "use_anchor": False,
        "is_running": True,
        "anchor_inertia": 0.0,
        "world_inertia": 0.25,
        "movement_speed_limit": -1.0,
        "rotation_speed_limit": -1.0,
        "movement_inertia_smoothing": 0.0,
        "frame_delta_time": 0.1,
        "simulation_delta_time": 0.1,
        "time_scale": 1.0,
        "skip_count": 0,
        "velocity_weight": 1.0,
        "teleport_mode": 0,
        "teleport_distance": 0.5,
        "teleport_rotation": 90.0,
    })
    np.testing.assert_allclose(result["world_shift_vector"], (1.5, 0.0, 0.0))
    assert result["teleport_triggered"] is False


def test_native_cpu_domain_commits_center_frame_shift_transaction():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    try:
        domain.update_frame(_frame(compiled.program))
        domain.step_center_frame_shift(np.zeros((1, 3), dtype=np.float32))
        state = domain.inspect()["kernel"]
        assert state["center_shift_count"] == 1
        assert state["center_shift_vectors"].shape == (1, 3)
        assert state["center_shift_rotations"].shape == (1, 4)
        assert state["center_shift_teleport_flags"].shape == (1,)
        assert np.isfinite(state["center_shift_vectors"]).all()
    finally:
        domain.dispose()


def test_native_task_reference_teleport_ignores_object_only_motion():
    compiled = _compiled(task_overrides={
        "teleport_mode": 2, "teleport_distance": 0.1,
    })
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    first = _frame(compiled.program)
    offset = np.asarray((3.0, 0.0, 0.0), dtype=np.float32)
    moved_animation = np.asarray(first.animated_base_world_positions).copy() + offset
    moved_components = np.asarray(first.partition_world_position).copy() + offset
    moved_animation.flags.writeable = False
    moved_components.flags.writeable = False
    second = replace(
        first,
        frame=first.frame + 1,
        animated_base_world_positions=moved_animation,
        partition_world_position=moved_components,
    )
    try:
        domain.update_frame(first)
        domain.update_frame(second)
        domain.step_task_reference_teleport()
        state = domain.read_task_reference_teleport_state()
        np.testing.assert_array_equal(state["flags"], (0,))
        np.testing.assert_allclose(state["measured_distances"], (0.0,), atol=1.0e-6)
        assert int(state["reference_indices"][0]) == 0
    finally:
        domain.dispose()


def test_native_task_reference_keep_uses_one_fixed_reference_and_partition_scope():
    compiled = _compiled_multi(
        task_overrides=(
            {"teleport_mode": 2, "teleport_distance": 0.1},
            {"teleport_mode": 2, "teleport_distance": 0.1},
        ),
    )
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    first = _frame(compiled.program)
    owners = np.asarray(compiled.program.particle_partition_index)
    moved_animation = np.asarray(first.animated_base_world_positions).copy()
    moved_animation[owners == 0, 0] += np.float32(2.0)
    moved_animation.flags.writeable = False
    second = replace(
        first,
        frame=first.frame + 1,
        animated_base_world_positions=moved_animation,
    )
    try:
        domain.update_frame(first)
        domain.step({
            "data_path_only": True,
            "integration_slice": True,
            "dt": 0.1,
            "simulation_power": 1.0,
            "velocity_weight": 1.0,
            "gravity": (0.0, -9.81, 0.0),
        })
        before = domain.read_output().world_positions.copy()
        before_dynamics = domain.read_debug_state()
        domain.update_frame(second)
        domain.step_task_reference_teleport()
        after = domain.read_output().world_positions
        state = domain.read_task_reference_teleport_state()
        np.testing.assert_array_equal(state["flags"], (3, 0))
        expected_references = []
        attributes = np.asarray(compiled.program.particle_attribute_flags)
        for partition in range(compiled.program.partition_count):
            fixed = np.flatnonzero((owners == partition) & ((attributes & 1) != 0))
            expected_references.append(int(fixed[0]) if fixed.size else -1)
        np.testing.assert_array_equal(
            state["reference_indices"], expected_references
        )
        np.testing.assert_allclose(
            after[owners == 0],
            before[owners == 0] + np.asarray((2.0, 0.0, 0.0), dtype=np.float32),
            atol=1.0e-6,
        )
        np.testing.assert_allclose(after[owners == 1], before[owners == 1], atol=1.0e-6)
        dynamics = domain.read_debug_state()
        np.testing.assert_allclose(
            dynamics["velocities"], before_dynamics["velocities"], atol=1.0e-7
        )
        np.testing.assert_allclose(dynamics["real_velocities"], 0.0, atol=1.0e-7)
        np.testing.assert_allclose(
            dynamics["velocity_reference_positions"][owners == 0],
            before_dynamics["velocity_reference_positions"][owners == 0]
            + np.asarray((2.0, 0.0, 0.0), dtype=np.float32),
            atol=1.0e-6,
        )
        assert int(state["teleport_count"]) == 1
        assert int(state["self_history_invalidation_count"]) == 1
    finally:
        domain.dispose()


def test_native_task_reference_reset_is_exact_and_invalidates_histories_once():
    compiled = _compiled(task_overrides={
        "teleport_mode": 1, "teleport_distance": 0.1,
    })
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    first = _frame(compiled.program)
    moved_animation = np.asarray(first.animated_base_world_positions).copy()
    moved_animation[:, 1] += np.float32(1.25)
    moved_animation.flags.writeable = False
    second = replace(
        first,
        frame=first.frame + 1,
        animated_base_world_positions=moved_animation,
    )
    try:
        domain.update_frame(first)
        domain.step({
            "data_path_only": True,
            "integration_slice": True,
            "dt": 0.1,
            "simulation_power": 1.0,
            "velocity_weight": 1.0,
            "gravity": (0.0, -9.81, 0.0),
        })
        domain.update_frame(second)
        domain.step_task_reference_teleport()
        domain.step_task_reference_teleport()
        state = domain.read_task_reference_teleport_state()
        np.testing.assert_array_equal(state["flags"], (5,))
        np.testing.assert_allclose(
            domain.read_output().world_positions, moved_animation, atol=1.0e-6
        )
        dynamics = domain.read_debug_state()
        np.testing.assert_allclose(
            dynamics["velocity_reference_positions"], moved_animation, atol=1.0e-7
        )
        np.testing.assert_allclose(dynamics["velocities"], 0.0, atol=1.0e-7)
        np.testing.assert_allclose(dynamics["real_velocities"], 0.0, atol=1.0e-7)
        assert int(state["teleport_count"]) == 1
        assert int(state["self_history_invalidation_count"]) == 1
    finally:
        domain.dispose()


def task_reference_teleport_contracts():
    test_native_task_reference_teleport_ignores_object_only_motion()
    test_native_task_reference_keep_uses_one_fixed_reference_and_partition_scope()
    test_native_task_reference_reset_is_exact_and_invalidates_histories_once()


def test_native_cpu_reset_teleport_restarts_center_stabilization_once():
    compiled = _compiled(
        profile_overrides={"stabilization_time_after_reset": 0.2},
        task_overrides={"teleport_mode": 1, "teleport_distance": 0.1},
    )
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    first = _frame(compiled.program)
    moved_positions = first.partition_world_position.copy()
    moved_positions[:, 0] += np.float32(2.0)
    moved_positions.flags.writeable = False
    second = replace(first, frame=first.frame + 1, partition_world_position=moved_positions)
    anchor_positions = np.zeros((1, 3), dtype=np.float32)
    center_settings = {
        "dt": 0.05,
        "frame_interpolation": 0.5,
        "distance_weights": np.ones(1, dtype=np.float32),
    }
    try:
        domain.update_frame(first)
        domain.update_frame(second)
        domain.step_center_frame_shift(anchor_positions)
        reset_state = domain.read_center_debug_state()
        assert int(reset_state["teleport_flags"][0]) & 4
        np.testing.assert_allclose(reset_state["velocity_weights"], (0.0,))

        domain.step_center(center_settings)
        np.testing.assert_allclose(
            domain.read_center_debug_state()["velocity_weights"], (0.25,), atol=1.0e-6
        )
        domain.step_center_frame_shift(anchor_positions)
        np.testing.assert_allclose(
            domain.read_center_debug_state()["velocity_weights"], (0.25,), atol=1.0e-6
        )
        domain.step_center({**center_settings, "frame_interpolation": 1.0})
        np.testing.assert_allclose(
            domain.read_center_debug_state()["velocity_weights"], (0.5,), atol=1.0e-6
        )
    finally:
        domain.dispose()


def test_native_cpu_reference_slice_prefix_keeps_fixed_pass_order():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    try:
        domain.update_frame(frame)
        domain.step_reference_slices({
            "anchor_component_local_positions": np.zeros((1, 3), dtype=np.float32),
            "dt": 0.1,
            "frame_interpolation": 1.0,
            "distance_weights": np.ones(1, dtype=np.float32),
            "simulation_power": 1.0,
            "velocity_weight": 1.0,
            "gravity": (0.0, -1.0, 0.0),
            "step_basic_positions": frame.animated_base_world_positions,
            "tether_compression": 0.4,
            "tether_stretch": 0.03,
        })
        state = domain.inspect()["kernel"]
        assert state["center_shift_count"] == 1
        assert state["center_step_count"] == 1
        assert state["step_count"] == 4
        assert domain.inspect()["step_count"] == 1
    finally:
        domain.dispose()


def test_native_cpu_reference_pipeline_runs_structural_order_through_motion():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    count = compiled.program.particle_count
    try:
        domain.update_frame(frame)
        domain.step_reference_pipeline({
            "anchor_component_local_positions": np.zeros((1, 3), dtype=np.float32),
            "dt": 0.1,
            "frame_interpolation": 1.0,
            "distance_weights": np.ones(1, dtype=np.float32),
            "simulation_power": 1.0,
            "distance_simulation_power": 1.0,
            "bending_simulation_power": 1.0,
            "velocity_weight": 1.0,
            "gravity": (0.0, -1.0, 0.0),
            "step_basic_positions": frame.animated_base_world_positions,
            "tether_compression": 0.4,
            "tether_stretch": 0.03,
            "step_basic_rotations": frame.animated_base_world_rotations,
            "angle_restoration_values": np.ones(count, dtype=np.float32),
            "angle_limit_values": np.ones(count, dtype=np.float32),
            "angle_restoration_velocity_attenuation": 0.0,
            "angle_restoration_gravity_falloff": 0.0,
            "angle_limit_stiffness": 0.2,
            "angle_restoration_enabled": True,
            "angle_limit_enabled": True,
            "motion_base_positions": frame.animated_base_world_positions,
            "motion_base_rotations": frame.animated_base_world_rotations,
            "motion_max_distances": np.zeros(count, dtype=np.float32),
            "motion_stiffness_values": np.ones(count, dtype=np.float32),
            "motion_backstop_radii": np.zeros(count, dtype=np.float32),
            "motion_backstop_distances": np.zeros(count, dtype=np.float32),
            "motion_normal_axis": 1,
            "motion_max_distance_enabled": True,
            "motion_backstop_enabled": False,
        })
        state = domain.inspect()["kernel"]
        assert state["step_count"] == 7
        assert domain.inspect()["step_count"] == 1
        assert np.isfinite(domain.read_output().world_positions).all()
    finally:
        domain.dispose()


def test_native_cpu_reference_pipeline_full_accepts_explicit_collision_slots():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    count = compiled.program.particle_count
    try:
        domain.update_frame(frame)
        settings = {
            "anchor_component_local_positions": np.zeros((1, 3), dtype=np.float32),
            "dt": 0.1,
            "frame_interpolation": 1.0,
            "distance_weights": np.ones(1, dtype=np.float32),
            "simulation_power": 1.0,
            "distance_simulation_power": 1.0,
            "bending_simulation_power": 1.0,
            "velocity_weight": 1.0,
            "gravity": (0.0, -1.0, 0.0),
            "step_basic_positions": frame.animated_base_world_positions,
            "tether_compression": 0.4,
            "tether_stretch": 0.03,
            "step_basic_rotations": frame.animated_base_world_rotations,
            "angle_restoration_values": np.ones(count, dtype=np.float32),
            "angle_limit_values": np.ones(count, dtype=np.float32),
            "angle_restoration_velocity_attenuation": 0.0,
            "angle_restoration_gravity_falloff": 0.0,
            "angle_limit_stiffness": 0.2,
            "angle_restoration_enabled": True,
            "angle_limit_enabled": True,
            "motion_base_positions": frame.animated_base_world_positions,
            "motion_base_rotations": frame.animated_base_world_rotations,
            "motion_max_distances": np.zeros(count, dtype=np.float32),
            "motion_stiffness_values": np.ones(count, dtype=np.float32),
            "motion_backstop_radii": np.zeros(count, dtype=np.float32),
            "motion_backstop_distances": np.zeros(count, dtype=np.float32),
            "motion_normal_axis": 1,
            "motion_max_distance_enabled": True,
            "motion_backstop_enabled": False,
            "point_collision": None,
            "edge_collision": None,
            "self_collision": None,
        }
        domain.step_reference_pipeline_full(settings)
        assert np.isfinite(domain.read_output().world_positions).all()
        assert domain.inspect()["kernel"]["step_count"] == 7
        assert domain.inspect()["step_count"] == 1
        domain.step_reference_pipeline_full(settings)
        state = domain.inspect()
        assert state["kernel"]["center_shift_count"] == 1
        assert state["kernel"]["step_count"] == 14
        assert state["step_count"] == 2
    finally:
        domain.dispose()


def test_native_cpu_compiled_pipeline_runs_whole_domain_self_and_owned_post():
    compiled = _compiled_multi(
        collision_groups=(1, 2),
        collision_masks=(0, 0),
        task_normal_axes=(0, 5),
    )
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    positions = np.asarray(frame.animated_base_world_positions, dtype=np.float32).copy()
    edge_midpoint = (positions[0] + positions[1]) / np.float32(2.0)
    positions[3] = edge_midpoint + np.asarray((0.0, -0.5, 0.001), dtype=np.float32)
    positions[4] = edge_midpoint + np.asarray((0.0, 0.5, 0.001), dtype=np.float32)
    positions.flags.writeable = False
    frame = replace(frame, animated_base_world_positions=positions)
    count = compiled.program.particle_count
    partition_count = compiled.program.partition_count
    try:
        domain.update_frame(frame)
        plan = scheduler.MC2SubstepPlan(
            update_index=0,
            simulation_delta_time=0.1,
            frame_interpolation=1.0,
            is_final_substep=True,
            powers=scheduler.MC2SimulationPowers(
                distance_bending=0.0, integration=0.0, angle=0.0
            ),
        )
        settings = reference_step.make_mc2_compiled_domain_pipeline_settings(
            compiled,
            frame,
            plan,
            anchor_component_local_positions=np.zeros(
                (partition_count, 3), dtype=np.float32
            ),
            step_basic_positions=positions,
            step_basic_rotations=frame.animated_base_world_rotations,
            distance_weights=np.ones(partition_count, dtype=np.float32),
            external_collision=_empty_collider_table(),
        )
        invalid = dict(settings)
        invalid_values = np.asarray(
            settings["post_step"]["dynamic_friction_values"]
        ).copy()
        invalid_values[0] = np.nan
        invalid["post_step"] = dict(
            settings["post_step"], dynamic_friction_values=invalid_values
        )
        try:
            domain.step_compiled_domain_pipeline_full(invalid)
        except ValueError as exc:
            assert "finite" in str(exc) or "invalid" in str(exc)
        else:
            raise AssertionError("compiled domain pipeline accepted invalid post scalars")
        assert domain.inspect()["kernel"]["step_count"] == 0

        order = []
        ordered_methods = (
            "step_task_reference_teleport", "step_center_frame_shift",
            "step_center", "step_center_inertia",
            "step_integration_partitioned", "step_tether_partitioned",
            "step_distance", "step_angle_partitioned", "step_bending",
            "_run_compiled_external_collision", "step_motion_partitioned",
            "step_whole_domain_self_owned", "step_post_owned_partitioned",
        )
        for name in ordered_methods:
            original = getattr(kernel, name)

            def record(*args, _name=name, _original=original, **kwargs):
                order.append(_name)
                return _original(*args, **kwargs)

            setattr(kernel, name, record)
        domain.step_compiled_domain_pipeline_full(settings)
        assert order == [
            "step_task_reference_teleport", "step_center_frame_shift",
            "step_center", "step_center_inertia",
            "step_integration_partitioned", "step_tether_partitioned",
            "step_distance", "step_angle_partitioned",
            "_run_compiled_external_collision", "step_distance",
            "step_motion_partitioned", "step_whole_domain_self_owned",
            "step_post_owned_partitioned",
        ], order
        output = domain.read_output().world_positions
        state = domain.inspect()["kernel"]
        assert np.any(np.abs(output - positions) > np.float32(1.0e-6))
        assert state["whole_domain_self_step_count"] == 1
        assert state["whole_domain_self_last_contact_count"] > 0
        assert state["compiled_external_ready"] is True
        assert state["compiled_external_step_count"] == 1
        assert np.any(np.abs(domain.read_debug_state()["real_velocities"]) > 1.0e-6)
        assert domain.inspect()["step_count"] == 1
    finally:
        domain.dispose()


def test_compiled_pipeline_settings_expand_each_partition_without_scalar_collapse():
    compiled = _compiled_multi(
        profile_overrides=(
            {
                "tether_compression": 0.15,
                "angle_restoration_enabled": False,
                "angle_restoration_velocity_attenuation": 0.2,
                "angle_restoration_gravity_falloff": 0.3,
                "angle_limit_enabled": True,
                "angle_limit_stiffness": 0.4,
                "max_distance_enabled": True,
                "backstop_enabled": False,
                "backstop_radius": 1.0,
                "motion_stiffness": 0.25,
                "collision_friction": 0.1,
                "particle_speed_limit": 2.0,
            },
            {
                "tether_compression": 0.75,
                "angle_restoration_enabled": True,
                "angle_restoration_velocity_attenuation": 0.6,
                "angle_restoration_gravity_falloff": 0.7,
                "angle_limit_enabled": False,
                "angle_limit_stiffness": 0.8,
                "max_distance_enabled": False,
                "backstop_enabled": True,
                "backstop_radius": 3.0,
                "motion_stiffness": 0.9,
                "collision_friction": 0.4,
                "particle_speed_limit": 7.0,
            },
        ),
        task_normal_axes=(0, 5),
    )
    frame = _frame(compiled.program)
    plan = scheduler.MC2SubstepPlan(
        update_index=0,
        simulation_delta_time=0.05,
        frame_interpolation=0.5,
        is_final_substep=False,
        powers=scheduler.MC2SimulationPowers(
            distance_bending=0.25, integration=0.5, angle=0.75
        ),
    )
    settings = reference_step.make_mc2_compiled_domain_pipeline_settings(
        compiled,
        frame,
        plan,
        anchor_component_local_positions=np.zeros((2, 3), dtype=np.float32),
        step_basic_positions=frame.animated_base_world_positions,
        step_basic_rotations=frame.animated_base_world_rotations,
        distance_weights=np.ones(2, dtype=np.float32),
        external_collision=_empty_collider_table(),
    )
    owners = np.asarray(compiled.program.particle_partition_index, dtype=np.intp)
    float_table = compiled.parameters.partition_parameters
    uint_table = compiled.parameters.partition_uint_parameters
    float_fields = {name: index for index, name in enumerate(float_table.fields)}
    uint_fields = {name: index for index, name in enumerate(uint_table.fields)}

    float_settings = {
        "tether_compression_values": "tether_compression_limit",
        "tether_stretch_values": "tether_stretch_limit",
        "angle_restoration_velocity_attenuation_values":
            "angle_restoration_velocity_attenuation",
        "angle_restoration_gravity_falloff_values":
            "angle_restoration_gravity_falloff",
        "angle_limit_stiffness_values": "angle_limit_stiffness",
        "motion_stiffness_values": "motion_stiffness",
        "motion_backstop_radii": "backstop_radius",
    }
    for setting_name, field_name in float_settings.items():
        expected = float_table.values[owners, float_fields[field_name]]
        assert np.array_equal(settings[setting_name], expected), setting_name
        assert settings[setting_name].flags.c_contiguous
        assert not settings[setting_name].flags.writeable

    uint_settings = {
        "angle_restoration_enabled_values": "use_angle_restoration",
        "angle_limit_enabled_values": "use_angle_limit",
        "motion_normal_axis_values": "normal_axis",
        "motion_max_distance_enabled_values": "use_max_distance",
        "motion_backstop_enabled_values": "use_backstop",
    }
    for setting_name, field_name in uint_settings.items():
        expected = uint_table.values[owners, uint_fields[field_name]]
        assert np.array_equal(settings[setting_name], expected), setting_name

    post_settings = {
        "dynamic_friction_values": "collision_dynamic_friction",
        "static_friction_speed_values": "collision_static_friction",
        "particle_speed_limit_values": "particle_speed_limit",
    }
    for setting_name, field_name in post_settings.items():
        expected = float_table.values[owners, float_fields[field_name]]
        assert np.array_equal(settings["post_step"][setting_name], expected), setting_name
    assert set(settings["motion_normal_axis_values"].tolist()) == {0, 5}
    assert len(set(settings["tether_compression_values"].tolist())) == 2


def test_native_cpu_compiled_external_collision_filters_each_partition():
    compiled = _compiled_multi(
        collision_modes=(1, 1), external_collision_masks=(1, 2)
    )
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    original = np.asarray(frame.animated_base_world_positions, dtype=np.float32).copy()
    center = np.asarray(((2.0, 2.0, 2.0),), dtype=np.float32)
    collider = collider_frame.MC2DomainColliderFrameSpec(
        frame=frame.frame,
        source_pointers=(10, 11),
        collider_keys=("sphere",),
        collider_types=np.asarray((0,), dtype=np.int32),
        collider_group_bits=np.asarray((1,), dtype=np.int32),
        collider_centers=center,
        collider_segment_a=center,
        collider_segment_b=center,
        collider_old_centers=center,
        collider_old_segment_a=center,
        collider_old_segment_b=center,
        collider_radii=np.asarray((2.0,), dtype=np.float32),
        frame_signature="0" * 64,
    )
    try:
        domain.update_frame(frame)
        invalid = dict(
            collider.native_mapping(),
            collider_centers=np.asarray(((np.nan, 2.0, 2.0),)),
        )
        try:
            domain.step_compiled_external_collision(invalid)
        except ValueError as exc:
            assert "finite" in str(exc)
        else:
            raise AssertionError("compiled external collision accepted a non-finite table")
        assert domain.inspect()["kernel"]["step_count"] == 0

        domain.begin_constraint_debug(32)
        before = domain.read_output().world_positions.copy()
        domain.step_compiled_external_collision(collider)
        domain.end_constraint_debug()
        output = domain.read_output().world_positions
        partition_index = compiled.program.particle_partition_index
        first = partition_index == 0
        second = partition_index == 1
        assert np.any(np.abs(output[first] - original[first]) > np.float32(1.0e-6))
        np.testing.assert_array_equal(output[second], original[second])
        state = domain.inspect()["kernel"]
        assert state["compiled_external_ready"] is True
        assert state["compiled_external_edge_count"] == 4
        assert state["compiled_external_step_count"] == 1
        external = domain.read_constraint_debug_state()[
            "external_collision_results"
        ]
        assert np.array_equal(external["partition_modes"], (1, 1))
        assert np.array_equal(external["partition_masks"], (1, 2))
        assert np.array_equal(
            external["particle_partitions"], partition_index
        )
        assert external["vertices"].shape[1:] == (2,)
        assert external["origins"].shape[1:] == (2, 3)
        assert external["role_corrections"].shape[1:] == (2, 3)
        assert np.all(external["primitive_kinds"] == 0)
        assert np.isfinite(external["friction_before"]).all()
        assert np.isfinite(external["friction_after"]).all()
        for vertex in range(compiled.program.particle_count):
            expected = np.zeros((3,), dtype=np.float32)
            for role in range(2):
                selected = external["vertices"][:, role] == vertex
                expected += np.sum(
                    external["role_corrections"][selected, role], axis=0
                )
            np.testing.assert_allclose(
                output[vertex] - before[vertex],
                expected,
                atol=2.0e-7,
                rtol=0.0,
            )
        domain.clear_constraint_debug()
    finally:
        domain.dispose()


def test_native_cpu_reference_pipeline_full_sequences_collision_passes():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    count = compiled.program.particle_count
    edge_table = next((table for table in compiled.program.primitive_tables if table.kind == "edge"), None)
    triangle_table = next((table for table in compiled.program.primitive_tables if table.kind == "triangle"), None)
    edges = np.asarray(edge_table.indices if edge_table is not None else np.empty((0, 2)), dtype=np.int32)
    triangles = np.asarray(triangle_table.indices if triangle_table is not None else np.empty((0, 3)), dtype=np.int32)
    center = np.asarray(((1.0, 2.0, 2.0),), dtype=np.float32)
    point = {
        "base_positions": frame.animated_base_world_positions,
        "collision_radii": np.full(count, 0.1, dtype=np.float32),
        "friction": np.zeros(count, dtype=np.float32),
        "collided_by_groups": 1,
        "collider_types": np.asarray((0,), dtype=np.int32),
        "collider_group_bits": np.asarray((1,), dtype=np.int32),
        "collider_centers": center,
        "collider_segment_a": center,
        "collider_segment_b": center,
        "collider_old_centers": center,
        "collider_old_segment_a": center,
        "collider_old_segment_b": center,
        "collider_radii": np.asarray((0.5,), dtype=np.float32),
    }
    edge = {key: value for key, value in point.items() if key != "base_positions"}
    edge["edges"] = edges
    self_collision = {
        "old_positions": frame.animated_base_world_positions,
        "edges": edges,
        "triangles": triangles,
        "friction": np.zeros(count, dtype=np.float32),
        "surface_thickness": 0.02,
    }
    try:
        domain.update_frame(frame)
        settings = {
            "anchor_component_local_positions": np.zeros((1, 3), dtype=np.float32),
            "dt": 0.1, "frame_interpolation": 1.0,
            "distance_weights": np.ones(1, dtype=np.float32),
            "simulation_power": 1.0, "distance_simulation_power": 1.0,
            "bending_simulation_power": 1.0,
            "velocity_weight": 1.0, "gravity": (0.0, -1.0, 0.0),
            "step_basic_positions": frame.animated_base_world_positions,
            "tether_compression": 0.4, "tether_stretch": 0.03,
            "step_basic_rotations": frame.animated_base_world_rotations,
            "angle_restoration_values": np.ones(count, dtype=np.float32),
            "angle_limit_values": np.ones(count, dtype=np.float32),
            "angle_restoration_velocity_attenuation": 0.0,
            "angle_restoration_gravity_falloff": 0.0,
            "angle_limit_stiffness": 0.2,
            "angle_restoration_enabled": True, "angle_limit_enabled": True,
            "motion_base_positions": frame.animated_base_world_positions,
            "motion_base_rotations": frame.animated_base_world_rotations,
            "motion_max_distances": np.zeros(count, dtype=np.float32),
            "motion_stiffness_values": np.ones(count, dtype=np.float32),
            "motion_backstop_radii": np.zeros(count, dtype=np.float32),
            "motion_backstop_distances": np.zeros(count, dtype=np.float32),
            "motion_normal_axis": 1, "motion_max_distance_enabled": True,
            "motion_backstop_enabled": False,
            "point_collision": point, "edge_collision": edge,
            "self_collision": self_collision,
        }
        try:
            domain.step_reference_pipeline_full(settings)
        except ValueError as exc:
            assert "mutually exclusive" in str(exc)
        else:
            raise AssertionError("reference pipeline accepted point and edge together")
        assert domain.inspect()["kernel"]["step_count"] == 0
        settings["edge_collision"] = None
        domain.step_reference_pipeline_full(settings)
        assert np.isfinite(domain.read_output().world_positions).all()
        assert domain.inspect()["kernel"]["step_count"] == 9
    finally:
        domain.dispose()


def test_native_cpu_kernel_exposes_external_point_collision_slice():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    try:
        domain.update_frame(frame)
        center = np.asarray(((1.0, 2.0, 2.0),), dtype=np.float32)
        domain.step_external_collision({
            "base_positions": frame.animated_base_world_positions,
            "collision_radii": np.full(compiled.program.particle_count, 0.1, dtype=np.float32),
            "friction": np.zeros(compiled.program.particle_count, dtype=np.float32),
            "collided_by_groups": 1,
            "collider_types": np.asarray((0,), dtype=np.int32),
            "collider_group_bits": np.asarray((1,), dtype=np.int32),
            "collider_centers": center,
            "collider_segment_a": center,
            "collider_segment_b": center,
            "collider_old_centers": center,
            "collider_old_segment_a": center,
            "collider_old_segment_b": center,
            "collider_radii": np.asarray((0.5,), dtype=np.float32),
        })
        assert np.isfinite(domain.read_output().world_positions).all()
        assert domain.inspect()["kernel"]["step_count"] == 1
    finally:
        domain.dispose()


def test_native_cpu_kernel_exposes_self_collision_slice():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    edge_table = next((table for table in compiled.program.primitive_tables if table.kind == "edge"), None)
    triangle_table = next((table for table in compiled.program.primitive_tables if table.kind == "triangle"), None)
    edges = np.asarray(edge_table.indices if edge_table is not None else np.empty((0, 2)), dtype=np.int32)
    triangles = np.asarray(triangle_table.indices if triangle_table is not None else np.empty((0, 3)), dtype=np.int32)
    try:
        domain.update_frame(frame)
        domain.step_self_collision({
            "old_positions": frame.animated_base_world_positions,
            "edges": edges,
            "triangles": triangles,
            "friction": np.zeros(compiled.program.particle_count, dtype=np.float32),
            "surface_thickness": 0.02,
        })
        assert np.isfinite(domain.read_output().world_positions).all()
        assert domain.inspect()["kernel"]["step_count"] == 1
    finally:
        domain.dispose()


def test_native_cpu_kernel_exposes_external_edge_collision_slice():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    edge_table = next((table for table in compiled.program.primitive_tables if table.kind == "edge"), None)
    edges = np.asarray(edge_table.indices if edge_table is not None else np.empty((0, 2)), dtype=np.int32)
    center = np.asarray(((1.0, 2.0, 2.0),), dtype=np.float32)
    try:
        domain.update_frame(frame)
        domain.step_external_edge_collision({
            "collision_radii": np.full(compiled.program.particle_count, 0.1, dtype=np.float32),
            "edges": edges,
            "friction": np.zeros(compiled.program.particle_count, dtype=np.float32),
            "collided_by_groups": 1,
            "collider_types": np.asarray((0,), dtype=np.int32),
            "collider_group_bits": np.asarray((1,), dtype=np.int32),
            "collider_centers": center,
            "collider_segment_a": center,
            "collider_segment_b": center,
            "collider_old_centers": center,
            "collider_old_segment_a": center,
            "collider_old_segment_b": center,
            "collider_radii": np.asarray((0.5,), dtype=np.float32),
        })
        assert np.isfinite(domain.read_output().world_positions).all()
        assert domain.inspect()["kernel"]["step_count"] == 1
    finally:
        domain.dispose()


if __name__ == "__main__":
    test_native_cpu_backend_uses_partitioned_animation_pose_ratio()
    print("PASS test_native_cpu_backend_uses_partitioned_animation_pose_ratio")
    test_native_cpu_backend_hot_updates_parameters_without_replacing_history()
    print("PASS test_native_cpu_backend_hot_updates_parameters_without_replacing_history")
    test_native_cpu_backend_rolls_back_parameters_when_host_commit_fails()
    print("PASS test_native_cpu_backend_rolls_back_parameters_when_host_commit_fails")
    test_native_cpu_backend_runs_compiled_whole_domain_self_policy()
    print("PASS test_native_cpu_backend_runs_compiled_whole_domain_self_policy")
    test_native_cpu_backend_blocks_compiled_whole_domain_self_pair()
    print("PASS test_native_cpu_backend_blocks_compiled_whole_domain_self_pair")
    test_native_whole_domain_self_debug_reports_intersection()
    print("PASS test_native_whole_domain_self_debug_reports_intersection")
    test_native_cpu_kernel_runs_only_explicit_data_path_mode()
    print("PASS test_native_cpu_kernel_runs_only_explicit_data_path_mode")
    test_native_debug_off_inspect_does_not_readback_dynamics()
    print("PASS test_native_debug_off_inspect_does_not_readback_dynamics")
    test_native_cpu_kernel_exposes_distance_slice_only_when_requested()
    print("PASS test_native_cpu_kernel_exposes_distance_slice_only_when_requested")
    test_native_cpu_kernel_exposes_tether_slice_with_step_basic_rest_lengths()
    print("PASS test_native_cpu_kernel_exposes_tether_slice_with_step_basic_rest_lengths")
    test_native_constraint_debug_distance_and_tether_sum_to_pass_delta()
    print("PASS test_native_constraint_debug_distance_and_tether_sum_to_pass_delta")
    test_native_cpu_kernel_exposes_angle_slice_with_baseline_transaction()
    print("PASS test_native_cpu_kernel_exposes_angle_slice_with_baseline_transaction")
    test_native_cpu_kernel_exposes_motion_slice_with_explicit_base_pose()
    print("PASS test_native_cpu_kernel_exposes_motion_slice_with_explicit_base_pose")
    test_native_cpu_kernel_exposes_inertia_slice_only_when_requested()
    print("PASS test_native_cpu_kernel_exposes_inertia_slice_only_when_requested")
    test_native_cpu_kernel_exposes_integration_slice_only_when_requested()
    print("PASS test_native_cpu_kernel_exposes_integration_slice_only_when_requested")
    test_native_cpu_kernel_tracks_multi_partition_frame_history()
    print("PASS test_native_cpu_kernel_tracks_multi_partition_frame_history")
    test_native_cpu_kernel_exposes_center_frame_shift_slice()
    print("PASS test_native_cpu_kernel_exposes_center_frame_shift_slice")
    test_native_cpu_domain_commits_center_frame_shift_transaction()
    print("PASS test_native_cpu_domain_commits_center_frame_shift_transaction")
    task_reference_teleport_contracts()
    print("PASS task_reference_teleport_contracts")
    test_native_cpu_reset_teleport_restarts_center_stabilization_once()
    print("PASS test_native_cpu_reset_teleport_restarts_center_stabilization_once")
    test_native_cpu_reference_slice_prefix_keeps_fixed_pass_order()
    print("PASS test_native_cpu_reference_slice_prefix_keeps_fixed_pass_order")
    test_native_cpu_reference_pipeline_runs_structural_order_through_motion()
    print("PASS test_native_cpu_reference_pipeline_runs_structural_order_through_motion")
    test_native_cpu_reference_pipeline_full_accepts_explicit_collision_slots()
    print("PASS test_native_cpu_reference_pipeline_full_accepts_explicit_collision_slots")
    test_native_cpu_compiled_pipeline_runs_whole_domain_self_and_owned_post()
    print("PASS test_native_cpu_compiled_pipeline_runs_whole_domain_self_and_owned_post")
    test_compiled_pipeline_settings_expand_each_partition_without_scalar_collapse()
    print("PASS test_compiled_pipeline_settings_expand_each_partition_without_scalar_collapse")
    test_native_cpu_compiled_external_collision_filters_each_partition()
    print("PASS test_native_cpu_compiled_external_collision_filters_each_partition")
    test_native_cpu_reference_pipeline_full_sequences_collision_passes()
    print("PASS test_native_cpu_reference_pipeline_full_sequences_collision_passes")
    test_native_cpu_kernel_exposes_external_point_collision_slice()
    print("PASS test_native_cpu_kernel_exposes_external_point_collision_slice")
    test_native_cpu_kernel_exposes_self_collision_slice()
    print("PASS test_native_cpu_kernel_exposes_self_collision_slice")
    test_native_cpu_kernel_exposes_external_edge_collision_slice()
    print("PASS test_native_cpu_kernel_exposes_external_edge_collision_slice")
