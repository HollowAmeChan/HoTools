"""E1 tests for pure MeshCloth static fragment construction."""

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

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "domain_pipeline",
    "two_mesh_static",
    "two_mesh_domain_v1.json",
)


def _snapshot(index=0):
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"][index]
    return ir.make_mc2_mesh_partition_static_snapshot(**payload)




def test_fragment_builds_full_host_owned_tier_a_data() -> None:
    result = fragment_module.build_mc2_mesh_static_fragment(_snapshot())
    proxy = result.final_proxy
    assert proxy.vertex_count == 3
    assert result.distance.record_count > 0
    assert result.bending is None or result.bending.record_count >= 0
    assert result.self_collision.point_count == 3
    assert result.self_collision.edge_count == len(proxy.edges)
    assert result.self_collision.triangle_count == len(proxy.triangles)
    assert result.baseline.baseline.depths == tuple(result.baseline.baseline.depths)
    assert not result.radius_multipliers.flags.writeable


def test_fragment_preserves_pin_and_radius_semantics() -> None:
    snapshot = _snapshot()
    result = fragment_module.build_mc2_mesh_static_fragment(snapshot)
    attributes = result.final_proxy.vertex_attributes
    assert attributes[0] & 0x01
    assert attributes[1] & 0x02
    assert attributes[2] & 0x02
    assert result.radius_multipliers.tolist() == snapshot.radius_multipliers.tolist()


def test_fragment_is_deterministic_and_does_not_mutate_capture() -> None:
    snapshot = _snapshot()
    first = fragment_module.build_mc2_mesh_static_fragment(snapshot)
    second = fragment_module.build_mc2_mesh_static_fragment(snapshot)
    assert first.final_proxy.proxy_signature == second.final_proxy.proxy_signature
    assert first.baseline.baseline.baseline_signature == second.baseline.baseline.baseline_signature
    assert first.distance.distance_signature == second.distance.distance_signature
    assert first.self_collision.static_signature == second.self_collision.static_signature
    assert not snapshot.local_positions.flags.writeable


def test_triangle_fragment_requires_uv_capture() -> None:
    empty_uvs = np.empty((0, 2), dtype=np.float32)
    empty_uvs.setflags(write=False)
    source = replace(
        _snapshot(index=0),
        has_uv=False,
        loop_uvs=empty_uvs,
    )
    assert source.has_uv is False
    try:
        fragment_module.build_mc2_mesh_static_fragment(source)
    except ValueError as exc:
        assert "requires captured UVs" in str(exc)
    else:
        raise AssertionError("triangle fragment without UV capture was accepted")


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"MC2 partition static fragment: {len(TESTS)} passed")
