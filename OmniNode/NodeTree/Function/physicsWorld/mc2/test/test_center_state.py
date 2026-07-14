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
    assert persistent.anchor_identity == frame.anchor_identity
    assert persistent.old_frame_world_position == persistent.old_world_position == (2.0, 3.0, 4.0)
    assert persistent.smoothing_velocity == (0.0, 0.0, 0.0)


def _adapter_static(fixed_indices) -> center.MC2CenterStaticSpec:
    return center.MC2CenterStaticSpec(
        task_id="mc2:mesh:center-adapter",
        proxy_signature="proxy",
        fixed_indices=tuple(fixed_indices),
        local_center_position=(0.0, 0.0, 0.0),
        initial_local_gravity_direction=(0.0, -1.0, 0.0),
        center_static_signature="center-static",
    )


def _adapter_frame(frame=1, position=(4.0, 5.0, 6.0)) -> center.MC2CenterFramePoseSpec:
    return center.MC2CenterFramePoseSpec(
        frame=frame,
        generation=3,
        component_identity="object:41",
        component_world_position=position,
        component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        component_world_scale=(2.0, 3.0, 4.0),
    )


def test_center_frame_adapter_uses_component_pose_without_fixed_points() -> None:
    frame = _adapter_frame()
    result = center.derive_mc2_center_world_pose(
        _adapter_static(()),
        frame,
        world_positions=((10.0, 0.0, 0.0),),
        world_rotations_xyzw=((0.0, 0.0, 0.0, 1.0),),
        vertex_bind_pose_rotations=((0.0, 0.0, 0.0, 1.0),),
    )
    assert result.position == frame.component_world_position
    assert result.rotation_xyzw == frame.component_world_rotation_xyzw
    assert result.scale == frame.component_world_scale
    assert result.negative_scale_direction == (1.0, 1.0, 1.0)


def test_center_frame_adapter_uses_fixed_particle_pose_and_bind_rotation() -> None:
    result = center.derive_mc2_center_world_pose(
        _adapter_static((0, 2)),
        _adapter_frame(),
        world_positions=((1.0, 2.0, 3.0), (9.0, 9.0, 9.0), (5.0, 6.0, 7.0)),
        world_rotations_xyzw=((0.0, 0.0, 0.0, 1.0),) * 3,
        vertex_bind_pose_rotations=((0.0, 0.0, 0.0, 1.0),) * 3,
    )
    np.testing.assert_allclose(result.position, (3.0, 4.0, 5.0), atol=1.0e-7)
    np.testing.assert_allclose(result.rotation_xyzw, (0.0, 0.0, 0.0, 1.0), atol=1.0e-7)


def test_center_persistent_state_builds_and_commits_continuous_step() -> None:
    static = _adapter_static(())
    first_frame = _adapter_frame()
    first_pose = center.derive_mc2_center_world_pose(
        static,
        first_frame,
        world_positions=((0.0, 0.0, 0.0),),
        world_rotations_xyzw=((0.0, 0.0, 0.0, 1.0),),
        vertex_bind_pose_rotations=((0.0, 0.0, 0.0, 1.0),),
    )
    persistent = center.MC2CenterPersistentState(static.center_static_signature)
    persistent.reset(first_frame, first_pose.position, first_pose.rotation_xyzw)
    second_frame = _adapter_frame(frame=2, position=(5.0, 5.0, 6.0))
    second_pose = center.derive_mc2_center_world_pose(
        static,
        second_frame,
        world_positions=((0.0, 0.0, 0.0),),
        world_rotations_xyzw=((0.0, 0.0, 0.0, 1.0),),
        vertex_bind_pose_rotations=((0.0, 0.0, 0.0, 1.0),),
    )
    step = persistent.make_step_input(
        second_frame,
        second_pose,
        simulation_delta_time=1.0 / 60.0,
        frame_interpolation=0.5,
    )
    assert step.old_frame_world_position == first_pose.position
    assert step.frame_world_position == second_pose.position
    profile = parameters.make_mc2_particle_profile()
    runtime = runtime_parameters.make_mc2_runtime_parameters(
        profile, parameters.make_mc2_setup_options("mesh_cloth")
    )
    result = center.evaluate_mc2_center_step(
        step,
        runtime,
        initial_local_gravity_direction=static.initial_local_gravity_direction,
    )
    persistent.commit_step(second_frame, second_pose, result)
    assert persistent.last_frame == 2
    assert persistent.anchor_identity == second_frame.anchor_identity
    assert persistent.old_frame_world_position == second_pose.position
    assert persistent.old_world_position == result.now_world_position
    assert persistent.velocity_weight == result.velocity_weight


def test_center_persistent_state_threads_frame_shift_into_step_history() -> None:
    static = _adapter_static(())
    first_frame = center.MC2CenterFramePoseSpec(
        frame=1,
        generation=0,
        component_identity="object:shift",
        component_world_position=(0.0, 0.0, 0.0),
        component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        component_world_scale=(1.0, 1.0, 1.0),
    )
    persistent = center.MC2CenterPersistentState(static.center_static_signature)
    persistent.reset(first_frame, (1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), velocity_weight=1.0)
    half_angle = np.float32(np.radians(90.0) * 0.5)
    second_frame = center.MC2CenterFramePoseSpec(
        frame=2,
        generation=0,
        component_identity="object:shift",
        component_world_position=(10.0, 0.0, 0.0),
        component_world_rotation_xyzw=(
            0.0,
            float(np.sin(half_angle)),
            0.0,
            float(np.cos(half_angle)),
        ),
        component_world_scale=(1.0, 1.0, 1.0),
    )
    shift = center.evaluate_mc2_center_frame_shift(
        persistent.make_frame_shift_input(
            second_frame,
            simulation_delta_time=0.1,
            frame_delta_time=0.1,
            world_inertia=0.25,
        )
    )
    center_pose = center.MC2CenterWorldPoseSpec(
        position=second_frame.component_world_position,
        rotation_xyzw=second_frame.component_world_rotation_xyzw,
        scale=second_frame.component_world_scale,
        negative_scale_direction=(1.0, 1.0, 1.0),
    )
    step = persistent.make_step_input(
        second_frame,
        center_pose,
        simulation_delta_time=0.1,
        frame_interpolation=1.0,
        frame_shift=shift,
    )
    np.testing.assert_allclose(step.old_frame_world_position, shift.old_frame_world_position)
    np.testing.assert_allclose(step.old_frame_world_rotation_xyzw, shift.old_frame_world_rotation_xyzw)
    np.testing.assert_allclose(step.old_world_position, shift.now_world_position)
    np.testing.assert_allclose(step.old_world_rotation_xyzw, shift.now_world_rotation_xyzw)


def test_center_persistent_state_builds_anchor_shift_from_pose_history() -> None:
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "tier_a",
        "center_frame_shift_anchor_001.json",
    )
    with open(path, "r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    values = fixture["input"]
    expected = fixture["expected"]
    half_angle = np.float32(np.radians(90.0) * 0.5)
    rotation_90 = (
        0.0,
        float(np.sin(half_angle)),
        0.0,
        float(np.cos(half_angle)),
    )
    first_frame = center.MC2CenterFramePoseSpec(
        frame=1,
        generation=0,
        component_identity="object:anchor",
        component_world_position=values["old_component_world_position"],
        component_world_rotation_xyzw=values["old_component_world_rotation_xyzw"],
        component_world_scale=values["old_component_world_scale"],
        anchor_identity="anchor:fixture",
        anchor_world_position=values["old_anchor_world_position"],
        anchor_world_rotation_xyzw=values["old_anchor_world_rotation_xyzw"],
    )
    persistent = center.MC2CenterPersistentState("anchor-static")
    persistent.reset(
        first_frame,
        values["old_frame_world_position"],
        values["old_frame_world_rotation_xyzw"],
        velocity_weight=1.0,
    )
    np.testing.assert_allclose(
        persistent.anchor_component_local_position,
        values["anchor_component_local_position"],
        atol=1.0e-6,
    )
    second_frame = center.MC2CenterFramePoseSpec(
        frame=2,
        generation=0,
        component_identity="object:anchor",
        component_world_position=values["component_world_position"],
        component_world_rotation_xyzw=rotation_90,
        component_world_scale=values["component_world_scale"],
        anchor_identity="anchor:fixture",
        anchor_world_position=values["anchor_world_position"],
        anchor_world_rotation_xyzw=rotation_90,
    )
    shift = center.evaluate_mc2_center_frame_shift(
        persistent.make_frame_shift_input(
            second_frame,
            simulation_delta_time=values["simulation_delta_time"],
            frame_delta_time=values["frame_delta_time"],
            world_inertia=values["world_inertia"],
            anchor_inertia=values["anchor_inertia"],
            movement_speed_limit=values["movement_speed_limit"],
            rotation_speed_limit=values["rotation_speed_limit"],
        )
    )
    for field, expected_value in expected.items():
        np.testing.assert_allclose(
            getattr(shift, field), expected_value, rtol=1.0e-6, atol=1.0e-6
        )


def test_center_persistent_state_commits_smoothing_velocity() -> None:
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "tier_a",
        "center_frame_shift_smoothing_001.json",
    )
    with open(path, "r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    values = fixture["input"]
    expected = fixture["expected"]
    state = center.MC2CenterPersistentState("center:smoothing")
    first_frame = center.MC2CenterFramePoseSpec(
        frame=1,
        generation=0,
        component_identity="object:smoothing",
        component_world_position=values["old_component_world_position"],
        component_world_rotation_xyzw=values[
            "old_component_world_rotation_xyzw"
        ],
        component_world_scale=values["old_component_world_scale"],
    )
    state.reset(
        first_frame,
        values["old_frame_world_position"],
        values["old_frame_world_rotation_xyzw"],
        velocity_weight=values["velocity_weight"],
    )
    state.old_world_position = tuple(values["now_world_position"])
    state.old_world_rotation_xyzw = tuple(values["now_world_rotation_xyzw"])
    state.smoothing_velocity = tuple(values["smoothing_velocity"])
    half_angle = np.float32(np.radians(90.0) * 0.5)
    second_frame = center.MC2CenterFramePoseSpec(
        frame=2,
        generation=0,
        component_identity=first_frame.component_identity,
        component_world_position=values["component_world_position"],
        component_world_rotation_xyzw=(
            0.0,
            float(np.sin(half_angle)),
            0.0,
            float(np.cos(half_angle)),
        ),
        component_world_scale=values["component_world_scale"],
    )
    shift_input = state.make_frame_shift_input(
        second_frame,
        simulation_delta_time=values["simulation_delta_time"],
        frame_delta_time=values["frame_delta_time"],
        world_inertia=values["world_inertia"],
        movement_inertia_smoothing=values["movement_inertia_smoothing"],
        movement_speed_limit=values["movement_speed_limit"],
        rotation_speed_limit=values["rotation_speed_limit"],
        now_time_scale=values["now_time_scale"],
        is_running=values["is_running"],
    )
    shift = center.evaluate_mc2_center_frame_shift(shift_input)
    np.testing.assert_allclose(
        shift.smoothing_velocity,
        expected["smoothing_velocity"],
        rtol=1.0e-6,
        atol=1.0e-6,
    )
    state.commit_frame_shift(shift)
    np.testing.assert_allclose(
        state.smoothing_velocity,
        expected["smoothing_velocity"],
        rtol=1.0e-6,
        atol=1.0e-6,
    )


def test_center_persistent_state_commits_paused_frame_shift() -> None:
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "tier_a",
        "center_frame_shift_zero_time_scale_001.json",
    )
    with open(path, "r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    values = fixture["input"]
    expected = fixture["expected"]
    first_frame = center.MC2CenterFramePoseSpec(
        frame=1,
        generation=0,
        component_identity="object:paused",
        component_world_position=values["old_component_world_position"],
        component_world_rotation_xyzw=values[
            "old_component_world_rotation_xyzw"
        ],
        component_world_scale=values["old_component_world_scale"],
    )
    state = center.MC2CenterPersistentState("center:paused")
    state.reset(
        first_frame,
        values["old_frame_world_position"],
        values["old_frame_world_rotation_xyzw"],
        velocity_weight=values["velocity_weight"],
    )
    state.old_world_position = tuple(values["now_world_position"])
    state.old_world_rotation_xyzw = tuple(values["now_world_rotation_xyzw"])
    half_angle = np.float32(np.radians(90.0) * 0.5)
    paused_frame = center.MC2CenterFramePoseSpec(
        frame=2,
        generation=0,
        component_identity=first_frame.component_identity,
        component_world_position=values["component_world_position"],
        component_world_rotation_xyzw=(
            0.0,
            float(np.sin(half_angle)),
            0.0,
            float(np.cos(half_angle)),
        ),
        component_world_scale=values["component_world_scale"],
    )
    shift = center.evaluate_mc2_center_frame_shift(
        state.make_frame_shift_input(
            paused_frame,
            simulation_delta_time=values["simulation_delta_time"],
            frame_delta_time=values["frame_delta_time"],
            world_inertia=values["world_inertia"],
            movement_inertia_smoothing=values["movement_inertia_smoothing"],
            movement_speed_limit=values["movement_speed_limit"],
            rotation_speed_limit=values["rotation_speed_limit"],
            now_time_scale=values["now_time_scale"],
            is_running=False,
        )
    )
    state.commit_paused_frame(paused_frame, shift)
    assert state.old_component_world_position == tuple(
        values["component_world_position"]
    )
    np.testing.assert_allclose(
        state.old_frame_world_position,
        expected["old_frame_world_position"],
        rtol=1.0e-6,
        atol=1.0e-6,
    )
    np.testing.assert_allclose(
        state.old_world_position,
        expected["now_world_position"],
        rtol=1.0e-6,
        atol=1.0e-6,
    )
    assert state.last_frame == paused_frame.frame


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
