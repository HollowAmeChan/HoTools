"""Tests for the pure scheduler/compiled-domain reference step compiler."""

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
    (
        "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups",
        os.path.join(MC2_ROOT, "setups"),
    ),
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
reference_step = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.reference_step"
)
scheduler = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.scheduler")

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "domain_pipeline",
    "two_mesh_static",
    "two_mesh_domain_v1.json",
)


def _compiled():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"][0]
    snapshot = ir.make_mc2_mesh_partition_static_snapshot(**payload)
    fragment = fragment_module.build_mc2_mesh_static_fragment(snapshot)
    profile = parameters.make_mc2_particle_profile(
        gravity=2.0,
        gravity_direction=(0.0, -1.0, 0.0),
        animation_pose_ratio=0.35,
        angle_restoration_enabled=True,
        angle_restoration_stiffness=0.2,
        collision_mode=0,
        self_collision_mode=0,
    )
    effective = runtime.make_mc2_runtime_parameters(
        profile,
        parameters.make_mc2_setup_options("mesh_cloth"),
        parameters.make_mc2_task_parameters(),
    )
    return compiler.compile_mc2_mesh_static_fragment(fragment, effective)


def _frame(compiled):
    program = compiled.program
    return ir.make_mc2_domain_frame_packet(
        program,
        frame=4,
        generation=2,
        animated_base_world_positions=program.particle_bind_position,
        animated_base_world_rotations=program.particle_bind_rotation,
        animated_base_world_normals=np.asarray(
            ((0.0, 0.0, 1.0),) * program.particle_count, dtype=np.float32
        ),
        partition_world_position=((0.0, 0.0, 0.0),),
        partition_world_rotation=((0.0, 0.0, 0.0, 1.0),),
        partition_world_scale=((1.0, 1.0, 1.0),),
        partition_world_linear=(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),),
        frame_delta_time=1.0 / 30.0,
        simulation_delta_time=1.0 / 90.0,
        time_scale=0.5,
        velocity_weight=(0.25,),
        gravity_ratio=(0.5,),
        is_running=True,
    )


def test_reference_settings_use_compiled_parameters_and_substep_plan() -> None:
    compiled = _compiled()
    frame = _frame(compiled)
    plan = scheduler.MC2SubstepPlan(
        update_index=1,
        simulation_delta_time=1.0 / 90.0,
        frame_interpolation=0.75,
        is_final_substep=False,
        powers=scheduler.derive_mc2_simulation_powers(1.0 / 90.0),
    )
    positions = compiled.program.particle_bind_position
    rotations = compiled.program.particle_bind_rotation
    settings = reference_step.make_mc2_reference_pipeline_settings(
        compiled,
        frame,
        plan,
        anchor_component_local_positions=np.zeros((1, 3), dtype=np.float32),
        step_basic_positions=positions,
        step_basic_rotations=rotations,
        motion_base_positions=positions,
        motion_base_rotations=rotations,
        distance_weights=np.ones(1, dtype=np.float32),
        old_positions=positions,
    )
    assert settings["dt"] == plan.simulation_delta_time
    assert settings["frame_interpolation"] == plan.frame_interpolation
    assert settings["simulation_power"] == plan.powers.integration
    assert settings["distance_simulation_power"] == plan.powers.distance_bending
    assert settings["gravity"] == (0.0, -1.0, 0.0)
    assert settings["velocity_weight"] == 0.25
    assert settings["tether_compression"] == np.float32(0.4).item()
    assert settings["angle_restoration_enabled"] is True
    assert settings["angle_restoration_values"].shape == (compiled.program.particle_count,)
    assert settings["post_step"]["old_positions"].shape == positions.shape
    assert settings["collision_mode"] == 0
    assert settings["self_collision_enabled"] is False


def test_reference_settings_reject_collision_mapping_that_disagrees_with_compiled_mode() -> None:
    compiled = _compiled()
    frame = _frame(compiled)
    plan = scheduler.MC2SubstepPlan(
        update_index=0,
        simulation_delta_time=0.1,
        frame_interpolation=1.0,
        is_final_substep=True,
        powers=scheduler.derive_mc2_simulation_powers(0.1),
    )
    positions = compiled.program.particle_bind_position
    rotations = compiled.program.particle_bind_rotation
    try:
        reference_step.make_mc2_reference_pipeline_settings(
            compiled,
            frame,
            plan,
            anchor_component_local_positions=np.zeros((1, 3), dtype=np.float32),
            step_basic_positions=positions,
            step_basic_rotations=rotations,
            motion_base_positions=positions,
            motion_base_rotations=rotations,
            distance_weights=np.ones(1, dtype=np.float32),
            point_collision={"unexpected": True},
        )
    except ValueError as exc:
        assert "collision_mode" in str(exc)
    else:
        raise AssertionError("collision mapping mismatch must be rejected")


if __name__ == "__main__":
    for test_name, test in sorted(globals().items()):
        if test_name.startswith("test_") and callable(test):
            test()
            print(f"PASS {test_name}")
