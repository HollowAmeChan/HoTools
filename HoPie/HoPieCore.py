"""HoPie 的轻量核心。

这个文件负责饼菜单 DSL、通用 operator 和注册基础设施，不保存 JSON，
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
    pie.finish()

`draw_view_options` 会收到一个 `LayoutBuilder` 和当前 context：

    def draw_view_options(layout, context):
        row = layout.row()
        row.item().prop(context.space_data.overlay, "show_text", "文本")

这里的“展开”是直接把回调绘制到当前槽位，不会再弹出一个新的嵌套饼。
"""

import inspect
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Callable, Dict, Mapping, Optional, Tuple, Union

if TYPE_CHECKING:
    # 仅供 IDE/类型检查器使用。Blender 的 UILayout 是 RNA 类型，运行时不应
    # 真的继承它；否则可能触发不可实例化或不可注册的 RNA 类型错误。
    from bpy.types import UILayout as _UILayoutType
else:
    _UILayoutType = object

try:
    import bpy
    from bpy.props import StringProperty
    _HO_OPERATOR_BASE = bpy.types.Operator
except (ImportError, AttributeError):
    bpy = None

    class _HO_OPERATOR_BASE:
        pass

    def StringProperty(**kwargs: Any) -> Any:
        return None


_UNSET = object()
_ICON_NAMES = None
_ICON_NAMES_READY = False
_QUICK_ACTIONS: Dict[str, Callable[..., Any]] = {}
_QUICK_ACTION_SERIAL = 0
_HO_PIE_EVENT = None


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


def _blender_icon_names() -> Optional[set]:
    """读取 Blender 当前版本的 UILayout 图标枚举。"""
    global _ICON_NAMES, _ICON_NAMES_READY
    if _ICON_NAMES_READY:
        return _ICON_NAMES
    _ICON_NAMES_READY = True
    try:
        import bpy
        rna = getattr(getattr(bpy.types, "UILayout", None), "bl_rna", None)
        functions = getattr(rna, "functions", None)
        if functions is None:
            return None
        for function_name in ("operator", "prop", "label", "menu"):
            try:
                function = functions.get(function_name)
            except AttributeError:
                function = functions[function_name]
            if function is None:
                continue
            parameters = getattr(function, "parameters", None)
            if parameters is None:
                continue
            try:
                parameter = parameters.get("icon")
            except AttributeError:
                parameter = parameters["icon"]
            enum_items = getattr(parameter, "enum_items", None)
            if enum_items is None:
                continue
            names = {
                str(item.identifier)
                for item in enum_items
                if getattr(item, "identifier", None)
            }
            if names:
                _ICON_NAMES = names
                return _ICON_NAMES
    except (ImportError, AttributeError, KeyError, IndexError, TypeError,
            RuntimeError, ValueError):
        pass
    return None


def _normalize_icon(icon: Any) -> Any:
    """图标不存在时统一回退到 Blender 的 ERROR 图标。"""
    if not isinstance(icon, str):
        return "ERROR"
    if icon == "":
        return "ERROR"
    names = _blender_icon_names()
    if names is not None and icon not in names:
        return "ERROR"
    return icon


def _icon_kwargs(icon: Any = None, icon_value: Any = None) -> Dict[str, Any]:
    """把 Blender 图标名和 PME 的 `@123` 图标值写成 UILayout 参数。"""
    if icon_value is not None:
        return {"icon_value": icon_value}
    if isinstance(icon, str) and icon.startswith("@"):
        try:
            return {"icon_value": int(icon[1:])}
        except (TypeError, ValueError):
            return {"icon": "ERROR"}
    if icon is not None:
        return {"icon": _normalize_icon(icon)}
    return {}


def _safe_call(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """调用版本间参数略有差异的 UILayout 方法。"""
    try:
        return method(*args, **kwargs)
    except TypeError:
        if kwargs.get("icon") not in (None, "ERROR"):
            # 某些 Blender 版本的 RNA 枚举反射不完整，运行时再做一次统一回退。
            retry = dict(kwargs)
            retry["icon"] = "ERROR"
            try:
                return method(*args, **retry)
            except TypeError:
                pass
        # 老版本或测试替身不认识 icon_value/use_mouse_over_open 等参数时，
        # 去掉这些非核心参数再调用一次。
        fallback = dict(kwargs)
        fallback.pop("icon_value", None)
        fallback.pop("use_mouse_over_open", None)
        fallback.pop("text_ctxt", None)
        fallback.pop("translate", None)
        return method(*args, **fallback)


def _store_quick_action(callback: Callable[..., Any]) -> str:
    """为一次菜单绘制保存回调，返回写入 operator 的短 token。"""
    global _QUICK_ACTION_SERIAL
    _QUICK_ACTION_SERIAL += 1
    token = "action_%d" % _QUICK_ACTION_SERIAL
    _QUICK_ACTIONS[token] = callback
    return token


class HO_OT_HoPieAction(_HO_OPERATOR_BASE):
    """执行 Core 菜单项临时保存的回调，保留 operator 的甩动命中。"""

    bl_idname = "ho.hopie_action"
    bl_label = "HoPie 操作"
    bl_options = {"INTERNAL"}

    action: StringProperty(options={"SKIP_SAVE"}) # type: ignore

    @classmethod
    def poll(cls, context):
        return context is not None

    def execute(self, context):
        callback = _QUICK_ACTIONS.pop(getattr(self, "action", ""), None)
        if callback is None:
            return {"CANCELLED"}
        try:
            result = _resolve(callback, context)
        except Exception as error:
            try:
                self.report({"WARNING"}, "HoPie 操作执行失败: %s" % error)
            except (AttributeError, RuntimeError):
                pass
            return {"CANCELLED"}
        if isinstance(result, set):
            return result
        return {"FINISHED"}


class HO_OT_HoPieExpression(_HO_OPERATOR_BASE):
    """执行一个 HoPie 表达式按钮，供简单切换操作复用。"""

    bl_idname = "ho.hopie_expression"
    bl_label = "HoPie 表达式"
    bl_options = {"INTERNAL"}

    command: StringProperty(options={"SKIP_SAVE"}) # type: ignore

    @classmethod
    def poll(cls, context):
        return context is not None

    def invoke(self, context, event):
        global _HO_PIE_EVENT
        _HO_PIE_EVENT = event
        return self.execute(context)

    def execute(self, context):
        global _HO_PIE_EVENT
        command = getattr(self, "command", "")
        if not command:
            _HO_PIE_EVENT = None
            return {"CANCELLED"}
        namespace = {
            "C": context,
            "context": context,
            # 常用对象提供短别名，表达式不必重复书写 C.space_data/C.screen。
            "space": getattr(context, "space_data", None),
            "screen": getattr(context, "screen", None),
            "scene": getattr(context, "scene", None),
            "preferences": getattr(context, "preferences", None),
            "bpy": bpy,
            "D": getattr(bpy, "data", None) if bpy is not None else None,
            "E": _HO_PIE_EVENT,
            "A": getattr(context, "area", None),
            "O": getattr(context, "active_object", None),
            "W": getattr(context, "window", None),
            "S": getattr(context, "scene", None),
            "R": getattr(context, "region", None),
        }
        try:
            exec(compile(command, "<HoPie expression>", "exec"),
                 {"__builtins__": {}}, namespace)
        except Exception as error:
            try:
                self.report({"WARNING"}, "HoPie 表达式执行失败: %s" % error)
            except (AttributeError, RuntimeError):
                pass
            _HO_PIE_EVENT = None
            return {"CANCELLED"}
        _HO_PIE_EVENT = None
        return {"FINISHED"}


class HO_OT_HoPieNestedPie(_HO_OPERATOR_BASE):
    """把当前鼠标事件交给 popup_menu_pie，复刻 PME 的嵌套饼入口。"""

    bl_idname = "ho.hopie_nested_pie"
    bl_label = "饼:Ho大饼"
    bl_options = {"INTERNAL"}

    pie_menu_name: StringProperty(options={"SKIP_SAVE"}) # type: ignore
    invoke_mode: StringProperty(default="RELEASE", options={"SKIP_SAVE"}) # type: ignore

    @classmethod
    def poll(cls, context):
        return bool(getattr(context, "window_manager", None))

    def invoke(self, context, event):
        if bpy is None:
            return {"CANCELLED"}
        menu_cls = getattr(getattr(bpy, "types", None),
                           getattr(self, "pie_menu_name", ""), None)
        draw = getattr(menu_cls, "draw", None)
        if draw is None:
            try:
                self.report({"WARNING"}, "找不到 HoPie 子饼: %s" % self.pie_menu_name)
            except (AttributeError, RuntimeError):
                pass
            return {"CANCELLED"}

        def draw_menu(menu, draw_context):
            draw(menu, draw_context)

        try:
            context.window_manager.popup_menu_pie(
                event,
                draw_menu,
                title=getattr(menu_cls, "bl_label", self.pie_menu_name),
            )
            return {"FINISHED"}
        except (AttributeError, RuntimeError, TypeError):
            try:
                bpy.ops.wm.call_menu_pie(
                    "INVOKE_DEFAULT", name=self.pie_menu_name)
            except (AttributeError, RuntimeError, TypeError):
                return {"CANCELLED"}
            return {"FINISHED"}


HO_PIE_CORE_CLASSES = (
    HO_OT_HoPieAction,
    HO_OT_HoPieExpression,
    HO_OT_HoPieNestedPie,
)


def register_classes(classes: Any) -> None:
    """统一注册一组 Blender 类。"""
    if bpy is None:
        return
    for item in classes:
        try:
            bpy.utils.register_class(item)
        except ValueError as error:
            if "already registered" not in str(error):
                raise


def unregister_classes(classes: Any) -> None:
    """统一逆序注销一组 Blender 类。"""
    if bpy is None:
        return
    for item in reversed(classes):
        try:
            bpy.utils.unregister_class(item)
        except (RuntimeError, ValueError) as error:
            if "not registered" not in str(error):
                raise


def register_keymap(
        keymap_name: str, space_type: str, key_type: str,
        *, shift: bool = False, alt: bool = False, menu_name: Optional[str] = None,
        keymap_store: Optional[list] = None, head: bool = True,
        operator_idname: str = "wm.call_menu_pie",
        property_name: str = "name", invoke_mode: Optional[str] = None) -> None:
    """创建一个插件快捷键，并把项目保存到传入的列表。"""
    if bpy is None:
        return
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if not keyconfig:
        return
    keymap = keyconfig.keymaps.new(
        name=keymap_name,
        space_type=space_type,
        region_type="WINDOW",
    )
    item = keymap.keymap_items.new(
        operator_idname,
        type=key_type,
        value="PRESS",
        shift=shift,
        alt=alt,
        head=head,
    )
    setattr(item.properties, property_name, menu_name)
    if invoke_mode is not None:
        item.properties.invoke_mode = invoke_mode
    if keymap_store is not None:
        keymap_store.append((keymap, item))


def remove_keymaps(items: list, menu_names: Any = ()) -> None:
    """删除保存的快捷键，并清理同名旧项目。"""
    for keymap, item in list(items):
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, ValueError):
            pass
    items.clear()

    menu_names = set(menu_names)
    if not menu_names or bpy is None:
        return
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if not keyconfig:
        return
    for keymap in keyconfig.keymaps:
        for item in list(keymap.keymap_items):
            if item.idname not in {"wm.call_menu_pie", "ho.hopie_nested_pie"}:
                continue
            item_name = getattr(item.properties, "name", "")
            if not item_name:
                item_name = getattr(item.properties, "pie_menu_name", "")
            if item_name not in menu_names:
                continue
            try:
                keymap.keymap_items.remove(item)
            except (ReferenceError, ValueError):
                pass


def find_space(context: Any, space_type: Optional[str] = None) -> Any:
    """从当前上下文取得空间，必要时回退到区域的 active space。"""
    space = getattr(context, "space_data", None)
    if space is not None and (
            space_type is None or getattr(space, "type", None) == space_type):
        return space
    area = getattr(context, "area", None)
    if area is None or (
            space_type is not None and getattr(area, "type", None) != space_type):
        return None
    spaces = getattr(area, "spaces", None)
    active = getattr(spaces, "active", None)
    if active is None or (
            space_type is not None and getattr(active, "type", None) != space_type):
        return None
    return active


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


def draw_prop(layout: Any, owner: Any, path: str,
              text: Optional[Any] = None, *, icon: Any = None,
              icon_value: Any = None, context: Any = None,
              **kwargs: Any) -> Any:
    """安全地绘制一个 RNA 属性。

    `owner` 可以是对象，也可以是接收 context 的回调；`path` 支持
    `scene.tool_settings.foo` 这样的嵌套路径。裸 UILayout 没有 context
    时可显式传入 `context=`。属性不存在时直接跳过，适合跨 Blender
    版本或跨编辑器共用的饼菜单。
    """
    if context is None:
        context = getattr(layout, "context", None)
    owner = _resolve(owner, context)
    owner, prop_name = resolve_path(owner, path)
    if owner is None or prop_name is None or not hasattr(owner, prop_name):
        return None

    target = layout.item() if isinstance(layout, LayoutBuilder) else layout
    call_kwargs = dict(kwargs)
    if text is not None:
        call_kwargs["text"] = _resolve(text, context)
    call_kwargs.update(_icon_kwargs(
        _resolve(icon, context),
        _resolve(icon_value, context),
    ))
    return _safe_call(target.prop, owner, prop_name, **call_kwargs)


def ensure_layout(layout: Any, context: Any = None,
                  operator_context: str = "INVOKE_DEFAULT") -> "LayoutBuilder":
    """保证拿到 Core 的布局包装器，已包装时原样返回。"""
    if isinstance(layout, LayoutBuilder):
        return layout
    return LayoutBuilder(layout, context, operator_context)


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
    scale_x: Optional[Any] = None
    scale_y: Optional[Any] = None
    height_offset: Optional[Any] = None


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


class LayoutBuilder(_UILayoutType):
    """UILayout 的小型、可链式包装。

    Builder 不持有 Blender 数据，只持有一个 `UILayout`；因此也可以用简单的
    测试替身验证菜单结构，而不需要启动 Blender。
    """

    _BUILDER_FIELDS = frozenset({
        "layout", "context", "metadata",
    })

    def __getattr__(self, name: str) -> Any:
        """把 Core 未定义的读取转发给底层 UILayout。

        expand() 回调允许直接复用旧的 Blender 绘制函数；这些函数通常会
        读取 `alignment`、`scale_x` 或其他 UILayout 属性。只代理未知属性，
        不覆盖 LayoutBuilder 自己的链式方法。
        """
        try:
            layout = object.__getattribute__(self, "layout")
        except AttributeError:
            raise AttributeError(name) from None
        try:
            return getattr(layout, name)
        except AttributeError:
            raise AttributeError(name) from None

    def __setattr__(self, name: str, value: Any) -> None:
        """把非 Builder 状态字段写入真实 UILayout。

        Blender 的 UILayout 属性是动态 RNA 属性，不能通过类注解完整列举；
        先尝试写入底层布局，失败时再保存为普通 Python 字段，以兼容外部
        回调自己的临时状态字段。
        """
        if name.startswith("_") or name in self._BUILDER_FIELDS:
            object.__setattr__(self, name, value)
            return

        if name == "operator_context":
            object.__setattr__(self, name, value)
            try:
                layout = object.__getattribute__(self, "layout")
                setattr(layout, name, value)
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass
            return

        try:
            layout = object.__getattribute__(self, "layout")
        except AttributeError:
            object.__setattr__(self, name, value)
            return

        try:
            setattr(layout, name, value)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            object.__setattr__(self, name, value)

    def __init__(self, layout: Any, context: Any = None,
                 operator_context: str = "INVOKE_DEFAULT", *,
                 pme_item_columns: bool = False,
                 pme_item: bool = False) -> None:
        self.layout = layout
        self.context = context
        self.operator_context = operator_context
        self.metadata: Dict[str, Any] = {}
        # PME 的展开布局会为每个条目建立独立列，避免同一行中的按钮
        # 共享宽度计算。这个状态只在 expand 的子布局中传播。
        self._pme_item_columns = bool(pme_item_columns)
        self._pme_item = bool(pme_item)
        _set_layout(layout, LayoutOptions(operator_context=operator_context),
                    context, operator_context)

    def _before_draw(self) -> None:
        """给 SlotBuilder 预留的绘制前钩子；普通布局不需要处理。"""
        return None

    @property
    def raw_layout(self) -> Any:
        """需要 Blender 原生 API 时的逃生口。"""
        return self.layout

    def configure(self, **values: Any) -> "LayoutBuilder":
        """修改当前容器的 PME 风格属性并返回自身。"""
        self._before_draw()
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
        if self._pme_item_columns and not self._pme_item:
            isolated = True
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
        self._before_draw()
        child = self.layout.column(align=align)
        builder = LayoutBuilder(
            child,
            self.context,
            options.pop("operator_context", self.operator_context),
            pme_item_columns=self._pme_item_columns,
            pme_item=True,
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
        self._before_draw()
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

    def quick_operator(self, callback: Callable[..., Any],
                       text: Optional[Any] = None, *, icon: Any = None,
                       icon_value: Any = None,
                       options: Optional[ItemOptions] = None,
                       props: Optional[Mapping[str, Any]] = None,
                       **operator_props: Any) -> Any:
        """用临时回调创建真正的 operator 按钮，保留饼菜单甩动命中。"""
        if not callable(callback):
            raise TypeError("quick_operator 需要传入可调用回调")
        values = dict(props or {})
        values["action"] = _store_quick_action(callback)
        return self.operator(
            HO_OT_HoPieAction.bl_idname,
            text,
            icon=icon,
            icon_value=icon_value,
            options=options,
            props=values,
            **operator_props,
        )

    quick_op = quick_operator
    action = quick_operator

    def expression(self, command: Any, text: Optional[Any] = None, *,
                   icon: Any = None, icon_value: Any = None,
                   options: Optional[ItemOptions] = None,
                   props: Optional[Mapping[str, Any]] = None,
                   **operator_props: Any) -> Any:
        """用 Core 表达式 operator 创建可甩动触发的按钮。"""
        command = _resolve(command, self.context)
        if not isinstance(command, str):
            raise TypeError("expression 需要字符串命令")
        values = dict(props or {})
        values["command"] = command
        return self.operator(
            HO_OT_HoPieExpression.bl_idname,
            text,
            icon=icon,
            icon_value=icon_value,
            options=options,
            props=values,
            **operator_props,
        )

    expr_operator = expression
    command = expression

    def toggle_prop(self, owner: Any, path: str,
                    text: Optional[Any] = None, *, icon: Any = None,
                    icon_value: Any = None,
                    options: Optional[ItemOptions] = None,
                    **operator_props: Any) -> Any:
        """把真实 RNA 布尔属性包装成可甩动触发的 toggle operator。"""
        owner = _resolve(owner, self.context)
        target, prop_name = resolve_path(owner, path)
        if target is None or prop_name is None or not hasattr(target, prop_name):
            return None
        current = getattr(target, prop_name)
        if not isinstance(current, bool):
            return None

        def toggle(_context: Any):
            value = getattr(target, prop_name)
            if not isinstance(value, bool):
                return {"CANCELLED"}
            setattr(target, prop_name, not value)
            return {"FINISHED"}

        if "depress" not in operator_props:
            operator_props["depress"] = current
        return self.quick_operator(
            toggle,
            text,
            icon=icon,
            icon_value=icon_value,
            options=options,
            **operator_props,
        )

    def prop(self, owner: Any, path: str, text: Optional[Any] = None,
             *, icon: Any = None, icon_value: Any = None,
             options: Optional[ItemOptions] = None, expand: Any = None,
             slider: Any = None, toggle: Any = None, icon_only: Any = None,
             index: Any = None, emboss: Any = None, **kwargs: Any) -> Any:
        """读取真实 RNA 属性并绘制；属性路径可以是 `foo.bar`。"""
        self._before_draw()
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

    def menu(self, menu_name: Union[str, Callable[..., Any]], text: Optional[Any] = None,
             *, icon: Any = None, icon_value: Any = None,
             options: Optional[ItemOptions] = None,
             use_mouse_over_open: Any = None,
             expand: Optional[Callable[..., Any]] = None,
             frame: bool = False, width: Optional[Any] = None,
             height: Optional[Any] = None,
             scale_x: Optional[Any] = None,
             scale_y: Optional[Any] = None,
             height_offset: Optional[Any] = None,
             settings: Optional[DialogSettings] = None,
             **item_values: Any) -> Any:
        """添加普通下拉菜单；它不会创建新的饼。"""
        self._before_draw()
        if callable(menu_name) and not isinstance(menu_name, type) and \
                not hasattr(menu_name, "draw"):
            if expand not in (None, True):
                raise ValueError("menu 的可调用参数和 expand 只能二选一")
            return self.expand(
                menu_name,
                frame=frame,
                width=width,
                height=height,
                scale_x=scale_x,
                scale_y=scale_y,
                height_offset=height_offset,
                settings=settings,
            )
        if expand is not None:
            if expand is True:
                return self.expand_menu(
                    menu_name,
                    frame=frame,
                    width=width,
                    height=height,
                    scale_x=scale_x,
                    scale_y=scale_y,
                    height_offset=height_offset,
                    settings=settings,
                )
            if not callable(expand):
                raise ValueError("menu(expand=...) 需要传入绘制回调或 True")
            # PME 的 @ 菜单标记会把内容直接画进当前槽位，不额外生成一个菜单按钮。
            return self.expand(
                expand,
                frame=frame,
                width=width,
                height=height,
                scale_x=scale_x,
                scale_y=scale_y,
                height_offset=height_offset,
                settings=settings,
            )
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
            operator_idname: Optional[str] = None,
            **item_values: Any) -> Any:
        """添加一个嵌套饼入口；绘制目标仍由 Blender 菜单注册系统负责。"""
        self._before_draw()
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
        nested_operator = operator_idname
        if nested_operator is None:
            owner = getattr(self, "_pie", None)
            nested_operator = getattr(
                owner, "nested_operator_idname", "wm.call_menu_pie")
        button = _safe_call(target.operator, nested_operator, **kwargs)
        try:
            property_name = (
                "pie_menu_name" if nested_operator != "wm.call_menu_pie" else "name"
            )
            setattr(button, property_name, menu_name)
            if invoke_mode is not None:
                button.invoke_mode = invoke_mode
            elif nested_operator != "wm.call_menu_pie":
                # PME 在 PMENU -> PMENU 时使用 SUB，保留子饼的事件语义。
                button.invoke_mode = "SUB"
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
        self._before_draw()
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
        self._before_draw()
        kwargs: Dict[str, Any] = {"text": _resolve(text, self.context)}
        kwargs.update(_icon_kwargs(
            _resolve(icon, self.context),
            _resolve(icon_value, self.context),
        ))
        return _safe_call(self.layout.label, **kwargs)

    def separator(self, factor: Optional[Any] = None) -> Any:
        self._before_draw()
        if factor is None:
            return self.layout.separator()
        try:
            return self.layout.separator(factor=_resolve(factor, self.context))
        except TypeError:
            return self.layout.separator()

    sep = separator

    def spacer(self, *, hsep: str = "NONE", factor: Optional[Any] = None) -> Any:
        """PME spacer 的轻量版本；COLUMN/ALIGNER 等标记保存在 metadata。"""
        self._before_draw()
        self.metadata.setdefault("spacers", []).append({"hsep": hsep, "factor": factor})
        factors = {"NONE": 1.0, "SPACER": 1.0, "COLUMN": 1.0,
                   "ALIGNER": 1.0, "LARGE": 3.0, "LARGER": 5.0}
        return self.separator(factor if factor is not None else factors.get(hsep, 1.0))

    def row(self, *, align: bool = True, options: Optional[LayoutOptions] = None,
            size: Optional[str] = None, vspacer: Optional[Any] = None,
            fixed_col: bool = False, fixed_but: bool = False,
            **layout_options: Any) -> "LayoutBuilder":
        """创建一行，并保留 PME 的 size/vspacer/fixed 配置。"""
        self._before_draw()
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
        builder = LayoutBuilder(
            child,
            self.context,
            merged.operator_context or self.operator_context,
            pme_item_columns=self._pme_item_columns,
        )
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
        self._before_draw()
        child = self.layout.column(align=align)
        merged = replace(options) if options is not None else LayoutOptions()
        for key, value in layout_options.items():
            if key in LayoutOptions.__dataclass_fields__:
                setattr(merged, key, value)
        return LayoutBuilder(
            child,
            self.context,
            merged.operator_context or self.operator_context,
            pme_item_columns=self._pme_item_columns,
        ).configure(
                                 **{key: value for key, value in vars(merged).items()
                                    if value is not None}
                             )

    def box(self, *, options: Optional[LayoutOptions] = None,
            **layout_options: Any) -> "LayoutBuilder":
        self._before_draw()
        child = self.layout.box()
        merged = replace(options) if options is not None else LayoutOptions()
        for key, value in layout_options.items():
            if key in LayoutOptions.__dataclass_fields__:
                setattr(merged, key, value)
        return LayoutBuilder(
            child,
            self.context,
            merged.operator_context or self.operator_context,
            pme_item_columns=self._pme_item_columns,
        ).configure(
                                 **{key: value for key, value in vars(merged).items()
                                    if value is not None}
                             )

    def split(self, factor: Optional[Any] = None,
              *, align: bool = False) -> "LayoutBuilder":
        self._before_draw()
        kwargs = {"align": align}
        if factor is not None:
            kwargs["factor"] = _resolve(factor, self.context)
        return LayoutBuilder(
            self.layout.split(**kwargs),
            self.context,
            self.operator_context,
            pme_item_columns=self._pme_item_columns,
        )

    def expand(self, draw: Callable[..., Any], *, frame: bool = False,
               width: Optional[Any] = None, height: Optional[Any] = None,
               scale_x: Optional[Any] = None, scale_y: Optional[Any] = None,
               height_offset: Optional[Any] = None,
               item_columns: bool = True,
               settings: Optional[DialogSettings] = None) -> "LayoutBuilder":
        """在当前槽位直接绘制回调内容，不调用 `layout.menu()`。

        回调签名支持 `draw(layout)` 或 `draw(layout, context)`；这里的 layout 是
        `LayoutBuilder`，因此可以继续链式调用 `row/prop/operator`。
        `width`/`height` 分别是 `scale_x`/`scale_y` 的直观别名，用于调整
        展开面板的横向和纵向比例。
        `item_columns` 默认启用 PME 的逐项列布局；旧的面板绘制函数无需改写，
        也能避免同一行中的按钮被 Blender 的宽度计算吞掉。
        `height_offset` 只控制垂直方向的留白，用于调整内容和饼中心的距离；
        正数让内容向上，负数让内容向下，不会占用下一个饼槽位。
        """
        self._before_draw()
        target = self.layout.box() if frame else self.layout
        target = target.column(align=True)
        builder = LayoutBuilder(
            target,
            self.context,
            self.operator_context,
            pme_item_columns=item_columns,
        )
        dialog = settings or DialogSettings(box=frame)
        if scale_x is None:
            scale_x = width
        if scale_x is None:
            scale_x = dialog.scale_x
        if scale_y is None:
            scale_y = height
        if scale_y is None:
            scale_y = dialog.scale_y
        if height_offset is None:
            height_offset = dialog.height_offset
        layout_scale = {}
        if scale_x is not None:
            layout_scale["scale_x"] = scale_x
        if scale_y is not None:
            layout_scale["scale_y"] = scale_y
        if layout_scale:
            builder.configure(**layout_scale)
        leading_offset = None
        trailing_offset = None
        if height_offset is not None:
            height_value = _resolve(height_offset, self.context)
            if height_value not in (None, 0):
                try:
                    if height_value < 0:
                        # separator 的因子不能用负数，负数改为内容前的留白。
                        leading_offset = -height_value
                    else:
                        # 内容后的留白会把垂直布局中的内容向上推。
                        trailing_offset = height_value
                except (TypeError, ValueError):
                    builder.separator(height_value)
        if leading_offset is not None:
            builder.separator(leading_offset)
        builder.metadata["dialog"] = dialog
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
        if trailing_offset is not None:
            builder.separator(trailing_offset)
        return builder

    expanded = expand
    def expand_menu(self, menu: Union[str, type, Callable[..., Any]], *,
                    frame: bool = False, width: Optional[Any] = None,
                    height: Optional[Any] = None,
                    scale_x: Optional[Any] = None, scale_y: Optional[Any] = None,
                    height_offset: Optional[Any] = None,
                    item_columns: bool = True,
                    settings: Optional[DialogSettings] = None) -> "LayoutBuilder":
        """把已注册 Menu 类直接绘制到当前面板，支持递归展开子 Menu。"""
        if callable(menu) and not isinstance(menu, type) and not hasattr(menu, "draw"):
            return self.expand(
                menu,
                frame=frame,
                width=width,
                height=height,
                scale_x=scale_x,
                scale_y=scale_y,
                height_offset=height_offset,
                item_columns=item_columns,
                settings=settings,
            )

        menu_cls = menu
        if isinstance(menu, str):
            try:
                import bpy
                menu_cls = getattr(bpy.types, menu, None)
            except ImportError:
                menu_cls = None
        draw = getattr(menu_cls, "draw", None)
        if draw is None:
            raise ValueError("找不到可展开的 Menu: %s" % menu)

        def draw_registered_menu(layout: "LayoutBuilder", context: Any) -> None:
            # Blender 的 Menu 实例不能可靠地由 Python 手动构造，用轻量代理提供
            # draw 方法实际需要的 layout 和类属性即可。
            class MenuProxy(SimpleNamespace):
                def __getattr__(self, name: str) -> Any:
                    return getattr(menu_cls, name)

            proxy = MenuProxy(
                # 传 Builder 而不是裸 UILayout，让子 Menu 也能继续调用 expand=True。
                layout=layout,
                bl_idname=getattr(menu_cls, "bl_idname", ""),
                bl_label=getattr(menu_cls, "bl_label", ""),
            )
            draw(proxy, context)

        return self.expand(
            draw_registered_menu,
            frame=frame,
            width=width,
            height=height,
            scale_x=scale_x,
            scale_y=scale_y,
            height_offset=height_offset,
            item_columns=item_columns,
            settings=settings,
        )

    expanded_menu = expand_menu
    expand_panel = expand
    panel = expand
    draw = expand


class SlotBuilder(LayoutBuilder):
    """一个有名字的饼槽位。"""

    _BUILDER_FIELDS = LayoutBuilder._BUILDER_FIELDS | {
        "name", "index",
    }

    def __init__(self, layout: Any, context: Any, name: str, index: int,
                 operator_context: str = "INVOKE_DEFAULT",
                 pie: Optional["HoPie"] = None) -> None:
        super().__init__(layout, context, operator_context)
        self.name = name
        self.index = index
        self._pie = pie
        self._activated = False

    def _before_draw(self) -> None:
        if self._pie is None or self._activated:
            return
        self._pie._activate_slot(self)
        self._activated = True


class HoPie(LayoutBuilder):
    """HoPie 菜单的入口对象。

    默认会从传入的 `self.layout` 创建 `menu_pie()`；如果调用方已经拿到了
    `layout.menu_pie()`，传 `menu_pie=False` 即可。槽位不会预先包成 column，
    而是在第一次绘制时直接写入饼的根布局，从而保留 Blender 原生的甩动命中区域。
    槽位按 PME 顺序激活，写完后调用 `finish()` 补齐空方向；也可以使用 with 语法。
    中心的 `top_center`/`bottom_center` 会在第一次使用时按 PME 的间隔规则追加。
    """

    _BUILDER_FIELDS = LayoutBuilder._BUILDER_FIELDS | {
        "config", "settings", "dialog", "nested_operator_idname",
    }

    SLOT_NAMES: Tuple[str, ...] = (
        "left", "right", "bottom", "top",
        "top_left", "top_right", "bottom_left", "bottom_right",
    )
    EXTRA_SLOT_NAMES: Tuple[str, ...] = ("top_center", "bottom_center")

    def __init__(self, layout: Any, context: Any = None, *,
                 menu_pie: bool = True,
                 config: Optional[HoPieConfig] = None,
                 settings: Optional[PieSettings] = None,
                 nested_operator_idname: str = "ho.hopie_nested_pie") -> None:
        if menu_pie and hasattr(layout, "menu_pie"):
            layout = layout.menu_pie()
        super().__init__(layout, context, "INVOKE_DEFAULT")
        self.config = config or HoPieConfig(pie=settings or PieSettings())
        self.nested_operator_idname = nested_operator_idname
        # 常用配置提供直接入口，完整配置仍可从 `pie.config` 读取。
        self.settings = self.config.pie
        self.dialog = self.config.dialog
        self._slots: Dict[str, SlotBuilder] = {}
        self._next_slot = 0
        self._finished = False
        self._center_started = False
        for index, name in enumerate(self.SLOT_NAMES):
            self._slots[name] = SlotBuilder(
                layout, context, name, index, self.operator_context, self,
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
            self._centers[name] = SlotBuilder(
                self.layout, self.context, name, index,
                self.operator_context, self,
            )
        return self._centers[name]

    def _activate_slot(self, slot: SlotBuilder) -> None:
        """按 PME 的顺序把槽位落到 menu_pie 根布局。"""
        if self._finished:
            raise RuntimeError("HoPie 已经 finish，不能继续添加菜单项")

        if slot.index < self._next_slot:
            raise RuntimeError(
                "HoPie 槽位必须按 PME 顺序绘制，当前槽位已经越过：%s" % slot.name
            )

        if slot.index < 8:
            while self._next_slot < slot.index:
                self.layout.separator()
                self._next_slot += 1
            self._next_slot = slot.index + 1
            return

        # 中心项存在时，PME 会先补两段间隔，再绘制中心最顶/最底。
        if not self._center_started:
            while self._next_slot < 8:
                self.layout.separator()
                self._next_slot += 1
            self.layout.separator()
            self.layout.separator()
            self._center_started = True
            self._next_slot = 9

            top = self._centers.get("top_center")
            if top is not None:
                top.layout = self.layout.column(align=True)
                top._activated = True

        if slot.index == 9 and self._next_slot == 9:
            self.layout.separator()
            slot.layout = self.layout.column(align=True)
            self._next_slot = 10

    def finish(self) -> "HoPie":
        """结束饼的声明并补齐未使用的方向槽位。"""
        if self._finished:
            return self
        if not self._center_started:
            while self._next_slot < 8:
                self.layout.separator()
                self._next_slot += 1
        self._finished = True
        return self

    finalize = finish

    def __enter__(self) -> "HoPie":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.finish()

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
    "HO_OT_HoPieAction",
    "HO_OT_HoPieExpression",
    "HO_OT_HoPieNestedPie",
    "HO_PIE_CORE_CLASSES",
    "HoPie",
    "HoPieConfig",
    "ItemOptions",
    "LayoutBuilder",
    "LayoutOptions",
    "PieBuilder",
    "PieSettings",
    "SlotBuilder",
    "draw_prop",
    "ensure_layout",
    "find_space",
    "register_classes",
    "register_keymap",
    "remove_keymaps",
    "unregister_classes",
    "resolve_path",
]
