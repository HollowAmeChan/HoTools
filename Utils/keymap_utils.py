"""将插件快捷键默认项解析到 Blender 用户快捷键项。"""


def _property_names(properties):
    """返回操作符属性名（兼容 bpy 结构与测试替身）。"""
    if properties is None:
        return ()
    keys = getattr(properties, "keys", None)
    if keys is not None:
        try:
            return tuple(keys())
        except (AttributeError, TypeError, RuntimeError):
            return ()
    if hasattr(properties, "__dict__"):
        return tuple(vars(properties))
    return ()


def _properties_match(candidate, reference):
    """判断两个快捷键项的操作符属性是否一致。

    同一个操作符（例如 ``wm.call_menu_pie``）会被多个插件复用，只有属性值
    相同才说明是同一个绑定，否则会串到别的插件（例如 UV Toolkit）的菜单上。
    """
    if reference is None:
        return True
    names = _property_names(reference)
    if not names:
        return True
    for name in names:
        if getattr(candidate, name, None) != getattr(reference, name, None):
            return False
    return True


def _properties_compatible(candidate, reference):
    """兜底候选是否与插件项冲突。

    用户可能改过操作符属性，镜像时也可能丢属性：这种情况仍然接受唯一的同名
    操作符；但候选带上了明确冲突的属性值（例如别的插件的菜单名）时不能顶替。
    """
    if reference is None:
        return True
    for name in _property_names(reference):
        expected = getattr(reference, name, None)
        actual = getattr(candidate, name, None)
        if actual == expected or not actual:
            continue
        return False
    return True


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


def _find_from_operator(user_items, addon_idname, addon_properties):
    """用 Blender 的 ``find_from_operator`` 解析用户快捷键项。

    ``properties`` 在该 API 里是仅关键字参数（位置传参在 Blender 4.1+ 会抛
    ``TypeError``），这里关键字优先、位置兜底，兼容旧版本与测试替身。
    """
    if not addon_idname:
        return None
    finder = getattr(user_items, "find_from_operator", None)
    if finder is None:
        return None
    try:
        return finder(addon_idname, properties=addon_properties)
    except TypeError:
        pass
    except (AttributeError, RuntimeError):
        return None
    try:
        return finder(addon_idname, addon_properties)
    except (AttributeError, TypeError, RuntimeError):
        return None


def find_user_keymap_item(user_keyconfig, addon_keymap, addon_item):
    """返回插件快捷键对应的 ``(user_keymap, user_item)``。

    优先使用 Blender 的 ``find_from_operator``，这样用户修改按键后仍能
    找到同一个操作符；备用逻辑用于兼容旧版本 Blender 和测试替身。

    匹配时必须带上操作符属性：``wm.call_menu_pie`` 之类的操作符会被多个
    插件共用，只按 idname 取第 N 项会串到别的插件菜单上。
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
    addon_properties = getattr(addon_item, "properties", None)

    user_item = _find_from_operator(user_items, addon_idname, addon_properties)
    if user_item is not None and _properties_match(
            getattr(user_item, "properties", None), addon_properties):
        return user_keymap, user_item

    same_operator = [
        item for item in user_items
        if getattr(item, "idname", None) == addon_idname
    ]
    candidates = [
        item for item in same_operator
        if _properties_match(getattr(item, "properties", None), addon_properties)
    ]
    if not candidates:
        # 用户可能手动改过操作符属性，或镜像时丢了属性；只有一个同名操作符
        # 且属性不冲突时才返回它，避免显示成别的插件的绑定。
        if len(same_operator) == 1 and _properties_compatible(
                getattr(same_operator[0], "properties", None), addon_properties):
            return user_keymap, same_operator[0]
        return None
    if len(candidates) == 1:
        return user_keymap, candidates[0]

    # 同一个操作符、同一组属性也可能有多个绑定（例如饼菜单的不同槽位），
    # 按插件项在这些绑定中的顺序对应。
    addon_items = [
        item for item in getattr(addon_keymap, "keymap_items", ())
        if getattr(item, "idname", None) == addon_idname
        and _properties_match(getattr(item, "properties", None), addon_properties)
    ]
    try:
        addon_ordinal = addon_items.index(addon_item)
    except ValueError:
        addon_ordinal = 0
    return user_keymap, candidates[min(addon_ordinal, len(candidates) - 1)]
