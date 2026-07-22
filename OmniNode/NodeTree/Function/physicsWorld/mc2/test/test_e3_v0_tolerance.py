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
collider_frame = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.collider_frame"
)
scheduler = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.scheduler"
)
reference_step = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.reference_step"
)

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
    return _frame_at(
        program,
        frame=6,
        generation=2,
        positions=program.particle_bind_position,
    )


def _frame_at(
    program,
    *,
    frame,
    generation,
    positions,
    partition_world_position=((0.0, 0.0, 0.0),),
    frame_delta_time=0.1,
    simulation_delta_time=0.1,
    time_scale=1.0,
    is_running=True,
    partition_frame_flags=(0,),
):
    return ir.make_mc2_domain_frame_packet(
        program,
        frame=frame,
        generation=generation,
        animated_base_world_positions=positions,
        animated_base_world_rotations=program.particle_bind_rotation,
        animated_base_world_normals=np.asarray(((0.0, 0.0, 1.0),) * program.particle_count, dtype=np.float32),
        partition_world_position=partition_world_position,
        partition_world_rotation=((0.0, 0.0, 0.0, 1.0),),
        partition_world_scale=((1.0, 1.0, 1.0),),
        partition_world_linear=(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),),
        frame_delta_time=frame_delta_time,
        simulation_delta_time=simulation_delta_time,
        time_scale=time_scale,
        is_running=is_running,
        partition_frame_flags=partition_frame_flags,
    )


def _center_frame_pose(frame, generation, position):
    return center_module.MC2CenterFramePoseSpec(
        frame=frame,
        generation=generation,
        component_identity="e3-center-component",
        component_world_position=tuple(float(value) for value in position),
        component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        component_world_scale=(1.0, 1.0, 1.0),
    )


def _full_reference_settings(
    program,
    positions,
    rotations,
    *,
    motion_base_positions=None,
    motion_base_rotations=None,
    point_collision=None,
    edge_collision=None,
    self_collision=None,
    post_step=None,
    collision_mode=None,
    self_collision_enabled=None,
):
    count = program.particle_count
    settings = {
        "anchor_component_local_positions": np.zeros((1, 3), dtype=np.float32),
        "dt": 0.1,
        "frame_interpolation": 1.0,
        "distance_weights": np.ones(1, dtype=np.float32),
        "simulation_power": 1.0,
        "distance_simulation_power": 1.0,
        "bending_simulation_power": 1.0,
        "velocity_weight": 1.0,
        "gravity": (0.0, 0.0, 0.0),
        "step_basic_positions": positions,
        "tether_compression": 0.4,
        "tether_stretch": 0.03,
        "step_basic_rotations": rotations,
        "angle_restoration_values": np.zeros(count, dtype=np.float32),
        "angle_limit_values": np.zeros(count, dtype=np.float32),
        "angle_restoration_velocity_attenuation": 0.0,
        "angle_restoration_gravity_falloff": 0.0,
        "angle_limit_stiffness": 0.0,
        "angle_restoration_enabled": False,
        "angle_limit_enabled": False,
        "motion_base_positions": positions if motion_base_positions is None else motion_base_positions,
        "motion_base_rotations": rotations if motion_base_rotations is None else motion_base_rotations,
        "motion_max_distances": np.zeros(count, dtype=np.float32),
        "motion_stiffness_values": np.ones(count, dtype=np.float32),
        "motion_backstop_radii": np.zeros(count, dtype=np.float32),
        "motion_backstop_distances": np.zeros(count, dtype=np.float32),
        "motion_normal_axis": 1,
        "motion_max_distance_enabled": False,
        "motion_backstop_enabled": False,
        "point_collision": point_collision,
        "edge_collision": edge_collision,
        "self_collision": self_collision,
    }
    if post_step is not None:
        settings["post_step"] = post_step
    if collision_mode is not None:
        settings["collision_mode"] = collision_mode
    if self_collision_enabled is not None:
        settings["self_collision_enabled"] = self_collision_enabled
    return settings


def _post_step_settings(effective, old_positions, dt=0.1):
    floats = effective.debug_dict()["float_values"]
    return {
        "old_positions": old_positions,
        "dt": dt,
        "dynamic_friction": floats["collision_dynamic_friction"],
        "static_friction_speed": floats["collision_static_friction"],
        "particle_speed_limit": floats["particle_speed_limit"],
        "velocity_weight": 1.0,
    }


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
        radius_multipliers=fragment.radius_multipliers,
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
        simulation_power_z = scheduler.derive_mc2_simulation_powers(dt).integration
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
        powers = scheduler.derive_mc2_simulation_powers(dt)
        simulation_power_z = powers.integration
        simulation_power_y = powers.distance_bending
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


def test_e3_full_reference_post_history_matches_same_source_v0():
    """The explicit transaction must commit V0 real-velocity history too."""
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
        powers = scheduler.derive_mc2_simulation_powers(dt)
        simulation_power_z = powers.integration
        simulation_power_y = powers.distance_bending
        v0.step_no_collision(dt)
        v0_positions, _ = v0.read()
        v0_debug = v0.refresh_debug_draw_snapshot(include_dynamics=True)
        domain.step_reference_pipeline_full({
            **_full_reference_settings(
                compiled.program,
                domain_before,
                frame.animated_base_world_rotations,
            ),
            "simulation_power": simulation_power_z,
            "distance_simulation_power": simulation_power_y,
            "bending_simulation_power": simulation_power_y,
            "gravity": (0.0, -1.0, 0.0),
            "post_step": {
                "old_positions": domain_before,
                "dt": dt,
                "dynamic_friction": 0.0,
                "static_friction_speed": 0.0,
                "particle_speed_limit": effective.debug_dict()["float_values"]["particle_speed_limit"],
                "velocity_weight": 1.0,
            },
        })
        domain_positions = domain.read_output().world_positions
        domain_real_velocities = domain.read_debug_state()["real_velocities"]
        np.testing.assert_allclose(domain_positions, v0_positions, rtol=4.0e-5, atol=4.0e-5)
        np.testing.assert_allclose(
            domain_real_velocities,
            np.asarray(v0_debug["dynamics"]["real_velocities"], dtype=np.float32),
            rtol=4.0e-5,
            atol=4.0e-5,
        )
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
        simulation_power_z = scheduler.derive_mc2_simulation_powers(0.1).integration
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


def test_e3_native_motion_branch_matches_v0_after_tether():
    snapshot, fragment, _compiled, _effective = _same_source_constraints()
    effective = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(
            gravity=0.0,
            damping=0.0,
            collision_friction=0.0,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            max_distance_enabled=True,
            max_distance=0.3,
            backstop_enabled=True,
            backstop_radius=0.5,
            backstop_distance=0.1,
            self_collision_mode=0,
        ),
        parameters.make_mc2_setup_options("mesh_cloth"),
        parameters.make_mc2_task_parameters(),
    )
    compiled = compiler.compile_mc2_mesh_static_fragment(fragment, effective)
    program = compiled.program
    v0 = native_context.MC2NativeContextV0(program.particle_count)
    domain = cpu_backend.create_mc2_cpu_backend_domain(
        compiled,
        native_kernel.MC2NativeCPUKernelV1(),
    )
    try:
        _register_v0_static(v0, snapshot, fragment)
        v0.update_parameters(effective)
        base_positions = program.particle_bind_position.copy()
        base_rotations = program.particle_bind_rotation
        first_frame = _frame_at(
            program,
            frame=1,
            generation=1,
            positions=base_positions,
        )
        v0.update_dynamic(frame_state.make_mc2_frame_input(
            task_id=snapshot.partition_id,
            topology_signature=fragment.final_proxy.proxy_signature,
            frame=1,
            generation=1,
            world_positions=base_positions,
            world_rotations_xyzw=base_rotations,
        ))
        v0.reset()
        domain.update_frame(first_frame)
        v0.step_no_collision(0.1)
        domain.step({
            "data_path_only": True,
            "integration_slice": True,
            "dt": 0.1,
            "simulation_power": 1.0,
            "velocity_weight": 1.0,
            "gravity": (0.0, 0.0, 0.0),
        })

        moved_base = base_positions + np.asarray((1.0, 0.0, 0.0), dtype=np.float32)
        second_frame = _frame_at(
            program,
            frame=2,
            generation=1,
            positions=moved_base,
        )
        v0.update_dynamic(frame_state.make_mc2_frame_input(
            task_id=snapshot.partition_id,
            topology_signature=fragment.final_proxy.proxy_signature,
            frame=2,
            generation=1,
            world_positions=moved_base,
            world_rotations_xyzw=base_rotations,
        ))
        v0.step_no_collision(0.1)
        domain.update_frame(second_frame)
        step_basic = domain.prepare_step_basic_pose(0.0)
        domain.step({
            "data_path_only": True,
            "integration_slice": True,
            "dt": 0.1,
            "simulation_power": 1.0,
            "velocity_weight": 1.0,
            "gravity": (0.0, 0.0, 0.0),
        })

        partition_fields = {
            name: index
            for index, name in enumerate(compiled.parameters.partition_parameters.fields)
        }
        particle_fields = {
            name: index
            for index, name in enumerate(compiled.parameters.particle_parameters.fields)
        }
        uint_fields = {
            name: index
            for index, name in enumerate(compiled.parameters.partition_uint_parameters.fields)
        }
        partition_values = compiled.parameters.partition_parameters.values[0]
        particle_values = compiled.parameters.particle_parameters.values
        domain.step({
            "data_path_only": True,
            "tether_slice": True,
            "step_basic_positions": step_basic["positions"],
            "compression": float(
                partition_values[partition_fields["tether_compression_limit"]]
            ),
            "stretch": float(
                partition_values[partition_fields["tether_stretch_limit"]]
            ),
        })
        domain.step({
            "data_path_only": True,
            "motion_slice": True,
            "base_positions": moved_base,
            "base_rotations": base_rotations,
            "max_distances": particle_values[:, particle_fields["max_distance"]],
            "stiffness_values": np.full(
                program.particle_count,
                partition_values[partition_fields["motion_stiffness"]],
                dtype=np.float32,
            ),
            "backstop_radii": np.full(
                program.particle_count,
                partition_values[partition_fields["backstop_radius"]],
                dtype=np.float32,
            ),
            "backstop_distances": particle_values[:, particle_fields["backstop_distance"]],
            "normal_axis": int(
                compiled.parameters.partition_uint_parameters.values[
                    0, uint_fields["normal_axis"]
                ]
            ),
            "max_distance_enabled": True,
            "backstop_enabled": False,
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


def test_e3_native_full_angle_motion_pipeline_matches_v0():
    snapshot, fragment, _compiled, _unused_effective = _same_source_constraints()
    effective = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(
            gravity=1.0,
            gravity_direction=(0.0, -1.0, 0.0),
            damping=0.0,
            collision_friction=0.0,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=True,
            angle_restoration_stiffness=0.2,
            angle_limit_enabled=True,
            angle_limit=15.0,
            angle_limit_stiffness=0.2,
            max_distance_enabled=True,
            max_distance=0.3,
            backstop_enabled=True,
            backstop_radius=0.5,
            backstop_distance=0.1,
            collision_mode=0,
            self_collision_mode=0,
        ),
        parameters.make_mc2_setup_options("mesh_cloth"),
        parameters.make_mc2_task_parameters(),
    )
    compiled = compiler.compile_mc2_mesh_static_fragment(fragment, effective)
    program = compiled.program
    v0 = native_context.MC2NativeContextV0(program.particle_count)
    domain = cpu_backend.create_mc2_cpu_backend_domain(
        compiled,
        native_kernel.MC2NativeCPUKernelV1(),
    )
    try:
        _register_v0_static(v0, snapshot, fragment)
        v0.update_parameters(effective)
        base_positions = program.particle_bind_position.copy()
        frame = _frame_at(program, frame=1, generation=1, positions=base_positions)
        v0.update_dynamic(frame_state.make_mc2_frame_input(
            task_id=snapshot.partition_id,
            topology_signature=fragment.final_proxy.proxy_signature,
            frame=frame.frame,
            generation=frame.generation,
            world_positions=base_positions,
            world_rotations_xyzw=frame.animated_base_world_rotations,
        ))
        v0.reset()
        v0.step_no_collision(0.1)
        v0_positions = np.asarray(v0.read()[0], dtype=np.float32)
        v0_debug = v0.refresh_debug_draw_snapshot(
            include_step_basic=True,
            include_dynamics=True,
        )

        domain.update_frame(frame)
        step_basic = domain.prepare_step_basic_pose()
        settings = reference_step.make_mc2_reference_pipeline_settings(
            compiled,
            frame,
            scheduler.MC2SubstepPlan(
                update_index=0,
                simulation_delta_time=0.1,
                frame_interpolation=1.0,
                is_final_substep=True,
                powers=scheduler.derive_mc2_simulation_powers(0.1),
            ),
            anchor_component_local_positions=np.zeros((1, 3), dtype=np.float32),
            step_basic_positions=step_basic["positions"],
            step_basic_rotations=step_basic["rotations"],
            motion_base_positions=base_positions,
            motion_base_rotations=frame.animated_base_world_rotations,
            distance_weights=np.ones(1, dtype=np.float32),
            old_positions=base_positions,
        )
        domain.step_reference_pipeline_full(settings)
        np.testing.assert_allclose(
            domain.read_output().world_positions,
            v0_positions,
            rtol=5.0e-4,
            atol=5.0e-4,
        )
        np.testing.assert_allclose(
            domain.read_debug_state()["real_velocities"],
            np.asarray(v0_debug["dynamics"]["real_velocities"], dtype=np.float32),
            rtol=5.0e-3,
            atol=2.0e-3,
        )
    finally:
        domain.dispose()
        v0.dispose()


def test_e3_center_frame_shift_two_frame_transaction_matches_v0():
    """Compare a real component move through V0 and Domain Center history."""
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"][0]
    payload.update({"pin_weights": (), "pin_present": False})
    snapshot = ir.make_mc2_mesh_partition_static_snapshot(**payload)
    fragment = fragment_module.build_mc2_mesh_static_fragment(snapshot)
    task_parameters = parameters.make_mc2_task_parameters(
        world_inertia=0.25,
        movement_inertia_smoothing=0.0,
        movement_speed_limit=-1.0,
        rotation_speed_limit=-1.0,
        teleport_mode=0,
    )
    effective = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(
            gravity=0.0,
            damping=0.0,
            collision_friction=0.0,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            self_collision_mode=0,
        ),
        parameters.make_mc2_setup_options("mesh_cloth"),
        task_parameters,
    )
    compiled = compiler.compile_mc2_mesh_static_fragment(fragment, effective)
    program = compiled.program
    v0 = native_context.MC2NativeContextV0(program.particle_count)
    domain = cpu_backend.create_mc2_cpu_backend_domain(
        compiled,
        native_kernel.MC2NativeCPUKernelV1(),
    )
    center_state = center_module.MC2CenterPersistentState(
        fragment.center.center_static_signature
    )
    try:
        _register_v0_static(v0, snapshot, fragment)
        v0.update_parameters(effective)
        base_positions = program.particle_bind_position.copy()
        base_rotations = program.particle_bind_rotation
        frame_one_pose = _center_frame_pose(1, 1, (0.0, 0.0, 0.0))
        frame_one = _frame_at(
            program,
            frame=1,
            generation=1,
            positions=base_positions,
        )
        v0.update_dynamic(frame_state.make_mc2_frame_input(
            task_id=snapshot.partition_id,
            topology_signature=fragment.final_proxy.proxy_signature,
            frame=1,
            generation=1,
            world_positions=base_positions,
            world_rotations_xyzw=base_rotations,
            center_frame_pose=frame_one_pose,
        ))
        v0.reset()
        center_pose_one = v0.derived_center_pose()
        center_state.reset(
            frame_one_pose,
            center_pose_one.position,
            center_pose_one.rotation_xyzw,
            velocity_weight=1.0,
        )
        v0.update_center_dynamic(center_state.make_step_input(
            frame_one_pose,
            center_pose_one,
            simulation_delta_time=0.1,
            frame_interpolation=1.0,
        ))
        v0.step_no_collision(0.1)
        domain.update_frame(frame_one)
        prefix_settings = {
            "anchor_component_local_positions": np.zeros((1, 3), dtype=np.float32),
            "dt": 0.1,
            "frame_interpolation": 1.0,
            "distance_weights": np.ones(1, dtype=np.float32),
            "simulation_power": 1.0,
            "velocity_weight": 1.0,
            "gravity": (0.0, 0.0, 0.0),
        }
        domain.step_reference_slices(prefix_settings)
        domain.step_post(_post_step_settings(effective, base_positions))
        np.testing.assert_allclose(
            domain.read_output().world_positions,
            np.asarray(v0.read()[0], dtype=np.float32),
            rtol=4.0e-5,
            atol=4.0e-5,
        )
        center_state.commit_step(
            frame_one_pose,
            center_pose_one,
            v0.read_center_step(),
        )

        moved_positions = base_positions + np.asarray((1.0, 0.0, 0.0), dtype=np.float32)
        frame_two_pose = _center_frame_pose(2, 1, (1.0, 0.0, 0.0))
        frame_two = _frame_at(
            program,
            frame=2,
            generation=1,
            positions=moved_positions,
            partition_world_position=((1.0, 0.0, 0.0),),
        )
        v0.update_dynamic(frame_state.make_mc2_frame_input(
            task_id=snapshot.partition_id,
            topology_signature=fragment.final_proxy.proxy_signature,
            frame=2,
            generation=1,
            world_positions=moved_positions,
            world_rotations_xyzw=base_rotations,
            center_frame_pose=frame_two_pose,
        ))
        center_pose_two = v0.derived_center_pose()
        shift = center_module.evaluate_mc2_center_frame_shift(
            center_state.make_frame_shift_input(
                frame_two_pose,
                center_pose=center_pose_two,
                simulation_delta_time=0.1,
                frame_delta_time=0.1,
                world_inertia=0.25,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
                movement_inertia_smoothing=0.0,
                is_running=True,
            )
        )
        v0.apply_center_frame_shift(center_state.old_frame_world_position, shift)
        v0_after_shift = np.asarray(v0.read()[0], dtype=np.float32).copy()
        v0.update_center_dynamic(center_state.make_step_input(
            frame_two_pose,
            center_pose_two,
            simulation_delta_time=0.1,
            frame_interpolation=1.0,
            frame_shift=shift,
        ))
        v0.step_no_collision(0.1)

        domain.update_frame(frame_two)
        domain.step_center_frame_shift(np.zeros((1, 3), dtype=np.float32))
        kernel_state = domain.inspect()["kernel"]
        np.testing.assert_allclose(
            kernel_state["center_shift_vectors"],
            (shift.frame_component_shift_vector,),
            rtol=2.0e-5,
            atol=2.0e-5,
        )
        np.testing.assert_allclose(
            domain.read_output().world_positions,
            v0_after_shift,
            rtol=2.0e-5,
            atol=2.0e-5,
        )
    finally:
        domain.dispose()
        v0.dispose()


def test_e3_native_mesh_point_collision_matches_v0():
    snapshot, fragment, _compiled, _effective = _same_source_constraints()
    effective = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(
            gravity=0.0,
            damping=0.0,
            collision_mode=1,
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
    compiled = compiler.compile_mc2_mesh_static_fragment(fragment, effective)
    program = compiled.program
    v0 = native_context.MC2NativeContextV0(program.particle_count)
    domain = cpu_backend.create_mc2_cpu_backend_domain(
        compiled,
        native_kernel.MC2NativeCPUKernelV1(),
    )
    center = np.asarray(((0.0, -1.0, 0.0),), dtype=np.float32)
    collider_types = np.asarray((0,), dtype=np.int32)
    collider_groups = np.asarray((1,), dtype=np.int32)
    collider_radii = np.asarray((0.5,), dtype=np.float32)
    collider = collider_frame.MC2ColliderFrameSpec(
        1,
        1,
        0,
        ("sphere",),
        collider_types,
        collider_groups,
        center,
        center,
        center,
        center,
        center,
        center,
        collider_radii,
        "e3-point-sphere",
    )
    try:
        _register_v0_static(v0, snapshot, fragment)
        v0.update_parameters(effective)
        v0.update_colliders(collider)
        base_positions = program.particle_bind_position.copy()
        base_rotations = program.particle_bind_rotation
        frame = _frame_at(
            program,
            frame=1,
            generation=1,
            positions=base_positions,
        )
        v0.update_dynamic(frame_state.make_mc2_frame_input(
            task_id=snapshot.partition_id,
            topology_signature=fragment.final_proxy.proxy_signature,
            frame=1,
            generation=1,
            world_positions=base_positions,
            world_rotations_xyzw=base_rotations,
        ))
        v0.reset()
        domain.update_frame(frame)
        v0.step_no_collision(0.1)
        v0_debug = v0.refresh_debug_draw_snapshot(include_dynamics=True)
        particle_fields = {
            name: index
            for index, name in enumerate(compiled.parameters.particle_parameters.fields)
        }
        particle_values = compiled.parameters.particle_parameters.values
        collision_radii_values = (
            particle_values[:, particle_fields["radius"]]
            * particle_values[:, particle_fields["radius_multiplier"]]
        )
        domain.step_reference_pipeline_full(_full_reference_settings(
            program,
            base_positions,
            base_rotations,
            point_collision={
            # Mesh point collision has no soft-sphere base pose. BoneSpring is
            # the only setup that supplies animated base positions here.
                "base_positions": np.zeros_like(base_positions),
                "collision_radii": collision_radii_values,
                "friction": particle_values[:, particle_fields["collision_friction"]],
                "collided_by_groups": 1,
                "collider_types": collider_types,
                "collider_group_bits": collider_groups,
                "collider_centers": center,
                "collider_segment_a": center,
                "collider_segment_b": center,
                "collider_old_centers": center,
                "collider_old_segment_a": center,
                "collider_old_segment_b": center,
                "collider_radii": collider_radii,
            },
            post_step=_post_step_settings(effective, base_positions),
            collision_mode=1,
            self_collision_enabled=False,
        ))
        v0_positions = np.asarray(v0.read()[0], dtype=np.float32)
        domain_positions = domain.read_output().world_positions
        domain_real_velocities = domain.read_debug_state()["real_velocities"]
        assert v0_positions[2, 1] < -1.1
        np.testing.assert_allclose(
            domain_positions,
            v0_positions,
            rtol=4.0e-5,
            atol=4.0e-5,
        )
        np.testing.assert_allclose(
            domain_real_velocities,
            np.asarray(v0_debug["dynamics"]["real_velocities"], dtype=np.float32),
            rtol=4.0e-5,
            atol=4.0e-5,
        )
    finally:
        domain.dispose()
        v0.dispose()


def test_e3_native_mesh_edge_collision_matches_v0():
    snapshot, fragment, _compiled, _effective = _same_source_constraints()
    effective = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(
            gravity=0.0,
            damping=0.0,
            collision_mode=2,
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
    compiled = compiler.compile_mc2_mesh_static_fragment(fragment, effective)
    program = compiled.program
    v0 = native_context.MC2NativeContextV0(program.particle_count)
    domain = cpu_backend.create_mc2_cpu_backend_domain(
        compiled,
        native_kernel.MC2NativeCPUKernelV1(),
    )
    center = np.asarray(((0.0, -0.5, 0.0),), dtype=np.float32)
    collider_types = np.asarray((0,), dtype=np.int32)
    collider_groups = np.asarray((1,), dtype=np.int32)
    collider_radii = np.asarray((0.5,), dtype=np.float32)
    collider = collider_frame.MC2ColliderFrameSpec(
        1,
        1,
        0,
        ("sphere",),
        collider_types,
        collider_groups,
        center,
        center,
        center,
        center,
        center,
        center,
        collider_radii,
        "e3-edge-sphere",
    )
    try:
        _register_v0_static(v0, snapshot, fragment)
        v0.update_parameters(effective)
        v0.update_colliders(collider)
        base_positions = program.particle_bind_position.copy()
        base_rotations = program.particle_bind_rotation
        frame = _frame_at(
            program,
            frame=1,
            generation=1,
            positions=base_positions,
        )
        v0.update_dynamic(frame_state.make_mc2_frame_input(
            task_id=snapshot.partition_id,
            topology_signature=fragment.final_proxy.proxy_signature,
            frame=1,
            generation=1,
            world_positions=base_positions,
            world_rotations_xyzw=base_rotations,
        ))
        v0.reset()
        domain.update_frame(frame)
        v0.step_no_collision(0.1)
        v0_debug = v0.refresh_debug_draw_snapshot(include_dynamics=True)
        edge_table = next(table for table in program.primitive_tables if table.kind == "edge")
        edges = np.asarray(edge_table.indices, dtype=np.int32)
        particle_fields = {
            name: index
            for index, name in enumerate(compiled.parameters.particle_parameters.fields)
        }
        particle_values = compiled.parameters.particle_parameters.values
        domain.step_reference_pipeline_full(_full_reference_settings(
            program,
            base_positions,
            base_rotations,
            edge_collision={
                "collision_radii": (
                particle_values[:, particle_fields["radius"]]
                * particle_values[:, particle_fields["radius_multiplier"]]
                ),
                "edges": edges,
                "friction": particle_values[:, particle_fields["collision_friction"]],
                "collided_by_groups": 1,
                "collider_types": collider_types,
                "collider_group_bits": collider_groups,
                "collider_centers": center,
                "collider_segment_a": center,
                "collider_segment_b": center,
                "collider_old_centers": center,
                "collider_old_segment_a": center,
                "collider_old_segment_b": center,
                "collider_radii": collider_radii,
            },
            post_step=_post_step_settings(effective, base_positions),
            collision_mode=2,
            self_collision_enabled=False,
        ))
        v0_positions = np.asarray(v0.read()[0], dtype=np.float32)
        domain_positions = domain.read_output().world_positions
        domain_real_velocities = domain.read_debug_state()["real_velocities"]
        assert np.any(np.abs(v0_positions - base_positions) > 1.0e-4)
        np.testing.assert_allclose(
            domain_positions,
            v0_positions,
            # V0 quantizes persistent self-contact parameters to half precision;
            # the shared native Domain kernel keeps the same ordered solve in float32.
            rtol=1.0e-4,
            atol=1.0e-4,
        )
        np.testing.assert_allclose(
            domain_real_velocities,
            np.asarray(v0_debug["dynamics"]["real_velocities"], dtype=np.float32),
            rtol=1.0e-4,
            atol=1.0e-4,
        )
    finally:
        domain.dispose()
        v0.dispose()


def test_e3_native_mesh_self_collision_matches_v0():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"][0]
    payload.update({
        "local_positions": (
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
            (0.1, 0.1, 0.0), (1.1, 0.1, 0.0), (0.1, 1.1, 0.0),
        ),
        "local_normals": ((0.0, 0.0, 1.0),) * 6,
        "edges": ((0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3)),
        "triangles": ((0, 1, 2), (3, 4, 5)),
        "triangle_loops": ((0, 1, 2), (3, 4, 5)),
        "loop_vertices": (0, 1, 2, 3, 4, 5),
        "loop_uvs": ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)) * 2,
        "pin_weights": (1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        "source_element_ids": (0, 1, 2, 3, 4, 5),
        "radius_multipliers": (1.0,) * 6,
    })
    snapshot = ir.make_mc2_mesh_partition_static_snapshot(**payload)
    fragment = fragment_module.build_mc2_mesh_static_fragment(snapshot)
    effective = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(
            gravity=0.0,
            damping=0.0,
            radius=0.05,
            collision_friction=0.0,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            self_collision_mode=2,
            self_collision_thickness=0.02,
        ),
        parameters.make_mc2_setup_options("mesh_cloth"),
        parameters.make_mc2_task_parameters(),
    )
    compiled = compiler.compile_mc2_mesh_static_fragment(fragment, effective)
    program = compiled.program
    v0 = native_context.MC2NativeContextV0(program.particle_count)
    domain = cpu_backend.create_mc2_cpu_backend_domain(
        compiled,
        native_kernel.MC2NativeCPUKernelV1(),
    )
    try:
        _register_v0_static(v0, snapshot, fragment)
        v0.update_parameters(effective)
        base_positions = program.particle_bind_position.copy()
        base_rotations = program.particle_bind_rotation
        frame = _frame_at(
            program,
            frame=1,
            generation=1,
            positions=base_positions,
        )
        v0.update_dynamic(frame_state.make_mc2_frame_input(
            task_id=snapshot.partition_id,
            topology_signature=fragment.final_proxy.proxy_signature,
            frame=1,
            generation=1,
            world_positions=base_positions,
            world_rotations_xyzw=base_rotations,
        ))
        v0.reset()
        domain.update_frame(frame)
        v0.step_no_collision(0.1)
        v0_debug = v0.refresh_debug_draw_snapshot(include_dynamics=True)
        edge_table = next(table for table in program.primitive_tables if table.kind == "edge")
        triangle_table = next(
            table for table in program.primitive_tables if table.kind == "triangle"
        )
        settings = {
            "anchor_component_local_positions": np.zeros((1, 3), dtype=np.float32),
            "dt": 0.1,
            "frame_interpolation": 1.0,
            "distance_weights": np.ones(1, dtype=np.float32),
            "simulation_power": 1.0,
            "distance_simulation_power": 1.0,
            "bending_simulation_power": 1.0,
            "velocity_weight": 1.0,
            "gravity": (0.0, 0.0, 0.0),
            "step_basic_positions": base_positions,
            "tether_compression": 0.4,
            "tether_stretch": 0.03,
            "step_basic_rotations": base_rotations,
            "angle_restoration_values": np.zeros(program.particle_count, dtype=np.float32),
            "angle_limit_values": np.zeros(program.particle_count, dtype=np.float32),
            "angle_restoration_velocity_attenuation": 0.0,
            "angle_restoration_gravity_falloff": 0.0,
            "angle_limit_stiffness": 0.0,
            "angle_restoration_enabled": False,
            "angle_limit_enabled": False,
            "motion_base_positions": base_positions,
            "motion_base_rotations": base_rotations,
            "motion_max_distances": np.zeros(program.particle_count, dtype=np.float32),
            "motion_stiffness_values": np.ones(program.particle_count, dtype=np.float32),
            "motion_backstop_radii": np.zeros(program.particle_count, dtype=np.float32),
            "motion_backstop_distances": np.zeros(program.particle_count, dtype=np.float32),
            "motion_normal_axis": 1,
            "motion_max_distance_enabled": False,
            "motion_backstop_enabled": False,
            "point_collision": None,
            "edge_collision": None,
            "self_collision": {
                # V0 sums the two primitive-side thickness values before solving.
                "old_positions": base_positions,
                "edges": np.asarray(edge_table.indices, dtype=np.int32),
                "triangles": np.asarray(triangle_table.indices, dtype=np.int32),
                "friction": np.zeros(program.particle_count, dtype=np.float32),
                "surface_thickness": 0.04,
            },
            "post_step": _post_step_settings(effective, base_positions),
            "collision_mode": 0,
            "self_collision_enabled": True,
        }
        domain.step_reference_pipeline_full(settings)
        v0_positions = np.asarray(v0.read()[0], dtype=np.float32)
        domain_positions = domain.read_output().world_positions
        domain_real_velocities = domain.read_debug_state()["real_velocities"]
        assert np.any(np.abs(v0_positions - base_positions) > 1.0e-4)
        np.testing.assert_allclose(
            domain_positions,
            v0_positions,
            # V0 quantizes persistent self-contact parameters to half precision;
            # the shared native Domain kernel keeps the same ordered solve in float32.
            rtol=1.0e-4,
            atol=1.0e-4,
        )
        np.testing.assert_allclose(
            domain_real_velocities,
            np.asarray(v0_debug["dynamics"]["real_velocities"], dtype=np.float32),
            # The self-position quantization delta is divided by dt in post.
            rtol=3.0e-3,
            atol=1.0e-3,
        )
    finally:
        domain.dispose()
        v0.dispose()


if __name__ == "__main__":
    test_e3_prediction_matches_same_source_v0_and_domain()
    print("PASS E3 same-source V0/Domain prediction tolerance")
    test_e3_full_reference_without_collisions_matches_same_source_v0_and_domain()
    print("PASS E3 same-source V0/Domain full no-collision tolerance")
    test_e3_full_reference_post_history_matches_same_source_v0()
    print("PASS E3 same-source V0/Domain post velocity history tolerance")
    test_e3_native_step_basic_pose_matches_v0_angle_reference()
    print("PASS E3 native StepBasic pose matches V0 Angle reference")
    test_e3_native_motion_branch_matches_v0_after_tether()
    print("PASS E3 native Tether-to-Motion branch matches V0")
    test_e3_native_full_angle_motion_pipeline_matches_v0()
    print("PASS E3 native full Angle Limit + Motion/Backstop pipeline matches V0")
    test_e3_center_frame_shift_two_frame_transaction_matches_v0()
    print("PASS E3 Center frame-shift two-frame transaction matches V0")
    test_e3_native_mesh_point_collision_matches_v0()
    print("PASS E3 native Mesh point collision matches V0")
    test_e3_native_mesh_edge_collision_matches_v0()
    print("PASS E3 native Mesh edge collision matches V0")
    test_e3_native_mesh_self_collision_matches_v0()
    print("PASS E3 native Mesh self collision matches V0")
