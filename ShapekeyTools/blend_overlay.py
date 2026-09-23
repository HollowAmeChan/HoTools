"""形态键混合矩阵的视口控制绘件。

绘件在 3D 视口左下角绘制一个坐标系（无标题栏，尽量简洁）：

- 横纵两条轴以及轴名（调试项里的参数名）；
- 混合矩阵的全部坐标点位（按权重着色，禁用点位打叉）；
- 可以用鼠标拖动的中心点（当前输入坐标）。

交互对齐 Unity 混合树的 Preview：拖动中心点就是在改输入坐标，坐标点本身也能拖动
改位置；权重按 ``blend_utils.blend_space_math`` 求解后写进操作物体的形态键。

底层的 GPU 图元/文字在 ``blend_utils.draw_func``，权重与形态键读写工具在
``blend_utils.blend_func``，这里只保留绘件状态、布局与交互。
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

try:
    from . import blend_debug_store as _store
    from .blend_utils import blend_func as _func
    from .blend_utils import blend_space_math as _math
    from .blend_utils import draw_func as _draw
    from .blend_utils import shapekey_utils as _keys
except ImportError:  # 兼容旧工具直接导入脚本
    import blend_debug_store as _store
    from blend_utils import blend_func as _func
    from blend_utils import blend_space_math as _math
    from blend_utils import draw_func as _draw
    from blend_utils import shapekey_utils as _keys


# region 绘制常量

_PANEL_MARGIN = 16.0
_PLOT_PADDING = 24.0
_FOOTER_HEIGHT = 40.0
_MIN_PLOT_SIZE = 140.0
_MAX_PLOT_SIZE = 940.0
# 初始坐标系是“翻倍”尺寸：基准边长 472（原来是 236）。
_BASE_PLOT_SIZE = 472.0

# 权重 → 半径（像素）：权重 0 是小圆点，权重 1 是最大半径（对齐 Unity 混合树的画法）。
# 尺寸按屏幕像素走，不随坐标系缩放变化；格点很密时圆会有重叠，属预期。
_HANDLE_RADIUS = 36.0
_MIN_HANDLE_RADIUS = 3.0
# 空心圆的线宽：填充半径 = 半径 − 这个值，所以圆越大越"空"（半权重仍然是空的）
_MIN_FILL_MARGIN = 8.0
_CENTER_RADIUS = 8.0
# 圆点画大了，命中半径也跟着放大（Unity 里点的 hit 区域也是跟着尺寸走的）
_PICK_RADIUS = 20.0
_GRID_STEPS = (0.25, 0.5, 0.75)

_FONT_SIZE = _draw.FONT_SIZE
_FONT_SIZE_SMALL = _draw.FONT_SIZE_SMALL

_COLOR_BACKDROP = _draw.COLOR_BACKDROP
_COLOR_BORDER = _draw.COLOR_BORDER
_COLOR_GRID = _draw.COLOR_GRID
_COLOR_AXIS = _draw.COLOR_AXIS
_COLOR_TEXT = _draw.COLOR_TEXT
_COLOR_TEXT_DIM = _draw.COLOR_TEXT_DIM
_COLOR_CENTER = _draw.COLOR_CENTER
_COLOR_HOVER = _draw.COLOR_HOVER
_COLOR_POINT = _draw.COLOR_POINT


def _point_radius(weight) -> float:
    """权重 → 点位半径：权重越高圆越大（Unity 混合树就是这么画的）。"""
    ratio = max(0.0, min(1.0, float(weight)))
    return _MIN_HANDLE_RADIUS + (_HANDLE_RADIUS - _MIN_HANDLE_RADIUS) * ratio


def _point_fill_radius(weight) -> float:
    """权重 → 实心填充半径；``<= 0`` 表示这一点画成空心圆。

    - 权重 0：非常小的实心点（Unity 里未生效的 motion 就是这个观感）；
    - 中间权重：细空心圆，**圆越大越空**，让"生效程度"一眼看出来；
    - 权重接近 1：填实。
    """
    radius = _point_radius(weight)
    if weight <= 1e-6:
        return max(1.0, radius * 0.55)
    fill = radius - _MIN_FILL_MARGIN
    return fill if fill >= 1.0 else 0.0


def _get_shader():
    """当前 2D 着色器（GPU 不可用时为 ``None``）；冒烟测试与诊断用。"""
    return _draw.get_shader()


# endregion


# region 绘件运行时


def _region_of(area):
    """取区域里真正画 2D 的那块 WINDOW 子区域。"""
    return next((item for item in area.regions if item.type == 'WINDOW'), None)


def windows_and_areas():
    """遍历所有窗口与它们当前屏幕上的区域，产出 ``(window, screen, area)``。"""
    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return
    try:
        windows = list(window_manager.windows)
    except (AttributeError, ReferenceError):
        return
    for window in windows:
        try:
            screen = window.screen
            areas = list(screen.areas) if screen is not None else []
        except (AttributeError, ReferenceError, RuntimeError):
            continue
        for area in areas:
            yield window, screen, area


def redraw_all_areas():
    """把整个窗口管理的 3D 视口都标脏，保证切换工作区/最大化后位置立刻刷新。"""
    count = 0
    for _window, _screen, area in windows_and_areas():
        try:
            if area.type != 'VIEW_3D':
                continue
            area.tag_redraw()
            count += 1
        except (AttributeError, ReferenceError, RuntimeError):
            continue
    return count


class _WidgetState:
    """视口绘件的运行时状态（只有当前会话有效，不进 .blend）。

    ``area`` 只是「最近一次真正画过的视口」的缓存，不能当成长期有效的东西：Ctrl+Space
    最大化、切换工作区、拖动区域分隔条都会让区域尺寸/身份变化，所以每次绘制与每个
    事件都会用 :func:`resolve_area` 重新解析，见 ``_layout_for_size``。
    """

    def __init__(self):
        self.handles: list = []
        self.is_running = False
        self.scale = 1.0
        self.window = None
        self.area = None
        self.mouse = None
        self.mouse_inside = False
        self.hover_kind = None
        self.hover_index = -1
        self.drag_kind = None
        self.drag_index = -1
        self.last_error = ""
        self.last_layout = None
        # 上次绘制用的区域尺寸：事件里的区域坐标是按当前视口算的，尺寸对不上就重算布局
        self.layout_size = None
        self.timer_running = False
        self.status = ""
        # 生成它的那次 invoke 绑定的快捷键（空间级 keymap），收尾时要摘掉
        self.keymaps = []

    # -- 状态查询 --------------------------------------------------------
    def describe(self, context) -> str:
        item = _store.active_item(context.scene) if context is not None else None
        if item is None:
            return "无调试矩阵：请先在左侧新建"
        return (
            f"{item.name or '未命名'}｜{item.u_name}/{item.v_name}｜"
            f"点位 {len(item.points)}｜"
            f"({item.cursor_u:.3f}, {item.cursor_v:.3f})"
        )

    def set_hover(self, kind, index=-1) -> None:
        if (self.hover_kind, self.hover_index) != (kind, index):
            self.hover_kind = kind
            self.hover_index = index
            self.tag_redraw()

    def area_size(self):
        """返回缓存区域当前的 ``(宽, 高)``；区域已失效时返回 ``None``。"""
        area = self.area
        if area is None:
            return None
        try:
            return float(area.width), float(area.height)
        except (AttributeError, ReferenceError, RuntimeError):
            self.area = None
            return None

    def tag_redraw(self) -> None:
        """让缓存区域重绘；区域失效时顺手清掉缓存，交给下一帧重新解析。"""
        area = self.area
        if area is None:
            return
        try:
            area.tag_redraw()
        except (AttributeError, ReferenceError, RuntimeError):
            self.area = None

    def refresh(self, context=None, area=None) -> bool:
        """重新解析目标视口并刷新整窗位置；返回是否发生了变化。

        区域尺寸变了（Ctrl+Space 最大化、切换工作区、拖分隔条）就丢掉缓存的布局，
        这样下一次命中测试会按新尺寸重算，而不是拿旧矩形去比新的鼠标坐标。
        ``area`` 可以显式指定（测试用代理区域模拟改尺寸）。
        """
        if area is None:
            area, _region = resolve_area(context)
        if area is None:
            return False
        previous = self.area_size()
        self.area = area
        self.window = getattr(context, "window", None) or self.window
        current = self.area_size()
        if previous != current:
            self.layout_size = None
            self.last_layout = None
            return True
        return False

    def _layout_for_size(self, context, item, region_width, region_height, weights):
        """按区域尺寸取（必要时重算）布局，绘制与命中测试共用同一份。"""
        size = (float(region_width), float(region_height))
        layout = self.last_layout
        if layout is None or self.layout_size != size:
            layout = compute_layout(region_width, region_height, item, len(weights))
            self.last_layout = layout
            self.layout_size = size
        return layout

    # -- 生命周期 --------------------------------------------------------
    def start(self, context, area=None) -> bool:
        if self.is_running:
            return True
        self.window = getattr(context, "window", None)
        area, _region = resolve_area(context, preferred=area)
        self.area = area
        self.layout_size = None
        self.last_layout = None
        self.is_running = True
        self.tag_redraw()
        return True

    # 绘件句柄由生成它的模态算子持有：``stop()`` 只翻状态，模态算子在下一个事件里
    # 看到状态就自己收尾（见 ``OP_ShapekeyTools_BlendWidget.modal``）。
    def stop(self) -> None:
        self.is_running = False
        self.hover_kind = None
        self.hover_index = -1
        self.drag_kind = None
        self.drag_index = -1
        self.mouse = None
        self.last_layout = None
        self.layout_size = None
        self.tag_redraw()

    def remove_handlers(self) -> None:
        """直接摘掉全部绘制句柄（卸载插件 / 模态算子收尾时用）。"""
        for handler in list(self.handles):
            try:
                bpy.types.SpaceView3D.draw_handler_remove(handler, 'WINDOW')
            except (ValueError, RuntimeError):
                pass
        self.handles.clear()

    def remove_keymaps(self) -> None:
        """摘掉生成时绑定的空间级快捷键。"""
        for keymap, item in list(self.keymaps):
            try:
                keymap.keymap_items.remove(item)
            except (AttributeError, ReferenceError, RuntimeError, ValueError):
                pass
        self.keymaps.clear()

    def cancel(self, reason="") -> None:
        """彻底收尾：快捷键、绘制句柄、定时器、状态一次清干净。

        任何“绘件已经不可用”的路径（模态被窗口丢掉、关闭按钮、插件卸载）都走这里，
        避免留下一个画着却点不动的幽灵控件。
        """
        self.status = reason
        stop_widget_timer()
        self.remove_keymaps()
        self.remove_handlers()
        set_drag_active(False)
        invalidate_axis_range()
        self.stop()
        redraw_all_areas()


WIDGET = _WidgetState()


def resolve_area(context=None, preferred=None):
    """解析绘件当前应该挂在哪个 3D 视口，返回 ``(area, region)``。

    解析顺序：调用方指定 → 事件/绘制所在区域 → 缓存区域 → 任一活着的 3D 视口。
    **每次绘制与每个事件都会重新解析**：Ctrl+Space 最大化、切换工作区、拖动分隔条都会
    换掉区域身份或尺寸；继续用缓存旧区域，就会照着旧矩形画、却拿新视口的鼠标坐标去
    命中，表现就是“点不动”。解析不出来时返回 ``(None, None)``，此时保留旧缓存。
    """
    candidates = []
    if preferred is not None:
        candidates.append(preferred)
    context_area = getattr(context, "area", None) if context is not None else None
    if context_area is not None:
        candidates.append(context_area)
    candidates.append(WIDGET.area)

    for area in candidates:
        if area is None:
            continue
        try:
            if area.type == 'VIEW_3D':
                return area, _region_of(area)
        except (AttributeError, ReferenceError, RuntimeError):
            continue

    fallback = None
    for _window, _screen, area in windows_and_areas():
        try:
            if area.type != 'VIEW_3D':
                continue
        except (AttributeError, ReferenceError, RuntimeError):
            continue
        region = _region_of(area)
        if region is not None:
            return area, region
        fallback = fallback or area
    if fallback is not None:
        return fallback, _region_of(fallback)
    return None, None


# 绘件在跑的时候用定时器做两件事：
# 1) 校对目标视口（最大化 / 切工作区会换掉区域身份或尺寸，要重新解析 + 刷新整窗位置）；
# 2) 看住模态交互算子有没有被窗口丢掉，丢了就自动收尾，避免“绘件还在、却点不动”。
_WIDGET_TIMER_INTERVAL = 0.2


def _widget_timer():
    if not WIDGET.is_running:
        WIDGET.timer_running = False
        return None
    if WIDGET.refresh(bpy.context):
        redraw_all_areas()
    return _WIDGET_TIMER_INTERVAL


def ensure_widget_timer() -> None:
    """确保校对定时器在跑（重复调用安全）。"""
    if WIDGET.timer_running:
        return
    try:
        if bpy.app.timers.is_registered(_widget_timer):
            WIDGET.timer_running = True
            return
        bpy.app.timers.register(_widget_timer, first_interval=_WIDGET_TIMER_INTERVAL)
        WIDGET.timer_running = True
    except (AttributeError, ValueError, RuntimeError):
        WIDGET.timer_running = False


def stop_widget_timer() -> None:
    """停掉校对定时器。"""
    WIDGET.timer_running = False
    try:
        if bpy.app.timers.is_registered(_widget_timer):
            bpy.app.timers.unregister(_widget_timer)
    except (AttributeError, ValueError, RuntimeError):
        pass


# endregion


# region 布局


def _text_width(text, size=_FONT_SIZE) -> float:
    return _draw.text_width(text, size)


def _plot_size() -> float:
    return max(_MIN_PLOT_SIZE,
               min(_MAX_PLOT_SIZE, _BASE_PLOT_SIZE * WIDGET.scale))


def compute_layout(region_width, region_height, item, point_count=0):
    """计算绘件的全部矩形与手柄位置（区域左下角为原点）。

    绘件固定贴在视口**左下角**（右下角容易被右侧的 N 面板/其他浮层挡住）。
    先按 ``WIDGET.scale`` 取基准尺寸，再按区域尺寸等比缩小，保证小视口里也不会
    越界（缩放只作用于坐标系本体，底部读数保持可读高度）。``point_count`` 只用于
    未来的自适应留白，当前不参与布局。
    """
    region_width = float(region_width or 0.0)
    region_height = float(region_height or 0.0)
    margin = _PANEL_MARGIN
    if region_width and region_height:
        available_width = max(60.0, region_width - margin * 2.0)
        available_height = max(60.0, region_height - margin * 2.0)
        max_plot_width = available_width - _PLOT_PADDING * 2.0
        max_plot_height = (
            available_height - _PLOT_PADDING * 2.0 - _FOOTER_HEIGHT)
        fit = min(max_plot_width, max_plot_height) / max(_plot_size(), 1.0)
    else:
        fit = 1.0

    plot = max(48.0, _plot_size() * min(1.0, fit))
    width = plot + _PLOT_PADDING * 2.0
    height = plot + _PLOT_PADDING * 2.0 + _FOOTER_HEIGHT
    # 左下角：左边距 + 下边距，面板再往里缩一个 ``_PLOT_PADDING`` 才是坐标系。
    panel_x = margin
    panel_y = margin
    plot_rect = (
        panel_x + _PLOT_PADDING,
        panel_y + _FOOTER_HEIGHT + _PLOT_PADDING,
        plot,
        plot,
    )
    return {
        "panel": (panel_x, panel_y, width, height),
        "plot": plot_rect,
        "anchor": "BOTTOM_LEFT",
        "footer_y": panel_y,
        "plot_size": plot,
        "axis_range": axis_range_for(item),
    }


# 坐标系范围按「点位坐标」缓存，而不是按数量：
# 只按键位数量缓存时，「重排为矩阵」这类**只改坐标不改数量**的操作会让范围保持旧值，
# 新坐标落到旧范围之外，uv_to_pixel 就把点映射到坐标系矩形外面（看起来像“飞出去”）。
# 键里带上坐标后：坐标变了就重新适配；拖动中心点（只改输入不改坐标）范围仍然稳定。
_AXIS_RANGE = {"key": None, "range": None}


def invalidate_axis_range() -> None:
    """外部改了点位坐标后清一次缓存（下次绘制重新适配）。"""
    _AXIS_RANGE["key"] = None
    if not _DRAG_ACTIVE["value"]:
        _AXIS_RANGE["range"] = None


# 拖动期间锁定坐标系范围：否则每帧按当前点位重新适配，映射会一直变，
# 表现为“点位追不上鼠标”。松手时清掉，下一次绘制再适配一次。
_DRAG_ACTIVE = {"value": False}


def set_drag_active(active: bool) -> None:
    """标记是否正在拖动（拖动中锁定范围，松手后重新适配）。"""
    was_active = _DRAG_ACTIVE["value"]
    _DRAG_ACTIVE["value"] = bool(active)
    if was_active and not active:
        invalidate_axis_range()


def axis_range_for(item):
    """取当前应该用的坐标系范围（拖动中锁定，其余时候按点位坐标适配）。"""
    if _DRAG_ACTIVE["value"] and _AXIS_RANGE["range"] is not None:
        return _AXIS_RANGE["range"]
    return _cached_axis_range(item)


def _cached_axis_range(item):
    if item is None:
        return (-1.0, 1.0, -1.0, 1.0)
    key = (item.as_pointer(), tuple(
        (round(point.u, 4), round(point.v, 4)) for point in item.points))
    if _AXIS_RANGE["key"] != key or _AXIS_RANGE["range"] is None:
        _AXIS_RANGE["key"] = key
        _AXIS_RANGE["range"] = _math.plot_axis_range(
            [(point.u, point.v) for point in item.points])
    return _AXIS_RANGE["range"]


def _plot_to_uv(px, py, layout):
    return _draw.plot_to_uv(px, py, layout["plot"], layout["axis_range"])


def _uv_to_plot(u, v, layout):
    """混合坐标 → 像素坐标；坐标本身越界时也夹在坐标系内，避免点位飞到面板外。"""
    x, y = _draw.uv_to_plot(u, v, layout["plot"], layout["axis_range"])
    return _clamp_to_plot(x, y, layout)


def _clamp_to_plot(px, py, layout):
    return _draw.clamp_to_rect(px, py, layout["plot"])


def _compute_handles(item, layout):
    """返回 ``(handles, centre)``；手柄为 ``(kind, index, x, y)``。"""
    handles = []
    for index, point in enumerate(item.points):
        x, y = _uv_to_plot(point.u, point.v, layout)
        handles.append(("point", index, x, y))
    if item is not None:
        centre = _uv_to_plot(item.cursor_u, item.cursor_v, layout)
    else:
        plot_x, plot_y, plot_width, plot_height = layout["plot"]
        centre = (plot_x + plot_width * 0.5, plot_y + plot_height * 0.5)
    return handles, centre


# endregion


# region 绘制


def draw_widget() -> None:
    """POST_PIXEL 绘制回调：整个坐标系绘件。"""
    try:
        _draw_widget_impl()
    except Exception as exc:  # noqa: BLE001 - 绘制回调里抛异常会打断视口
        _draw.reset_shader()
        if WIDGET.last_error != repr(exc):
            WIDGET.last_error = repr(exc)
            print(f"[HoTools] 混合矩阵绘件绘制失败：{type(exc).__name__}: {exc}")


def _draw_widget_impl() -> None:
    if not WIDGET.is_running:
        return
    # 每次绘制都重新解析视口：最大化 / 切工作区之后会被画到新的那块区域上。
    # 解析不出来（脚本/后台调用）就退回缓存区域，至少还能按已知尺寸画一帧。
    area, _region = resolve_area(bpy.context)
    if area is None:
        area = WIDGET.area
    if area is None:
        return
    WIDGET.area = area
    try:
        region_width = float(area.width or 0.0)
        region_height = float(area.height or 0.0)
    except (AttributeError, ReferenceError, RuntimeError):
        return
    context = bpy.context
    item = _store.active_item(context.scene) if context.scene else None
    if item is None:
        _draw_placeholder(region_width, region_height)
        return

    weights, _names = _func.evaluate_item(item)
    layout = WIDGET._layout_for_size(
        context, item, region_width, region_height, weights)
    handles, centre = _compute_handles(item, layout)

    _draw_backdrop(layout)
    _draw_grid(layout)
    _draw_axes(layout, item)
    _draw_points(item, weights, handles, layout)
    _draw_centre(centre, item)
    _draw_footer(layout, item, weights)


def _draw_backdrop(layout) -> None:
    x, y, width, height = layout["panel"]
    _draw.draw_rect(x, y, width, height, _COLOR_BACKDROP)
    _draw.draw_frame(x, y, width, height, _COLOR_BORDER, 1.0)


def _draw_grid(layout) -> None:
    plot_x, plot_y, plot_width, plot_height = layout["plot"]
    u_min, u_max, v_min, v_max = layout["axis_range"]
    for step in _GRID_STEPS:
        for value in (step, -step):
            if not u_min < value < u_max:
                continue
            x, _ = _uv_to_plot(value, 0.0, layout)
            _draw.draw_line_strip(
                ((x, plot_y), (x, plot_y + plot_height)), _COLOR_GRID, 1.0)
        for value in (step, -step):
            if not v_min < value < v_max:
                continue
            _, y = _uv_to_plot(0.0, value, layout)
            _draw.draw_line_strip(
                ((plot_x, y), (plot_x + plot_width, y)), _COLOR_GRID, 1.0)


def _draw_axes(layout, item) -> None:
    plot_x, plot_y, plot_width, plot_height = layout["plot"]
    origin_x, origin_y = _uv_to_plot(0.0, 0.0, layout)
    _draw.draw_line_strip(
        ((origin_x, plot_y), (origin_x, plot_y + plot_height)), _COLOR_AXIS, 1.4)
    _draw.draw_line_strip(
        ((plot_x, origin_y), (plot_x + plot_width, origin_y)), _COLOR_AXIS, 1.4)

    _draw.draw_text(item.u_name, plot_x + plot_width - _text_width(item.u_name) - 2.0,
                    origin_y + 3.0, _COLOR_TEXT)
    _draw.draw_text(item.v_name, origin_x + 4.0,
                    plot_y + plot_height - _FONT_SIZE - 2.0, _COLOR_TEXT)


def _draw_points(item, weights, handles, layout) -> None:
    """矩阵点位：**半径随权重变化**（对齐 Unity 混合树的画法），不用颜色编码。

    - 权重 0 → 很小的实心点（未生效的 motion）；权重 1 → 最大实心圆；
    - 中间权重是空心圆，圆越大越空；
    - 当前活动点位套一圈高亮环，鼠标悬停再套一圈更亮的；
    - 权重 > 0 时在圆旁标 `序号:权重`。
    """
    hovered = WIDGET.hover_kind == "point"
    for index, point in enumerate(item.points):
        _kind, _index, x, y = handles[index]
        weight = weights[index] if index < len(weights) else 0.0
        radius = _point_radius(weight)
        if hovered and WIDGET.hover_index == index:
            _draw.draw_ring(x, y, radius + 3.0, _COLOR_HOVER, 1.4)
        if item.point_index == index:
            _draw.draw_ring(x, y, radius + 4.0, _COLOR_CENTER, 1.2)
        _draw.draw_ring(x, y, radius, _COLOR_POINT, 1.6)
        fill = _point_fill_radius(weight)
        if fill > 0.0:
            _draw.draw_filled_circle(x, y, fill, _COLOR_POINT)
        if weight > 1e-6 or (hovered and WIDGET.hover_index == index):
            _draw.draw_text(f"{index + 1}:{weight:.2f}",
                            x + radius + 3.0, y + 3.0, _COLOR_TEXT)
        else:
            _draw.draw_text(str(index + 1), x + radius + 3.0, y + 3.0,
                            _COLOR_TEXT_DIM)


def _draw_centre(centre, item) -> None:
    cx, cy = centre
    reach = _CENTER_RADIUS + 4.0
    _draw.draw_line_strip(((cx - reach, cy), (cx + reach, cy)), _COLOR_CENTER, 1.4)
    _draw.draw_line_strip(((cx, cy - reach), (cx, cy + reach)), _COLOR_CENTER, 1.4)
    _draw.draw_ring(cx, cy, _CENTER_RADIUS, _COLOR_CENTER, 1.8)
    _draw.draw_text(
        f"{item.u_name} {item.cursor_u:.3f}   {item.v_name} {item.cursor_v:.3f}",
        cx + _CENTER_RADIUS + 6.0, cy - _CENTER_RADIUS - 12.0,
        _COLOR_CENTER, _FONT_SIZE)


def _draw_footer(layout, item, weights) -> None:
    """底部一行读数：模式 + 生效/总数 + 物体数 + 操作提示。"""
    panel_x, panel_y, _width, _height = layout["panel"]
    text_x = panel_x + 8.0
    mode_label = next(
        (label for identifier, label, _description in _math.BLEND_MODE_ITEMS
         if identifier == item.mix_mode),
        item.mix_mode,
    )
    active = sum(1 for weight in weights if weight > 1e-6)
    objects = _keys.active_objects(item)
    _draw.draw_text(
        f"{item.name or '未命名'}｜{mode_label}｜生效 {active}/{len(weights)}"
        f"｜物体 {len(objects)}",
        text_x, panel_y + _FOOTER_HEIGHT - 16.0, _COLOR_TEXT_DIM, _FONT_SIZE_SMALL,
    )
    _draw.draw_text(
        "拖动中心点改输入　拖动圆点改坐标　R 回原点　W 归零　[ ] 缩放　ESC 关闭",
        text_x, panel_y + _FOOTER_HEIGHT - 29.0, _COLOR_TEXT_DIM, _FONT_SIZE_SMALL,
    )


def _draw_placeholder(region_width, region_height) -> None:
    """还没有调试矩阵时的简易提示条（同样贴左下角）。"""
    width, height = 260.0, 40.0
    x = _PANEL_MARGIN
    y = _PANEL_MARGIN
    _draw.draw_rect(x, y, width, height, _COLOR_BACKDROP)
    _draw.draw_frame(x, y, width, height, _COLOR_BORDER, 1.0)
    _draw.draw_text("混合矩阵：先在左侧新建一个调试矩阵", x + 8.0, y + 22.0,
                    _COLOR_TEXT)
    _draw.draw_text("ESC 关闭绘件", x + 8.0, y + 8.0, _COLOR_TEXT_DIM,
                    _FONT_SIZE_SMALL)


# endregion


# region 命中测试与输入处理（绘制/交互共用）


def pick_in_area(context, region_x, region_y, area=None):
    """在指定视口里做命中测试，返回 ``(kind, index)``。

    ``region_x/region_y`` 必须是**该视口**的区域坐标（左上角为原点），布局也按该视口
    的实际尺寸取 —— 这正是切换工作区/最大化之后“点不动”的根因：布局与鼠标坐标必须
    来自同一块区域、同一时刻的尺寸。
    """
    item = _store.active_item(context.scene)
    area = area or getattr(context, "area", None)
    if area is None or getattr(area, "type", None) != 'VIEW_3D':
        area = WIDGET.area or resolve_area(context)[0]
    if item is None or area is None:
        return None, -1
    try:
        region_width = float(area.width or 0.0)
        region_height = float(area.height or 0.0)
    except (AttributeError, ReferenceError, RuntimeError):
        return None, -1
    if not region_width or not region_height:
        return None, -1
    weights, _names = _func.evaluate_item(item)
    layout = WIDGET._layout_for_size(
        context, item, region_width, region_height, weights)
    handles, centre = _compute_handles(item, layout)
    if (region_x - centre[0]) ** 2 + (region_y - centre[1]) ** 2 <= _PICK_RADIUS ** 2:
        return "centre", -1
    best = None
    best_distance = _PICK_RADIUS ** 2
    for kind, index, x, y in handles:
        distance = (region_x - x) ** 2 + (region_y - y) ** 2
        if distance <= best_distance:
            best_distance = distance
            best = (kind, index)
    return (best if best is not None else (None, -1))


def pointer_to_uv(region_x, region_y, layout):
    """区域坐标 → 混合坐标（夹在坐标系矩形内）。"""
    px, py = _clamp_to_plot(region_x, region_y, layout)
    return _plot_to_uv(px, py, layout)


def set_cursor(context, region_x, region_y, layout):
    item = _store.active_item(context.scene)
    if item is None or layout is None:
        return False
    u, v = pointer_to_uv(region_x, region_y, layout)
    item.cursor_u = round(u, 4)
    item.cursor_v = round(v, 4)
    if context.scene.ho_bs_apply_on_cursor:
        _func.apply_weights(context, item)
    return True


def set_point(context, index, region_x, region_y, layout):
    item = _store.active_item(context.scene)
    if item is None or layout is None or not 0 <= index < len(item.points):
        return False
    u, v = pointer_to_uv(region_x, region_y, layout)
    point = item.points[index]
    point.u = round(u, 4)
    point.v = round(v, 4)
    if context.scene.ho_bs_apply_on_cursor:
        _func.apply_weights(context, item)
    return True


def reset_cursor(context):
    item = _store.active_item(context.scene)
    if item is None:
        return False
    item.cursor_u = 0.0
    item.cursor_v = 0.0
    if context.scene.ho_bs_apply_on_cursor:
        _func.apply_weights(context, item)
    WIDGET.layout_size = None
    WIDGET.tag_redraw()
    redraw_all_areas()
    return True


def clear_all_keys(context):
    """全键归零（键盘 W / 面板按钮共用）。"""
    item = _store.active_item(context.scene)
    if item is None:
        return False
    _func.clear_all_keys(item, context)
    WIDGET.tag_redraw()
    return True


def scale_widget(context, step):
    WIDGET.scale = max(0.5, min(2.0, WIDGET.scale + step))
    WIDGET.layout_size = None
    WIDGET.tag_redraw()
    redraw_all_areas()
    return True


# endregion


# region 快捷键


_ADDON_KEYMAP = {"keymap": None}


def _addon_keymap():
    """拿到（必要时创建）addon keyconfig 里的 ``3D View`` 空间快捷键表。

    绑在**空间**上而不是模态算子上：切换工作区、Ctrl+Space 最大化都不会丢，
    这样点击永远有事件进来（模态算子会被窗口丢弃，那正是之前“点不动”的根因）。
    """
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return None
    keymap = _ADDON_KEYMAP["keymap"]
    if keymap is None:
        keymap = keyconfig.keymaps.get("3D View")
        if keymap is None:
            keymap = keyconfig.keymaps.new(name="3D View", space_type='VIEW_3D')
        _ADDON_KEYMAP["keymap"] = keymap
    return keymap


def _bind(keymap, operator_id, key, **properties):
    """取或建一个绑定项；重复调用不会叠加。"""
    for item in keymap.keymap_items:
        if item.idname == operator_id and item.type == key:
            return item
    item = keymap.keymap_items.new(operator_id, key, 'PRESS')
    for name, value in properties.items():
        try:
            setattr(item, name, value)
        except (AttributeError, TypeError):
            pass
    return item


def bind_widget_keys() -> list:
    """绑定绘件的全部快捷键，返回 ``[(keymap, item), ...]`` 供收尾时摘除。"""
    keymap = _addon_keymap()
    if keymap is None:
        return []
    bindings = [
        (keymap, _bind(keymap, OP_ShapekeyTools_BlendWidgetPick.bl_idname,
                       'LEFTMOUSE')),
        (keymap, _bind(keymap, OP_ShapekeyTools_BlendWidgetKey.bl_idname, 'R',
                       command='RESET')),
        (keymap, _bind(keymap, OP_ShapekeyTools_BlendWidgetKey.bl_idname, 'W',
                       command='CLEAR')),
        (keymap, _bind(keymap, OP_ShapekeyTools_BlendWidgetKey.bl_idname,
                       'LEFT_BRACKET', command='SCALE_DOWN')),
        (keymap, _bind(keymap, OP_ShapekeyTools_BlendWidgetKey.bl_idname,
                       'RIGHT_BRACKET', command='SCALE_UP')),
    ]
    for _keymap, item in bindings:
        try:
            item.active = True
        except (AttributeError, ReferenceError):
            pass
    return bindings


# endregion


# region 算子


class OP_ShapekeyTools_BlendWidget(Operator):
    bl_idname = "ho.shapekeytools_blend_widget"
    bl_label = "生成调试矩阵"
    bl_description = (
        "在 3D 视口左下角绘制混合矩阵坐标系：横纵轴参数名、矩阵点位、可拖动的中心点"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return bool(getattr(context, "window_manager", None)) and (
            resolve_area(context)[0] is not None)

    def invoke(self, context, event):
        return self._start(context)

    def execute(self, context):
        """脚本路径（``bpy.ops.ho.shapekeytools_blend_widget('EXEC_DEFAULT')``）。

        模态算子无法从脚本 invoke（Blender 的 ``wm_operator_invoke`` 只接受真实事件），
        但 ``execute`` 可以，因此留这条路径给自动化测试与调试。
        """
        return self._start(context)

    def _start(self, context):
        if WIDGET.is_running:
            self.report({'INFO'}, "调试矩阵已经在运行")
            return {'CANCELLED'}
        area, _region = resolve_area(context)
        if area is None:
            self.report({'ERROR'}, "找不到 3D 视口，无法生成调试矩阵")
            return {'CANCELLED'}
        WIDGET.start(context, area=area)
        WIDGET.window = getattr(context, "window", None) or WIDGET.window
        handler = bpy.types.SpaceView3D.draw_handler_add(
            draw_widget, (), 'WINDOW', 'POST_PIXEL')
        WIDGET.handles.append(handler)
        # 交互走空间级快捷键（见 ``bind_widget_keys``）：它不随工作区切换失效，
        # 每次点击只起一个活到松手的短模态。
        WIDGET.keymaps.extend(bind_widget_keys())
        ensure_widget_timer()
        redraw_all_areas()
        self.report({'INFO'}, "调试矩阵已生成：拖动中心点即可调试混合权重")
        return {'FINISHED'}


class OP_ShapekeyTools_BlendWidgetPick(Operator):
    """控件交互：由 3D 视口的左键快捷键触发，命中控件时才进入模态拖动。

    为什么不让生成算子的模态一直挂着：Ctrl+Space 最大化、切换工作区时 Blender 会把
    窗口上的模态算子清掉，绘制句柄却还在 —— 绘件看着还在，鼠标事件却没人收了。
    改成“空间级快捷键 + 点击时短模态”之后，**点击永远有事件**，模态只活到松手。
    """

    bl_idname = "ho.shapekeytools_blend_widget_pick"
    bl_label = "调试矩阵交互"
    bl_description = "调试矩阵的鼠标交互（左键拖动中心点 / 坐标点位）"
    bl_options = {'INTERNAL', 'BLOCKING'}

    # 脚本/Debug 用：直接给出区域坐标可以脱离真实事件做命中测试
    region_x: bpy.props.FloatProperty(name="区域 X", default=0.0, options={'SKIP_SAVE'})  # type: ignore
    region_y: bpy.props.FloatProperty(name="区域 Y", default=0.0, options={'SKIP_SAVE'})  # type: ignore

    @classmethod
    def poll(cls, context):
        return WIDGET.is_running and context.scene is not None

    def invoke(self, context, event):
        if not WIDGET.is_running:
            return {'CANCELLED'}
        WIDGET.window = getattr(context, "window", None) or WIDGET.window
        area = getattr(context, "area", None)
        if area is not None and getattr(area, "type", None) == 'VIEW_3D':
            WIDGET.area = area
        kind, index = pick_in_area(
            context, event.mouse_region_x, event.mouse_region_y, area)
        if kind is None:
            # 没点到控件：原样放行，选择 / 框选 / 导航都不受影响
            WIDGET.set_hover("", -1)
            return {'PASS_THROUGH'}
        WIDGET.drag_kind = kind
        WIDGET.drag_index = index
        item = _store.active_item(context.scene)
        if kind == "point" and item is not None:
            item.point_index = index
        # 拖动期间锁定坐标系范围，保证点位跟得上鼠标；松手后重新适配
        set_drag_active(True)
        context.window_manager.modal_handler_add(self)
        WIDGET.tag_redraw()
        return {'RUNNING_MODAL'}

    def execute(self, context):
        """脚本路径：用给定的区域坐标走一次命中测试（不进入模态）。"""
        kind, index = pick_in_area(context, self.region_x, self.region_y)
        if kind == "centre":
            WIDGET.drag_kind, WIDGET.drag_index = "centre", -1
        elif kind == "point":
            WIDGET.drag_kind, WIDGET.drag_index = "point", index
            item = _store.active_item(context.scene)
            if item is not None:
                item.point_index = index
        self.report({'INFO'}, f"命中 {kind}:{index}")
        return {'FINISHED'}

    def modal(self, context, event):
        if not WIDGET.is_running:
            return {'CANCELLED'}
        if event.type == 'MOUSEMOVE':
            if WIDGET.drag_kind in {"centre", "point"}:
                layout = WIDGET.last_layout
                if WIDGET.drag_kind == "centre":
                    set_cursor(context, event.mouse_region_x, event.mouse_region_y,
                               layout)
                else:
                    set_point(context, WIDGET.drag_index,
                              event.mouse_region_x, event.mouse_region_y, layout)
                WIDGET.tag_redraw()
            else:
                kind, index = pick_in_area(
                    context, event.mouse_region_x, event.mouse_region_y,
                    getattr(context, "area", None))
                WIDGET.set_hover(kind or "", index)
            return {'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            WIDGET.drag_kind = None
            WIDGET.drag_index = -1
            set_drag_active(False)
            WIDGET.layout_size = None
            WIDGET.tag_redraw()
            return {'FINISHED'}
        if event.type == 'ESC':
            WIDGET.drag_kind = None
            WIDGET.drag_index = -1
            set_drag_active(False)
            WIDGET.layout_size = None
            WIDGET.tag_redraw()
            return {'FINISHED'}
        return {'PASS_THROUGH'}


class OP_ShapekeyTools_BlendWidgetKey(Operator):
    """绘件的键盘命令（R 回原点 / W 归零 / [ ] 缩放），由空间级快捷键触发。"""

    bl_idname = "ho.shapekeytools_blend_widget_key"
    bl_label = "调试矩阵快捷键"
    bl_description = "调试矩阵的键盘命令（回原点 / 归零 / 缩放）"
    bl_options = {'INTERNAL'}

    command: bpy.props.EnumProperty(
        name="命令",
        items=(
            ('RESET', "回到原点", ""),
            ('CLEAR', "归零权重", ""),
            ('SCALE_UP', "放大", ""),
            ('SCALE_DOWN', "缩小", ""),
        ),
        default='RESET',
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return WIDGET.is_running and context.scene is not None

    def execute(self, context):
        if self.command == 'RESET':
            reset_cursor(context)
        elif self.command == 'CLEAR':
            clear_all_keys(context)
        elif self.command == 'SCALE_UP':
            scale_widget(context, 0.1)
        elif self.command == 'SCALE_DOWN':
            scale_widget(context, -0.1)
        return {'FINISHED'}


class OP_ShapekeyTools_BlendWidgetStop(Operator):
    bl_idname = "ho.shapekeytools_blend_widget_stop"
    bl_label = "关闭调试矩阵"
    bl_description = "关闭视口左下角的混合矩阵坐标绘件"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if not WIDGET.is_running:
            return {'CANCELLED'}
        # 一次性收干净：快捷键、绘制句柄、定时器、状态。交互是「空间级快捷键 +
        # 点击时短模态」，所以这里直接摘掉绑定即可，不会留下点不动的幽灵控件。
        WIDGET.cancel("已关闭")
        self.report({'INFO'}, "调试矩阵已关闭")
        return {'FINISHED'}


# endregion


cls = [
    OP_ShapekeyTools_BlendWidget,
    OP_ShapekeyTools_BlendWidgetPick,
    OP_ShapekeyTools_BlendWidgetKey,
    OP_ShapekeyTools_BlendWidgetStop,
]


def register():
    for item in cls:
        bpy.utils.register_class(item)


def unregister():
    WIDGET.cancel()
    _ADDON_KEYMAP["keymap"] = None
    for item in reversed(cls):
        bpy.utils.unregister_class(item)


__all__ = (
    "WIDGET",
    "axis_range_for",
    "compute_layout",
    "draw_widget",
    "invalidate_axis_range",
    "pick_in_area",
    "redraw_all_areas",
    "register",
    "resolve_area",
    "set_drag_active",
    "unregister",
)
