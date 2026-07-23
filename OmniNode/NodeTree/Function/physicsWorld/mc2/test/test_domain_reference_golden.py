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


def _compiled_domain():
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
    compiled = compiler.compile_mc2_mesh_static_fragment(fragment, effective)
    domain = cpu_backend.create_mc2_cpu_backend_domain(
        compiled,
        native_kernel.MC2NativeCPUKernelV1(),
    )
    return compiled, effective, domain


def _frame(program):
    count = program.particle_count
    return ir.make_mc2_domain_frame_packet(
        program,
        frame=6,
        generation=2,
        animated_base_world_positions=program.particle_bind_position,
        animated_base_world_rotations=program.particle_bind_rotation,
        animated_base_world_normals=np.asarray(
            ((0.0, 0.0, 1.0),) * count,
            dtype=np.float32,
        ),
        partition_world_position=((0.0, 0.0, 0.0),),
        partition_world_rotation=((0.0, 0.0, 0.0, 1.0),),
        partition_world_scale=((1.0, 1.0, 1.0),),
        partition_world_linear=(
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        ),
        frame_delta_time=0.1,
        simulation_delta_time=0.1,
        time_scale=1.0,
        skip_count=0,
        is_running=True,
        partition_frame_flags=(0,),
    )


def _golden(case_name):
    with open(GOLDEN_FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["schema"] == "mc2_e3_domain_golden_v1"
    return payload["cases"][case_name]


def _full_reference_settings(program, positions, rotations, *, post_step=None):
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
        "point_collision": None,
        "edge_collision": None,
        "self_collision": None,
    }
    if post_step is not None:
        settings["post_step"] = post_step
    return settings


def _assert_golden(actual, case, field):
    expected = np.asarray(case[field], dtype=np.float32)
    assert actual.dtype == np.float32
    assert actual.shape == expected.shape
    assert np.isfinite(actual).all()
    np.testing.assert_allclose(
        actual,
        expected,
        rtol=float(case["rtol"]),
        atol=float(case["atol"]),
    )


def test_domain_prediction_matches_frozen_e3_reference():
    compiled, _effective, domain = _compiled_domain()
    try:
        domain.update_frame(_frame(compiled.program))
        powers = scheduler.derive_mc2_simulation_powers(0.1)
        domain.step(
            {
                "data_path_only": True,
                "integration_slice": True,
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
