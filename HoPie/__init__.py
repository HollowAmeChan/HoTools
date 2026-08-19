import bpy
from bpy.props import StringProperty
from . import HoMainPie, align_pie, cursor_pie, delete_merge_pie, selection_mode_pie
from .HoPieCore import (
    DialogSettings,
    HoPie,
    HoPieConfig,
    ItemOptions,
    LayoutBuilder,
    LayoutOptions,
    PieSettings,
)


class HO_OT_HoPieNestedPie(bpy.types.Operator):
    """把当前鼠标事件交给 Blender 的 popup_menu_pie，复刻 PME 的嵌套饼入口。"""

    bl_idname = "ho.hopie_nested_pie"
    bl_label = "HoPie 嵌套饼"
    bl_options = {"INTERNAL"}

    pie_menu_name: StringProperty(options={"SKIP_SAVE"})
    invoke_mode: StringProperty(default="RELEASE", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(getattr(context, "window_manager", None))

    def invoke(self, context, event):
        menu_cls = getattr(bpy.types, self.pie_menu_name, None)
        draw = getattr(menu_cls, "draw", None)
        if draw is None:
            self.report({"WARNING"}, "找不到 HoPie 子饼: %s" % self.pie_menu_name)
            return {"CANCELLED"}

        def draw_menu(menu, draw_context):
            draw(menu, draw_context)

        try:
            # popup_menu_pie 使用当前事件的鼠标位置和方向，保留甩动命中。
            context.window_manager.popup_menu_pie(
                event,
                draw_menu,
                title=getattr(menu_cls, "bl_label", self.pie_menu_name),
            )
            return {"FINISHED"}
        except (AttributeError, RuntimeError, TypeError):
            # 非标准窗口上下文退回 Blender 原生调用，至少保证菜单可用。
            try:
                bpy.ops.wm.call_menu_pie(
                    "INVOKE_DEFAULT", name=self.pie_menu_name)
            except (AttributeError, RuntimeError, TypeError):
                return {"CANCELLED"}
            return {"FINISHED"}


_HO_PIE_CORE_CLASSES = (HO_OT_HoPieNestedPie,)


align_pie_keymaps = []
cursor_pie_keymaps = []
selection_mode_pie_keymaps = []
delete_merge_pie_keymaps = []
main_pie_keymaps = []
_align_pie_enabled = False
_cursor_pie_enabled = False
_selection_mode_pie_enabled = False
_delete_merge_pie_enabled = False
_main_pie_enabled = False


def reg_props():
    align_pie.register_props()


def ureg_props():
    align_pie.unregister_props()


def _register_keymap(
        keymap_name, space_type, key_type, shift=False, alt=False,
        menu_name=None, keymap_store=None, head=True,
        operator_idname="wm.call_menu_pie", property_name="name",
        invoke_mode=None):
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if not keyconfig:
        return
    keymap = keyconfig.keymaps.new(
        name=keymap_name,
        space_type=space_type,
        region_type='WINDOW',
    )
    item = keymap.keymap_items.new(
        operator_idname,
        type=key_type,
        value='PRESS',
        shift=shift,
        alt=alt,
        head=head,
    )
    setattr(item.properties, property_name, menu_name)
    if invoke_mode is not None:
        item.properties.invoke_mode = invoke_mode
    keymap_store.append((keymap, item))


def _remove_keymaps(items, menu_names=()):
    for keymap, item in list(items):
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, ValueError):
            pass
    items.clear()

    menu_names = set(menu_names)
    if not menu_names:
        return
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if not keyconfig:
        return
    for keymap in keyconfig.keymaps:
        for item in list(keymap.keymap_items):
            if item.idname not in {'wm.call_menu_pie', 'ho.hopie_nested_pie'}:
                continue
            item_name = getattr(item.properties, 'name', '')
            if not item_name:
                item_name = getattr(item.properties, 'pie_menu_name', '')
            if item_name not in menu_names:
                continue
            try:
                keymap.keymap_items.remove(item)
            except (ReferenceError, ValueError):
                pass


def _register_classes(classes):
    for item in classes:
        try:
            bpy.utils.register_class(item)
        except ValueError as error:
            if 'already registered' not in str(error):
                raise


def _unregister_classes(classes):
    for item in reversed(classes):
        try:
            bpy.utils.unregister_class(item)
        except (RuntimeError, ValueError) as error:
            if 'not registered' not in str(error):
                raise


def set_align_pie_enabled(enabled):
    global _align_pie_enabled
    enabled = bool(enabled)
    if enabled:
        if _align_pie_enabled:
            return
        _remove_keymaps(
            align_pie_keymaps,
            {'HO_MT_align_pie', 'HO_MT_uv_align_pie'},
        )
        _register_classes(align_pie.ALIGN_PIE_CLASSES)
        _register_keymap(
            'Mesh', 'EMPTY', 'A', alt=True,
            menu_name='HO_MT_align_pie', keymap_store=align_pie_keymaps,
        )
        _register_keymap(
            'UV Editor', 'EMPTY', 'A', alt=True,
            menu_name='HO_MT_uv_align_pie', keymap_store=align_pie_keymaps,
        )
        _register_keymap(
            'Curve', 'EMPTY', 'A', alt=True,
            menu_name='HO_MT_align_pie', keymap_store=align_pie_keymaps,
        )
    else:
        _remove_keymaps(
            align_pie_keymaps,
            {'HO_MT_align_pie', 'HO_MT_uv_align_pie'},
        )
        if _align_pie_enabled:
            _unregister_classes(align_pie.ALIGN_PIE_CLASSES)
    _align_pie_enabled = enabled


def set_cursor_pie_enabled(enabled):
    global _cursor_pie_enabled
    enabled = bool(enabled)
    if enabled:
        if _cursor_pie_enabled:
            return
        _remove_keymaps(cursor_pie_keymaps, {'HO_MT_cursor_pie'})
        _register_classes(cursor_pie.CURSOR_PIE_CLASSES)
        _register_keymap(
            '3D View Generic', 'VIEW_3D', 'S', shift=True,
            menu_name='HO_MT_cursor_pie', keymap_store=cursor_pie_keymaps,
        )
    else:
        _remove_keymaps(cursor_pie_keymaps, {'HO_MT_cursor_pie'})
        if _cursor_pie_enabled:
            _unregister_classes(cursor_pie.CURSOR_PIE_CLASSES)
    _cursor_pie_enabled = enabled


def set_selection_mode_pie_enabled(enabled):
    global _selection_mode_pie_enabled
    enabled = bool(enabled)
    if enabled:
        if _selection_mode_pie_enabled:
            return
        _remove_keymaps(
            selection_mode_pie_keymaps,
            {'HO_MT_selection_mode_pie'},
        )
        _register_classes(selection_mode_pie.SELECTION_MODE_PIE_CLASSES)
        _register_keymap(
            '3D View Generic', 'VIEW_3D', 'W', head=True,
            menu_name='HO_MT_selection_mode_pie',
            keymap_store=selection_mode_pie_keymaps,
        )
    else:
        _remove_keymaps(
            selection_mode_pie_keymaps,
            {'HO_MT_selection_mode_pie'},
        )
        if _selection_mode_pie_enabled:
            _unregister_classes(selection_mode_pie.SELECTION_MODE_PIE_CLASSES)
    _selection_mode_pie_enabled = enabled


def set_delete_merge_pie_enabled(enabled):
    global _delete_merge_pie_enabled
    enabled = bool(enabled)
    if enabled:
        if _delete_merge_pie_enabled:
            return
        _remove_keymaps(
            delete_merge_pie_keymaps,
            {'HO_MT_delete_merge_pie'},
        )
        _register_classes(delete_merge_pie.DELETE_MERGE_PIE_CLASSES)
        _register_keymap(
            'Mesh', 'EMPTY', 'X', head=True,
            menu_name='HO_MT_delete_merge_pie',
            keymap_store=delete_merge_pie_keymaps,
        )
    else:
        _remove_keymaps(
            delete_merge_pie_keymaps,
            {'HO_MT_delete_merge_pie'},
        )
        if _delete_merge_pie_enabled:
            _unregister_classes(delete_merge_pie.DELETE_MERGE_PIE_CLASSES)
    _delete_merge_pie_enabled = enabled


def set_main_pie_enabled(enabled):
    global _main_pie_enabled
    enabled = bool(enabled)
    if enabled:
        if _main_pie_enabled:
            return
        _remove_keymaps(main_pie_keymaps, {'HO_MT_HoMainPie'})
        _register_classes(_HO_PIE_CORE_CLASSES)
        _register_classes(HoMainPie.HO_MAIN_PIE_CLASSES)
        _register_keymap(
            'Mesh', 'EMPTY', 'SPACE', head=True,
            menu_name='HO_MT_HoMainPie', keymap_store=main_pie_keymaps,
            operator_idname='ho.hopie_nested_pie',
            property_name='pie_menu_name', invoke_mode='HOTKEY',
        )
    else:
        _remove_keymaps(main_pie_keymaps, {'HO_MT_HoMainPie'})
        if _main_pie_enabled:
            _unregister_classes(HoMainPie.HO_MAIN_PIE_CLASSES)
            _unregister_classes(_HO_PIE_CORE_CLASSES)
    _main_pie_enabled = enabled


def preference_keymaps():
    return [
        *align_pie_keymaps,
        *cursor_pie_keymaps,
        *selection_mode_pie_keymaps,
        *delete_merge_pie_keymaps,
        *main_pie_keymaps,
    ]


def register():
    reg_props()


def unregister():
    set_main_pie_enabled(False)
    set_delete_merge_pie_enabled(False)
    set_selection_mode_pie_enabled(False)
    set_cursor_pie_enabled(False)
    set_align_pie_enabled(False)
    ureg_props()
