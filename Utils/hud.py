"""Shared 2D HUD text helpers for modal HoTools operators."""

import blf


DEFAULT_KEY_COLOR = (1.0, 0.85, 0.2, 1.0)
DEFAULT_VALUE_COLOR = (1.0, 1.0, 1.0, 1.0)


def _rgba(color):
    if len(color) == 4:
        return tuple(color)
    return (*color, 1.0)


def begin_hud(font_id=0, size=16, shadow=True, shadow_alpha=0.6, shadow_size=3):
    """Set the shared HoTools modal HUD font state."""
    blf.size(font_id, size)
    if shadow:
        blf.enable(font_id, blf.SHADOW)
        blf.shadow(font_id, shadow_size, 0.0, 0.0, 0.0, shadow_alpha)
        blf.shadow_offset(font_id, 1, -1)
    return font_id


def end_hud(font_id=0, shadow=True):
    """Restore the font state after drawing a shared HUD."""
    if shadow:
        blf.disable(font_id, blf.SHADOW)


def draw_hud_key_value(
    font_id,
    x,
    y,
    key_text,
    value_text,
    value_color=DEFAULT_VALUE_COLOR,
    key_color=DEFAULT_KEY_COLOR,
):
    """Draw one colored key/value row and return its total width."""
    key_text = str(key_text)
    value_text = str(value_text)
    blf.color(font_id, *_rgba(key_color))
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, key_text)
    key_width, _ = blf.dimensions(font_id, key_text)

    blf.color(font_id, *_rgba(value_color))
    blf.position(font_id, x + key_width, y, 0)
    blf.draw(font_id, value_text)
    value_width, _ = blf.dimensions(font_id, value_text)
    return key_width + value_width


def draw_hud_lines(
    font_id,
    x,
    y,
    lines,
    line_height=22,
    direction=1,
    key_color=DEFAULT_KEY_COLOR,
    value_color=DEFAULT_VALUE_COLOR,
):
    """Draw ``(key, value[, value_color])`` rows at a fixed line spacing."""
    for index, line in enumerate(lines):
        if len(line) == 3:
            key_text, value_text, row_color = line
        else:
            key_text, value_text = line
            row_color = value_color
        draw_hud_key_value(
            font_id,
            x,
            y + index * line_height * direction,
            key_text,
            value_text,
            value_color=row_color,
            key_color=key_color,
        )


def measure_hud_lines(font_id, lines):
    """Return the widest key/value row using the active BLF font."""
    return max(
        (
            blf.dimensions(font_id, f"{line[0]}{line[1]}")[0]
            for line in lines
        ),
        default=0.0,
    )


def draw_hud_rows(
    font_id,
    x,
    y,
    rows,
    key_color=DEFAULT_KEY_COLOR,
    value_color=DEFAULT_VALUE_COLOR,
):
    """Draw ``(offset, key, value[, value_color])`` rows."""
    for row in rows:
        if len(row) == 4:
            offset, key_text, value_text, row_color = row
        else:
            offset, key_text, value_text = row
            row_color = value_color
        draw_hud_key_value(
            font_id,
            x,
            y + offset,
            key_text,
            value_text,
            value_color=row_color,
            key_color=key_color,
        )


def draw_mouse_hud(
    mouse,
    lines,
    offset=20,
    line_height=22,
    direction=1,
    font_id=0,
    size=16,
    shadow=True,
    shadow_alpha=0.6,
    key_color=DEFAULT_KEY_COLOR,
    value_color=DEFAULT_VALUE_COLOR,
):
    """Draw standard key/value rows beside a region-space mouse position."""
    x = mouse[0] + offset
    y = mouse[1] + offset
    begin_hud(font_id, size=size, shadow=shadow, shadow_alpha=shadow_alpha)
    draw_hud_lines(
        font_id,
        x,
        y,
        lines,
        line_height=line_height,
        direction=direction,
        key_color=key_color,
        value_color=value_color,
    )
    end_hud(font_id, shadow=shadow)


def draw_mouse_hud_rows(
    mouse,
    rows,
    offset=20,
    font_id=0,
    size=16,
    shadow=True,
    shadow_alpha=0.6,
    key_color=DEFAULT_KEY_COLOR,
    value_color=DEFAULT_VALUE_COLOR,
):
    """Draw standard rows beside a mouse position with explicit offsets."""
    x = mouse[0] + offset
    y = mouse[1] + offset
    begin_hud(font_id, size=size, shadow=shadow, shadow_alpha=shadow_alpha)
    draw_hud_rows(
        font_id,
        x,
        y,
        rows,
        key_color=key_color,
        value_color=value_color,
    )
    end_hud(font_id, shadow=shadow)
