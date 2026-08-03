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

from Exporter.ConstraintIR import SCHEMA, SCHEMA_VERSION
from Exporter.ConstraintIRExporter import ConstraintIRExporter


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
        hotools_boneprops=SimpleNamespace(generateMCH=mch, auxBone=aux),
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
        [SimpleNamespace(name=item.name, constraints=[]) for item in data_bones]
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


def test_neutral_ir_contract():
    armature = build_armature_fixture()
    data = ConstraintIRExporter.export_to_dict(
        armature,
        export_time="2026-08-03T00:00:00Z",
    )

    assert list(data) == [
        "schema",
        "schemaVersion",
        "exportTime",
        "armatureName",
        "mchEnabledBones",
        "mchBindings",
        "auxBones",
        "knownConstraints",
        "unknownConstraints",
    ]
    assert data["schema"] == SCHEMA == "hotools.rig-constraint-ir"
    assert data["schemaVersion"] == SCHEMA_VERSION == 2
    assert data["armatureName"] == "HeroRig"
    assert data["mchEnabledBones"] == ["UpperArm"]

    binding = data["mchBindings"][0]
    assert binding["sourceBone"] == "UpperArm"
    assert binding["mchBone"] == "SidecarBone"
    assert binding["constraint"]["constraintType"] == "CHILD_OF"
    assert binding["constraint"]["parameters"]["inverse_matrix"][0] == [
        1.0,
        0.0,
        0.0,
        0.0,
    ]
    assert binding["constraint"]["parameters"]["use_scale_y"] is False
    assert "active" not in binding["constraint"]["parameters"]
    assert "set_inverse_pending" not in binding["constraint"]["parameters"]

    aux_map = {item["boneName"]: item for item in data["auxBones"]}
    assert set(aux_map) == {"Fan01", "FanPin", "SidecarBone", "Twist01"}
    assert aux_map["SidecarBone"]["auxType"] == "MCH"
    assert aux_map["SidecarBone"]["sourceBones"] == ["UpperArm"]
    assert aux_map["SidecarBone"]["constraintNames"] == ["HoTools_MCH_Parent"]
    assert aux_map["SidecarBone"]["constraints"] == []
    assert aux_map["Fan01"]["sourceBones"] == ["UpperArm", "Forearm"]
    assert aux_map["Fan01"]["involvedBones"] == [
        "UpperArm",
        "Forearm",
        "Fan01",
        "FanPin",
    ]
    assert aux_map["FanPin"]["involvedBones"] == aux_map["Fan01"]["involvedBones"]

    twist = aux_map["Twist01"]
    assert twist["constraintNames"] == [
        "HoTools_TWIST_CopyRotation",
        "HoTools_TWIST_StretchTo",
    ]
    assert twist["involvedBones"] == ["UpperArm", "Twist01", "Forearm"]
    assert [item["constraintType"] for item in twist["constraints"]] == [
        "COPY_ROTATION",
        "STRETCH_TO",
    ]
    assert [item["stackIndex"] for item in twist["constraints"]] == [0, 2]
    assert twist["constraints"][0]["parameters"]["use_x"] is True
    assert twist["constraints"][0]["parameters"]["owner_space"] == "LOCAL"
    assert twist["constraints"][0]["parameters"]["target_space"] == "LOCAL_OWNER_ORIENT"
    assert twist["constraints"][1]["parameters"]["rest_length"] == 1.75
    assert twist["constraints"][1]["parameters"]["owner_space"] == "LOCAL_WITH_PARENT"
    assert twist["constraints"][1]["parameters"]["target_space"] == "WORLD"

    assert len(data["unknownConstraints"]) == 1
    unknown = data["unknownConstraints"][0]
    assert unknown["ownerBone"] == "Twist01"
    assert unknown["constraint"]["targetObjectName"] == "OtherRig"
    assert unknown["constraint"]["targetBoneName"] == "OtherBone"
    assert unknown["reason"] == "辅助骨约束未匹配 HoTools 生成规则"
    assert [
        (item["relationType"], item["auxType"])
        for item in data["knownConstraints"]
    ] == [
        ("AUX_CONSTRAINT", "FAN"),
        ("MCH_BINDING", "MCH"),
        ("AUX_CONSTRAINT", "TWIST"),
        ("AUX_CONSTRAINT", "TWIST"),
    ]

    encoded = json.dumps(data)
    assert '"type": "Rotation"' not in encoded
    assert '"type": "Child"' not in encoded
    assert '"semantic"' not in encoded
    assert '"targetPath"' not in encoded


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

    assert ConstraintIRExporter._constraint_parameters(item) == {
        "raw_new_option": "FUTURE_MODE"
    }
    assert ConstraintIRExporter._constraint_references(item) == {
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
    assert ConstraintIRExporter._custom_properties(item) == {
        "authorTag": "keep-me",
        "nested": {"mode": "raw", "weight": 0.5},
    }


def test_known_and_unknown_scan_is_complete_and_deduplicated():
    armature = build_armature_fixture()
    armature.pose.bones.get("Forearm").constraints.append(
        constraint(
            armature,
            "CHILD_OF",
            "HoTools_MCH_Parent",
            "UpperArm",
        )
    )
    armature.pose.bones.get("FanPin").constraints.append(
        constraint(
            armature,
            "COPY_ROTATION",
            "User_Copy_Rotation",
            "Forearm",
        )
    )
    # A registered but malformed MCH constraint cannot fall through to the
    # ordinary Aux claim path.
    sidecar_aux = armature.data.bones.get(
        "SidecarBone"
    ).hotools_boneprops.auxBone
    sidecar_aux.constraintNames.append(SimpleNamespace(name="Broken_MCH_Parent"))
    armature.pose.bones.get("SidecarBone").constraints.append(
        constraint(
            armature,
            "CHILD_OF",
            "Broken_MCH_Parent",
            "Forearm",
        )
    )

    data = ConstraintIRExporter.export_to_dict(armature, export_time="test")
    known_keys = {
        (item["ownerBone"], item["constraint"]["stackIndex"])
        for item in data["knownConstraints"]
    }
    unknown_keys = {
        (item["ownerBone"], item["constraint"]["stackIndex"])
        for item in data["unknownConstraints"]
    }
    all_keys = {
        (pose_bone.name, stack_index)
        for pose_bone in armature.pose.bones
        for stack_index, _constraint in enumerate(pose_bone.constraints)
    }

    assert known_keys.isdisjoint(unknown_keys)
    assert len(known_keys) == len(data["knownConstraints"])
    assert len(unknown_keys) == len(data["unknownConstraints"])
    assert known_keys | unknown_keys == all_keys
    assert ("Forearm", 0) in unknown_keys
    assert ("FanPin", 0) in unknown_keys
    assert ("SidecarBone", 1) in unknown_keys
    assert not any(
        item["ownerBone"] == "SidecarBone"
        and item["constraint"]["stackIndex"] == 1
        for item in data["knownConstraints"]
    )


def test_mch_requires_one_exact_source_relation():
    armature = build_armature_fixture()
    sidecar_aux = armature.data.bones.get(
        "SidecarBone"
    ).hotools_boneprops.auxBone
    sidecar_aux.sourceBones.append(SimpleNamespace(name="Forearm"))

    data = ConstraintIRExporter.export_to_dict(armature, export_time="test")
    assert data["mchBindings"] == []
    assert any(
        item["ownerBone"] == "SidecarBone"
        and item["constraint"]["stackIndex"] == 0
        for item in data["unknownConstraints"]
    )
    assert not any(
        item["ownerBone"] == "SidecarBone"
        for item in data["knownConstraints"]
    )


def test_non_armature_is_rejected():
    try:
        ConstraintIRExporter.build_ir(SimpleNamespace(type="MESH"))
    except ValueError:
        return
    raise AssertionError("non-armature input must be rejected")


if __name__ == "__main__":
    test_neutral_ir_contract()
    test_blender_rna_fields_and_additional_references_are_preserved()
    test_known_and_unknown_scan_is_complete_and_deduplicated()
    test_mch_requires_one_exact_source_relation()
    test_non_armature_is_rejected()
    print("constraint IR tests passed")
