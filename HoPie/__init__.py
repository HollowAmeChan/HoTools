"""HoPie public API."""

from . import AlignPie, CursorPie, DeleteMergePie, HoMainPie, SelectionModePie
from . import _Register as _register_module
from ._Core import (
    DialogSettings,
    HO_PIE_CORE_CLASSES,
    HoPie,
    HoPieConfig,
    ItemOptions,
    LayoutBuilder,
    LayoutOptions,
    PieBuilder,
    PieSettings,
    SlotBuilder,
    draw_prop,
    ensure_layout,
    find_space,
)
from ._Register import (
    align_pie_keymaps,
    cursor_pie_keymaps,
    delete_merge_pie_keymaps,
    main_pie_keymaps,
    preference_keymaps,
    selection_mode_pie_keymaps,
    set_pie_enabled,
    register,
    unregister,
)


def __getattr__(name):
    if name in {
        '_align_pie_enabled',
        '_cursor_pie_enabled',
        '_selection_mode_pie_enabled',
        '_delete_merge_pie_enabled',
        '_main_pie_enabled',
        '_core_registered',
    }:
        return getattr(_register_module, name)
    raise AttributeError(name)


__all__ = [
    'AlignPie',
    'CursorPie',
    'DeleteMergePie',
    'HoMainPie',
    'SelectionModePie',
    'DialogSettings',
    'HO_PIE_CORE_CLASSES',
    'HoPie',
    'HoPieConfig',
    'ItemOptions',
    'LayoutBuilder',
    'LayoutOptions',
    'PieBuilder',
    'PieSettings',
    'SlotBuilder',
    'draw_prop',
    'ensure_layout',
    'find_space',
    'align_pie_keymaps',
    'cursor_pie_keymaps',
    'delete_merge_pie_keymaps',
    'main_pie_keymaps',
    'selection_mode_pie_keymaps',
    'preference_keymaps',
    'set_pie_enabled',
    'register',
    'unregister',
]
