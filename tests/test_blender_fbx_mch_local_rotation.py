import sys
import tempfile
from pathlib import Path

import bpy
from bpy.props import BoolProperty, PointerProperty
from bpy.types import PropertyGroup
from mathutils import Matrix


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from Exporter.FbxExporter import FBXExporter
from Exporter.UnityConstraintMapper import UnityConstraintMapper
from Exporter.ConstraintAnalyzer import ConstraintAnalyzer
from BoneTools.boneOperators import OP_ForceClearBoneRotation
from io_scene_fbx import parse_fbx


class TestBoneProps(PropertyGroup):
    generateMCH: BoolProperty(default=False)


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

parent_constraints = ConstraintAnalyzer.analyze(armature)
constraint_data = UnityConstraintMapper.export_to_dict(
    armature.name,
    parent_constraints,
)
constraint_map = {
    item["boneName"]: item["constraints"]
    for item in constraint_data["bones"]
}
assert constraint_map["MCH_First"] == [
    {
        "type": "Child",
        "semantic": "parent",
        "targetPath": "First",
        "weight": 1.0,
        "space": {"source": "world", "target": "world"},
        "maintainOffset": True,
    }
]
assert constraint_map["MCH_Second"][0]["targetPath"] == "Second"

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
