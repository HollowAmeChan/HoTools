"""Run with Blender --background --factory-startup --python this_file."""

import sys
from pathlib import Path

import bpy
from mathutils import Matrix


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from BoneTools import boneHumanoid, boneProperty, boneTPose, hoAux
from BoneTools import humanoid_tpose_solver
from Exporter.HumanoidMappingExporter import HumanoidMappingExporter


hoAux.register()
boneProperty.register()
boneHumanoid.register()
boneTPose.register()


class LayoutRecorder:
    def __init__(self):
        self.events = []

    def row(self, **_kwargs):
        return self

    def label(self, **kwargs):
        self.events.append(("label", kwargs.get("text")))

    def operator(self, operator, **_kwargs):
        self.events.append(("operator", operator))


def create_armature():
    data = bpy.data.armatures.new("TPoseTestData")
    armature = bpy.data.objects.new("TPoseTest", data)
    bpy.context.scene.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)

    specs = (
        ("hips", (0.0, 0.0, 1.0), (0.0, 0.0, 1.4), None),
        ("spine", (0.0, 0.0, 1.4), (0.0, 0.0, 1.8), "hips"),
        ("chest", (0.0, 0.0, 1.8), (0.0, 0.0, 2.1), "spine"),
        ("head", (0.0, 0.0, 2.3), (0.0, 0.0, 2.7), "chest"),
        ("shoulder.L", (-0.12, 0.0, 2.0), (-0.4, 0.0, 1.9), "chest"),
        ("upper_arm.L", (-0.4, 0.0, 1.9), (-0.78, 0.0, 1.55), "shoulder.L"),
        ("lower_arm.L", (-0.78, 0.0, 1.55), (-1.08, 0.0, 1.28), "upper_arm.L"),
        ("hand.L", (-1.08, 0.0, 1.28), (-1.28, 0.0, 1.18), "lower_arm.L"),
        ("shoulder.R", (0.12, 0.0, 2.0), (0.4, 0.0, 1.9), "chest"),
        ("upper_arm.R", (0.4, 0.0, 1.9), (0.78, 0.0, 1.55), "shoulder.R"),
        ("lower_arm.R", (0.78, 0.0, 1.55), (1.08, 0.0, 1.28), "upper_arm.R"),
        ("hand.R", (1.08, 0.0, 1.28), (1.28, 0.0, 1.18), "lower_arm.R"),
    )
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head, tail, _parent in specs:
        bone = data.edit_bones.new(name)
        # HoFBX mirrors Blender X: the character's left is Blender +X.
        bone.head = (-head[0], head[1], head[2])
        bone.tail = (-tail[0], tail[1], tail[2])
    for name, _head, _tail, parent in specs:
        if parent:
            data.edit_bones[name].parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")

    for name, _head, _tail, _parent in specs:
        data.bones[name].hotools_boneprops.humanoidMapping = name
    return armature


def assert_matrix_close(actual, expected, epsilon=1e-5):
    error = max(
        abs(actual[row][column] - expected[row][column])
        for row in range(4)
        for column in range(4)
    )
    assert error < epsilon, error


armature = create_armature()
layout = LayoutRecorder()
boneTPose.draw_tpose_row(layout, armature)
assert layout.events == [
    ("operator", "ho.humanoid_tpose_preview"),
    ("operator", "ho.humanoid_tpose_save"),
    ("operator", "ho.humanoid_tpose_auto"),
    ("operator", "ho.humanoid_tpose_clear_pose"),
    ("operator", "ho.humanoid_tpose_clear_calibration"),
]
constraint = armature.pose.bones["upper_arm.L"].constraints.new("LIMIT_ROTATION")
constraint.mute = False

# Start from a distinct hand-authored pose so preview restoration is observable.
armature.pose.bones["head"].location.x = 0.2
armature.pose.bones["hips"].rotation_mode = "XYZ"
armature.pose.bones["hips"].rotation_euler.z = 0.15
original_basis = {
    pose_bone.name: pose_bone.matrix_basis.copy()
    for pose_bone in armature.pose.bones
}

# Automatic T-Pose enters preview and meets the Unity joint tolerances.
armature.data.pose_position = "REST"
assert bpy.ops.ho.humanoid_tpose_auto() == {"FINISHED"}
assert boneTPose.is_previewing(armature)
assert armature.data.pose_position == "POSE"
assert constraint.mute
bpy.context.view_layer.update()
assert humanoid_tpose_solver.validate(armature)["total"] < .01

# Saving during the candidate preview persists per-bone basis matrices.
assert bpy.ops.ho.humanoid_tpose_save() == {"FINISHED"}
assert boneTPose.cached_bone_count(armature) == len(armature.pose.bones)
saved_basis = {
    pose_bone.name: pose_bone.matrix_basis.copy()
    for pose_bone in armature.pose.bones
}

# Toggling preview off restores the original channels and constraint state.
assert bpy.ops.ho.humanoid_tpose_preview() == {"FINISHED"}
assert not boneTPose.is_previewing(armature)
assert armature.data.pose_position == "REST"
assert not constraint.mute
for pose_bone in armature.pose.bones:
    assert_matrix_close(pose_bone.matrix_basis, original_basis[pose_bone.name])

# Preview applies the saved values; reset exits preview and retains calibration.
armature.pose.bones["head"].location.x = 0.5
assert bpy.ops.ho.humanoid_tpose_preview() == {"FINISHED"}
for pose_bone in armature.pose.bones:
    assert_matrix_close(pose_bone.matrix_basis, saved_basis[pose_bone.name])
assert bpy.ops.ho.humanoid_tpose_clear_pose() == {"FINISHED"}
assert not boneTPose.is_previewing(armature)
assert boneTPose.cached_bone_count(armature) == len(armature.pose.bones)
for pose_bone in armature.pose.bones:
    assert_matrix_close(pose_bone.matrix_basis, Matrix.Identity(4))

# File and history changes close previews before Blender snapshots the data.
assert bpy.ops.ho.humanoid_tpose_preview() == {"FINISHED"}
boneTPose._restore_previews_before_file_change(None)
assert not boneTPose.is_previewing(armature)
assert not constraint.mute
for pose_bone in armature.pose.bones:
    assert_matrix_close(pose_bone.matrix_basis, Matrix.Identity(4))

# Clearing calibration is independent and does not change the current pose.
snapshot = {bone.name: bone.matrix_basis.copy() for bone in armature.pose.bones}
reference = HumanoidMappingExporter.capture_reference_poses([armature])
export = HumanoidMappingExporter.build_export_dict([armature], reference)
assert len(export["armatures"][0]["tPose"]["bones"]) == len(armature.data.bones)
from mathutils import Quaternion, Vector
for row in export["armatures"][0]["tPose"]["bones"]:
    q = row["rotation"]
    delta = Matrix.LocRotScale(Vector(row["position"]), Quaternion((q[3], q[0], q[1], q[2])), Vector(row["scale"]))
    assert_matrix_close(delta, saved_basis[row["boneName"]])
for bone in armature.pose.bones:
    assert_matrix_close(bone.matrix_basis, snapshot[bone.name])
armature.data.bones["head"].hotools_boneprops.humanoidTPoseCached = False
try:
    HumanoidMappingExporter.capture_reference_poses([armature])
    raise AssertionError("Partial T-Pose was silently exported")
except ValueError as exception:
    assert "不完整" in str(exception)
armature.data.bones["head"].hotools_boneprops.humanoidTPoseCached = True

# An export may apply a different rest pose. Rebase the calibration against
# that rest while retaining the original physical reference skeleton.
expected_reference = {name: item["pose"].copy() for name, item in reference[armature.name].items()}
bpy.ops.object.mode_set(mode="EDIT")
change = Matrix.Rotation(.23, 4, "Z")
for bone in armature.data.edit_bones:
    bone.matrix = change @ bone.matrix
bpy.ops.object.mode_set(mode="OBJECT")
HumanoidMappingExporter.rebase_reference_rest(reference, [armature])
HumanoidMappingExporter.update_reference_poses(export, [armature], reference)
poses = {}
for row in export["armatures"][0]["tPose"]["bones"]:
    bone = armature.data.bones[row["boneName"]]
    parent_rest = bone.parent.matrix_local if bone.parent else Matrix.Identity(4)
    local_rest = parent_rest.inverted() @ bone.matrix_local
    q = row["rotation"]
    delta = Matrix.LocRotScale(Vector(row["position"]), Quaternion((q[3], q[0], q[1], q[2])), Vector(row["scale"]))
    poses[bone.name] = (poses[bone.parent.name] if bone.parent else armature.matrix_world) @ local_rest @ delta
    assert_matrix_close(poses[bone.name], expected_reference[bone.name])

armature.pose.bones["head"].location.x = 0.25
pose_before_clear = armature.pose.bones["head"].matrix_basis.copy()
assert bpy.ops.ho.humanoid_tpose_clear_calibration() == {"FINISHED"}
assert boneTPose.cached_bone_count(armature) == 0
assert_matrix_close(armature.pose.bones["head"].matrix_basis, pose_before_clear)
assert "tPose" not in HumanoidMappingExporter.build_export_dict([armature])["armatures"][0]

boneTPose.unregister()
boneHumanoid.unregister()
boneProperty.unregister()
hoAux.unregister()
print("HUMANOID_TPOSE_OK", bpy.app.version_string)
