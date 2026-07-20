import uuid
import time
import hashlib


_COMMITTED_CACHE = {}


class OmniCacheWriteIntent:
    def __init__(self, mode, value):
        self.mode = str(mode or "replace")
        self.value = value


class OmniCacheOwnerDict(dict):
    """
    零拷贝缓存载体：一个普通 dict，但实现了 omni_cache_dispose 协议。

    runtime cache 对实现了 omni_cache_dispose 的对象走零拷贝路径：
    - _snapshot_value 直接返回本体（读/写/提交都不深拷贝）；
    - _collect_cache_value_ids / _dispose_cache_value 把它当作不透明 owner，
      不再递归深入其内部（dict/list/numpy）。

    适用于物理这类「读→原地改→写回同一对象」的逐帧滚动状态：
    节点把 read_cache 返回的本体原地修改后按 replace 写回，提交时
    old is new，不产生 dispose，committed_ids 也只记一个顶层 id。

    用法：把要缓存的状态 dict 包成 OmniCacheOwnerDict(state)。
    它在所有 isinstance(x, dict) 检查下仍是 dict，物理代码无需改访问方式。
    """
    def omni_cache_dispose(self, reason):
        # 内部持有的都是 Python 容器 / numpy / bpy 引用，无需显式释放，
        # 交给 GC 即可。提供此方法只是为了让 runtime 识别为零拷贝 owner。
        return


def cache_replace(value):
    return OmniCacheWriteIntent("replace", value)


def cache_mutate(value):
    return OmniCacheWriteIntent("mutate", value)


def _is_write_intent(value):
    return isinstance(value, OmniCacheWriteIntent)


def _decode_write_intent(value):
    if _is_write_intent(value):
        return value
    return cache_replace(value)


def _intent_visible_value(value):
    if _is_write_intent(value):
        return value.value
    return value


def cache_visible_value(value):
    return _intent_visible_value(value)


def _has_cache_dispose(value):
    return callable(getattr(value, "omni_cache_dispose", None))


def _has_cache_debug_snapshot(value):
    return callable(getattr(value, "omni_cache_debug_snapshot", None))


def _collect_cache_value_ids(value, result=None, seen=None):
    value = _intent_visible_value(value)
    if result is None:
        result = set()
    if seen is None:
        seen = set()

    if value is None or isinstance(value, (str, bool, int, float)):
        return result

    value_id = id(value)
    if value_id in seen:
        return result
    seen.add(value_id)
    result.add(value_id)

    # dispose-owner（含可变缓存 owner）自管理其内容，与 snapshot/dispose
    # 的语义一致：不深入递归，只记录 owner 自身的 id（O(顶层)）。
    if _has_cache_dispose(value):
        return result

    if isinstance(value, dict):
        for item in value.values():
            _collect_cache_value_ids(item, result, seen)
        return result

    if isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_cache_value_ids(item, result, seen)

    return result


def _committed_value_ids():
    result = set()
    for values in _COMMITTED_CACHE.values():
        for value in values.values():
            _collect_cache_value_ids(value, result)
    return result


def _pending_replace_value_ids(run):
    result = set()
    for values in run.pending.values():
        for intent in values.values():
            intent = _decode_write_intent(intent)
            if intent.mode == "replace":
                _collect_cache_value_ids(intent.value, result)
    return result


def _dispose_cache_value(value, reason, seen=None, active_ids=None):
    value = _intent_visible_value(value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return

    if seen is None:
        seen = set()

    value_id = id(value)
    if value_id in seen:
        return
    if active_ids and value_id in active_ids:
        return
    seen.add(value_id)

    dispose_func = getattr(value, "omni_cache_dispose", None)
    if callable(dispose_func):
        dispose_func(str(reason or "dispose"))
        return

    if isinstance(value, dict):
        for item in value.values():
            _dispose_cache_value(item, reason, seen, active_ids)
        return

    if isinstance(value, (list, tuple, set)):
        for item in value:
            _dispose_cache_value(item, reason, seen, active_ids)


def _dispose_pending_intent(intent, reason, active_ids=None, seen=None):
    intent = _decode_write_intent(intent)
    if intent.mode != "replace":
        return
    value = intent.value
    _dispose_cache_value(value, reason, seen, active_ids)


def _debug_snapshot_value(value):
    value = _intent_visible_value(value)
    if _has_cache_debug_snapshot(value):
        debug_func = getattr(value, "omni_cache_debug_snapshot", None)
        try:
            return debug_func()
        except Exception:
            return repr(value)
    return _snapshot_value(value)


def _snapshot_value(value):
    value = _intent_visible_value(value)

    if value is None or isinstance(value, (str, bool, int, float)):
        return value

    if _has_cache_dispose(value):
        return value

    if hasattr(value, "as_pointer"):
        return value

    if isinstance(value, list):
        return [_snapshot_value(item) for item in value]

    if isinstance(value, tuple):
        return tuple(_snapshot_value(item) for item in value)

    if isinstance(value, dict):
        return {key: _snapshot_value(item) for key, item in value.items()}

    copy_func = getattr(value, "copy", None)
    if callable(copy_func):
        try:
            return copy_func()
        except Exception:
            pass

    try:
        return tuple(value)
    except Exception:
        pass

    return value


def _runtime_tree_key(tree):
    if tree is None:
        return "tree:<none>"

    try:
        return f"tree:{int(tree.as_pointer())}"
    except Exception:
        return f"tree:{id(tree)}"


def runtime_tree_key(tree):
    return _runtime_tree_key(tree)


def batch_item_identity(value):
    identity = None
    for name in ("omni_runtime_identity", "stable_id", "task_id", "slot_id", "source_id"):
        candidate = None
        if isinstance(value, dict):
            candidate = value.get(name)
        else:
            candidate = getattr(value, name, None)
        if callable(candidate):
            try:
                candidate = candidate()
            except Exception:
                candidate = None
        if candidate not in (None, ""):
            identity = (name, str(candidate))
            break
    if identity is None:
        session_uid = getattr(value, "session_uid", None)
        if session_uid not in (None, 0, ""):
            identity = ("session_uid", str(session_uid))
    if identity is None and hasattr(value, "as_pointer"):
        try:
            identity = (
                "bpy",
                value.__class__.__name__,
                str(getattr(value, "name_full", getattr(value, "name", "")) or ""),
                str(int(value.as_pointer())),
            )
        except Exception:
            identity = None
    if identity is None and isinstance(value, (str, bool, int, float, type(None))):
        identity = ("scalar", type(value).__name__, repr(value))
    if identity is None:
        identity = (
            "fallback",
            value.__class__.__module__,
            value.__class__.__qualname__,
            repr(value),
        )
    digest = hashlib.sha1(repr(identity).encode("utf-8")).hexdigest()[:20]
    return digest


def ensure_node_runtime_uid(node):
    uid = ""
    try:
        uid = str(getattr(node, "omni_runtime_uid", "") or "")
    except Exception:
        uid = ""

    if uid:
        return uid

    uid = uuid.uuid4().hex
    try:
        node.omni_runtime_uid = uid
    except Exception:
        return str(getattr(node, "name", "") or id(node))
    return uid


def ensure_tree_runtime_uids(tree):
    if tree is None or not hasattr(tree, "nodes"):
        return

    used = set()
    for node in tree.nodes:
        if not hasattr(node, "omni_runtime_uid"):
            continue

        try:
            uid = str(getattr(node, "omni_runtime_uid", "") or "")
        except Exception:
            uid = ""

        if not uid or uid in used:
            uid = uuid.uuid4().hex
            try:
                node.omni_runtime_uid = uid
            except Exception:
                uid = f"node:{getattr(node, 'name', id(node))}"

        used.add(uid)


def cache_key_for_node(node, explicit_key):
    key = str(explicit_key or "").strip()
    if key:
        return key
    return ensure_node_runtime_uid(node)


class RuntimeCacheRun:
    def __init__(self, root_tree):
        self.root_tree_key = _runtime_tree_key(root_tree)
        self.pending = {}
        self.discarded_pending = []
        self.deleted_namespaces = set()
        self.deleted_keys = {}
        self.failed = False


class RuntimeCacheContext:
    def __init__(self, run, path=()):
        self.run = run
        self.path = tuple(path)

    def namespace(self):
        return (self.run.root_tree_key, self.path)

    def mark_failed(self):
        self.run.failed = True

    def descend_group(self, node, child_tree):
        node_uid = ensure_node_runtime_uid(node)
        child_key = _runtime_tree_key(child_tree)
        return RuntimeCacheContext(
            self.run,
            self.path + (f"group:{node_uid}:{child_key}",),
        )

    def descend_batch_item(
        self,
        node,
        child_tree,
        item_index,
        item_value=None,
        item_identity=None,
        identity_occurrence=0,
    ):
        node_uid = ensure_node_runtime_uid(node)
        child_key = _runtime_tree_key(child_tree)
        item_identity = str(item_identity or batch_item_identity(item_value))
        return RuntimeCacheContext(
            self.run,
            self.path + (
                f"batchv2:{node_uid}:item:{item_identity}:"
                f"occ:{int(identity_occurrence)}:{child_key}",
            ),
        )


def begin_run(root_tree):
    return RuntimeCacheContext(RuntimeCacheRun(root_tree))


def finish_run(context, phases=None):
    if context is None:
        return

    run = context.run
    if run.failed:
        seen = set()
        active_ids = _committed_value_ids()
        for intent in run.discarded_pending:
            _dispose_pending_intent(intent, "run_failed", active_ids=active_ids, seen=seen)
        for values in run.pending.values():
            for intent in values.values():
                _dispose_pending_intent(intent, "run_failed", active_ids=active_ids, seen=seen)
        run.pending.clear()
        run.discarded_pending.clear()
        run.deleted_namespaces.clear()
        run.deleted_keys.clear()
        return

    # 两阶段：先把所有缓存变更应用到最终状态、收集待回收的旧值候选；
    # 再用一次 committed_value_ids() 扫描（缓存最终可达集合）统一回收。
    # 这样 committed_ids 从 O(K×N)（每次 dispose 都重扫）降到 O(N)。
    t_snapshot = 0.0

    dispose_candidates = []  # [(value, reason)]

    # ---- 阶段 1：应用删除 / 替换，收集待回收旧值（不触碰 committed_ids）----
    for namespace in run.deleted_namespaces:
        values = _COMMITTED_CACHE.pop(namespace, None)
        if values:
            for value in values.values():
                dispose_candidates.append((value, "clear_namespace"))

    for namespace, keys in run.deleted_keys.items():
        if namespace in run.deleted_namespaces:
            continue
        target = _COMMITTED_CACHE.get(namespace)
        if not target:
            continue
        for key in keys:
            value = target.pop(key, None)
            dispose_candidates.append((value, "delete"))
        if not target:
            _COMMITTED_CACHE.pop(namespace, None)

    for intent in run.discarded_pending:
        intent = _decode_write_intent(intent)
        if intent.mode == "replace":
            dispose_candidates.append((intent.value, "discard_pending"))

    for namespace, values in run.pending.items():
        target = _COMMITTED_CACHE.setdefault(namespace, {})
        for key, intent in values.items():
            intent = _decode_write_intent(intent)
            if intent.mode == "replace":
                # write_cache 在排入 pending 时已把值拷成缓存私有副本，
                # 此处直接采用，无需再次深拷贝（消除冗余的提交期快照）。
                new_value = intent.value
                old_value = target.get(key)
                target[key] = new_value
                if old_value is not None and old_value is not new_value:
                    dispose_candidates.append((old_value, "replace"))
                continue
            if intent.mode == "mutate":
                if key not in target:
                    raise RuntimeError("cache_mutate target is missing from committed cache")
                old_value = target[key]
                if old_value is not intent.value:
                    raise RuntimeError("cache_mutate value is not the committed cache owner")
                target[key] = old_value
                continue
            raise RuntimeError(f"unknown cache write mode: {intent.mode}")

    # ---- 阶段 2：缓存已到最终状态，扫描一次可达集合后统一回收 ----
    t_ids = 0.0
    t_dispose = 0.0
    if dispose_candidates:
        s = time.perf_counter()
        active_ids = _committed_value_ids()
        t_ids = time.perf_counter() - s

        disposed_seen = set()
        s = time.perf_counter()
        for value, reason in dispose_candidates:
            _dispose_cache_value(value, reason, seen=disposed_seen, active_ids=active_ids)
        t_dispose = time.perf_counter() - s

    run.pending.clear()
    run.discarded_pending.clear()
    run.deleted_namespaces.clear()
    run.deleted_keys.clear()

    if phases is not None:
        phases["[finish] committed_ids"] = phases.get("[finish] committed_ids", 0.0) + t_ids
        phases["[finish] snapshot"] = phases.get("[finish] snapshot", 0.0) + t_snapshot
        phases["[finish] dispose"] = phases.get("[finish] dispose", 0.0) + t_dispose


def read_cache(context, key):
    if context is None:
        return False, None

    namespace = context.namespace()
    if namespace in context.run.deleted_namespaces:
        return False, None

    deleted_keys = context.run.deleted_keys.get(namespace, set())
    if key in deleted_keys:
        return False, None

    namespace_values = _COMMITTED_CACHE.get(namespace, {})
    if key not in namespace_values:
        return False, None
    return True, _snapshot_value(namespace_values[key])


def write_cache(context, key, value):
    if context is None:
        return

    namespace = context.namespace()
    intent = _decode_write_intent(value)
    if intent.mode not in {"replace", "mutate"}:
        raise ValueError(f"unknown cache write mode: {intent.mode}")

    if intent.mode == "mutate":
        if namespace in context.run.deleted_namespaces:
            raise ValueError("cache_mutate cannot target a namespace scheduled for deletion")
        if key in context.run.deleted_keys.get(namespace, set()):
            raise ValueError("cache_mutate cannot target a key scheduled for deletion")
        namespace_values = _COMMITTED_CACHE.get(namespace)
        if namespace_values is None or key not in namespace_values:
            raise ValueError("cache_mutate target is missing from committed cache")
        if namespace_values[key] is not intent.value:
            raise ValueError("cache_mutate value is not the committed cache owner")

    values = context.run.pending.setdefault(namespace, {})
    previous = values.get(key)
    if previous is not None:
        previous_intent = _decode_write_intent(previous)
        if previous_intent.mode == "replace" and previous_intent.value is not intent.value:
            context.run.discarded_pending.append(previous_intent)
    if intent.mode == "replace":
        intent = cache_replace(_snapshot_value(intent.value))
    values[key] = intent


def snapshot_cache(context):
    if context is None:
        return {}

    namespace = context.namespace()
    values = {}

    if namespace not in context.run.deleted_namespaces:
        values.update(_COMMITTED_CACHE.get(namespace, {}))

    for key in context.run.deleted_keys.get(namespace, set()):
        values.pop(key, None)

    values.update({
        key: _intent_visible_value(value)
        for key, value in context.run.pending.get(namespace, {}).items()
    })
    return {key: _debug_snapshot_value(value) for key, value in values.items()}


def delete_cache(context, key):
    if context is None or not key:
        return 0

    namespace = context.namespace()
    visible_before = snapshot_cache(context)

    pending_values = context.run.pending.get(namespace)
    if pending_values is not None:
        pending_value = pending_values.pop(key, None)
        if pending_value is not None:
            context.run.discarded_pending.append(pending_value)
        if not pending_values:
            context.run.pending.pop(namespace, None)

    context.run.deleted_keys.setdefault(namespace, set()).add(key)
    return 1 if key in visible_before else 0


def clear_namespace(context):
    if context is None:
        return 0

    namespace = context.namespace()
    visible_before = snapshot_cache(context)
    pending_values = context.run.pending.pop(namespace, None)
    if pending_values:
        context.run.discarded_pending.extend(pending_values.values())
    context.run.deleted_keys.pop(namespace, None)
    context.run.deleted_namespaces.add(namespace)
    return len(visible_before)


def clear_all():
    seen = set()
    for values in _COMMITTED_CACHE.values():
        for value in values.values():
            _dispose_cache_value(value, "clear_all", seen)
    _COMMITTED_CACHE.clear()


def _compiled_namespace_contract(compiled, path):
    if compiled is None:
        return None
    path = tuple(path or ())
    if not path:
        return getattr(compiled, "runtime_cache_contract", None)
    segment = str(path[0])
    for kind, node_uid, child_key, child in (
        getattr(compiled, "runtime_namespace_children", ()) or ()
    ):
        if kind == "group":
            if segment != f"group:{node_uid}:{child_key}":
                continue
        elif kind == "batch":
            prefix = f"batchv2:{node_uid}:item:"
            suffix = f":{child_key}"
            if not (segment.startswith(prefix) and segment.endswith(suffix)):
                continue
        else:
            continue
        return _compiled_namespace_contract(child, path[1:])
    return None


def _contracts_compatible(previous, current):
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return False
    return bool(
        previous.get("schema") == current.get("schema") == 1
        and previous.get("preservable", False)
        and current.get("preservable", False)
        and previous.get("signature") == current.get("signature")
    )


def reconcile_root_tree(tree, previous_compiled, current_compiled):
    root_key = _runtime_tree_key(tree)
    removed_values = []
    preserved_namespaces = 0
    removed_namespaces = 0
    for namespace in list(_COMMITTED_CACHE.keys()):
        if namespace[0] != root_key:
            continue
        previous = _compiled_namespace_contract(previous_compiled, namespace[1])
        current = _compiled_namespace_contract(current_compiled, namespace[1])
        if _contracts_compatible(previous, current):
            preserved_namespaces += 1
            continue
        values = _COMMITTED_CACHE.pop(namespace, None)
        removed_namespaces += 1
        if values:
            removed_values.extend(values.values())
    active_ids = _committed_value_ids()
    seen = set()
    for value in removed_values:
        _dispose_cache_value(
            value,
            "recompile_incompatible",
            seen,
            active_ids=active_ids,
        )
    return {
        "preserved_namespaces": preserved_namespaces,
        "removed_namespaces": removed_namespaces,
    }


def clear_root_tree(tree, reason="clear_root_tree"):
    root_key = _runtime_tree_key(tree)
    removed_values = []
    for namespace in list(_COMMITTED_CACHE.keys()):
        if namespace[0] == root_key:
            values = _COMMITTED_CACHE.pop(namespace, None)
            if values:
                removed_values.extend(values.values())
    active_ids = _committed_value_ids()
    seen = set()
    for value in removed_values:
        _dispose_cache_value(value, reason, seen, active_ids=active_ids)
