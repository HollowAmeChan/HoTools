"""Pure-host contracts for the two BoneCloth object adapters."""

from __future__ import annotations

import importlib
import os
import sys
import types
from types import SimpleNamespace


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

object_spec = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.setups.bone_cloth.object_spec"
)
capabilities = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.setups.bone_cloth.capabilities"
)
declaration = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.declaration"
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

    def __iter__(self):
        return iter(self._values.values())


class _Bone:
    def __init__(self, name, children=(), *, group=1, collided=0):
        self.name = name
        self.children = list(children)
        self.hotools_collision = SimpleNamespace(
            primary_collision_group=group,
            collided_by_groups=collided,
        )


class _Armature(_Pointer):
    type = "ARMATURE"

    def __init__(self, pointer: int, name: str, bones):
        super().__init__(pointer)
        self.name = self.name_full = name
        collection = _Bones(bones)
        self.data = _Pointer(pointer + 1000)
        self.data.bones = collection
        self.pose = SimpleNamespace(bones=collection)


def _rig(pointer=101, *, group=3, collided=0b1010):
    tip = _Bone("Tip")
    root = _Bone("Root", (tip,))
    control = _Bone(
        "Control",
        (root,),
        group=group,
        collided=collided,
    )
    return _Armature(pointer, f"Rig{pointer}", (control, root, tip))


def test_panel_and_socket_objects_share_source_identity_but_keep_radius_ownership():
    armature = _rig()
    source = (armature, "Control")
    panel = object_spec.read_mc2_bone_cloth_panel_object(source)
    custom = object_spec.make_mc2_bone_cloth_custom_object(
        source,
        primary_collision_group=panel.explicit_properties.primary_collision_group,
        collided_by_groups=panel.explicit_properties.collided_by_groups,
    )
    assert panel.source_identity == custom.source_identity
    assert panel.signature != custom.signature
    assert panel.property_origin == "panel"
    assert custom.property_origin == "socket"
    assert (
        panel.explicit_properties.particle_radius_source
        == object_spec.MC2_BONE_PARTICLE_RADIUS_COLLISION
    )
    assert (
        custom.explicit_properties.particle_radius_source
        == object_spec.MC2_BONE_PARTICLE_RADIUS_PROFILE
    )
    assert tuple(
        chain.bone_names for chain in panel.partition_source.chains
    ) == (("Root", "Tip"),)


def test_custom_object_does_not_read_panel_properties():
    armature = _rig(group=9, collided=0xFFFF)
    custom = object_spec.make_mc2_bone_cloth_custom_object(
        (armature, "Control")
    )
    properties = custom.explicit_properties
    assert properties.primary_collision_group == 1
    assert properties.collided_by_groups == 0
    assert properties.self_collision_groups == 1
    assert properties.particle_radius_source == "profile_curve"


def test_object_lists_apply_one_complete_socket_property_set():
    first = _rig(201)
    second = _rig(202)
    objects = object_spec.make_mc2_bone_cloth_custom_objects(
        [(first, "Control"), (second, "Control")],
        primary_collision_group=4,
        collided_by_groups=5,
    )
    assert len(objects) == 2
    assert tuple(
        value.explicit_properties.self_collision_groups for value in objects
    ) == (13, 13)


def test_invalid_panel_source_and_collision_groups_fail_explicitly():
    armature = _rig(301)
    try:
        object_spec.read_mc2_bone_cloth_panel_object((armature, "Missing"))
    except ValueError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("missing panel Bone was accepted")

    for values in (
        {"primary_collision_group": 0},
        {"primary_collision_group": 17},
        {"collided_by_groups": -1},
        {"collided_by_groups": 0x10000},
    ):
        try:
            object_spec.make_mc2_bone_cloth_custom_object(
                (armature, "Control"),
                **values,
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid BoneCloth properties accepted: {values!r}")


def test_bone_collision_radius_adapter_declares_exact_conversion_boundary():
    adapter = capabilities.MC2_BONE_CLOTH_BONE_COLLISION_ADAPTER
    assert declaration.MC2_SOLVER_DECLARATION["capability_adapters"] == [adapter]
    assert adapter["activation"] == "panel_object_only"
    assert adapter["consumes"]["radius"] == {
        "target": "particle.radius",
        "conversion": "absolute_blender_units",
        "terminal_policy": "inherit_last_real_bone",
        "update_policy": "static_fragment_rebuild",
    }
    assert adapter["not_consumed_as_particle_radius"] == (
        "collision_type",
        "length",
        "offset",
    )
    assert adapter["custom_object_fallback"] == (
        "MC2ParticleProfileSpec.radius_curve"
    )


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"MC2 Bone object spec: {len(tests)} passed")
