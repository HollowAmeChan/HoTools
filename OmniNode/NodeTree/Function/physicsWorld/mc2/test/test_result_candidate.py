"""MC2 产品结果事务与多目标输出测试。"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import numpy as np


MC2_ROOT = Path(__file__).resolve().parents[1]
PHYSICS_WORLD = MC2_ROOT.parent
FUNCTION = PHYSICS_WORLD.parent
NODETREE = FUNCTION.parent
OMNINODE = NODETREE.parent
HOTOOLS = OMNINODE.parent

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2", MC2_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [str(package_path)]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

results_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.results"
)
domain_output_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_output"
)


class _ResultWorld:
    def __init__(self, frame: int = 12, generation: int = 4) -> None:
        self.frame_context = SimpleNamespace(frame=frame)
        self.generation = generation
        self.result_streams = {}
        self.fail_publish = False

    def clear_results(self, channel=None, solver=None) -> None:
        if channel is None and solver is None:
            self.result_streams.clear()
            return
        channels = (str(channel),) if channel is not None else tuple(self.result_streams)
        for result_channel in channels:
            items = self.result_streams.get(result_channel, ())
            if solver is None:
                self.result_streams.pop(result_channel, None)
                continue
            kept = [item for item in items if item.get("solver") != solver]
            if kept:
                self.result_streams[result_channel] = kept
            else:
                self.result_streams.pop(result_channel, None)

    def publish_result(self, item, channel=None, solver="unknown", **payload):
        if self.fail_publish:
            raise RuntimeError("injected publish failure")
        result = dict(item or {})
        result.update(payload)
        result["channel"] = str(channel or result.get("channel") or "")
        result.setdefault("solver", solver)
        self.result_streams.setdefault(result["channel"], []).append(result)
        return result

    def consume_results(self, channel, solver=None, frame=None, generation=None):
        items = list(self.result_streams.get(str(channel), ()))
        if solver is not None:
            items = [item for item in items if item.get("solver") == solver]
        if frame is not None:
            items = [item for item in items if item.get("frame") == frame]
        if generation is not None:
            items = [item for item in items if item.get("generation") == generation]
        return items


def test_public_result_transaction_accepts_product_channels_atomically() -> None:
    world = _ResultWorld()
    mesh = {
        "channel": "gn_attribute",
        "solver": "mc2",
        "slot_id": "mc2:mesh:test",
        "target_key": "101:202",
        "frame": 12,
        "generation": 4,
        "ready": True,
    }
    bone = {
        "channel": "bone_transform",
        "writeback_type": "bone_transform_batch",
        "solver": "mc2",
        "slot_id": "mc2:bone:test",
        "target_key": "303:404",
        "frame": 12,
        "generation": 4,
        "ready": True,
    }
    published = results_module.publish_mc2_result_transaction(world, (mesh, bone))
    assert tuple(result["channel"] for result in published) == (
        "gn_attribute",
        "bone_transform",
    )
    assert len(world.result_streams["gn_attribute"]) == 1
    assert len(world.result_streams["bone_transform"]) == 1
    assert tuple(results_module.iter_mc2_results(world)) == published


def test_domain_multi_target_results_share_one_complete_transaction() -> None:
    commands = tuple(
        domain_output_module.MC2MeshWritebackCommandV1(
            target_id=f"mesh:{object_ptr}:{data_ptr}",
            domain_signature="domain-signature",
            layout_signature="layout-signature",
            partition_index=index,
            frame=12,
            generation=4,
            source_elements=np.arange(2, dtype=np.uint32),
            logical_particle_indices=np.arange(
                index * 2,
                index * 2 + 2,
                dtype=np.uint32,
            ),
            world_positions=np.full((2, 3), float(index), dtype=np.float32),
            object_local_offsets=np.full((2, 3), float(index + 1), dtype=np.float32),
        )
        for index, (object_ptr, data_ptr) in enumerate(((101, 201), (102, 202)))
    )
    batch = domain_output_module.MC2MeshWritebackBatchV1(
        transaction_id="mc2-domain-frame-12",
        domain_signature="domain-signature",
        layout_signature="layout-signature",
        frame=12,
        generation=4,
        commands=commands,
    )
    public = results_module.make_mc2_mesh_domain_results(
        batch=batch,
        slot_id="mc2.domain.mesh.product.v1",
        world_generation=4,
    )
    assert len(public) == 2
    assert {item["slot_id"] for item in public} == {"mc2.domain.mesh.product.v1"}
    assert {item["transaction_id"] for item in public} == {"mc2-domain-frame-12"}
    assert [item["transaction_index"] for item in public] == [0, 1]
    assert {item["transaction_size"] for item in public} == {2}
    assert [item["target_key"] for item in public] == ["101:201", "102:202"]

    world = _ResultWorld()
    published = results_module.publish_mc2_result_transaction(world, public)
    assert len(published) == 2
    previous = dict(world.result_streams)
    try:
        results_module.publish_mc2_result_transaction(world, public[:1])
    except ValueError as exc:
        assert "incomplete" in str(exc)
    else:
        raise AssertionError("incomplete multi-target transaction was accepted")
    assert world.result_streams == previous


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"PASS {name}")
