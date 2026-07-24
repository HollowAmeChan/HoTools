"""Small declarative geometry records shared by preview and generation."""

from dataclasses import dataclass

from mathutils import Vector


@dataclass(frozen=True)
class PlannedBone:
    resource_key: str
    preferred_name: str
    role_tag: str
    marker: str
    head: Vector
    tail: Vector
    roll_reference: Vector
    parent_name: str
