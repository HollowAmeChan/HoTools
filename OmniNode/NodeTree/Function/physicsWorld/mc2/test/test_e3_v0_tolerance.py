"""E3 same-source V0/DomainV1 tolerance evidence for the prediction pass."""

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
final_proxy_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.final_proxy"
)
baseline_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.mesh_baseline"
)
distance_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.distance_static"
)
bending_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.bending_static"
)
center_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.center_state"
)
self_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.self_collision_static"
)
parameters = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters")
runtime = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters")
frame_state = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.frame_state")
native_context = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.native_context")
cpu_backend = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.cpu_backend")
native_kernel = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.cpu_native_kernel")

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "domain_pipeline", "two_mesh_static", "two_mesh_domain_v1.json",
)


def _source():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"][0]
    return ir.make_mc2_mesh_partition_static_snapshot(**payload)


def _same_source():
    snapshot = _source()
    fragment = fragment_module.build_mc2_mesh_static_fragment(snapshot)
    effective = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(
            gravity=1.0,
            gravity_direction=(0.0, -1.0, 0.0),
            collision_friction=0.0,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            self_collision_mode=0,
        ),
        parameters.make_mc2_setup_options("mesh_cloth"),
        parameters.make_mc2_task_parameters(),
    )
    return snapshot, fragment, compiler.compile_mc2_mesh_static_fragment(fragment, effective), effective


def _same_source_constraints():
    snapshot = _source()
    fragment = fragment_module.build_mc2_mesh_static_fragment(snapshot)
    effective = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(
            gravity=1.0,
            gravity_direction=(0.0, -1.0, 0.0),
            collision_friction=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            self_collision_mode=0,
        ),
        parameters.make_mc2_setup_options("mesh_cloth"),
        parameters.make_mc2_task_parameters(),
    )
    return snapshot, fragment, compiler.compile_mc2_mesh_static_fragment(fragment, effective), effective


def _frame(program):
    return ir.make_mc2_domain_frame_packet(
        program,
        frame=6,
        generation=2,
        animated_base_world_positions=program.particle_bind_position,
        animated_base_world_rotations=program.particle_bind_rotation,
        animated_base_world_normals=np.asarray(((0.0, 0.0, 1.0),) * program.particle_count, dtype=np.float32),
        partition_world_position=((0.0, 0.0, 0.0),),
        partition_world_rotation=((0.0, 0.0, 0.0, 1.0),),
        partition_world_scale=((1.0, 1.0, 1.0),),
        partition_world_linear=(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),),
        frame_delta_time=0.1,
        simulation_delta_time=0.1,
        time_scale=1.0,
        is_running=True,
    )


def _register_v0_static(context, snapshot, fragment):
    proxy = final_proxy_module.build_mc2_final_proxy(
        task_id=snapshot.partition_id,
        setup_type="mesh_cloth",
        vertex_identities=tuple(f"mesh:v{int(value)}" for value in snapshot.source_element_ids),
        local_positions=snapshot.local_positions,
        local_normals=snapshot.local_normals,
        local_tangents=fragment.final_proxy.local_tangents,
        uvs=fragment.final_proxy.uvs,
        vertex_attributes=fragment.final_proxy.vertex_attributes,
        lines=snapshot.edges,
        triangles=snapshot.triangles,
        triangle_uvs=np.asarray(fragment.final_proxy.uvs, dtype=np.float64)[snapshot.triangles],
        native_context=context,
    )
    context.update_proxy_finalizer_derived(
        proxy=proxy.proxy,
        finalizer=proxy.finalizer,
    )
    baseline = baseline_module.build_mc2_mesh_baseline(proxy.proxy, native_context=context)
    context.update_baseline_derived({
        "attributes": baseline.final_proxy.vertex_attributes,
        "native_registration": baseline.baseline.native_registration,
    })
    distance_module.build_mc2_distance_static(
        baseline.final_proxy,
        baseline.baseline,
        vertex_to_vertex_ranges=proxy.vertex_to_vertex_ranges,
        vertex_to_vertex_data=proxy.vertex_to_vertex_data,
        native_context=context,
    )
    bending_module.build_mc2_bending_static(
        baseline.final_proxy,
        initial_local_to_world_columns=tuple(tuple(float(v) for v in row) for row in snapshot.source_bind_matrix),
        native_context=context,
    )
    center_module.build_mc2_center_static(
        baseline.final_proxy,
        vertex_bind_pose_rotations=proxy.vertex_bind_pose_rotations,
        world_gravity_direction=(0.0, -1.0, 0.0),
        native_context=context,
    )
    self_module.build_mc2_self_collision_static(
        baseline.final_proxy,
        baseline.baseline.depths,
        native_context=context,
    )


def test_e3_prediction_matches_same_source_v0_and_domain():
    snapshot, fragment, compiled, effective = _same_source()
    frame = _frame(compiled.program)
    v0 = native_context.MC2NativeContextV0(compiled.program.particle_count)
    domain = cpu_backend.create_mc2_cpu_backend_domain(
        compiled,
        native_kernel.MC2NativeCPUKernelV1(),
    )
    try:
        _register_v0_static(v0, snapshot, fragment)
        v0.update_parameters(effective)
        v0.set_tether_enabled(False)
        domain.update_frame(frame)
        domain_before = domain.read_output().world_positions.copy()
        v0.update_dynamic(frame_state.make_mc2_frame_input(
            task_id=snapshot.partition_id,
            topology_signature=fragment.final_proxy.proxy_signature,
            frame=frame.frame,
            generation=frame.generation,
            world_positions=domain_before,
            world_rotations_xyzw=frame.animated_base_world_rotations,
        ))
        v0.reset()
        dt = 0.1
        frequency_ratio = 90.0 * dt
        simulation_power_z = frequency_ratio if frequency_ratio <= 1.0 else frequency_ratio ** 0.3
        v0.step_no_collision(dt)
        v0_positions, _ = v0.read()
        domain.step({
            "data_path_only": True,
            "integration_slice": True,
            "dt": dt,
            "simulation_power": simulation_power_z,
            "velocity_weight": 1.0,
            "gravity": (0.0, -1.0, 0.0),
        })
        domain_positions = domain.read_output().world_positions
        assert np.isfinite(v0_positions).all()
        assert np.isfinite(domain_positions).all()
        np.testing.assert_allclose(domain_positions, v0_positions, rtol=2.0e-5, atol=2.0e-5)
    finally:
        domain.dispose()
        v0.dispose()


def test_e3_full_reference_without_collisions_matches_same_source_v0_and_domain():
    snapshot, fragment, compiled, effective = _same_source_constraints()
    frame = _frame(compiled.program)
    v0 = native_context.MC2NativeContextV0(compiled.program.particle_count)
    domain = cpu_backend.create_mc2_cpu_backend_domain(
        compiled,
        native_kernel.MC2NativeCPUKernelV1(),
    )
    try:
        _register_v0_static(v0, snapshot, fragment)
        v0.update_parameters(effective)
        domain.update_frame(frame)
        domain_before = domain.read_output().world_positions.copy()
        v0.update_dynamic(frame_state.make_mc2_frame_input(
            task_id=snapshot.partition_id,
            topology_signature=fragment.final_proxy.proxy_signature,
            frame=frame.frame,
            generation=frame.generation,
            world_positions=domain_before,
            world_rotations_xyzw=frame.animated_base_world_rotations,
        ))
        v0.reset()
        dt = 0.1
        frequency_ratio = 90.0 * dt
        simulation_power_z = frequency_ratio if frequency_ratio <= 1.0 else frequency_ratio ** 0.3
        simulation_power_y = frequency_ratio ** 0.5 if frequency_ratio > 1.0 else frequency_ratio
        v0.step_no_collision(dt)
        v0_positions, _ = v0.read()
        domain.step_reference_pipeline_full({
            "anchor_component_local_positions": np.zeros((1, 3), dtype=np.float32),
            "dt": dt,
            "frame_interpolation": 1.0,
            "distance_weights": np.ones(1, dtype=np.float32),
            "simulation_power": simulation_power_z,
            "distance_simulation_power": simulation_power_y,
            "bending_simulation_power": simulation_power_y,
            "velocity_weight": 1.0,
            "gravity": (0.0, -1.0, 0.0),
            "step_basic_positions": domain_before,
            "tether_compression": 0.4,
            "tether_stretch": 0.03,
            "step_basic_rotations": frame.animated_base_world_rotations,
            "angle_restoration_values": np.zeros(compiled.program.particle_count, dtype=np.float32),
            "angle_limit_values": np.zeros(compiled.program.particle_count, dtype=np.float32),
            "angle_restoration_velocity_attenuation": 0.0,
            "angle_restoration_gravity_falloff": 0.0,
            "angle_limit_stiffness": 0.0,
            "angle_restoration_enabled": False,
            "angle_limit_enabled": False,
            "motion_base_positions": domain_before,
            "motion_base_rotations": frame.animated_base_world_rotations,
            "motion_max_distances": np.zeros(compiled.program.particle_count, dtype=np.float32),
            "motion_stiffness_values": np.ones(compiled.program.particle_count, dtype=np.float32),
            "motion_backstop_radii": np.zeros(compiled.program.particle_count, dtype=np.float32),
            "motion_backstop_distances": np.zeros(compiled.program.particle_count, dtype=np.float32),
            "motion_normal_axis": 1,
            "motion_max_distance_enabled": False,
            "motion_backstop_enabled": False,
            "point_collision": None,
            "edge_collision": None,
            "self_collision": None,
        })
        domain_positions = domain.read_output().world_positions
        np.testing.assert_allclose(domain_positions, v0_positions, rtol=4.0e-5, atol=4.0e-5)
    finally:
        domain.dispose()
        v0.dispose()


def test_e3_native_step_basic_pose_matches_v0_angle_reference():
    snapshot, fragment, compiled, _unused_effective = _same_source_constraints()
    effective = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(
            gravity=1.0,
            gravity_direction=(0.0, -1.0, 0.0),
            collision_friction=0.0,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=True,
            angle_restoration_stiffness=0.2,
            angle_limit_enabled=False,
            self_collision_mode=0,
        ),
        parameters.make_mc2_setup_options("mesh_cloth"),
        parameters.make_mc2_task_parameters(),
    )
    frame = _frame(compiled.program)
    v0 = native_context.MC2NativeContextV0(compiled.program.particle_count)
    domain = cpu_backend.create_mc2_cpu_backend_domain(
        compiled,
        native_kernel.MC2NativeCPUKernelV1(),
    )
    try:
        _register_v0_static(v0, snapshot, fragment)
        v0.update_parameters(effective)
        v0.set_debug_constraint_results(native_context.MC2_DEBUG_CONSTRAINT_ANGLE)
        domain.update_frame(frame)
        domain_before = domain.read_output().world_positions.copy()
        v0.update_dynamic(frame_state.make_mc2_frame_input(
            task_id=snapshot.partition_id,
            topology_signature=fragment.final_proxy.proxy_signature,
            frame=frame.frame,
            generation=frame.generation,
            world_positions=domain_before,
            world_rotations_xyzw=frame.animated_base_world_rotations,
        ))
        v0.reset()
        v0.step_no_collision(0.1)
        debug = v0.refresh_debug_draw_snapshot(
            include_step_basic=True,
            include_angle_restoration=True,
            include_constraint_results=True,
        )
        pose = domain.prepare_step_basic_pose(0.0)
        np.testing.assert_allclose(
            np.asarray(pose["positions"], dtype=np.float32),
            np.asarray(debug["step_basic_positions"], dtype=np.float32),
            rtol=2.0e-5,
            atol=2.0e-5,
        )
        np.testing.assert_allclose(
            np.asarray(pose["rotations"], dtype=np.float32),
            np.asarray(debug["step_basic_rotations_xyzw"], dtype=np.float32),
            rtol=2.0e-5,
            atol=2.0e-5,
        )
        frequency_ratio = 90.0 * 0.1
        simulation_power_z = frequency_ratio ** 0.3
        domain.step({
            "data_path_only": True,
            "integration_slice": True,
            "dt": 0.1,
            "simulation_power": simulation_power_z,
            "velocity_weight": 1.0,
            "gravity": (0.0, -1.0, 0.0),
        })
        domain.step({
            "data_path_only": True,
            "angle_slice": True,
            "step_basic_positions": pose["positions"],
            "step_basic_rotations": pose["rotations"],
            "restoration_values": np.full(
                compiled.program.particle_count,
                np.float32(0.2 * (9.0 ** 1.8)),
                dtype=np.float32,
            ),
            "limit_values": np.zeros(compiled.program.particle_count, dtype=np.float32),
            "restoration_velocity_attenuation": 0.0,
            "restoration_gravity_falloff": 0.0,
            "limit_stiffness": 0.0,
            "restoration_enabled": True,
            "limit_enabled": False,
        })
        np.testing.assert_allclose(
            domain.read_output().world_positions,
            np.asarray(v0.read()[0], dtype=np.float32),
            rtol=4.0e-5,
            atol=4.0e-5,
        )
    finally:
        domain.dispose()
        v0.dispose()


if __name__ == "__main__":
    test_e3_prediction_matches_same_source_v0_and_domain()
    print("PASS E3 same-source V0/Domain prediction tolerance")
    test_e3_full_reference_without_collisions_matches_same_source_v0_and_domain()
    print("PASS E3 same-source V0/Domain full no-collision tolerance")
    test_e3_native_step_basic_pose_matches_v0_angle_reference()
    print("PASS E3 native StepBasic pose matches V0 Angle reference")
