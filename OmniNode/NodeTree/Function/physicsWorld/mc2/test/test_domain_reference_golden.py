"""删除V0 owner后仍长期保留的DomainV1基础数值合同。"""

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

ir = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_ir"
)
compiler = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_compile"
)
fragment_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.static_fragment"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
runtime = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters"
)
cpu_backend = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.cpu_backend"
)
native_kernel = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.cpu_native_kernel"
)
scheduler = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.scheduler"
)
reference_step = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.reference_step"
)

FIXTURE_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "domain_pipeline",
)
STATIC_FIXTURE = os.path.join(
    FIXTURE_ROOT,
    "two_mesh_static",
    "two_mesh_domain_v1.json",
)
GOLDEN_FIXTURE = os.path.join(
    FIXTURE_ROOT,
    "backend_reference",
    "e3_v0_golden_v1.json",
)


def _source():
    with open(STATIC_FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"][0]
    return ir.make_mc2_mesh_partition_static_snapshot(**payload)


def _compiled_domain(profile=None, task_parameters=None):
    snapshot = _source()
    if profile is None:
        profile = parameters.make_mc2_particle_profile(
            gravity=1.0,
            gravity_direction=(0.0, -1.0, 0.0),
            collision_friction=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            self_collision_mode=0,
        )
    return _domain_from_snapshot(snapshot, profile, task_parameters)


def _domain_from_snapshot(snapshot, profile, task_parameters=None):
    fragment = fragment_module.build_mc2_mesh_static_fragment(snapshot)
    effective = runtime.make_mc2_runtime_parameters(
        profile,
        parameters.make_mc2_setup_options("mesh_cloth"),
        (
            parameters.make_mc2_task_parameters()
            if task_parameters is None
            else task_parameters
        ),
    )
    compiled = compiler.compile_mc2_static_fragments(
        (fragment,), (effective,)
    )
    domain = cpu_backend.create_mc2_cpu_backend_domain(
        compiled,
        native_kernel.MC2NativeCPUKernelV1(),
    )
    return compiled, effective, domain


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
    skip_count=0,
    is_running=True,
):
    return ir.make_mc2_domain_frame_packet(
        program,
        frame=frame,
        generation=generation,
        animated_base_world_positions=positions,
        animated_base_world_rotations=program.particle_bind_rotation,
        animated_base_world_normals=np.asarray(
            ((0.0, 0.0, 1.0),) * program.particle_count,
            dtype=np.float32,
        ),
        partition_world_position=partition_world_position,
        partition_world_rotation=((0.0, 0.0, 0.0, 1.0),),
        partition_world_scale=((1.0, 1.0, 1.0),),
        partition_world_linear=(
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        ),
        frame_delta_time=frame_delta_time,
        simulation_delta_time=simulation_delta_time,
        time_scale=time_scale,
        skip_count=skip_count,
        is_running=is_running,
        partition_frame_flags=(0,),
    )


def _frame(program):
    return _frame_at(
        program,
        frame=6,
        generation=2,
        positions=program.particle_bind_position,
    )


def _golden(case_name):
    with open(GOLDEN_FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["schema"] == "mc2_e3_domain_golden_v1"
    return payload["cases"][case_name]


def _full_reference_settings(
    program,
    positions,
    rotations,
    *,
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
        "motion_base_positions": positions,
        "motion_base_rotations": rotations,
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


def _assert_golden(actual, case, field):
    field_payload = case[field]
    if isinstance(field_payload, dict):
        expected = np.asarray(field_payload["values"], dtype=np.float32)
        rtol = float(field_payload["rtol"])
        atol = float(field_payload["atol"])
    else:
        expected = np.asarray(field_payload, dtype=np.float32)
        rtol = float(case["rtol"])
        atol = float(case["atol"])
    assert actual.dtype == np.float32
    assert actual.shape == expected.shape
    assert np.isfinite(actual).all()
    np.testing.assert_allclose(
        actual,
        expected,
        rtol=rtol,
        atol=atol,
    )


def test_domain_prediction_matches_frozen_e3_reference():
    compiled, _effective, domain = _compiled_domain()
    try:
        domain.update_frame(_frame(compiled.program))
        powers = scheduler.derive_mc2_simulation_powers(0.1)
        domain.step_integration(
            {
                "dt": 0.1,
                "simulation_power": powers.integration,
                "velocity_weight": 1.0,
                "gravity": (0.0, -1.0, 0.0),
            }
        )
        _assert_golden(
            domain.read_output().world_positions,
            _golden("prediction"),
            "world_positions",
        )
    finally:
        domain.dispose()


def test_domain_full_reference_matches_frozen_e3_no_collision_reference():
    compiled, _effective, domain = _compiled_domain()
    try:
        frame = _frame(compiled.program)
        domain.update_frame(frame)
        before = domain.read_output().world_positions.copy()
        powers = scheduler.derive_mc2_simulation_powers(0.1)
        settings = _full_reference_settings(
            compiled.program,
            before,
            frame.animated_base_world_rotations,
        )
        settings.update(
            {
                "simulation_power": powers.integration,
                "distance_simulation_power": powers.distance_bending,
                "bending_simulation_power": powers.distance_bending,
                "gravity": (0.0, -1.0, 0.0),
            }
        )
        domain.step_reference_pipeline_full(settings)
        _assert_golden(
            domain.read_output().world_positions,
            _golden("full_no_collision"),
            "world_positions",
        )
    finally:
        domain.dispose()


def test_domain_post_history_matches_frozen_e3_reference():
    compiled, effective, domain = _compiled_domain()
    try:
        frame = _frame(compiled.program)
        domain.update_frame(frame)
        before = domain.read_output().world_positions.copy()
        powers = scheduler.derive_mc2_simulation_powers(0.1)
        floats = effective.debug_dict()["float_values"]
        settings = _full_reference_settings(
            compiled.program,
            before,
            frame.animated_base_world_rotations,
            post_step={
                "old_positions": before,
                "dt": 0.1,
                "dynamic_friction": 0.0,
                "static_friction_speed": 0.0,
                "particle_speed_limit": floats["particle_speed_limit"],
                "velocity_weight": 1.0,
            },
        )
        settings.update(
            {
                "simulation_power": powers.integration,
                "distance_simulation_power": powers.distance_bending,
                "bending_simulation_power": powers.distance_bending,
                "gravity": (0.0, -1.0, 0.0),
            }
        )
        domain.step_reference_pipeline_full(settings)
        case = _golden("post_history")
        _assert_golden(
            domain.read_output().world_positions,
            case,
            "world_positions",
        )
        _assert_golden(
            domain.read_debug_state()["real_velocities"],
            case,
            "real_velocities",
        )
    finally:
        domain.dispose()


def test_domain_step_basic_and_angle_match_frozen_e3_reference():
    compiled, _effective, domain = _compiled_domain()
    try:
        frame = _frame(compiled.program)
        domain.update_frame(frame)
        pose = domain.prepare_step_basic_pose(0.0)
        case = _golden("step_basic_angle")
        _assert_golden(
            np.asarray(pose["positions"], dtype=np.float32),
            case,
            "step_basic_positions",
        )
        _assert_golden(
            np.asarray(pose["rotations"], dtype=np.float32),
            case,
            "step_basic_rotations_xyzw",
        )
        powers = scheduler.derive_mc2_simulation_powers(0.1)
        domain.step_integration(
            {
                "dt": 0.1,
                "simulation_power": powers.integration,
                "velocity_weight": 1.0,
                "gravity": (0.0, -1.0, 0.0),
            }
        )
        domain.step_angle(
            {
                "step_basic_positions": pose["positions"],
                "step_basic_rotations": pose["rotations"],
                "restoration_values": np.full(
                    compiled.program.particle_count,
                    np.float32(0.2 * (9.0 ** 1.8)),
                    dtype=np.float32,
                ),
                "limit_values": np.zeros(
                    compiled.program.particle_count,
                    dtype=np.float32,
                ),
                "restoration_velocity_attenuation": 0.0,
                "restoration_gravity_falloff": 0.0,
                "limit_stiffness": 0.0,
                "restoration_enabled": True,
                "limit_enabled": False,
            }
        )
        _assert_golden(
            domain.read_output().world_positions,
            case,
            "world_positions",
        )
    finally:
        domain.dispose()


def test_domain_tether_motion_matches_frozen_e3_reference():
    profile = parameters.make_mc2_particle_profile(
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
    )
    compiled, _effective, domain = _compiled_domain(profile)
    program = compiled.program
    try:
        base_positions = program.particle_bind_position.copy()
        base_rotations = program.particle_bind_rotation
        domain.update_frame(
            _frame_at(
                program,
                frame=1,
                generation=1,
                positions=base_positions,
            )
        )
        domain.step_integration(
            {
                "dt": 0.1,
                "simulation_power": 1.0,
                "velocity_weight": 1.0,
                "gravity": (0.0, 0.0, 0.0),
            }
        )
        moved_base = base_positions + np.asarray(
            (1.0, 0.0, 0.0),
            dtype=np.float32,
        )
        domain.update_frame(
            _frame_at(
                program,
                frame=2,
                generation=1,
                positions=moved_base,
            )
        )
        step_basic = domain.prepare_step_basic_pose(0.0)
        domain.step_integration(
            {
                "dt": 0.1,
                "simulation_power": 1.0,
                "velocity_weight": 1.0,
                "gravity": (0.0, 0.0, 0.0),
            }
        )
        partition_fields = {
            name: index
            for index, name in enumerate(
                compiled.parameters.partition_parameters.fields
            )
        }
        particle_fields = {
            name: index
            for index, name in enumerate(
                compiled.parameters.particle_parameters.fields
            )
        }
        uint_fields = {
            name: index
            for index, name in enumerate(
                compiled.parameters.partition_uint_parameters.fields
            )
        }
        partition_values = compiled.parameters.partition_parameters.values[0]
        particle_values = compiled.parameters.particle_parameters.values
        domain.step_tether(
            {
                "step_basic_positions": step_basic["positions"],
                "compression": float(
                    partition_values[
                        partition_fields["tether_compression_limit"]
                    ]
                ),
                "stretch": float(
                    partition_values[partition_fields["tether_stretch_limit"]]
                ),
            }
        )
        domain.step_motion(
            {
                "base_positions": moved_base,
                "base_rotations": base_rotations,
                "max_distances": particle_values[
                    :, particle_fields["max_distance"]
                ],
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
                "backstop_distances": particle_values[
                    :, particle_fields["backstop_distance"]
                ],
                "normal_axis": int(
                    compiled.parameters.partition_uint_parameters.values[
                        0, uint_fields["normal_axis"]
                    ]
                ),
                "max_distance_enabled": True,
                "backstop_enabled": False,
            }
        )
        _assert_golden(
            domain.read_output().world_positions,
            _golden("tether_motion"),
            "world_positions",
        )
    finally:
        domain.dispose()


def test_domain_full_angle_motion_matches_frozen_e3_reference():
    profile = parameters.make_mc2_particle_profile(
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
    )
    compiled, _effective, domain = _compiled_domain(profile)
    program = compiled.program
    try:
        base_positions = program.particle_bind_position.copy()
        frame = _frame_at(
            program,
            frame=1,
            generation=1,
            positions=base_positions,
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
        case = _golden("full_angle_motion")
        _assert_golden(
            domain.read_output().world_positions,
            case,
            "world_positions",
        )
        _assert_golden(
            domain.read_debug_state()["real_velocities"],
            case,
            "real_velocities",
        )
    finally:
        domain.dispose()


def _run_center_transaction(
    case_name,
    *,
    teleport_mode=0,
    frame_delta_time=0.1,
    simulation_delta_time=0.1,
    time_scale=1.0,
    skip_count=0,
    is_running=True,
):
    profile = parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.0,
        collision_friction=0.0,
        distance_stiffness=0.5,
        bending_stiffness=0.0,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        self_collision_mode=0,
    )
    task_parameters = parameters.make_mc2_task_parameters(
        world_inertia=0.25,
        depth_inertia=1.0,
        movement_inertia_smoothing=0.0,
        movement_speed_limit=-1.0,
        rotation_speed_limit=-1.0,
        teleport_mode=teleport_mode,
        teleport_distance=0.5,
        teleport_rotation=90.0,
    )
    compiled, effective, domain = _compiled_domain(profile, task_parameters)
    program = compiled.program
    partition_fields = {
        name: index
        for index, name in enumerate(
            compiled.parameters.partition_parameters.fields
        )
    }
    partition_values = compiled.parameters.partition_parameters.values[0]
    tether_compression = float(
        partition_values[partition_fields["tether_compression_limit"]]
    )
    tether_stretch = float(
        partition_values[partition_fields["tether_stretch_limit"]]
    )
    try:
        base_positions = program.particle_bind_position.copy()
        frame_one = _frame_at(
            program,
            frame=1,
            generation=1,
            positions=base_positions,
        )
        domain.update_frame(frame_one)
        frame_one_powers = scheduler.derive_mc2_simulation_powers(0.1)
        domain.step_reference_pass_prefix(
            {
                "anchor_component_local_positions": np.zeros(
                    (1, 3),
                    dtype=np.float32,
                ),
                "dt": 0.1,
                "frame_interpolation": 1.0,
                "distance_weights": np.ones(1, dtype=np.float32),
                "simulation_power": frame_one_powers.integration,
                "velocity_weight": 1.0,
                "gravity": (0.0, 0.0, 0.0),
                "step_basic_positions": base_positions,
                "tether_compression": tether_compression,
                "tether_stretch": tether_stretch,
            }
        )
        domain.step_distance(frame_one_powers.distance_bending)
        domain.step_post(
            {
                "old_positions": base_positions,
                "dt": 0.1,
                "dynamic_friction": 0.0,
                "static_friction_speed": 0.0,
                "particle_speed_limit": effective.debug_dict()["float_values"][
                    "particle_speed_limit"
                ],
                "velocity_weight": 1.0,
            }
        )
        _assert_golden(
            domain.read_output().world_positions,
            _golden("center_frame_one"),
            "world_positions",
        )

        moved_positions = base_positions + np.asarray(
            (1.0, 0.0, 0.0),
            dtype=np.float32,
        )
        frame_two = _frame_at(
            program,
            frame=2,
            generation=1,
            positions=moved_positions,
            partition_world_position=((1.0, 0.0, 0.0),),
            frame_delta_time=frame_delta_time,
            simulation_delta_time=simulation_delta_time,
            time_scale=time_scale,
            skip_count=skip_count,
            is_running=is_running,
        )
        domain.update_frame(frame_two)
        domain.step_center_frame_shift(np.zeros((1, 3), dtype=np.float32))
        case = _golden(case_name)
        kernel_state = domain.inspect()["kernel"]
        assert (
            int(kernel_state["center_shift_teleport_flags"][0])
            == int(case["teleport_flags"])
        )
        _assert_golden(
            kernel_state["center_shift_vectors"],
            case,
            "shift_vector",
        )
        _assert_golden(
            domain.read_output().world_positions,
            case,
            "after_shift",
        )
        if simulation_delta_time <= 0.0:
            return

        domain.step_center(
            {
                "dt": simulation_delta_time,
                "frame_interpolation": 1.0,
                "distance_weights": np.ones(1, dtype=np.float32),
            }
        )
        domain.step_center_inertia()
        powers = scheduler.derive_mc2_simulation_powers(simulation_delta_time)
        domain.step_integration(
            {
                "dt": simulation_delta_time,
                "simulation_power": powers.integration,
                "velocity_weight": 1.0,
                "gravity": (0.0, 0.0, 0.0),
            }
        )
        after_integration = domain.read_output().world_positions.copy()
        domain.step_tether(
            {
                "step_basic_positions": moved_positions,
                "compression": tether_compression,
                "stretch": tether_stretch,
            }
        )
        domain.step_distance(powers.distance_bending)
        domain.step_distance(powers.distance_bending)
        if teleport_mode == 0 and is_running:
            assert np.any(
                np.abs(
                    domain.read_output().world_positions - after_integration
                )
                > 1.0e-5
            )
        old_positions = np.asarray(
            case["after_shift"]["values"],
            dtype=np.float32,
        )
        domain.step_post(
            {
                "old_positions": old_positions,
                "dt": simulation_delta_time,
                "dynamic_friction": 0.0,
                "static_friction_speed": 0.0,
                "particle_speed_limit": effective.debug_dict()["float_values"][
                    "particle_speed_limit"
                ],
                "velocity_weight": 1.0,
            }
        )
        if teleport_mode == 0 and is_running:
            assert np.any(
                np.abs(
                    domain.read_output().world_positions - old_positions
                )
                > 1.0e-5
            )
        _assert_golden(
            domain.read_output().world_positions,
            case,
            "world_positions",
        )
        _assert_golden(
            domain.read_debug_state()["real_velocities"],
            case,
            "real_velocities",
        )
    finally:
        domain.dispose()


def test_domain_center_transactions_match_frozen_e3_reference():
    cases = (
        ("center_default", {}),
        ("center_keep", {"teleport_mode": 2}),
        ("center_reset", {"teleport_mode": 1}),
        (
            "center_paused",
            {"is_running": False, "simulation_delta_time": 0.0},
        ),
        (
            "center_catchup",
            {
                "frame_delta_time": 0.3,
                "simulation_delta_time": 0.1,
                "skip_count": 2,
            },
        ),
    )
    for case_name, kwargs in cases:
        _run_center_transaction(case_name, **kwargs)


def _post_step_settings(effective, old_positions):
    floats = effective.debug_dict()["float_values"]
    return {
        "old_positions": old_positions,
        "dt": 0.1,
        "dynamic_friction": floats["collision_dynamic_friction"],
        "static_friction_speed": floats["collision_static_friction"],
        "particle_speed_limit": floats["particle_speed_limit"],
        "velocity_weight": 1.0,
    }


def _collision_parameters(compiled):
    fields = {
        name: index
        for index, name in enumerate(
            compiled.parameters.particle_parameters.fields
        )
    }
    values = compiled.parameters.particle_parameters.values
    return fields, values


def test_domain_point_collision_matches_frozen_e3_reference():
    profile = parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.0,
        collision_mode=1,
        collision_friction=0.0,
        distance_stiffness=0.0,
        bending_stiffness=0.0,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        self_collision_mode=0,
    )
    compiled, effective, domain = _compiled_domain(profile)
    program = compiled.program
    center = np.asarray(((0.0, -1.0, 0.0),), dtype=np.float32)
    collider_types = np.asarray((0,), dtype=np.int32)
    collider_groups = np.asarray((1,), dtype=np.int32)
    collider_radii = np.asarray((0.5,), dtype=np.float32)
    try:
        base_positions = program.particle_bind_position.copy()
        base_rotations = program.particle_bind_rotation
        domain.update_frame(
            _frame_at(
                program,
                frame=1,
                generation=1,
                positions=base_positions,
            )
        )
        fields, values = _collision_parameters(compiled)
        domain.step_reference_pipeline_full(
            _full_reference_settings(
                program,
                base_positions,
                base_rotations,
                point_collision={
                    "base_positions": np.zeros_like(base_positions),
                    "collision_radii": (
                        values[:, fields["radius"]]
                        * values[:, fields["radius_multiplier"]]
                    ),
                    "friction": values[:, fields["collision_friction"]],
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
            )
        )
        case = _golden("point_collision")
        assert domain.read_output().world_positions[2, 1] < -1.1
        _assert_golden(
            domain.read_output().world_positions,
            case,
            "world_positions",
        )
        _assert_golden(
            domain.read_debug_state()["real_velocities"],
            case,
            "real_velocities",
        )
    finally:
        domain.dispose()


def test_domain_edge_collision_matches_frozen_e3_reference():
    profile = parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.0,
        collision_mode=2,
        collision_friction=0.0,
        distance_stiffness=0.0,
        bending_stiffness=0.0,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        self_collision_mode=0,
    )
    compiled, effective, domain = _compiled_domain(profile)
    program = compiled.program
    center = np.asarray(((0.0, -0.5, 0.0),), dtype=np.float32)
    collider_types = np.asarray((0,), dtype=np.int32)
    collider_groups = np.asarray((1,), dtype=np.int32)
    collider_radii = np.asarray((0.5,), dtype=np.float32)
    try:
        base_positions = program.particle_bind_position.copy()
        base_rotations = program.particle_bind_rotation
        domain.update_frame(
            _frame_at(
                program,
                frame=1,
                generation=1,
                positions=base_positions,
            )
        )
        edge_table = next(
            table for table in program.primitive_tables if table.kind == "edge"
        )
        fields, values = _collision_parameters(compiled)
        domain.step_reference_pipeline_full(
            _full_reference_settings(
                program,
                base_positions,
                base_rotations,
                edge_collision={
                    "collision_radii": (
                        values[:, fields["radius"]]
                        * values[:, fields["radius_multiplier"]]
                    ),
                    "edges": np.asarray(edge_table.indices, dtype=np.int32),
                    "friction": values[:, fields["collision_friction"]],
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
            )
        )
        case = _golden("edge_collision")
        assert np.any(
            np.abs(domain.read_output().world_positions - base_positions)
            > 1.0e-4
        )
        _assert_golden(
            domain.read_output().world_positions,
            case,
            "world_positions",
        )
        _assert_golden(
            domain.read_debug_state()["real_velocities"],
            case,
            "real_velocities",
        )
    finally:
        domain.dispose()


def test_domain_self_collision_matches_frozen_e3_reference():
    with open(STATIC_FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"][0]
    payload.update(
        {
            "local_positions": (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.1, 0.1, 0.0),
                (1.1, 0.1, 0.0),
                (0.1, 1.1, 0.0),
            ),
            "local_normals": ((0.0, 0.0, 1.0),) * 6,
            "edges": (
                (0, 1),
                (1, 2),
                (2, 0),
                (3, 4),
                (4, 5),
                (5, 3),
            ),
            "triangles": ((0, 1, 2), (3, 4, 5)),
            "triangle_loops": ((0, 1, 2), (3, 4, 5)),
            "loop_vertices": (0, 1, 2, 3, 4, 5),
            "loop_uvs": (
                (0.0, 0.0),
                (1.0, 0.0),
                (0.0, 1.0),
            )
            * 2,
            "pin_weights": (1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            "source_element_ids": (0, 1, 2, 3, 4, 5),
            "radius_multipliers": (1.0,) * 6,
        }
    )
    snapshot = ir.make_mc2_mesh_partition_static_snapshot(**payload)
    profile = parameters.make_mc2_particle_profile(
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
    )
    compiled, effective, domain = _domain_from_snapshot(snapshot, profile)
    program = compiled.program
    try:
        base_positions = program.particle_bind_position.copy()
        base_rotations = program.particle_bind_rotation
        domain.update_frame(
            _frame_at(
                program,
                frame=1,
                generation=1,
                positions=base_positions,
            )
        )
        edge_table = next(
            table for table in program.primitive_tables if table.kind == "edge"
        )
        triangle_table = next(
            table
            for table in program.primitive_tables
            if table.kind == "triangle"
        )
        domain.step_reference_pipeline_full(
            _full_reference_settings(
                program,
                base_positions,
                base_rotations,
                self_collision={
                    "old_positions": base_positions,
                    "edges": np.asarray(
                        edge_table.indices,
                        dtype=np.int32,
                    ),
                    "triangles": np.asarray(
                        triangle_table.indices,
                        dtype=np.int32,
                    ),
                    "friction": np.zeros(
                        program.particle_count,
                        dtype=np.float32,
                    ),
                    "surface_thickness": 0.04,
                },
                post_step=_post_step_settings(effective, base_positions),
                collision_mode=0,
                self_collision_enabled=True,
            )
        )
        case = _golden("self_collision")
        assert np.any(
            np.abs(domain.read_output().world_positions - base_positions)
            > 1.0e-4
        )
        _assert_golden(
            domain.read_output().world_positions,
            case,
            "world_positions",
        )
        _assert_golden(
            domain.read_debug_state()["real_velocities"],
            case,
            "real_velocities",
        )
    finally:
        domain.dispose()


if __name__ == "__main__":
    tests = tuple(
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"MC2 Domain E3 golden: {len(tests)} passed")
