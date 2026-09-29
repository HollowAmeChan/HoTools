"""无头复现：会话拖拽时，点位/中心点是否会因为布局与鼠标坐标不一致而"飞"。

关键场景：``WIDGET.area``（绘制用的视口）与 ``WIDGET.last_layout``（快照）尺寸不一致，
或者存在多个调试矩阵时来回切换。旧实现直接拿快照换算鼠标坐标，一旦尺寸不匹配，
拖动会把值推向角上。
"""

import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR.parent) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR.parent))

result = bpy.ops.preferences.addon_enable(module="HoTools")
assert result == {"FINISHED"}, result

from HoTools.ShapekeyTools import blend_debug_store as store  # noqa: E402
from HoTools.ShapekeyTools import blend_overlay as overlay  # noqa: E402
from HoTools.ShapekeyTools.blend_utils import blend_func as blend_func  # noqa: E402


class FakeArea:
    type = 'VIEW_3D'

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.regions = []

    def tag_redraw(self):
        pass


class FakeEvent:
    def __init__(self, x, y):
        self.mouse_region_x = x
        self.mouse_region_y = y


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.scene.ho_bs_debug_items.clear()
    bpy.context.scene.ho_bs_debug_index = 0


def make_face(name, key_names):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.shape_key_add(name="Basis", from_mix=False)
    for key_name in key_names:
        obj.shape_key_add(name=key_name, from_mix=False)
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def make_matrix(face, count):
    face.active_shape_key_index = face.data.shape_keys.key_blocks.find(
        face.data.shape_keys.key_blocks[1].name)
    assert bpy.ops.ho.shapekeytools_blend_debug_add() == {'FINISHED'}
    for _ in range(count):
        assert bpy.ops.ho.shapekeytools_blend_point_add_active() == {'FINISHED'}
    return store.active_item(bpy.context.scene)


clear_scene()
face = make_face("FlyFace", ["A", "I", "U", "E", "O"])
matrix_a = make_matrix(face, 4)
matrix_b = make_matrix(face, 4)
assert len(bpy.context.scene.ho_bs_debug_items) == 2

AREA = FakeArea(560.0, 728.0)
overlay.WIDGET.start(bpy.context, area=AREA)
overlay.WIDGET.area = AREA


def layout_for(item, width, height):
    weights, _names = blend_func.evaluate_item(item)
    return overlay.WIDGET._layout_for_size(bpy.context, item, width, height, weights)


def drag(item, *, kind, steps=8, step_pixels=12.0, area=None):
    """用会话走一次完整的按下-拖动，返回浮点轨迹。

    每步都验证核心不变量：**写进去的值 == 当前鼠标位置在该视口布局里对应的坐标**
    （否则点位就会"飞"到鼠标以外）。
    """
    area = area or AREA
    overlay.set_drag_active(False)
    overlay.invalidate_axis_range()
    bpy.context.scene.ho_bs_debug_index = (
        0 if item.as_pointer() == matrix_a.as_pointer() else 1)
    overlay.WIDGET.area = area
    layout = layout_for(item, area.width, area.height)
    handles, centre = overlay._compute_handles(item, layout)
    if kind == "centre":
        start = centre
    else:
        # 挑一个离中心点最远、不会和中心点抢命中的点位
        start = max(
            ((entry[2], entry[3]) for entry in handles),
            key=lambda point: (point[0] - centre[0]) ** 2 + (point[1] - centre[1]) ** 2)
    session = overlay.WidgetDragSession(bpy.context, on_redraw=lambda: None)
    assert session.press(bpy.context, start[0], start[1], area) is True, (
        f"{kind} 没按下：{start}")
    # 拖动期间坐标系范围被冻结在按下那一刻：写进去的值必须始终落在这个范围内
    locked = overlay._layout_axis_range(layout)
    trace = []
    for step in range(1, steps + 1):
        x = start[0] + step_pixels * step
        y = start[1] + step_pixels * step
        session.move(bpy.context, x, y)
        current = layout_for(item, area.width, area.height)
        expected = overlay._plot_to_uv(*overlay._clamp_to_plot(x, y, current),
                                       current)
        if kind == "centre":
            actual = (item.cursor_u, item.cursor_v)
        else:
            point = item.points[item.point_index]
            actual = (point.u, point.v)
        assert abs(actual[0] - expected[0]) < 1e-3, (step, actual, expected)
        assert abs(actual[1] - expected[1]) < 1e-3, (step, actual, expected)
        assert locked[0] - 1e-6 <= actual[0] <= locked[1] + 1e-6, (
            f"{kind} 第 {step} 步写出的 u 超出锁定范围：{actual} vs {locked}")
        assert locked[2] - 1e-6 <= actual[1] <= locked[3] + 1e-6, (
            f"{kind} 第 {step} 步写出的 v 超出锁定范围：{actual} vs {locked}")
        trace.append((round(actual[0], 3), round(actual[1], 3)))
    session.release()
    bpy.context.view_layer.update()
    return trace, layout


# ── 单矩阵：拖中心点应该线性平移，不会一步跳到角上 ────────────────────────
trace, layout = drag(matrix_a, kind="centre")
assert trace[0] == (0.058, 0.058), trace
assert all(abs(entry[0] - entry[1]) < 1e-6 for entry in trace), trace
for before, after in zip(trace, trace[1:]):
    assert after[0] > before[0], f"应该单调变大：{trace}"
    assert after[0] - before[0] < 0.15, f"单步跨度过大：{trace}"
assert trace[-1][0] < 1.0, f"不该一步飞到角上：{trace}"

# ── 两个矩阵：来回切换拖拽也不能飞 ───────────────────────────────────────
for round_index in range(3):
    for item in (matrix_a, matrix_b):
        item.cursor_u = 0.0
        item.cursor_v = 0.0
        overlay.invalidate_axis_range()
        trace, _layout = drag(item, kind="centre")
        assert trace[0] == (0.058, 0.058), (round_index, trace)
        assert trace[-1][0] < 0.6, (round_index, trace)

# ── 两个矩阵的坐标系范围不同：切矩阵必须换布局，不能沿用上一个矩阵的范围 ────────
# 旧实现只按视口尺寸缓存布局：视口没变就永远用第一次那份，于是 B 的点位按 A 的范围
# 映射，越界的点被夹到坐标系角上（正是「最后一个控制点飞到右上角」）。
matrix_a.points[0].u, matrix_a.points[0].v = -0.2, -0.2
matrix_b.points[0].u, matrix_b.points[0].v = 6.0, 6.0
overlay.invalidate_axis_range()
layout_two_a = layout_for(matrix_a, AREA.width, AREA.height)
layout_two_b = layout_for(matrix_b, AREA.width, AREA.height)
assert layout_two_a["plot"] == layout_two_b["plot"], "矩形只跟视口尺寸走"
range_two_a = overlay._layout_axis_range(layout_two_a)
range_two_b = overlay._layout_axis_range(layout_two_b)
assert range_two_a != range_two_b, (range_two_a, range_two_b)
assert range_two_b[1] >= 6.0, f"B 的范围必须适配它自己的点位：{range_two_b}"
# 每个矩阵的手柄都必须落在坐标系内（按自己的范围映射，不许被夹到角上）
for two_item, two_layout in ((matrix_a, layout_two_a), (matrix_b, layout_two_b)):
    px, py, pw, ph = two_layout["plot"]
    for _kind, index, x, y in overlay._compute_handles(two_item, two_layout)[0]:
        assert px <= x <= px + pw and py <= y <= py + ph, (
            two_item.name, index, x, y, two_layout["plot"])
matrix_a.points[0].u, matrix_a.points[0].v = -1.0, 1.0
matrix_b.points[0].u, matrix_b.points[0].v = -0.33, 0.67
overlay.invalidate_axis_range()

# ── 视口尺寸中途变化（等价于 Ctrl+Space）时也不许飞 ──────────────────────
# 过程里 area 从大变小，会话必须每次按当前尺寸算布局
matrix_a.cursor_u = matrix_a.cursor_v = 0.0
matrix_b.cursor_u = matrix_b.cursor_v = 0.0
overlay.invalidate_axis_range()
bpy.context.scene.ho_bs_debug_index = 0
assert store.active_item(bpy.context.scene).as_pointer() == matrix_a.as_pointer()
small = FakeArea(320.0, 260.0)
overlay.WIDGET.area = small
layout_small = layout_for(matrix_a, small.width, small.height)
_handles, centre_small = overlay._compute_handles(matrix_a, layout_small)
session = overlay.WidgetDragSession(bpy.context, on_redraw=lambda: None)
assert session.press(bpy.context, centre_small[0], centre_small[1], small) is True
# 拖动过程中视口被改小：继续按新尺寸换算
for step in range(1, 5):
    x = centre_small[0] + 10.0 * step
    y = centre_small[1] + 10.0 * step
    session.move(bpy.context, x, y)
current = layout_for(matrix_a, small.width, small.height)
expected = overlay._plot_to_uv(*overlay._clamp_to_plot(x, y, current), current)
assert abs(matrix_a.cursor_u - expected[0]) < 1e-3, (
    matrix_a.cursor_u, expected)
assert abs(matrix_a.cursor_v - expected[1]) < 1e-3, (matrix_a.cursor_v, expected)
assert -1.0 <= matrix_a.cursor_u <= 1.0 and -1.0 <= matrix_a.cursor_v <= 1.0
session.release()
small_range = overlay._layout_axis_range(layout_for(matrix_a, small.width, small.height))
# 小视口里 40px 本来就该换算出更大的坐标（框只有 140px 宽）；要盯的是**没有被夹到角上**
assert matrix_a.cursor_u < small_range[1] and matrix_a.cursor_v < small_range[3], (
    f"视口变小后中心点被夹到角上：{(matrix_a.cursor_u, matrix_a.cursor_v)} vs {small_range}")

# ── 拖到坐标系外面：值必须在锁定的范围上收敛，不能越拖越远 ──────────────────
# 旧实现把范围冻在布局字典里、锁又只认「有没有锁」不认矩阵；一旦锁失效，被夹在框边的
# 值每帧都会把范围撑大 15%（plot_axis_range 的留白），于是一路几何级数增长 ——
# 表现就是「点位往右上角越飞越远」。
bpy.context.scene.ho_bs_debug_index = 0
matrix_a.cursor_u = matrix_a.cursor_v = 0.0
overlay.invalidate_axis_range()
overlay.WIDGET.area = AREA
layout_esc = layout_for(matrix_a, AREA.width, AREA.height)
locked_range = overlay._layout_axis_range(layout_esc)
_handles, centre_esc = overlay._compute_handles(matrix_a, layout_esc)
session = overlay.WidgetDragSession(bpy.context, on_redraw=lambda: None)
assert session.press(bpy.context, centre_esc[0], centre_esc[1], AREA) is True
escape = []
for step in range(1, 9):
    session.move(bpy.context, centre_esc[0] + 40.0 * step,
                 centre_esc[1] + 40.0 * step)
    escape.append((round(matrix_a.cursor_u, 4), round(matrix_a.cursor_v, 4)))
assert overlay._layout_axis_range(layout_esc) == locked_range, (
    f"拖动期间坐标系范围必须锁死：{locked_range} -> "
    f"{overlay._layout_axis_range(layout_esc)}")
assert escape[0][0] < 0.5, f"第一步就跳到角上了：{escape}"
assert escape[-1] == escape[-2] == escape[-3], (
    f"鼠标停在框外时值还在变大（范围没锁住）：{escape}")
assert escape[-1] == (round(locked_range[1], 4), round(locked_range[3], 4)), (
    f"夹取后应该正好停在锁定范围的上界：{escape[-1]} vs {locked_range}")
session.release()
# 松手后重新适配范围，中心点仍然画得出来（不会因为值超出范围而消失）
refit = overlay._layout_axis_range(layout_for(matrix_a, AREA.width, AREA.height))
assert refit[1] >= locked_range[1] and refit[0] <= locked_range[0], refit
px, py, pw, ph = layout_for(matrix_a, AREA.width, AREA.height)["plot"]
x, y = overlay._uv_to_plot(matrix_a.cursor_u, matrix_a.cursor_v,
                           layout_for(matrix_a, AREA.width, AREA.height))
assert px <= x <= px + pw and py <= y <= py + ph, (x, y)

# ── 拖点位：同样要线性、不能越界 ─────────────────────────────────────────
overlay.WIDGET.area = AREA
overlay.invalidate_axis_range()
trace, _layout = drag(matrix_b, kind="point")
point_range = overlay._cached_axis_range(matrix_b)
assert all(point_range[0] - 1e-6 <= entry[0] <= point_range[1] + 1e-6
           and point_range[2] - 1e-6 <= entry[1] <= point_range[3] + 1e-6
           for entry in trace), (trace, point_range)
for before, after in zip(trace, trace[1:]):
    assert after[0] >= before[0] and after[1] >= before[1], trace

# ── 拖动中途切换矩阵：应该停止这次拖动，而不是写进另一个矩阵 ──────────────
matrix_a.cursor_u = matrix_a.cursor_v = 0.25
matrix_b.cursor_u = matrix_b.cursor_v = -0.25
overlay.invalidate_axis_range()
bpy.context.scene.ho_bs_debug_index = 1
layout_b = layout_for(matrix_b, AREA.width, AREA.height)
_handles, centre_b = overlay._compute_handles(matrix_b, layout_b)
session = overlay.WidgetDragSession(bpy.context, on_redraw=lambda: None)
assert session.press(bpy.context, centre_b[0], centre_b[1], AREA) is True
bpy.context.scene.ho_bs_debug_index = 0  # 拖到一半切走
before_a = (matrix_a.cursor_u, matrix_a.cursor_v)
session.move(bpy.context, centre_b[0] + 40.0, centre_b[1] + 40.0)
assert (matrix_a.cursor_u, matrix_a.cursor_v) == before_a, "不该写进另一个矩阵"
session.release()

overlay.WIDGET.cancel("测试收尾")
bpy.ops.preferences.addon_disable(module="HoTools")
print("BLEND_WIDGET_DRAG_OK", bpy.app.version_string)
