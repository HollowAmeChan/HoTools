"""HoTools product fixtures for ordered BoneCloth lateral connections."""

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

bone_connection = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.bone_connection"
)


POSITIONS = (
    (0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 2.0, 0.0),
    (1.0, 0.0, 0.0),
    (1.0, 1.0, 0.0),
    (1.0, 2.0, 0.0),
    (2.0, 0.0, 0.0),
    (2.0, 1.0, 0.0),
    (2.0, 2.0, 0.0),
)
PARENTS = (-1, 0, 1, -1, 3, 4, -1, 6, 7)
CHAINS = ((0, 1, 2), (3, 4, 5), (6, 7, 8))


def _build(chains=CHAINS, mode=1):
    return bone_connection.build_hotools_bone_connection(
        POSITIONS,
        PARENTS,
        chains,
        mode,
    )


def test_product_sequential_pairs_same_depth_in_task_order() -> None:
    result = _build()
    expected_lateral = {
        (0, 3), (1, 4), (2, 5),
        (3, 6), (4, 7), (5, 8),
    }
    assert result.connection_model == "hotools_product"
    assert expected_lateral <= set(result.lines)
    assert {(0, 6), (1, 7), (2, 8)}.isdisjoint(result.lines)
    assert result.root_order == (0, 3, 6)
    assert result.source_vertex_order == tuple(range(9))
    assert result.levels == (0, 1, 2, 0, 1, 2, 0, 1, 2)
    assert result.triangles


def test_product_sequential_uses_node_order_not_distance() -> None:
    result = _build(((0, 1, 2), (6, 7, 8), (3, 4, 5)))
    assert {(0, 6), (1, 7), (2, 8)} <= set(result.lines)
    assert {(3, 6), (4, 7), (5, 8)} <= set(result.lines)
    assert {(0, 3), (1, 4), (2, 5)}.isdisjoint(result.lines)


def test_product_loop_connects_last_chain_to_first() -> None:
    result = _build(mode=2)
    assert {(0, 6), (1, 7), (2, 8)} <= set(result.lines)


def test_product_line_keeps_only_parent_child_membership() -> None:
    result = _build(mode=0)
    assert result.lines == ((0, 1), (1, 2), (3, 4), (4, 5), (6, 7), (7, 8))
    assert result.triangles == ()


def test_product_chain_contract_rejects_overlap_and_wrong_parent_order() -> None:
    for chains, message in (
        (((0, 1, 2), (2, 3, 4), (5, 6, 7, 8)), "cover every particle"),
        (((0, 2, 1), (3, 4, 5), (6, 7, 8)), "follow parent relations"),
    ):
        try:
            _build(chains)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("invalid product chain layout was accepted")


TESTS = (
    ("ordered same-depth membership", test_product_sequential_pairs_same_depth_in_task_order),
    ("node order is authoritative", test_product_sequential_uses_node_order_not_distance),
    ("loop closes first and last", test_product_loop_connects_last_chain_to_first),
    ("line is longitudinal only", test_product_line_keeps_only_parent_child_membership),
    ("invalid chain layouts reject", test_product_chain_contract_rejects_overlap_and_wrong_parent_order),
)


def main() -> None:
    for name, test in TESTS:
        test()
        print(f"[PASS] {name}")
    print(f"{len(TESTS)}/{len(TESTS)} passed")


if __name__ == "__main__":
    main()
