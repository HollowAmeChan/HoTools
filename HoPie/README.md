# HoPie Core 快速用法

`_Core.py` 是 HoTools 自己的饼菜单代码层。它包装 Blender 的 `UILayout`，提供通用 operator 和布局基础设施，不保存静态 JSON；具体业务菜单和功能开关统一由 `_Register.py` 管理。

## 创建一个饼

在 `Menu.draw(self, context)` 中：

```python
from ._Core import HoPie

pie = HoPie(self.layout, context)
pie.left.pie("HO_MT_AnotherPie", "网格工具", icon="MESH_DATA")
pie.top.operator("ho.example", "执行", icon="CHECKMARK", enabled=True)
pie.finish()
```

如果外面已经调用了 `self.layout.menu_pie()`，使用 `HoPie.from_pie_layout(layout, context)`，避免重复创建。

## 槽位名称

八个方向和 PME 的顺序一致：

| 名称 | 方向 |
| --- | --- |
| `left` / `right` | 左 / 右 |
| `bottom` / `top` | 下 / 上 |
| `top_left` / `top_right` | 左上 / 右上 |
| `bottom_left` / `bottom_right` | 左下 / 右下 |
| `top_center` / `bottom_center` | 中心最顶 / 中心最底 |

`center` 是 `top_center` 的别名，`center_secondary` 是 `bottom_center` 的别名。也可以用 `pie[0]` 到 `pie[9]` 访问。槽位声明不要求按上表顺序书写，`finish()` 会按固定顺序回放并补齐空位；也可以使用 `with HoPie(...) as pie:` 自动结束。

## 三种入口

```python
slot.pie("HO_MT_ChildPie", "进入子饼")       # 嵌套饼
slot.menu("HO_MT_ChildMenu", "普通菜单")     # 普通下拉菜单
slot.popover("OBJECT_PT_display", "视图显示") # Blender 面板
slot.expand(draw_options, frame=True, width=1.25, height=1.2, height_offset=1.0)  # 当前槽位直接展开并留出距离
slot.expression(
    "C.space_data.overlay.show_overlays = not C.space_data.overlay.show_overlays",
    "叠加层", icon="OVERLAY",
)  # 用 operator 保留甩动命中
slot.toggle_prop(context.space_data.overlay, "show_overlays", "叠加层")
```

`slot.pie(...)` 使用 HoPie 自己的事件转发器打开子饼，因此会沿用当前鼠标事件；需要兼容原生调用时可传 `operator_idname="wm.call_menu_pie"`。

展开面板可以继续展开子面板，内容会保持在同一个绘制上下文中：

```python
def draw_parent(layout, context):
    layout.label("父面板")
    layout.expand(draw_child, frame=True)
```

也可以把普通菜单入口直接写成展开面板：`layout.menu("子菜单", "子面板", expand=draw_child)`。这样不会再弹出第二个窗口，而是和父面板同时绘制。

如果子面板已经是注册过的 Blender `Menu`，可以直接写 `layout.menu("HO_MT_Child", expand=True)`，内部的 `Menu.draw` 会在当前布局中递归绘制。

`expand` 的回调接收 `LayoutBuilder` 和 `context`：

```python
def draw_options(layout, context):
    row = layout.row(size="LARGE")
    row.item().prop(context.space_data.overlay, "show_text", "文本")
    row.item().operator("ho.refresh", "刷新", icon="FILE_REFRESH")
```

`expand` 也兼容直接接收原生 `UILayout` 的旧绘制函数：`scale_x`、`scale_y`、
`alignment`、`enabled`、`alert`、`use_property_decorate` 等属性赋值会自动转发到底层布局，
因此可以直接复用其他模块的绘制函数，不需要为 HoPie 改写一份。

展开面板的 `width`/`height` 分别是横向和纵向比例，底层对应 Blender 的 `UILayout.scale_x/scale_y`；`height_offset` 只控制垂直方向，正数让内容向上，负数让内容向下，不会占用下一个槽位。也可以直接传 `scale_x`/`scale_y`，或在 `DialogSettings(scale_x=..., scale_y=..., height_offset=...)` 中统一配置。

`prop` 直接读取传入对象的真实 RNA 属性，也支持 `"foo.bar"` 这样的属性路径。属性不存在时会跳过当前项，不会让整个饼报错。

`LayoutBuilder` 在运行时只是 `UILayout` 的轻量包装；它只在类型检查阶段模拟继承 `bpy.types.UILayout`。因此回调标注为 `LayoutBuilder` 时，编辑器可以同时提示 Blender 原生布局方法和 HoPie 的 `item()`、`expression()`、`expand()` 等扩展方法。

需要甩动触发的布尔开关不要使用 `prop()`，改用 `toggle_prop()` 或 `expression()`；前者直接翻转真实 RNA 属性，后者执行一次 Core 表达式。表达式按钮可使用 `C`/`context`、`bpy`、`D`（`bpy.data`）、`E`（当前事件）以及 `A/O/W/S/R` 上下文别名，不提供 Python 内置函数。

跨模块复用同一逻辑时，也可以使用 Core 的安全辅助函数：

```python
from ._Core import draw_prop

draw_prop(layout, context.space_data.overlay, "show_text", "文本", icon="TEXT", context=context)
```

HoMainPie 遵循同一约定：视图开关和叠加层属性直接绘制在主饼槽位；只有网格工具这类确实要“进入下一层”的功能才使用 `menu()` 或 `pie()`。

表达式按钮除了 `C`/`context` 外，也提供 `space`、`screen`、`scene` 和 `preferences` 别名；因此可以用一条命令同步切换多个 RNA 布尔属性：

```python
slot.expression(
    "space.show_region_header = not space.show_region_header; "
    "screen.show_statusbar = not screen.show_statusbar",
    text="标题/状态栏",
)
```

## 常用配置

按钮支持 `text_ctxt`、`translate`、`icon`、`icon_value`、`enabled`、`active`、`alert`、`emboss`、`depress`、`icon_only`、`operator_context`、`scale_x`、`scale_y` 等参数。布局支持 `row`、`column`、`box`、`split`、`size`、`vspacer`、`fixed_col`、`fixed_but` 和 `spacer(hsep=...)`。

图标名优先交给当前 Blender 直接绘制；RNA 拒绝时统一回退为 `ERROR`，`@123` 仍表示自定义 `icon_value`。

参数可以是普通值，也可以是接收 `context` 的函数，例如：

```python
pie.right.operator(
    "ho.toggle",
    "切换",
    enabled=lambda context: context.object is not None,
)
```

> **展开布局注意**：Blender 在饼菜单的嵌套展开容器中，`row(align=True)` 可能吞掉固定行的一列。需要多列按钮时，优先使用 `grid_flow(columns=N, even_columns=True, even_rows=True, align=True)`；这样既能保留完整按钮，也能保持列宽和视觉对齐。
