"""形态键混合矩阵的 Blender 级契约测试。

覆盖：页签注册、调试项/坐标点/操作物体的增删、坐标自动排布、权重求解与写入。
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
from HoTools.ShapekeyTools import blend_editor as editor  # noqa: E402
from HoTools.ShapekeyTools import blend_overlay as overlay  # noqa: E402
from HoTools.ShapekeyTools.blend_utils import blend_func as blend_func  # noqa: E402
from HoTools.ShapekeyTools.blend_utils import point_layout as point_layout  # noqa: E402
from HoTools.ShapekeyTools.blend_utils import (  # noqa: E402
    blend_space_math as blend_math,
    draw_func as draw_func,
    shapekey_utils as shapekey_utils,
)


def assert_close(value, expected, tolerance=1e-5, message=""):
    if abs(value - expected) > tolerance:
        raise AssertionError(f"{message}: {value} != {expected}")


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def make_face(name, key_names):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
        [],
        [(0, 1, 2, 3)],
    )
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    # 必须先显式建立基础键：Blender 的第一次 shape_key_add 会成为参考键。
    obj.shape_key_add(name="Basis", from_mix=False)
    for key_name in key_names:
        key = obj.shape_key_add(name=key_name, from_mix=False)
        key.data[0].co.x += 0.1  # 让键和基础键有实际差别
    return obj


# ── 页签注册 ──────────────────────────────────────────────────────────────
panel_items = [
    identifier
    for identifier, _label, _description in
    bpy.types.Scene.ho_ShapekeyToolsPanel_Mod.keywords['items']
] if 'items' in bpy.types.Scene.ho_ShapekeyToolsPanel_Mod.keywords else None
assert panel_items is None or 'PANEL_SHAPEKEYTOOLS_BLENDMATRIX' in panel_items
# 注意：bpy.ops.ho.xxx 是动态命名空间，用 hasattr 永远为真，必须查注册表
for operator_id in (
    "shapekeytools_blend_debug_add",
    "shapekeytools_blend_debug_remove",
    "shapekeytools_blend_debug_clear",
    "shapekeytools_blend_point_add_active",
    "shapekeytools_blend_point_remove",
    "shapekeytools_blend_point_set_key",
    "shapekeytools_blend_object_add",
    "shapekeytools_blend_object_remove",
    "shapekeytools_blend_object_clear",
    "shapekeytools_blend_apply",
    "shapekeytools_blend_reset_cursor",
    "shapekeytools_blend_clear_all_keys",
    "shapekeytools_blend_jump_to_point",
    "shapekeytools_blend_widget",
    "shapekeytools_blend_widget_pick",
    "shapekeytools_blend_widget_key",
    "shapekeytools_blend_widget_stop",
):
    struct = "HO_OT_" + operator_id
    assert hasattr(bpy.types, struct), f"{operator_id} 没有注册（{struct} 不存在）"

# 被删掉的一坨添加/批量功能必须真的消失
for removed in (
    "shapekeytools_blend_point_add",
    "shapekeytools_blend_point_clear",
    "shapekeytools_blend_point_from_active",
    "shapekeytools_blend_point_from_object",
    "shapekeytools_blend_point_grid",
    "shapekeytools_blend_point_toggle",
    "shapekeytools_blend_point_nudge",
    "shapekeytools_blend_clear_weights",
    "shapekeytools_blend_toggle_weights",
):
    assert not hasattr(bpy.types, "HO_OT_" + removed), f"{removed} 应该已删除"
    assert not hasattr(store, removed), f"{removed} 应该已删除"

# ── 坐标自动排布 ──────────────────────────────────────────────────────────
assert point_layout.grid_coordinates(0) == []
assert point_layout.grid_coordinates(1) == [(0.0, 0.0)]
assert point_layout.grid_coordinates(2) == [(-1.0, 0.0), (1.0, 0.0)]
assert point_layout.grid_coordinates(4) == [
    (-1.0, 1.0), (1.0, 1.0), (-1.0, -1.0), (1.0, -1.0)]
nine = point_layout.grid_coordinates(9)
assert len(nine) == 9 and nine[0] == (-1.0, 1.0) and nine[4] == (0.0, 0.0)
assert nine[-1] == (1.0, -1.0)

# ── 场景数据 ──────────────────────────────────────────────────────────────
clear_scene()
bpy.context.scene.ho_bs_debug_items.clear()
bpy.context.scene.ho_bs_debug_index = 0

face_a = make_face("FaceA", ["Smile_L", "Smile_R", "Open", "Extra"])
face_b = make_face("FaceB", ["Smile_L", "Smile_R", "Open", "Extra"])
for obj in bpy.context.selected_objects:
    obj.select_set(False)
face_a.select_set(True)
bpy.context.view_layer.objects.active = face_a

assert bpy.ops.ho.shapekeytools_blend_debug_add() == {'FINISHED'}
item = store.active_item(bpy.context.scene)
assert item is not None
assert [entry.object for entry in item.objects] == [face_a]

# ── 添加当前形态键（唯一的新增入口）：加一个、活动键切到下一个 ──────────────
# 先把活动键摆在第一个，方便按顺序验证
shape_keys = face_a.data.shape_keys
face_a.active_shape_key_index = shape_keys.key_blocks.find("Smile_L")
assert bpy.ops.ho.shapekeytools_blend_point_add_active() == {'FINISHED'}
assert [point.shape_key for point in item.points] == ["Smile_L"]
assert face_a.active_shape_key.name == "Smile_R", "添加后活动键应切到下一个"
# 连续点击会把剩下的键逐个加进来
for expected in ("Smile_R", "Open", "Extra"):
    assert bpy.ops.ho.shapekeytools_blend_point_add_active() == {'FINISHED'}
    assert item.points[-1].shape_key == expected
assert [point.shape_key for point in item.points] == [
    "Smile_L", "Smile_R", "Open", "Extra"]
assert len(item.points) == 4
# 点位自动占空格子：坐标互不重合，且落在矩阵范围内
assert len(store.occupied_coordinates(item)) == 4, "每个点位应占一个不同的格子"
for point in item.points:
    assert -1.0 <= point.u <= 1.0 and -1.0 <= point.v <= 1.0, (point.u, point.v)
# 删掉多余的点，后面的断言按三点矩阵算
item.points.remove(3)

# 重复添加同一个键不会新建点位，只把活动行切过去
face_a.active_shape_key_index = shape_keys.key_blocks.find("Smile_L")
assert bpy.ops.ho.shapekeytools_blend_point_add_active() == {'FINISHED'}
assert len(item.points) == 3, "已在矩阵里的键不该重复添加"
assert item.point_index == 0, "应该切到已有的那一行"
# 停在基础键上时从第一个可用键开始
face_a.active_shape_key_index = shape_keys.key_blocks.find("Basis")
assert bpy.ops.ho.shapekeytools_blend_point_add_active() == {'FINISHED'}
assert len(item.points) == 3, "基础键不产生新点位"

# ── 点位找空位 ────────────────────────────────────────────────────────────
# 用一个临时矩阵验证，别动上面那个已经摆好的
scratch = bpy.context.scene.ho_bs_debug_items.add()
assert store.free_grid_coordinate(scratch) == (0.0, 0.0), "空矩阵的第一个格子是原点"
scratch_point = scratch.points.add()
scratch_point.shape_key = "K0"
scratch_point.u, scratch_point.v = (0.0, 0.0)
assert store.free_grid_coordinate(scratch) in point_layout.grid_coordinates(2), (
    "原点被占了以后要换到相邻格子")
assert store.free_grid_coordinate(scratch) != (0.0, 0.0)
assert store.occupied_coordinates(scratch) == {(0.0, 0.0): 0}
assert store.occupied_coordinates(scratch, exclude=0) == {}
bpy.context.scene.ho_bs_debug_items.remove(
    len(bpy.context.scene.ho_bs_debug_items) - 1)
store.clamp_index(bpy.context.scene)

# 加/减/清空：操作物体对象列表（行下标存在场景上，供 template_list 使用）
face_b.select_set(True)
bpy.context.view_layer.objects.active = face_b
assert bpy.ops.ho.shapekeytools_blend_object_add() == {'FINISHED'}
assert len(item.objects) == 2
assert store.object_list_index(bpy.context.scene) == 1, "新增后应选中第一行新增项"
assert bpy.ops.ho.shapekeytools_blend_object_add() == {'FINISHED'}  # 幂等
assert len(item.objects) == 2
store.set_object_list_index(bpy.context.scene, 1)
assert bpy.ops.ho.shapekeytools_blend_object_remove() == {'FINISHED'}
assert len(item.objects) == 1
assert store.object_list_index(bpy.context.scene) == 0, "删除后行下标要夹回范围内"
# 越界写入会被夹住，列表控件不会拿到非法下标
assert store.set_object_list_index(bpy.context.scene, 99) == 0
assert bpy.ops.ho.shapekeytools_blend_object_add() == {'FINISHED'}
assert len(item.objects) == 2
assert store.set_object_list_index(bpy.context.scene, 5) == 1
assert store.set_object_list_index(bpy.context.scene, -3) == 0

# 物体行不再有「启用/禁用」与「选中该物体」：列表里的行全部参与混合
assert not hasattr(store, "OP_ShapekeyTools_BlendObjectToggle")
assert not hasattr(store, "OP_ShapekeyTools_BlendObjectSelect")
for removed in ("HO_OT_shapekeytools_blend_object_toggle",
                "HO_OT_shapekeytools_blend_object_select"):
    assert not hasattr(bpy.types, removed), f"{removed} 应该已经从注册表里消失"
assert store.PG_ShapekeyTools_BlendObject.bl_rna.properties.get("enabled") is None, (
    "物体行不该再有 enabled")
assert [entry.object for entry in item.objects] == [face_a, face_b]
assert shapekey_utils.active_objects(item) == [face_a, face_b]
assert shapekey_utils.total_objects(item) == 2
# 指针失效的行会被自动按名字回查；查不到就跳过，不影响其它行
item.objects[0].object = None
item.objects[0].object_name = "已经不存在了"
assert shapekey_utils.active_objects(item) == [face_b], "失效行应被跳过"
item.objects[0].object = face_a
item.objects[0].object_name = face_a.name
assert shapekey_utils.active_objects(item) == [face_a, face_b]

# ── 权重求值与写入 ────────────────────────────────────────────────────────
# 把三个点位摆成明确的三角形，权重才好算
item.points[0].shape_key = "Smile_L"
item.points[1].shape_key = "Smile_R"
item.points[2].shape_key = "Open"
for point, (u, v) in zip(item.points, ((-1.0, 1.0), (1.0, 1.0), (-1.0, -1.0))):
    point.u, point.v = u, v
item.mix_mode = blend_math.MODE_CARTESIAN_2D
item.cursor_u = 1.0
item.cursor_v = 1.0
editor.invalidate_weight_cache()
weights, names = editor.evaluate_item(item)
assert names == ("Smile_L", "Smile_R", "Open")
assert_close(weights[1], 1.0, message="右上角应完全取 Smile_R")
assert_close(weights[0], 0.0)
assert_close(weights[2], 0.0)

report = blend_func.apply_weights(bpy.context, item)
assert not report.failed, report.failed
assert report.objects == 2
assert report.written == 6  # 3 个键 × 2 个物体
assert_close(face_a.data.shape_keys.key_blocks["Smile_R"].value, 1.0)
assert_close(face_b.data.shape_keys.key_blocks["Smile_R"].value, 1.0)
assert_close(face_a.data.shape_keys.key_blocks["Smile_L"].value, 0.0)
assert face_a.data.shape_keys.key_blocks["Extra"].mute is True, "矩阵外的键应被静音"
assert face_a.data.shape_keys.key_blocks["Smile_L"].mute is False, "矩阵内的键不应被静音"
assert face_a.data.shape_keys.key_blocks["Smile_R"].mute is False

# 中心点：三点矩阵的输入落在两个点上时权重均分
item.cursor_u = 0.0
item.cursor_v = 1.0
editor.invalidate_weight_cache()
weights, _names = editor.evaluate_item(item)
assert_close(sum(weights), 1.0, message="权重和")
assert_close(weights[0], 0.5, message="上边中点")
assert_close(weights[1], 0.5, message="上边中点")

# 1D 简单模式：先把三个点摆成真正的一维直线，再验证相邻插值
item.mix_mode = blend_math.MODE_SIMPLE_1D
item.cursor_v = 0.0
for point, (u, v) in zip(item.points, ((-1.0, 0.0), (1.0, 0.0), (0.0, 0.0))):
    point.u = u
    point.v = v
item.cursor_u = 0.0
editor.invalidate_weight_cache()
weights, _names = editor.evaluate_item(item)
assert_close(sum(weights), 1.0, message="1D 权重和")
assert_close(weights[2], 1.0, message="1D 取到中间点")
item.cursor_u = 0.5
editor.invalidate_weight_cache()
weights, _names = editor.evaluate_item(item)
# 点位顺序是 Smile_L(u=-1) / Smile_R(u=1) / Open(u=0)，u=0.5 落在 Open 与 Smile_R 之间
assert_close(weights[2], 0.5, message="1D 相邻插值（Open）")
assert_close(weights[1], 0.5, message="1D 相邻插值（Smile_R）")
assert_close(weights[0], 0.0, message="1D 不相邻点权重为 0")

# 点位没有启用/禁用开关了：矩阵里出现的点一律参与混合
assert store.PG_ShapekeyTools_BlendPoint.bl_rna.properties.get("enabled") is None
for removed in ("shapekeytools_blend_point_toggle",
                "shapekeytools_blend_point_nudge",
                "shapekeytools_blend_point_clear",
                "shapekeytools_blend_point_grid",
                "shapekeytools_blend_point_from_active",
                "shapekeytools_blend_point_from_object"):
    assert not hasattr(bpy.types, "HO_OT_" + removed), f"{removed} 应该已删除"
assert shapekey_utils.points(item) == tuple(item.points)

# 空物体列表时不会误写，且报告里能看出没有物体
item.objects.clear()
editor.invalidate_weight_cache()
empty_report = blend_func.apply_weights(bpy.context, item)
assert empty_report.written == 0 and empty_report.objects == 0
assert bpy.ops.ho.shapekeytools_blend_object_add() == {'FINISHED'}

# ── 全键归零：所有形态键归零 + 活动键切回基型 ─────────────────────────────
bpy.context.view_layer.objects.active = face_a
face_a.active_shape_key_index = face_a.data.shape_keys.key_blocks.find("Smile_R")
face_a.data.shape_keys.key_blocks["Extra"].value = 0.7
assert bpy.ops.ho.shapekeytools_blend_clear_all_keys() == {'FINISHED'}
assert_close(face_a.data.shape_keys.key_blocks["Smile_R"].value, 0.0)
assert_close(face_a.data.shape_keys.key_blocks["Extra"].value, 0.0), (
    "矩阵里没有的键也要归零")
assert face_a.active_shape_key.name == "Basis", "全键归零后活动键要切回基型"
assert face_b.data.shape_keys.key_blocks["Smile_R"].value == 0.0
assert not hasattr(bpy.types, "HO_OT_shapekeytools_blend_clear_weights"), (
    "旧的「归零权重」应已被「全键归零」取代")
assert not hasattr(bpy.types, "HO_OT_shapekeytools_blend_toggle_weights")

# ── 调试矩阵：新建/删除/清空 ─────────────────────────────────────────────
assert bpy.ops.ho.shapekeytools_blend_debug_add() == {'FINISHED'}
assert len(bpy.context.scene.ho_bs_debug_items) == 2
assert bpy.ops.ho.shapekeytools_blend_debug_remove() == {'FINISHED'}
assert len(bpy.context.scene.ho_bs_debug_items) == 1
assert store.active_item(bpy.context.scene).as_pointer() == item.as_pointer(), (
    "删除新建的矩阵后活动矩阵应回到原来那个")

# 换一个形态键名也要能改（挑选菜单走这条路径）
assert bpy.ops.ho.shapekeytools_blend_point_set_key(
    index=0, shape_key="Open") == {'FINISHED'}
assert item.points[0].shape_key == "Open"
assert item.points[0].name == "Open"
assert bpy.ops.ho.shapekeytools_blend_point_set_key(
    index=0, shape_key="Smile_L") == {'FINISHED'}

assert bpy.ops.ho.shapekeytools_blend_debug_clear() == {'FINISHED'}
assert len(bpy.context.scene.ho_bs_debug_items) == 0
assert store.active_item(bpy.context.scene) is None

# 绘件状态机（后台没有 3D 视口，只验证不会抛异常）
assert overlay.WIDGET.is_running is False
overlay.WIDGET.start(bpy.context)
assert overlay.WIDGET.is_running is True
overlay.WIDGET.stop()
assert overlay.WIDGET.is_running is False

# ── 绘件布局与命中几何 ────────────────────────────────────────────────────
bpy.ops.ho.shapekeytools_blend_debug_add()
item = store.active_item(bpy.context.scene)
item.points.clear()
for index, (u, v) in enumerate(((-1.0, 1.0), (1.0, 1.0), (-1.0, -1.0), (1.0, -1.0))):
    point = item.points.add()
    point.shape_key = f"K{index}"
    point.u, point.v = u, v
item.cursor_u = 0.5
item.cursor_v = -0.25

layout = overlay.compute_layout(1200.0, 800.0, item, 4)
panel_x, panel_y, panel_w, panel_h = layout["panel"]
plot_x, plot_y, plot_w, plot_h = layout["plot"]
assert layout["anchor"] == "BOTTOM_LEFT"
assert panel_x == overlay._PANEL_MARGIN, "绘件应贴左边距"
assert panel_y == overlay._PANEL_MARGIN, "绘件应贴下边距"
assert panel_x + panel_w <= 1200.0 and panel_y + panel_h <= 800.0, "绘件不能越界"
assert panel_x + panel_w < 1200.0 - panel_x, "绘件应偏左下，而不是偏右"
assert plot_w == plot_h, "坐标系必须是正方形"
assert (plot_x, plot_y) == (
    panel_x + overlay._PLOT_PADDING, panel_y + overlay._FOOTER_HEIGHT + overlay._PLOT_PADDING)

# 小视口也要能放下（等比缩小，仍然贴左下角，不越界）
small = overlay.compute_layout(320.0, 260.0, item, 4)
sx, sy, sw, sh = small["panel"]
assert sx == overlay._PANEL_MARGIN and sy == overlay._PANEL_MARGIN, small["panel"]
assert sx + sw <= 320.0 and sy + sh <= 260.0, small["panel"]
assert small["plot"][2] >= 40.0, small["plot"]
# 没有区域尺寸时也要给得出左下角布局（脚本/后台调用）
blind = overlay.compute_layout(0.0, 0.0, item, 4)
assert blind["panel"][:2] == (overlay._PANEL_MARGIN, overlay._PANEL_MARGIN)

# 坐标点与中心点的像素位置必须和坐标映射一致
handles, centre = overlay._compute_handles(item, layout)
assert len(handles) == 4
centre_expected = overlay._uv_to_plot(item.cursor_u, item.cursor_v, layout)
assert_close(centre[0], centre_expected[0], 1e-6, "中心点 x")
assert_close(centre[1], centre_expected[1], 1e-6, "中心点 y")
# 反向映射必须回到原坐标
u_back, v_back = overlay._plot_to_uv(centre[0], centre[1], layout)
assert_close(u_back, item.cursor_u, 1e-6, "中心点 u 往返")
assert_close(v_back, item.cursor_v, 1e-6, "中心点 v 往返")
# 坐标点手柄落在坐标系内
for _kind, _index, x, y in handles:
    assert plot_x <= x <= plot_x + plot_w, (x, plot_x, plot_w)
    assert plot_y <= y <= plot_y + plot_h, (y, plot_y, plot_h)
# 夹取：越界的鼠标坐标会被夹回坐标系内
clamped = overlay._clamp_to_plot(plot_x - 500.0, plot_y + 99999.0, layout)
assert clamped == (plot_x, plot_y + plot_h), clamped

# ── 点位不能飞出坐标系（回归：重排为矩阵后坐标变了、范围却没重算）────────────
# 坐标系范围按「点位坐标」缓存：只按数量缓存时，重排（数量不变）会让新坐标落在旧
# 范围外，点位被映射到矩形外。这里直接覆盖「重排 → 重算 → 仍在框内」。
overlay.invalidate_axis_range()
item.points.clear()
for slot in range(9):
    point = item.points.add()
    point.shape_key = f"G{slot}"
    point.u, point.v = 0.9, -0.9
layout_nine = overlay.compute_layout(900.0, 700.0, item, 9)
plot_rect = layout_nine["plot"]
handles_nine, _centre_nine = overlay._compute_handles(item, layout_nine)
for _kind, index, x, y in handles_nine:
    assert plot_rect[0] <= x <= plot_rect[0] + plot_rect[2], (index, x)
    assert plot_rect[1] <= y <= plot_rect[1] + plot_rect[3], (index, y)

for slot, point in enumerate(item.points):  # 只改坐标、不改数量
    point.u, point.v = (-1.0, 0.0, 1.0)[slot % 3], (1.0, 0.0, -1.0)[slot % 3]
grid_range = overlay._cached_axis_range(item)
assert grid_range == (-1.15, 1.15, -1.15, 1.15), (
    f"改坐标后坐标系范围必须重新适配，实际 {grid_range}")
layout_grid = overlay.compute_layout(900.0, 700.0, item, 9)
handles_grid, _centre_grid = overlay._compute_handles(item, layout_grid)
grid_rect = layout_grid["plot"]
for _kind, index, x, y in handles_grid:
    assert grid_rect[0] <= x <= grid_rect[0] + grid_rect[2], (
        f"重排后点位 {index} 飞出坐标系：x={x}")
    assert grid_rect[1] <= y <= grid_rect[1] + grid_rect[3], (
        f"重排后点位 {index} 飞出坐标系：y={y}")
grid_xs = sorted(x for _k, _i, x, _y in handles_grid)
assert grid_xs[0] < grid_xs[-1], "重排后点位不该挤在一起"

# 手滑输入了离谱坐标（UI 的 soft_min/soft_max 不限制硬输入）也要夹在框内
item.points[0].u = 98765.0
item.points[0].v = -43210.0
overlay.invalidate_axis_range()
layout_wild = overlay.compute_layout(900.0, 700.0, item, 9)
wild_handles, _c = overlay._compute_handles(item, layout_wild)
wild_rect = layout_wild["plot"]
for _kind, index, x, y in wild_handles:
    assert wild_rect[0] - 0.5 <= x <= wild_rect[0] + wild_rect[2] + 0.5, (index, x)
    assert wild_rect[1] - 0.5 <= y <= wild_rect[1] + wild_rect[3] + 0.5, (index, y)
item.points[0].u, item.points[0].v = -1.0, 1.0
overlay.invalidate_axis_range()

# 拖动中心点只改输入、不改坐标：范围必须保持稳定（否则拖动时映射会漂）
range_before = overlay._cached_axis_range(item)
item.cursor_u, item.cursor_v = 0.42, -0.37
assert overlay._cached_axis_range(item) == range_before, "拖动中心点不该让范围漂移"
item.cursor_u, item.cursor_v = 0.0, 0.0

# 拖动点位期间范围要锁住：否则每帧重新适配，点位会追不上鼠标
locked = overlay._cached_axis_range(item)
overlay.set_drag_active(True)
item.points[0].u, item.points[0].v = 0.1, 0.1
assert overlay.axis_range_for(item) == locked, "拖动中范围必须锁定"
item.points[0].u, item.points[0].v = 55.0, -55.0
assert overlay.axis_range_for(item) == locked, "拖动中点位跑远也不该改范围"
# 松手后重新适配，并且点位仍然落在坐标系内
overlay.set_drag_active(False)
fitted = overlay.axis_range_for(item)
assert fitted != locked, "松手后必须重新适配范围"
assert fitted[1] >= 55.0 and fitted[0] <= -55.0, fitted
drag_layout = overlay.compute_layout(900.0, 700.0, item, 9)
drag_rect = drag_layout["plot"]
for _kind, index, x, y in overlay._compute_handles(item, drag_layout)[0]:
    assert drag_rect[0] - 0.5 <= x <= drag_rect[0] + drag_rect[2] + 0.5, (index, x)
    assert drag_rect[1] - 0.5 <= y <= drag_rect[1] + drag_rect[3] + 0.5, (index, y)
assert overlay.axis_range_for(item) == fitted, "没有变化时不该反复重算"

# ── 视口变化后仍要能点中（回归：Ctrl+Space 最大化 / 切换工作区后控件点不动）──────
# 缓存区域尺寸变了就必须丢掉旧布局，否则会照着旧矩形画、拿新视口的鼠标坐标去命中。
overlay.WIDGET.area = None
overlay.WIDGET.layout_size = None
overlay.WIDGET.last_layout = None
size_a = overlay.WIDGET._layout_for_size(bpy.context, item, 560.0, 728.0, (0.25,) * 4)
assert overlay.WIDGET.layout_size == (560.0, 728.0)
assert overlay.WIDGET._layout_for_size(bpy.context, item, 560.0, 728.0, (0.25,) * 4) is size_a, (
    "同一尺寸必须复用同一份布局")
size_b = overlay.WIDGET._layout_for_size(bpy.context, item, 1280.0, 720.0, (0.25,) * 4)
assert size_b is not size_a, "尺寸变了必须重算布局"
assert overlay.WIDGET.layout_size == (1280.0, 720.0)
b_x, b_y, b_w, b_h = size_b["panel"]
assert (b_x, b_y) == (overlay._PANEL_MARGIN, overlay._PANEL_MARGIN)
assert b_x + b_w <= 1280.0 and b_y + b_h <= 720.0

# 用「新视口尺寸 + 新视口的鼠标坐标」做命中：中心点必须点得到
handles_b, centre_b = overlay._compute_handles(item, size_b)
hits = [
    (kind, index)
    for kind, index, x, y in handles_b
    if abs(x - centre_b[0]) < 1.0 and abs(y - centre_b[1]) < 1.0
]
# 中心点一定落在坐标系矩形内，且被拖动后会跟着新布局走
assert size_b["plot"][0] <= centre_b[0] <= size_b["plot"][0] + size_b["plot"][2]
assert size_b["plot"][1] <= centre_b[1] <= size_b["plot"][1] + size_b["plot"][3]
# 布局是纯函数：同样的尺寸与数据一定给出同样的矩形（命中测试靠这个保证一致）
again = overlay.compute_layout(1280.0, 720.0, item, 4)
assert again["panel"] == size_b["panel"]
assert again["plot"] == size_b["plot"]

# stop() 必须把布局缓存一并清掉，避免下次启动沿用上个视口的矩形
overlay.WIDGET.stop()
assert overlay.WIDGET.layout_size is None and overlay.WIDGET.last_layout is None

# 视口解析：解析不出来时必须安全返回 (None, None)，解析出来时必须是 3D 视口，
# 两种情况都不许抛异常（后台 Blender 也可能带着屏幕/区域数据）。
for resolved, region in (overlay.resolve_area(bpy.context),
                         overlay.resolve_area(None),
                         overlay.resolve_area(bpy.context, preferred=None)):
    if resolved is None:
        assert region is None
    else:
        assert resolved.type == 'VIEW_3D', resolved.type
# 心跳定时器在后台也能安全地启停
overlay.ensure_widget_timer()
overlay.stop_widget_timer()
assert overlay.WIDGET.timer_running is False

# ── 交互不再挂在模态算子上（回归：Ctrl+Space / 切工作区后控件点不动）────────────
# 交互改成「3D 视口空间级快捷键 + 点击时短模态」：快捷键不随工作区切换失效，
# 所以点击永远有事件进来。这里验证快捷键绑定、命中函数与命令算子都就位。
keymap = overlay._addon_keymap()
assert keymap is not None and keymap.space_type == 'VIEW_3D', keymap
bindings = overlay.bind_widget_keys()
assert bindings, "必须绑上左键快捷键"
bound = {(item.idname, item.type) for _keymap, item in bindings}
assert (overlay.OP_ShapekeyTools_BlendWidgetPick.bl_idname, 'LEFTMOUSE') in bound, bound
assert (overlay.OP_ShapekeyTools_BlendWidgetKey.bl_idname, 'R') in bound, bound
assert (overlay.OP_ShapekeyTools_BlendWidgetKey.bl_idname, 'W') in bound, bound
assert (overlay.OP_ShapekeyTools_BlendWidgetKey.bl_idname, 'LEFT_BRACKET') in bound
assert (overlay.OP_ShapekeyTools_BlendWidgetKey.bl_idname, 'RIGHT_BRACKET') in bound
# 重复绑定不叠加
assert len(overlay.bind_widget_keys()) == len(bindings), "重复绑定必须幂等"
WIDGET_REAL = overlay.WIDGET
try:
    # 命中函数：没在工作时一律不命中，不许抛异常
    WIDGET_REAL.is_running = False
    assert overlay.pick_in_area(bpy.context, 10.0, 10.0) == (None, -1)
    WIDGET_REAL.is_running = True
    bpy.ops.ho.shapekeytools_blend_debug_add()
    live_item = store.active_item(bpy.context.scene)
    live_item.points.clear()
    for slot, (u, v) in enumerate(((-1.0, 1.0), (1.0, 1.0), (-1.0, -1.0))):
        point = live_item.points.add()
        point.shape_key = f"P{slot}"
        point.u, point.v = u, v
    # 不给区域时命中函数应安全返回（后台没有可视视口）
    assert overlay.pick_in_area(bpy.context, 10.0, 10.0) == (None, -1)
    # 命令算子：R / W / [ / ] 都要能跑
    WIDGET_REAL.is_running = True
    live_item.cursor_u, live_item.cursor_v = 0.4, -0.3
    for command in ("RESET", "CLEAR", "SCALE_UP", "SCALE_DOWN"):
        result = bpy.ops.ho.shapekeytools_blend_widget_key(command=command)
        assert result == {'FINISHED'}, (command, result)
    assert (live_item.cursor_u, live_item.cursor_v) == (0.0, 0.0)
    assert overlay.WIDGET.scale == 1.0, overlay.WIDGET.scale
    # 收尾：快捷键、句柄、定时器、状态一次清干净
    WIDGET_REAL.handles.append(
        bpy.types.SpaceView3D.draw_handler_add(lambda: None, (), 'WINDOW', 'POST_PIXEL'))
    WIDGET_REAL.keymaps.extend(bindings)
    WIDGET_REAL.cancel("测试收尾")
    assert overlay.WIDGET.is_running is False
    assert not overlay.WIDGET.keymaps and not overlay.WIDGET.handles
finally:
    WIDGET_REAL.keymaps.clear()
    WIDGET_REAL.handles.clear()
    WIDGET_REAL.is_running = False

bpy.ops.ho.shapekeytools_blend_debug_clear()

# ── 注册契约：UIList / Menu 必须显式给出 bl_idname ─────────────────────────
# 回归：HO_UL_ShapekeyTools_BlendPoints 当初没写 bl_idname，
# template_list 直接 AttributeError（UIList 和 Menu 都不会从类名自动生成）。
def assert_registered_identifiers(module, expected_prefix):
    for item in module.cls:
        if getattr(item, "is_operator", False) or getattr(item, "is_property_group", False):
            identifier = getattr(item, "bl_idname", None)
        else:
            identifier = getattr(item, "bl_idname", None) or item.__name__
        assert identifier, f"{module.__name__}.{item.__name__} 缺少注册标识"
        if expected_prefix and hasattr(item, "bl_idname"):
            assert item.bl_idname, f"{item.__name__}.bl_idname 是空字符串"


assert_registered_identifiers(store, None)
assert_registered_identifiers(editor, None)
assert_registered_identifiers(overlay, None)
for klass in (editor.HO_UL_ShapekeyTools_BlendPoints,
              editor.HO_UL_ShapekeyTools_BlendObjects,
              editor.HO_MT_ShapekeyTools_BlendPointKey):
    assert issubclass(klass, (bpy.types.UIList, bpy.types.Menu)), klass
    assert klass.bl_idname, f"{klass.__name__} 必须显式声明 bl_idname"
assert editor.HO_UL_ShapekeyTools_BlendPoints.bl_idname == (
    editor.HO_UL_ShapekeyTools_BlendPoints.__name__)
# template_list 既能按 bl_idname 也能按类名查找，两种写法都必须命中
assert editor.HO_UL_ShapekeyTools_BlendPoints.bl_idname.startswith("HO_UL_")

# draw_item 的签名必须是 UIList 约定的形式
import inspect  # noqa: E402

parameters = list(inspect.signature(
    editor.HO_UL_ShapekeyTools_BlendPoints.draw_item).parameters)
assert parameters[:2] == ["self", "context"], parameters
assert len(parameters) == 9, parameters

# 空状态下画页面不能抛异常（后台模式里 UILayout 不可用，所以只做数据层校验）
bpy.context.scene.ho_ShapekeyToolsPanel_Mod = 'PANEL_SHAPEKEYTOOLS_BLENDMATRIX'
assert store.active_item(bpy.context.scene) is None
bpy.ops.ho.shapekeytools_blend_debug_add()
empty_item = store.active_item(bpy.context.scene)
assert editor.evaluate_item(empty_item) == ((), ())
assert blend_func.evaluate_item(empty_item) == ((), ())
assert shapekey_utils.points(empty_item) == ()
assert point_layout.duplicate_coordinate_groups(empty_item) == []
assert shapekey_utils.candidate_shape_keys(empty_item, bpy.context) == [
    "Smile_L", "Smile_R", "Open", "Extra"]
assert blend_func.candidate_shape_key_names(empty_item, bpy.context) == [
    "Smile_L", "Smile_R", "Open", "Extra"]
assert blend_func.item_weights(empty_item) == []

# ── 工具包拆分契约 ────────────────────────────────────────────────────────
# 纯数学必须保持零 bpy 依赖，才能被 Blender 之外的单元测试直接导入。
import ast  # noqa: E402

math_source = Path(blend_math.__file__).read_text(encoding='utf-8')
math_imports = {
    node.names[0].name.split('.')[0]
    for node in ast.walk(ast.parse(math_source))
    if isinstance(node, ast.Import)
} | {
    (node.module or '').split('.')[0]
    for node in ast.walk(ast.parse(math_source))
    if isinstance(node, ast.ImportFrom)
}
assert not ({'bpy', 'gpu', 'blf', 'gpu_extras'} & math_imports), math_imports

# 工具模块位置正确：功能工具与绘制工具都在 blend_utils 包里
assert blend_func.__name__.endswith("blend_utils.blend_func")
assert draw_func.__name__.endswith("blend_utils.draw_func")
assert blend_math.__name__.endswith("blend_utils.blend_space_math")
assert shapekey_utils.__name__.endswith("blend_utils.shapekey_utils")
assert point_layout.__name__.endswith("blend_utils.point_layout")
assert overlay.__name__.endswith("blend_overlay")

# 数据层不应该再带界面 / 绘制 / 取值 / 排布代码：store 只留数据模型与数据算子
for leaked in (
    "draw_object_list",        # 列表绘制 → blend_editor 的标准 UIList
    "enabled_points",          # 点位不再有启用开关
    "active_objects",
    "resolve_object",
    "shape_key_names",
    "unique_shape_keys",
    "candidate_shape_keys",
    "mesh_candidates",
    "append_object",
    "grid_coordinates",        # 排布 → point_layout
    "assign_grid",             # 重排已删
    "duplicate_coordinate_groups",
    "iter_points",
):
    assert not hasattr(store, leaked), f"store 不该再有 {leaked}"
# store 只保留“选择态”取值（数据和它的下标是同一层的东西）
for kept in ("debug_items", "active_index", "active_item", "clamp_index",
             "object_list_index", "set_object_list_index"):
    assert hasattr(store, kept), f"store 应该保留 {kept}"
# 其他模块也不该留着已搬走的实现
assert not hasattr(store, "draw_object_list"), "物体列表绘制应交给标准 UIList"
assert not hasattr(draw_func, "draw_object_list"), (
    "draw_func 只放 GPU 图元/文字，列表交给 template_list")
assert not hasattr(overlay, "apply_weights"), "权重写入应放在 blend_func"
assert not hasattr(blend_func, "draw_widget")
assert not hasattr(draw_func, "draw_widget")

# ── 操作物体对象列表：标准 UIList + template_list 契约 ─────────────────────
object_list = editor.HO_UL_ShapekeyTools_BlendObjects
assert issubclass(object_list, bpy.types.UIList)
assert object_list.bl_idname == object_list.__name__
assert object_list.bl_idname.startswith("HO_UL_")
# 行绘制签名必须符合 UIList 约定
object_parameters = list(inspect.signature(object_list.draw_item).parameters)
assert object_parameters[:2] == ["self", "context"], object_parameters
assert len(object_parameters) == 9, object_parameters
# 列表数据在调试矩阵上、活动行下标在场景上（template_list 需要 ID 上的下标）
assert store.PG_ShapekeyTools_BlendDebugItem.bl_rna.properties.get("objects")
assert store.PG_ShapekeyTools_BlendDebugItem.bl_rna.properties.get(
    "objects_index") is None, "行下标不该留在条目上，应由场景持有"
assert bpy.types.Scene.bl_rna.properties.get("ho_bs_object_list") is not None
# 物体行只需要「物体指针 + 名字兜底」：没有启用开关，也没有别的行状态
assert set(store.PG_ShapekeyTools_BlendObject.bl_rna.properties.keys()) >= {
    "object", "object_name"}
assert store.PG_ShapekeyTools_BlendObject.bl_rna.properties.get("enabled") is None

# 取值工具的两种入口都要能用（shapekey_utils 实现 + blend_func 转发别名）
assert shapekey_utils.shape_key_names(face_a) == blend_func.shape_key_names(face_a)
assert shapekey_utils.points is blend_func.points
assert shapekey_utils.active_objects is blend_func.active_objects
# 往列表里加物体：去重 + 类型校验
probe_item = bpy.context.scene.ho_bs_debug_items.add()
assert shapekey_utils.append_object(probe_item, face_a) is True
assert shapekey_utils.append_object(probe_item, face_a) is False  # 幂等
assert shapekey_utils.append_object(probe_item, None) is False
assert shapekey_utils.append_objects(probe_item, [face_a, face_b]) == 1
assert shapekey_utils.ensure_active_object(probe_item, bpy.context) is False
probe_item.objects.clear()
active_name = getattr(bpy.context.object, "name", None)
assert shapekey_utils.ensure_active_object(probe_item, bpy.context) is True
assert [entry.object for entry in probe_item.objects] == [bpy.context.object], (
    active_name, [entry.object_name for entry in probe_item.objects])
bpy.context.scene.ho_bs_debug_items.remove(
    len(bpy.context.scene.ho_bs_debug_items) - 1)

# 颜色插值（纯计算，不需要 GPU）：权重越高越暖，0 权重是暗色
cold = draw_func.weight_color(0.0)
hot = draw_func.weight_color(1.0)
assert hot[0] > cold[0] and hot[2] < cold[2], (cold, hot)
mid = draw_func.weight_color(0.5)
assert cold[0] < mid[0] < hot[0], (cold, mid, hot)
# 夹取与坐标映射的薄封装要和数学层一致
rect = (10.0, 20.0, 100.0, 100.0)
axis_range = (-1.0, 1.0, -1.0, 1.0)
assert draw_func.clamp_to_rect(-50.0, 500.0, rect) == (10.0, 120.0)
assert draw_func.clamp_to_rect(60.0, 70.0, rect) == (60.0, 70.0)
assert draw_func.plot_to_uv(*draw_func.uv_to_plot(0.5, -0.5, rect, axis_range),
                            rect, axis_range) == (0.5, -0.5)
bpy.ops.ho.shapekeytools_blend_debug_clear()

# ── 绘制期不许写 ID 属性（回归：物体列表越界下标导致整个面板画不出来）────────
# Blender 在面板绘制回调里禁止写 ID（Scene/Object…）属性，一旦写就抛
# “Writing to ID classes in this context is not allowed”，面板从那里断掉。
# 这里用一个记录型 layout 代理把 drawBlendPanel 真正跑一遍，并录下所有对
# scene/mesh 这类 ID 数据块的赋值，确保绘制期一个都没有。
_ID_TYPES = (bpy.types.Scene, bpy.types.Object, bpy.types.Mesh,
             bpy.types.Collection, bpy.types.World)


class _RecordingLayout:
    """包一层真实 UILayout，记录它会写哪些 ID 属性。

    只暴露 panel 绘制真正用到的那些方法；其余属性转发给真实 layout，
    这样 ``box.row()`` / ``row.prop(...)`` 这些照常工作。
    """

    def __init__(self, real, writes, calls):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_writes", writes)
        object.__setattr__(self, "_calls", calls)

    def __getattr__(self, name):
        target = getattr(object.__getattribute__(self, "_real"), name)
        if not callable(target):
            return target

        def _call(*args, **kwargs):
            object.__getattribute__(self, "_calls").append(
                (name, tuple(type(a).__name__ for a in args)))
            # 模拟画一个属性：如果目标是 ID 数据块，就是绘制期写 ID
            if name == "prop" and args and isinstance(args[0], _ID_TYPES):
                object.__getattribute__(self, "_writes").append(
                    (type(args[0]).__name__, args[1] if len(args) > 1 else "?"))
            return target(*args, **kwargs)
        return _call


def assert_panel_draws_without_writing_ids(state_setup):
    """在真实绘制回调里跑一遍面板，断言没有对 ID 属性赋值。"""
    outcome = {"writes": [], "calls": [], "errors": []}

    class _PanelProbe(bpy.types.Panel):
        bl_idname = "HO_PT_blend_matrix_draw_probe"
        bl_label = "混合矩阵绘制探针"
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'UI'
        bl_category = "HoTools"
        bl_options = set()

        def draw(self, context):
            state_setup()
            real = self.layout
            proxy = _RecordingLayout(real, outcome["writes"], outcome["calls"])
            # Panel.layout 是只读描述符，用 object.__setattr__ 换成本次绘制的代理
            object.__setattr__(self, "layout", proxy)
            try:
                editor.drawBlendPanel(proxy, context)
            except Exception:  # noqa: BLE001
                import traceback as _tb

                outcome["errors"].append(_tb.format_exc())
            finally:
                object.__setattr__(self, "layout", real)

    bpy.utils.register_class(_PanelProbe)
    try:
        layout_probe_draw()
    finally:
        bpy.utils.unregister_class(_PanelProbe)

    assert not outcome["errors"], f"面板绘制抛异常：{outcome['errors'][0]}"
    assert not outcome["writes"], (
        f"绘制期写了 ID 属性，会让面板直接断掉：{outcome['writes']}")
    if panel_drawn:
        assert outcome["calls"], "面板真的画了，却没有任何布局调用被记录"
    else:
        # 后台模式没有可绘制的 UI 区域，画不了；真正的绘制覆盖在 GUI 冒烟测试里
        assert not outcome["calls"]


# 真正触发一次面板 draw：Blender 只在绘制回调里存在 UILayout，
# 后台模式下没有可绘制的区域，这时退化成纯数据校验（不误报成功）。
panel_drawn = False


def layout_probe_draw():
    """让探针面板真的画一帧（不行就跳过，由 GUI 冒烟测试兜底）。"""
    global panel_drawn
    area = next((a for s in bpy.data.screens for a in s.areas
                 if a.type == 'VIEW_3D'), None)
    ui_region = None
    if area is not None:
        area.spaces.active.show_region_ui = True
        ui_region = next((r for r in area.regions if r.type == 'UI'), None)
    window = bpy.context.window
    if area is None or window is None or not getattr(ui_region, "height", 0):
        return
    try:
        with bpy.context.temp_override(
                window=window, screen=bpy.context.screen, area=area,
                region=ui_region, scene=bpy.context.scene,
                view_layer=bpy.context.view_layer):
            result = bpy.ops.wm.call_panel(
                name="HO_PT_blend_matrix_draw_probe", keep_open=False)
        panel_drawn = bool(result)
    except Exception:  # noqa: BLE001 - 后台/无法弹面板时跳过
        panel_drawn = False


bpy.ops.ho.shapekeytools_blend_debug_add()
draw_item = store.active_item(bpy.context.scene)
draw_item.points.clear()
for slot in range(3):
    point = draw_item.points.add()
    point.shape_key = f"D{slot}"
    point.u, point.v = (-1.0, 0.0, 1.0)[slot], 0.0


def _prepare_out_of_range():
    """正是之前崩掉的场景：物体列表下标越界，需要夹取（可重复调用）。"""
    scene = bpy.context.scene
    current = store.active_item(scene)
    current.objects_expanded = True
    current.objects.clear()
    for suffix in ("A", "B"):
        probe = bpy.data.objects.get(f"DrawProbe{suffix}")
        if probe is None:
            probe = bpy.data.objects.new(f"DrawProbe{suffix}", bpy.data.meshes.new(
                f"DrawProbe{suffix}Mesh"))
            bpy.context.scene.collection.objects.link(probe)
        shapekey_utils.append_object(current, probe)
    scene.ho_bs_object_list = 99  # 越界，旧代码会在这里写 ID 属性 → 抛异常
    return current


assert len(_prepare_out_of_range().objects) == 2
assert_panel_draws_without_writing_ids(_prepare_out_of_range)
print("PANEL_DRAW_PROBE", "drawn" if panel_drawn else "skipped-headless", flush=True)


def _prepare_empty_list():
    current = store.active_item(bpy.context.scene)
    current.objects_expanded = True
    current.objects.clear()
    bpy.context.scene.ho_bs_object_list = 7  # 空列表 + 非零下标
    return current


assert_panel_draws_without_writing_ids(_prepare_empty_list)


def _prepare_collapsed():
    current = store.active_item(bpy.context.scene)
    current.objects_expanded = False
    return current


assert_panel_draws_without_writing_ids(_prepare_collapsed)
bpy.ops.ho.shapekeytools_blend_debug_clear()

bpy.ops.preferences.addon_disable(module="HoTools")
print("SHAPEKEY_BLEND_MATRIX_OK", bpy.app.version_string)
