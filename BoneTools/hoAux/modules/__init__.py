"""HoAux body-specific generation modules."""

from . import elbow_volume, limb_twist, shoulder_volume

DEFINITIONS = (
    limb_twist.FOREARM_DEFINITION,
    elbow_volume.DEFINITION,
    limb_twist.UPPER_ARM_DEFINITION,
    shoulder_volume.DEFINITION,
)

__all__ = ("DEFINITIONS", "elbow_volume", "limb_twist", "shoulder_volume")
