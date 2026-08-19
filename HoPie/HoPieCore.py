"""HoPie 的轻量核心。

这个文件只负责“怎么写一个饼菜单”，不负责注册类、注册快捷键、保存 JSON，
也不依赖 PME。它借鉴了 PME 的几个实用约定：

* 饼菜单有八个方向槽位，另外提供 PME 风格的最顶、最底两个中心槽位；
* `pie()` 是进入另一个饼，`menu()` 是普通菜单，`expand()` 是在当前槽位
  直接展开内容，三者明确区分；
* 常见的 enabled、active、alert、emboss、operator_context、icon_value、
  row/column/box/split 等属性都有明确参数；
* 所有内容都可以从真实 Blender RNA 对象绘制，不需要静态菜单数据。

最小用法（放在 Blender 的 Menu.draw 中）：

    pie = HoPie(self.layout, context)
    pie.left.pie("HO_MT_HoMainPieMesh", "网格工具", icon="MESH_DATA")
    pie.top.operator("ho.some_operator", "执行", icon="CHECKMARK")
    pie.top_left.expand(draw_view_options, frame=True)
    pie.top_center.operator("ho.some_operator", "最顶")

`draw_view_options` 会收到一个 `LayoutBuilder` 和当前 context：

    def draw_view_options(layout, context):
        row = layout.row()
        row.item().prop(context.space_data.overlay, "show_text", "文本")

这里的“展开”是直接把回调绘制到当前槽位，不会再弹出一个新的嵌套饼。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Mapping, Optional, Tuple, Union


_UNSET = object()


def _resolve(value: Any, context: Any) -> Any:
    """解析允许动态计算的参数。

    传入普通值时原样返回；传入函数时优先使用 `(context)`，无参数函数也能用。
    这样菜单可以直接读取当前场景、当前对象和当前视图状态。
    """
    if not callable(value):
        return value
    try:
        parameters = inspect.signature(value).parameters.values()
        positional = [
            item for item in parameters
            if item.kind in (item.POSITIONAL_ONLY, item.POSITIONAL_OR_KEYWORD)
        ]
        if positional:
            return value(context)
        return value()
    except (TypeError, ValueError):
        # 某些 Blender/RNA 可调用对象没有可检查的签名。
        try:
            return value(context)
        except TypeError:
            return value()


def _set_layout(layout: Any, options: Optional["LayoutOptions"], context: Any,
                default_operator_context: Optional[str] = None) -> Any:
    """把通用布局属性安全地写入 UILayout。

    不同 Blender 版本对 UILayout 暴露的属性略有差异，所以单个属性不存在时
    只跳过它，不让整个饼菜单失效。
    """
    if options is None:
        options = LayoutOptions()
    values = {
        "operator_context": options.operator_context
        if options.operator_context is not None else default_operator_context,
        "enabled": options.enabled,
        "active": options.active,
        "alert": options.alert,
        "alignment": options.alignment,
        "scale_x": options.scale_x,
        "scale_y": options.scale_y,
    }
    for name, value in values.items():
        if value is None:
            continue
        value = _resolve(value, context)
        try:
            setattr(layout, name, value)
        except (AttributeError, TypeError, ValueError):
            pass
    return layout


def _icon_kwargs(icon: Any = None, icon_value: Any = None) -> Dict[str, Any]:
    """把 Blender 图标名和 PME 的 `@123` 图标值写成 UILayout 参数。"""
    if icon_value is not None:
        return {"icon_value": icon_value}
    if isinstance(icon, str) and icon.startswith("@"):
        try:
            return {"icon_value": int(icon[1:])}
        except (TypeError, ValueError):
            # 非数字的自定义图标名交给 Blender 处理，避免误吞掉用户输入。
            return {"icon": icon}
    if icon is not None:
        return {"icon": icon}
    return {}


def _safe_call(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """调用版本间参数略有差异的 UILayout 方法。"""
    try:
        return method(*args, **kwargs)
    except TypeError:
        # 老版本或测试替身不认识 icon_value/use_mouse_over_open 等参数时，
        # 去掉这些非核心参数再调用一次。
        fallback = dict(kwargs)
        fallback.pop("icon_value", None)
        fallback.pop("use_mouse_over_open", None)
        fallback.pop("text_ctxt", None)
        fallback.pop("translate", None)
        return method(*args, **fallback)


def resolve_path(owner: Any, path: str) -> Tuple[Any, Optional[str]]:
    """解析 `a.b.c`，返回最后一个属性的 owner 和属性名。

    `prop()` 使用它来支持真实 RNA 的嵌套对象；属性不存在时返回 `(None, None)`。
    """
    if owner is None or not isinstance(path, str) or not path:
        return None, None
    parts = [part for part in path.split(".") if part]
    if not parts:
        return None, None
    current = owner
    for part in parts[:-1]:
        try:
            if isinstance(current, Mapping):
                current = current[part]
            else:
                current = getattr(current, part)
        except (AttributeError, KeyError, IndexError, TypeError):
            return None, None
        if current is None:
            return None, None
    return current, parts[-1]


@dataclass
class PieSettings:
    """保留 PME 饼菜单级设置，供未来统一的调用器使用。"""

    radius: float = -1.0
    threshold: float = -1.0
    confirm: float = -1.0
    flick: bool = False
    open_mode: str = "PRESS"


@dataclass
class DialogSettings:
    """直接展开/对话框内容的通用配置。"""

    title: str = ""
    box: bool = False
    auto_close: bool = True
    expand: bool = True
    panel: str = "PIE"
    width: int = 0


@dataclass
class HoPieConfig:
    """一个饼的配置容器；只保存配置，不触碰 Blender 注册系统。"""

    pie: PieSettings = field(default_factory=PieSettings)
    dialog: DialogSettings = field(default_factory=DialogSettings)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LayoutOptions:
    """UILayout 容器属性，所有字段都可以是普通值或 `context -> value`。"""

    operator_context: Optional[Any] = None
    enabled: Optional[Any] = None
    active: Optional[Any] = None
    alert: Optional[Any] = None
    alignment: Optional[Any] = None
    scale_x: Optional[Any] = None
    scale_y: Optional[Any] = None


@dataclass
class ItemOptions:
    """按钮/属性项属性，尽量覆盖 PME 常用的可调字段。"""

    text_ctxt: Optional[Any] = None
    translate: Optional[Any] = None
    icon: Optional[Any] = None
    icon_value: Optional[Any] = None
    enabled: Optional[Any] = None
    active: Optional[Any] = None
    alert: Optional[Any] = None
    emboss: Optional[Any] = None
    depress: Optional[Any] = None
    icon_only: Optional[Any] = None
    operator_context: Optional[Any] = None
    alignment: Optional[Any] = None
    scale_x: Optional[Any] = None
    scale_y: Optional[Any] = None
    use_mouse_over_open: Optional[Any] = None
    expand: Optional[Any] = None
    slider: Optional[Any] = None
    toggle: Optional[Any] = None
    index: Optional[Any] = None
    event: Optional[Any] = None
    full_event: Optional[Any] = None


_OPERATOR_STYLE_FIELDS = {
    "text_ctxt", "translate", "icon", "icon_value", "enabled", "active",
    "alert", "emboss", "depress", "icon_only", "operator_context",
    "alignment", "scale_x", "scale_y",
}
_MENU_STYLE_FIELDS = _OPERATOR_STYLE_FIELDS | {"use_mouse_over_open"}


def _copy_item_options(options: Optional[ItemOptions]) -> ItemOptions:
    if options is None:
        return ItemOptions()
    if isinstance(options, Mapping):
        fields = ItemOptions.__dataclass_fields__
        return ItemOptions(**{
            key: value for key, value in options.items() if key in fields
        })
    return replace(options)


class LayoutBuilder:
    """UILayout 的小型、可链式包装。

    Builder 不持有 Blender 数据，只持有一个 `UILayout`；因此也可以用简单的
    测试替身验证菜单结构，而不需要启动 Blender。
    """

    def __init__(self, layout: Any, context: Any = None,
                 operator_context: str = "INVOKE_DEFAULT") -> None:
        self.layout = layout
        self.context = context
        self.operator_context = operator_context
        self.metadata: Dict[str, Any] = {}
        _set_layout(layout, LayoutOptions(operator_context=operator_context),
                    context, operator_context)

    @property
    def raw_layout(self) -> Any:
        """需要 Blender 原生 API 时的逃生口。"""
        return self.layout

    def configure(self, **values: Any) -> "LayoutBuilder":
        """修改当前容器的 PME 风格属性并返回自身。"""
        _set_layout(
            self.layout,
            LayoutOptions(**{
                key: value for key, value in values.items()
                if key in LayoutOptions.__dataclass_fields__
            }),
            self.context,
            self.operator_context,
        )
        return self

    def _item_options(self, options: Optional[ItemOptions], **values: Any) -> ItemOptions:
        result = _copy_item_options(options)
        for key, value in values.items():
            if value is not _UNSET and value is not None:
                setattr(result, key, value)
        return result

    def _item_layout(self, options: ItemOptions) -> Any:
        """为带状态/缩放的单项建立隔离列，避免属性泄漏到后续按钮。"""
        state = (
            options.enabled, options.active, options.alert,
            options.scale_x, options.scale_y, options.alignment,
        )
        isolated = any(value is not None for value in state)
        target = self.layout.column(align=True) if isolated else self.layout
        layout_options = LayoutOptions(
            operator_context=options.operator_context or self.operator_context,
            enabled=options.enabled,
            active=options.active,
            alert=options.alert,
            alignment=options.alignment,
            scale_x=options.scale_x,
            scale_y=options.scale_y,
        )
        return _set_layout(target, layout_options, self.context, self.operator_context)

    def item(self, align: bool = True, **options: Any) -> "LayoutBuilder":
        """创建 PME 常用的“每个按钮一列”，适合展开槽位中的横向排版。"""
        child = self.layout.column(align=align)
        builder = LayoutBuilder(
            child,
            self.context,
            options.pop("operator_context", self.operator_context),
        )
        if options:
            builder.configure(**options)
        return builder

    def operator(self, idname: str, text: Optional[Any] = None,
                 *, icon: Any = None, icon_value: Any = None,
                 options: Optional[ItemOptions] = None,
                 props: Optional[Mapping[str, Any]] = None,
                 **operator_props: Any) -> Any:
        """添加操作按钮，并把 `props`/额外关键字写入操作属性。"""
        style_values = {
            key: operator_props.pop(key)
            for key in _OPERATOR_STYLE_FIELDS
            if key in operator_props
        }
        item = self._item_options(options, icon=icon, icon_value=icon_value)
        item = self._item_options(item, **style_values)
        target = self._item_layout(item)
        kwargs: Dict[str, Any] = {}
        if text is not None:
            kwargs["text"] = _resolve(text, self.context)
        for name in ("text_ctxt", "translate", "emboss", "depress", "icon_only"):
            value = getattr(item, name)
            if value is not None:
                kwargs[name] = _resolve(value, self.context)
        kwargs.update(_icon_kwargs(
            _resolve(item.icon, self.context),
            _resolve(item.icon_value, self.context),
        ))
        button = _safe_call(target.operator, idname, **kwargs)
        values = dict(props or {})
        values.update(operator_props)
        for name, value in values.items():
            try:
                setattr(button, name, _resolve(value, self.context))
            except (AttributeError, TypeError, ValueError):
                # 不同 Blender 版本没有该操作属性时，菜单按钮仍应保留。
                pass
        return button

    def prop(self, owner: Any, path: str, text: Optional[Any] = None,
             *, icon: Any = None, icon_value: Any = None,
             options: Optional[ItemOptions] = None, expand: Any = None,
             slider: Any = None, toggle: Any = None, icon_only: Any = None,
             index: Any = None, emboss: Any = None, **kwargs: Any) -> Any:
        """读取真实 RNA 属性并绘制；属性路径可以是 `foo.bar`。"""
        owner = _resolve(owner, self.context)
        owner, prop_name = resolve_path(owner, path)
        if owner is None or prop_name is None or not hasattr(owner, prop_name):
            return None
        style_values = {
            key: kwargs.pop(key)
            for key in ItemOptions.__dataclass_fields__
            if key in kwargs
        }
        item = self._item_options(
            options,
            icon=icon,
            icon_value=icon_value,
            expand=expand,
            slider=slider,
            toggle=toggle,
            icon_only=icon_only,
            emboss=emboss,
        )
        item = self._item_options(item, **style_values)
        target = self._item_layout(item)
        call_kwargs: Dict[str, Any] = {}
        if text is not None:
            call_kwargs["text"] = _resolve(text, self.context)
        for name in ("text_ctxt", "translate", "expand", "slider", "toggle",
                     "icon_only", "event", "full_event", "emboss"):
            value = getattr(item, name, None)
            if value is None:
                value = kwargs.pop(name, None)
            if value is not None:
                call_kwargs[name] = _resolve(value, self.context)
        if index is None:
            index = item.index
        if index is not None:
            call_kwargs["index"] = _resolve(index, self.context)
        call_kwargs.update(_icon_kwargs(
            _resolve(item.icon, self.context),
            _resolve(item.icon_value, self.context),
        ))
        return _safe_call(target.prop, owner, prop_name, **call_kwargs)

    def menu(self, menu_name: str, text: Optional[Any] = None,
             *, icon: Any = None, icon_value: Any = None,
             options: Optional[ItemOptions] = None,
             use_mouse_over_open: Any = None,
             **item_values: Any) -> Any:
        """添加普通下拉菜单；它不会创建新的饼。"""
        style_values = {
            key: item_values.pop(key)
            for key in _MENU_STYLE_FIELDS
            if key in item_values
        }
        item = self._item_options(
            options, icon=icon, icon_value=icon_value,
            use_mouse_over_open=use_mouse_over_open,
        )
        item = self._item_options(item, **style_values)
        target = self._item_layout(item)
        kwargs: Dict[str, Any] = {}
        if text is not None:
            kwargs["text"] = _resolve(text, self.context)
        if item.use_mouse_over_open is not None:
            kwargs["use_mouse_over_open"] = _resolve(item.use_mouse_over_open, self.context)
        kwargs.update(_icon_kwargs(
            _resolve(item.icon, self.context),
            _resolve(item.icon_value, self.context),
        ))
        return _safe_call(target.menu, menu_name, **kwargs)

    def pie(self, menu_name: str, text: Optional[Any] = None,
            *, icon: Any = None, icon_value: Any = None,
            options: Optional[ItemOptions] = None,
            invoke_mode: Optional[str] = None,
            **item_values: Any) -> Any:
        """添加一个嵌套饼入口；绘制目标仍由 Blender 菜单注册系统负责。"""
        style_values = {
            key: item_values.pop(key)
            for key in _OPERATOR_STYLE_FIELDS
            if key in item_values
        }
        item = self._item_options(options, icon=icon, icon_value=icon_value)
        item = self._item_options(item, **style_values)
        target = self._item_layout(item)
        kwargs: Dict[str, Any] = {}
        if text is not None:
            kwargs["text"] = _resolve(text, self.context)
        for name in ("text_ctxt", "translate", "emboss", "depress", "icon_only"):
            value = getattr(item, name)
            if value is not None:
                kwargs[name] = _resolve(value, self.context)
        kwargs.update(_icon_kwargs(
            _resolve(item.icon, self.context),
            _resolve(item.icon_value, self.context),
        ))
        button = _safe_call(target.operator, "wm.call_menu_pie", **kwargs)
        try:
            button.name = menu_name
            if invoke_mode is not None:
                button.invoke_mode = invoke_mode
        except (AttributeError, TypeError, ValueError):
            pass
        return button

    nested_pie = pie

    def popover(self, panel: str, text: Optional[Any] = None,
                *, icon: Any = None, icon_value: Any = None,
                options: Optional[ItemOptions] = None,
                space_type: Optional[str] = None,
                region_type: Optional[str] = None,
                **item_values: Any) -> Any:
        """添加 Blender 原生面板入口。"""
        style_values = {
            key: item_values.pop(key)
            for key in _MENU_STYLE_FIELDS
            if key in item_values
        }
        item = self._item_options(options, icon=icon, icon_value=icon_value)
        item = self._item_options(item, **style_values)
        target = self._item_layout(item)
        kwargs: Dict[str, Any] = {"panel": panel}
        if text is not None:
            kwargs["text"] = _resolve(text, self.context)
        if space_type is not None:
            kwargs["space_type"] = space_type
        if region_type is not None:
            kwargs["region_type"] = region_type
        kwargs.update(_icon_kwargs(
            _resolve(item.icon, self.context),
            _resolve(item.icon_value, self.context),
        ))
        return _safe_call(target.popover, **kwargs)

    def label(self, text: Any = "", *, icon: Any = None,
              icon_value: Any = None) -> Any:
        kwargs: Dict[str, Any] = {"text": _resolve(text, self.context)}
        kwargs.update(_icon_kwargs(
            _resolve(icon, self.context),
            _resolve(icon_value, self.context),
        ))
        return _safe_call(self.layout.label, **kwargs)

    def separator(self, factor: Optional[Any] = None) -> Any:
        if factor is None:
            return self.layout.separator()
        try:
            return self.layout.separator(factor=_resolve(factor, self.context))
        except TypeError:
            return self.layout.separator()

    sep = separator

    def spacer(self, *, hsep: str = "NONE", factor: Optional[Any] = None) -> Any:
        """PME spacer 的轻量版本；COLUMN/ALIGNER 等标记保存在 metadata。"""
        self.metadata.setdefault("spacers", []).append({"hsep": hsep, "factor": factor})
        factors = {"NONE": 1.0, "SPACER": 1.0, "COLUMN": 1.0,
                   "ALIGNER": 1.0, "LARGE": 3.0, "LARGER": 5.0}
        return self.separator(factor if factor is not None else factors.get(hsep, 1.0))

    def row(self, *, align: bool = True, options: Optional[LayoutOptions] = None,
            size: Optional[str] = None, vspacer: Optional[Any] = None,
            fixed_col: bool = False, fixed_but: bool = False,
            **layout_options: Any) -> "LayoutBuilder":
        """创建一行，并保留 PME 的 size/vspacer/fixed 配置。"""
        if vspacer not in (None, "NONE", 0):
            values = {"NORMAL": 1.0, "LARGE": 3.0, "LARGER": 5.0}
            self.separator(values.get(vspacer, vspacer))
        child = self.layout.row(align=align)
        scale_y = layout_options.pop("scale_y", None)
        if scale_y is None:
            scale_y = {"NORMAL": 1.0, "LARGE": 1.25, "LARGER": 1.5}.get(size)
        merged = replace(options) if options is not None else LayoutOptions()
        if scale_y is not None:
            merged.scale_y = scale_y
        for key, value in layout_options.items():
            if key in LayoutOptions.__dataclass_fields__:
                setattr(merged, key, value)
        builder = LayoutBuilder(child, self.context,
                                merged.operator_context or self.operator_context)
        builder.configure(**{
            key: value for key, value in vars(merged).items() if value is not None
        })
        builder.metadata["row"] = {
            "size": size, "vspacer": vspacer,
            "fixed_col": fixed_col, "fixed_but": fixed_but,
        }
        return builder

    def column(self, *, align: bool = True,
               options: Optional[LayoutOptions] = None,
               **layout_options: Any) -> "LayoutBuilder":
        child = self.layout.column(align=align)
        merged = replace(options) if options is not None else LayoutOptions()
        for key, value in layout_options.items():
            if key in LayoutOptions.__dataclass_fields__:
                setattr(merged, key, value)
        return LayoutBuilder(child, self.context,
                             merged.operator_context or self.operator_context).configure(
                                 **{key: value for key, value in vars(merged).items()
                                    if value is not None}
                             )

    def box(self, *, options: Optional[LayoutOptions] = None,
            **layout_options: Any) -> "LayoutBuilder":
        child = self.layout.box()
        merged = replace(options) if options is not None else LayoutOptions()
        for key, value in layout_options.items():
            if key in LayoutOptions.__dataclass_fields__:
                setattr(merged, key, value)
        return LayoutBuilder(child, self.context,
                             merged.operator_context or self.operator_context).configure(
                                 **{key: value for key, value in vars(merged).items()
                                    if value is not None}
                             )

    def split(self, factor: Optional[Any] = None,
              *, align: bool = False) -> "LayoutBuilder":
        kwargs = {"align": align}
        if factor is not None:
            kwargs["factor"] = _resolve(factor, self.context)
        return LayoutBuilder(self.layout.split(**kwargs), self.context,
                             self.operator_context)

    def expand(self, draw: Callable[..., Any], *, frame: bool = False,
               settings: Optional[DialogSettings] = None) -> "LayoutBuilder":
        """在当前槽位直接绘制回调内容，不调用 `layout.menu()`。

        回调签名支持 `draw(layout)` 或 `draw(layout, context)`；这里的 layout 是
        `LayoutBuilder`，因此可以继续链式调用 `row/prop/operator`。
        """
        target = self.layout.box() if frame else self.layout
        target = target.column(align=True)
        builder = LayoutBuilder(target, self.context, self.operator_context)
        builder.metadata["dialog"] = settings or DialogSettings(box=frame)
        try:
            parameters = inspect.signature(draw).parameters
        except (TypeError, ValueError):
            parameters = {"layout": None, "context": None}
        positional = [
            item for item in parameters.values()
            if item.kind in (item.POSITIONAL_ONLY, item.POSITIONAL_OR_KEYWORD)
        ]
        if len(positional) == 0:
            draw()
        elif len(positional) == 1:
            draw(builder)
        else:
            draw(builder, self.context)
        return builder

    expanded = expand
    expanded_menu = expand
    draw = expand


class SlotBuilder(LayoutBuilder):
    """一个有名字的饼槽位。"""

    def __init__(self, layout: Any, context: Any, name: str, index: int,
                 operator_context: str = "INVOKE_DEFAULT") -> None:
        super().__init__(layout, context, operator_context)
        self.name = name
        self.index = index


class HoPie(LayoutBuilder):
    """HoPie 菜单的入口对象。

    默认会从传入的 `self.layout` 创建 `menu_pie()`；如果调用方已经拿到了
    `layout.menu_pie()`，传 `menu_pie=False` 即可。八个方向槽位在初始化时固定建立，
    所以可以按任意顺序写 `pie.left`、`pie.top_left`，不会因为调用顺序改变方向。
    中心的 `top_center`/`bottom_center` 会在第一次使用时按 PME 的间隔规则追加。
    """

    SLOT_NAMES: Tuple[str, ...] = (
        "left", "right", "bottom", "top",
        "top_left", "top_right", "bottom_left", "bottom_right",
    )
    EXTRA_SLOT_NAMES: Tuple[str, ...] = ("top_center", "bottom_center")

    def __init__(self, layout: Any, context: Any = None, *,
                 menu_pie: bool = True,
                 config: Optional[HoPieConfig] = None,
                 settings: Optional[PieSettings] = None) -> None:
        if menu_pie and hasattr(layout, "menu_pie"):
            layout = layout.menu_pie()
        super().__init__(layout, context, "INVOKE_DEFAULT")
        self.config = config or HoPieConfig(pie=settings or PieSettings())
        # 常用配置提供直接入口，完整配置仍可从 `pie.config` 读取。
        self.settings = self.config.pie
        self.dialog = self.config.dialog
        self._slots: Dict[str, SlotBuilder] = {}
        for index, name in enumerate(self.SLOT_NAMES):
            child = layout.column(align=True)
            self._slots[name] = SlotBuilder(
                child, context, name, index, self.operator_context,
            )
        self._centers: Dict[str, SlotBuilder] = {}

    @classmethod
    def from_pie_layout(cls, layout: Any, context: Any = None,
                        **kwargs: Any) -> "HoPie":
        """用已经创建好的 `menu_pie()` 布局构造 HoPie。"""
        return cls(layout, context, menu_pie=False, **kwargs)

    def slot(self, name_or_index: Union[str, int]) -> SlotBuilder:
        if isinstance(name_or_index, int):
            all_names = self.SLOT_NAMES + self.EXTRA_SLOT_NAMES
            try:
                name_or_index = all_names[name_or_index]
            except IndexError as error:
                raise KeyError(name_or_index) from error
        aliases = {
            "center": "top_center",
            "center_secondary": "bottom_center",
            "topmost": "top_center",
            "bottommost": "bottom_center",
        }
        name_or_index = aliases.get(name_or_index, name_or_index)
        if name_or_index in self.EXTRA_SLOT_NAMES:
            index = 8 + self.EXTRA_SLOT_NAMES.index(name_or_index)
            return self._center(name_or_index, index)
        try:
            return self._slots[name_or_index]
        except KeyError as error:
            raise KeyError("未知饼槽位: %s" % name_or_index) from error

    def __getitem__(self, name_or_index: Union[str, int]) -> SlotBuilder:
        return self.slot(name_or_index)

    def _center(self, name: str, index: int) -> SlotBuilder:
        if name not in self._centers:
            # PME 只有在中心项存在时才插入两段间隔；第一次访问时再创建，
            # 不让一个没有中心按钮的普通饼平白多出两个菜单项。
            if not self._centers:
                self.layout.separator()
                self.layout.separator()
                top_child = self.layout.column(align=True)
                self._centers["top_center"] = SlotBuilder(
                    top_child, self.context, "top_center", 8,
                    self.operator_context,
                )
                if name == "bottom_center":
                    self.layout.separator()
                    bottom_child = self.layout.column(align=True)
                    self._centers["bottom_center"] = SlotBuilder(
                        bottom_child, self.context, "bottom_center", 9,
                        self.operator_context,
                    )
            elif name == "bottom_center":
                self.layout.separator()
                child = self.layout.column(align=True)
                self._centers[name] = SlotBuilder(
                    child, self.context, name, index, self.operator_context,
                )
        return self._centers[name]

    @property
    def center(self) -> SlotBuilder:
        return self.top_center

    @property
    def center_secondary(self) -> SlotBuilder:
        return self.bottom_center

    @property
    def top_center(self) -> SlotBuilder:
        """PME 第 9 项：饼中心最顶。"""
        return self._center("top_center", 8)

    @property
    def bottom_center(self) -> SlotBuilder:
        """PME 第 10 项：饼中心最底。"""
        return self._center("bottom_center", 9)

    # 这两个别名让“最顶/最底”的含义在调用处更明显。
    topmost = top_center
    bottommost = bottom_center

    @property
    def left(self) -> SlotBuilder:
        return self._slots["left"]

    @property
    def right(self) -> SlotBuilder:
        return self._slots["right"]

    @property
    def bottom(self) -> SlotBuilder:
        return self._slots["bottom"]

    @property
    def top(self) -> SlotBuilder:
        return self._slots["top"]

    @property
    def top_left(self) -> SlotBuilder:
        return self._slots["top_left"]

    @property
    def top_right(self) -> SlotBuilder:
        return self._slots["top_right"]

    @property
    def bottom_left(self) -> SlotBuilder:
        return self._slots["bottom_left"]

    @property
    def bottom_right(self) -> SlotBuilder:
        return self._slots["bottom_right"]


# 这个别名便于把它当作“饼创建器”阅读，也方便以后保留 PME 风格命名。
PieBuilder = HoPie


__all__ = [
    "DialogSettings",
    "HoPie",
    "HoPieConfig",
    "ItemOptions",
    "LayoutBuilder",
    "LayoutOptions",
    "PieBuilder",
    "PieSettings",
    "SlotBuilder",
    "resolve_path",
]
