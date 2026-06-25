# -*- coding: utf-8 -*-
"""HoTools 多语言支持 / i18n public API.

业务模块统一从这里导入：``from ..i18n import tr``。
详见 [ROADMAP_I18N.md](../ROADMAP_I18N.md)。
"""

from .manager import (
    tr,
    tr_iface,
    current_locale,
    reload,
    register,
    unregister,
    SUPPORTED_LOCALES,
    BASE_LOCALE,
)

__all__ = [
    'tr',
    'tr_iface',
    'current_locale',
    'reload',
    'register',
    'unregister',
    'SUPPORTED_LOCALES',
    'BASE_LOCALE',
]
