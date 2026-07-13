"""Tier A Center static and persistent reset contract tests."""

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

center = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.center_state")
parameters = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters")
runtime_parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters"
)
final_proxy = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.final_proxy"
)

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "tier_a", "center_static_fixed_001.json"
)
CENTER_STEP_FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "tier_a", "center_step_inertia_001.json"
)


def _fixture_and_spec():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    source = fixture["input"]
    count = len(source["positions"])
    built = final_proxy.build_mc2_mesh_final_proxy(
        task_id="mc2:mesh:center",
        vertex_identities=tuple(f"v{index}" for index in range(count)),
        local_positions=source["positions"],
        local_normals=((0.0, 0.0, 1.0),) * count,
        local_tangents=((1.0, 0.0, 0.0),) * count,
        uvs=((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.0, 0.0)),
        vertex_attributes=source["attributes"],
        triangles=source["triangles"],
    )
    spec = center.build_mc2_center_static(
        built.proxy,
        vertex_bind_pose_rotations=built.vertex_bind_pose_rotations,
        world_gravity_direction=source["world_gravity_direction"],
    )
    return fixture, spec


def test_center_static_matches_fixed_mc2_oracle() -> None:
    fixture, spec = _fixture_and_spec()
    assert fixture["oracle_tier"] == "A"
    expected = fixture["expected"]
    assert spec.fixed_indices == tuple(expected["fixed_indices"])
    np.testing.assert_allclose(
        spec.local_center_position, expected["local_center_position"], rtol=1.0e-6, atol=1.0e-7
    )
    np.testing.assert_allclose(
        spec.initial_local_gravity_direction,
        expected["initial_local_gravity_direction"],
        rtol=1.0e-6,
        atol=1.0e-7,
    )


def test_center_static_packer_is_fixed_dtype_and_read_only() -> None:
    _fixture, spec = _fixture_and_spec()
    packed = center.pack_mc2_center_static(spec)
    assert packed["fixed_indices"].dtype == np.int32
    assert packed["local_center_position"].dtype == np.float32
    assert packed["initial_local_gravity_direction"].shape == (3,)
    assert all(not value.flags.writeable for value in packed.values())


def test_center_persistent_reset_uses_frame_component_and_derived_center_pose() -> None:
    _fixture, static = _fixture_and_spec()
    frame = center.MC2CenterFramePoseSpec(
        frame=7,
        generation=2,
        component_identity="object:17",
        component_world_position=(1.0, 2.0, 3.0),
        component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        component_world_scale=(1.0, 2.0, 1.0),
        anchor_identity="anchor:3",
        anchor_world_position=(4.0, 5.0, 6.0),
    )
    persistent = center.MC2CenterPersistentState(static.center_static_signature)
    persistent.smoothing_velocity = (9.0, 9.0, 9.0)
    persistent.reset(frame, (2.0, 3.0, 4.0), (0.0, 0.0, 0.0, 1.0))
    assert persistent.initialized and persistent.reset_count == 1
    assert persistent.old_component_world_position == frame.component_world_position
    assert persistent.old_frame_world_position == persistent.old_world_position == (2.0, 3.0, 4.0)
    assert persistent.smoothing_velocity == (0.0, 0.0, 0.0)


def test_center_step_evaluator_matches_fixed_mc2_oracle() -> None:
    with open(CENTER_STEP_FIXTURE_PATH, "r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    values = fixture["input"]
    expected = fixture["expected"]
    half_angle = np.float32(np.radians(values["frame_world_rotation_axis_angle"]["degrees"]) * 0.5)
    frame_rotation = (0.0, float(np.sin(half_angle)), 0.0, float(np.cos(half_angle)))
    frame_interpolation = np.float32(
        (np.float32(values["now_update_time_before_step"])
         + np.float32(values["simulation_delta_time"])
         - np.float32(values["frame_old_time"]))
        / (np.float32(values["time"]) - np.float32(values["frame_old_time"]))
    )
    step = center.MC2CenterStepInputSpec(
        simulation_delta_time=values["simulation_delta_time"],
        frame_interpolation=float(frame_interpolation),
        old_frame_world_position=values["old_frame_world_position"],
        frame_world_position=values["frame_world_position"],
        old_frame_world_rotation_xyzw=values["old_frame_world_rotation_xyzw"],
        frame_world_rotation_xyzw=frame_rotation,
        old_frame_world_scale=values["old_frame_world_scale"],
        frame_world_scale=values["frame_world_scale"],
        old_world_position=values["old_frame_world_position"],
        old_world_rotation_xyzw=values["old_frame_world_rotation_xyzw"],
        initial_scale=values["init_scale"],
        negative_scale_direction=values["negative_scale_direction"],
        velocity_weight=values["velocity_weight_before_step"],
        distance_weight=values["distance_weight"],
    )
    profile = parameters.make_mc2_particle_profile(
        gravity=values["gravity"],
        gravity_direction=values["world_gravity_direction"],
        gravity_falloff=values["gravity_falloff"],
        stabilization_time_after_reset=values["stabilization_time_after_reset"],
        blend_weight=values["parameter_blend_weight"],
        local_inertia=values["local_inertia"],
        local_movement_speed_limit=values["local_movement_speed_limit"],
        local_rotation_speed_limit=values["local_rotation_speed_limit"],
    )
    runtime = runtime_parameters.make_mc2_runtime_parameters(
        profile, parameters.make_mc2_setup_options("mesh_cloth")
    )
    result = center.evaluate_mc2_center_step(
        step,
        runtime,
        initial_local_gravity_direction=values["initial_local_gravity_direction"],
    )
    for field, expected_value in expected.items():
        np.testing.assert_allclose(
            getattr(result, field), expected_value, rtol=1.0e-6, atol=1.0e-6
        )


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"PASS {name}")
