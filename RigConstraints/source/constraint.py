"""Capture one unmodified Blender constraint as a v4 source fact."""

from .parameters import capture_parameters, capture_custom_properties
from .references import capture_references


def capture_constraint(constraint, armature, stack_index):
    """Return source fields without classifying or taking ownership of them."""
    result = {
        "stackIndex": stack_index,
        "name": str(getattr(constraint, "name", "")),
        "constraintType": str(getattr(constraint, "type", "")),
        "targetObjectName": str(getattr(getattr(constraint, "target", None), "name", "")),
        "targetBoneName": str(getattr(constraint, "subtarget", "")),
        "parameters": capture_parameters(constraint),
        "references": capture_references(constraint),
    }
    properties = capture_custom_properties(constraint)
    if properties:
        result["customProperties"] = properties
    return result
