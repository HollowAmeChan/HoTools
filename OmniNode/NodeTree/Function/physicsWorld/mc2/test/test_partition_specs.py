"""Pure contract tests for MC2 partition entries and collector resolution."""

from __future__ import annotations

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
partitions = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.partition_specs"
)


class FakeData:
    def __init__(self, pointer: int) -> None:
        self._pointer = pointer

    def as_pointer(self):
        return self._pointer


class FakeMeshSource:
    type = "MESH"

    def __init__(self, pointer: int, name: str | None = None) -> None:
        self._pointer = pointer
        self.name = name or f"Mesh{pointer}"
        self.name_full = self.name
        self.data = FakeData(pointer + 10000)

    def as_pointer(self):
        return self._pointer


def _entry(source, **values):
    return partitions.make_mc2_partition_entry(
        source,
        setup_type=names.MC2_SETUP_MESH_CLOTH,
        **values,
    )


def test_default_stable_id_is_source_deterministic() -> None:
    source = FakeMeshSource(101)
    first = _entry(source)
    second = _entry(source)
    assert first.stable_id == second.stable_id
    assert first.signature == second.signature
    assert first.stable_id.startswith("mc2.mesh_cloth:")


def test_unset_keeps_implicit_values_and_sparse_patch_tracks_owner() -> None:
    source = FakeMeshSource(102)
    implicit_profile = parameters.make_mc2_particle_profile(
        gravity=2.0,
        collision_friction=0.2,
        spring_enabled=False,
    )
    implicit = _entry(
        source,
        stable_id="cloth:shared",
        origin="implicit",
        producer="panel",
        profile=implicit_profile,
    )
    explicit = _entry(
        source,
        stable_id="cloth:shared",
        origin="explicit",
        producer="node",
    ).with_patch(partitions.make_mc2_partition_patch(
        profile_values={"gravity": 3.0},
        producer="gravity_override",
    ))
    plan = partitions.collect_mc2_partition_entries(
        setup_type=names.MC2_SETUP_MESH_CLOTH,
        implicit_entries=[implicit],
        explicit_entries=[explicit],
    )
    resolved = plan.partitions[0]
    assert resolved.profile.gravity == 3.0
    assert resolved.profile.collision_friction == 0.2
    assert resolved.field_source("profile.gravity") == "override:gravity_override"
    assert resolved.field_source("profile.collision_friction") == "implicit:panel"
    assert plan.report.merged_partition_count == 1


def test_explicit_full_profile_wins_over_implicit_profile() -> None:
    source = FakeMeshSource(103)
    implicit = _entry(
        source,
        stable_id="cloth:profile",
        origin="implicit",
        producer="panel",
        profile=parameters.make_mc2_particle_profile(
            gravity=2.0, spring_enabled=False
        ),
    )
    explicit = _entry(
        source,
        stable_id="cloth:profile",
        producer="node",
        profile=parameters.make_mc2_particle_profile(
            gravity=7.0, spring_enabled=False
        ),
    )
    resolved = partitions.collect_mc2_partition_entries(
        setup_type=names.MC2_SETUP_MESH_CLOTH,
        implicit_entries=implicit,
        explicit_entries=explicit,
    ).partitions[0]
    assert resolved.profile.gravity == 7.0
    assert resolved.field_source("profile.gravity") == "explicit:node"


def test_explicit_order_is_authoritative_then_implicit_is_stable() -> None:
    implicit_a = _entry(
        FakeMeshSource(201), stable_id="implicit:z", origin="implicit"
    )
    implicit_b = _entry(
        FakeMeshSource(202), stable_id="implicit:a", origin="implicit"
    )
    explicit_a = _entry(FakeMeshSource(203), stable_id="explicit:second")
    explicit_b = _entry(FakeMeshSource(204), stable_id="explicit:first")
    plan = partitions.collect_mc2_partition_entries(
        setup_type=names.MC2_SETUP_MESH_CLOTH,
        explicit_entries=[explicit_a, explicit_b],
        implicit_entries=[implicit_a, implicit_b],
    )
    assert plan.report.ordered_stable_ids == (
        "explicit:second",
        "explicit:first",
        "implicit:a",
        "implicit:z",
    )
    assert tuple(partition.partition_index for partition in plan.partitions) == (
        0, 1, 2, 3
    )


def test_duplicate_explicit_definition_is_rejected() -> None:
    source = FakeMeshSource(301)
    first = _entry(source, stable_id="duplicate", producer="first")
    second = _entry(
        source,
        stable_id="duplicate",
        producer="second",
        enabled=False,
    )
    try:
        partitions.collect_mc2_partition_entries(
            setup_type=names.MC2_SETUP_MESH_CLOTH,
            explicit_entries=[first, second],
        )
    except partitions.MC2PartitionConflictError as exc:
        assert exc.kind == "duplicate_explicit"
        assert exc.stable_id == "duplicate"
    else:
        raise AssertionError("different explicit definitions must conflict")


def test_same_stable_id_cannot_point_to_different_sources() -> None:
    implicit = _entry(
        FakeMeshSource(401),
        stable_id="source:conflict",
        origin="implicit",
    )
    explicit = _entry(FakeMeshSource(402), stable_id="source:conflict")
    try:
        partitions.collect_mc2_partition_entries(
            setup_type=names.MC2_SETUP_MESH_CLOTH,
            implicit_entries=implicit,
            explicit_entries=explicit,
        )
    except partitions.MC2PartitionConflictError as exc:
        assert exc.kind == "source_mismatch"
    else:
        raise AssertionError("same stable id must not alias different sources")


def test_explicit_none_can_clear_anchor_while_unset_inherits_default() -> None:
    source_a = FakeMeshSource(501)
    source_b = FakeMeshSource(502)
    default_anchor = object()
    inherit = _entry(source_a, stable_id="anchor:inherit")
    clear = _entry(
        source_b,
        stable_id="anchor:clear",
        anchor_object=None,
    )
    plan = partitions.collect_mc2_partition_entries(
        setup_type=names.MC2_SETUP_MESH_CLOTH,
        explicit_entries=[inherit, clear],
        default_anchor_object=default_anchor,
    )
    assert plan.partitions[0].anchor_object is default_anchor
    assert plan.partitions[1].anchor_object is None
    assert plan.partitions[0].field_source("partition.anchor_object") == "collector.default"
    assert plan.partitions[1].field_source("partition.anchor_object") == (
        "explicit:mc2.partition_source"
    )


def test_disabled_partition_is_retained_but_not_active() -> None:
    enabled = _entry(FakeMeshSource(601), stable_id="enabled")
    disabled = _entry(
        FakeMeshSource(602), stable_id="disabled", enabled=False
    )
    plan = partitions.collect_mc2_partition_entries(
        setup_type=names.MC2_SETUP_MESH_CLOTH,
        explicit_entries=[enabled, disabled],
    )
    assert plan.report.partition_count == 2
    assert plan.report.active_partition_count == 1
    assert tuple(item.stable_id for item in plan.active_partitions) == ("enabled",)


def test_unknown_sparse_field_is_rejected() -> None:
    try:
        partitions.make_mc2_partition_patch(profile_values={"not_a_field": 1.0})
    except ValueError as exc:
        assert "not_a_field" in str(exc)
    else:
        raise AssertionError("unknown patch field must fail")


def test_sparse_patch_uses_existing_parameter_normalization() -> None:
    patch = partitions.make_mc2_partition_patch(
        profile_values={"gravity": -5.0},
        task_values={"world_inertia": 4.0},
        setup_values={"collided_by_groups": 0x1FFFF},
    )
    entry = _entry(FakeMeshSource(701), stable_id="normalized").with_patch(patch)
    resolved = partitions.collect_mc2_partition_entries(
        setup_type=names.MC2_SETUP_MESH_CLOTH,
        explicit_entries=entry,
    ).partitions[0]
    assert resolved.profile.gravity == 0.0
    assert resolved.task_parameters.world_inertia == 1.0
    assert resolved.setup_options.collided_by_groups == 0xFFFF


if __name__ == "__main__":
    passed = 0
    for test_name, test in sorted(globals().items()):
        if test_name.startswith("test_") and callable(test):
            test()
            passed += 1
            print(f"PASS {test_name}")
    print(f"MC2 partition specs: {passed} passed")
