"""Negative review cases for declarations, shared caches and raw copyR gating."""

import json
import sys
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, PointerProperty
from bpy.types import PropertyGroup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from BoneTools.boneProperty import PG_Hotools_BoneRef, PG_Hotools_AuxBoneInfo
from RigConstraints.blender.properties import PROPERTY_CLASSES, PG_RigConstraintGroup
from RigConstraints.blender import metadata, review, review_ui
from RigConstraints.source import capture_armature


class LargeInfo(PropertyGroup):
    isHoAuxBone: BoolProperty(default=False)


class EdgeProps(PropertyGroup):
    auxBone: PointerProperty(type=PG_Hotools_AuxBoneInfo)
    constraintGroups: CollectionProperty(type=PG_RigConstraintGroup)
    generateMCH: BoolProperty(default=False)
    hoAux: PointerProperty(type=LargeInfo)


for cls in (PG_Hotools_BoneRef, PG_Hotools_AuxBoneInfo, *PROPERTY_CLASSES, LargeInfo, EdgeProps):
    bpy.utils.register_class(cls)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=EdgeProps)
rig = bpy.data.objects.new("ReviewEdges", bpy.data.armatures.new("ReviewEdgesData"))
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
for index, name in enumerate(("Target", "Owner", "Excluded", "Standalone")):
    bone = rig.data.edit_bones.new(name)
    bone.head, bone.tail = (index * .3, 0, 0), (index * .3, 1, .2)
bpy.ops.object.mode_set(mode="OBJECT")


def add(owner, kind="COPY_ROTATION", target="Target"):
    constraint = rig.pose.bones[owner].constraints.new(kind)
    constraint.target, constraint.subtarget = rig, target
    return constraint


def declare(owner, constraint, generator="hotools.aux.copy_r"):
    return metadata.register_group(rig.pose.bones[owner], "COPY_ROTATION", [constraint],
                                   generator_id=generator, roles=["rotation"])


results = {}

# Unregistered raw Copy Rotation never becomes a copyR through a name heuristic.
c1 = add("Owner")
c1.name = "HoTools_COPY_R_CopyRotation"
report = review.scan(rig)
results["raw_copy_rotation_gate"] = not report["known"] and any(row["ownerBone"] == "Owner" for row in report["unknown"])

# The semantic definition admits explicit registered copyR generators only.
declare("Owner", c1, "unregistered.generator")
report = review.scan(rig)
results["copy_r_generator_gate"] = bool(report["broken"]) and not report["known"]
metadata.clear_groups(rig.data.bones["Owner"])

# Two groups sharing the same owner-local group identity are corrupt even when
# they reference disjoint constraints; duplicate membership is a separate case.
declare("Owner", c1)
c2 = add("Owner")
c2.name = "SecondCopyRotation"
groups = rig.data.bones["Owner"].hotools_boneprops.constraintGroups
first = metadata.iter_groups(rig.data.bones["Owner"])[0]
duplicate = groups.add()
for name in ("groupId", "semanticType", "semanticVersion", "generatorId", "evidence", "ownsBone"):
    setattr(duplicate, name, first[name])
member = duplicate.members.add()
member.constraintName, member.constraintType, member.role, member.order = c2.name, "COPY_ROTATION", "rotation", 0
report = review.scan(rig)
results["duplicate_group_identity"] = bool(report["broken"]) and not report["known"]

# A forged groupId cannot make two entries for the same generator distinct.
duplicate.groupId = "different_identity"
report = review.scan(rig)
results["duplicate_generator_identity"] = bool(report["broken"]) and not report["known"]

# Reusing one actual source in two different declarations is always diagnosed.
duplicate.groupId = "different_identity"
duplicate.generatorId = "another_generator"
duplicate.members[0].constraintName = c1.name
report = review.scan(rig)
results["duplicate_source_membership"] = bool(report["broken"]) and not report["known"]
metadata.clear_groups(rig.data.bones["Owner"])

# Cache objects remain separate, but a shared declaration write invalidates all
# objects whose data contains the edited Bone metadata.
declare("Owner", c1)
other = bpy.data.objects.new("SharedReviewEdges", rig.data)
bpy.context.scene.collection.objects.link(other)
bpy.context.view_layer.update()
review.scan(rig)
review.scan(other)
assert review.cached(rig) is not review.cached(other)
declare("Owner", c1)
results["shared_metadata_write_invalidates_all"] = review.cached(rig) is None and review.cached(other) is None
review.scan(rig)
review.scan(other)
metadata.clear_groups(rig.data.bones["Owner"])
results["data_invalidation_clears_shared_reports"] = review.cached(rig) is None and review.cached(other) is None

# A required target missing from a declared copyR is broken, not silently raw.
declare("Owner", c1)
c1.target = None
report = review.scan(rig)
results["declared_missing_target"] = any(row["ownerBone"] == "Owner" and "目标对象缺失" in row["message"] for row in report["broken"])
c1.target = rig
missing_name = metadata.iter_groups(rig.data.bones["Owner"])[0]["members"][0]["constraintName"]
c1.name = "UserRenamed"
report = review.scan(rig)
results["rename_keeps_broken_evidence"] = any(row["ownerBone"] == "Owner" and missing_name in row["message"] for row in report["broken"])

# Large HoAux owner constraints and declarations are completely outside this
# ordinary scanner, even if their ordinary metadata is independently corrupt.
excluded = rig.data.bones["Excluded"]
excluded.hotools_boneprops.hoAux.isHoAuxBone = True
cx = add("Excluded")
declare("Excluded", cx)
excluded.hotools_boneprops.constraintGroups[0].semanticVersion = 99
cx.target = None
report = review.scan(rig)
results["large_hoaux_owners_excluded"] = report["excludedCount"] == 1 and all(
    row["ownerBone"] != "Excluded" for category in ("known", "broken", "unknown") for row in report[category])

# Scan changes neither actual source facts nor persistent declaration metadata.
before = capture_armature(rig)
review.scan(rig)
after = capture_armature(rig)
for snapshot in (before, after):
    snapshot.pop("exportTime", None)
    snapshot.pop("inputFingerprint", None)
results["scan_is_read_only"] = before == after

# Drawing only consumes an existing report. No scans or authoring writes occur.
class Layout:
    def operator(self, *args, **kwargs):
        return self
    def label(self, *args, **kwargs):
        pass
    def panel(self, *args, **kwargs):
        return self, self
    def box(self):
        return self
    def row(self, *args, **kwargs):
        return self


from types import SimpleNamespace
original_scan = review.scan
review.scan = lambda _owner: (_ for _ in ()).throw(AssertionError("draw called scan"))
try:
    review_ui.draw_review(Layout(), SimpleNamespace(object=rig))
    results["draw_uses_cache_only"] = True
finally:
    review.scan = original_scan

print("CONSTRAINT_REVIEW_EDGE_RESULTS", json.dumps(results, sort_keys=True))
failures = [name for name, passed in results.items() if not passed]
assert not failures, "Review edge regressions: " + ", ".join(failures)
print("CONSTRAINT_REVIEW_EDGES_OK", bpy.app.version_string)
