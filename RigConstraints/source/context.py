"""Capture bind frames and conservative channel/animation use facts."""

import json
from typing import Any


def _bone_get(bones: Any, name: str) -> Any | None:
    getter = getattr(bones, "get", None)
    if callable(getter):
        return getter(name)
    for bone in bones:
        if getattr(bone, "name", None) == name:
            return bone
    return None


def capture_binding_context(armature, bones=None):
    """Read current object/bone frames without changing the armature."""
    bones = list(armature.data.bones) if bones is None else list(bones)
    def matrix(value):
        if value is None:
            return []
        return [float(v) for row in value for v in row]
    position_only = _position_only_bones(armature, bones)
    return {
        "space": "BLENDER_ARMATURE", "matrixLayout": "ROW_MAJOR",
        "objectMatrix": matrix(getattr(armature, "matrix_world", None)),
        "bones": [{
            "boneName": b.name,
            "parentBone": str(getattr(getattr(b, "parent", None), "name", "")),
            "restMatrix": matrix(getattr(b, "matrix_local", None)),
            "poseBasis": matrix(getattr(_bone_get(getattr(getattr(armature, "pose", None), "bones", ()), b.name), "matrix_basis", None)),
            "inheritScale": str(getattr(b, "inherit_scale", "FULL")),
            "inheritRotation": bool(getattr(b, "use_inherit_rotation", True)),
            "connected": bool(getattr(b, "use_connect", False)),
            "positionOnly": b.name in position_only,
            "hasPoseAnimation": _has_pose_animation(armature, b.name),
        } for b in bones],
    }


def _has_pose_animation(armature, bone_name):
    anim = getattr(armature, "animation_data", None)
    if anim is None:
        return False
    prefix = 'pose.bones[' + json.dumps(bone_name, ensure_ascii=False) + ']'
    curves = list(getattr(anim, "drivers", ()))
    actions = [getattr(anim, "action", None)]
    actions.extend(getattr(strip, "action", None) for track in getattr(anim, "nla_tracks", ()) for strip in track.strips)
    for action in actions:
        if action is None:
            continue
        curves.extend(getattr(action, "fcurves", ()))
        for layer in getattr(action, "layers", ()):
            for strip in layer.strips:
                for bag in getattr(strip, "channelbags", ()):
                    curves.extend(bag.fcurves)
    return any(getattr(curve, "data_path", "").startswith(prefix) for curve in curves)


def _position_only_bones(armature, bones):
    """Conservative channel-use proof; never infer point semantics from a name."""
    scenes = getattr(armature, "users_scene", None)
    if scenes is None:
        return set()
    names = {b.name for b in bones}
    full = {getattr(getattr(b, "parent", None), "name", "") for b in bones}
    objects = {o.name: o for scene in scenes for o in scene.objects}.values()
    for obj in objects:
        if getattr(obj, "parent", None) == armature and getattr(obj, "parent_type", "") == "BONE":
            full.add(getattr(obj, "parent_bone", ""))
        modifiers = getattr(obj, "modifiers", ())
        if any(getattr(m, "object", None) == armature for m in modifiers):
            if any(getattr(m, "type", "") == "NODES" for m in modifiers):
                return set()
            full.update(getattr(g, "name", "") for g in getattr(obj, "vertex_groups", ()))
        anim = getattr(obj, "animation_data", None)
        for driver in getattr(anim, "drivers", ()):
            for variable in driver.driver.variables:
                for target in variable.targets:
                    if getattr(target, "id", None) == armature:
                        full.add(getattr(target, "bone_target", ""))
    owners = list(getattr(getattr(armature, "pose", None), "bones", ())) + list(objects)
    positional = {"COPY_LOCATION", "DAMPED_TRACK", "LOCKED_TRACK", "STRETCH_TO"}
    for owner in owners:
        for c in getattr(owner, "constraints", ()):
            if getattr(c, "target", None) == armature:
                if getattr(c, "type", "") not in positional or getattr(c, "head_tail", 0) != 0 or getattr(c, "use_bbone_shape", False):
                    full.add(getattr(c, "subtarget", ""))
            for target in getattr(c, "targets", ()):
                if getattr(target, "target", None) == armature:
                    full.add(getattr(target, "subtarget", ""))
    return names - full
