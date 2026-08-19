# HoPieCore 快速用法

`HoPieCore.py` 是 HoTools 自己的饼菜单代码层。它只包装 Blender 的 `UILayout`，不保存静态 JSON，也不负责注册菜单和快捷键。

## 创建一个饼

在 `Menu.draw(self, context)` 中：

```python
from .HoPieCore import HoPie

pie = HoPie(self.layout, context)
pie.left.pie("HO_MT_AnotherPie", "网格工具", icon="MESH_DATA")
pie.top.operator("ho.example", "执行", icon="CHECKMARK", enabled=True)
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

`center` 是 `top_center` 的别名，`center_secondary` 是 `bottom_center` 的别名。也可以用 `pie[0]` 到 `pie[9]` 访问。

## 三种入口

```python
slot.pie("HO_MT_ChildPie", "进入子饼")       # 嵌套饼
slot.menu("HO_MT_ChildMenu", "普通菜单")     # 普通下拉菜单
slot.popover("OBJECT_PT_display", "视图显示") # Blender 面板
slot.expand(draw_options, frame=True)          # 当前槽位直接展开
```

`expand` 的回调接收 `LayoutBuilder` 和 `context`：

```python
def draw_options(layout, context):
    row = layout.row(size="LARGE")
    row.item().prop(context.space_data.overlay, "show_text", "文本")
    row.item().operator("ho.refresh", "刷新", icon="FILE_REFRESH")
```

`prop` 直接读取传入对象的真实 RNA 属性，也支持 `"foo.bar"` 这样的属性路径。属性不存在时会跳过当前项，不会让整个饼报错。

## 常用配置

按钮支持 `text_ctxt`、`translate`、`icon`、`icon_value`、`enabled`、`active`、`alert`、`emboss`、`depress`、`icon_only`、`operator_context`、`scale_x`、`scale_y` 等参数。布局支持 `row`、`column`、`box`、`split`、`size`、`vspacer`、`fixed_col`、`fixed_but` 和 `spacer(hsep=...)`。

参数可以是普通值，也可以是接收 `context` 的函数，例如：

```python
pie.right.operator(
    "ho.toggle",
    "切换",
    enabled=lambda context: context.object is not None,
)
```

