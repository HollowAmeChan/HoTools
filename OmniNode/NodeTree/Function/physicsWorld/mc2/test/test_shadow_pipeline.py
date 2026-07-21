"""E1 shadow report tests that stay outside the Blender execution boundary."""

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
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups", os.path.join(MC2_ROOT, "setups")),
    (
        "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth",
        os.path.join(MC2_ROOT, "setups", "mesh_cloth"),
    ),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

ir = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_ir"
)
fragment_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.static_fragment"
)
compiler = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_compile"
)
shadow = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.shadow_pipeline"
)
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
    runtime = importlib.import_module(
        "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters"
    )
    parameters = importlib.import_module(
        "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
    )
    profile = parameters.make_mc2_particle_profile(self_collision_mode=2)
    effective = runtime.make_mc2_runtime_parameters(
        profile,
        parameters.make_mc2_setup_options("mesh_cloth"),
        parameters.make_mc2_task_parameters(),
    )
    return fragment, compiler.compile_mc2_mesh_static_fragment(fragment, effective), effective


def test_shadow_report_matches_fragment_and_compiled_program() -> None:
    fragment, compiled, effective = _compiled()
    report = shadow.compare_mc2_mesh_static_to_compiled(
        fragment,
        compiled,
        effective_parameter_signature=effective.parameter_signature,
    )
    assert report.compatible is True
    assert all(item.matched for item in report.checks)
    assert report.debug_dict()["compatible"] is True


def test_shadow_report_identifies_array_mismatch() -> None:
    fragment, compiled, effective = _compiled()
    changed = np.array(fragment.radius_multipliers, dtype=np.float32, copy=True)
    changed[0] = 0.25
    changed.setflags(write=False)
    altered = replace(fragment, radius_multipliers=changed)
    report = shadow.compare_mc2_mesh_static_to_compiled(
        altered,
        compiled,
        effective_parameter_signature=effective.parameter_signature,
    )
    assert report.compatible is False
    assert any(item.name == "radius_multipliers" and not item.matched for item in report.checks)


def test_shadow_disabled_path_returns_without_validating_inputs() -> None:
    assert shadow.run_mc2_mesh_shadow_compile(
        None,
        None,
        None,
        None,
        shadow_enabled=False,
    ) is None


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"MC2 shadow pipeline: {len(TESTS)} passed")
