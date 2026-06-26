# -*- coding: utf-8 -*-
"""本地化字典集合 / locale dictionaries.

每个语言模块导出一个 ``translations`` 字典：``{ "中文原文": "译文", ... }``。
基准语言 zh_HANS 的键即译文，通常保持为空。
"""

from . import zh_HANS, en_US, ja_JP


def all_dicts():
    """返回 ``{locale: dict}``，供 manager 载入。返回副本避免运行时被改写。"""
    return {
        'zh_HANS': dict(zh_HANS.translations),
        'en_US': dict(en_US.translations),
        'ja_JP': dict(ja_JP.translations),
    }
