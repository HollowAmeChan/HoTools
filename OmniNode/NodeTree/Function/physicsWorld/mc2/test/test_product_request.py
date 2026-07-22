"""MC2 setup 中立产品请求合同的纯宿主测试。"""

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

names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
partitions = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.partition_specs"
)
request_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_request"
)
solver = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_solver"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)


def test_product_import_graph_excludes_v0_owner_modules():
    prefix = "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2."
    forbidden = (
        "specs",
        "solver",
        "native_context",
        "interaction_scope",
        "shadow_pipeline",
    )
    loaded = set(sys.modules)
    assert not [prefix + name for name in forbidden if prefix + name in loaded]


class _Source:
    def __init__(self, pointer: int, name: str):
        self._pointer = pointer
        self.name = self.name_full = name

    def as_pointer(self):
        return self._pointer


def _request(setup_type: str):
    entry = partitions.make_mc2_partition_entry(
        _Source(101, setup_type),
        setup_type=setup_type,
        origin="explicit",
        producer="test.product_request",
    )
    plan = partitions.collect_mc2_partition_entries(
        setup_type=setup_type,
        explicit_entries=(entry,),
        default_setup_options=parameters.make_mc2_setup_options(setup_type),
    )
    return request_module.MC2ProductRequestV1(
        plan=plan,
        fusion_policy=request_module.MC2_FUSION_REQUIRE,
        report_text=f"{setup_type} 测试域",
    )


def test_one_request_contract_carries_all_three_setup_types():
    for setup_type in names.MC2_SETUP_TYPES:
        request = _request(setup_type)
        assert request.setup_type == setup_type
        assert request.domain_signature == request.plan.report.domain_signature
        payload = request.debug_dict()
        assert payload["schema"] == "mc2_product_request_v1"
        assert payload["setup_type"] == setup_type


def test_bone_request_dispatches_to_domain_product_without_v0_fallback():
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    calls = []
    original = solver.step_mc2_products

    def _record(current_world, requests, **kwargs):
        frozen = tuple(requests)
        assert len(frozen) == 1
        calls.append((frozen[0].setup_type, kwargs))
        return current_world, True, "domain product"

    solver.step_mc2_products = _record
    try:
        for setup_type in (
            names.MC2_SETUP_BONE_CLOTH,
            names.MC2_SETUP_BONE_SPRING,
        ):
            returned, ready, status = solver.step_mc2_product(
                world,
                _request(setup_type),
            )
            assert returned is world and ready is True
            assert status == "domain product"
    finally:
        solver.step_mc2_products = original
    assert tuple(value[0] for value in calls) == (
        names.MC2_SETUP_BONE_CLOTH,
        names.MC2_SETUP_BONE_SPRING,
    )
    assert world.solver_slots == {}


def test_request_rejects_non_fusion_policy():
    valid = _request(names.MC2_SETUP_MESH_CLOTH)
    try:
        request_module.MC2ProductRequestV1(
            plan=valid.plan,
            fusion_policy="SPLIT",
            report_text="invalid",
        )
    except ValueError as exc:
        assert "Require Fusion" in str(exc)
    else:
        raise AssertionError("非融合产品请求被接受")


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"MC2 product request: {len(tests)} passed")
