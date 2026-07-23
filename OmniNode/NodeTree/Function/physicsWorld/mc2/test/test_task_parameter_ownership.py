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
partition_specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.partition_specs"
)
request_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_request"
)


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
    entry = partition_specs.make_mc2_partition_entry(
        source,
        setup_type=names.MC2_SETUP_MESH_CLOTH,
        origin="explicit",
        producer="test.task_parameter_ownership",
    )

    def _request(task_parameters):
        plan = partition_specs.collect_mc2_partition_entries(
            setup_type=names.MC2_SETUP_MESH_CLOTH,
            explicit_entries=(entry,),
            default_profile=parameters.make_mc2_particle_profile(),
            default_setup_options=parameters.make_mc2_setup_options(
                names.MC2_SETUP_MESH_CLOTH
            ),
            default_task_parameters=task_parameters,
        )
        return request_module.MC2ProductRequestV1(
            plan=plan,
            fusion_policy=request_module.MC2_FUSION_REQUIRE,
            report_text="task parameter ownership product request",
        )

    first = _request(first_parameters)
    second = _request(second_parameters)
    first_partition = first.plan.active_partitions[0]
    second_partition = second.plan.active_partitions[0]
    assert first.domain_signature == second.domain_signature
    assert first_partition.stable_id == second_partition.stable_id
    assert first_partition.source_token == second_partition.source_token
    assert first_partition.setup_options == second_partition.setup_options
    assert first_partition.task_parameters != second_partition.task_parameters


if __name__ == "__main__":
    for test_name, test in sorted(globals().items()):
        if test_name.startswith("test_") and callable(test):
            test()
            print(f"PASS {test_name}")
