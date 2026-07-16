"""Production-contract tests for multi-chain HoTools BoneCloth tasks."""

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
    def __init__(self, bones, pointer=1001):
        self.data = Data(bones, pointer + 1)
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


TESTS = (
    (
        "multi-chain product topology and static",
        test_product_task_builds_multi_chain_topology_and_static_bundle,
    ),
    ("multi-armature task rejection", test_product_task_rejects_sources_from_multiple_armatures),
)


def main() -> None:
    for name, test in TESTS:
        test()
        print(f"[PASS] {name}")
    print(f"{len(TESTS)}/{len(TESTS)} passed")


if __name__ == "__main__":
    main()
