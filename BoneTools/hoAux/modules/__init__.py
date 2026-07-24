"""HoAux body-specific generation modules."""

from . import elbow_volume, shoulder_volume

DEFINITIONS = (elbow_volume.DEFINITION, shoulder_volume.DEFINITION)

__all__ = ("DEFINITIONS", "elbow_volume", "shoulder_volume")
