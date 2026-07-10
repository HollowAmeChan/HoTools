"""Registry for semantic rigid-constraint debug renderers.

The public rigid debug module owns viewport lifetime and colors.  This package
owns only constraint meaning.  Adding a new Jolt constraint therefore requires
a new small renderer and one registry entry, rather than another branch in the
viewport handler.
"""

from __future__ import annotations

from . import cone, distance, fixed, hinge, point, six_dof, slider, swing_twist
from .common import append_anchor_pair, append_frame_axes, make_context


CONSTRAINT_DEBUG_BUILDERS = {
    "FIXED": fixed.append_lines,
    "POINT": point.append_lines,
    "DISTANCE": distance.append_lines,
    "HINGE": hinge.append_lines,
    "SLIDER": slider.append_lines,
    "CONE": cone.append_lines,
    "SWING_TWIST": swing_twist.append_lines,
    "SIX_DOF": six_dof.append_lines,
}


def build_constraint_debug_lines(spec, state: dict | None = None) -> dict:
    """Return semantic line groups for one constraint as plain tuples."""
    context = make_context(spec, state)
    groups = {
        "base": [],
        "limits": [],
        "motor": [],
        "state": [],
        "known_type": context.constraint_type in CONSTRAINT_DEBUG_BUILDERS,
        "constraint_type": context.constraint_type,
    }
    builder = CONSTRAINT_DEBUG_BUILDERS.get(context.constraint_type)
    if builder is None:
        append_anchor_pair(groups["base"], context)
        append_frame_axes(groups["base"], context.frame_a, context.size * 0.35)
    else:
        builder(groups, spec, context)
    return groups


__all__ = ["CONSTRAINT_DEBUG_BUILDERS", "build_constraint_debug_lines"]
