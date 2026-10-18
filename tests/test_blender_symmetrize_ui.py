"""Direction wording and draw-handler lifetime for the Alt-X preview."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MeshTools import symmetrize as ui


for axis in "XYZ":
    for direction, source, target in (("POSITIVE", "+", "-"), ("NEGATIVE", "-", "+")):
        assert ui._direction_label(direction, axis) == f"{source}{axis} → {target}{axis}"
        assert ui._direction_label(direction, axis, True) == f"保留 {source}{axis}，删除 {target}{axis}"

area = SimpleNamespace(header_text_set=Mock(), tag_redraw=Mock(), type="VIEW_3D")
op = SimpleNamespace(HUD=object(), VIEW3D=object(), area=area)
ui._ACTIVE_DRAWS[op.HUD] = area
ui._ACTIVE_DRAWS[op.VIEW3D] = area
with patch.object(ui.bpy.types.SpaceView3D, "draw_handler_remove") as remove:
    ui.OP_Symmetrize.finish(op)
    ui.OP_Symmetrize.finish(op)
    assert remove.call_count == 2, "每个绘制句柄只能移除一次"
assert not ui._ACTIVE_DRAWS
assert op.HUD is None and op.VIEW3D is None
area.header_text_set.assert_called_with(None)

# Orbit navigation must not trigger a right-click cancel or confirmation.
for event_type in ("MIDDLEMOUSE", "RIGHTMOUSE", "LEFTMOUSE"):
    op = SimpleNamespace(area=area, finish=Mock(), passthrough=False)
    event = SimpleNamespace(type=event_type, alt=True, mouse_region_x=100, mouse_region_y=100)
    assert ui.OP_Symmetrize.modal(op, SimpleNamespace(area=area), event) == {"PASS_THROUGH"}
    assert op.passthrough
    op.finish.assert_not_called()

# Escape cancels and clears both overlays before returning.
op = SimpleNamespace(area=area, finish=Mock(), passthrough=False)
event = SimpleNamespace(type="ESC", alt=False, mouse_region_x=100, mouse_region_y=100)
assert ui.OP_Symmetrize.modal(op, SimpleNamespace(area=area), event) == {"CANCELLED"}
op.finish.assert_called_once()

# Disable/reload also removes leftover handles, including already-invalid ones.
ui._ACTIVE_DRAWS[object()] = area
with patch.object(ui.bpy.types.SpaceView3D, "draw_handler_remove", side_effect=ValueError("removed")):
    ui.cleanup_symmetrize_huds()
assert not ui._ACTIVE_DRAWS

print("SYMMETRIZE_UI_OK")
