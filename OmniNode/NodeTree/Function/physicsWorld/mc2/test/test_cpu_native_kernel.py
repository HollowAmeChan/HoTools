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


if __name__ == "__main__":
    test_native_cpu_kernel_runs_only_explicit_data_path_mode()
    print("PASS test_native_cpu_kernel_runs_only_explicit_data_path_mode")
    test_native_cpu_kernel_exposes_distance_slice_only_when_requested()
    print("PASS test_native_cpu_kernel_exposes_distance_slice_only_when_requested")
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
