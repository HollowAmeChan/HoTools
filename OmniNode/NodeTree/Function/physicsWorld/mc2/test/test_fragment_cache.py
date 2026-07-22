"""E4 tests for transactional MeshCloth static fragment reuse."""

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
fragment_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.static_fragment"
)
cache_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.fragment_cache"
)

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "domain_pipeline", "two_mesh_static", "two_mesh_domain_v1.json",
)


def _snapshots():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payloads = json.load(handle)["static_snapshots"]
    return tuple(
        ir.make_mc2_mesh_partition_static_snapshot(**payload)
        for payload in payloads
    )


class _CountingBuilder:
    def __init__(self):
        self.calls = []
        self.fail_partition = None

    def __call__(self, snapshot, *, world_gravity_direction):
        self.calls.append(snapshot.partition_id)
        if snapshot.partition_id == self.fail_partition:
            raise RuntimeError("injected fragment failure")
        return fragment_module.build_mc2_mesh_static_fragment(
            snapshot,
            world_gravity_direction=world_gravity_direction,
        )


def test_cache_reuses_exact_fragments_and_preserves_requested_order():
    snapshots = _snapshots()
    builder = _CountingBuilder()
    cache = cache_module.MC2MeshFragmentCacheV1(builder)
    first = cache.stage(snapshots)
    assert first.hit_count == 0 and first.build_count == 2
    cache.commit(first)
    second = cache.stage(tuple(reversed(snapshots)))
    assert second.hit_count == 2 and second.build_count == 0
    assert second.fragments == tuple(reversed(first.fragments))
    cache.commit(second)
    assert builder.calls == [snapshot.partition_id for snapshot in snapshots]


def test_gravity_is_part_of_fragment_cache_identity():
    snapshots = _snapshots()
    builder = _CountingBuilder()
    cache = cache_module.MC2MeshFragmentCacheV1(builder)
    first = cache.stage(snapshots, world_gravity_direction=(0.0, -1.0, 0.0))
    cache.commit(first)
    changed = cache.stage(snapshots, world_gravity_direction=(1.0, 0.0, 0.0))
    assert changed.hit_count == 0 and changed.build_count == 2


def test_failed_stage_does_not_publish_partial_fragments():
    snapshots = _snapshots()
    builder = _CountingBuilder()
    builder.fail_partition = snapshots[1].partition_id
    cache = cache_module.MC2MeshFragmentCacheV1(builder)
    try:
        cache.stage(snapshots)
    except RuntimeError as exc:
        assert "injected fragment failure" in str(exc)
    else:
        raise AssertionError("fragment failure was accepted")
    assert cache.entry_count == 0 and cache.revision == 0
    builder.fail_partition = None
    retry = cache.stage(snapshots)
    assert retry.build_count == 2


def test_commit_prunes_entries_not_present_in_new_domain():
    snapshots = _snapshots()
    cache = cache_module.MC2MeshFragmentCacheV1()
    cache.commit(cache.stage(snapshots))
    assert cache.entry_count == 2
    retained = cache.stage((snapshots[1],))
    assert retained.hit_count == 1
    cache.commit(retained)
    assert cache.entry_count == 1
    assert cache.inspect()["partition_ids"] == [snapshots[1].partition_id]


def test_stale_or_foreign_batch_cannot_publish():
    snapshots = _snapshots()
    first_cache = cache_module.MC2MeshFragmentCacheV1()
    second_cache = cache_module.MC2MeshFragmentCacheV1()
    stale = first_cache.stage(snapshots)
    first_cache.commit(first_cache.stage((snapshots[0],)))
    try:
        first_cache.commit(stale)
    except RuntimeError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("stale cache batch was accepted")
    foreign = second_cache.stage(snapshots)
    try:
        first_cache.commit(foreign)
    except ValueError as exc:
        assert "another cache" in str(exc)
    else:
        raise AssertionError("foreign cache batch was accepted")


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"MC2 fragment cache: {len(TESTS)} passed")
