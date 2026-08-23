"""Blender 节点编辑器的 Tab 搜索。

节点目录直接读取当前 Blender 已注册的节点类，避免维护按版本拆分的
静态节点清单，也让已注册的第三方节点可以自然参与搜索。
"""

from __future__ import annotations

import gettext
import hashlib
import re
from functools import lru_cache
from pathlib import Path

import bpy
from bpy.props import EnumProperty
from bpy.types import Node, Operator

from ..Utils.runtime_platform import configure_runtime_paths, resolve_runtime_target

_ADDON_ROOT = Path(__file__).resolve().parent.parent
configure_runtime_paths(resolve_runtime_target(_ADDON_ROOT))

try:
    from pypinyin import Style as _PinyinStyle
    from pypinyin import lazy_pinyin as _lazy_pinyin
except Exception:
    _PinyinStyle = None
    _lazy_pinyin = None


_REGISTERED = False
_ENABLED = False
_KEYMAPS = []
_ENUM_CACHE = []
_ENTRY_BY_ID = {}
_ZH_TRANSLATIONS = {}

_GENERIC_NODE_IDS = {
    "Node",
    "NodeCustomGroup",
    "ShaderNode",
    "ShaderNodeCustomGroup",
    "GeometryNode",
    "GeometryNodeCustomGroup",
    "CompositorNode",
    "CompositorNodeCustomGroup",
}

_NON_CREATABLE_NODE_IDS = {
    # 当前版本几何节点中的运行时辅助节点，不应该出现在添加列表中。
    "GeometryNodeApplySimulatedData",
}

_VARIANT_PROPERTIES = {
    "ShaderNodeMath": ("operation",),
    "ShaderNodeVectorMath": ("operation",),
    "CompositorNodeMath": ("operation",),
    "TextureNodeMath": ("operation",),
    "FunctionNodeBooleanMath": ("operation",),
    "FunctionNodeCompare": ("data_type",),
    "ShaderNodeMix": ("data_type",),
    "ShaderNodeMapRange": ("data_type",),
    "GeometryNodeSwitch": ("input_type",),
}

_ZONE_PAIRS = {
    "GeometryNodeSimulationInput": "GeometryNodeSimulationOutput",
    "GeometryNodeRepeatInput": "GeometryNodeRepeatOutput",
    "GeometryNodeForeachGeometryElementInput": "GeometryNodeForeachGeometryElementOutput",
}
_ZONE_OUTPUT_IDS = set(_ZONE_PAIRS.values())


def _active_tree(context):
    space = getattr(context, "space_data", None)
    if space is None or getattr(space, "type", None) != "NODE_EDITOR":
        return None
    return getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)


def _translation():
    """读取 Blender 中文翻译表，不改变用户当前的界面语言。"""
    path = Path(bpy.utils.resource_path("LOCAL")) / "datafiles" / "locale" / "zh_HANS" / "LC_MESSAGES" / "blender.mo"
    key = str(path)
    if key in _ZH_TRANSLATIONS:
        return _ZH_TRANSLATIONS[key]

    catalog = None
    try:
        with path.open("rb") as stream:
            catalog = gettext.GNUTranslations(stream)
    except (OSError, EOFError):
        catalog = gettext.NullTranslations()
    _ZH_TRANSLATIONS[key] = catalog
    return catalog


def _zh(text):
    text = str(text or "")
    translated = _translation().gettext(text)
    if translated == text:
        try:
            translated = bpy.app.translations.pgettext_iface(text)
        except Exception:
            pass
    return translated or text


# 拼音库加载失败时，用这些 GBK 区间保留最基本的首字母搜索。
_GBK_INITIAL_RANGES = (
    (0xB0A1, 0xB0C4, "a"), (0xB0C5, 0xB2C0, "b"),
    (0xB2C1, 0xB4ED, "c"), (0xB4EE, 0xB6E9, "d"),
    (0xB6EA, 0xB7A1, "e"), (0xB7A2, 0xB8C0, "f"),
    (0xB8C1, 0xB9FD, "g"), (0xB9FE, 0xBBF6, "h"),
    (0xBBF7, 0xBFA5, "j"), (0xBFA6, 0xC0AB, "k"),
    (0xC0AC, 0xC2E7, "l"), (0xC2E8, 0xC4C2, "m"),
    (0xC4C3, 0xC5B5, "n"), (0xC5B6, 0xC5BD, "o"),
    (0xC5BE, 0xC6D9, "p"), (0xC6DA, 0xC8BA, "q"),
    (0xC8BB, 0xC8F5, "r"), (0xC8F6, 0xCBF9, "s"),
    (0xCBFA, 0xCDD9, "t"), (0xCDDA, 0xCEF3, "w"),
    (0xCEF4, 0xD1B9, "x"), (0xD1BA, 0xD4D0, "y"),
    (0xD4D1, 0xD7F9, "z"),
)


def _gbk_initials(text):
    result = []
    for char in str(text or ""):
        if "\u4e00" <= char <= "\u9fff":
            try:
                encoded = char.encode("gbk")
                code = (encoded[0] << 8) | encoded[1]
            except (UnicodeEncodeError, IndexError):
                continue
            result.append(next((initial for start, end, initial in _GBK_INITIAL_RANGES if start <= code <= end), ""))
        elif char.isascii() and char.isalnum():
            result.append(char.lower())
    return "".join(result)


def _compact_pinyin(parts):
    return "".join(
        char.casefold()
        for part in (str(value) for value in parts)
        for char in part
        if char.isalnum()
    )


@lru_cache(maxsize=2048)
def _pinyin_forms(text):
    if _lazy_pinyin is not None:
        try:
            full = _compact_pinyin(_lazy_pinyin(
                text,
                style=_PinyinStyle.NORMAL,
                errors="default",
                v_to_u=False,
            ))
            initials = _compact_pinyin(_lazy_pinyin(
                text,
                style=_PinyinStyle.FIRST_LETTER,
                errors="default",
                v_to_u=False,
            ))
            return full, initials
        except Exception:
            pass

    initials = _gbk_initials(text)
    return initials, initials


def _search_aliases(text):
    initials_aliases = []
    full_aliases = []
    for part in re.split(r"[>|]", str(text or "")):
        if not any("\u4e00" <= char <= "\u9fff" for char in part):
            continue
        full_pinyin, initials = _pinyin_forms(part.strip())
        if initials and initials not in initials_aliases:
            initials_aliases.append(initials)
        if full_pinyin and full_pinyin not in full_aliases:
            full_aliases.append(full_pinyin)

    # 保持首字母在全拼前，显示时再把这组索引放到节点名称后面。
    return initials_aliases + [alias for alias in full_aliases if alias not in initials_aliases]


def _display(label_zh, label_en=None):
    label_zh = str(label_zh or "")
    label_en = str(label_en or "")
    base_label_zh = label_zh
    aliases = _search_aliases(label_zh)
    if aliases:
        label_zh = f"{label_zh} [{' '.join(aliases)}]"
    if label_en and label_en != base_label_zh:
        return f"{label_zh} | {label_en}"
    return label_zh or label_en


def _entry_id(entry, index):
    payload = repr((entry.get("node_type"), entry.get("settings"), entry.get("group_name"), entry.get("special")))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"hotab_{index}_{digest}"


def _contains_tree(parent, target):
    if parent is target:
        return True
    try:
        return bool(parent.contains_tree(target))
    except (AttributeError, RuntimeError):
        return False


def _group_entries(tree):
    if tree is None:
        return []

    tree_id = getattr(tree, "bl_idname", "")
    if tree_id == "OmniNodeTree":
        node_type = "HO_OmniNode_GroupNode"
        group_property = "target_tree"
    else:
        node_type = {
            "ShaderNodeTree": "ShaderNodeGroup",
            "GeometryNodeTree": "GeometryNodeGroup",
            "CompositorNodeTree": "CompositorNodeGroup",
            "TextureNodeTree": "TextureNodeGroup",
        }.get(tree_id)
        group_property = "node_tree"

    if node_type is None:
        return []

    entries = []
    for group in bpy.data.node_groups:
        if getattr(group, "bl_idname", "") != tree_id:
            continue
        if group is tree or str(getattr(group, "name", "")).startswith("."):
            continue
        if _contains_tree(group, tree):
            continue
        name = str(group.name)
        entries.append({
            "label_zh": name,
            "label_en": name,
            "node_type": node_type,
            "group_property": group_property,
            "group": group,
            "group_name": name,
        })
    return entries


def _iter_registered_omni_classes():
    try:
        from ..OmniNode import OmniNodeRegister
        return OmniNodeRegister.iter_registered_node_classes()
    except (ImportError, AttributeError, RuntimeError):
        return ()


def _omni_entries(tree):
    if getattr(tree, "bl_idname", "") != "OmniNodeTree":
        return []

    entries = []
    for cls in _iter_registered_omni_classes():
        node_type = getattr(cls, "bl_idname", "")
        if not node_type or node_type == "HO_OmniNode_GroupNode":
            continue
        label = getattr(cls, "bl_label", "") or node_type
        entries.append({
            "label_zh": label,
            "label_en": "",
            "node_type": node_type,
        })
    return entries


def _node_classes(tree):
    tree_id = getattr(tree, "bl_idname", "")
    if tree_id == "OmniNodeTree":
        return []

    classes = []
    seen_ids = set()
    for name in dir(bpy.types):
        try:
            cls = getattr(bpy.types, name)
            if not isinstance(cls, type) or not issubclass(cls, Node) or cls is Node:
                continue
            node_id = cls.bl_rna.identifier
        except (AttributeError, TypeError, RuntimeError):
            continue
        if node_id in seen_ids or node_id in _GENERIC_NODE_IDS or node_id in _NON_CREATABLE_NODE_IDS:
            continue
        if node_id.endswith("CustomGroup") or node_id in _ZONE_OUTPUT_IDS:
            continue
        try:
            if not cls.poll(tree):
                continue
        except (AttributeError, RuntimeError, TypeError):
            continue
        seen_ids.add(node_id)
        classes.append(cls)
    return sorted(classes, key=lambda cls: cls.bl_rna.identifier.casefold())


def _class_entry(cls, node_id=None, settings=None, variant_zh="", variant_en=""):
    node_id = node_id or cls.bl_rna.identifier
    english = str(getattr(cls.bl_rna, "name", node_id))
    chinese = _zh(english)
    if variant_en:
        english = f"{variant_en} > {english}"
    if variant_zh:
        chinese = f"{variant_zh} > {chinese}"
    return {
        "label_zh": chinese,
        "label_en": english,
        "node_type": node_id,
        "settings": dict(settings or {}),
    }


def _class_entries(tree):
    entries = []
    for cls in _node_classes(tree):
        node_id = cls.bl_rna.identifier
        if node_id in _ZONE_PAIRS:
            output_id = _ZONE_PAIRS[node_id]
            output_cls = bpy.types.Node.bl_rna_get_subclass_py(output_id)
            if output_cls is None:
                continue
            zone_name_en = "Simulation Zone"
            if node_id == "GeometryNodeRepeatInput":
                zone_name_en = "Repeat Zone"
            elif node_id == "GeometryNodeForeachGeometryElementInput":
                zone_name_en = "For Each Geometry Element Zone"
            entries.append({
                "label_zh": _zh(zone_name_en),
                "label_en": zone_name_en,
                "node_type": node_id,
                "special": "zone",
                "zone_output": output_id,
            })
            continue

        entries.append(_class_entry(cls))
        for prop_name in _VARIANT_PROPERTIES.get(node_id, ()):
            try:
                prop = cls.bl_rna.properties.get(prop_name)
                if prop is None or prop.type != "ENUM":
                    continue
                for item in prop.enum_items:
                    item_en = str(item.name)
                    item_zh = _zh(item_en)
                    entries.append(_class_entry(
                        cls,
                        settings={prop_name: item.identifier},
                        variant_zh=item_zh,
                        variant_en=item_en,
                    ))
            except (AttributeError, RuntimeError, TypeError):
                continue
    return entries


def _build_entries(context):
    tree = _active_tree(context)
    if tree is None:
        return []
    entries = _class_entries(tree)
    entries.extend(_omni_entries(tree))
    entries.extend(_group_entries(tree))
    entries.sort(key=lambda entry: (str(entry.get("label_zh", "")).casefold(), str(entry.get("node_type", ""))))
    return entries


def _enum_items(self, context):
    del self
    _ENUM_CACHE.clear()
    _ENTRY_BY_ID.clear()
    for index, entry in enumerate(_build_entries(context)):
        identifier = _entry_id(entry, index)
        label = _display(entry.get("label_zh"), entry.get("label_en"))
        item = (identifier, label, entry.get("node_type", ""))
        _ENUM_CACHE.append(item)
        _ENTRY_BY_ID[identifier] = entry
    return _ENUM_CACHE


def _select_nodes(tree, nodes):
    for current in tree.nodes:
        current.select = False
    for node in nodes:
        node.select = True
    tree.nodes.active = nodes[-1]


def _cursor_location(context):
    cursor = getattr(context.space_data, "cursor_location", None)
    return cursor.copy() if cursor is not None and hasattr(cursor, "copy") else cursor


def _new_zone(tree, entry, location):
    input_node = tree.nodes.new(type=entry["node_type"])
    output_node = None
    try:
        output_node = tree.nodes.new(type=entry["zone_output"])
        input_node.pair_with_output(output_node)
        if location is not None:
            x, y = float(location[0]), float(location[1])
            input_node.location = (x - 150, y)
            output_node.location = (x + 150, y)
        return [input_node, output_node]
    except Exception:
        if output_node is not None:
            tree.nodes.remove(output_node)
        tree.nodes.remove(input_node)
        raise


def _create_node(context, entry):
    tree = _active_tree(context)
    if tree is None:
        raise RuntimeError("当前区域不是可编辑的节点树")
    location = _cursor_location(context)
    group = entry.get("group")
    nodes = []

    if entry.get("special") == "zone":
        nodes = _new_zone(tree, entry, location)
    else:
        node = tree.nodes.new(type=entry["node_type"])
        nodes = [node]
        try:
            group_property = entry.get("group_property")
            if group_property and group is not None:
                setattr(node, group_property, group)
            for name, value in entry.get("settings", {}).items():
                setattr(node, name, value)
            if location is not None:
                node.location = location
        except Exception:
            tree.nodes.remove(node)
            raise

    _select_nodes(tree, nodes)
    return nodes


class NODE_OT_hotab_search(Operator):
    bl_idname = "ho.hotab_search"
    bl_label = "菜单:节点搜索"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "search_entry"

    search_entry: EnumProperty(items=_enum_items, name="节点") # type: ignore

    @classmethod
    def poll(cls, context):
        return _active_tree(context) is not None

    def invoke(self, context, event):
        del event
        context.window_manager.invoke_search_popup(self)
        return {"CANCELLED"}

    def execute(self, context):
        entry = _ENTRY_BY_ID.get(self.search_entry)
        if entry is None:
            return {"CANCELLED"}
        try:
            _create_node(context, entry)
            bpy.ops.node.translate_attach_remove_on_cancel("INVOKE_DEFAULT")
        except Exception as exc:
            self.report({"ERROR"}, f"创建节点失败: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


def preference_keymaps():
    return list(_KEYMAPS)


def enable():
    global _ENABLED
    if _ENABLED:
        return
    key_config = bpy.context.window_manager.keyconfigs.addon
    if key_config is None:
        return
    key_map = key_config.keymaps.new(name="Node Editor", space_type="NODE_EDITOR")
    key_entry = key_map.keymap_items.new(NODE_OT_hotab_search.bl_idname, "TAB", value="PRESS")
    _KEYMAPS.append((key_map, key_entry))
    _ENABLED = True


def disable():
    global _ENABLED
    for key_map, key_entry in reversed(_KEYMAPS):
        try:
            key_map.keymap_items.remove(key_entry)
        except (ReferenceError, RuntimeError):
            pass
    _KEYMAPS.clear()
    _ENABLED = False


def register():
    global _REGISTERED
    if _REGISTERED:
        return
    bpy.utils.register_class(NODE_OT_hotab_search)
    _REGISTERED = True


def unregister():
    global _REGISTERED
    disable()
    if not _REGISTERED:
        return
    bpy.utils.unregister_class(NODE_OT_hotab_search)
    _REGISTERED = False
