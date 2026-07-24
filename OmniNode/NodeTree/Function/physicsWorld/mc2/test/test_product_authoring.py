"""MC2 Mesh对象、完整域分区与纯collector合同测试。"""

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

authoring = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.authoring"
)
object_spec = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.object_spec"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
request_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_request"
)


class _Pointer:
    def __init__(self, pointer):
        self._pointer = pointer

    def as_pointer(self):
        return self._pointer


class _Mesh(_Pointer):
    type = "MESH"

    def __init__(self, pointer, name):
        super().__init__(pointer)
        self.data = _Pointer(pointer + 1000)
        self.name = self.name_full = name


def _wrapped(pointer, name, *, group=1, collided=0):
    source = _Mesh(pointer, name)
    return object_spec.make_mc2_mesh_custom_object(
        source,
        primary_collision_group=group,
        collided_by_groups=collided,
    )


def test_domain_outputs_complete_partitions_and_preserves_real_source():
    sleeve = _wrapped(101, "Sleeve", group=3, collided=0b10000)
    anchor = _Pointer(999)
    profile = parameters.make_mc2_particle_profile(
        gravity=7.5,
        self_collision_mode=2,
    )
    task = parameters.make_mc2_task_parameters(world_inertia=0.25)
    partition = authoring.make_mc2_mesh_domain_partitions(
        (sleeve,),
        profile=profile,
        task_parameters=task,
        anchor_object=anchor,
    )[0]
    assert partition.source is sleeve.source_object
    assert partition.source_properties is sleeve.explicit_properties
    assert partition.profile is profile
    assert partition.task_parameters is task
    assert partition.anchor_object is anchor
    assert partition.enabled is True
    assert partition.collision_group == 0b100
    assert partition.collision_mask == 0b10100
    assert partition.setup_options.collided_by_groups == 0b10100
    assert not partition.patches


def test_collector_only_collects_complete_partitions_in_input_order():
    objects = (
        _wrapped(201, "A", group=1),
        _wrapped(202, "B", group=2, collided=1),
    )
    partitions = authoring.make_mc2_mesh_domain_partitions(objects)
    request = authoring.make_mc2_mesh_product_request(partitions)
    assert isinstance(request, request_module.MC2ProductRequestV1)
    assert request.setup_type == "mesh_cloth"
    assert request.debug_dict()["schema"] == "mc2_product_request_v1"
    assert tuple(
        value.stable_id for value in request.plan.active_partitions
    ) == tuple(value.stable_id for value in partitions)
    assert request.plan.report.explicit_input_count == 2
    assert request.plan.report.implicit_input_count == 0
    assert request.plan.report.merged_partition_count == 0
    assert "收集2个完整分区" in request.report_text
    assert "Require Fusion" in request.report_text


def test_collector_rejects_empty_raw_or_duplicate_inputs():
    try:
        authoring.make_mc2_mesh_product_request(())
    except ValueError as exc:
        assert "没有输入分区" in str(exc)
    else:
        raise AssertionError("empty collector request was accepted")

    raw = _Mesh(301, "Raw")
    try:
        authoring.make_mc2_mesh_domain_partitions((raw,))
    except TypeError as exc:
        assert "包装后的对象" in str(exc)
    else:
        raise AssertionError("raw Mesh bypassed the object adapter")

    partition = authoring.make_mc2_mesh_domain_partitions(
        (_wrapped(302, "Duplicate"),)
    )[0]
    try:
        authoring.make_mc2_mesh_product_request((partition, partition))
    except ValueError as exc:
        assert "重复stable id" in str(exc)
    else:
        raise AssertionError("duplicate stable id was accepted")


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"MC2 product authoring: {len(tests)} passed")
