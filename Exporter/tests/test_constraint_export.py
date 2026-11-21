"""Pure-Python contract tests for the neutral rig constraint IR."""

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace


EXPORTER_DIR = Path(__file__).resolve().parents[1]
if "Exporter" not in sys.modules:
    package = types.ModuleType("Exporter")
    package.__path__ = [str(EXPORTER_DIR)]
    sys.modules["Exporter"] = package

sys.path.insert(0, str(EXPORTER_DIR.parent))
from RigConstraints.model import SCHEMA, SCHEMA_VERSION
from RigConstraints.source import (capture_armature, capture_constraint, capture_parameters,
                                   capture_references, capture_custom_properties)
from RigConstraints.semantics import translate
# Pure-Python fixtures have no Blender runtime; version is deliberately absent.
import RigConstraints.source.reader as source_reader
source_reader._version = lambda: ""


class BoneCollection(list):
    def get(self, name):
        return next((bone for bone in self if bone.name == name), None)


class FakeConstraint(SimpleNamespace):
    def __init__(self, *, custom_properties=None, **kwargs):
        super().__init__(**kwargs)
        self._custom_properties = custom_properties or {}

    def items(self):
        return self._custom_properties.items()


class FakeIDPropertyGroup:
    """Matches Blender's dict-like IDPropertyGroup without being a Mapping."""

    def __init__(self, values):
        self.values = values

    def to_dict(self):
        return self.values

    def __iter__(self):
        return iter(self.values)


def bone(name, *, mch=False, aux_type=None, sources=(), constraint_names=()):
    aux = SimpleNamespace(
        isAuxBone=aux_type is not None,
        auxType=aux_type or "NONE",
        sourceBones=[SimpleNamespace(name=source) for source in sources],
        constraintNames=[SimpleNamespace(name=value) for value in constraint_names],
    )
    return SimpleNamespace(
        name=name,
        hotools_boneprops=SimpleNamespace(generateMCH=mch, auxBone=aux, constraintGroups=[]),
    )


def constraint(armature, constraint_type, name, target_bone, **parameters):
    values = {
        "name": name,
        "type": constraint_type,
        "target": armature,
        "subtarget": target_bone,
        "influence": 1.0,
        "mute": False,
        "active": True,
        "set_inverse_pending": False,
    }
    values.update(parameters)
    return FakeConstraint(**values)


def build_armature_fixture():
    data_bones = BoneCollection(
        [
            bone("FanPin", aux_type="FAN", sources=("UpperArm", "Forearm")),
            bone("UpperArm", mch=True),
            bone(
                "Twist01",
                aux_type="TWIST",
                sources=("UpperArm",),
                constraint_names=(
                    "HoTools_TWIST_CopyRotation",
                    "HoTools_TWIST_StretchTo",
                ),
            ),
            bone(
                "SidecarBone",
                aux_type="MCH",
                sources=("UpperArm",),
                constraint_names=("HoTools_MCH_Parent",),
            ),
            bone("Forearm"),
            bone(
                "Fan01",
                aux_type="FAN",
                sources=("UpperArm", "Forearm"),
                constraint_names=("HoTools_FAN_CopyRotation",),
            ),
        ]
    )
    pose_bones = BoneCollection(
        [SimpleNamespace(name=item.name, bone=item, constraints=[]) for item in data_bones]
    )
    armature = SimpleNamespace(
        type="ARMATURE",
        name="HeroRig",
        data=SimpleNamespace(bones=data_bones),
        pose=SimpleNamespace(bones=pose_bones),
    )

    pose_bones.get("SidecarBone").constraints.append(
        constraint(
            armature,
            "CHILD_OF",
            "HoTools_MCH_Parent",
            "UpperArm",
            inverse_matrix=(
                (1.0, 0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0, 0.0),
                (0.0, 0.0, 1.0, 0.0),
                (0.0, 0.0, 0.0, 1.0),
            ),
            use_location_x=True,
            use_location_y=True,
            use_location_z=True,
            use_rotation_x=True,
            use_rotation_y=True,
            use_rotation_z=True,
            use_scale_x=False,
            use_scale_y=False,
            use_scale_z=False,
        )
    )
    pose_bones.get("Fan01").constraints.append(
        constraint(
            armature,
            "COPY_ROTATION",
            "HoTools_FAN_CopyRotation",
            "FanPin",
            influence=0.25,
            owner_space="WORLD",
            target_space="WORLD",
            mix_mode="REPLACE",
            use_x=True,
            use_y=True,
            use_z=True,
            invert_x=False,
            invert_y=False,
            invert_z=False,
        )
    )
    external_constraint = FakeConstraint(
        name="External",
        type="COPY_ROTATION",
        target=SimpleNamespace(name="OtherRig"),
        subtarget="OtherBone",
        influence=1.0,
    )
    pose_bones.get("Twist01").constraints.extend(
        [
            constraint(
                armature,
                "COPY_ROTATION",
                "HoTools_TWIST_CopyRotation",
                "Forearm",
                influence=0.6,
                owner_space="LOCAL",
                target_space="LOCAL_OWNER_ORIENT",
                mix_mode="REPLACE",
                use_x=True,
                use_y=True,
                use_z=True,
                invert_x=False,
                invert_y=False,
                invert_z=False,
            ),
            external_constraint,
            constraint(
                armature,
                "STRETCH_TO",
                "HoTools_TWIST_StretchTo",
                "Forearm",
                owner_space="LOCAL_WITH_PARENT",
                target_space="WORLD",
                head_tail=0.2,
                rest_length=1.75,
                volume="NO_VOLUME",
                keep_axis="SWING_Y",
                bulge=1.0,
                use_bulge_min=False,
                use_bulge_max=False,
                bulge_min=0.0,
                bulge_max=0.0,
                bulge_smooth=0.0,
            ),
        ]
    )
    return armature


def test_source_snapshot_retains_raw_facts_without_invented_ownership():
    armature = build_armature_fixture()
    before = [(p.name, [(c.name, c.type) for c in p.constraints]) for p in armature.pose.bones]
    data = capture_armature(armature)
    assert data["schema"] == SCHEMA == "hotools.rig-constraint-ir"
    assert data["schemaVersion"] == SCHEMA_VERSION == 4
    assert data["captureStage"] == "AUTHORING" and data["armatureName"] == "HeroRig"
    assert data["mchPlans"] == ["UpperArm"]
    assert not data["declarations"]  # Old aux names are data, never declarations.
    rows = {(s["ownerBone"], s["constraint"]["stackIndex"]): s["constraint"] for s in data["sources"]}
    assert len(rows) == len(data["sources"]) == 5
    parent = rows[("SidecarBone", 0)]
    assert parent["constraintType"] == "CHILD_OF" and parent["targetBoneName"] == "UpperArm"
    assert parent["parameters"]["inverse_matrix"][0] == [1.0, 0.0, 0.0, 0.0]
    assert parent["parameters"]["use_scale_y"] is False
    assert "active" not in parent["parameters"] and "set_inverse_pending" not in parent["parameters"]
    rotation = rows[("Twist01", 0)]
    assert rotation["parameters"]["owner_space"] == "LOCAL"
    assert rotation["parameters"]["target_space"] == "LOCAL_OWNER_ORIENT"
    assert rows[("Twist01", 2)]["parameters"]["rest_length"] == 1.75
    assert rows[("Twist01", 1)]["targetObjectName"] == "OtherRig"
    encoded = json.dumps(data)
    assert '"targetPath"' not in encoded and '"knownConstraints"' not in encoded
    assert before == [(p.name, [(c.name, c.type) for c in p.constraints]) for p in armature.pose.bones]
    translated = translate(data)
    assert not translated["semantics"]
    assert len(translated["diagnostics"]) == 5


def test_blender_rna_fields_and_additional_references_are_preserved():
    object_rna = SimpleNamespace(identifier="Object", properties=[])
    space_object = SimpleNamespace(
        name="SpaceRig",
        name_full="SpaceRig",
        bl_rna=object_rna,
    )
    target_object = SimpleNamespace(
        name="TargetRig",
        name_full="TargetRig",
        bl_rna=object_rna,
    )
    target_item_properties = [
        SimpleNamespace(identifier="target", is_readonly=False, type="POINTER"),
        SimpleNamespace(identifier="subtarget", is_readonly=False, type="STRING"),
        SimpleNamespace(identifier="weight", is_readonly=False, type="FLOAT"),
    ]
    target_item = SimpleNamespace(
        target=target_object,
        subtarget="Spine",
        weight=0.75,
        bl_rna=SimpleNamespace(
            identifier="ArmatureConstraintTarget",
            properties=target_item_properties,
        ),
    )
    properties = [
        SimpleNamespace(identifier="raw_new_option", is_readonly=False, type="ENUM"),
        SimpleNamespace(identifier="target", is_readonly=False, type="POINTER"),
        SimpleNamespace(identifier="space_object", is_readonly=False, type="POINTER"),
        SimpleNamespace(identifier="targets", is_readonly=True, type="COLLECTION"),
        SimpleNamespace(identifier="is_valid", is_readonly=True, type="BOOLEAN"),
    ]
    item = FakeConstraint(
        type="COPY_ROTATION",
        raw_new_option="FUTURE_MODE",
        target=target_object,
        space_object=space_object,
        targets=[target_item],
        is_valid=True,
        bl_rna=SimpleNamespace(properties=properties),
        custom_properties={
            "authorTag": "keep-me",
            "nested": FakeIDPropertyGroup({"mode": "raw", "weight": 0.5}),
        },
    )

    assert capture_parameters(item) == {
        "raw_new_option": "FUTURE_MODE"
    }
    assert capture_references(item) == {
        "space_object": {"name": "SpaceRig", "rnaType": "Object"},
        "targets": [
            {
                "properties": {
                    "subtarget": "Spine",
                    "target": {"name": "TargetRig", "rnaType": "Object"},
                    "weight": 0.75,
                },
                "rnaType": "ArmatureConstraintTarget",
            }
        ],
    }
    assert capture_custom_properties(item) == {
        "authorTag": "keep-me",
        "nested": {"mode": "raw", "weight": 0.5},
    }


def test_raw_capture_preserves_every_stack_entry_once():
    armature = build_armature_fixture()
    armature.pose.bones.get("Forearm").constraints.append(constraint(armature, "CHILD_OF", "UnregisteredParent", "UpperArm"))
    armature.pose.bones.get("FanPin").constraints.append(constraint(armature, "COPY_ROTATION", "User_Copy_Rotation", "Forearm"))
    data = capture_armature(armature)
    keys = [(s["ownerBone"], s["constraint"]["stackIndex"]) for s in data["sources"]]
    expected = {(pose.name, i) for pose in armature.pose.bones for i, _ in enumerate(pose.constraints)}
    assert len(keys) == len(set(keys)) and set(keys) == expected
    assert not data["declarations"]
    assert capture_constraint(armature.pose.bones.get("FanPin").constraints[0], armature, 7)["stackIndex"] == 7


def test_non_armature_and_uninitialized_pose_are_rejected():
    for item in (SimpleNamespace(type="MESH"), SimpleNamespace(type="ARMATURE", name="Empty", pose=None)):
        try:
            capture_armature(item)
        except ValueError:
            continue
        raise AssertionError("invalid armature input must be rejected")


if __name__ == "__main__":
    test_source_snapshot_retains_raw_facts_without_invented_ownership()
    test_blender_rna_fields_and_additional_references_are_preserved()
    test_raw_capture_preserves_every_stack_entry_once()
    test_non_armature_and_uninitialized_pose_are_rejected()
    print("CONSTRAINT_SOURCE_UNIT_OK")
