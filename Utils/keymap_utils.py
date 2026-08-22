"""将插件快捷键默认项解析到 Blender 用户快捷键项。"""


def _find_keymap(keymaps, addon_keymap):
    """查找与插件快捷键对应的用户快捷键表。"""
    name = getattr(addon_keymap, "name", "")
    space_type = getattr(addon_keymap, "space_type", None)
    region_type = getattr(addon_keymap, "region_type", None)

    finder = getattr(keymaps, "find", None)
    if finder is not None:
        try:
            found = finder(
                name,
                space_type=space_type,
                region_type=region_type,
            )
        except (AttributeError, TypeError, RuntimeError):
            found = None
        if found is not None:
            return found

    getter = getattr(keymaps, "get", None)
    if getter is not None:
        try:
            found = getter(name)
        except (AttributeError, TypeError, RuntimeError):
            found = None
        if found is not None:
            return found

    for candidate in keymaps:
        if getattr(candidate, "name", None) != name:
            continue
        if space_type is not None and getattr(candidate, "space_type", None) != space_type:
            continue
        if region_type is not None and getattr(candidate, "region_type", None) != region_type:
            continue
        return candidate
    return None


def find_user_keymap_item(user_keyconfig, addon_keymap, addon_item):
    """返回插件快捷键对应的 ``(user_keymap, user_item)``。

    优先使用 Blender 的 ``find_from_operator``，这样用户修改按键后仍能
    找到同一个操作符；备用逻辑用于兼容旧版本 Blender 和测试替身。
    """
    if user_keyconfig is None or addon_keymap is None or addon_item is None:
        return None

    user_keymap = _find_keymap(
        getattr(user_keyconfig, "keymaps", ()),
        addon_keymap,
    )
    if user_keymap is None:
        return None

    user_items = getattr(user_keymap, "keymap_items", ())
    addon_idname = getattr(addon_item, "idname", None)
    finder = getattr(user_items, "find_from_operator", None)
    if finder is not None and addon_idname:
        try:
            user_item = finder(
                addon_idname,
                getattr(addon_item, "properties", None),
            )
        except (AttributeError, TypeError, RuntimeError):
            user_item = None
        if user_item is not None:
            return user_keymap, user_item

    candidates = [
        item for item in user_items
        if getattr(item, "idname", None) == addon_idname
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return user_keymap, candidates[0]

    # 同一个操作符可能有多个绑定（例如饼菜单），按插件项的顺序对应。
    addon_items = list(getattr(addon_keymap, "keymap_items", ()))
    try:
        addon_ordinal = [
            item for item in addon_items
            if getattr(item, "idname", None) == addon_idname
        ].index(addon_item)
    except ValueError:
        addon_ordinal = 0
    return user_keymap, candidates[min(addon_ordinal, len(candidates) - 1)]
