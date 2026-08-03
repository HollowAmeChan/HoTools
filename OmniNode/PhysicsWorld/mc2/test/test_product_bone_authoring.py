"""BoneCloth/BoneSpring 显式统一域 authoring 的纯宿主测试。"""

from __future__ import annotations

from dataclasses import replace
import importlib
import os
import sys
import types


MC2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(MC2_ROOT)
FUNCTION = os.path.dirname(PHYSICS_WORLD)
NODETREE = os.path.dirname(FUNCTION)
OMNINODE = NODETREE
HOTOOLS = os.path.dirname(OMNINODE)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.Function", FUNCTION),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.PhysicsWorld.mc2", MC2_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

authoring = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.setups.bone_cloth.authoring"
)
object_spec = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.setups.bone_cloth.object_spec"
)
source_spec = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.setups.bone_cloth.source_spec"
)
domain_collect = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.domain_collect"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.parameters"
)
partition_specs = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.partition_specs"
)
request_module = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.product_request"
)
source_identity = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.source_identity"
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


def _explicit_object(armature, *sources):
    return object_spec.MC2BoneClothObjectSpec(
        partition_source=source_spec.MC2BonePartitionSourceV1(
            "bone_cloth",
            armature,
            tuple(source_spec.make_mc2_bone_chain_source(value) for value in sources),
        ),
        explicit_properties=object_spec.make_mc2_bone_cloth_explicit_properties(),
        property_origin="socket",
    )


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
    objects = object_spec.make_mc2_bone_cloth_custom_objects(
        [(armature, "ControlA"), (armature, "ControlB")],
    )
    assert all(
        item.explicit_properties.collided_by_groups == 0
        for item in objects
    )
    partitions = authoring.make_mc2_bone_cloth_domain_partitions(
        objects,
        setup_options=parameters.make_mc2_setup_options(
            "bone_cloth",
            connection_model="hotools_product",
            connection_mode=2,
        ),
    )
    request = authoring.make_mc2_bone_cloth_product_requests(partitions)[0]
    assert isinstance(request, request_module.MC2ProductRequestV1)
    assert request.setup_type == "bone_cloth"
    assert len(request.plan.active_partitions) == 2
    assert all(
        partition.setup_options.collided_by_groups == 0
        for partition in request.plan.active_partitions
    )
    assert tuple(
        tuple(chain.bone_names for chain in partition.source.chains)
        for partition in request.plan.active_partitions
    ) == ((('A1', 'A2'),), (('B1', 'B2'),))
    assert all(
        isinstance(partition.source, source_spec.MC2BonePartitionSourceV1)
        for partition in request.plan.active_partitions
    )
    assert "融合 2 个分区" in request.report_text


def test_bone_cloth_accepts_flat_parallel_chains_for_product_lateral_links():
    flat_bones = tuple(_Bone(name) for name in ("A", "B", "C"))
    armature = _Armature(202, "FlatRig", flat_bones)
    value = {
        "armature": armature,
        "chains": (
            {"bones": ("A",)},
            {"bones": ("B",)},
            {"bones": ("C",)},
        ),
    }
    chains = source_spec.expand_mc2_bone_cloth_control(value)
    assert tuple(chain.bone_names for chain in chains) == (("A",), ("B",), ("C",))
    bone_object = object_spec.make_mc2_bone_cloth_custom_object(value)
    assert tuple(
        chain.bone_names for chain in bone_object.partition_source.chains
    ) == (("A",), ("B",), ("C",))


def test_bone_cloth_object_domain_collector_builds_complete_partitions():
    a2 = _Bone("A2")
    a1 = _Bone("A1", (a2,))
    b2 = _Bone("B2")
    b1 = _Bone("B1", (b2,))
    control_a = _Bone("ControlA", (a1,))
    control_b = _Bone("ControlB", (b1,))
    armature = _Armature(
        151,
        "Rig",
        (control_a, control_b, a1, a2, b1, b2),
    )
    objects = object_spec.make_mc2_bone_cloth_custom_objects(
        [(armature, "ControlA"), (armature, "ControlB")],
        primary_collision_group=3,
        collided_by_groups=0b10000,
    )
    profile = parameters.make_mc2_particle_profile(
        gravity=7.5,
        self_collision_mode=2,
    )
    task = parameters.make_mc2_task_parameters(world_inertia=0.25)
    partitions = authoring.make_mc2_bone_cloth_domain_partitions(
        objects,
        profile=profile,
        task_parameters=task,
        setup_options=parameters.make_mc2_setup_options(
            "bone_cloth",
            connection_model="hotools_product",
            connection_mode=2,
        ),
    )
    assert len(partitions) == 2
    assert all(partition.profile is profile for partition in partitions)
    assert all(partition.task_parameters is task for partition in partitions)
    assert all(partition.enabled is True for partition in partitions)
    assert all(partition.collision_group == 0b100 for partition in partitions)
    assert all(partition.collision_mask == 0b10100 for partition in partitions)
    assert all(
        partition.setup_options.collided_by_groups == 0b10000
        for partition in partitions
    )
    requests = authoring.make_mc2_bone_cloth_product_requests(partitions)
    assert len(requests) == 1
    assert tuple(
        partition.stable_id
        for partition in requests[0].plan.active_partitions
    ) == tuple(partition.stable_id for partition in partitions)
    assert "Grouping: Armature Rig" in requests[0].report_text


def test_bone_collector_groups_cross_armature_as_visible_requests():
    left_root = _Bone("LeftRoot")
    left_control = _Bone("Control", (left_root,))
    right_root = _Bone("RightRoot")
    right_control = _Bone("Control", (right_root,))
    left = _Armature(171, "Left", (left_control, left_root))
    right = _Armature(172, "Right", (right_control, right_root))
    objects = object_spec.make_mc2_bone_cloth_custom_objects(
        [(left, "Control"), (right, "Control")]
    )
    partitions = authoring.make_mc2_bone_cloth_domain_partitions(objects)
    requests = authoring.make_mc2_bone_cloth_product_requests(partitions)
    assert len(requests) == 2
    assert tuple(
        request.plan.active_partitions[0].source.armature
        for request in requests
    ) == (left, right)


def test_bone_domain_and_collector_reject_unwrapped_or_incomplete_values():
    root = _Bone("Root")
    control = _Bone("Control", (root,))
    armature = _Armature(181, "Rig", (control, root))
    try:
        authoring.make_mc2_bone_cloth_domain_partitions(
            [(armature, "Control")]
        )
    except TypeError as exc:
        assert "wrapped BoneCloth objects" in str(exc)
    else:
        raise AssertionError("raw Bone bypassed the object adapter")

    objects = object_spec.make_mc2_bone_cloth_custom_objects(
        [(armature, "Control")]
    )
    partition = authoring.make_mc2_bone_cloth_domain_partitions(objects)[0]
    try:
        authoring.make_mc2_bone_cloth_product_requests((partition, partition))
    except ValueError as exc:
        assert "duplicate stable id" in str(exc)
    else:
        raise AssertionError("duplicate Bone partition was accepted")

    invalid_partitions = (
        (replace(partition, origin="implicit"), "implicit partitions"),
        (
            replace(
                partition,
                source_properties=partition_specs.MC2_UNSET,
            ),
            "complete object properties",
        ),
        (
            partition.with_patch(partition_specs.make_mc2_partition_patch(
                task_values={"world_inertia": 0.5}
            )),
            "partition patches",
        ),
    )
    for invalid, expected in invalid_partitions:
        try:
            authoring.make_mc2_bone_cloth_product_requests([invalid])
        except (TypeError, ValueError) as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"invalid Bone partition was accepted: {expected}")


def test_explicit_bone_cloth_chains_share_one_partition_without_tasks():
    armature = _Armature(201, "Rig")
    bone_object = _explicit_object(
        armature,
        _chain(armature, "A1", "A2"),
        _chain(armature, "B1", "B2", "B3"),
    )
    partitions = authoring.make_mc2_bone_cloth_domain_partitions([bone_object])
    request = authoring.make_mc2_bone_cloth_product_requests(partitions)[0]
    assert len(request.plan.active_partitions) == 1
    source = request.plan.active_partitions[0].source
    assert source.task_sources == (
        _chain(armature, "A1", "A2"),
        _chain(armature, "B1", "B2", "B3"),
    )
    token = source_identity.mc2_source_token(source)
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


def test_bone_plan_builds_same_domain_draft_and_spring_filters_colliders():
    armature = _Armature(351, "SpringRig")
    request = authoring.make_mc2_bone_spring_product_request([
        _chain(armature, "Hair", "Hair.001"),
    ])
    draft = domain_collect.build_mc2_domain_draft(request.plan)
    assert isinstance(draft, domain_collect.MC2DomainDraftV1)
    assert draft.setup_type == "bone_spring"
    assert draft.partition_ids == request.plan.report.ordered_stable_ids
    external = _Armature(352, "ColliderOwner")
    world = types.SimpleNamespace(
        collider_snapshot={
            "frame": 7,
            "colliders": [
                {
                    "key": "self",
                    "type": "SPHERE",
                    "owner": armature,
                    "primary_group": 1,
                    "center": (0, 0, 0),
                    "radius": 1,
                },
                {
                    "key": "sphere",
                    "type": "SPHERE",
                    "owner": external,
                    "primary_group": 1,
                    "center": (1, 0, 0),
                    "radius": 1,
                },
                {
                    "key": "box",
                    "type": "BOX",
                    "owner": external,
                    "primary_group": 1,
                    "center": (2, 0, 0),
                    "size": (1, 1, 1),
                },
            ],
        },
        previous_collider_snapshot=None,
    )
    frame = domain_collect.build_mc2_domain_collider_frame_for_draft(world, draft)
    assert frame.source_pointers == (351,)
    assert frame.collider_keys == ("sphere",)


def test_bone_spring_require_fusion_rejects_cross_armature():
    left = _Armature(401, "Left")
    right = _Armature(402, "Right")
    try:
        authoring.make_mc2_bone_spring_product_request(
            [_chain(left, "A"), _chain(right, "B")]
        )
    except ValueError as exc:
        assert "多个显式 collector" in str(exc)
    else:
        raise AssertionError("跨 Armature BoneSpring 请求被静默拆分")


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
