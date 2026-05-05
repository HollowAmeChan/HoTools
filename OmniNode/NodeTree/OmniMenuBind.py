import ast
import json
from typing import Any

import bpy


OMNI_BIND_VALUE_TYPES = {"BOOL", "INT", "FLOAT", "STRING", "VECTOR"}
OMNI_BIND_DEFAULT_CAPACITY = 32
LIVE_BIND_CONTEXTS: dict[tuple[int, str], dict[str, Any]] = {}


def _safe_json_loads(raw: str, fallback: Any):
    try:
        return json.loads(raw) if raw else fallback
    except Exception:
        return fallback


def _safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps(str(value), ensure_ascii=False)


def _normalize_bind_value_type(value_type: str) -> str:
    value_type = str(value_type or "FLOAT").upper()
    if value_type not in OMNI_BIND_VALUE_TYPES:
        return "FLOAT"
    return value_type


def _normalize_bind_rule(rule: dict[str, Any]) -> dict[str, Any]:
    rule = dict(rule or {})
    rule["key"] = str(rule.get("key") or rule.get("name") or "bind_param")
    rule["name"] = str(rule.get("name") or rule["key"])
    rule["value_type"] = _normalize_bind_value_type(rule.get("value_type"))
    rule["description"] = str(rule.get("description") or "")
    rule["source"] = rule.get("source") or {}

    if "default" not in rule:
        if rule["value_type"] == "BOOL":
            rule["default"] = False
        elif rule["value_type"] == "INT":
            rule["default"] = 0
        elif rule["value_type"] == "FLOAT":
            rule["default"] = 0.0
        elif rule["value_type"] == "STRING":
            rule["default"] = ""
        else:
            rule["default"] = [0.0, 0.0, 0.0]

    return rule


def _coerce_bind_value(value_type: str, value: Any):
    value_type = _normalize_bind_value_type(value_type)

    if value_type == "BOOL":
        return bool(value)
    if value_type == "INT":
        try:
            return int(value)
        except Exception:
            return 0
    if value_type == "FLOAT":
        try:
            return float(value)
        except Exception:
            return 0.0
    if value_type == "STRING":
        return "" if value is None else str(value)

    if isinstance(value, (list, tuple)):
        raw = list(value[:3])
    else:
        raw = [0.0, 0.0, 0.0]
    while len(raw) < 3:
        raw.append(0.0)
    return [float(raw[0]), float(raw[1]), float(raw[2])]


def _parse_custom_property_token(token: str):
    token = str(token or "").strip()
    if len(token) < 4 or token[0] != "[" or token[-1] != "]":
        return None

    inner = token[1:-1].strip()
    try:
        key = ast.literal_eval(inner)
    except Exception:
        return None
    if isinstance(key, str):
        return key
    return None


def _parse_property_path_segments(property_name: str):
    property_name = str(property_name or "").strip()
    if property_name.startswith("."):
        property_name = property_name[1:]
    if not property_name:
        return []

    segments = []
    length = len(property_name)
    index = 0

    while index < length:
        if property_name[index] == ".":
            index += 1
            continue

        if property_name[index] == "[":
            end = property_name.find("]", index)
            if end < 0:
                return []
            token = property_name[index:end + 1]
            key = _parse_custom_property_token(token)
            if key is None:
                return []
            segments.append(("key", key))
            index = end + 1
            continue

        start = index
        while index < length and property_name[index] not in ".[":
            index += 1
        name = property_name[start:index].strip()
        if not name:
            return []
        segments.append(("attr", name))

    return segments


def _resolve_property_owner(datablock, property_name: str):
    segments = _parse_property_path_segments(property_name)
    if not segments:
        return None, None

    owner = datablock
    for access_type, access_name in segments[:-1]:
        if owner is None:
            return None, None
        try:
            if access_type == "attr":
                owner = getattr(owner, access_name)
            else:
                owner = owner[access_name]
        except Exception:
            return None, None

    return owner, segments[-1]


def _assign_resolved_property(owner, last_segment, value: Any) -> bool:
    if owner is None or last_segment is None:
        return False

    access_type, access_name = last_segment
    try:
        if access_type == "key":
            owner[access_name] = value
        else:
            setattr(owner, access_name, value)
        return True
    except Exception:
        return False


def write_datablock_property(datablock, property_name: str, value: Any):
    property_name = str(property_name or "").strip()
    if datablock is None or not property_name:
        return

    owner, last_segment = _resolve_property_owner(datablock, property_name)
    _assign_resolved_property(owner, last_segment, value)


def _find_tree_node_by_name(tree, node_name: str):
    if tree is None or not hasattr(tree, "nodes"):
        return None
    for node in tree.nodes:
        if getattr(node, "name", "") == node_name:
            return node
    return None


def _tree_runtime_key(tree) -> int:
    if tree is None:
        return 0
    try:
        return int(tree.as_pointer())
    except Exception:
        return id(tree)


def _live_ref_key(tree, bind_key: str) -> tuple[int, str]:
    return (_tree_runtime_key(tree), str(bind_key))


def build_bind_rule_from_node(node) -> dict[str, Any] | None:
    if node is None:
        return None

    spec = getattr(node, "_bind_spec", None)
    if not isinstance(spec, dict):
        return None
    value_type = str(spec.get("value_type") or "FLOAT").upper()
    input_name = "Value"
    default_value = 0.0
    prop_name = ""

    if len(node.inputs) > 0:
        value_socket = node.inputs[-1]
        input_name = getattr(value_socket, "name", input_name) or input_name
        default_value = getattr(value_socket, "default_value", default_value)
    if len(node.inputs) > 1:
        prop_name = str(getattr(node.inputs[1], "default_value", "") or "")

    return {
        "key": str(spec.get("key") or node.name),
        "name": str(spec.get("name") or node.name),
        "value_type": value_type,
        "default": default_value,
        "description": str(spec.get("description") or f"Bind from {node.name}.{input_name}"),
        "source": {
            "node_name": getattr(node, "name", ""),
            "property_name": prop_name,
        },
    }


def append_pending_bind_rule(tree, rule: dict[str, Any]):
    if tree is None or not hasattr(tree, "omni_bind_pending_rules"):
        return None

    item = tree.omni_bind_pending_rules.add()
    item.key = str(rule.get("key") or rule.get("name") or "bind_param")
    item.payload = _safe_json_dumps(dict(rule or {}))
    item.enabled = bool(rule.get("enabled", True))
    return item


def clear_pending_bind_rules(tree):
    if tree is not None and hasattr(tree, "omni_bind_pending_rules"):
        tree.omni_bind_pending_rules.clear()


def collect_bind_rule(tree, node):
    rule = build_bind_rule_from_node(node)
    if rule is None:
        return None
    return append_pending_bind_rule(tree, rule)


def clear_live_bind_contexts(tree):
    tree_key = _tree_runtime_key(tree)
    stale_keys = [key for key in LIVE_BIND_CONTEXTS if key[0] == tree_key]
    for key in stale_keys:
        LIVE_BIND_CONTEXTS.pop(key, None)


def set_live_bind_context(tree, bind_key: str, datablock, prop_name=""):
    LIVE_BIND_CONTEXTS[_live_ref_key(tree, bind_key)] = {
        "datablock": datablock,
        "prop_name": prop_name,
    }


def get_live_bind_context(tree, bind_key: str):
    return LIVE_BIND_CONTEXTS.get(_live_ref_key(tree, bind_key))


def capture_bind_node_runtime_context(tree, node, args):
    rule = build_bind_rule_from_node(node)
    if rule is None:
        return
    datablock = args[0] if len(args) > 0 else None
    prop_name = str(args[1]) if len(args) > 1 and args[1] is not None else ""
    set_live_bind_context(tree, rule["key"], datablock, prop_name)


def _resolve_bind_node_runtime_context(tree, node, rule):
    bind_key = str(rule.get("key") or "")
    source = rule.get("source") or {}
    live_context = get_live_bind_context(tree, bind_key) or {}

    datablock = live_context.get("datablock")
    prop_name = str(live_context.get("prop_name") or "")

    if datablock is None and node is not None and len(node.inputs) > 0:
        datablock = getattr(node.inputs[0], "default_value", None)
    if not prop_name and node is not None and len(node.inputs) > 1:
        prop_name = str(getattr(node.inputs[1], "default_value", "") or "")
    if not prop_name:
        prop_name = str(source.get("property_name") or "")

    return datablock, prop_name


def execute_bind_node_update(node, datablock, prop_name: str, raw_value):
    update_func = getattr(node, "_bind_update", None)
    if callable(update_func):
        return update_func(datablock, prop_name, raw_value)
    return raw_value


def apply_bind_node_update(tree, rule, raw_value):
    node_name = str((rule.get("source") or {}).get("node_name") or "")
    node = _find_tree_node_by_name(tree, node_name)
    datablock, prop_name = _resolve_bind_node_runtime_context(tree, node, rule)
    return execute_bind_node_update(node, datablock, prop_name, raw_value)


def omni_bind_item_value_update(self, context):
    tree = getattr(self, "id_data", None)
    if tree is None:
        return
    OmniMenuBindRuntime.on_runtime_item_value_changed(tree, self, context)


class OmniBindPendingRuleItem(bpy.types.PropertyGroup):
    key: bpy.props.StringProperty(default="")  # type: ignore
    payload: bpy.props.StringProperty(default="{}")  # type: ignore
    enabled: bpy.props.BoolProperty(default=True)  # type: ignore


class OmniBindRuntimeItem(bpy.types.PropertyGroup):
    key: bpy.props.StringProperty(default="")  # type: ignore
    name: bpy.props.StringProperty(default="")  # type: ignore
    value_type: bpy.props.StringProperty(default="FLOAT")  # type: ignore
    description: bpy.props.StringProperty(default="")  # type: ignore
    rule_json: bpy.props.StringProperty(default="{}")  # type: ignore

    bool_value: bpy.props.BoolProperty(update=omni_bind_item_value_update)  # type: ignore
    int_value: bpy.props.IntProperty(update=omni_bind_item_value_update)  # type: ignore
    float_value: bpy.props.FloatProperty(update=omni_bind_item_value_update)  # type: ignore
    string_value: bpy.props.StringProperty(update=omni_bind_item_value_update)  # type: ignore
    vector_value: bpy.props.FloatVectorProperty(size=3, subtype="XYZ", update=omni_bind_item_value_update)  # type: ignore

    def get_rule(self) -> dict[str, Any]:
        return _normalize_bind_rule(_safe_json_loads(self.rule_json, {}))

    def set_rule(self, rule: dict[str, Any]):
        rule = _normalize_bind_rule(rule)
        self.key = rule["key"]
        self.name = rule["name"]
        self.value_type = rule["value_type"]
        self.description = rule["description"]
        self.rule_json = _safe_json_dumps(rule)

    def set_runtime_value(self, value: Any):
        value_type = _normalize_bind_value_type(self.value_type)
        coerced = _coerce_bind_value(value_type, value)

        if value_type == "BOOL":
            self.bool_value = coerced
        elif value_type == "INT":
            self.int_value = coerced
        elif value_type == "FLOAT":
            self.float_value = coerced
        elif value_type == "STRING":
            self.string_value = coerced
        else:
            self.vector_value = coerced

    def get_runtime_value(self):
        value_type = _normalize_bind_value_type(self.value_type)
        if value_type == "BOOL":
            return self.bool_value
        if value_type == "INT":
            return self.int_value
        if value_type == "FLOAT":
            return self.float_value
        if value_type == "STRING":
            return self.string_value
        return list(self.vector_value)


class OmniMenuBindRuntime:
    @classmethod
    def ensure_tree_props(cls, tree_type):
        if hasattr(tree_type, "omni_bind_pending_rules"):
            return
        tree_type.omni_bind_pending_rules = bpy.props.CollectionProperty(type=OmniBindPendingRuleItem)  # type: ignore
        tree_type.omni_bind_runtime_items = bpy.props.CollectionProperty(type=OmniBindRuntimeItem)  # type: ignore
        tree_type.omni_bind_is_rebuilding = bpy.props.BoolProperty(default=False)  # type: ignore

    @classmethod
    def remove_tree_props(cls, tree_type):
        for attr in [
            "omni_bind_pending_rules",
            "omni_bind_runtime_items",
            "omni_bind_is_rebuilding",
        ]:
            if hasattr(tree_type, attr):
                delattr(tree_type, attr)

    @classmethod
    def iter_pending_rules(cls, tree):
        if not hasattr(tree, "omni_bind_pending_rules"):
            return []
        rules = []
        for item in tree.omni_bind_pending_rules:
            if item.enabled:
                rules.append(_normalize_bind_rule(_safe_json_loads(item.payload, {})))
        return rules

    @classmethod
    def clear_runtime_items(cls, tree):
        if not hasattr(tree, "omni_bind_runtime_items"):
            return
        tree.omni_bind_is_rebuilding = True
        try:
            tree.omni_bind_runtime_items.clear()
        finally:
            tree.omni_bind_is_rebuilding = False

    @classmethod
    def build_runtime_items_from_pending(cls, tree):
        if not hasattr(tree, "omni_bind_runtime_items"):
            return

        rules = cls.iter_pending_rules(tree)

        tree.omni_bind_is_rebuilding = True
        try:
            tree.omni_bind_runtime_items.clear()
            for rule in rules[:OMNI_BIND_DEFAULT_CAPACITY]:
                item = tree.omni_bind_runtime_items.add()
                item.set_rule(rule)
                item.set_runtime_value(rule.get("default"))
        finally:
            tree.omni_bind_is_rebuilding = False

    @classmethod
    def apply_runtime_update(cls, tree, item: OmniBindRuntimeItem):
        rule = item.get_rule()
        try:
            apply_bind_node_update(tree, rule, item.get_runtime_value())
        except Exception as exc:
            print("[OmniMenuBind] bind update error:", exc)

    @classmethod
    def on_runtime_item_value_changed(cls, tree, item: OmniBindRuntimeItem, context):
        if getattr(tree, "omni_bind_is_rebuilding", False):
            return
        cls.apply_runtime_update(tree, item)

    @classmethod
    def draw_runtime_panel(cls, layout: bpy.types.UILayout, tree):
        box = layout.box()
        box.label(text="Omni Dynamic Params")

        if not hasattr(tree, "omni_bind_runtime_items"):
            box.label(text="Bind system not installed", icon="ERROR")
            return

        if len(tree.omni_bind_runtime_items) == 0:
            box.label(text="No dynamic params", icon="INFO")
            return

        for item in tree.omni_bind_runtime_items:
            col = box.column(align=True)
            label = item.name or item.key
            value_type = _normalize_bind_value_type(item.value_type)

            if value_type == "BOOL":
                col.prop(item, "bool_value", text=label)
            elif value_type == "INT":
                col.prop(item, "int_value", text=label)
            elif value_type == "FLOAT":
                col.prop(item, "float_value", text=label)
            elif value_type == "STRING":
                col.prop(item, "string_value", text=label)
            else:
                col.prop(item, "vector_value", text=label)

            if item.description:
                col.label(text=item.description, icon="BLANK1")


_CLASSES = [OmniBindPendingRuleItem, OmniBindRuntimeItem]


def register(tree_type=None):
    for item in _CLASSES:
        bpy.utils.register_class(item)
    if tree_type is not None:
        OmniMenuBindRuntime.ensure_tree_props(tree_type)


def unregister(tree_type=None):
    if tree_type is not None:
        OmniMenuBindRuntime.remove_tree_props(tree_type)
    for item in reversed(_CLASSES):
        bpy.utils.unregister_class(item)
