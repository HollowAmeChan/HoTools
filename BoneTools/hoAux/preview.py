"""Single active HoAux preview, following the ordinary aux preview lifecycle."""

import bpy

from .module_registry import definitions, get_definition
from .preview_draw import PreviewScene, ViewportPreview


_timer_running = False
_toggle_guard = False
_timer_interval = 0.08


def _settings(definition, scene):
    return definition.settings(scene)


def _start_timer():
    global _timer_running
    if not _timer_running:
        _timer_running = True
        bpy.app.timers.register(_timer)


def _show(context, module_type):
    definition = get_definition(module_type)
    try:
        scene = definition.build_preview_scene(context)
    except (KeyError, TypeError, ValueError, ReferenceError) as exc:
        obj = context.object
        scene = PreviewScene(
            obj.name if obj is not None else "",
            title=definition.label,
            message=str(exc),
        )
    ViewportPreview.show(module_type, scene)
    _start_timer()


def set_module_preview_enabled(context, module_type, enabled):
    global _toggle_guard
    if _toggle_guard:
        return
    _toggle_guard = True
    try:
        if enabled:
            for definition in definitions():
                if definition.type_id == module_type:
                    continue
                settings = _settings(definition, context.scene)
                if settings.preview_enabled:
                    settings.preview_enabled = False
            _show(context, module_type)
        else:
            ViewportPreview.clear(module_type)
    finally:
        _toggle_guard = False


def refresh_active_preview(context):
    module_type = ViewportPreview.active_owner()
    if module_type is None:
        return
    definition = get_definition(module_type)
    if not _settings(definition, context.scene).preview_enabled:
        ViewportPreview.clear(module_type)
        return
    _show(context, module_type)


def _timer():
    global _timer_running
    if ViewportPreview.active_owner() is None:
        _timer_running = False
        return None
    try:
        refresh_active_preview(bpy.context)
    except (AttributeError, KeyError, ReferenceError, RuntimeError, ValueError):
        ViewportPreview.clear()
        _timer_running = False
        return None
    return _timer_interval


def shutdown():
    global _timer_running
    _timer_running = False
    ViewportPreview.shutdown()
