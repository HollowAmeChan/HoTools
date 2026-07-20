"""Regression tests for the D-05 Profile/Task ownership contract."""

from __future__ import annotations

from dataclasses import replace
import importlib
import os
import sys
import types


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
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
runtime = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters"
)
specs = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs")


class FakeMeshSource:
    type = "MESH"
    name = "D05Source"
    name_full = name
    data = None

    def as_pointer(self):
        return 505


def _runtime_maps(value):
    return (
        dict(zip(runtime.MC2_RUNTIME_FLOAT_FIELDS, value.float_values)),
        dict(zip(runtime.MC2_RUNTIME_INT_FIELDS, value.int_values)),
    )


def test_profile_has_no_task_owned_fields() -> None:
    profile = parameters.make_mc2_particle_profile()
    for name in (
        "normal_axis",
        "anchor_inertia",
        "world_inertia",
        "movement_inertia_smoothing",
        "movement_speed_limit",
        "rotation_speed_limit",
        "local_inertia",
        "local_movement_speed_limit",
        "local_rotation_speed_limit",
        "depth_inertia",
        "centrifugal_acceleration",
        "teleport_mode",
        "teleport_distance",
        "teleport_rotation",
        "cloth_mass",
    ):
        assert not hasattr(profile, name), name


def test_task_parameters_are_the_only_runtime_owner() -> None:
    profile = parameters.make_mc2_particle_profile()
    options = parameters.make_mc2_setup_options(names.MC2_SETUP_MESH_CLOTH)
    task_parameters = parameters.make_mc2_task_parameters(
        normal_axis=4,
        anchor_inertia=0.25,
        world_inertia=0.75,
        depth_inertia=0.5,
        teleport_mode=2,
        teleport_distance=1.25,
        teleport_rotation=45.0,
        cloth_mass=0.8,
    )
    value = runtime.make_mc2_runtime_parameters(profile, options, task_parameters)
    floats, ints = _runtime_maps(value)
    assert ints["normal_axis"] == 4
    assert ints["teleport_mode"] == 2
    assert floats["anchor_inertia"] == 0.25
    assert floats["world_inertia"] == 0.75
    assert floats["depth_inertia"] == 0.5
    assert floats["teleport_distance"] == 1.25
    assert floats["teleport_rotation"] == 45.0
    assert abs(floats["cloth_mass"] - 0.8) < 1.0e-6
    assert floats["centrifugal_acceleration"] == 0.0


def test_hidden_centrifugal_abi_defaults_to_zero() -> None:
    task_parameters = parameters.make_mc2_task_parameters()
    assert task_parameters.centrifugal_acceleration == 0.0

    value = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(),
        parameters.make_mc2_setup_options(names.MC2_SETUP_MESH_CLOTH),
        task_parameters,
    )
    floats, _ints = _runtime_maps(value)
    assert floats["centrifugal_acceleration"] == 0.0


def test_task_parameter_hot_update_preserves_identity_and_topology() -> None:
    source = FakeMeshSource()
    first_parameters = parameters.make_mc2_task_parameters()
    second_parameters = replace(first_parameters, world_inertia=0.25)
    first = specs.make_mc2_task_spec(
        names.MC2_SETUP_MESH_CLOTH,
        [source],
        task_parameters=first_parameters,
    )
    second = specs.make_mc2_task_spec(
        names.MC2_SETUP_MESH_CLOTH,
        [source],
        task_parameters=second_parameters,
    )
    assert first.task_id == second.task_id
    assert first.source_signature == second.source_signature
    assert first.topology_signature == second.topology_signature
    assert first.config_signature == second.config_signature
    assert first.parameter_signature != second.parameter_signature
    assert first.implementation_version == second.implementation_version == 3


if __name__ == "__main__":
    for test_name, test in sorted(globals().items()):
        if test_name.startswith("test_") and callable(test):
            test()
            print(f"PASS {test_name}")
