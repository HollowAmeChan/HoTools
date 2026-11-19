"""Retarget normalized Humanoid muscles onto a calibrated Blender skeleton."""

from __future__ import annotations

from math import radians

from mathutils import Matrix, Quaternion, Vector
from Exporter.HumanoidMappingExporter import HumanoidMappingExporter

from . import muscles
from .anim_parser import HumanoidClip


_IDENTITY = Quaternion()
_UNITY_UP = Vector((0.0, 1.0, 0.0))
_UNITY_FORWARD = Vector((0.0, 0.0, 1.0))
_UNITY_RIGHT = Vector((1.0, 0.0, 0.0))
_UNITY_SLOTS = {
    HumanoidMappingExporter.to_unity_human_name(slot): slot
    for slot in ("hips", *(joint.slot for joint in muscles.JOINTS))
}

# Segment masses, used only for the temporary body-centre/root calculation.
_MASSES = {
    "hips": 12.0, "spine": 2.5, "chest": 12.0, "upper_chest": 12.0,
    "neck": 1.0, "head": 4.0,
}
for _side in ("L", "R"):
    for _slot, _mass in (
        ("shoulder", 0.5), ("upper_arm", 2.0), ("lower_arm", 1.5), ("hand", 0.5),
        ("upper_leg", 10.0), ("lower_leg", 4.0), ("foot", 0.8), ("toes", 0.2),
    ):
        _MASSES[f"{_slot}.{_side}"] = _mass


def matrix_from_values(values):
    return Matrix(tuple(
        tuple(float(values[row * 4 + column]) for column in range(4))
        for row in range(4)
    ))


def cached_reference_basis(pose_bone):
    props = getattr(getattr(pose_bone, "bone", None), "hotools_boneprops", None)
    if props is None or not getattr(props, "humanoidTPoseCached", False):
        return None
    return matrix_from_values(props.humanoidTPoseMatrixBasis)


def humanoid_mapping(armature):
    result = {}
    for bone in armature.data.bones:
        props = getattr(bone, "hotools_boneprops", None)
        label = getattr(props, "humanoidMapping", "") if props else ""
        human_name = HumanoidMappingExporter.to_unity_human_name(label)
        slot = _UNITY_SLOTS.get(human_name)
        if slot and slot not in result:
            result[slot] = bone.name
    return result


def clip_readiness(armature):
    if armature is None or armature.type != "ARMATURE":
        return False, "请先选择人型骨架", 0, 0
    mapping = humanoid_mapping(armature)
    calibrated = sum(
        cached_reference_basis(pose_bone) is not None
        for pose_bone in armature.pose.bones
    )
    if not mapping:
        return False, "请先为骨架填写 Humanoid 映射", 0, calibrated
    if not calibrated:
        return False, "请先保存 T-Pose 标定", len(mapping), 0
    if any(slot not in mapping for slot in ("hips", "spine", "head")):
        return False, "Humanoid 映射需要包含 Hips、Spine 和 Head", len(mapping), calibrated
    if not all(
        mapping.get(f"shoulder.{side}") or mapping.get(f"upper_arm.{side}")
        for side in ("L", "R")
    ):
        return False, "Humanoid 映射需要包含左右肩或上臂", len(mapping), calibrated
    if any(cached_reference_basis(armature.pose.bones[name]) is None
           for name in mapping.values()):
        return False, "映射骨骼的 T-Pose 缓存不完整，请重新保存标定", len(mapping), calibrated
    return True, "", len(mapping), calibrated


def has_supported_curves(armature, clip):
    mapping = humanoid_mapping(armature)
    if mapping.get("hips") and any(
        name.startswith(("RootT.", "RootQ.")) for name in clip.curves
    ):
        return True
    return any(
        joint.slot in mapping and any(channel in clip.curves for channel in joint.channels)
        for joint in muscles.JOINTS
    )


def _normalized(vector, fallback=None):
    return vector.normalized() if vector.length > 1e-7 else fallback


def anatomical_axes(armature, mapping):
    def bone(slot):
        return armature.pose.bones.get(mapping.get(slot, ""))

    hips, head = bone("hips"), bone("head")
    left = bone("shoulder.L") or bone("upper_arm.L")
    right = bone("shoulder.R") or bone("upper_arm.R")
    side = _normalized(right.head - left.head)
    if side is None:
        raise ValueError("左右肩的位置重合，无法推算人型坐标轴")
    # The pelvis-to-spine segment is usually upright even when the neck or
    # ankles are offset in depth.
    spine = bone("spine")
    pelvis_up = spine.head - hips.head
    leg_up = Vector()
    for suffix in (".L", ".R"):
        upper, lower = bone("upper_leg" + suffix), bone("lower_leg" + suffix)
        foot = bone("foot" + suffix)
        if upper and foot:
            leg_up += upper.head - foot.head
        elif upper and lower:
            leg_up += upper.head - lower.head
    torso_up = head.head - hips.head
    if pelvis_up.length > 1e-6 and pelvis_up.normalized().dot(torso_up.normalized()) > 0.5:
        raw_up = pelvis_up
    else:
        raw_up = leg_up if leg_up.length > 1e-6 else torso_up
    up = _normalized(raw_up - side * raw_up.dot(side))
    if up is None:
        raise ValueError("无法从 T-Pose 推算人型坐标轴")
    # Unity uses a left-handed coordinate system. In Blender the model's
    # forward is up x right, not right x up.
    forward = up.cross(side).normalized()
    return {"right": side, "up": up, "forward": forward}


def _to_unity_rotation(rotation, conversion):
    return (conversion @ rotation.to_matrix() @ conversion.transposed()).to_quaternion()


def _from_unity_rotation(rotation, conversion):
    return (conversion.transposed() @ rotation.to_matrix() @ conversion).to_quaternion()


def _frame(direction, secondary):
    x = direction.normalized()
    y = _normalized(secondary - x * secondary.dot(x))
    if y is None:
        y = _normalized(_UNITY_FORWARD - x * _UNITY_FORWARD.dot(x))
    if y is None:
        y = _normalized(_UNITY_RIGHT - x * _UNITY_RIGHT.dot(x))
    return Matrix((x, y, x.cross(y).normalized())).transposed().to_quaternion()


def _joint_frame(joint, points, tails):
    slot = joint.slot
    suffix = slot[-2:] if slot.endswith((".L", ".R")) else ""
    left = suffix == ".L"
    direction = None
    children = {
        "spine": ("chest", "upper_chest", "neck", "head"),
        "chest": ("upper_chest", "neck", "head"),
        "upper_chest": ("neck", "head"),
        "neck": ("head",),
    }
    base = slot[:-2] if suffix else slot
    child_base = {
        "shoulder": "upper_arm", "upper_arm": "lower_arm", "lower_arm": "hand",
        "upper_leg": "lower_leg", "lower_leg": "foot",
    }.get(base)
    candidates = children.get(slot, ())
    if child_base:
        candidates = (child_base + suffix,)
    if "_" in base:
        finger, segment = base.split("_", 1)
        if finger in {"thumb", "index", "middle", "ring", "little"}:
            next_segment = {"proximal": "intermediate", "intermediate": "distal"}.get(segment)
            if next_segment:
                candidates = (finger + "_" + next_segment + suffix,)
            elif segment == "distal":
                parent = finger + "_intermediate" + suffix
                if parent in points:
                    direction = points[slot] - points[parent]
    for child in candidates:
        if child in points:
            direction = points[child] - points[slot]
            break
    if direction is None:
        direction = tails[slot] - points[slot]
    if direction.length < 1e-7:
        direction = _UNITY_UP.copy()

    kind = joint.frame
    if kind == "torso":
        return _frame(_UNITY_UP if slot == "head" else direction, -_UNITY_FORWARD)
    if kind == "leg":
        return _frame(direction, -_UNITY_FORWARD)
    if kind == "foot":
        return _frame(-_UNITY_UP, -_UNITY_FORWARD)
    if kind == "face":
        return _frame(_UNITY_FORWARD, -_UNITY_UP)
    if kind == "forearm":
        return _frame(direction, _UNITY_FORWARD if left else -_UNITY_FORWARD)
    if kind == "thumb":
        return _frame(direction, _UNITY_UP.cross(direction))
    if kind == "hand":
        parent = "lower_arm" + suffix
        if parent in points:
            direction = points[slot] - points[parent]
    return _frame(direction, -_UNITY_UP if left else _UNITY_UP)


def _reference_rotation(joint, frame):
    if joint.frame not in {"finger", "thumb"}:
        return muscles.swing_twist(joint.reference)
    finger, segment_side = joint.slot.split("_", 1)
    segment, side = segment_side.split(".")
    mirror = 1 if side == "L" else -1
    # Unity's open-hand offsets are quaternion tangent vectors in the palm
    # frame, rather than a fixed flexion angle about each finger's own axis.
    # Expressing them in the measured finger frame also handles splayed
    # fingers and a thumb that is oblique to the palm.
    if finger == "thumb":
        tangent = (
            (-_UNITY_UP - _UNITY_FORWARD) * (0.125 * mirror)
            if segment == "proximal" else _UNITY_UP * (0.2 * mirror)
        )
    elif segment == "proximal":
        spread = {"index": -0.08, "middle": -0.04, "ring": 0.04, "little": 0.08}[finger]
        tangent = (_UNITY_UP * spread - _UNITY_FORWARD * 0.3) * mirror
    else:
        tangent = _UNITY_FORWARD * (-0.33 * mirror)
    local = frame.inverted() @ tangent
    return Quaternion((1.0, *local)).normalized()


def _pose_matrix(pose_bone, basis, parent_matrix=None):
    kwargs = {}
    if pose_bone.parent:
        kwargs = {
            "parent_matrix": parent_matrix,
            "parent_matrix_local": pose_bone.parent.bone.matrix_local,
        }
    return pose_bone.bone.convert_local_to_pose(basis, pose_bone.bone.matrix_local, **kwargs)


def _basis_matrix(pose_bone, matrix, parent_matrix=None):
    kwargs = {}
    if pose_bone.parent:
        kwargs = {
            "parent_matrix": parent_matrix,
            "parent_matrix_local": pose_bone.parent.bone.matrix_local,
        }
    return pose_bone.bone.convert_local_to_pose(matrix, pose_bone.bone.matrix_local,
                                              invert=True, **kwargs)


def _evaluate(armature, bases):
    poses = {}
    for bone in armature.pose.bones:
        poses[bone.name] = _pose_matrix(
            bone, bases[bone.name], poses.get(bone.parent.name) if bone.parent else None
        )
    return poses


def _mass_points(mapping):
    result = []
    for slot, mass in _MASSES.items():
        target = slot
        if slot == "upper_chest" and slot not in mapping:
            target = "chest" if "chest" in mapping else "spine"
        if slot == "chest" and slot not in mapping:
            target = "spine"
        if target not in mapping:
            continue
        base, _, side = target.partition(".")
        child_slot = {
            "spine": "chest", "chest": "upper_chest", "upper_chest": "neck",
            "neck": "head", "shoulder": "upper_arm", "upper_arm": "lower_arm",
            "lower_arm": "hand", "upper_leg": "lower_leg", "lower_leg": "foot",
        }.get(base)
        if child_slot in {"chest", "upper_chest"} and child_slot not in mapping:
            child_slot = "neck" if "neck" in mapping else "head"
        if child_slot and side:
            child_slot += "." + side
        name = mapping[target]
        child = mapping.get(child_slot) if child_slot else None
        result.append((name, child, mass))
    return result


def _body_centre(poses, mass_points):
    centre = Vector()
    total = 0.0
    for name, child, mass in mass_points:
        point = poses[name].translation
        if child:
            point = (point + poses[child].translation) * 0.5
        centre += point * mass
        total += mass
    return centre / total if total else Vector()


def _body_frame(mapping, poses, axes):
    def point(*slots):
        for slot in slots:
            if slot in mapping:
                return poses[mapping[slot]].translation
        return None
    left = point("upper_arm.L", "shoulder.L")
    right = point("upper_arm.R", "shoulder.R")
    left_hip, right_hip = point("upper_leg.L"), point("upper_leg.R")
    pelvis = (left_hip + right_hip) * 0.5 if left_hip is not None and right_hip is not None else point("hips")
    up = _normalized((left + right) * 0.5 - pelvis, axes["up"])
    side = right - left
    if left_hip is not None and right_hip is not None:
        side += right_hip - left_hip
    side = _normalized(side - up * side.dot(up), axes["right"])
    return Matrix((side, up, up.cross(side).normalized())).transposed()


def build_reference_state(armature, clip: HumanoidClip):
    ready, message, _mapping_count, _calibrated_count = clip_readiness(armature)
    if not ready:
        raise ValueError(message)
    mapping = humanoid_mapping(armature)
    bases = {
        bone.name: cached_reference_basis(bone) or bone.matrix_basis.copy()
        for bone in armature.pose.bones
    }
    references = _evaluate(armature, bases)
    for bone in armature.pose.bones:
        bone.matrix_basis = bases[bone.name]
    import bpy
    bpy.context.view_layer.update()
    axes = anatomical_axes(armature, mapping)
    conversion = Matrix((axes["right"], axes["up"], axes["forward"]))
    unity_rotations = {
        name: _to_unity_rotation(matrix.to_quaternion(), conversion)
        for name, matrix in references.items()
    }
    points = {slot: conversion @ references[name].translation for slot, name in mapping.items()}
    tails = {
        slot: conversion @ (references[name] @ Vector((0, armature.data.bones[name].length, 0)))
        for slot, name in mapping.items()
    }
    joints = {}
    for joint in muscles.JOINTS:
        name = mapping.get(joint.slot)
        if not name:
            continue
        bone = armature.pose.bones[name]
        frame = _joint_frame(joint, points, tails)
        post = unity_rotations[name].inverted() @ frame
        parent_rotation = unity_rotations[bone.parent.name] if bone.parent else _IDENTITY
        reference_q = _reference_rotation(joint, frame)
        pre = parent_rotation.inverted() @ frame @ reference_q.inverted()
        joints[joint.slot] = {
            "spec": joint, "name": name, "pre": pre, "post": post,
            "local_reference": parent_rotation.inverted() @ unity_rotations[name],
        }
    mass_points = _mass_points(mapping)
    centre = _body_centre(references, mass_points)
    floor_points = [
        points[slot].y for slot in ("toes.L", "toes.R", "foot.L", "foot.R")
        if slot in points
    ]
    height = (references[mapping["head"]].translation - references[mapping["hips"]].translation).length
    floor = min(floor_points) if floor_points else centre.dot(axes["up"]) - height * 2.0
    scale = max(1e-5, centre.dot(axes["up"]) - floor)
    return {
        "bases": bases, "references": references, "mapping": mapping, "axes": axes,
        "conversion": conversion, "joints": joints, "mass_points": mass_points,
        "body_centre": centre, "rig_scale": scale, "clip": clip,
        "body_frame_reference": _body_frame(mapping, references, axes),
        "basis_parts": {name: basis.decompose() for name, basis in bases.items()},
    }


def _body_orientation(state, poses):
    """The body frame spans the hip and shoulder joints, rather than Hips."""
    frame = _body_frame(state["mapping"], poses, state["axes"])
    return (frame @ state["body_frame_reference"].transposed()).to_quaternion()


def apply_sample(armature, state, sample, muscle_scale=1.0):
    conversion = state["conversion"]
    bases = {name: basis.copy() for name, basis in state["bases"].items()}
    angles = {
        slot: list(muscles.angles_for_sample(data["spec"], sample))
        for slot, data in state["joints"].items()
    }
    for absent, fallbacks in (
        ("upper_chest", ("chest", "spine")), ("chest", ("spine",)),
    ):
        fallback = next((slot for slot in fallbacks if slot in angles), None)
        if absent not in state["joints"] and fallback is not None:
            extra = muscles.angles_for_sample(muscles.BY_SLOT[absent], sample)
            angles[fallback] = [a + b for a, b in zip(angles[fallback], extra)]
    for slot, data in state["joints"].items():
        joint = data["spec"]
        dof = angles[slot].copy()
        if slot in muscles.TWIST_SLOTS:
            dof[0] *= 0.5
        local = data["pre"] @ muscles.swing_twist(dof) @ data["post"].inverted()
        parent = state["joints"].get(joint.twist_parent)
        if parent is not None:
            extra = Quaternion((1.0, 0.0, 0.0), radians(angles[joint.twist_parent][0] * 0.5))
            local = parent["post"] @ extra @ parent["post"].inverted() @ local
        delta = data["local_reference"].inverted() @ local
        delta = _from_unity_rotation(delta, conversion)
        if muscle_scale != 1.0:
            delta = _IDENTITY.slerp(delta, muscle_scale)
        location, rotation, scale = state["basis_parts"][data["name"]]
        bases[data["name"]] = Matrix.LocRotScale(location, rotation @ delta, scale)

    poses = _evaluate(armature, bases)
    hips_name = state["mapping"]["hips"]
    hips = armature.pose.bones[hips_name]
    parent_pose = poses.get(hips.parent.name) if hips.parent else None
    if all(f"RootQ.{axis}" in sample for axis in "xyzw"):
        root = Quaternion(tuple(sample[f"RootQ.{axis}"] for axis in "wxyz"))
        if root.magnitude > 1e-7:
            desired = _from_unity_rotation(root.normalized(), conversion)
            correction = desired @ _body_orientation(state, poses).inverted()
            location, rotation, scale = poses[hips_name].decompose()
            poses[hips_name] = Matrix.LocRotScale(location, correction @ rotation, scale)
            bases[hips_name] = _basis_matrix(hips, poses[hips_name], parent_pose)
            poses = _evaluate(armature, bases)

    if any(f"RootT.{axis}" in sample for axis in "xyz"):
        root_translation = Vector((
            sample.get("RootT.x", 0.0), sample.get("RootT.y", 1.0) - 1.0,
            sample.get("RootT.z", 0.0),
        ))
        desired = state["body_centre"] + conversion.transposed() @ root_translation * state["rig_scale"]
        translation = desired - _body_centre(poses, state["mass_points"])
        matrix = poses[hips_name].copy()
        matrix.translation += translation
        bases[hips_name] = _basis_matrix(hips, matrix, parent_pose)
    for bone in armature.pose.bones:
        bone.matrix_basis = bases[bone.name]
    armature.update_tag(refresh={"OBJECT"})
    import bpy
    bpy.context.view_layer.update()
