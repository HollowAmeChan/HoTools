import bpy
from . import align_pie, cursor_pie, delete_merge_pie, selection_mode_pie


align_pie_keymaps = []
cursor_pie_keymaps = []
selection_mode_pie_keymaps = []
delete_merge_pie_keymaps = []
_align_pie_enabled = False
_cursor_pie_enabled = False
_selection_mode_pie_enabled = False
_delete_merge_pie_enabled = False


def reg_props():
    align_pie.register_props()


def ureg_props():
    align_pie.unregister_props()


def _register_keymap(
        keymap_name, space_type, key_type, shift=False, alt=False,
        menu_name=None, keymap_store=None, head=True):
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if not keyconfig:
        return
    keymap = keyconfig.keymaps.new(
        name=keymap_name,
        space_type=space_type,
        region_type='WINDOW',
    )
    item = keymap.keymap_items.new(
        'wm.call_menu_pie',
        type=key_type,
        value='PRESS',
        shift=shift,
        alt=alt,
        head=head,
    )
    item.properties.name = menu_name
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
            if item.idname != 'wm.call_menu_pie':
                continue
            if getattr(item.properties, 'name', '') not in menu_names:
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


def preference_keymaps():
    return [
        *align_pie_keymaps,
        *cursor_pie_keymaps,
        *selection_mode_pie_keymaps,
        *delete_merge_pie_keymaps,
    ]


def register():
    reg_props()


def unregister():
    set_delete_merge_pie_enabled(False)
    set_selection_mode_pie_enabled(False)
    set_cursor_pie_enabled(False)
    set_align_pie_enabled(False)
    ureg_props()
