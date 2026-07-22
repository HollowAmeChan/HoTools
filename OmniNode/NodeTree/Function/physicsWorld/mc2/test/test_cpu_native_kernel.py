"""E3 Python adapter to native CPU data-path owner integration test."""

from __future__ import annotations

import importlib
import json
import os
import sys
import types

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

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "domain_pipeline", "two_mesh_static", "two_mesh_domain_v1.json",
)


def _compiled():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"][0]
    snapshot = ir.make_mc2_mesh_partition_static_snapshot(**payload)
    fragment = fragment_module.build_mc2_mesh_static_fragment(snapshot)
    effective = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(self_collision_mode=2),
        parameters.make_mc2_setup_options("mesh_cloth"),
        parameters.make_mc2_task_parameters(),
    )
    return compiler.compile_mc2_mesh_static_fragment(fragment, effective)


def _compiled_multi():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payloads = json.load(handle)["static_snapshots"]
    fragments = tuple(
        fragment_module.build_mc2_mesh_static_fragment(
            ir.make_mc2_mesh_partition_static_snapshot(**payload)
        )
        for payload in payloads
    )
    effectives = tuple(
        runtime.make_mc2_runtime_parameters(
            parameters.make_mc2_particle_profile(self_collision_mode=2),
            parameters.make_mc2_setup_options("mesh_cloth"),
            parameters.make_mc2_task_parameters(),
        )
        for _fragment in fragments
    )
    return compiler.compile_mc2_mesh_static_fragments(fragments, effectives)


def _frame(program):
    return ir.make_mc2_domain_frame_packet(
        program,
        frame=6,
        generation=2,
        animated_base_world_positions=program.particle_bind_position + np.float32(2.0),
        animated_base_world_rotations=program.particle_bind_rotation,
        animated_base_world_normals=np.asarray(((0.0, 0.0, 1.0),) * 3, dtype=np.float32),
        partition_world_position=((2.0, 0.0, 0.0),),
        partition_world_rotation=((0.0, 0.0, 0.0, 1.0),),
        partition_world_scale=((1.0, 1.0, 1.0),),
        partition_world_linear=(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),),
        frame_delta_time=0.1,
        simulation_delta_time=0.1,
        time_scale=1.0,
        is_running=True,
    )


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
        assert debug_state["real_velocities"].shape == (
            compiled.program.particle_count, 3
        )
        assert inspection["step_count"] == 1
    finally:
        domain.dispose()
    assert domain.disposed


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
        assert domain.inspect()["kernel"]["step_count"] == 1
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
        assert state["step_count"] == 3
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
        assert state["step_count"] == 6
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
        domain.step_reference_pipeline_full({
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
        })
        assert np.isfinite(domain.read_output().world_positions).all()
        assert domain.inspect()["kernel"]["step_count"] == 6
        assert domain.inspect()["step_count"] == 1
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
        assert domain.inspect()["kernel"]["step_count"] == 8
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
    test_native_cpu_kernel_runs_only_explicit_data_path_mode()
    print("PASS test_native_cpu_kernel_runs_only_explicit_data_path_mode")
    test_native_cpu_kernel_exposes_distance_slice_only_when_requested()
    print("PASS test_native_cpu_kernel_exposes_distance_slice_only_when_requested")
    test_native_cpu_kernel_exposes_tether_slice_with_step_basic_rest_lengths()
    print("PASS test_native_cpu_kernel_exposes_tether_slice_with_step_basic_rest_lengths")
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
    test_native_cpu_reference_slice_prefix_keeps_fixed_pass_order()
    print("PASS test_native_cpu_reference_slice_prefix_keeps_fixed_pass_order")
    test_native_cpu_reference_pipeline_runs_structural_order_through_motion()
    print("PASS test_native_cpu_reference_pipeline_runs_structural_order_through_motion")
    test_native_cpu_reference_pipeline_full_accepts_explicit_collision_slots()
    print("PASS test_native_cpu_reference_pipeline_full_accepts_explicit_collision_slots")
    test_native_cpu_reference_pipeline_full_sequences_collision_passes()
    print("PASS test_native_cpu_reference_pipeline_full_sequences_collision_passes")
    test_native_cpu_kernel_exposes_external_point_collision_slice()
    print("PASS test_native_cpu_kernel_exposes_external_point_collision_slice")
    test_native_cpu_kernel_exposes_self_collision_slice()
    print("PASS test_native_cpu_kernel_exposes_self_collision_slice")
    test_native_cpu_kernel_exposes_external_edge_collision_slice()
    print("PASS test_native_cpu_kernel_exposes_external_edge_collision_slice")
