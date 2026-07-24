"""Pure Mesh domain draft assembly tests."""

from __future__ import annotations

import importlib
import os
import sys
import types
from types import SimpleNamespace


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

collect = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_collect"
)
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

    def __init__(self, pointer: int) -> None:
        self._pointer = pointer
        self.name = f"Mesh{pointer}"
        self.name_full = self.name
        self.data = FakeData(pointer + 10000)

    def as_pointer(self):
        return self._pointer


def _entry(pointer: int, stable_id: str, **kwargs):
    return partitions.make_mc2_partition_entry(
        FakeMeshSource(pointer),
        setup_type="mesh_cloth",
        stable_id=stable_id,
        **kwargs,
    )


def _plan(*, gravity=3.0):
    implicit = _entry(
        101,
        "sleeve",
        origin="implicit",
        producer="panel",
        profile=parameters.make_mc2_particle_profile(
            gravity=2.0,
            damping=0.1,
            spring_enabled=False,
        ),
        task_parameters=parameters.make_mc2_task_parameters(cloth_mass=0.2),
    )
    sleeve = _entry(101, "sleeve", producer="node").with_patch(
        partitions.make_mc2_partition_patch(
            profile_values={"gravity": gravity},
            partition_values={"collision_mask": 9},
            producer="sleeve_override",
        )
    )
    coat = _entry(
        102,
        "coat",
        producer="node",
        profile=parameters.make_mc2_particle_profile(
            gravity=8.0,
            damping=0.3,
            spring_enabled=False,
        ),
        task_parameters=parameters.make_mc2_task_parameters(cloth_mass=0.8),
        collision_group=8,
        collision_mask=8,
    )
    return partitions.collect_mc2_partition_entries(
        setup_type="mesh_cloth",
        implicit_entries=implicit,
        explicit_entries=(sleeve, coat),
    )


def test_domain_draft_resolves_effectives_filters_and_provenance() -> None:
    draft = collect.build_mc2_domain_draft(_plan())
    assert draft.partition_ids == ("sleeve", "coat")
    assert draft.collision_groups == (1, 8)
    assert draft.collision_masks == (9, 8)
    assert draft.external_collision_masks == (0, 0)
    first = draft.effectives[0].debug_dict()
    second = draft.effectives[1].debug_dict()
    assert first["float_values"]["gravity"] == 3.0
    assert abs(first["float_values"]["cloth_mass"] - 0.2) < 1.0e-6
    assert second["float_values"]["gravity"] == 8.0
    assert abs(second["float_values"]["cloth_mass"] - 0.8) < 1.0e-6
    assert draft.partitions[0].field_source("profile.gravity") == (
        "override:sleeve_override"
    )
    assert draft.partitions[0].field_source_history("profile.gravity") == (
        "collector.default",
        "implicit:panel",
        "override:sleeve_override",
    )


def test_parameter_change_keeps_domain_identity_but_changes_draft_signature() -> None:
    first = collect.build_mc2_domain_draft(_plan(gravity=3.0))
    changed = collect.build_mc2_domain_draft(_plan(gravity=4.0))
    assert first.domain_id == changed.domain_id
    assert first.collector_domain_signature == changed.collector_domain_signature
    assert first.draft_signature != changed.draft_signature


def test_domain_draft_external_collision_masks_are_parameter_state() -> None:
    first = collect.build_mc2_domain_draft(
        _plan(), external_collision_masks=(1, 2),
    )
    changed = collect.build_mc2_domain_draft(
        _plan(), external_collision_masks=(1, 4),
    )
    assert first.external_collision_masks == (1, 2)
    assert first.domain_id == changed.domain_id
    assert first.draft_signature != changed.draft_signature


def test_domain_draft_rejects_no_active_partitions() -> None:
    plan = partitions.collect_mc2_partition_entries(
        setup_type="mesh_cloth",
        explicit_entries=_entry(301, "disabled", enabled=False),
    )
    try:
        collect.build_mc2_domain_draft(plan)
    except ValueError as exc:
        assert "no active partitions" in str(exc)
    else:
        raise AssertionError("empty active domain must fail")


def test_domain_draft_captures_one_unfiltered_collider_table() -> None:
    draft = collect.build_mc2_domain_draft(_plan())
    external = FakeMeshSource(501)
    world = SimpleNamespace(
        collider_snapshot={
            "frame": 12,
            "colliders": [
                {"key": "self_sleeve", "type": "SPHERE", "owner": draft.partitions[0].source, "primary_group": 1, "center": (0, 0, 0), "radius": 1},
                {"key": "self_coat", "type": "SPHERE", "owner": draft.partitions[1].source, "primary_group": 2, "center": (0, 0, 0), "radius": 1},
                {"key": "external_1", "type": "SPHERE", "owner": external, "primary_group": 1, "center": (1, 0, 0), "radius": 1},
                {"key": "external_3", "type": "SPHERE", "owner": external, "primary_group": 3, "center": (3, 0, 0), "radius": 1},
            ],
        },
        previous_collider_snapshot=None,
    )
    frame = collect.build_mc2_domain_collider_frame_for_draft(world, draft)
    assert frame.frame == 12
    assert frame.source_pointers == (101, 102)
    assert frame.collider_keys == ("external_1", "external_3")
    assert frame.collider_group_bits.tolist() == [1, 4]


if __name__ == "__main__":
    passed = 0
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            passed += 1
            print(f"PASS {name}")
    print(f"MC2 domain collect: {passed} passed")
