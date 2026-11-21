"""Read-only ordinary constraint review and authoring facts in real Blender."""

import json
import sys
from pathlib import Path
import bpy
from bpy.props import BoolProperty, CollectionProperty, PointerProperty
from bpy.types import PropertyGroup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from BoneTools.boneProperty import PG_Hotools_BoneRef, PG_Hotools_AuxBoneInfo
from RigConstraints.blender.properties import PROPERTY_CLASSES, PG_RigConstraintGroup
from RigConstraints.blender.metadata import _replace_aux_constraints, register_group
from RigConstraints.blender import review, review_ui
from RigConstraints.source import capture_armature
from RigConstraints.semantics import translate
from RigConstraints.codec import dumps, loads


class LargeExcluded(PropertyGroup):
    isHoAuxBone: BoolProperty(default=False)


class Props(PropertyGroup):
    auxBone: PointerProperty(type=PG_Hotools_AuxBoneInfo)
    constraintGroups: CollectionProperty(type=PG_RigConstraintGroup)
    generateMCH: BoolProperty(default=False)
    hoAux: PointerProperty(type=LargeExcluded)


for cls in (PG_Hotools_BoneRef, PG_Hotools_AuxBoneInfo, *PROPERTY_CLASSES, LargeExcluded, Props):
    bpy.utils.register_class(cls)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=Props)
rig = bpy.data.objects.new("ReviewRig", bpy.data.armatures.new("ReviewData"))
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
for index, name in enumerate(("P", "R", "U", "Twist", "Aim", "CopyR", "Raw", "Large")):
    b = rig.data.edit_bones.new(name)
    b.head, b.tail = (index, 0, 0), (index, 1, 0)
bpy.ops.object.mode_set(mode="OBJECT")


def add(owner, kind, target="R"):
    c = rig.pose.bones[owner].constraints.new(kind)
    if hasattr(c, "target"):
        c.target, c.subtarget = rig, target
    return c


def tag(owner, kind, targets):
    aux = rig.data.bones[owner].hotools_boneprops.auxBone
    aux.isAuxBone, aux.auxType = True, kind
    for name in targets:
        aux.sourceBones.add().name = name


tag("Twist", "TWIST", ["R"])
cr, st = add("Twist", "COPY_ROTATION"), add("Twist", "STRETCH_TO")
_replace_aux_constraints(rig.pose.bones["Twist"], [cr, st])
tag("Aim", "AIM", ["R", "U"])
a, u = add("Aim", "DAMPED_TRACK"), add("Aim", "LOCKED_TRACK", "U")
a.track_axis, u.track_axis, u.lock_axis = "TRACK_X", "TRACK_NEGATIVE_Z", "LOCK_X"
_replace_aux_constraints(rig.pose.bones["Aim"], [a, u])
cp = add("CopyR", "COPY_ROTATION")
register_group(rig.pose.bones["CopyR"], "COPY_ROTATION", [cp], generator_id="hotools.aux.copy_r", roles=["rotation"])
add("Raw", "COPY_ROTATION")
add("Raw", "LIMIT_ROTATION")
rig.data.bones["Large"].hotools_boneprops.hoAux.isHoAuxBone = True
add("Large", "COPY_ROTATION")
rig.data.bones["P"].hotools_boneprops.generateMCH = True

before = dumps(capture_armature(rig))
report = review.scan(rig)
after = capture_armature(rig)
assert loads(before)["sources"] == after["sources"]
assert loads(before)["declarations"] == after["declarations"]
assert len(report["known"]) == 3 and len(report["unknown"]) == 2, report
assert not report["broken"] and report["excludedCount"] == 1
assert report["mchPlans"] == ["P"]
assert loads(dumps(report["document"]))["semantics"] == report["document"]["semantics"]

# User-adjustable scalar weight and mute keep ordinary Twist structurally valid.
cr.influence, cr.mute = .3, True
assert not review.scan(rig)["broken"]
# Wrong order is reported, without modifying the real stack or declaration.
rig.pose.bones["Twist"].constraints.move(1, 0)
assert any("相邻且有序" in row["message"] for row in review.scan(rig)["broken"])
rig.pose.bones["Twist"].constraints.move(0, 1)
# A renamed member does not silently attach to another constraint of that type.
cp.name = "Renamed by user"
report = review.scan(rig)
assert any(row["ownerBone"] == "CopyR" and "缺少成员" in row["message"] for row in report["broken"])
assert cp.name == "Renamed by user"
# Cache belongs to Object; a shared datablock does not share poses or reviews.
other = bpy.data.objects.new("SharedReview", rig.data)
bpy.context.scene.collection.objects.link(other)
bpy.context.view_layer.update()
assert review.cached(other) is None
review.scan(other)
review.invalidate(rig.data)
assert review.cached(rig) is None and review.cached(other) is None
review.scan(rig)
review.invalidate(rig)
assert review.cached(rig) is None
review_ui.register()
assert hasattr(bpy.types, "DATA_PT_Hotools_ConstraintReview")
review_ui.unregister()
print("CONSTRAINT_REVIEW_OK", bpy.app.version_string)
