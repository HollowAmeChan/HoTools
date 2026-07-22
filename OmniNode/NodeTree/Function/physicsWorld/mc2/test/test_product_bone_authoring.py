"""BoneCloth/BoneSpring 显式统一域 authoring 的纯宿主测试。"""

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
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_bone_authoring"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
request_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_request"
)
specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)


class _Pointer:
    def __init__(self, pointer: int):
        self._pointer = pointer

    def as_pointer(self):
        return self._pointer


class _Bones:
    def __init__(self, values):
        self._values = {bone.name: bone for bone in values}

    def get(self, name):
        return self._values.get(name)


class _Bone:
    def __init__(self, name, children=()):
        self.name = name
        self.children = list(children)


class _Armature(_Pointer):
    type = "ARMATURE"

    def __init__(self, pointer: int, name: str, bones=()):
        super().__init__(pointer)
        self.name = self.name_full = name
        self.data = _Pointer(pointer + 1000)
        self.pose = types.SimpleNamespace(bones=_Bones(bones))


def _chain(armature, *names):
    return {
        "armature": armature,
        "root_bone": names[0],
        "bones": names,
    }


def test_bone_cloth_control_groups_become_ordered_partitions_in_one_domain():
    a2 = _Bone("A2")
    a1 = _Bone("A1", (a2,))
    b2 = _Bone("B2")
    b1 = _Bone("B1", (b2,))
    control_a = _Bone("ControlA", (a1,))
    control_b = _Bone("ControlB", (b1,))
    armature = _Armature(
        101,
        "Rig",
        (control_a, control_b, a1, a2, b1, b2),
    )
    request = authoring.make_mc2_bone_cloth_product_request(
        [(armature, "ControlA"), (armature, "ControlB")],
        setup_options=parameters.make_mc2_setup_options(
            "bone_cloth",
            connection_model="hotools_product",
            connection_mode=2,
        ),
    )
    assert isinstance(request, request_module.MC2ProductRequestV1)
    assert request.setup_type == "bone_cloth"
    assert len(request.plan.active_partitions) == 2
    assert tuple(
        tuple(chain.bone_names for chain in partition.source.chains)
        for partition in request.plan.active_partitions
    ) == ((('A1', 'A2'),), (('B1', 'B2'),))
    assert all(
        isinstance(partition.source, authoring.MC2BonePartitionSourceV1)
        for partition in request.plan.active_partitions
    )
    assert "融合 2 个分区" in request.report_text


def test_explicit_bone_cloth_chains_share_one_partition_without_tasks():
    armature = _Armature(201, "Rig")
    request = authoring.make_mc2_bone_cloth_product_request([
        _chain(armature, "A1", "A2"),
        _chain(armature, "B1", "B2", "B3"),
    ])
    assert len(request.plan.active_partitions) == 1
    source = request.plan.active_partitions[0].source
    assert source.task_sources == (
        _chain(armature, "A1", "A2"),
        _chain(armature, "B1", "B2", "B3"),
    )
    token = specs.mc2_source_token(source)
    assert token["kind"] == "bone_partition_v1"
    assert tuple(item["root_bone"] for item in token["chains"]) == ("A1", "B1")


def test_bone_spring_merges_roots_and_enforces_line():
    armature = _Armature(301, "SpringRig")
    request = authoring.make_mc2_bone_spring_product_request([
        _chain(armature, "HairL", "HairL.001"),
        _chain(armature, "HairR", "HairR.001"),
    ])
    assert request.setup_type == "bone_spring"
    assert len(request.plan.active_partitions) == 1
    assert len(request.plan.active_partitions[0].source.chains) == 2
    assert request.plan.active_partitions[0].setup_options.connection_mode == 0
    normalized = authoring.make_mc2_bone_spring_product_request(
        [_chain(armature, "HairL", "HairL.001")],
        setup_options=parameters.make_mc2_setup_options(
            "bone_spring", connection_mode=1
        ),
    )
    assert normalized.plan.active_partitions[0].setup_options.connection_mode == 0


def test_require_fusion_rejects_cross_armature_without_hidden_split():
    left = _Armature(401, "Left")
    right = _Armature(402, "Right")
    for factory, sources in (
        (
            authoring.make_mc2_bone_cloth_product_request,
            [_chain(left, "A"), _chain(right, "B")],
        ),
        (
            authoring.make_mc2_bone_spring_product_request,
            [_chain(left, "A"), _chain(right, "B")],
        ),
    ):
        try:
            factory(sources)
        except ValueError as exc:
            assert "多个显式 collector" in str(exc)
        else:
            raise AssertionError("跨 Armature 请求被静默拆分")


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"MC2 Bone product authoring: {len(tests)} passed")
