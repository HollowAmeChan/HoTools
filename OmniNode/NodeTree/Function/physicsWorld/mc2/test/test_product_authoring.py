"""MC2 Mesh 产品对象、覆盖、隐式 registry 与 collector 的纯宿主测试。"""

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
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_authoring"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
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


def test_explicit_override_and_implicit_registry_merge_into_one_domain():
    world = world_types.PhysicsWorldCache()
    world.generation = 3
    world.frame_context.frame = 12
    sleeve, coat = _Mesh(101, "Sleeve"), _Mesh(102, "Coat")
    sleeve_entry = authoring.make_mc2_mesh_partition_entries((sleeve,))[0]
    profile = parameters.make_mc2_particle_profile(
        gravity=7.5,
        self_collision_mode=2,
    )
    implicit_entry = authoring.override_mc2_mesh_partition_entries(
        (sleeve_entry,),
        profile=profile,
    )[0]
    count, dirty = authoring.register_mc2_mesh_partition_entries(
        world,
        (implicit_entry,),
    )
    assert count == dirty == 1

    explicit = authoring.make_mc2_mesh_partition_entries((sleeve, coat))
    request = authoring.make_mc2_mesh_product_request(world, explicit)
    assert len(request.plan.active_partitions) == 2
    assert request.plan.report.merged_partition_count == 1
    assert request.plan.report.explicit_input_count == 2
    assert request.plan.report.implicit_input_count == 1
    sleeve_partition = request.plan.active_partitions[0]
    assert sleeve_partition.profile.gravity == 7.5
    assert sleeve_partition.field_source("profile.gravity").startswith("implicit:")
    assert "融合 2 个分区" in request.report_text
    assert "显隐合并 1" in request.report_text
    assert "Require Fusion" in request.report_text


def test_registry_snapshot_disables_entries_removed_by_the_same_producer():
    world = world_types.PhysicsWorldCache()
    entries = authoring.make_mc2_mesh_partition_entries(
        (_Mesh(201, "A"), _Mesh(202, "B"))
    )
    assert authoring.register_mc2_mesh_partition_entries(world, entries) == (2, 2)
    count, dirty = authoring.register_mc2_mesh_partition_entries(world, entries[:1])
    assert count == 1 and dirty == 1
    implicit = authoring.collect_implicit_mc2_mesh_partition_entries(world)
    assert len(implicit) == 1 and implicit[0].stable_id == entries[0].stable_id


def test_collector_rejects_empty_or_non_mesh_inputs():
    world = world_types.PhysicsWorldCache()
    try:
        authoring.make_mc2_mesh_product_request(world, ())
    except ValueError as exc:
        assert "没有启用" in str(exc)
    else:
        raise AssertionError("empty collector request was accepted")
    try:
        authoring.make_mc2_mesh_partition_entries((_Pointer(99),))
    except TypeError as exc:
        assert "Mesh Object" in str(exc)
    else:
        raise AssertionError("non-Mesh authoring source was accepted")


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
