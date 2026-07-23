"""Tier A tests for the MC2 N2 runtime parameter ABI."""

from __future__ import annotations

from dataclasses import replace
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

names = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names")
parameters = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters")
runtime = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters")

FIXTURE_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "tier_a")


def _field(spec, schema, name):
    return spec[schema.index(name)]


def _fixture(case_id):
    with open(os.path.join(FIXTURE_DIRECTORY, case_id + ".json"), "r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    assert fixture["oracle_tier"] == "A"
    assert fixture["mc2_commit"] == "418f89ff31a45bb4b2336641ad5907a1110eabea"
    return fixture


def _assert_matches_oracle(
    spec,
    case_id,
    *,
    product_float_overrides=None,
    product_int_overrides=None,
    product_curve_overrides=None,
):
    expected = _fixture(case_id)["expected"]
    assert expected["abi_version"] == runtime.MC2_RUNTIME_PARAMETERS_ABI
    assert tuple(expected["float_fields"]) == runtime.MC2_RUNTIME_FLOAT_FIELDS
    assert tuple(expected["int_fields"]) == runtime.MC2_RUNTIME_INT_FIELDS
    assert tuple(expected["curve_fields"]) == runtime.MC2_RUNTIME_CURVE_FIELDS
    packed = runtime.pack_mc2_runtime_parameters(spec)
    expected_floats = np.asarray(expected["float_values"], dtype=np.float32).copy()
    for name, value in (product_float_overrides or {}).items():
        expected_floats[runtime.MC2_RUNTIME_FLOAT_FIELDS.index(name)] = np.float32(value)
    np.testing.assert_array_equal(packed["float_values"], expected_floats)
    expected_ints = np.asarray(expected["int_values"], dtype=np.int32).copy()
    for name, value in (product_int_overrides or {}).items():
        expected_ints[runtime.MC2_RUNTIME_INT_FIELDS.index(name)] = np.int32(value)
    np.testing.assert_array_equal(packed["int_values"], expected_ints)
    expected_curves = np.asarray(
        expected["curve_values"], dtype=np.float32
    ).reshape(expected["curve_shape"]).copy()
    for name, value in (product_curve_overrides or {}).items():
        expected_curves[runtime.MC2_RUNTIME_CURVE_FIELDS.index(name)] = np.float32(value)
    np.testing.assert_array_equal(packed["curve_values"], expected_curves)


def test_default_mesh_runtime_matches_get_cloth_parameters_rules() -> None:
    profile = parameters.make_mc2_particle_profile()
    options = parameters.make_mc2_setup_options(names.MC2_SETUP_MESH_CLOTH)
    spec = runtime.make_mc2_runtime_parameters(profile, options)

    assert runtime.MC2_RUNTIME_PARAMETERS_ABI == 0
    assert _field(spec.float_values, runtime.MC2_RUNTIME_FLOAT_FIELDS, "gravity") == 5.0
    assert _field(spec.int_values, runtime.MC2_RUNTIME_INT_FIELDS, "bending_method") == 2
    assert _field(spec.int_values, runtime.MC2_RUNTIME_INT_FIELDS, "use_max_distance") == 0
    damping = _field(spec.curve_values, runtime.MC2_RUNTIME_CURVE_FIELDS, "damping")
    radius = _field(spec.curve_values, runtime.MC2_RUNTIME_CURVE_FIELDS, "radius")
    collision_limit = _field(
        spec.curve_values, runtime.MC2_RUNTIME_CURVE_FIELDS, "collision_limit_distance"
    )
    expected_damping = (np.float32(0.05) * np.float32(0.2)).item()
    assert damping == (expected_damping,) * 16
    assert radius == (np.float32(0.02).item(),) * 16
    assert collision_limit == (0.0,) * 16


def test_bone_spring_applies_mc2_fixed_overrides() -> None:
    profile = parameters.make_mc2_particle_profile(
        gravity=9.0,
        gravity_direction=(0.0, -1.0, 0.0),
        tether_compression=0.25,
        distance_stiffness=0.9,
        bending_stiffness=1.0,
        max_distance_enabled=True,
        max_distance=0.375,
        backstop_enabled=True,
        backstop_radius=0.125,
        backstop_distance=0.25,
        motion_stiffness=0.75,
        collision_mode=2,
        collision_friction=0.1,
        collision_limit_distance=0.125,
        self_collision_mode=2,
        self_collision_sync_mode=2,
        spring_enabled=True,
        spring_power=0.3,
    )
    options = parameters.make_mc2_setup_options(names.MC2_SETUP_BONE_SPRING)
    spec = runtime.make_mc2_runtime_parameters(profile, options)

    floats = dict(zip(runtime.MC2_RUNTIME_FLOAT_FIELDS, spec.float_values))
    ints = dict(zip(runtime.MC2_RUNTIME_INT_FIELDS, spec.int_values))
    curves = dict(zip(runtime.MC2_RUNTIME_CURVE_FIELDS, spec.curve_values))
    assert floats["gravity"] == 0.0
    assert floats["bending_stiffness"] == 0.0
    assert floats["backstop_radius"] == 0.0
    assert floats["motion_stiffness"] == 0.0
    assert floats["tether_compression_limit"] == np.float32(0.8).item()
    assert floats["collision_dynamic_friction"] == 0.5
    assert floats["spring_power"] == np.float32(0.3).item()
    assert ints["collision_mode"] == 1
    assert ints["self_collision_mode"] == ints["self_collision_sync_mode"] == 0
    assert ints["use_max_distance"] == ints["use_backstop"] == 0
    assert curves["distance_stiffness"] == (0.5,) * 16
    assert curves["max_distance"] == (0.0,) * 16
    assert curves["backstop_distance"] == (0.0,) * 16
    assert curves["collision_limit_distance"] == (0.125,) * 16
    assert curves["self_collision_thickness"] == (0.0,) * 16
    # 保留 source fixture 作为 V0 oracle；产品有效参数消除 BoneSpring 不消费的输入。
    _assert_matches_oracle(
        spec,
        "runtime_parameters_bone_spring_001",
        product_float_overrides={
            "bending_stiffness": 0.0,
            "backstop_radius": 0.0,
            "motion_stiffness": 0.0,
        },
        product_int_overrides={"bending_method": 0},
        product_curve_overrides={
            "max_distance": 0.0,
            "backstop_distance": 0.0,
            "self_collision_thickness": 0.0,
        },
    )


def test_mesh_runtime_full_block_matches_unity_oracle() -> None:
    fixture = _fixture("runtime_parameters_mesh_curve_001")
    expected_curve = np.asarray(fixture["expected"]["curve_values"][:16], dtype=np.float32)
    curve_payload = {
        "kind": "float_curve",
        "points": [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 1.0}, {"x": 1.0, "y": 0.25}],
    }
    profile = parameters.make_mc2_particle_profile(damping=0.5, damping_curve=curve_payload)
    options = parameters.make_mc2_setup_options(names.MC2_SETUP_MESH_CLOTH)

    def oracle_curve_sampler(_payload, positions):
        assert positions == tuple(index / 15.0 for index in range(16))
        return expected_curve / np.float32(0.5 * 0.2)

    spec = runtime.make_mc2_runtime_parameters(
        profile, options, curve_sampler=oracle_curve_sampler
    )
    _assert_matches_oracle(spec, "runtime_parameters_mesh_curve_001")


def test_curve_sampling_uses_i_over_15_then_applies_mc2_scale() -> None:
    payload = {
        "kind": "float_curve",
        "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}],
    }
    curve = parameters.make_mc2_curve_spec(
        0.5, payload, minimum=0.0, maximum=1.0, name="test"
    )
    calls = []

    def sampler(received_payload, positions):
        calls.append((received_payload, positions))
        return positions

    values = runtime.sample_mc2_curve16(curve, scale=0.2, curve_sampler=sampler)
    assert len(calls) == 1
    assert calls[0][1] == tuple(index / 15.0 for index in range(16))
    assert values[0] == 0.0
    assert values[-1] == np.float32(0.1).item()
    assert values[7] == np.float32((7.0 / 15.0) * 0.1).item()


def test_bending_method_uses_mc2_epsilon_and_scheduler_is_not_in_abi() -> None:
    options = parameters.make_mc2_setup_options(names.MC2_SETUP_MESH_CLOTH)
    profile = parameters.make_mc2_particle_profile(bending_stiffness=0.0)
    disabled = runtime.make_mc2_runtime_parameters(profile, options)
    enabled_profile = replace(profile, bending_stiffness=2.0e-8)
    enabled = runtime.make_mc2_runtime_parameters(enabled_profile, options)
    assert _field(disabled.int_values, runtime.MC2_RUNTIME_INT_FIELDS, "bending_method") == 0
    assert _field(enabled.int_values, runtime.MC2_RUNTIME_INT_FIELDS, "bending_method") == 2
    assert "substeps" not in runtime.MC2_RUNTIME_FLOAT_FIELDS
    assert "iterations" not in runtime.MC2_RUNTIME_INT_FIELDS
    assert disabled.parameter_signature != enabled.parameter_signature

    spring_options = parameters.make_mc2_setup_options(names.MC2_SETUP_BONE_SPRING)
    spring = runtime.make_mc2_runtime_parameters(enabled_profile, spring_options)
    assert _field(spring.int_values, runtime.MC2_RUNTIME_INT_FIELDS, "bending_method") == 0
    assert _field(spring.float_values, runtime.MC2_RUNTIME_FLOAT_FIELDS, "bending_stiffness") == 0.0


def test_animation_pose_ratio_is_domain_metadata_not_v0_float_abi() -> None:
    profile = parameters.make_mc2_particle_profile(animation_pose_ratio=0.25)
    changed = parameters.make_mc2_particle_profile(animation_pose_ratio=0.75)
    options = parameters.make_mc2_setup_options("mesh_cloth")
    first = runtime.make_mc2_runtime_parameters(profile, options)
    second = runtime.make_mc2_runtime_parameters(changed, options)
    assert first.animation_pose_ratio == 0.25
    assert second.animation_pose_ratio == 0.75
    assert first.parameter_signature != second.parameter_signature
    assert len(first.float_values) == len(runtime.MC2_RUNTIME_FLOAT_FIELDS)
    assert "animation_pose_ratio" not in runtime.MC2_RUNTIME_FLOAT_FIELDS
    assert runtime.pack_mc2_runtime_parameters(first)["float_values"].shape == (
        len(runtime.MC2_RUNTIME_FLOAT_FIELDS),
    )


def test_cross_task_self_collision_is_mesh_only() -> None:
    profile = parameters.make_mc2_particle_profile(
        self_collision_mode=2,
        self_collision_sync_mode=2,
    )
    mesh = runtime.make_mc2_runtime_parameters(
        profile, parameters.make_mc2_setup_options(names.MC2_SETUP_MESH_CLOTH)
    )
    cloth = runtime.make_mc2_runtime_parameters(
        profile, parameters.make_mc2_setup_options(names.MC2_SETUP_BONE_CLOTH)
    )
    spring = runtime.make_mc2_runtime_parameters(
        profile, parameters.make_mc2_setup_options(names.MC2_SETUP_BONE_SPRING)
    )
    assert _field(mesh.int_values, runtime.MC2_RUNTIME_INT_FIELDS, "self_collision_sync_mode") == 2
    assert _field(cloth.int_values, runtime.MC2_RUNTIME_INT_FIELDS, "self_collision_sync_mode") == 0
    assert _field(spring.int_values, runtime.MC2_RUNTIME_INT_FIELDS, "self_collision_sync_mode") == 0


def test_packer_freezes_exact_native_dtypes_shapes_and_read_only_arrays() -> None:
    profile = parameters.make_mc2_particle_profile()
    options = parameters.make_mc2_setup_options(names.MC2_SETUP_BONE_CLOTH)
    spec = runtime.make_mc2_runtime_parameters(profile, options)
    packed = runtime.pack_mc2_runtime_parameters(spec)
    assert packed["float_values"].dtype == np.float32
    assert packed["float_values"].shape == (len(runtime.MC2_RUNTIME_FLOAT_FIELDS),)
    assert packed["int_values"].dtype == np.int32
    assert packed["int_values"].shape == (len(runtime.MC2_RUNTIME_INT_FIELDS),)
    assert packed["curve_values"].dtype == np.float32
    assert packed["curve_values"].shape == (len(runtime.MC2_RUNTIME_CURVE_FIELDS), 16)
    assert all(not value.flags.writeable for value in packed.values())


if __name__ == "__main__":
    for test_name, test in sorted(globals().items()):
        if test_name.startswith("test_") and callable(test):
            test()
            print(f"PASS {test_name}")
