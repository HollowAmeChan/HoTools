import uuid


_COMMITTED_CACHE = {}


def _snapshot_value(value):
    if value is None or isinstance(value, (str, bool, int, float)):
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

    def descend_batch_item(self, node, child_tree, item_index):
        node_uid = ensure_node_runtime_uid(node)
        child_key = _runtime_tree_key(child_tree)
        return RuntimeCacheContext(
            self.run,
            self.path + (f"batch:{node_uid}:item:{int(item_index)}:{child_key}",),
        )


def begin_run(root_tree):
    return RuntimeCacheContext(RuntimeCacheRun(root_tree))


def finish_run(context):
    if context is None:
        return

    run = context.run
    if run.failed:
        run.pending.clear()
        run.deleted_namespaces.clear()
        run.deleted_keys.clear()
        return

    for namespace in run.deleted_namespaces:
        _COMMITTED_CACHE.pop(namespace, None)

    for namespace, keys in run.deleted_keys.items():
        if namespace in run.deleted_namespaces:
            continue
        target = _COMMITTED_CACHE.get(namespace)
        if not target:
            continue
        for key in keys:
            target.pop(key, None)
        if not target:
            _COMMITTED_CACHE.pop(namespace, None)

    for namespace, values in run.pending.items():
        target = _COMMITTED_CACHE.setdefault(namespace, {})
        for key, value in values.items():
            target[key] = _snapshot_value(value)
    run.pending.clear()
    run.deleted_namespaces.clear()
    run.deleted_keys.clear()


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
    values = context.run.pending.setdefault(namespace, {})
    values[key] = _snapshot_value(value)


def snapshot_cache(context):
    if context is None:
        return {}

    namespace = context.namespace()
    values = {}

    if namespace not in context.run.deleted_namespaces:
        values.update(_COMMITTED_CACHE.get(namespace, {}))

    for key in context.run.deleted_keys.get(namespace, set()):
        values.pop(key, None)

    values.update(context.run.pending.get(namespace, {}))
    return {key: _snapshot_value(value) for key, value in values.items()}


def delete_cache(context, key):
    if context is None or not key:
        return 0

    namespace = context.namespace()
    visible_before = snapshot_cache(context)

    pending_values = context.run.pending.get(namespace)
    if pending_values is not None:
        pending_values.pop(key, None)
        if not pending_values:
            context.run.pending.pop(namespace, None)

    context.run.deleted_keys.setdefault(namespace, set()).add(key)
    return 1 if key in visible_before else 0


def clear_namespace(context):
    if context is None:
        return 0

    namespace = context.namespace()
    visible_before = snapshot_cache(context)
    context.run.pending.pop(namespace, None)
    context.run.deleted_keys.pop(namespace, None)
    context.run.deleted_namespaces.add(namespace)
    return len(visible_before)


def clear_all():
    _COMMITTED_CACHE.clear()


def clear_root_tree(tree):
    root_key = _runtime_tree_key(tree)
    for namespace in list(_COMMITTED_CACHE.keys()):
        if namespace[0] == root_key:
            del _COMMITTED_CACHE[namespace]
