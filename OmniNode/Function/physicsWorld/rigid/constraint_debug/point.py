"""Point constraint visualization."""

from __future__ import annotations

from .common import append_anchor_pair, append_free_rotation_sphere


def append_lines(groups: dict[str, list], spec, context) -> None:
    base = groups["base"]
    append_anchor_pair(base, context)
    # A point constraint removes three translations but preserves all three
    # angular DOFs.  A three-ring sphere communicates that free rotation.
    append_free_rotation_sphere(base, context.frame_a, context.size * 0.22)
