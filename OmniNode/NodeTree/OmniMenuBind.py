# OmniMenuBind
# 这个文件集中管理 OmniNode 的动态 Bind 参数系统。
#
# 当前流程：
# 1. 编译阶段扫描 Bind GraphNode，找到 processor_tree 输入中的 ParameterSocket。
# 2. 将 ParameterSocket 展开为 pending rule，再在 tree.run() 结束后生成侧栏动态参数。
# 3. 执行阶段缓存 Bind 节点本次运行的真实 args 与 processor_graph。
# 4. 用户在侧栏修改动态参数时，用新值替换 args 中对应的 ParameterSocket 输入。
# 5. 重新执行缓存中的 processor_graph，让子树使用真实 datablock 完成更新。
#
# 注意：
# - 动态参数本身不是持久运行时系统，LIVE_BIND_CONTEXTS 只保存当前 Python 会话内的运行缓存。
# - 文件重载、插件重载、节点结构变化、未重新运行 tree 等情况都会让缓存丢失或过时。
# - 侧栏 UI 只负责暴露缓存状态，不尝试自动恢复缓存。

import ast
import json
from typing import Any

import bpy


# =============================================================================
# 基础配置与序列化工具
# =============================================================================

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


def _socket_default_to_json_value(value: Any):
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    try:
        return list(value)
    except Exception:
        return str(value)


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


# =============================================================================
# ParameterSocket 与 Bind 规则
# =============================================================================


def _socket_to_bind_value_type(socket, fallback="FLOAT") -> str:
    socket_type = getattr(socket, "bl_idname", "")
    if socket_type in {"NodeSocketBool", "OmniNodeSocketParameterBool"}:
        return "BOOL"
    if socket_type in {"NodeSocketInt", "OmniNodeSocketParameterInt"}:
        return "INT"
    if socket_type in {"NodeSocketFloat", "OmniNodeSocketParameterFloat"}:
        return "FLOAT"
    if socket_type in {"NodeSocketString", "OmniNodeSocketParameterString"}:
        return "STRING"
    if socket_type in {"NodeSocketVector", "OmniNodeSocketParameterVector"}:
        return "VECTOR"
    return _normalize_bind_value_type(fallback)


def _is_parameter_socket(socket) -> bool:
    return str(getattr(socket, "bl_idname", "")).startswith("OmniNodeSocketParameter")


def find_parameter_input_index(node) -> int:
    if node is None:
        return -1

    processor_tree = getattr(node, "processor_tree", None)
    if processor_tree is not None:
        for index, item in enumerate(getattr(processor_tree, "group_inputs", [])):
            if str(getattr(item, "socket_type", "")).startswith("OmniNodeSocketParameter"):
                return index

    for index, socket in enumerate(getattr(node, "inputs", [])):
        if _is_parameter_socket(socket):
            return index

    return -1


def coerce_node_parameter_value(node, value):
    value_index = find_parameter_input_index(node)
    inputs = getattr(node, "inputs", [])
    if 0 <= value_index < len(inputs):
        return _coerce_bind_value(_socket_to_bind_value_type(inputs[value_index]), value)
    return value


def get_parameter_value_from_args(node, args):
    value_index = find_parameter_input_index(node)
    return args[value_index] if 0 <= value_index < len(args) else None


# =============================================================================
# Datablock 属性路径读写
# =============================================================================


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


def read_datablock_property(datablock, property_name: str):
    property_name = str(property_name or "").strip()
    if datablock is None or not property_name:
        return None

    owner, last_segment = _resolve_property_owner(datablock, property_name)
    if owner is None or last_segment is None:
        return None

    access_type, access_name = last_segment
    try:
        if access_type == "key":
            return owner[access_name]
        return getattr(owner, access_name)
    except Exception:
        return None


# =============================================================================
# Bind 规则收集与运行缓存
# =============================================================================


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

    value_socket = None
    value_index = find_parameter_input_index(node)

    if value_index < 0:
        return None

    if value_index < len(node.inputs):
        value_socket = node.inputs[value_index]
    if value_socket is None:
        return None

    value_type = _socket_to_bind_value_type(value_socket)
    input_name = "Value"
    default_value = 0.0

    input_name = getattr(value_socket, "name", input_name) or input_name
    default_value = _socket_default_to_json_value(getattr(value_socket, "default_value", default_value))

    return {
        "key": str(node.name),
        "name": str(input_name or node.name),
        "value_type": value_type,
        "default": default_value,
        "description": f"Bind from {node.name}.{input_name}",
        "source": {
            "node_name": getattr(node, "name", ""),
            "parameter_input_index": value_index,
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


def set_live_bind_context(tree, bind_key: str, args=None, processor_graph=None):
    LIVE_BIND_CONTEXTS[_live_ref_key(tree, bind_key)] = {
        "args": list(args or []),
        "processor_graph": processor_graph,
    }


def get_live_bind_context(tree, bind_key: str):
    return LIVE_BIND_CONTEXTS.get(_live_ref_key(tree, bind_key))


def _format_datablock_label(datablock) -> str:
    if datablock is None:
        return "<missing>"

    id_type = getattr(datablock, "id_type", None) or type(datablock).__name__
    name = getattr(datablock, "name_full", None) or getattr(datablock, "name", None) or repr(datablock)
    return f"{id_type}: {name}"


def _collect_datablocks(value: Any, datablocks: list, seen: set[int]) -> None:
    if isinstance(value, bpy.types.ID):
        try:
            key = int(value.as_pointer())
        except Exception:
            key = id(value)
        if key not in seen:
            seen.add(key)
            datablocks.append(value)
        return

    if isinstance(value, dict):
        for item in value.values():
            _collect_datablocks(item, datablocks, seen)
        return

    if isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_datablocks(item, datablocks, seen)


def _runtime_debug_info(tree, rule: dict[str, Any]) -> dict[str, Any]:
    bind_key = str(rule.get("key") or "")
    source = rule.get("source") or {}
    source_node = _find_tree_node_by_name(tree, str(source.get("node_name") or ""))
    live_context = get_live_bind_context(tree, bind_key)

    # TODO: 这里只能判断缓存对象是否存在，无法判断 processor_tree 或 Bind IO 是否在 run 后发生过变化。
    # 后续如果需要更严格的状态，可以给 tree/group_io/bind node 增加 version 或 run stamp。
    datablocks = []
    if live_context is not None:
        _collect_datablocks(live_context.get("args") or [], datablocks, set())

    return {
        "has_live_context": live_context is not None,
        "has_processor_graph": bool(live_context and live_context.get("processor_graph") is not None),
        "has_source_node": source_node is not None,
        "datablocks": datablocks,
    }


def capture_bind_node_runtime_context(tree, node, args, processor_graph=None):
    rule = build_bind_rule_from_node(node)
    if rule is None:
        return
    set_live_bind_context(tree, rule["key"], args, processor_graph)


def _resolve_bind_node_runtime_context(tree, node, rule):
    bind_key = str(rule.get("key") or "")
    live_context = get_live_bind_context(tree, bind_key) or {}

    args = list(live_context.get("args") or [])
    processor_graph = live_context.get("processor_graph")
    if not args and node is not None:
        for socket in node.inputs:
            args.append(getattr(socket, "default_value", None))

    return args, processor_graph


# =============================================================================
# Bind 更新执行入口
# =============================================================================


def execute_bind_node_update(node, args, raw_value, processor_graph=None):
    value = coerce_node_parameter_value(node, raw_value)
    return run_bind_processor_graph(node, args, value, processor_graph)


def run_bind_processor_graph(node, args, value, processor_graph):
    if processor_graph is None:
        return value

    from .OmniExecutor import OmniExecutor

    provided_inputs = {}
    value_index = find_parameter_input_index(node)
    for index, item in enumerate(getattr(processor_graph.tree_ref, "group_inputs", [])):
        if index >= len(args):
            continue
        if index == value_index:
            provided_inputs[item.uid] = value
        else:
            provided_inputs[item.uid] = args[index]

    result, _trace = OmniExecutor._execute(processor_graph, provided_inputs=provided_inputs)
    outputs = getattr(node, "outputs", [])
    if len(outputs) == 0:
        return value

    values = []
    for socket in outputs:
        values.append(result.get(socket.identifier))

    if len(values) == 1:
        return values[0]
    return tuple(values)


def apply_bind_node_update(tree, rule, raw_value):
    node_name = str((rule.get("source") or {}).get("node_name") or "")
    node = _find_tree_node_by_name(tree, node_name)
    args, processor_graph = _resolve_bind_node_runtime_context(tree, node, rule)

    # TODO: 如果 source node 已经找不到，但旧 live context 仍在，当前仍可能执行旧 processor_graph。
    # 这是调试期允许观察的 stale cache 行为；未来可以选择在 node is None 时直接拒绝 update。
    value_index = int((rule.get("source") or {}).get("parameter_input_index") or 0)
    while len(args) <= value_index:
        args.append(None)
    args[value_index] = raw_value
    return execute_bind_node_update(node, args, raw_value, processor_graph)


def omni_bind_item_value_update(self, context):
    tree = getattr(self, "id_data", None)
    if tree is None:
        return
    OmniMenuBindRuntime.on_runtime_item_value_changed(tree, self, context)


# =============================================================================
# Blender Runtime PropertyGroup
# =============================================================================


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


# =============================================================================
# 动态面板构建与交互
# =============================================================================


class OmniMenuBindRuntime:
    @classmethod
    def ensure_tree_props(cls, tree_type):
        if hasattr(tree_type, "omni_bind_pending_rules"):
            return
        tree_type.omni_bind_pending_rules = bpy.props.CollectionProperty(type=OmniBindPendingRuleItem)  # type: ignore
        tree_type.omni_bind_runtime_items = bpy.props.CollectionProperty(type=OmniBindRuntimeItem)  # type: ignore
        tree_type.omni_bind_is_rebuilding = bpy.props.BoolProperty(default=False)  # type: ignore
        tree_type.omni_bind_show_advanced_info = bpy.props.BoolProperty(
            name="Advanced",
            description="显示bind缓存,数据块,子树编译缓存等高级调试信息",
            default=False,
        )  # type: ignore

    @classmethod
    def remove_tree_props(cls, tree_type):
        for attr in [
            "omni_bind_pending_rules",
            "omni_bind_runtime_items",
            "omni_bind_is_rebuilding",
            "omni_bind_show_advanced_info",
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
        header = box.row(align=True)
        header.label(text="Omni动态面板", icon="DRIVER")
        if hasattr(tree, "omni_bind_show_advanced_info"):
            header.prop(tree, "omni_bind_show_advanced_info", text="", icon="PREFERENCES")

        if not hasattr(tree, "omni_bind_runtime_items"):
            box.label(text="Bind system not installed", icon="ERROR")
            return

        if len(tree.omni_bind_runtime_items) == 0:
            box.label(text="无动态参数", icon="INFO")
            return

        runtime_entries = []
        has_cache_warning = False
        for item in tree.omni_bind_runtime_items:
            rule = item.get_rule()
            debug_info = _runtime_debug_info(tree, rule)
            cache_ready = (
                debug_info["has_live_context"]
                and debug_info["has_source_node"]
                and debug_info["has_processor_graph"]
            )
            has_cache_warning = has_cache_warning or not cache_ready
            runtime_entries.append((item, rule, debug_info, cache_ready))

        if has_cache_warning:
            warning = box.row(align=True)
            warning.alert = True
            warning.label(text="Bind运行缓存丢失或过时，请再次运行树。", icon="ERROR")
        else:
            box.label(text="运行缓存就绪", icon="CHECKMARK")

        show_advanced = bool(getattr(tree, "omni_bind_show_advanced_info", False))

        for item, rule, debug_info, cache_ready in runtime_entries:
            source = rule.get("source") or {}

            card = box.box()
            title = card.row(align=True)
            title.alert = not cache_ready
            title.label(text=item.name or item.key, icon="RNA")
            if cache_ready:
                title.label(text="缓存就绪", icon="CHECKMARK")
            else:
                title.label(text="缓存丢失", icon="ERROR")

            col = card.column(align=True)
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

            if not cache_ready:
                warning = card.row(align=True)
                warning.alert = True
                warning.label(text="缓存丢失，更新可能无法到达子树。", icon="ERROR")

            if not show_advanced:
                continue

            status = card.column(align=True)
            node_name = str(source.get("node_name") or "")
            if node_name:
                node_icon = "NODE" if debug_info["has_source_node"] else "ERROR"
                node_text = f"源Node: {node_name}" if debug_info["has_source_node"] else f"源Node丢失: {node_name}"
                status.label(text=node_text, icon=node_icon)

            processor_icon = "CHECKMARK" if debug_info["has_processor_graph"] else "ERROR"
            processor_text = "运行缓存: 就绪" if debug_info["has_processor_graph"] else "运行缓存: 丢失"
            status.label(text=processor_text, icon=processor_icon)

            datablocks = debug_info["datablocks"]
            if debug_info["has_live_context"]:
                if datablocks:
                    status.label(text="Datablocks使用中: ", icon="OUTLINER_OB_GROUP_INSTANCE")
                    for datablock in datablocks[:8]:
                        status.label(text=_format_datablock_label(datablock), icon="LIBRARY_DATA_DIRECT")
                    if len(datablocks) > 8:
                        status.label(text=f"... {len(datablocks) - 8} more", icon="BLANK1")
                else:
                    status.label(text="Datablocks使用中: 无", icon="INFO")
            else:
                status.label(text="Datablocks使用中: <丢失运行cache>", icon="ERROR")

            if item.description:
                status.label(text=item.description, icon="BLANK1")


# =============================================================================
# 注册与卸载
# =============================================================================


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
