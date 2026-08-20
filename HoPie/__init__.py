from . import HoMainPie, align_pie, cursor_pie, delete_merge_pie, selection_mode_pie
from .HoPieCore import (
    DialogSettings,
    HO_PIE_CORE_CLASSES,
    HoPie,
    HoPieConfig,
    ItemOptions,
    LayoutBuilder,
    LayoutOptions,
    PieSettings,
    draw_prop,
    ensure_layout,
    find_space,
    register_classes as _register_classes,
    register_keymap as _register_keymap,
    remove_keymaps as _remove_keymaps,
    unregister_classes as _unregister_classes,
)


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
_main_pie_edit_mode_only = True
_core_registered = False


def reg_props():
    align_pie.register_props()


def ureg_props():
    align_pie.unregister_props()


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
        _register_classes(HoMainPie.HO_MAIN_PIE_CLASSES)
        _register_main_pie_keymap()
    else:
        _remove_keymaps(main_pie_keymaps, {'HO_MT_HoMainPie'})
        if _main_pie_enabled:
            _unregister_classes(HoMainPie.HO_MAIN_PIE_CLASSES)
    _main_pie_enabled = enabled


def _register_main_pie_keymap():
    """按偏好设置把主饼绑定到编辑网格或整个三维视图。"""
    if _main_pie_edit_mode_only:
        keymap_name, space_type = 'Mesh', 'EMPTY'
    else:
        keymap_name, space_type = '3D View Generic', 'VIEW_3D'
    _register_keymap(
        keymap_name, space_type, 'SPACE', head=True,
        menu_name='HO_MT_HoMainPie', keymap_store=main_pie_keymaps,
        operator_idname='ho.hopie_nested_pie',
        property_name='pie_menu_name', invoke_mode='HOTKEY',
    )
    _register_keymap(
        'UV Editor', 'EMPTY', 'SPACE', head=True,
        menu_name='HO_MT_HoMainPie', keymap_store=main_pie_keymaps,
        operator_idname='ho.hopie_nested_pie',
        property_name='pie_menu_name', invoke_mode='HOTKEY',
    )


def set_main_pie_edit_mode_only(only_edit_mode):
    """切换主饼是否只在编辑网格键位表中生效。"""
    global _main_pie_edit_mode_only
    only_edit_mode = bool(only_edit_mode)
    if _main_pie_edit_mode_only == only_edit_mode:
        return
    _main_pie_edit_mode_only = only_edit_mode
    if _main_pie_enabled:
        _remove_keymaps(main_pie_keymaps, {'HO_MT_HoMainPie'})
        _register_main_pie_keymap()


def preference_keymaps():
    return [
        *align_pie_keymaps,
        *cursor_pie_keymaps,
        *selection_mode_pie_keymaps,
        *delete_merge_pie_keymaps,
        *main_pie_keymaps,
    ]


def register():
    global _core_registered
    reg_props()
    if not _core_registered:
        _register_classes(HO_PIE_CORE_CLASSES)
        _core_registered = True


def unregister():
    global _core_registered
    set_main_pie_enabled(False)
    set_delete_merge_pie_enabled(False)
    set_selection_mode_pie_enabled(False)
    set_cursor_pie_enabled(False)
    set_align_pie_enabled(False)
    if _core_registered:
        _unregister_classes(HO_PIE_CORE_CLASSES)
        _core_registered = False
    ureg_props()
