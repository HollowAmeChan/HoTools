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


def _fragment(index=0):
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"][index]
    snapshot = ir.make_mc2_mesh_partition_static_snapshot(**payload)
    return fragment_module.build_mc2_mesh_static_fragment(snapshot)


def _effective(*, gravity=5.0, damping=0.05, cloth_mass=0.0):
    profile = parameters.make_mc2_particle_profile(
        self_collision_mode=2,
        gravity=gravity,
        damping=damping,
    )
    options = parameters.make_mc2_setup_options("mesh_cloth")
    task = parameters.make_mc2_task_parameters(cloth_mass=cloth_mass)
    return runtime.make_mc2_runtime_parameters(profile, options, task)


def _fragments():
    return (_fragment(0), _fragment(1))


def test_compiler_builds_one_program_and_parameter_packet() -> None:
    compiled = compiler.compile_mc2_mesh_static_fragment(_fragment(), _effective())
    assert compiled.program.partition_count == 1
    assert compiled.program.particle_count == compiled.fragment.final_proxy.vertex_count
    assert compiled.program.partition_particle_views[0].resolved_indices().tolist() == [0, 1, 2]
    assert compiled.program.required_capabilities == ("mesh_cloth", "self_collision")
    assert compiled.program.partition_center_local_position.shape == (1, 3)
    assert compiled.program.partition_initial_local_gravity_direction.tolist() == [
        [0.0, -1.0, 0.0]
    ]
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


def test_multi_compiler_merges_particles_and_keeps_structural_constraints_local() -> None:
    fragments = _fragments()
    compiled = compiler.compile_mc2_mesh_static_fragments(
        fragments,
        (_effective(), _effective(gravity=8.0, damping=0.2, cloth_mass=0.6)),
        domain_id="mc2.domain:test-two",
        collision_groups=(1, 2),
        collision_masks=(3, 3),
    )
    assert compiled.program.partition_ids == ("sleeve", "coat")
    assert compiled.program.partition_particle_views[0].resolved_indices().tolist() == [0, 1, 2]
    assert compiled.program.partition_particle_views[1].resolved_indices().tolist() == [3, 4]
    assert compiled.program.output_target_index.tolist() == [0, 0, 0, 1, 1]
    assert [target.target_id for target in compiled.program.output_targets] == [
        "mesh:sleeve", "mesh:coat"
    ]
    for table in compiled.program.constraint_tables:
        for row, owner in zip(table.indices, table.owner_partition_index):
            assert all(compiled.program.particle_partition_index[int(index)] == owner for index in row)
    for table in compiled.program.primitive_tables:
        assert set(int(owner) for owner in table.owner_partition_index) <= {0, 1}
    assert compiled.parameters.particle_parameters.row_count == 5
    assert compiled.parameters.partition_parameters.row_count == 2
    assert compiled.program.partition_center_local_position.tolist() == [
        [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    ]
    assert compiled.program.partition_initial_local_gravity_direction.tolist() == [
        [0.0, -1.0, 0.0], [0.0, -1.0, 0.0]
    ]


def test_multi_compiler_preserves_partition_parameter_differences_and_filters() -> None:
    compiled = compiler.compile_mc2_mesh_static_fragments(
        _fragments(),
        (_effective(gravity=5.0, damping=0.05, cloth_mass=0.1),
         _effective(gravity=9.0, damping=0.3, cloth_mass=0.8)),
        collision_groups=(1, 2),
        collision_masks=(1, 2),
    )
    partition = compiled.parameters.partition_parameters
    gravity_index = partition.fields.index("gravity")
    assert partition.values[:, gravity_index].tolist() == [5.0, 9.0]
    particle = compiled.parameters.particle_parameters
    mass_index = particle.fields.index("cloth_mass")
    assert all(abs(float(value) - 0.1) < 1.0e-6 for value in particle.values[:3, mass_index])
    assert all(abs(float(value) - 0.8) < 1.0e-6 for value in particle.values[3:, mass_index])
    uint = compiled.parameters.partition_uint_parameters.values
    assert uint[:, -2:].tolist() == [[1, 1], [2, 2]]
    assert not (int(uint[0, -1]) & int(uint[1, -2]))
    assert not (int(uint[1, -1]) & int(uint[0, -2]))


def test_multi_compile_cache_report_distinguishes_reuse_parameter_update_and_reorder() -> None:
    fragments = _fragments()
    first = compiler.compile_mc2_mesh_static_fragments(
        fragments, (_effective(), _effective()), domain_id="mc2.domain:cache",
        collision_groups=(1, 2), collision_masks=(3, 3),
    )
    cold = compiler.compare_mc2_domain_compile_cache(None, first)
    assert not cold.exact_cache_hit
    same = compiler.compile_mc2_mesh_static_fragments(
        fragments, (_effective(), _effective()), domain_id="mc2.domain:cache",
        collision_groups=(1, 2), collision_masks=(3, 3),
    )
    exact = compiler.compare_mc2_domain_compile_cache(first, same)
    assert exact.exact_cache_hit
    mask_update = compiler.compile_mc2_mesh_static_fragments(
        fragments, (_effective(), _effective()), domain_id="mc2.domain:cache",
        collision_groups=(1, 2), collision_masks=(1, 2),
    )
    updated = compiler.compare_mc2_domain_compile_cache(first, mask_update)
    assert updated.layout_cache_hit
    assert updated.program_cache_hit
    assert updated.parameter_layout_cache_hit
    assert not updated.parameter_value_cache_hit
    reordered = compiler.compile_mc2_mesh_static_fragments(
        tuple(reversed(fragments)), (_effective(), _effective()),
        domain_id="mc2.domain:cache", collision_groups=(1, 2), collision_masks=(3, 3),
    )
    reorder_report = compiler.compare_mc2_domain_compile_cache(first, reordered)
    assert reorder_report.common_order_changed
    assert not reorder_report.program_cache_hit
    deleted = compiler.compile_mc2_mesh_static_fragments(
        (fragments[1],), (_effective(),), domain_id="mc2.domain:cache",
        collision_groups=(1,), collision_masks=(3,),
    )
    delete_report = compiler.compare_mc2_domain_compile_cache(first, deleted)
    assert delete_report.removed_partition_ids == ("sleeve",)


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
