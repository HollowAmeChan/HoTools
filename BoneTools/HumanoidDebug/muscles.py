"""Unity's default Humanoid ranges and swing/twist coordinates.

Muscle zero is the centre of a joint's range, rather than its T-Pose.
Angles below are degrees. The defaults and composition were checked against
HumanTrait and HumanPoseHandler in Unity 2022.3; Unity is not used at runtime.
"""

from dataclasses import dataclass
from math import radians, tan

from mathutils import Quaternion


@dataclass(frozen=True)
class Joint:
    slot: str
    channels: tuple
    limits: tuple
    signs: tuple
    reference: tuple = (0.0, 0.0, 0.0)
    frame: str = "torso"
    twist_parent: str = ""


JOINTS = []


def _joint(slot, channels, limits, signs=(1, 1, 1), reference=(0, 0, 0),
           frame="torso", twist_parent=""):
    JOINTS.append(Joint(slot, channels, limits, signs, reference, frame, twist_parent))


for prefix, slot, extent in (
    ("Spine", "spine", 40), ("Chest", "chest", 40),
    ("UpperChest", "upper_chest", 20),
):
    _joint(slot, (
        f"{prefix} Twist Left-Right", f"{prefix} Left-Right",
        f"{prefix} Front-Back",
    ), ((-extent, extent),) * 3)

for prefix, slot in (("Neck", "neck"), ("Head", "head")):
    _joint(slot, (
        f"{prefix} Turn Left-Right", f"{prefix} Tilt Left-Right",
        f"{prefix} Nod Down-Up",
    ), ((-40, 40),) * 3)

_joint("jaw", (None, "Jaw Left-Right", "Jaw Close"),
       ((0, 0), (-10, 10), (-10, 10)), frame="face")

for side_name, side in (("Left", "L"), ("Right", "R")):
    suffix = f".{side}"
    left = side == "L"
    mirror = 1 if left else -1
    _joint("eye" + suffix, (
        None, f"{side_name} Eye In-Out", f"{side_name} Eye Down-Up",
    ), ((0, 0), (-20, 20), (-10, 15)), (1, mirror, -1), frame="face")
    _joint("upper_leg" + suffix, (
        f"{side_name} Upper Leg Twist In-Out", f"{side_name} Upper Leg In-Out",
        f"{side_name} Upper Leg Front-Back",
    ), ((-60, 60), (-60, 60), (-90, 50)), (mirror, mirror, 1),
        (0, 0, 30), "leg")
    _joint("lower_leg" + suffix, (
        f"{side_name} Lower Leg Twist In-Out", None,
        f"{side_name} Lower Leg Stretch",
    ), ((-90, 90), (0, 0), (-80, 80)), (mirror, 1, -1),
        (0, 0, -80), "leg", "upper_leg" + suffix)
    _joint("foot" + suffix, (
        None, f"{side_name} Foot Twist In-Out", f"{side_name} Foot Up-Down",
    ), ((0, 0), (-30, 30), (-50, 50)), (1, mirror, 1),
        frame="foot", twist_parent="lower_leg" + suffix)
    _joint("toes" + suffix, (None, None, f"{side_name} Toes Up-Down"),
           ((0, 0), (0, 0), (-50, 50)), frame="face")
    _joint("shoulder" + suffix, (
        None, f"{side_name} Shoulder Front-Back", f"{side_name} Shoulder Down-Up",
    ), ((0, 0), (-15, 15), (-15, 30)), (1, 1, -mirror), frame="arm")
    _joint("upper_arm" + suffix, (
        f"{side_name} Arm Twist In-Out", f"{side_name} Arm Front-Back",
        f"{side_name} Arm Down-Up",
    ), ((-90, 90), (-100, 100), (-60, 100)), (mirror, 1, -mirror),
        (0, 30, -40 * mirror), "arm")
    _joint("lower_arm" + suffix, (
        f"{side_name} Forearm Twist In-Out", None, f"{side_name} Forearm Stretch",
    ), ((-90, 90), (0, 0), (-80, 80)), (mirror, 1, -mirror),
        (0, 0, -80 * mirror), "forearm", "upper_arm" + suffix)
    _joint("hand" + suffix, (
        None, f"{side_name} Hand In-Out", f"{side_name} Hand Down-Up",
    ), ((0, 0), (-40, 40), (-80, 80)), (1, 1, -mirror),
        frame="hand", twist_parent="lower_arm" + suffix)

    for finger_name in ("Thumb", "Index", "Middle", "Ring", "Little"):
        finger = finger_name.lower()
        thumb = finger == "thumb"
        prefix = f"{side_name}Hand.{finger_name}"
        spread = 25 if thumb else (20 if finger in {"index", "little"} else 7.5)
        spread_sign = -1 if finger in {"thumb", "index", "middle"} else 1
        flex_sign = mirror if thumb else -mirror
        # The open-hand reference is constructed in rig.py from the measured
        # palm/finger frames, including natural spread and thumb orientation.
        _joint(f"{finger}_proximal{suffix}", (
            None, prefix + ".Spread", prefix + ".1 Stretched",
        ), ((0, 0), (-spread, spread), (-20, 20) if thumb else (-50, 50)),
            (1, spread_sign, flex_sign), frame="thumb" if thumb else "finger")
        for index, segment in ((2, "intermediate"), (3, "distal")):
            _joint(f"{finger}_{segment}{suffix}",
                   (None, None, f"{prefix}.{index} Stretched"),
                   ((0, 0), (0, 0), (-40, 35) if thumb else (-45, 45)),
                   (1, 1, flex_sign), frame="thumb" if thumb else "finger")


JOINTS = tuple(JOINTS)
BY_SLOT = {joint.slot: joint for joint in JOINTS}
CHANNELS = {
    channel for joint in JOINTS for channel in joint.channels if channel is not None
}
TWIST_SLOTS = {
    joint.twist_parent for joint in JOINTS if joint.twist_parent
}


def swing_twist(angles):
    """Compose the two swing angles first, then twist about the long axis."""
    x, y, z = (radians(angle) for angle in angles)
    # Avoid the pole at +/-180 without clamping valid muscles to [-1, 1]:
    # imported clips can slightly exceed their nominal limits.
    bound = 3.141592653589793 - 1e-5
    y, z = max(-bound, min(bound, y)), max(-bound, min(bound, z))
    swing = Quaternion((1.0, 0.0, tan(y * 0.5), tan(z * 0.5))).normalized()
    return swing @ Quaternion((1.0, 0.0, 0.0), x)


def angles_for_sample(joint, sample):
    return tuple(
        sample.get(channel, 0.0) * (maximum if sample.get(channel, 0.0) >= 0 else -minimum) * sign
        if channel is not None else 0.0
        for channel, (minimum, maximum), sign in
        zip(joint.channels, joint.limits, joint.signs)
    )
