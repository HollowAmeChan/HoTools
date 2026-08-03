import sys
import tempfile
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup
from mathutils import Matrix


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from Exporter.FbxExporter import FBXExporter
from Exporter.ConstraintIRExporter import ConstraintIRExporter
from BoneTools.auxBone.boneTwist import TwistBoneCore
from BoneTools.boneProperty import _register_aux_constraint, _replace_aux_constraints
from BoneTools.boneOperators import OP_ForceClearBoneRotation
from BoneTools.previewUtils import AuxPreviewUtils
from Utils import bone_utils
from io_scene_fbx import parse_fbx


class TestBoneRef(PropertyGroup):
    name: StringProperty(default="")


class TestAuxInfo(PropertyGroup):
    isAuxBone: BoolProperty(default=False)
    auxType: StringProperty(default="NONE")
    sourceBones: CollectionProperty(type=TestBoneRef)
    constraintNames: CollectionProperty(type=TestBoneRef)


class TestBoneProps(PropertyGroup):
    generateMCH: BoolProperty(default=False)
    auxBone: PointerProperty(type=TestAuxInfo)


def assert_matrix_close(actual, expected, tolerance=1e-5):
    for row in range(4):
        for column in range(4):
            assert abs(actual[row][column] - expected[row][column]) < tolerance


def assert_identity_local_rotation(bone, tolerance=1e-5):
    assert bone.parent is not None
    relative = bone.parent.matrix.inverted_safe() @ bone.matrix
    assert relative.to_quaternion().angle < tolerance


def read_fbx_local_rotations(filepath, bone_names):
    root, _version = parse_fbx.parse(str(filepath))
    objects = next(elem for elem in root.elems if elem.id == b"Objects")
    rotations = {}
    for model in objects.elems:
        if model.id != b"Model" or model.props[2] != b"LimbNode":
            continue
        name = model.props[1].split(b"\x00", 1)[0].decode("utf-8")
        if name not in bone_names:
            continue
        properties = next(
            elem for elem in model.elems if elem.id == b"Properties70"
        )
        rotation = next(
            elem
            for elem in properties.elems
            if elem.id == b"P" and elem.props[0] == b"Lcl Rotation"
        )
        rotations[name] = tuple(float(value) for value in rotation.props[-3:])
    return rotations


def read_fbx_bone_parents(filepath, bone_names):
    root, _version = parse_fbx.parse(str(filepath))
    objects = next(elem for elem in root.elems if elem.id == b"Objects")
    models = {
        model.props[0]: model.props[1].split(b"\x00", 1)[0].decode("utf-8")
        for model in objects.elems
        if model.id == b"Model"
    }
    connections = next(elem for elem in root.elems if elem.id == b"Connections")
    parent_ids = {
        connection.props[1]: connection.props[2]
        for connection in connections.elems
        if connection.id == b"C" and connection.props[0] == b"OO"
    }
    model_ids = {name: model_id for model_id, name in models.items()}
    return {
        name: models.get(parent_ids.get(model_ids[name]))
        for name in bone_names
    }


bpy.utils.register_class(TestBoneRef)
bpy.utils.register_class(TestAuxInfo)
bpy.utils.register_class(TestBoneProps)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=TestBoneProps)

data = bpy.data.armatures.new("FBXMCHLocalRotationData")
armature = bpy.data.objects.new("FBXMCHLocalRotation", data)
bpy.context.scene.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")

root = data.edit_bones.new("Root")
root.head = (0.0, 0.0, 0.0)
root.tail = (0.75, 1.0, 1.5)
root.roll = 0.37

first = data.edit_bones.new("First")
first.head = root.tail
first.tail = (2.0, 1.75, 1.1)
first.roll = -0.42
first.parent = root

second = data.edit_bones.new("Second")
second.head = first.tail
second.tail = (2.3, 0.8, 2.4)
second.roll = 0.61
second.parent = first

leaf = data.edit_bones.new("Leaf")
leaf.head = second.tail
leaf.tail = (2.7, 0.2, 3.0)
leaf.parent = second

original_matrices = {
    "First": first.matrix.copy(),
    "Second": second.matrix.copy(),
}
original_lengths = {
    "First": first.length,
    "Second": second.length,
}

bpy.ops.object.mode_set(mode="OBJECT")
data.bones["First"].hotools_boneprops.generateMCH = True
data.bones["Second"].hotools_boneprops.generateMCH = True
bpy.ops.object.mode_set(mode="EDIT")

name_map = FBXExporter.build_mch_and_clear(armature)
assert name_map == {"First": "MCH_First", "Second": "MCH_Second"}

first = data.edit_bones["First"]
second = data.edit_bones["Second"]
mch_first = data.edit_bones["MCH_First"]
mch_second = data.edit_bones["MCH_Second"]

# MCH bones preserve the source bind orientation before it is cleared.
assert_matrix_close(mch_first.matrix, original_matrices["First"])
assert_matrix_close(mch_second.matrix, original_matrices["Second"])

# Main bones keep their direct hierarchy and serialize zero local rotations.
assert first.parent.name == "Root"
assert second.parent.name == "First"
assert_identity_local_rotation(first)
assert_identity_local_rotation(second)
assert abs(first.length - original_lengths["First"]) < 1e-5
assert abs(second.length - original_lengths["Second"]) < 1e-5

# MCH bones are sidecars; original descendants stay on the main-bone chain.
assert mch_first.parent.name == "Root"
assert mch_second.parent.name == "First"
assert data.edit_bones["Leaf"].parent.name == "Second"

bpy.ops.object.mode_set(mode="OBJECT")
for bone_name in name_map:
    pose_bone = armature.pose.bones[bone_name]
    pose_bone.location = (1.0, 2.0, 3.0)
    pose_bone.rotation_mode = "XYZ"
    pose_bone.rotation_euler = (0.2, -0.3, 0.4)
    pose_bone.scale = (1.2, 0.8, 1.1)

assert FBXExporter.clear_pose_bone_transforms(armature, name_map) == 2
bpy.context.view_layer.update()
mch_bind_before_constraint = {
    bone_name: armature.pose.bones[bone_name].matrix.copy()
    for bone_name in name_map.values()
}
assert FBXExporter.add_mch_parent_constraints(armature, name_map) == 2
bpy.context.view_layer.update()
for bone_name, bind_matrix in mch_bind_before_constraint.items():
    assert_matrix_close(armature.pose.bones[bone_name].matrix, bind_matrix)

for source_name, mch_name in name_map.items():
    constraint = armature.pose.bones[mch_name].constraints[
        FBXExporter.MCH_PARENT_CONSTRAINT_NAME
    ]
    assert constraint.type == "CHILD_OF"
    assert constraint.target == armature
    assert constraint.subtarget == source_name
    assert abs(constraint.influence - 1.0) < 1e-6
    mch_aux = armature.data.bones[mch_name].hotools_boneprops.auxBone
    assert mch_aux.isAuxBone
    assert mch_aux.auxType == "MCH"
    assert [item.name for item in mch_aux.sourceBones] == [source_name]
    assert [item.name for item in mch_aux.constraintNames] == [
        FBXExporter.MCH_PARENT_CONSTRAINT_NAME
    ]

mch_before_follow = armature.pose.bones["MCH_First"].matrix.copy()
armature.pose.bones["First"].rotation_mode = "XYZ"
armature.pose.bones["First"].rotation_euler = (0.0, 0.0, 0.35)
bpy.context.view_layer.update()
mch_after_follow = armature.pose.bones["MCH_First"].matrix.copy()
assert any(
    abs(mch_after_follow[row][column] - mch_before_follow[row][column]) > 1e-5
    for row in range(4)
    for column in range(4)
)
assert FBXExporter.clear_pose_bone_transforms(armature, name_map) == 2
bpy.context.view_layer.update()

constraint_data = ConstraintIRExporter.export_to_dict(armature)
binding_map = {
    item["mchBone"]: item
    for item in constraint_data["mchBindings"]
}
assert binding_map["MCH_First"]["sourceBone"] == "First"
assert binding_map["MCH_Second"]["sourceBone"] == "Second"
assert binding_map["MCH_First"]["constraint"]["constraintType"] == "CHILD_OF"
assert binding_map["MCH_First"]["constraint"]["parameters"]["influence"] == 1.0
assert binding_map["MCH_First"]["constraint"]["parameters"]["use_scale_x"] is False
assert binding_map["MCH_First"]["constraint"]["parameters"]["use_rotation_y"] is True
assert "type" not in binding_map["MCH_First"]["constraint"]
aux_map = {item["boneName"]: item for item in constraint_data["auxBones"]}
assert set(aux_map) == {"MCH_First", "MCH_Second"}
for source_name, mch_name in name_map.items():
    assert aux_map[mch_name]["auxType"] == "MCH"
    assert aux_map[mch_name]["sourceBones"] == [source_name]
    assert aux_map[mch_name]["constraintNames"] == [
        FBXExporter.MCH_PARENT_CONSTRAINT_NAME
    ]
    assert aux_map[mch_name]["constraints"] == []
assert constraint_data["unknownConstraints"] == []
assert [item["relationType"] for item in constraint_data["knownConstraints"]] == [
    "MCH_BINDING",
    "MCH_BINDING",
]
assert {item["auxType"] for item in constraint_data["knownConstraints"]} == {"MCH"}

# RNA collections must preserve every target entry rather than serialize the
# bpy_prop_collection itself as an empty RNA struct.
armature_constraint = armature.pose.bones["Leaf"].constraints.new("ARMATURE")
armature_constraint.name = "RawArmatureTargets"
armature_constraint.mute = True
armature_target = armature_constraint.targets.new()
armature_target.target = armature
armature_target.subtarget = "First"
armature_target.weight = 0.4
reference_probe = ConstraintIRExporter.export_to_dict(armature)
raw_armature = next(
    item["constraint"]
    for item in reference_probe["unknownConstraints"]
    if item["ownerBone"] == "Leaf"
    and item["constraint"]["name"] == "RawArmatureTargets"
)
target_records = raw_armature["references"]["targets"]
assert len(target_records) == 1
assert target_records[0]["properties"]["subtarget"] == "First"
assert abs(target_records[0]["properties"]["weight"] - 0.4) < 1e-6
assert target_records[0]["properties"]["target"]["name"] == armature.name
armature.pose.bones["Leaf"].constraints.remove(armature_constraint)

for bone_name in name_map:
    assert_matrix_close(
        armature.pose.bones[bone_name].matrix_basis,
        Matrix.Identity(4),
    )
    assert_identity_local_rotation(armature.pose.bones[bone_name])

# Verify Blender's FBX axis correction/decomposition still writes zero rotations.
with tempfile.TemporaryDirectory(prefix="hotools_fbx_mch_") as temp_dir:
    fbx_path = Path(temp_dir) / "mch_local_rotation.fbx"
    assert bpy.ops.export_scene.fbx(
        filepath=str(fbx_path),
        use_selection=True,
        object_types={'ARMATURE'},
        add_leaf_bones=False,
        primary_bone_axis='Y',
        secondary_bone_axis='X',
        bake_anim=False,
        axis_forward='-Z',
        axis_up='Y',
    ) == {'FINISHED'}
    exported_rotations = read_fbx_local_rotations(
        fbx_path,
        {"First", "Second"},
    )
    assert exported_rotations.keys() == {"First", "Second"}
    for rotation in exported_rotations.values():
        assert all(abs(value) < 1e-4 for value in rotation), rotation

    exported_parents = read_fbx_bone_parents(
        fbx_path,
        {"Second", "Leaf", "MCH_First", "MCH_Second"},
    )
    assert exported_parents == {
        "Second": "First",
        "Leaf": "Second",
        "MCH_First": "Root",
        "MCH_Second": "First",
    }


# A preferred display-name collision must not delete or repurpose the user's bone.
# Re-running preprocessing must find the generated MCH by Aux properties and reuse it.
collision_data = bpy.data.armatures.new("MCHNameCollisionData")
collision_armature = bpy.data.objects.new("MCHNameCollision", collision_data)
bpy.context.scene.collection.objects.link(collision_armature)
bpy.ops.object.select_all(action="DESELECT")
bpy.context.view_layer.objects.active = collision_armature
collision_armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")

collision_root = collision_data.edit_bones.new("Root")
collision_root.head = (0.0, 0.0, 0.0)
collision_root.tail = (0.0, 1.0, 0.0)
collision_main = collision_data.edit_bones.new("Main")
collision_main.head = collision_root.tail
collision_main.tail = (0.8, 2.0, 0.4)
collision_main.parent = collision_root
user_named_bone = collision_data.edit_bones.new("MCH_Main")
user_named_bone.head = (2.0, 0.0, 0.0)
user_named_bone.tail = (2.0, 1.0, 0.0)
malformed_sidecar = collision_data.edit_bones.new("MalformedSidecar")
malformed_sidecar.head = (3.0, 0.0, 0.0)
malformed_sidecar.tail = (3.0, 1.0, 0.0)
bpy.ops.object.mode_set(mode="OBJECT")
collision_data.bones["Main"].hotools_boneprops.generateMCH = True
malformed_aux = collision_data.bones[
    "MalformedSidecar"
].hotools_boneprops.auxBone
malformed_aux.isAuxBone = True
malformed_aux.auxType = "MCH"
for source_name in ("Main", "Root"):
    source_ref = malformed_aux.sourceBones.add()
    source_ref.name = source_name

# A user-owned preferred name is a hard error. No MCH bone may be created
# before the caller fixes the collision.
try:
    FBXExporter.clear_armatures_bone_rotation(
        [collision_armature], [collision_armature], collision_armature
    )
except RuntimeError as error:
    assert "MCH_Main" in str(error)
else:
    raise AssertionError("MCH preprocessing must stop on a user bone-name collision")
assert collision_data.bones.get("MCH_Main") is not None
assert collision_data.bones.get("MalformedSidecar") is not None
assert not collision_data.bones["MCH_Main"].hotools_boneprops.auxBone.isAuxBone
assert collision_data.bones.get("MCH_Main.001") is None

bpy.ops.object.mode_set(mode="EDIT")
collision_data.edit_bones.remove(collision_data.edit_bones["MCH_Main"])
bpy.ops.object.mode_set(mode="OBJECT")
first_collision_map = FBXExporter.clear_armatures_bone_rotation(
    [collision_armature], [collision_armature], collision_armature
)[collision_armature.name]
generated_collision_name = first_collision_map["Main"]
assert generated_collision_name == "MCH_Main"
assert generated_collision_name != "MalformedSidecar"
assert collision_data.bones.get("MCH_Main") is not None
assert FBXExporter.is_mch_aux_bone_for_source(
    collision_data.bones[generated_collision_name], "Main"
)
bone_count_after_first_run = len(collision_data.bones)

second_collision_map = FBXExporter.clear_armatures_bone_rotation(
    [collision_armature], [collision_armature], collision_armature
)[collision_armature.name]
assert second_collision_map == first_collision_map
assert len(collision_data.bones) == bone_count_after_first_run
generated_constraint = collision_armature.pose.bones[
    generated_collision_name
].constraints[0]
assert generated_constraint.target == collision_armature
assert generated_constraint.subtarget == "Main"

# An unregistered preferred constraint name is also a hard collision. The
# generator must stop until the user removes or renames that constraint.
bpy.context.view_layer.objects.active = collision_armature
bpy.ops.object.mode_set(mode="EDIT")
aux_owner = collision_data.edit_bones.new("AuxOwner")
aux_owner.head = (0.0, 1.0, 0.0)
aux_owner.tail = (0.0, 2.0, 0.0)
aux_owner.parent = collision_data.edit_bones["Root"]
bpy.ops.object.mode_set(mode="OBJECT")
AuxPreviewUtils.set_aux_bone_props(
    collision_armature,
    ["AuxOwner"],
    "TWIST",
    ["Main"],
)
aux_pose = collision_armature.pose.bones["AuxOwner"]
canonical_name = bone_utils.aux_constraint_name("TWIST", "CopyRotation")
user_constraint = aux_pose.constraints.new("COPY_ROTATION")
user_constraint.name = canonical_name
try:
    TwistBoneCore._ensure_copy_rotation_constraint(
        aux_pose,
        collision_armature,
        "Main",
        0.5,
    )
except RuntimeError as error:
    assert canonical_name in str(error)
else:
    raise AssertionError("Aux constraint generation must stop on a preferred-name collision")
assert len(aux_pose.constraints) == 1
aux_pose.constraints.remove(user_constraint)
generated_copy = TwistBoneCore._ensure_copy_rotation_constraint(
    aux_pose,
    collision_armature,
    "Main",
    0.5,
)
assert generated_copy.name == canonical_name
_replace_aux_constraints(aux_pose, [generated_copy])
aux_info = collision_data.bones["AuxOwner"].hotools_boneprops.auxBone
assert [item.name for item in aux_info.constraintNames] == [generated_copy.name]


# The manual command uses the same rest/pose clearing contract as MCH export.
manual_data = bpy.data.armatures.new("ManualClearLocalRotationData")
manual_armature = bpy.data.objects.new("ManualClearLocalRotation", manual_data)
bpy.context.scene.collection.objects.link(manual_armature)
bpy.ops.object.select_all(action="DESELECT")
bpy.context.view_layer.objects.active = manual_armature
manual_armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")

manual_root = manual_data.edit_bones.new("ManualRoot")
manual_root.head = (0.0, 0.0, 0.0)
manual_root.tail = (-0.8, 1.4, 1.2)
manual_root.roll = -0.29

manual_first = manual_data.edit_bones.new("ManualFirst")
manual_first.head = manual_root.tail
manual_first.tail = (0.6, 2.0, 1.7)
manual_first.roll = 0.48
manual_first.parent = manual_root

manual_second = manual_data.edit_bones.new("ManualSecond")
manual_second.head = manual_first.tail
manual_second.tail = (1.3, 1.6, 2.8)
manual_second.roll = -0.73
manual_second.parent = manual_first

bpy.ops.object.mode_set(mode="OBJECT")
for bone_name in ("ManualFirst", "ManualSecond"):
    pose_bone = manual_armature.pose.bones[bone_name]
    pose_bone.rotation_mode = "XYZ"
    pose_bone.location = (0.5, -0.2, 0.9)
    pose_bone.rotation_euler = (0.3, 0.1, -0.4)
    pose_bone.scale = (0.9, 1.2, 1.1)

bpy.ops.object.mode_set(mode="EDIT")
for bone in manual_data.edit_bones:
    bone.select = bone.select_head = bone.select_tail = False
for bone_name in ("ManualFirst", "ManualSecond"):
    bone = manual_data.edit_bones[bone_name]
    bone.select = bone.select_head = bone.select_tail = True
manual_data.edit_bones.active = manual_data.edit_bones["ManualFirst"]

bpy.utils.register_class(OP_ForceClearBoneRotation)
assert bpy.ops.ho.force_clear_bone_rotation() == {'FINISHED'}
assert manual_armature.mode == "EDIT"
assert manual_data.edit_bones.active.name == "ManualFirst"
assert_identity_local_rotation(manual_data.edit_bones["ManualFirst"])
assert_identity_local_rotation(manual_data.edit_bones["ManualSecond"])

bpy.ops.object.mode_set(mode="OBJECT")
for bone_name in ("ManualFirst", "ManualSecond"):
    assert_matrix_close(
        manual_armature.pose.bones[bone_name].matrix_basis,
        Matrix.Identity(4),
    )
    assert_identity_local_rotation(manual_armature.pose.bones[bone_name])

print("FBX_MCH_LOCAL_ROTATION_OK", bpy.app.version_string)
