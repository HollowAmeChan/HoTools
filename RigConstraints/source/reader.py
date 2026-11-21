"""Source facts are captured once, before export rewrites their bindings."""

from ..codec import fingerprint
from ..model import new_document
from .constraint import capture_constraint
from .context import capture_binding_context


def excluded_bone(bone):
    props = getattr(bone, "hotools_boneprops", None)
    large = getattr(props, "hoAux", None)
    return bool(getattr(large, "isHoAuxBone", False))


def _version():
    try:
        import bpy
        return ".".join(str(v) for v in bpy.app.version)
    except ImportError:
        return ""


def capture_armature(armature, *, capture_stage="AUTHORING"):
    """Read v4 facts and explicit declarations without rewriting author data."""
    from ..blender.metadata import iter_groups
    if getattr(armature, "type", None) != "ARMATURE":
        raise ValueError("Select an armature object")
    if getattr(armature, "pose", None) is None:
        raise ValueError("骨架姿态尚未初始化；请更新场景后重试")
    doc = new_document(armature.name, _version(), capture_stage)
    bones = list(armature.data.bones)
    doc["sourceContext"] = capture_binding_context(armature, bones)
    doc["declarations"] = []
    doc["mchPlans"] = [b.name for b in bones if not excluded_bone(b)
                       and getattr(getattr(b, "hotools_boneprops", None), "generateMCH", False)]
    doc["excludedOwners"] = [b.name for b in bones if excluded_bone(b)]
    owners = [("OBJECT", armature.name, armature)]
    owners += [("BONE", p.name, p) for p in sorted(armature.pose.bones, key=lambda b: b.name)
               if not excluded_bone(p.bone)]
    for kind, name, owner in owners:
        by_name = {}
        for index, constraint in enumerate(getattr(owner, "constraints", ())):
            sid = "c" + str(len(doc["sources"]))
            by_name[constraint.name] = sid
            doc["sources"].append({
                "sourceId": sid, "ownerBone": name, "ownerKind": kind,
                "captureStage": capture_stage,
                "constraint": capture_constraint(constraint, armature, index),
            })
        if kind == "BONE":
            aux = getattr(getattr(owner.bone, "hotools_boneprops", None), "auxBone", None)
            for group in iter_groups(owner.bone, pose_bone=owner):
                declaration = dict(group)
                declaration["ownerBone"] = name
                declaration["auxType"] = str(getattr(aux, "auxType", "") or "")
                declaration["sourceBones"] = [r.name for r in getattr(aux, "sourceBones", ())]
                declaration["memberSourceIds"] = [by_name.get(m.get("constraintName", ""), "")
                                                   for m in group.get("members", ())]
                doc["declarations"].append(declaration)
    doc["inputFingerprint"] = fingerprint(doc)
    return doc
