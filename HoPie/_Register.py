"""Central registration and feature-switch management for HoPie."""

from dataclasses import dataclass
from typing import Any, Callable, Optional

try:
    import bpy
except ImportError:
    bpy = None

from . import (
    AlignPie,
    ArmatureModPie,
    CursorPie,
    DeleteMergePie,
    HoMainPie,
    SelectionModePie,
)
from ._Core import HO_PIE_CORE_CLASSES


def register_classes(classes: Any) -> None:
    if bpy is None:
        return
    for item in classes:
        try:
            bpy.utils.register_class(item)
        except ValueError as error:
            if "already registered" not in str(error):
                raise


def unregister_classes(classes: Any) -> None:
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
        *, shift: bool = False, alt: bool = False,
        menu_name: Optional[str] = None, keymap_store: Optional[list] = None,
        head: bool = True, operator_idname: str = "wm.call_menu_pie",
        property_name: str = "name", invoke_mode: Optional[str] = None) -> None:
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
            if item.idname not in {
                    "wm.call_menu_pie",
                    "ho.hopie_nested_pie",
                    "ho.armature_mode_pie",
            }:
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


align_pie_keymaps = []
cursor_pie_keymaps = []
selection_mode_pie_keymaps = []
delete_merge_pie_keymaps = []
main_pie_keymaps = []
armature_mode_pie_keymaps = []
# Short-name alias kept for callers that use the module's ArmatureModPie name.
armature_mod_pie_keymaps = armature_mode_pie_keymaps

_align_pie_enabled = False
_cursor_pie_enabled = False
_selection_mode_pie_enabled = False
_delete_merge_pie_enabled = False
_main_pie_enabled = False
_armature_mode_pie_enabled = False
# Alias for the ArmatureModPie feature name.
_armature_mod_pie_enabled = False
_core_registered = False


@dataclass(frozen=True)
class _PieSpec:
    state_name: str
    classes: tuple
    keymap_store: list
    menu_names: tuple[str, ...]
    register_keymaps: Callable[[list], None]


def _register_align_keymaps(store):
    register_keymap(
        'Mesh', 'EMPTY', 'A', alt=True,
        menu_name='HO_MT_align_pie', keymap_store=store,
    )
    register_keymap(
        'UV Editor', 'EMPTY', 'A', alt=True,
        menu_name='HO_MT_uv_align_pie', keymap_store=store,
    )
    register_keymap(
        'Curve', 'EMPTY', 'A', alt=True,
        menu_name='HO_MT_align_pie', keymap_store=store,
    )


def _register_cursor_keymaps(store):
    register_keymap(
        '3D View Generic', 'VIEW_3D', 'S', shift=True,
        menu_name='HO_MT_cursor_pie', keymap_store=store,
    )


def _register_selection_mode_keymaps(store):
    register_keymap(
        '3D View Generic', 'VIEW_3D', 'W',
        menu_name='HO_MT_selection_mode_pie', keymap_store=store,
    )


def _register_delete_merge_keymaps(store):
    register_keymap(
        'Mesh', 'EMPTY', 'X',
        menu_name='HO_MT_delete_merge_pie', keymap_store=store,
    )


def _register_main_keymaps(store):
    register_keymap(
        '3D View Generic', 'VIEW_3D', 'SPACE',
        menu_name='HO_MT_HoMainPie', keymap_store=store,
        operator_idname='ho.hopie_nested_pie',
        property_name='pie_menu_name', invoke_mode='HOTKEY',
    )
    register_keymap(
        'UV Editor', 'EMPTY', 'SPACE',
        menu_name='HO_MT_HoMainPie', keymap_store=store,
        operator_idname='ho.hopie_nested_pie',
        property_name='pie_menu_name', invoke_mode='HOTKEY',
    )


def _register_armature_mode_keymaps(store):
    for keymap_name in ('Object Mode', 'Armature', 'Pose'):
        register_keymap(
            keymap_name, 'EMPTY', 'TAB',
            menu_name='HO_MT_armature_mode_pie', keymap_store=store,
            head=True,
            operator_idname='ho.armature_mode_pie',
            property_name='pie_menu_name',
        )


_PIE_SPECS = {
    'align': _PieSpec(
        '_align_pie_enabled',
        AlignPie.ALIGN_PIE_CLASSES,
        align_pie_keymaps,
        ('HO_MT_align_pie', 'HO_MT_uv_align_pie'),
        _register_align_keymaps,
    ),
    'cursor': _PieSpec(
        '_cursor_pie_enabled',
        CursorPie.CURSOR_PIE_CLASSES,
        cursor_pie_keymaps,
        ('HO_MT_cursor_pie',),
        _register_cursor_keymaps,
    ),
    'selection_mode': _PieSpec(
        '_selection_mode_pie_enabled',
        SelectionModePie.SELECTION_MODE_PIE_CLASSES,
        selection_mode_pie_keymaps,
        ('HO_MT_selection_mode_pie',),
        _register_selection_mode_keymaps,
    ),
    'delete_merge': _PieSpec(
        '_delete_merge_pie_enabled',
        DeleteMergePie.DELETE_MERGE_PIE_CLASSES,
        delete_merge_pie_keymaps,
        ('HO_MT_delete_merge_pie',),
        _register_delete_merge_keymaps,
    ),
    'main': _PieSpec(
        '_main_pie_enabled',
        HoMainPie.HO_MAIN_PIE_CLASSES,
        main_pie_keymaps,
        ('HO_MT_HoMainPie',),
        _register_main_keymaps,
    ),
    'armature_mode': _PieSpec(
        '_armature_mode_pie_enabled',
        ArmatureModPie.ARMATURE_MODE_PIE_CLASSES,
        armature_mode_pie_keymaps,
        ('HO_MT_armature_mode_pie',),
        _register_armature_mode_keymaps,
    ),
}


def set_pie_enabled(name: str, enabled: bool) -> None:
    if name == 'armature_mod':
        name = 'armature_mode'
    spec = _PIE_SPECS[name]
    enabled = bool(enabled)
    current = bool(globals()[spec.state_name])
    if enabled:
        if current:
            return
        remove_keymaps(spec.keymap_store, spec.menu_names)
        register_classes(spec.classes)
        spec.register_keymaps(spec.keymap_store)
    else:
        remove_keymaps(spec.keymap_store, spec.menu_names)
        if current:
            unregister_classes(spec.classes)
    globals()[spec.state_name] = enabled
    if name == 'armature_mode':
        globals()['_armature_mod_pie_enabled'] = enabled


def disable_all_pies() -> None:
    for name in (
        'main', 'delete_merge', 'selection_mode', 'cursor', 'align',
        'armature_mode',
    ):
        set_pie_enabled(name, False)


def preference_keymaps():
    return [
        *align_pie_keymaps,
        *cursor_pie_keymaps,
        *selection_mode_pie_keymaps,
        *delete_merge_pie_keymaps,
        *main_pie_keymaps,
        *armature_mode_pie_keymaps,
    ]


def register():
    global _core_registered
    if not _core_registered:
        register_classes(HO_PIE_CORE_CLASSES)
        _core_registered = True
    AlignPie.register_props()


def unregister():
    global _core_registered
    disable_all_pies()
    if _core_registered:
        unregister_classes(HO_PIE_CORE_CLASSES)
        _core_registered = False
    AlignPie.unregister_props()


__all__ = [
    'align_pie_keymaps',
    'cursor_pie_keymaps',
    'selection_mode_pie_keymaps',
    'delete_merge_pie_keymaps',
    'main_pie_keymaps',
    'armature_mode_pie_keymaps',
    'armature_mod_pie_keymaps',
    'set_pie_enabled',
    'disable_all_pies',
    'preference_keymaps',
    'register',
    'unregister',
]
