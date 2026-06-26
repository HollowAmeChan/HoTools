# -*- coding: utf-8 -*-
"""HoTools 多语言核心 / i18n core.

负责：
- 解析*有效语言*（插件偏好设置，或当偏好为 AUTO 时跟随 Blender 的 locale）。
- 合并并查询本地化字典，缺失时回退到中文键（msgid）。
- 将同一套字典注册到 ``bpy.app.translations``，让无法被 ``tr()`` 包裹的字符串
  在插件跟随 Blender 语言时获得尽力而为的原生翻译。

公共 API 通过 ``i18n/__init__.py`` 暴露，业务模块只需 ``from ..i18n import tr``。
"""

import bpy

# 插件根包名，用于读取 AddonPreferences（子包 __package__ 形如 "HoTools.i18n"）。
_ADDON_PKG = (__package__ or __name__).split('.')[0]

# 受支持的显式语言；zh_HANS 是基准/键语言（msgid 即中文原文）。
SUPPORTED_LOCALES = ('zh_HANS', 'en_US', 'ja_JP')
BASE_LOCALE = 'zh_HANS'

# 本地化字典：locale -> { msgid: 译文 }，在 register() 时从 .locales 载入。
_TRANSLATIONS = {}

# 解析结果缓存，避免每次重绘都读偏好；reload() 时清空。
_cached_locale = None


def _addon_prefs():
    """返回本插件的 AddonPreferences，未注册时返回 None。"""
    try:
        addon = bpy.context.preferences.addons.get(_ADDON_PKG)
        return addon.preferences if addon else None
    except Exception:
        return None


def _blender_locale():
    try:
        return bpy.app.translations.locale or BASE_LOCALE
    except Exception:
        return BASE_LOCALE


def _normalize(locale):
    """把任意 locale 码归一到受支持集合，无法匹配时回退基准语言。"""
    if not locale:
        return BASE_LOCALE
    if locale in SUPPORTED_LOCALES:
        return locale
    # 仅按语言前缀匹配，例如 'en' -> 'en_US'、'ja' -> 'ja_JP'、'zh_CN' -> 'zh_HANS'。
    lang = locale.split('_')[0].lower()
    for loc in SUPPORTED_LOCALES:
        if loc.split('_')[0].lower() == lang:
            return loc
    return BASE_LOCALE


def current_locale():
    """解析当前*有效语言*。偏好为 AUTO 时跟随 Blender；否则用显式选择。"""
    global _cached_locale
    if _cached_locale is not None:
        return _cached_locale
    prefs = _addon_prefs()
    choice = getattr(prefs, 'hoTools_language', 'AUTO') if prefs else 'AUTO'
    resolved = _normalize(_blender_locale()) if choice == 'AUTO' else _normalize(choice)
    _cached_locale = resolved
    return resolved


def tr(text, ctxt=None):
    """把中文原文翻译为有效语言；缺失译文时回退中文键。"""
    if not text:
        return text
    table = _TRANSLATIONS.get(current_locale())
    if table:
        if ctxt is not None:
            val = table.get((ctxt, text))
            if val:
                return val
        val = table.get(text)
        if val:
            return val
    return text


def tr_iface(text, ctxt=None):
    """界面字符串翻译。当前与 tr() 同义，保留独立入口以备区分上下文。"""
    return tr(text, ctxt)


def reload():
    """偏好回调调用：清空缓存并触发重绘，使语言切换即时生效。"""
    global _cached_locale
    _cached_locale = None
    try:
        wm = bpy.context.window_manager
        for window in wm.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


# --- bpy.app.translations 桥接 ------------------------------------------------

def _build_bpy_dict():
    """把内部字典转成 Blender 的 {locale: {(ctxt, msgid): 译文}} 格式。"""
    out = {}
    for locale, table in _TRANSLATIONS.items():
        if locale == BASE_LOCALE:
            continue  # 基准语言键即译文，无需注册。
        entries = {}
        for key, val in table.items():
            if not val:
                continue
            ctxt, msgid = key if isinstance(key, tuple) else ('*', key)
            entries[(ctxt, msgid)] = val
        if entries:
            out[locale] = entries
    return out


def _register_bpy_translations():
    d = _build_bpy_dict()
    if not d:
        return  # Phase 1 字典为空：不向 Blender 注册任何内容。
    try:
        bpy.app.translations.unregister(_ADDON_PKG)
    except Exception:
        pass
    try:
        bpy.app.translations.register(_ADDON_PKG, d)
    except Exception:
        pass


def _unregister_bpy_translations():
    try:
        bpy.app.translations.unregister(_ADDON_PKG)
    except Exception:
        pass


def register():
    global _TRANSLATIONS
    from . import locales
    _TRANSLATIONS = locales.all_dicts()
    _register_bpy_translations()
    reload()


def unregister():
    global _TRANSLATIONS, _cached_locale
    _unregister_bpy_translations()
    _TRANSLATIONS = {}
    _cached_locale = None
