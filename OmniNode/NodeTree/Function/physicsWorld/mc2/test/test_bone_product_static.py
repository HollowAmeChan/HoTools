"""Production-contract tests for multi-chain HoTools BoneCloth tasks."""

from __future__ import annotations

import importlib
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

parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)
topology = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
static_build = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_cloth.static_build"
)
product_authoring = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_bone_authoring"
)
domain_collect = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_collect"
)
domain_compile = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_compile"
)
bone_fragment = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_cloth.static_fragment"
)
domain_owner = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_owner"
)
cpu_kernel = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.cpu_native_kernel"
)
center_state = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.center_state"
)
frame_state = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.frame_state"
)
product_bone_frame = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_bone_frame"
)
product_bone_collect = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_bone_collect"
)
bone_fragment_cache = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_cloth.fragment_cache"
)


IDENTITY = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


class Bone:
    def __init__(self, name, head, tail):
        self.name = name
        self.head_local = head
        self.tail_local = tail
        self.matrix_local = IDENTITY
        self.parent = None
        self.children = []


class Bones(list):
    def get(self, name):
        return next((bone for bone in self if bone.name == name), None)


class Data:
    def __init__(self, bones, pointer):
        self.bones = Bones(bones)
        self._pointer = pointer

    def as_pointer(self):
        return self._pointer


class Armature:
    type = "ARMATURE"

    def __init__(self, bones, pointer=1001):
        self.data = Data(bones, pointer + 1)
        self.pose = types.SimpleNamespace(bones=self.data.bones)
        self.name = "ProductArmature"
        self.name_full = self.name
        self._pointer = pointer

    def as_pointer(self):
        return self._pointer


def _armature():
    bones = []
    for chain_index, prefix in enumerate(("A", "B", "C")):
        previous = None
        for depth in range(3):
            bone = Bone(
                f"{prefix}{depth}",
                (float(chain_index), float(depth), 0.0),
                (float(chain_index), float(depth + 1), 0.0),
            )
            bone.parent = previous
            if previous is not None:
                previous.children.append(bone)
            bones.append(bone)
            previous = bone
    return Armature(bones)


def _task(armature):
    sources = [
        {
            "armature": armature,
            "root_bone": f"{prefix}0",
            "bones": [f"{prefix}{depth}" for depth in range(3)],
        }
        for prefix in ("A", "B", "C")
    ]
    return specs.make_mc2_task_spec(
        "bone_cloth",
        sources,
        profile=parameters.make_mc2_particle_profile(),
        setup_options=parameters.make_mc2_setup_options(
            "bone_cloth",
            connection_model="hotools_product",
            connection_mode=1,
        ),
    )


def test_product_task_builds_multi_chain_topology_and_static_bundle() -> None:
    task = _task(_armature())
    built_topology = topology.build_mc2_topology_spec(task)
    assert built_topology.connection_model == "hotools_product"
    source_task = specs.make_mc2_task_spec(
        "bone_cloth",
        task.sources,
        setup_options=parameters.make_mc2_setup_options(
            "bone_cloth",
            connection_mode=1,
        ),
    )
    assert source_task.task_id == task.task_id
    assert source_task.topology_signature != task.topology_signature
    assert len(built_topology.sources) == 3
    assert built_topology.particle_count == 9
    assert {(0, 3), (1, 4), (2, 5), (3, 6), (4, 7), (5, 8)} <= set(
        built_topology.bone_connection.lines
    )
    assert built_topology.bone_connection.triangles

    built_static = static_build.build_mc2_bone_cloth_static_for_task(
        task,
        built_topology,
    )
    assert built_static.connection_model == "hotools_product"
    assert built_static.final_proxy.vertex_count == 9
    assert {
        tuple(sorted(triangle))
        for triangle in built_static.final_proxy.triangles
    } == set(built_topology.bone_connection.triangles)
    assert built_static.distance.distance_targets


def test_product_task_rejects_sources_from_multiple_armatures() -> None:
    task = _task(_armature())
    other = _armature()
    other._pointer = 2001
    other.data._pointer = 2002
    mixed_sources = list(task.sources)
    replacement = dict(mixed_sources[-1])
    replacement["armature"] = other
    mixed_sources[-1] = replacement
    mixed = specs.make_mc2_task_spec(
        "bone_cloth",
        mixed_sources,
        profile=task.profile,
        setup_options=task.setup_options,
    )
    built_topology = topology.build_mc2_topology_spec(mixed)
    try:
        static_build.build_mc2_bone_cloth_static_for_task(mixed, built_topology)
    except ValueError as exc:
        assert "one Armature" in str(exc)
    else:
        raise AssertionError("multi-armature BoneCloth task was accepted")


def test_product_partition_capture_matches_task_topology_without_task_creation() -> None:
    armature = _armature()
    task = _task(armature)
    legacy_fingerprint, legacy_snapshots = topology.prepare_static_inputs_for_task(task)
    legacy = topology.build_mc2_topology_spec(
        task,
        static_input_fingerprint=legacy_fingerprint,
        static_input_snapshots=legacy_snapshots,
    )
    request = product_authoring.make_mc2_bone_cloth_product_request(
        list(task.sources),
        profile=task.profile,
        setup_options=task.setup_options,
        task_parameters=task.task_parameters,
    )
    partition = request.plan.active_partitions[0]
    product_fingerprint, product_snapshots = (
        topology.prepare_static_inputs_for_partition(partition)
    )
    product = topology.build_mc2_partition_topology_spec(
        partition,
        static_input_fingerprint=product_fingerprint,
        static_input_snapshots=product_snapshots,
    )
    assert product.task_id == partition.stable_id
    assert product.particle_count == legacy.particle_count == 9
    assert product.connection_mode == legacy.connection_mode
    assert product.connection_model == legacy.connection_model == "hotools_product"
    assert product.bone_connection.lines == legacy.bone_connection.lines
    assert product.bone_connection.triangles == legacy.bone_connection.triangles
    assert product.bone_connection.root_indices == legacy.bone_connection.root_indices
    assert product_fingerprint.geometry == legacy_fingerprint.geometry
    assert product_fingerprint.surface == legacy_fingerprint.surface

    legacy_static = static_build.build_mc2_bone_cloth_static_for_task(
        task,
        legacy,
        raw_snapshots=legacy_snapshots,
    )
    product_static = static_build.build_mc2_bone_static_for_partition(
        partition,
        product,
        raw_snapshots=product_snapshots,
    )
    assert product_static.final_proxy.vertex_identities == (
        legacy_static.final_proxy.vertex_identities
    )
    assert product_static.final_proxy.edges == legacy_static.final_proxy.edges
    assert product_static.final_proxy.triangles == legacy_static.final_proxy.triangles
    np.testing.assert_allclose(
        product_static.final_proxy.local_positions,
        legacy_static.final_proxy.local_positions,
        rtol=0.0,
        atol=0.0,
    )
    np.testing.assert_allclose(
        product_static.baseline.depths,
        legacy_static.baseline.depths,
        rtol=0.0,
        atol=0.0,
    )
    assert product_static.distance.distance_ranges == legacy_static.distance.distance_ranges
    assert product_static.distance.distance_targets == legacy_static.distance.distance_targets
    np.testing.assert_allclose(
        product_static.distance.distance_rest_signed,
        legacy_static.distance.distance_rest_signed,
        rtol=0.0,
        atol=0.0,
    )
    assert product_static.bending.bending_quads == legacy_static.bending.bending_quads
    np.testing.assert_allclose(
        product_static.bending.bending_rest_angle_or_volume,
        legacy_static.bending.bending_rest_angle_or_volume,
        rtol=0.0,
        atol=0.0,
    )
    fragment = bone_fragment.build_mc2_bone_static_fragment(
        partition,
        product_fingerprint,
        product,
        product_snapshots,
    )
    draft = domain_collect.build_mc2_domain_draft(request.plan)
    compiled = domain_compile.compile_mc2_domain_draft(draft, (fragment,))
    assert isinstance(compiled, domain_compile.MC2CompiledDomainV1)
    assert compiled.program.setup_type == "bone_cloth"
    assert compiled.program.partition_ids == (partition.stable_id,)
    assert compiled.program.output_targets[0].space_kind == "bone_pose"
    assert compiled.program.output_targets[0].target_id == fragment.output_target_id
    assert compiled.program.particle_count == 9
    assert compiled.program.particle_source_element.tolist() == list(range(9))
    assert {
        table.kind for table in compiled.program.constraint_tables
    } == {"distance", "tether", "bending"}
    assert compiled.parameters.layout_signature == compiled.program.layout_signature
    owner = domain_owner.MC2FusedCPUOwnerV1(cpu_kernel.MC2NativeCPUKernelV1())
    try:
        created = owner.sync_fragments(
            draft,
            (fragment,),
            fragment_cache_revision=1,
            fragment_builds=1,
        )
        reused = owner.sync_fragments(
            draft,
            (fragment,),
            fragment_cache_revision=1,
            fragment_cache_hits=1,
        )
        assert created.action == "created"
        assert reused.action == "reused"
        assert owner.compiled.program.setup_type == "bone_cloth"
        assert owner.inspect()["schema"] == "mc2_fused_cpu_owner_v1"
    finally:
        owner.dispose()


def test_bone_spring_partition_uses_the_same_domain_owner() -> None:
    armature = _armature()
    source_task = _task(armature)
    request = product_authoring.make_mc2_bone_spring_product_request(
        list(source_task.sources),
        profile=source_task.profile,
        task_parameters=source_task.task_parameters,
    )
    partition = request.plan.active_partitions[0]
    fingerprint, snapshots = topology.prepare_static_inputs_for_partition(partition)
    product_topology = topology.build_mc2_partition_topology_spec(
        partition,
        static_input_fingerprint=fingerprint,
        static_input_snapshots=snapshots,
    )
    fragment = bone_fragment.build_mc2_bone_static_fragment(
        partition,
        fingerprint,
        product_topology,
        snapshots,
    )
    draft = domain_collect.build_mc2_domain_draft(request.plan)
    compiled = domain_compile.compile_mc2_domain_draft(draft, (fragment,))
    assert compiled.program.setup_type == "bone_spring"
    assert compiled.program.required_capabilities[0] == "bone_spring"
    assert compiled.program.output_targets[0].space_kind == "bone_pose"

    owner = domain_owner.MC2FusedCPUOwnerV1(cpu_kernel.MC2NativeCPUKernelV1())
    try:
        report = owner.sync_fragments(draft, (fragment,), fragment_builds=1)
        assert report.action == "created"
        assert owner.compiled.program.domain_signature == compiled.program.domain_signature
        assert owner.compiled.program.setup_type == "bone_spring"
    finally:
        owner.dispose()


def test_same_armature_bone_cloth_partitions_compile_into_one_domain() -> None:
    armature = _armature()
    request = product_authoring.make_mc2_bone_cloth_product_request(
        [(armature, "A0"), (armature, "B0")],
        setup_options=parameters.make_mc2_setup_options(
            "bone_cloth",
            connection_mode=0,
        ),
    )
    assert len(request.plan.active_partitions) == 2
    fragments = []
    for partition in request.plan.active_partitions:
        fingerprint, snapshots = topology.prepare_static_inputs_for_partition(partition)
        product_topology = topology.build_mc2_partition_topology_spec(
            partition,
            static_input_fingerprint=fingerprint,
            static_input_snapshots=snapshots,
        )
        fragments.append(bone_fragment.build_mc2_bone_static_fragment(
            partition,
            fingerprint,
            product_topology,
            snapshots,
        ))

    draft = domain_collect.build_mc2_domain_draft(request.plan)
    compiled = domain_compile.compile_mc2_domain_draft(draft, tuple(fragments))
    assert compiled.program.partition_count == 2
    assert compiled.program.particle_count == 4
    assert compiled.program.partition_ids == draft.partition_ids
    assert len({target.target_id for target in compiled.program.output_targets}) == 2

    frame_inputs = []
    for fragment in fragments:
        particle_count = fragment.final_proxy.vertex_count
        frame_inputs.append(frame_state.make_mc2_frame_input(
            task_id=fragment.partition_id,
            topology_signature=fragment.topology.topology_signature,
            frame=12,
            generation=3,
            world_positions=fragment.final_proxy.local_positions,
            world_rotations_xyzw=None,
            raw_pose_matrices=np.tile(
                np.eye(3, dtype=np.float32),
                (particle_count, 1, 1),
            ),
            source_world_linear=np.eye(3, dtype=np.float32),
            center_frame_pose=center_state.MC2CenterFramePoseSpec(
                frame=12,
                generation=3,
                component_identity=f"object:{armature.as_pointer()}",
                component_world_position=(0.0, 0.0, 0.0),
                component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
                component_world_scale=(1.0, 1.0, 1.0),
            ),
        ))
    packet, frame_snapshots = product_bone_frame.compile_mc2_bone_product_frame(
        compiled,
        frame_inputs,
    )
    assert packet.frame == 12 and packet.generation == 3
    assert packet.animated_base_world_positions.shape == (4, 3)
    assert packet.animated_base_world_rotations.shape == (4, 4)
    assert len(frame_snapshots) == 2
    np.testing.assert_allclose(
        np.linalg.norm(packet.animated_base_world_rotations, axis=1),
        np.ones(4),
        rtol=1.0e-5,
        atol=1.0e-6,
    )

    owner = domain_owner.MC2FusedCPUOwnerV1(cpu_kernel.MC2NativeCPUKernelV1())
    try:
        report = owner.sync_fragments(
            draft,
            tuple(fragments),
            fragment_cache_revision=1,
            fragment_builds=2,
        )
        assert report.action == "created"
        assert tuple(owner.inspect()["partition_ids"]) == draft.partition_ids
    finally:
        owner.dispose()


def test_bone_product_collection_and_fragment_cache_are_transactional() -> None:
    armature = _armature()
    request = product_authoring.make_mc2_bone_cloth_product_request(
        [(armature, "A0"), (armature, "B0")],
        setup_options=parameters.make_mc2_setup_options(
            "bone_cloth",
            connection_mode=0,
        ),
    )
    collection = product_bone_collect.collect_mc2_bone_product_plan(
        object(),
        request.plan,
    )
    assert collection.draft.partition_ids == tuple(
        value.partition.stable_id for value in collection.static_inputs
    )
    assert collection.armature is armature
    assert collection.armature_pointer == armature.as_pointer()
    assert len(collection.static_inputs) == 2

    cache = bone_fragment_cache.MC2BoneFragmentCacheV1()
    first = cache.stage(collection.static_inputs)
    assert first.hit_count == 0 and first.build_count == 2
    assert cache.inspect()["entry_count"] == 0
    cache.commit(first)
    assert cache.revision == 1
    assert cache.inspect()["partition_ids"] == list(collection.draft.partition_ids)

    second = cache.stage(collection.static_inputs)
    assert second.hit_count == 2 and second.build_count == 0
    assert second.fragments == first.fragments
    cache.commit(second)
    assert cache.revision == 2

    build_count = 0

    def fail_second(partition, fingerprint, product_topology, snapshots):
        nonlocal build_count
        build_count += 1
        if build_count == 2:
            raise RuntimeError("injected Bone fragment failure")
        return bone_fragment.build_mc2_bone_static_fragment(
            partition,
            fingerprint,
            product_topology,
            snapshots,
        )

    failing_cache = bone_fragment_cache.MC2BoneFragmentCacheV1(fail_second)
    try:
        failing_cache.stage(collection.static_inputs)
    except RuntimeError as exc:
        assert "injected Bone fragment failure" in str(exc)
    else:
        raise AssertionError("Bone fragment stage unexpectedly succeeded")
    assert failing_cache.revision == 0
    assert failing_cache.inspect()["entry_count"] == 0


TESTS = (
    (
        "multi-chain product topology and static",
        test_product_task_builds_multi_chain_topology_and_static_bundle,
    ),
    ("multi-armature task rejection", test_product_task_rejects_sources_from_multiple_armatures),
    (
        "partition capture matches task topology",
        test_product_partition_capture_matches_task_topology_without_task_creation,
    ),
    (
        "BoneSpring partition uses unified owner",
        test_bone_spring_partition_uses_the_same_domain_owner,
    ),
    (
        "same Armature partitions compile into one domain",
        test_same_armature_bone_cloth_partitions_compile_into_one_domain,
    ),
    (
        "Bone product collection and fragment cache are transactional",
        test_bone_product_collection_and_fragment_cache_are_transactional,
    ),
)


def main() -> None:
    for name, test in TESTS:
        test()
        print(f"[PASS] {name}")
    print(f"{len(TESTS)}/{len(TESTS)} passed")


if __name__ == "__main__":
    main()
