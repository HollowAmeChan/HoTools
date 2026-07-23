"""Blender-side smoke test for active MC2 authoring curves."""

from __future__ import annotations

import importlib
import json
import os
import sys
import types

import numpy as np


HERE = os.path.dirname(os.path.abspath(__file__))
PHYSICS_WORLD = os.path.dirname(HERE)
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
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2", os.path.join(PHYSICS_WORLD, "mc2")),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

names = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names")
parameters = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters")
runtime = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters")
partition_specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.partition_specs"
)


class FakeMeshSource:
    name = "MC2RuntimeCurveSource"
    type = "MESH"

    def as_pointer(self):
        return 1729


curve_payload = {
    "kind": "float_curve",
    "interpolation": "BEZIER",
    "extend": "CLAMP",
    "points": [
        {
            "x": 0.0, "y": 0.0, "interpolation": "BEZIER",
            "right_handle_type": "FREE", "right_tangent": 0.0,
        },
        {
            "x": 0.5, "y": 1.0, "interpolation": "BEZIER",
            "left_handle_type": "FREE", "left_tangent": 0.0,
            "right_handle_type": "FREE", "right_tangent": 0.0,
        },
        {
            "x": 1.0, "y": 0.25, "interpolation": "BEZIER",
            "left_handle_type": "FREE", "left_tangent": 0.0,
        },
    ],
}
profile = parameters.make_mc2_particle_profile(damping=0.5, damping_curve=curve_payload)
options = parameters.make_mc2_setup_options(names.MC2_SETUP_MESH_CLOTH)
runtime_spec = runtime.make_mc2_runtime_parameters(profile, options)
curves = dict(zip(runtime.MC2_RUNTIME_CURVE_FIELDS, runtime_spec.curve_values))
assert len(curves["damping"]) == 16
fixture_path = os.path.join(
    PHYSICS_WORLD,
    "mc2", "test", "fixtures", "tier_a", "runtime_parameters_mesh_curve_001.json",
)
with open(fixture_path, "r", encoding="utf-8") as handle:
    expected = json.load(handle)["expected"]
expected_damping = np.asarray(expected["curve_values"][:16], dtype=np.float32)
np.testing.assert_allclose(curves["damping"], expected_damping, rtol=1.0e-6, atol=1.0e-7)

entry = partition_specs.make_mc2_partition_entry(
    FakeMeshSource(),
    setup_type=names.MC2_SETUP_MESH_CLOTH,
    origin="explicit",
    producer="test_blender_mc2_runtime_parameters",
)
plan = partition_specs.collect_mc2_partition_entries(
    setup_type=names.MC2_SETUP_MESH_CLOTH,
    explicit_entries=(entry,),
    default_profile=profile,
    default_setup_options=options,
)
assert plan.active_partitions[0].profile == profile
assert runtime.make_mc2_runtime_parameters(
    plan.active_partitions[0].profile,
    plan.active_partitions[0].setup_options,
    plan.active_partitions[0].task_parameters,
).parameter_signature == runtime_spec.parameter_signature
print("MC2 Blender runtime parameters: PASS")
