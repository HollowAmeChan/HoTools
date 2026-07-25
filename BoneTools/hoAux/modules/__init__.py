"""HoAux body-specific generation modules."""

from . import (
    elbow_volume,
    limb_bulge,
    limb_twist,
    shoulder_volume,
    upper_arm_slide,
    wrist_volume,
)

DEFINITIONS = (
    wrist_volume.DEFINITION,
    limb_bulge.FOREARM_DEFINITION,
    limb_twist.FOREARM_DEFINITION,
    elbow_volume.DEFINITION,
    limb_bulge.UPPER_ARM_DEFINITION,
    limb_twist.UPPER_ARM_DEFINITION,
    upper_arm_slide.DEFINITION,
    shoulder_volume.DEFINITION,
)

__all__ = (
    "DEFINITIONS",
    "elbow_volume",
    "limb_twist",
    "limb_bulge",
    "shoulder_volume",
    "upper_arm_slide",
    "wrist_volume",
)
