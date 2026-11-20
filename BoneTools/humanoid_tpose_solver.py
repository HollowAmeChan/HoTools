"""Humanoid reference-pose correction matching Unity's Enforce T-Pose behavior.

Directions, tolerances and traversal follow AvatarSetupTool's public behavior;
the Blender adapter reads mapped joint positions rather than bone display axes.
All calculations use the HoFBX Unity world frame. No Unity runtime is required.
"""
from math import acos, degrees

import bpy
from mathutils import Matrix, Quaternion, Vector
from Exporter.HumanoidMappingExporter import HumanoidMappingExporter


_FRAME = Matrix(((-1, 0, 0), (0, 0, 1), (0, -1, 0)))
_IDENTITY = Quaternion()
_AXES = tuple(Vector(axis) for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
_ORDER = [
    "Hips", "LeftUpperLeg", "RightUpperLeg", "LeftLowerLeg", "RightLowerLeg",
    "LeftFoot", "RightFoot", "Spine", "Chest", "Neck", "Head",
    "LeftShoulder", "RightShoulder", "LeftUpperArm", "RightUpperArm",
    "LeftLowerArm", "RightLowerArm", "LeftHand", "RightHand", "LeftToes", "RightToes",
    "LeftEye", "RightEye", "Jaw",
]
_PARENTS = {
    "Spine": "Hips", "Chest": "Spine", "UpperChest": "Chest", "Neck": "UpperChest", "Head": "Neck",
    "LeftEye": "Head", "RightEye": "Head", "Jaw": "Head",
}
# rule = (target direction, angular tolerance in degrees, global frame,
#         optional comparison-plane normal, optional preferred child slots)
_RULES = {
    "Hips": ((0, 1, 0), 15, True, None, None),
    "Spine": ((0, 1, 0), 30, True, None, ("Chest", "UpperChest", "Neck", "Head")),
    "Chest": ((0, 1, 0), 30, True, None, ("UpperChest", "Neck", "Head")),
    "Neck": ((0, 1, 0), 30, True, None, None),
    "UpperChest": ((0, 1, 0), 30, True, None, ("Neck", "Head")),
}
for _side, _sign in (("Left", -1), ("Right", 1)):
    for _child, _parent in (("UpperLeg", "Hips"), ("LowerLeg", "UpperLeg"), ("Foot", "LowerLeg"),
                            ("Toes", "Foot"), ("Shoulder", "UpperChest"), ("UpperArm", "Shoulder"),
                            ("LowerArm", "UpperArm"), ("Hand", "LowerArm")):
        _PARENTS[_side + _child] = _parent if _parent in {"Hips", "UpperChest"} else _side + _parent
    _RULES.update({
        _side + "UpperLeg": ((.05 * _sign, -1, 0), 15, True, None, None),
        _side + "LowerLeg": ((.05 * _sign, -1, -.15), 20, True, None, None),
        _side + "Foot": ((.05 * _sign, 0, 1), 20, True, (0, 1, 0), None),
        _side + "Shoulder": ((_sign, 0, 0), 20, True, None, None),
        _side + "UpperArm": ((_sign, 0, 0), 5, True, None, None),
        _side + "LowerArm": ((_sign, 0, 0), 5, True, None, None),
        _side + "Hand": ((_sign, 0, 0), 10, False, (0, 0, 1), (_side + " Middle Proximal",)),
    })
    for _finger in ("Thumb", "Index", "Middle", "Ring", "Little"):
        for _segment, _parent in (("Proximal", _side + "Hand"),
                                 ("Intermediate", f"{_side} {_finger} Proximal"),
                                 ("Distal", f"{_side} {_finger} Intermediate")):
            _slot = f"{_side} {_finger} {_segment}"
            _ORDER.append(_slot)
            _PARENTS[_slot] = _parent
            _RULES[_slot] = ((_sign, 0, 1 if _finger == "Thumb" else 0),
                             10 if _segment == "Proximal" else 5, False, None, None)
_ORDER.append("UpperChest")
_FIRST_CHILD = {parent: next(slot for slot in _ORDER if _PARENTS.get(slot) == parent)
                for parent in set(_PARENTS.values())}


def mapped_bones(armature):
    result = {}
    for bone in armature.pose.bones:
        props = getattr(bone.bone, "hotools_boneprops", None)
        slot = HumanoidMappingExporter.to_unity_human_name(getattr(props, "humanoidMapping", ""))
        if slot and slot not in result:
            result[slot] = bone
    return result


def _unit(vector):
    return vector.normalized() if vector.length_squared > 1e-15 else Vector()


def _angle(a, b):
    length = a.length * b.length
    return degrees(acos(max(-1.0, min(1.0, a.dot(b) / length)))) if length > 1e-15 else 0.0


def _interpolate_adjustment(rotation, amount):
    # Unity's native Quaternion.Slerp normalizes a linear interpolation when
    # dot(identity, rotation) >= .95. Blender's spherical branch otherwise
    # differs by up to hundredths of a degree on the thumb correction.
    if rotation.w < 0:
        rotation = -rotation
    if rotation.w < .95:
        return _IDENTITY.slerp(rotation, amount)
    return Quaternion((1.0 + (rotation.w - 1.0) * amount,
                       rotation.x * amount, rotation.y * amount, rotation.z * amount)).normalized()


class _Pose:
    def __init__(self, armature):
        self.armature = armature
        self.bones = mapped_bones(armature)

    def point(self, slot):
        return _FRAME @ (self.armature.matrix_world @ self.bones[slot].head)

    def rotation(self, slot):
        rotation = (self.armature.matrix_world @ self.bones[slot].matrix).to_quaternion().to_matrix()
        return (_FRAME @ rotation @ _FRAME.transposed()).to_quaternion()

    def set_rotation(self, slot, rotation):
        bone = self.bones[slot]
        location, _, scale = (self.armature.matrix_world @ bone.matrix).decompose()
        converted = (_FRAME.transposed() @ rotation.to_matrix() @ _FRAME).to_quaternion()
        bone.matrix = self.armature.matrix_world.inverted() @ Matrix.LocRotScale(location, converted, scale)
        bpy.context.view_layer.update()

    def move(self, slot, offset):
        bone = self.bones[slot]
        matrix = bone.matrix.copy()
        matrix.translation += self.armature.matrix_world.inverted().to_3x3() @ (_FRAME.transposed() @ offset)
        bone.matrix = matrix
        bpy.context.view_layer.update()

    def direction(self, slot):
        rule = _RULES.get(slot)
        if rule is None or slot not in self.bones:
            return Vector()
        children = rule[4]
        child = (next((name for name in children if name in self.bones), None)
                 if children is not None else _FIRST_CHILD.get(slot))
        if child in self.bones:
            return _unit(self.point(child) - self.point(slot))
        bone = self.bones[slot]
        if len(bone.children) == 1:
            target = bone.children[0].head
        elif not bone.children:
            # Blender's explicit tail is the terminal child exported by HoFBX.
            target = bone.tail
        else:
            return Vector()
        return _unit(_FRAME @ (self.armature.matrix_world.to_3x3() @ (target - bone.head)))

    def orientation(self):
        names = ("LeftUpperLeg", "RightUpperLeg", "LeftUpperArm", "RightUpperArm")
        if not all(slot in self.bones for slot in names):
            return _IDENTITY.copy()
        left_leg, right_leg, left_arm, right_arm = (self.point(slot) for slot in names)
        lateral = _unit(_unit(right_leg - left_leg) + _unit(right_arm - left_arm))
        up = _unit((left_arm + right_arm - left_leg - right_leg) * .5)
        if all(abs(lateral[a] * lateral[b]) < .05 for a, b in ((0, 1), (1, 2), (2, 0))):
            axis = max(range(3), key=lambda i: abs(up[i]))
            sign = 1.0 if up[axis] >= 0 else -1.0
            up = Vector()
            up[axis] = sign
        forward = _unit(lateral.cross(up))
        if forward.length_squared == 0 or up.length_squared == 0:
            return _IDENTITY.copy()
        right = _unit(up.cross(forward))
        up = forward.cross(right)
        return Matrix((right, up, forward)).transposed().to_quaternion()

    def comparison(self, slot, orientation):
        direction, tolerance, global_space, plane, _ = _RULES[slot]
        space = orientation
        parent = _PARENTS.get(slot)
        if not global_space and parent not in (None, "Hips") and parent in self.bones and parent in _RULES:
            current = self.direction(parent)
            if current.length_squared:
                reference = orientation @ _unit(Vector(_RULES[parent][0]))
                space = reference.rotation_difference(current) @ orientation
        current = self.direction(slot)
        target = space @ _unit(Vector(direction))
        if plane is not None:
            normal = space @ Vector(plane)
            current = current - normal * current.dot(normal)
        return current, target, tolerance

    def position_adjustment(self):
        if not all(slot in self.bones for slot in ("LeftUpperLeg", "RightUpperLeg")):
            return Vector(), 0.0
        toes = all(side + "Toes" in self.bones for side in ("Left", "Right"))
        feet = ("LeftToes", "RightToes") if toes else ("LeftFoot", "RightFoot")
        if not all(slot in self.bones for slot in feet):
            return Vector(), 0.0
        hip = (self.point("LeftUpperLeg") + self.point("RightUpperLeg")) * .5
        foot = (self.point(feet[0]) + self.point(feet[1])) * .5
        height = hip.y - foot.y
        if height <= 0:
            return Vector(), 0.0
        offset = Vector()
        if foot.y < 0 or foot.y > height * (.1 if toes else .3):
            offset.y = height * (1.03 if toes else 1.13) - hip.y
        if abs(hip.x) > .01 * height:
            offset.x = -hip.x
        if abs(hip.z) > .2 * height:
            offset.z = -hip.z
        return offset, offset.length * 100.0 / height

    def errors(self):
        orientation = self.orientation()
        errors = {}
        for slot in _ORDER:
            if slot not in self.bones or slot not in _RULES:
                continue
            if slot == "Hips":
                error = max(_angle(orientation @ axis, axis) for axis in _AXES) - _RULES[slot][1]
            else:
                current, target, tolerance = self.comparison(slot, orientation)
                error = _angle(current, target) - tolerance if current.length_squared else 0.0
            if error > 0:
                errors[slot] = error
        _, position_error = self.position_adjustment()
        return {"bones": errors, "position": position_error, "total": sum(errors.values()) + position_error}


def validate(armature):
    return _Pose(armature).errors()


def generate(armature):
    pose = _Pose(armature)
    if not any(slot in _RULES for slot in pose.bones):
        raise ValueError("需要有效的 Humanoid 骨骼映射")
    orientation = pose.orientation()
    for slot in _ORDER:
        if slot not in pose.bones or slot not in _RULES:
            continue
        if slot == "Hips":
            if max(_angle(orientation @ axis, axis) for axis in _AXES) > _RULES[slot][1]:
                pose.set_rotation(slot, orientation.inverted() @ pose.rotation(slot))
            orientation = pose.orientation()
            continue
        current, target, tolerance = pose.comparison(slot, orientation)
        if current.length_squared < 1e-15:
            continue
        angle = _angle(current, target)
        if angle <= tolerance * .99:
            continue
        amount = max(0.0, min(1.0, 1.05 - tolerance / angle))
        adjustment = _interpolate_adjustment(current.rotation_difference(target), amount)
        foot = slot.replace("UpperLeg", "Foot").replace("LowerLeg", "Foot")
        preserve_foot = slot.endswith(("UpperLeg", "LowerLeg")) and foot in pose.bones
        foot_rotation = pose.rotation(foot) if preserve_foot else None
        pose.set_rotation(slot, adjustment @ pose.rotation(slot))
        if preserve_foot:
            pose.set_rotation(foot, foot_rotation)
    offset, _ = pose.position_adjustment()
    if offset.length_squared and "Hips" in pose.bones:
        pose.move("Hips", offset)
    return pose.errors()
