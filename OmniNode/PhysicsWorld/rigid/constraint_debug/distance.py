"""Distance constraint visualization."""

from __future__ import annotations

from .common import (
    append_anchor_pair,
    append_free_rotation_sphere,
    current_value,
)


def append_lines(groups: dict[str, list], spec, context) -> None:
    append_anchor_pair(groups["base"], context)

    minimum = max(float(getattr(spec, "distance_min", 0.0) or 0.0), 0.0)
    maximum = max(float(getattr(spec, "distance_max", minimum) or minimum), 0.0)
    if minimum > maximum:
        minimum, maximum = maximum, minimum

    # The two exact-radius shells show the permitted point-to-point distance
    # interval.  When min == max they collapse to the familiar rigid stick.
    if minimum > 1.0e-7:
        append_free_rotation_sphere(groups["limits"], context.frame_a, minimum)
    if maximum > 1.0e-7 and abs(maximum - minimum) > 1.0e-7:
        append_free_rotation_sphere(groups["limits"], context.frame_a, maximum)

    value = current_value(context, "distance")
    if value is not None and value > 1.0e-7:
        append_free_rotation_sphere(groups["state"], context.frame_a, value)
