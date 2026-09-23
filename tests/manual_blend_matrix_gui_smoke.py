"""GUI 集成冒烟：真的把混合矩阵绘件画进 3D 视口，并抓绘制回调里的异常。

不能是 ``--background``（后台没有 GPU 上下文与真实事件循环）。手动跑：

    blender --factory-startup --python tests/manual_blend_matrix_gui_smoke.py
    blender --factory-startup --python tests/manual_blend_matrix_gui_smoke.py -- --visual

加 ``-- --visual`` 时不自动退出，方便肉眼看**左下角**的坐标系绘件，并手动试
Ctrl+Space 最大化 / 切换工作区之后还能不能拖动中心点。

绘件本体是模态算子，脚本无法 invoke（``wm_operator_invoke`` 只接受真实事件），
但它有 ``execute`` 路径，所以测试用 ``('EXEC_DEFAULT')`` 启动，然后直接驱动绘制回调、
命中测试与键盘命令算子。
"""

import sys
import traceback
from pathlib import Path

import bpy

ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR.parent) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR.parent))

VISUAL = "--visual" in sys.argv
ERRORS = []
# 侧栏面板绘制统计：用来验证 blend_editor.drawBlendPanel（含 template_list）能真的画出来
PANEL_DRAWS = {"count": 0, "ok": 0, "errors": []}


def _excepthook(exc_type, exc_value, exc_tb):
    ERRORS.append("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _excepthook

print("SMOKE enable", flush=True)
assert bpy.ops.preferences.addon_enable(module="HoTools") == {'FINISHED'}

from HoTools.ShapekeyTools import blend_debug_store as store
from HoTools.ShapekeyTools import blend_editor as editor
from HoTools.ShapekeyTools import blend_overlay as overlay
from HoTools.ShapekeyTools.blend_utils import blend_func as blend_func
from HoTools.ShapekeyTools.blend_utils import point_layout as point_layout

# ── 造一个带 3x3 口型矩阵的网格 ───────────────────────────────────────────
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
mesh = bpy.data.meshes.new("SmokeMesh")
mesh.from_pydata(
    [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1)],
    [], [(0, 1, 2, 3), (0, 4, 5, 1)])
obj = bpy.data.objects.new("SmokeFace", mesh)
bpy.context.scene.collection.objects.link(obj)
obj.shape_key_add(name="Basis", from_mix=False)
for name in ("M_A", "M_I", "M_U", "M_E", "M_O", "M_N", "M_Blink", "M_Smile", "M_Angry"):
    obj.shape_key_add(name=name, from_mix=False)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

assert bpy.ops.ho.shapekeytools_blend_debug_add() == {'FINISHED'}
item = store.active_item(bpy.context.scene)
item.name = "口型 3x3"
item.u_name = "MouthOpen"
item.v_name = "MouthWide"
# 用「添加当前形态键」按顺序把 9 个键点进来，顺便验证自动切键与格子分配
for _ in range(9):
    assert bpy.ops.ho.shapekeytools_blend_point_add_active() == {'FINISHED'}
assert len(item.points) == 9, [p.shape_key for p in item.points]
assert len(store.occupied_coordinates(item)) == 9, "9 个点位应各占一格"
# 重排矩阵：左上起、行优先（先把点打乱）
for point in item.points:
    point.u, point.v = 0.31, -0.27
assert bpy.ops.ho.shapekeytools_blend_point_reorder() == {'FINISHED'}
assert [(point.u, point.v) for point in item.points] == \
    point_layout.matrix_grid(3, 3), "重排后应铺满 3×3 格点"
# 微调：按格点步长挪一格
item.point_index = 4
assert bpy.ops.ho.shapekeytools_blend_point_nudge(du=1, dv=0) == {'FINISHED'}
assert (item.points[4].u, item.points[4].v) == (1.0, 0.0)
assert bpy.ops.ho.shapekeytools_blend_point_nudge(du=-1, dv=0) == {'FINISHED'}
assert (item.points[4].u, item.points[4].v) == (0.0, 0.0)
print("SMOKE points", len(item.points), flush=True)

bpy.context.scene.ho_ShapekeyToolsPanel_Mod = 'PANEL_SHAPEKEYTOOLS_BLENDMATRIX'

area = None
for screen in bpy.data.screens:
    for candidate in screen.areas:
        if candidate.type == 'VIEW_3D':
            candidate.spaces.active.show_region_ui = True
            if area is None:
                area = candidate

if area is None:
    print("SMOKE_NO_VIEW3D", flush=True)
    bpy.ops.wm.quit_blender()
else:
    print("SMOKE view3d", area.width, area.height, flush=True)
    # 绘件本体：走 execute 路径（脚本无法 invoke 模态算子）
    assert bpy.ops.ho.shapekeytools_blend_widget('EXEC_DEFAULT') == {'FINISHED'}
    assert overlay.WIDGET.is_running is True
    assert overlay.WIDGET.handles, "绘制句柄没装上"
    assert overlay.WIDGET.keymaps, "空间级快捷键没绑上"
    assert overlay.WIDGET.timer_running is True
    print("SMOKE keymaps", [(item.idname.split('_')[-1], item.type)
                            for _km, item in overlay.WIDGET.keymaps], flush=True)

    overlay.draw_widget()
    layout = overlay.WIDGET.last_layout
    print("SMOKE shader_ok:", bool(overlay._get_shader()), flush=True)
    print("SMOKE layout:", None if layout is None
          else tuple(round(value, 1) for value in layout["panel"]), flush=True)
    assert layout is not None, "绘制没有产生布局"
    panel_x, panel_y, panel_width, panel_height = layout["panel"]
    assert layout["anchor"] == "BOTTOM_LEFT", layout.get("anchor")
    assert panel_x == overlay._PANEL_MARGIN, f"绘件没有贴左边距：{panel_x}"
    assert panel_y == overlay._PANEL_MARGIN, f"绘件没有贴下边距：{panel_y}"
    assert panel_x + panel_width <= area.width + 1.0, "绘件越过视口右边界"
    assert panel_y + panel_height <= area.height + 1.0, "绘件越过视口上边界"

    # ── 命中测试（这是「点不动」的核心）：中心点与坐标点都要点得到 ──
    handles, centre = overlay._compute_handles(item, layout)
    hit = overlay.pick_in_area(bpy.context, centre[0], centre[1], area)
    print("SMOKE pick centre:", hit, flush=True)
    assert hit == ("centre", -1), f"中心点点不中：{hit}"
    # 挑一个不和中心点重合的方块（9 点矩阵里必然有），命中判定优先中心点，
    # 所以贴着中心点的那个方块本来就会让位给中心点，这是预期行为。
    target = next(
        entry for entry in handles
        if (entry[2] - centre[0]) ** 2 + (entry[3] - centre[1]) ** 2 > 400.0)
    _kind, point_index, point_x, point_y = target
    hit_point = overlay.pick_in_area(bpy.context, point_x, point_y, area)
    print("SMOKE pick point:", hit_point, flush=True)
    assert hit_point == ("point", point_index), f"坐标点点不中：{hit_point}"
    # 空白处不命中（要能放行给 Blender 做选择/框选）
    assert overlay.pick_in_area(bpy.context, 1.0, 1.0, area) == (None, -1)
    # 命令算子：R / W / [ / ]
    item.cursor_u, item.cursor_v = 0.5, 0.5
    assert bpy.ops.ho.shapekeytools_blend_widget_key(command='RESET') == {'FINISHED'}
    assert (item.cursor_u, item.cursor_v) == (0.0, 0.0)
    assert bpy.ops.ho.shapekeytools_blend_widget_key(command='SCALE_UP') == {'FINISHED'}
    assert overlay.WIDGET.scale > 1.0
    assert bpy.ops.ho.shapekeytools_blend_widget_key(command='SCALE_DOWN') == {'FINISHED'}
    assert bpy.ops.ho.shapekeytools_blend_widget_key(command='CLEAR') == {'FINISHED'}

    # ── 视口尺寸变化后（等价于 Ctrl+Space 最大化）仍然要能点中 ──
    # Area 的宽高是只读的，用一个同类型代理来模拟“视口被改了尺寸”。
    class _ResizedArea:
        type = area.type

        def __init__(self, size):
            self.width, self.height = size

        @property
        def regions(self):
            return area.regions

        def tag_redraw(self):
            return area.tag_redraw()

    resized = _ResizedArea((int(area.width * 0.62), int(area.height * 0.7)))
    stale = overlay.WIDGET.last_layout
    changed = overlay.WIDGET.refresh(bpy.context, area=resized)
    print("SMOKE resized ->", resized.width, resized.height,
          "changed:", changed, flush=True)
    assert changed, "视口尺寸变了，刷新必须报告变化"
    assert (overlay.WIDGET.last_layout is not stale
            and overlay.WIDGET.last_layout is None), "旧尺寸的布局必须被丢掉"
    # 按新尺寸取布局（命中测试内部走的就是这条路径）
    weights, _names = blend_func.evaluate_item(item)
    fresh = overlay.WIDGET._layout_for_size(
        bpy.context, item, resized.width, resized.height, weights)
    fx, fy, fw, fh = fresh["panel"]
    assert (fx, fy) == (overlay._PANEL_MARGIN, overlay._PANEL_MARGIN), fresh["panel"]
    assert fx + fw <= resized.width + 1.0, fresh["panel"]
    assert fy + fh <= resized.height + 1.0, fresh["panel"]
    _handles, centre2 = overlay._compute_handles(item, fresh)
    after = overlay.pick_in_area(bpy.context, centre2[0], centre2[1], resized)
    print("SMOKE pick after resize:", after, flush=True)
    assert after == ("centre", -1), f"视口变化后中心点点不中了：{after}"
    overlay.WIDGET.refresh(bpy.context, area=area)
    overlay.draw_widget()

    item.cursor_u, item.cursor_v = 0.6, 0.6
    editor.invalidate_weight_cache()
    blend_func.apply_weights(bpy.context, item)

    # ── 侧栏面板也要真的画一次（覆盖 template_list，例如物体列表的 UIList）──
    # 脚本切不了侧栏分类，所以注册一个临时面板到 HoTools 分类下，
    # 用 wm.call_panel 弹一次（它会一直重绘到被关掉，所以放在最后做）。
    class _PanelProbe(bpy.types.Panel):
        bl_idname = "SMOKE_PT_blend_panel_probe"
        bl_label = "混合矩阵冒烟面板"
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'UI'
        bl_category = "HoTools"
        bl_options = set()

        def draw(self, context):
            PANEL_DRAWS["count"] += 1
            try:
                editor.drawBlendPanel(self.layout, context)
                PANEL_DRAWS["ok"] += 1
            except Exception:  # noqa: BLE001
                PANEL_DRAWS["errors"].append(traceback.format_exc())

    bpy.utils.register_class(_PanelProbe)
    area.spaces.active.show_region_ui = True
    ui_region = next((r for r in area.regions if r.type == 'UI'), None)
    try:
        with bpy.context.temp_override(
                window=bpy.context.window, screen=bpy.context.screen,
                area=area, region=ui_region,
                scene=bpy.context.scene, view_layer=bpy.context.view_layer):
            bpy.ops.wm.call_panel(name=_PanelProbe.bl_idname, keep_open=False)
        print("SMOKE panel probe invoked", flush=True)
    except Exception as exc:  # noqa: BLE001 - 面板探针只是补充覆盖，失败不算错
        print(f"SMOKE panel probe skipped: {type(exc).__name__}: {exc}", flush=True)


def _tick():
    for screen in bpy.data.screens:
        for candidate in screen.areas:
            candidate.tag_redraw()
    overlay.draw_widget()
    if VISUAL:
        if ERRORS or PANEL_DRAWS["errors"]:
            print("SMOKE errors", len(ERRORS) + len(PANEL_DRAWS["errors"]), flush=True)
            for text in (ERRORS + PANEL_DRAWS["errors"])[:3]:
                print(text, flush=True)
        return 0.5
    print("SMOKE weights:", {
        key.name: round(key.value, 3) for key in obj.data.shape_keys.key_blocks
        if key.value > 1e-6 or key.mute
    }, flush=True)
    print("SMOKE panel_draws:", PANEL_DRAWS["count"], "ok:", PANEL_DRAWS["ok"],
          flush=True)
    for text in PANEL_DRAWS["errors"][:2]:
        print(text, flush=True)
    errors = ERRORS + PANEL_DRAWS["errors"]
    print("SMOKE errors", len(errors), flush=True)
    overlay.WIDGET.cancel("冒烟收尾")
    assert overlay.WIDGET.is_running is False, "收尾后必须停止"
    assert not overlay.WIDGET.keymaps and not overlay.WIDGET.handles
    if PANEL_DRAWS["count"]:
        assert PANEL_DRAWS["ok"] > 0, "面板探针跑了但一次都没画成"
    print("SMOKE_DONE", "FAIL" if errors else "OK", flush=True)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_tick, first_interval=0.5 if VISUAL else 0.1)
