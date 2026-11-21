"""Ordinary constraint declarations: generation, legacy reads and lifecycle.

Run in an isolated Blender process with --background --factory-startup
--disable-autoexec --python-exit-code 1 --python this_file.py.
"""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from BoneTools import boneProperty, hoAux
from BoneTools.auxBone.boneFan import BoneFanCore
from BoneTools.auxBone.boneFanSingle import BoneFanSingleCore
from BoneTools.auxBone.boneFanSide import BoneFanSideCore
from BoneTools.auxBone.boneTwist import TwistBoneCore
from BoneTools.previewUtils import AuxPreviewUtils
from RigConstraints.blender import metadata
from RigConstraints.blender.properties import PROPERTY_CLASSES


def make_rig():
    data = bpy.data.armatures.new("MetadataRigData")
    rig = bpy.data.objects.new("MetadataRig", data)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    names = ["Root", "Source", "Target", "Up", "TwistOwner", "AimOwner", "MchOwner", "IdentityOwner", "DeleteOwner", "CopyROwner", "CopyRBroken", "AimDetach"]
    names += [core._fan_name(core.AUX_TYPE, "out", 1, 2) for core in (BoneFanCore, BoneFanSingleCore, BoneFanSideCore)]
    for index, name in enumerate(names):
        bone = data.edit_bones.new(name)
        bone.head = (index * .25, 0, .1)
        bone.tail = (index * .25, .8, .3)
        bone.use_deform = False
        if name != "Root":
            bone.parent = data.edit_bones["Root"]
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig


def tag(rig, name, kind, sources=("Source",)):
    AuxPreviewUtils.set_aux_bone_props(rig, [name], kind, list(sources))
    return rig.pose.bones[name]


def add_constraint(owner, kind, name, rig, target="Target"):
    constraint = owner.constraints.new(kind)
    constraint.name = name
    constraint.target = rig
    constraint.subtarget = target
    return constraint


class Refs(list):
    def add(self):
        value = NS(name="")
        self.append(value)
        return value


class Stack(list):
    def get(self, name):
        return next((c for c in self if c.name == name), None)


hoAux.register()  # Existing BoneProps dependency; no large HoAux modules generated.
boneProperty.register()
assert PROPERTY_CLASSES[0].bl_rna.identifier == "PG_RigConstraintMember"
assert PROPERTY_CLASSES[1].bl_rna.identifier == "PG_RigConstraintGroup"
rig = make_rig()
invalidations = []
old_invalidate = metadata._invalidate
metadata._invalidate = lambda owner: invalidations.append(owner)

try:
    owner = tag(rig, "TwistOwner", "TWIST")
    rotation = TwistBoneCore._ensure_copy_rotation_constraint(owner, rig, "Target", .4)
    assert len(owner.bone.hotools_boneprops.constraintGroups) == 0
    stretch = TwistBoneCore._ensure_stretch_to_constraint(owner, rig, "Target")
    assert len(owner.bone.hotools_boneprops.constraintGroups) == 0
    boneProperty._replace_aux_constraints(owner, [rotation, stretch])
    groups = metadata.iter_groups(owner.bone, pose_bone=owner)
    assert len(groups) == 1 and groups[0]["semanticType"] == "TWIST"
    assert [m["role"] for m in groups[0]["members"]] == ["rotation", "stretch"]
    assert [m["constraintType"] for m in groups[0]["members"]] == ["COPY_ROTATION", "STRETCH_TO"]
    assert groups[0]["evidence"] == "GENERATED"
    assert groups[0]["ownsBone"]
    group_id = groups[0]["groupId"]
    count, _ = TwistBoneCore.add_copy_rotation_to_twist_bones(
        bpy.context, rig, ["Source"], [owner.name], manual_target="Target")
    assert count == 1
    assert len(owner.bone.hotools_boneprops.constraintGroups) == 1
    assert metadata.iter_groups(owner.bone)[0]["groupId"] == group_id
    view = metadata.iter_groups(owner.bone)
    view[0]["members"][0]["constraintName"] = "not persisted"
    assert metadata.iter_groups(owner.bone)[0]["members"][0]["constraintName"] == rotation.name

    # A deleted actual member does not erase or replace its recorded evidence.
    rotation_name = rotation.name
    owner.constraints.remove(rotation)
    damaged = metadata.iter_groups(owner.bone, pose_bone=owner)[0]
    assert damaged["evidence"] == "GENERATED"
    assert damaged["members"][0]["constraintName"] == rotation_name
    rotation = TwistBoneCore._ensure_copy_rotation_constraint(owner, rig, "Target", .4)
    boneProperty._replace_aux_constraints(owner, [rotation, stretch])
    assert metadata.iter_groups(owner.bone)[0]["groupId"] == group_id
    rotation.influence = .17
    rotation.mute = True
    assert metadata.iter_groups(owner.bone)[0]["groupId"] == group_id

    for core in (BoneFanCore, BoneFanSingleCore, BoneFanSideCore):
        name = core._fan_name(core.AUX_TYPE, "out", 1, 2)
        fan = tag(rig, name, core.AUX_TYPE, ("Source", "Target"))
        core._add_fan_constraints(rig, [fan.name], ["Target"])
        fan_groups = metadata.iter_groups(fan.bone, pose_bone=fan)
        assert len(fan_groups) == 1 and fan_groups[0]["semanticType"] == "FAN"
        assert fan_groups[0]["members"][0]["role"] == "rotation"
        assert fan_groups[0]["generatorId"].endswith(core.AUX_TYPE.lower())
        core._add_fan_constraints(rig, [fan.name], ["Target"])
        assert len(fan.bone.hotools_boneprops.constraintGroups) == 1

    aim = rig.pose.bones["AimOwner"]
    position = add_constraint(aim, "COPY_LOCATION", "IndependentPosition", rig)
    damped = add_constraint(aim, "DAMPED_TRACK", "LookDirection", rig)
    damped.track_axis = "TRACK_X"
    locked = add_constraint(aim, "LOCKED_TRACK", "UpDirection", rig, "Up")
    locked.track_axis, locked.lock_axis = "TRACK_NEGATIVE_Z", "LOCK_X"
    boneProperty.register_existing_aim_pair(aim)
    boneProperty.register_existing_aim_pair(aim)
    aim_groups = metadata.iter_groups(aim.bone, pose_bone=aim)
    assert len(aim_groups) == 1 and aim_groups[0]["semanticType"] == "AIM"
    assert not aim_groups[0]["ownsBone"]
    assert [m["constraintName"] for m in aim_groups[0]["members"]] == [damped.name, locked.name]
    assert [m["role"] for m in aim_groups[0]["members"]] == ["aim", "up"]
    assert position.name not in {m["constraintName"] for m in aim_groups[0]["members"]}

    mch = tag(rig, "MchOwner", "MCH")
    child_of = add_constraint(mch, "CHILD_OF", "MchParent", rig, "Source")
    boneProperty._register_aux_constraint(mch, child_of)
    assert len(mch.bone.hotools_boneprops.constraintGroups) == 0
    boneProperty._replace_aux_constraints(mch, [child_of])
    assert metadata.iter_groups(mch.bone)[0]["members"][0]["role"] == "parent"
    assert metadata.iter_groups(mch.bone)[0]["ownsBone"]

    identity = tag(rig, "IdentityOwner", "FAN", ("Source", "Target"))
    copied = add_constraint(identity, "COPY_ROTATION", "IdentityCopy", rig)
    boneProperty._replace_aux_constraints(identity, [copied])
    AuxPreviewUtils.set_aux_bone_props(rig, [identity.name], "FAN", ["Source", "Target"])
    assert len(identity.bone.hotools_boneprops.constraintGroups) == 1
    AuxPreviewUtils.set_aux_bone_props(rig, [identity.name], "FAN_SIDE", ["Source", "Target"])
    assert len(identity.bone.hotools_boneprops.constraintGroups) == 0
    assert not identity.bone.hotools_boneprops.auxBone.constraintNames
    assert identity.constraints.get(copied.name) is not None

    # Legacy minimal PropertyGroups and pure-Python fakes need no new collection.
    aux = NS(isAuxBone=True, auxType="TWIST", sourceBones=Refs([NS(name="Source")]),
             constraintNames=Refs(), aimVersion=1)
    fake_bone = NS(hotools_boneprops=NS(auxBone=aux, hoAux=NS(sentinel="preserved")))
    fake = NS(name="Fake", bone=fake_bone, id_data=None,
              constraints=Stack([NS(name="OldRotation", type="COPY_ROTATION"), NS(name="OldStretch", type="STRETCH_TO")]))
    boneProperty._replace_aux_constraints(fake, fake.constraints)
    assert [r.name for r in aux.constraintNames] == ["OldRotation", "OldStretch"]
    before_names = [r.name for r in aux.constraintNames]
    legacy = metadata.iter_groups(fake_bone, pose_bone=fake)
    assert legacy[0]["evidence"] == "LEGACY"
    assert legacy[0]["ownsBone"]
    fake.constraints.pop(0)
    missing = metadata.iter_groups(fake_bone, pose_bone=fake)[0]
    assert missing["members"][0]["constraintName"] == "OldRotation"
    assert missing["members"][0]["constraintType"] == "COPY_ROTATION"
    assert before_names == [r.name for r in aux.constraintNames]

    # Old Aim ownership can include an independent Copy Location before its pair.
    aux.auxType = "AIM"
    aux.constraintNames = Refs([NS(name=n) for n in ("Location", "Aim", "Up")])
    fake.constraints = Stack([NS(name="Location", type="COPY_LOCATION"), NS(name="Aim", type="DAMPED_TRACK"), NS(name="Up", type="LOCKED_TRACK")])
    old_aim = metadata.iter_groups(fake_bone, pose_bone=fake)[0]
    assert [m["constraintName"] for m in old_aim["members"]] == ["Aim", "Up"]
    assert not old_aim["ownsBone"]
    metadata.reset_aux_info(fake_bone)
    assert aux.auxType == "NONE" and not aux.isAuxBone and not aux.constraintNames
    assert fake_bone.hotools_boneprops.hoAux.sentinel == "preserved"

    copy_owner = tag(rig, "CopyROwner", "COPY_R", ("Target",))
    copy_owner.bone.use_deform = True
    generated = add_constraint(copy_owner, "COPY_ROTATION", "GeneratedCopyR", rig)
    manual = add_constraint(copy_owner, "COPY_ROTATION", "ManualCopyRotation", rig)
    boneProperty._replace_aux_constraints(copy_owner, [generated])
    copy_group = metadata.iter_groups(copy_owner.bone, pose_bone=copy_owner)[0]
    assert copy_group["semanticType"] == "COPY_ROTATION" and not copy_group["ownsBone"]
    assert copy_group["generatorId"] == "hotools.aux.copy_r"
    assert not metadata.owns_aux_bone(copy_owner.bone, pose_bone=copy_owner)
    toggle_group = next(group for group in boneProperty._collect_aux_groups(rig.data) if group["auxType"] == "COPY_R")
    assert boneProperty._aux_group_constraint_state(rig, [copy_owner.name]) == (1, 0)
    assert bpy.ops.hotools.aux_group_constraint_toggle(key=toggle_group["key"]) == {"FINISHED"}
    assert generated.mute and not manual.mute
    assert bpy.ops.hotools.aux_group_constraint_toggle(key=toggle_group["key"]) == {"FINISHED"}
    assert not generated.mute and not manual.mute
    metadata.register_group(copy_owner, "COPY_ROTATION", [manual], generator_id="test.unrelated", roles=["rotation"])
    assert len(metadata.iter_groups(copy_owner.bone)) == 2
    metadata.unregister_group(copy_owner.bone, "COPY_ROTATION", generator_id="test.unrelated")
    assert copy_owner.bone.hotools_boneprops.auxBone.auxType == "COPY_R"
    assert len(metadata.iter_groups(copy_owner.bone)) == 1

    # Constraint-only removal never touches owner bind/rest/parent or mesh weights.
    mesh = bpy.data.meshes.new("CopyRWeights")
    mesh.from_pydata([(0, 0, 0)], [], [])
    skin = bpy.data.objects.new("CopyRWeights", mesh)
    bpy.context.scene.collection.objects.link(skin)
    modifier = skin.modifiers.new("Armature", "ARMATURE")
    modifier.object = rig
    weight_group = skin.vertex_groups.new(name=copy_owner.name)
    weight_group.add([0], .67, "REPLACE")
    original_weight = weight_group.weight(0)
    original_rest = copy_owner.bone.matrix_local.copy()
    original_basis = copy_owner.matrix_basis.copy()
    original_parent = copy_owner.bone.parent.name
    detached = boneProperty.AuxBoneRemover.remove(bpy.context, rig, [copy_owner.name], True, False)
    assert detached["removed_bones"] == 0 and detached["preserved_bones"] == 1 and detached["removed_constraints"] == 1
    copy_owner = rig.pose.bones["CopyROwner"]
    assert copy_owner.constraints.get("GeneratedCopyR") is None
    assert copy_owner.constraints.get("ManualCopyRotation") is not None
    assert copy_owner.bone.matrix_local == original_rest and copy_owner.matrix_basis == original_basis
    assert copy_owner.bone.parent.name == original_parent
    assert skin.vertex_groups["CopyROwner"].weight(0) == original_weight
    assert metadata.iter_groups(copy_owner.bone) == []

    broken = tag(rig, "CopyRBroken", "COPY_R", ("Target",))
    bad_copy = add_constraint(broken, "COPY_ROTATION", "BrokenCopyR", rig)
    boneProperty._replace_aux_constraints(broken, [bad_copy])
    bad_copy.name = "RenamedCopyR"
    replacement = add_constraint(broken, "COPY_LOCATION", "BrokenCopyR", rig)
    broken_group = next(group for group in boneProperty._collect_aux_groups(rig.data) if group["auxType"] == "COPY_R")
    try:
        status = bpy.ops.hotools.aux_group_constraint_toggle(key=broken_group["key"])
    except RuntimeError:
        status = {"CANCELLED"}
    assert status == {"CANCELLED"}
    assert not bad_copy.mute and not replacement.mute
    fan_name = BoneFanCore._fan_name(BoneFanCore.AUX_TYPE, "out", 1, 2)
    try:
        boneProperty.AuxBoneRemover.remove(bpy.context, rig, [fan_name, broken.name], True, False)
    except boneProperty.AuxRemovalBlockedError:
        pass
    else:
        raise AssertionError("A damaged adopted declaration must block the entire removal preflight")
    assert rig.data.bones.get(fan_name) is not None
    assert broken.constraints["BrokenCopyR"].as_pointer() == replacement.as_pointer()
    assert broken.constraints["RenamedCopyR"].as_pointer() == bad_copy.as_pointer()
    assert metadata.iter_groups(broken.bone)[0]["members"][0]["constraintName"] == "BrokenCopyR"
    # Explicit metadata reset resolves the test's broken declaration, never raw constraints.
    metadata.reset_aux_info(broken.bone)

    adopted_aim = rig.pose.bones["AimDetach"]
    independent = add_constraint(adopted_aim, "COPY_LOCATION", "KeptPosition", rig)
    aim_a = add_constraint(adopted_aim, "DAMPED_TRACK", "AdoptedAim", rig)
    aim_a.track_axis = "TRACK_X"
    aim_b = add_constraint(adopted_aim, "LOCKED_TRACK", "AdoptedUp", rig, "Up")
    aim_b.track_axis, aim_b.lock_axis = "TRACK_NEGATIVE_Z", "LOCK_X"
    boneProperty.register_existing_aim_pair(adopted_aim)
    aim_toggle = next(group for group in boneProperty._collect_aux_groups(rig.data) if group["auxType"] == "AIM")
    assert bpy.ops.hotools.aux_group_constraint_toggle(key=aim_toggle["key"]) == {"FINISHED"}
    assert aim_a.mute and aim_b.mute and not independent.mute
    detached = boneProperty.AuxBoneRemover.remove(bpy.context, rig, [adopted_aim.name], True, False)
    assert detached["removed_bones"] == 0 and detached["removed_constraints"] == 2
    assert rig.data.bones.get("AimDetach") is not None
    assert [c.name for c in rig.pose.bones["AimDetach"].constraints] == [independent.name]

    # Precise unregister removes only the chosen declaration; it never removes
    # constraints or another generator's metadata and cannot resurrect legacy.
    copy_owner = tag(rig, "CopyROwner", "COPY_R", ("Target",))
    generated = add_constraint(copy_owner, "COPY_ROTATION", "UnregisterCopyR", rig)
    boneProperty._replace_aux_constraints(copy_owner, [generated])
    metadata.register_group(copy_owner, "COPY_ROTATION", [copy_owner.constraints["ManualCopyRotation"]], generator_id="test.unrelated", roles=["rotation"])
    assert metadata.unregister_group(copy_owner.bone, "COPY_ROTATION", generator_id="hotools.aux.copy_r") == 1
    assert [g["generatorId"] for g in metadata.iter_groups(copy_owner.bone)] == ["test.unrelated"]
    assert copy_owner.constraints.get("UnregisterCopyR") is not None
    metadata.unregister_group(copy_owner.bone, "COPY_ROTATION", generator_id="test.unrelated")
    assert metadata.iter_groups(copy_owner.bone) == []

    # Save/reopen preserves declarations. No user file is read or saved.
    expected = metadata.iter_groups(rig.data.bones["TwistOwner"])
    with tempfile.TemporaryDirectory(prefix="hotools_constraint_metadata_") as directory:
        filepath = str(Path(directory) / "metadata.blend")
        bpy.ops.wm.save_as_mainfile(filepath=filepath, check_existing=False)
        bpy.ops.wm.open_mainfile(filepath=filepath)
        rig = bpy.data.objects["MetadataRig"]
        bpy.context.view_layer.objects.active = rig
        assert metadata.iter_groups(rig.data.bones["TwistOwner"]) == expected

    # Clearing identity preserves actual constraints and the unrelated main flag.
    aim = rig.pose.bones["AimOwner"]
    aim.bone.hotools_boneprops.auxBone.aimVersion = 9
    aim.bone.hotools_boneprops.generateMCH = True
    names = [c.name for c in aim.constraints]
    metadata.reset_aux_info(aim.bone)
    assert metadata.iter_groups(aim.bone) == []
    assert aim.bone.hotools_boneprops.auxBone.aimVersion == 1
    assert aim.bone.hotools_boneprops.generateMCH
    assert names == [c.name for c in aim.constraints]

    before_invalidations = len(invalidations)
    result = boneProperty.AuxBoneRemover.remove(bpy.context, rig, ["TwistOwner"], False, False)
    assert result["removed_bones"] == 1 and rig.data.bones.get("TwistOwner") is None
    assert len(invalidations) > before_invalidations
    remaining = boneProperty.AuxBoneRemover.collect_all_aux_names(rig)
    result = boneProperty.AuxBoneRemover.remove(bpy.context, rig, remaining, False, False)
    assert result["removed_bones"] == len(remaining)
    assert boneProperty.AuxBoneRemover.collect_all_aux_names(rig) == []
    assert rig.data.bones.get("Source") is not None
finally:
    metadata._invalidate = old_invalidate
    boneProperty.unregister()
    hoAux.unregister()

# The dependency classes can register again after a complete unregister cycle.
hoAux.register()
boneProperty.register()
boneProperty.unregister()
hoAux.unregister()
print("CONSTRAINT_METADATA_OK", bpy.app.version_string)
