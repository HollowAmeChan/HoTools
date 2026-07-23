"""MC2 多显式产品请求的纯宿主事务测试。"""

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
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.names"
)
mc2_names = importlib.import_module(
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
slot_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_slot"
)
solver = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_solver"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)


class _Source:
    def __init__(self, pointer: int):
        self._pointer = pointer
        self.name = self.name_full = f"Mesh{pointer}"

    def as_pointer(self):
        return self._pointer


def _request(pointer: int):
    entry = partitions.make_mc2_partition_entry(
        _Source(pointer),
        setup_type=mc2_names.MC2_SETUP_MESH_CLOTH,
        origin="explicit",
        producer="test.product_batch",
    )
    plan = partitions.collect_mc2_partition_entries(
        setup_type=mc2_names.MC2_SETUP_MESH_CLOTH,
        explicit_entries=(entry,),
        default_setup_options=parameters.make_mc2_setup_options(
            mc2_names.MC2_SETUP_MESH_CLOTH
        ),
    )
    return request_module.MC2ProductRequestV1(
        plan=plan,
        fusion_policy=request_module.MC2_FUSION_REQUIRE,
        report_text=f"Mesh {pointer}",
    )


def _world():
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    world.frame_context.frame = 7
    world.frame_context.generation = 1
    world.replace_required = False
    return world


def _result(slot_id: str, target: int) -> dict:
    return {
        "channel": names.GN_ATTRIBUTE_CHANNEL,
        "solver": mc2_names.MC2_SOLVER_ID,
        "ready": True,
        "frame": 7,
        "generation": 1,
        "slot_id": slot_id,
        "target_key": f"mesh:{target}:{target + 1000}",
    }


def _install_staged_slot(world, request, target: int, disposed) -> None:
    slot_id = slot_module.make_mc2_product_slot_id(
        request.setup_type,
        request.domain_signature,
    )
    slot = world_types.PhysicsSolverSlot(
        slot_id,
        slot_module.MC2_FUSED_PRODUCT_SLOT_KIND,
        world.generation,
    )
    slot.data["output_results"] = (_result(slot_id, target),)
    slot.data["_dispose"] = lambda reason: disposed.append((slot_id, reason))
    world.solver_slots[slot_id] = slot


def test_two_explicit_domains_publish_once_as_one_result_transaction():
    world = _world()
    requests = (_request(101), _request(202))
    disposed = []
    publication_calls = []
    original_dispatch = solver._dispatch_product
    original_publish = slot_module.publish_mc2_result_transaction

    def _dispatch(current_world, request, **_kwargs):
        target = 1 if request is requests[0] else 2
        _install_staged_slot(current_world, request, target, disposed)
        return current_world, True, f"domain {target}"

    def _publish(current_world, results):
        frozen = tuple(results)
        publication_calls.append(frozen)
        return original_publish(current_world, frozen)

    solver._dispatch_product = _dispatch
    slot_module.publish_mc2_result_transaction = _publish
    try:
        returned, ready, status = solver.step_mc2_products(world, requests)
    finally:
        solver._dispatch_product = original_dispatch
        slot_module.publish_mc2_result_transaction = original_publish

    assert returned is world and ready is True
    assert "域 2" in status
    assert len(publication_calls) == 1
    assert len(publication_calls[0]) == 2
    published = world.consume_results(solver=mc2_names.MC2_SOLVER_ID)
    assert len(published) == 2
    assert {item["target_key"] for item in published} == {
        "mesh:1:1001",
        "mesh:2:1002",
    }
    assert disposed == []
    for request in requests:
        slot_id = slot_module.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        assert len(world.solver_slots[slot_id].data["published_output_results"]) == 1


def test_second_domain_failure_discards_all_attempted_owners_and_results():
    world = _world()
    requests = (_request(303), _request(404))
    disposed = []
    original_dispatch = solver._dispatch_product
    world.publish_result(
        _result("old", 99),
        channel=names.GN_ATTRIBUTE_CHANNEL,
        solver=mc2_names.MC2_SOLVER_ID,
    )

    def _dispatch(current_world, request, **_kwargs):
        target = 3 if request is requests[0] else 4
        _install_staged_slot(current_world, request, target, disposed)
        if request is requests[1]:
            raise RuntimeError("injected second-domain failure")
        return current_world, True, "first domain staged"

    solver._dispatch_product = _dispatch
    try:
        try:
            solver.step_mc2_products(world, requests)
        except RuntimeError as exc:
            assert "injected second-domain failure" in str(exc)
        else:
            raise AssertionError("第二个 domain 的注入故障没有传播")
    finally:
        solver._dispatch_product = original_dispatch

    assert len(disposed) == 2
    assert all(reason == "mc2_product_batch_failure" for _slot, reason in disposed)
    assert world.solver_slots == {}
    assert world.consume_results(solver=mc2_names.MC2_SOLVER_ID) == []
    assert world.replace_required is True


def test_duplicate_explicit_domain_is_rejected_before_execution():
    world = _world()
    request = _request(505)
    original_dispatch = solver._dispatch_product
    calls = []
    solver._dispatch_product = lambda *_args, **_kwargs: calls.append(True)
    try:
        try:
            solver.step_mc2_products(world, (request, request))
        except ValueError as exc:
            assert "重复执行" in str(exc)
        else:
            raise AssertionError("重复的显式 domain 被执行")
    finally:
        solver._dispatch_product = original_dispatch
    assert calls == []
    assert world.solver_slots == {}


def test_empty_product_batch_discards_all_product_slots_and_results():
    world = _world()
    request = _request(606)
    disposed = []
    _install_staged_slot(world, request, 6, disposed)
    world.publish_result(
        _result("old", 6),
        channel=names.GN_ATTRIBUTE_CHANNEL,
        solver=mc2_names.MC2_SOLVER_ID,
    )

    returned, ready, status = solver.step_mc2_products(world, ())

    assert returned is world and ready is False
    assert "无活动request" in status and "清理 1" in status
    assert world.solver_slots == {}
    assert disposed == [(
        slot_module.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        ),
        "mc2_product_request_removed",
    )]
    assert world.consume_results(solver=mc2_names.MC2_SOLVER_ID) == []
    assert world.replace_required is True


def test_successful_product_batch_discards_only_removed_product_slots():
    world = _world()
    stale_request = _request(707)
    active_request = _request(808)
    disposed = []
    _install_staged_slot(world, stale_request, 7, disposed)
    original_dispatch = solver._dispatch_product

    def _dispatch(current_world, request, **_kwargs):
        _install_staged_slot(current_world, request, 8, disposed)
        return current_world, True, "active domain staged"

    solver._dispatch_product = _dispatch
    try:
        returned, ready, status = solver.step_mc2_products(
            world, (active_request,)
        )
    finally:
        solver._dispatch_product = original_dispatch

    stale_slot_id = slot_module.make_mc2_product_slot_id(
        stale_request.setup_type, stale_request.domain_signature
    )
    active_slot_id = slot_module.make_mc2_product_slot_id(
        active_request.setup_type, active_request.domain_signature
    )
    assert returned is world and ready is True
    assert "清理 1" in status
    assert set(world.solver_slots) == {active_slot_id}
    assert disposed == [(stale_slot_id, "mc2_product_request_removed")]


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"MC2 product batch: {len(tests)} passed")
