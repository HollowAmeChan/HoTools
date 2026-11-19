"""Run with Blender --background --factory-startup --python-exit-code 1 --python."""

import sys
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Matrix


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from BoneTools import boneOperators, boneProperty, hoAux
from Utils import bone_utils


hoAux.register()
boneProperty.register()
boneOperators.register()


def create_armature(name):
    bpy.ops.object.select_all(action="DESELECT")
    data = bpy.data.armatures.new(name + "Data")
    armature = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(armature)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    for index, bone_name in enumerate((
        "hips", "arm.L", "arm.R", "LeftHand", "RightHand", "missing_L",
    )):
        bone = data.edit_bones.new(bone_name)
        bone.head = (index * 0.3, 0, 0)
        bone.tail = (index * 0.3, 1, 0)
    bpy.ops.object.mode_set(mode="OBJECT")
    return armature


def assert_matrix_close(actual, expected):
    assert max(
        abs(actual[row][column] - expected[row][column])
        for row in range(4) for column in range(4)
    ) < 1e-5, (actual, expected)


other = create_armature("Untouched")
other.pose.bones["arm.L"].constraints.new("LIMIT_ROTATION")
other_constraint = other.constraints.new("LIMIT_LOCATION")
armature = create_armature("Operations")
for name in ("hips", "arm.L", "arm.R"):
    armature.pose.bones[name].constraints.new("LIMIT_ROTATION")
armature.pose.bones["missing_L"].constraints.new("LIMIT_LOCATION").mute = True
object_constraint = armature.constraints.new("LIMIT_LOCATION")
armature.data.bones["hips"].hotools_boneprops.humanoidMapping = "hips"

# Invocation opens a confirmation, without changing any constraint. The dialog
# counts the actual scope and executes only after Blender receives confirmation.
dialogs = []
dialog_context = SimpleNamespace(
    active_object=armature,
    window_manager=SimpleNamespace(
        invoke_confirm=lambda operator, event, **kwargs: (
            dialogs.append(kwargs) or {"RUNNING_MODAL"}
        ),
    ),
)
for cls, expected_count in (
    (boneOperators.OP_ClearAllBoneConstraints, 4),
    (boneOperators.OP_ClearHumanoidConstraints, 1),
):
    operator = SimpleNamespace(bl_label=cls.bl_label)
    assert cls.invoke(operator, dialog_context, None) == {"RUNNING_MODAL"}
    assert armature.name in dialogs[-1]["message"]
    assert f"{expected_count} 个约束" in dialogs[-1]["message"]
    assert dialogs[-1]["icon"] == "WARNING"
    assert sum(len(b.constraints) for b in armature.pose.bones) == 4

# Humanoid deletion remains scoped; all-bone deletion includes muted constraints
# and preserves object-level constraints and other armatures.
assert bpy.ops.ho.clear_humanoid_constraints() == {"FINISHED"}
assert not armature.pose.bones["hips"].constraints
assert sum(len(b.constraints) for b in armature.pose.bones) == 3
assert bpy.ops.ho.clear_all_bone_constraints() == {"FINISHED"}
assert all(not bone.constraints for bone in armature.pose.bones)
assert armature.constraints.get(object_constraint.name) == object_constraint
assert len(other.pose.bones["arm.L"].constraints) == 1
assert other.constraints.get(other_constraint.name) == other_constraint

# Mirror selected sources to their opposite names, including unselected targets,
# while preserving the original selection, active bone, mirror, and auto-key.
bpy.ops.object.mode_set(mode="POSE")
left = armature.pose.bones["arm.L"]
right = armature.pose.bones["arm.R"]
left.rotation_mode = "XYZ"
left.location = (0.2, 0.4, -0.3)
left.rotation_euler = (0.25, 0.5, -0.2)
left.scale = (0.8, 1.2, 1.1)
right.rotation_mode = "QUATERNION"
armature.pose.bones["hips"].location = (0.4, 0.5, 0.2)
armature.pose.bones["missing_L"].location.x = 0.7
armature.pose.bones["LeftHand"].rotation_mode = "AXIS_ANGLE"
armature.pose.bones["LeftHand"].rotation_axis_angle = (0.6, 0.0, 1.0, 0.0)
selection = ["arm.L", "LeftHand", "hips", "missing_L"]
bone_utils.select_bones(armature, selection)
active = armature.data.bones.active
before = {bone.name: bone.matrix_basis.copy() for bone in armature.pose.bones}
mirror_x = Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))
armature.data.use_mirror_x = True
bpy.context.scene.tool_settings.use_keyframe_insert_auto = True

assert bpy.ops.ho.symmetrize_selected_pose() == {"FINISHED"}
assert_matrix_close(right.matrix_basis, mirror_x @ before["arm.L"] @ mirror_x)
assert_matrix_close(
    armature.pose.bones["RightHand"].matrix_basis,
    mirror_x @ before["LeftHand"] @ mirror_x,
)
for name in selection:
    assert_matrix_close(armature.pose.bones[name].matrix_basis, before[name])
assert set(bone_utils.selected_bone_names(bpy.context, armature)) == set(selection)
assert armature.data.bones.active == active
assert armature.data.use_mirror_x
assert bpy.context.scene.tool_settings.use_keyframe_insert_auto
assert armature.animation_data is None or armature.animation_data.action is None

# Copying both sides snapshots their initial poses before writing either target.
right.location = (-0.3, 0.15, 0.5)
right.rotation_quaternion = (0.9, 0.1, 0.2, 0.3)
bone_utils.select_bones(armature, ["arm.L", "arm.R"])
left_before = left.matrix_basis.copy()
right_before = right.matrix_basis.copy()
assert bpy.ops.ho.symmetrize_selected_pose() == {"FINISHED"}
assert_matrix_close(left.matrix_basis, mirror_x @ right_before @ mirror_x)
assert_matrix_close(right.matrix_basis, mirror_x @ left_before @ mirror_x)
assert right.rotation_mode == "QUATERNION"
assert left.rotation_mode == "XYZ"

# Selecting only unpaired/central bones is a no-op.
bone_utils.select_bones(armature, ["hips", "missing_L"])
before = {bone.name: bone.matrix_basis.copy() for bone in armature.pose.bones}
assert bpy.ops.ho.symmetrize_selected_pose() == {"CANCELLED"}
for bone in armature.pose.bones:
    assert_matrix_close(bone.matrix_basis, before[bone.name])

# The panel keeps each pair of related operations on one row and invokes both
# bulk-delete operators through the confirmation path.
class LayoutRecorder:
    def __init__(self, rows=None):
        self.rows = [] if rows is None else rows
        self.operator_context = "INVOKE_DEFAULT"
        self.buttons = []

    def column(self, **_kwargs):
        return self

    def row(self, **_kwargs):
        row = LayoutRecorder(self.rows)
        self.rows.append(row)
        return row

    def operator(self, name, **kwargs):
        if name in {"ho.reset_all_bone_pose", "ho.symmetrize_selected_pose"}:
            assert "icon" not in kwargs
        self.buttons.append((name, self.operator_context))

    def separator(self):
        pass

    def panel(self, _name, **_kwargs):
        return SimpleNamespace(label=lambda **_kwargs: None), None


layout = LayoutRecorder()
boneOperators.drawBoneOperatorsPanel(layout, bpy.context)
rows = [
    [name for name, _context in row.buttons] for row in layout.rows
]
assert ["ho.reset_all_bone_pose", "ho.symmetrize_selected_pose"] in rows
assert boneOperators.OP_SymmetrizeSelectedPose.bl_label == "镜像/翻转姿态"
assert [
    "ho.disable_all_bone_constraints",
    "ho.enable_all_bone_constraints",
    "ho.clear_all_bone_constraints",
] in rows
for row in layout.rows:
    for name, operator_context in row.buttons:
        if name in {"ho.clear_all_bone_constraints", "ho.clear_humanoid_constraints"}:
            assert operator_context == "INVOKE_DEFAULT"

boneOperators.unregister()
boneProperty.unregister()
hoAux.unregister()
print("BONE_POSE_OPERATIONS_OK", bpy.app.version_string)
