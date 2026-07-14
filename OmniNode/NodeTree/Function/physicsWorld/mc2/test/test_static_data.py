"""Pure validation tests for MC2 N0 static data contracts.

Run with Blender's Python or a Python environment that provides NumPy:
    python test_static_data.py
"""

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
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

static_data = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.static_data"
)


FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "proxy_static_triangle_contract_001.json",
)


def _fixture_specs():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    assert fixture["source"]["oracle_tier"] == "B"
    assert "does not prove builder parity" in fixture["scope"]
    proxy = static_data.make_mc2_proxy_static_spec(**fixture["proxy"])
    baseline_payload = dict(fixture["baseline"])
    baseline_payload["proxy_signature"] = proxy.proxy_signature
    baseline = static_data.make_mc2_baseline_static_spec(**baseline_payload)
    return fixture, proxy, baseline


def _expect_error(exception_type, callback, text: str) -> None:
    try:
        callback()
    except exception_type as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError(f"expected {exception_type.__name__}: {text}")


def test_tier_b_fixture_builds_separate_proxy_and_baseline_specs() -> None:
    fixture, proxy, baseline = _fixture_specs()
    assert fixture["case_id"] == "proxy_static_triangle_contract_001"
    assert proxy.vertex_count == baseline.vertex_count == 3
    assert proxy.edges == ((0, 1), (0, 2), (1, 2))
    assert proxy.triangles == ((0, 1, 2),)
    assert baseline.parent_indices == (-1, 0, 0)
    assert baseline.child_ranges == ((0, 2), (2, 0), (2, 0))
    assert baseline.root_indices == (-1, 0, 0)
    assert baseline.proxy_signature == proxy.proxy_signature
    assert len(proxy.proxy_signature) == len(baseline.baseline_signature) == 64


def test_static_packers_freeze_explicit_native_dtypes_and_shapes() -> None:
    fixture, proxy, baseline = _fixture_specs()
    proxy_buffers = static_data.pack_mc2_proxy_static(proxy)
    baseline_buffers = static_data.pack_mc2_baseline_static(baseline)
    assert proxy_buffers["local_positions"].dtype == np.float32
    assert proxy_buffers["vertex_attributes"].dtype == np.uint8
    assert proxy_buffers["edges"].dtype == np.int32
    assert proxy_buffers["triangles"].shape == (1, 3)
    assert baseline_buffers["parent_indices"].dtype == np.int32
    assert baseline_buffers["child_ranges"].shape == (3, 2)
    assert baseline_buffers["baseline_flags"].dtype == np.uint8
    assert baseline_buffers["vertex_local_rotations"].shape == (3, 4)
    assert all(not array.flags.writeable for array in proxy_buffers.values())
    assert all(not array.flags.writeable for array in baseline_buffers.values())

    numpy_proxy_payload = dict(fixture["proxy"])
    for name in (
        "local_positions", "local_normals", "local_tangents", "uvs",
        "vertex_attributes", "edges", "triangles",
    ):
        numpy_proxy_payload[name] = np.asarray(numpy_proxy_payload[name])
    numpy_proxy = static_data.make_mc2_proxy_static_spec(**numpy_proxy_payload)
    assert numpy_proxy.proxy_signature == proxy.proxy_signature


def _finalizer(proxy):
    return static_data.make_mc2_proxy_finalizer_static_spec(
        proxy=proxy,
        vertex_to_vertex_ranges=((0, 2), (2, 2), (4, 2)),
        vertex_to_vertex_data=(2, 1, 2, 0, 1, 0),
        vertex_to_triangle_records=(((0, 0),), ((0, 0),), ((0, 0),)),
        vertex_bind_pose_positions=((0, 0, 0), (-1, 0, 0), (0, -1, 0)),
        vertex_bind_pose_rotations=((0, 0, 0, 1),) * 3,
    )


def test_proxy_finalizer_validates_derived_topology_and_packs_ragged_records() -> None:
    _fixture, proxy, _baseline = _fixture_specs()
    finalizer = _finalizer(proxy)
    buffers = static_data.pack_mc2_proxy_finalizer_static(finalizer)
    assert finalizer.proxy_signature == proxy.proxy_signature
    assert buffers["vertex_to_triangle_ranges"].shape == (3, 2)
    assert buffers["vertex_to_triangle_data"].shape == (3, 2)
    assert all(not array.flags.writeable for array in buffers.values())

    _expect_error(
        ValueError,
        lambda: static_data.make_mc2_proxy_finalizer_static_spec(
            proxy=proxy,
            vertex_to_vertex_ranges=((0, 1), (1, 1), (2, 0)),
            vertex_to_vertex_data=(1, 0),
            vertex_to_triangle_records=(((0, 0),), ((0, 0),), ((0, 0),)),
            vertex_bind_pose_positions=((0, 0, 0), (-1, 0, 0), (0, -1, 0)),
            vertex_bind_pose_rotations=((0, 0, 0, 1),) * 3,
        ),
        "exactly the finalized proxy edges",
    )
    _expect_error(
        ValueError,
        lambda: static_data.make_mc2_proxy_finalizer_static_spec(
            proxy=proxy,
            vertex_to_vertex_ranges=finalizer.vertex_to_vertex_ranges,
            vertex_to_vertex_data=finalizer.vertex_to_vertex_data,
            vertex_to_triangle_records=((), ((0, 0),)),
            vertex_bind_pose_positions=finalizer.vertex_bind_pose_positions,
            vertex_bind_pose_rotations=finalizer.vertex_bind_pose_rotations,
        ),
        "length must match vertex_count",
    )


def test_proxy_signature_is_canonical_for_unordered_edges_but_keeps_winding() -> None:
    fixture, first, _ = _fixture_specs()
    payload = dict(fixture["proxy"])
    payload["edges"] = [[2, 0], [0, 1], [1, 2]]
    second = static_data.make_mc2_proxy_static_spec(**payload)
    assert second.proxy_signature == first.proxy_signature
    payload["triangles"] = [[0, 2, 1]]
    third = static_data.make_mc2_proxy_static_spec(**payload)
    assert third.proxy_signature != first.proxy_signature


def test_proxy_validation_rejects_identity_topology_and_numeric_errors() -> None:
    fixture, proxy, _ = _fixture_specs()
    mutable_positions = tuple(list(value) for value in proxy.local_positions)
    _expect_error(
        TypeError,
        lambda: replace(proxy, local_positions=mutable_positions),
        "immutable tuples",
    )

    payload = dict(fixture["proxy"])
    payload["vertex_identities"] = ["v", "v", "v2"]
    _expect_error(ValueError, lambda: static_data.make_mc2_proxy_static_spec(**payload), "unique")

    payload = dict(fixture["proxy"])
    payload["edges"] = [[0, 0]]
    _expect_error(ValueError, lambda: static_data.make_mc2_proxy_static_spec(**payload), "self edge")

    payload = dict(fixture["proxy"])
    payload["triangles"] = [[0, 1, 3]]
    _expect_error(ValueError, lambda: static_data.make_mc2_proxy_static_spec(**payload), "out of range")

    payload = dict(fixture["proxy"])
    payload["local_positions"] = [[0, 0, float("nan")], [1, 0, 0], [0, 1, 0]]
    _expect_error(ValueError, lambda: static_data.make_mc2_proxy_static_spec(**payload), "NaN/Inf")


def test_baseline_validation_rejects_cycles_ranges_and_non_unit_rotations() -> None:
    fixture, proxy, _ = _fixture_specs()

    payload = dict(fixture["baseline"])
    payload.update(proxy_signature=proxy.proxy_signature, parent_indices=[1, 0, -1])
    _expect_error(ValueError, lambda: static_data.make_mc2_baseline_static_spec(**payload), "cycle")

    payload = dict(fixture["baseline"])
    payload.update(proxy_signature=proxy.proxy_signature, child_data=[0, 2])
    _expect_error(ValueError, lambda: static_data.make_mc2_baseline_static_spec(**payload), "disagrees")

    payload = dict(fixture["baseline"])
    payload.update(proxy_signature=proxy.proxy_signature, baseline_ranges=[[1, 3]])
    _expect_error(ValueError, lambda: static_data.make_mc2_baseline_static_spec(**payload), "dense")

    payload = dict(fixture["baseline"])
    rotations = list(payload["vertex_local_rotations"])
    rotations[1] = [0, 0, 0, 2]
    payload.update(proxy_signature=proxy.proxy_signature, vertex_local_rotations=rotations)
    _expect_error(ValueError, lambda: static_data.make_mc2_baseline_static_spec(**payload), "unit xyzw")


TESTS = (
    ("Tier B fixture separates proxy and baseline", test_tier_b_fixture_builds_separate_proxy_and_baseline_specs),
    ("packers freeze dtype and shape", test_static_packers_freeze_explicit_native_dtypes_and_shapes),
    (
        "proxy finalizer validates and packs derived arrays",
        test_proxy_finalizer_validates_derived_topology_and_packs_ragged_records,
    ),
    (
        "proxy signatures canonicalize only unordered edges",
        test_proxy_signature_is_canonical_for_unordered_edges_but_keeps_winding,
    ),
    ("proxy validation rejects malformed data", test_proxy_validation_rejects_identity_topology_and_numeric_errors),
    (
        "baseline validation rejects malformed data",
        test_baseline_validation_rejects_cycles_ranges_and_non_unit_rotations,
    ),
)


def main() -> None:
    passed = 0
    for name, test in TESTS:
        test()
        passed += 1
        print(f"[PASS] {name}")
    print(f"{passed}/{len(TESTS)} passed")


if __name__ == "__main__":
    main()
