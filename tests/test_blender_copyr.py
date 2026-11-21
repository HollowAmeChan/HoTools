"""copyR authoring on existing bones, ownership and safe lifecycle in real RNA."""

from pathlib import Path
import sys
import tempfile

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup
from mathutils import Euler, Matrix

ADDON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON_ROOT))

from RigConstraints.blender import metadata
from RigConstraints.blender.properties import PROPERTY_CLASSES, PG_RigConstraintGroup
from BoneTools.auxBone import copyRotation
from BoneTools.auxBone.copyRotation import CopyRotationCore
from Utils.bone_selection import select_bones


class TestReference(PropertyGroup):
    name: StringProperty(default="")


class TestAux(PropertyGroup):
    isAuxBone: BoolProperty(default=False)
    auxType: EnumProperty(items=[(name, name, "") for name in ("NONE", "COPY_R", "FAN")], default="NONE")
    sourceBones: CollectionProperty(type=TestReference)
    constraintNames: CollectionProperty(type=TestReference)


class TestProps(PropertyGroup):
    auxBone: PointerProperty(type=TestAux)
    constraintGroups: CollectionProperty(type=PG_RigConstraintGroup)


for cls in (*PROPERTY_CLASSES, TestReference, TestAux, TestProps):
    bpy.utils.register_class(cls)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=TestProps)
copyRotation.register()

rig = bpy.data.objects.new("CopyRTest", bpy.data.armatures.new("CopyRTestData"))
bpy.context.scene.collection.objects.link(rig)
bpy.ops.object.select_all(action="DESELECT")
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT")


def add_bone(name, head, tail, parent=None, roll=0):
    bone = rig.data.edit_bones.new(name)
    bone.head, bone.tail, bone.roll = head, tail, roll
    if parent:
        bone.parent = rig.data.edit_bones[parent]


add_bone("Pelvis", (0, 0, 1), (0, 0, 1.4), roll=.3)
add_bone("Thigh", (.2, 0, 1), (.3, .1, .4), "Pelvis", .5)
add_bone("SkirtRoot", (.2, -.1, 1), (.5, .2, .4), "Pelvis", -.8)
add_bone("OtherSkirt", (-.2, -.1, 1), (-.5, .2, .4), "Pelvis", -.6)
add_bone("SkirtChild", (.5, .2, .4), (.6, .3, .1), "SkirtRoot")
bpy.ops.object.mode_set(mode="POSE")
initial_count = len(rig.data.bones)
initial_rest = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones}
initial_parents = {bone.name: bone.parent.name if bone.parent else "" for bone in rig.data.bones}
owner = rig.pose.bones["SkirtRoot"]
manual = owner.constraints.new("COPY_ROTATION")
manual.name = "UserOtherRotation"
manual.target = rig
manual.subtarget = "Pelvis"
manual.mute = True

# Mesh weights represent user-owned data; copyR never creates/transfers/deletes it.
mesh = bpy.data.meshes.new("CopyRWeightMesh")
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
mesh_object = bpy.data.objects.new("CopyRWeightObject", mesh)
bpy.context.scene.collection.objects.link(mesh_object)
vertex_group = mesh_object.vertex_groups.new(name="SkirtRoot")
vertex_group.add([0, 1], .7, "REPLACE")
weights_before = [vertex_group.weight(index) for index in (0, 1)]

settings = bpy.context.scene.ho_copyr_settings
assert settings.target_space == "LOCAL_OWNER_ORIENT"
assert settings.owner_space == "LOCAL"
assert settings.influence == 1
settings.target_bone = "Thigh"
select_bones(rig, ["SkirtRoot"])
assert bpy.ops.ho.copyr_generate() == {"FINISHED"}
constraint = owner.constraints.get(CopyRotationCore.CONSTRAINT_NAME)
assert constraint is not None
constraint_pointer = constraint.as_pointer()
assert constraint.type == "COPY_ROTATION"
assert constraint.target == rig and constraint.subtarget == "Thigh"
assert constraint.owner_space == "LOCAL" and constraint.target_space == "LOCAL_OWNER_ORIENT"
assert constraint.mix_mode == "REPLACE"
assert constraint.use_x and constraint.use_y and constraint.use_z
assert not (constraint.invert_x or constraint.invert_y or constraint.invert_z)
aux = owner.bone.hotools_boneprops.auxBone
assert aux.isAuxBone and aux.auxType == "COPY_R"
assert [ref.name for ref in aux.sourceBones] == ["Thigh"]
group = metadata.iter_groups(owner.bone)[0]
assert group["semanticType"] == "COPY_ROTATION"
assert group["generatorId"] == "hotools.aux.copy_r"
assert group["members"] == [{"constraintName": constraint.name, "constraintType": "COPY_ROTATION", "role": "rotation", "order": 0}]
assert group.get("ownsBone") is False
group_id = group["groupId"]

# Repeating the command updates only its explicitly registered instance.
settings.influence = .3
assert bpy.ops.ho.copyr_generate() == {"FINISHED"}
assert owner.constraints.get(CopyRotationCore.CONSTRAINT_NAME).as_pointer() == constraint_pointer
assert len(owner.constraints) == 2 and owner.constraints.get("UserOtherRotation") == manual
assert abs(constraint.influence - .3) < 1e-6
assert metadata.iter_groups(owner.bone)[0]["groupId"] == group_id

# Different rest axes retain the owner's rest orientation and match the
# owner-orientation conjugation, including parent motion and partial influence.
for influence in (0, .3, .5, 1):
    CopyRotationCore.configure(rig, ["SkirtRoot"], "Thigh", influence=influence)
    rig.pose.bones["Thigh"].rotation_mode = "QUATERNION"
    rig.pose.bones["Thigh"].rotation_quaternion = Euler((.7, -.4, .3), "XYZ").to_quaternion()
    rig.pose.bones["Pelvis"].rotation_mode = "QUATERNION"
    rig.pose.bones["Pelvis"].rotation_quaternion = Euler((.3, .1, -.2), "XYZ").to_quaternion()
    bpy.context.view_layer.update()
    target = rig.pose.bones["Thigh"]
    correction = owner.bone.matrix_local.to_quaternion().inverted() @ target.bone.matrix_local.to_quaternion()
    desired_delta = correction @ target.rotation_quaternion @ correction.inverted()
    q = Matrix.Identity(4).to_quaternion().slerp(desired_delta, influence)
    local_bind = owner.parent.bone.matrix_local.inverted() @ owner.bone.matrix_local
    expected = owner.parent.matrix @ local_bind @ q.to_matrix().to_4x4()
    assert max(abs(owner.matrix[row][column] - expected[row][column]) for row in range(4) for column in range(4)) < 2e-5

# Preserve a user-owned constraint with the exact preferred name. Do not rename,
# adopt or silently put a second copy behind it. Multi-owner preflight is atomic.
other = rig.pose.bones["OtherSkirt"]
collision = other.constraints.new("COPY_ROTATION")
collision.name = CopyRotationCore.CONSTRAINT_NAME
collision.influence = .42
before_influence = constraint.influence
try:
    CopyRotationCore.configure(rig, ["SkirtRoot", "OtherSkirt"], "Pelvis", influence=.1)
except ValueError:
    pass
else:
    raise AssertionError("unregistered name collision must be reported")
assert constraint.influence == before_influence and constraint.subtarget == "Thigh"
assert len(other.constraints) == 1 and abs(collision.influence - .42) < 1e-6
assert not other.bone.hotools_boneprops.auxBone.isAuxBone
other.constraints.remove(collision)

# Renaming loses identity until the user explicitly resolves it. A similarly
# named replacement is never guessed as the owned constraint.
constraint.name = "RenamedByUser"
try:
    CopyRotationCore.configure(rig, ["SkirtRoot"], "Thigh")
except ValueError:
    pass
else:
    raise AssertionError("broken registered reference must not be guessed")
assert owner.constraints.get("RenamedByUser") == constraint
constraint.name = CopyRotationCore.CONSTRAINT_NAME

for target in ("MissingBone", "SkirtRoot", "SkirtChild"):
    try:
        CopyRotationCore.configure(rig, ["SkirtRoot"], target)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid target should fail before mutation: " + target)

# A saved/reopened file keeps the group identity and can be updated idempotently.
with tempfile.TemporaryDirectory(prefix="hotools_copyr_") as directory:
    saved = Path(directory) / "copyr.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(saved))
    bpy.ops.wm.open_mainfile(filepath=str(saved))
    rig = bpy.data.objects["CopyRTest"]
    bpy.context.view_layer.objects.active = rig
    owner = rig.pose.bones["SkirtRoot"]
    persisted = metadata.iter_groups(owner.bone)[0]
    assert persisted["groupId"] == group_id and persisted["generatorId"] == CopyRotationCore.GENERATOR_ID
    CopyRotationCore.configure(rig, ["SkirtRoot"], "Thigh", influence=.5)
    assert len(owner.constraints) == 2

assert len(rig.data.bones) == initial_count
for bone in rig.data.bones:
    assert bone.matrix_local == initial_rest[bone.name]
    assert (bone.parent.name if bone.parent else "") == initial_parents[bone.name]
mesh_object = bpy.data.objects["CopyRWeightObject"]
vertex_group = mesh_object.vertex_groups["SkirtRoot"]
assert weights_before == [vertex_group.weight(index) for index in (0, 1)]

# Edit-mode entry preserves edit mode and selection; removal retains original
# bones and weights and never deletes unrelated manual constraints.
if rig.mode != "EDIT":
    bpy.ops.object.mode_set(mode="EDIT")
select_bones(rig, ["SkirtRoot"])
assert bpy.ops.ho.copyr_remove() == {"FINISHED"}
assert rig.mode == "EDIT"
bpy.ops.object.mode_set(mode="POSE")
owner = rig.pose.bones["SkirtRoot"]
assert owner.constraints.get("UserOtherRotation") is not None
assert len(owner.constraints) == 1
assert metadata.iter_groups(owner.bone) == []
assert not owner.bone.hotools_boneprops.auxBone.isAuxBone
assert len(rig.data.bones) == initial_count
assert weights_before == [vertex_group.weight(index) for index in (0, 1)]
assert CopyRotationCore.remove(rig, ["SkirtRoot"]) == 0

# The same disclosure/creation controls are wired into the ordinary Aux panel.
class LayoutProbe:
    def __init__(self, calls=None):
        self.calls = [] if calls is None else calls

    def box(self):
        return LayoutProbe(self.calls)

    def row(self, **_kwargs):
        return LayoutProbe(self.calls)

    def prop(self, _owner, name, **_kwargs):
        self.calls.append(("prop", name))

    def prop_search(self, _owner, name, _search, collection, **_kwargs):
        self.calls.append(("search", name, collection))

    def label(self, **kwargs):
        self.calls.append(("label", kwargs.get("text")))

    def operator(self, name, **_kwargs):
        self.calls.append(("operator", name))


settings = bpy.context.scene.ho_copyr_settings
settings.ui_expanded = True
layout = LayoutProbe()
copyRotation.draw_panel(layout, bpy.context)
assert ("operator", "ho.copyr_generate") in layout.calls
assert ("operator", "ho.copyr_remove") in layout.calls
assert ("search", "target_bone", "bones") in layout.calls

# Creating from Edit mode also returns to Edit mode without creating bones.
bpy.ops.object.mode_set(mode="EDIT")
select_bones(rig, ["SkirtRoot"])
settings.target_bone = "Thigh"
assert bpy.ops.ho.copyr_generate() == {"FINISHED"}
assert rig.mode == "EDIT"
assert bpy.ops.ho.copyr_remove() == {"FINISHED"}
assert rig.mode == "EDIT"
assert len(rig.data.edit_bones) == initial_count
bpy.ops.object.mode_set(mode="POSE")

# Exercise feature-specific registration teardown and reinstall.
copyRotation.unregister()
assert not hasattr(bpy.types.Scene, "ho_copyr_settings")
copyRotation.register()
assert bpy.context.scene.ho_copyr_settings.target_space == "LOCAL_OWNER_ORIENT"
copyRotation.unregister()
print("COPY_R_OK", bpy.app.version_string)
