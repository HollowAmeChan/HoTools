"""E1 tests for one-partition static domain compilation."""

from __future__ import annotations

import importlib
import json
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

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "domain_pipeline",
    "two_mesh_static",
    "two_mesh_domain_v1.json",
)


def _fragment():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"][0]
    snapshot = ir.make_mc2_mesh_partition_static_snapshot(**payload)
    return fragment_module.build_mc2_mesh_static_fragment(snapshot)


def _effective():
    profile = parameters.make_mc2_particle_profile(self_collision_mode=2)
    options = parameters.make_mc2_setup_options("mesh_cloth")
    task = parameters.make_mc2_task_parameters()
    return runtime.make_mc2_runtime_parameters(profile, options, task)


def test_compiler_builds_one_program_and_parameter_packet() -> None:
    compiled = compiler.compile_mc2_mesh_static_fragment(_fragment(), _effective())
    assert compiled.program.partition_count == 1
    assert compiled.program.particle_count == compiled.fragment.final_proxy.vertex_count
    assert compiled.program.partition_particle_views[0].resolved_indices().tolist() == [0, 1, 2]
    assert compiled.program.required_capabilities == ("mesh_cloth", "self_collision")
    assert compiled.parameters.partition_uint_parameters.fields[-2:] == (
        "collision_group",
        "collision_mask",
    )
    assert compiled.parameters.constraint_parameters
    assert compiled.parameters.layout_signature == compiled.program.layout_signature


def test_compiler_preserves_local_constraint_partition_and_output_identity() -> None:
    compiled = compiler.compile_mc2_mesh_static_fragment(_fragment(), _effective())
    for table in compiled.program.constraint_tables:
        assert all(
            compiled.program.particle_partition_index[int(index)] == 0
            for row in table.indices
            for index in row
        )
    assert compiled.program.output_target_index.tolist() == [0, 0, 0]
    assert compiled.program.output_source_element.tolist() == [0, 1, 2]


def test_collision_mask_is_parameter_hot_update_not_program_rebuild() -> None:
    fragment = _fragment()
    effective = _effective()
    first = compiler.compile_mc2_mesh_static_fragment(
        fragment, effective, collision_group=1, collision_mask=0xFFFF
    )
    second = compiler.compile_mc2_mesh_static_fragment(
        fragment, effective, collision_group=1, collision_mask=0
    )
    assert first.program.layout_signature == second.program.layout_signature
    assert first.program.domain_signature == second.program.domain_signature
    assert first.parameters.parameter_layout_signature == second.parameters.parameter_layout_signature
    assert first.parameters.parameter_signature != second.parameters.parameter_signature


def test_compiler_is_deterministic() -> None:
    first = compiler.compile_mc2_mesh_static_fragment(_fragment(), _effective())
    second = compiler.compile_mc2_mesh_static_fragment(_fragment(), _effective())
    assert first.program.domain_signature == second.program.domain_signature
    assert first.parameters.parameter_signature == second.parameters.parameter_signature
    assert first.debug_dict() == second.debug_dict()


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"MC2 domain compile: {len(TESTS)} passed")
