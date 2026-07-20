# -*- coding: utf-8 -*-
"""Blender background regression tests for compile/runtime cache lifecycle."""

from __future__ import annotations

import importlib.util
import os
import sys
import types

import bpy


_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_OMNINODE_DIR = os.path.dirname(_TEST_DIR)
_NODE_TREE_DIR = os.path.join(_OMNINODE_DIR, "NodeTree")
_PACKAGE = "HoTools.OmniNode.NodeTree"


def _install_package(name, path):
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [path]
    module.__package__ = name
    sys.modules[name] = module


_install_package("HoTools", os.path.dirname(os.path.dirname(_NODE_TREE_DIR)))
_install_package("HoTools.OmniNode", os.path.dirname(_NODE_TREE_DIR))
_install_package(_PACKAGE, _NODE_TREE_DIR)


def _load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_NODE_TREE_DIR, filename))
    module = importlib.util.module_from_spec(spec)
    module.__package__ = name.rsplit(".", 1)[0]
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runtime_state = _load_module(f"{_PACKAGE}.OmniRuntimeState", "OmniRuntimeState.py")


class _Compiler:
    compile = None


compiler_module = types.ModuleType(f"{_PACKAGE}.OmniCompiler")
compiler_module.OmniCompiler = _Compiler
sys.modules[compiler_module.__name__] = compiler_module

executor_module = types.ModuleType(f"{_PACKAGE}.OmniExecutor")
executor_module.OmniExecutor = type("OmniExecutor", (), {"run": staticmethod(lambda *args, **kwargs: None)})
sys.modules[executor_module.__name__] = executor_module

ir_module = types.ModuleType(f"{_PACKAGE}.OmniIR")
ir_module.SubtreeCall = type("SubtreeCall", (), {})
ir_module.BatchSubtreeCall = type("BatchSubtreeCall", (), {})
sys.modules[ir_module.__name__] = ir_module

debug_module = types.ModuleType(f"{_PACKAGE}.OmniDebug")
debug_module.OmniDebug = type(
    "OmniDebug",
    (),
    {
        "format_runtime_timing_report": staticmethod(lambda *args, **kwargs: []),
    },
)
sys.modules[debug_module.__name__] = debug_module

timing_module = types.ModuleType(f"{_PACKAGE}.OmniTiming")
timing_module.OmniRuntimeTiming = type(
    "OmniRuntimeTiming",
    (),
    {
        "CONSOLE": "console",
        "OVERLAY": "overlay",
        "is_enabled": staticmethod(lambda tree: False),
        "record": staticmethod(lambda *args, **kwargs: None),
        "flush": staticmethod(lambda *args, **kwargs: ()),
        "clear_tree": staticmethod(lambda *args, **kwargs: None),
        "clear": staticmethod(lambda: None),
    },
)
sys.modules[timing_module.__name__] = timing_module

draw_module = types.ModuleType(f"{_PACKAGE}.OmniNodeDraw")
draw_module.clear_tree = lambda tree: None
draw_module.DrawRuntimeTiming = type(
    "DrawRuntimeTiming",
    (),
    {
        "ensure_handler": staticmethod(lambda: None),
        "tag_tree": staticmethod(lambda tree: None),
        "clear_tree": staticmethod(lambda tree: None),
        "update_tree": staticmethod(lambda *args, **kwargs: None),
    },
)
draw_module.DrawCompileFlow = type(
    "DrawCompileFlow",
    (),
    {
        "clear_tree": staticmethod(lambda tree: None),
        "tag_tree": staticmethod(lambda tree: None),
        "update_tree": staticmethod(lambda *args, **kwargs: None),
    },
)
sys.modules[draw_module.__name__] = draw_module

operator_module = types.ModuleType(f"{_PACKAGE}.OmniNodeOperator")
operator_module.HO_UL_GraphNodeIO = type("HO_UL_GraphNodeIO", (), {})
operator_module.OP_IOItemAdd = type("OP_IOItemAdd", (), {"bl_idname": "omni.test_add"})
operator_module.OP_IOItemRemove = type("OP_IOItemRemove", (), {"bl_idname": "omni.test_remove"})
operator_module.OP_IOItemMove = type("OP_IOItemMove", (), {"bl_idname": "omni.test_move"})
operator_module.OmniGraphNodeIOItem = type("OmniGraphNodeIOItem", (bpy.types.PropertyGroup,), {})
sys.modules[operator_module.__name__] = operator_module

tree_module = _load_module(f"{_PACKAGE}.OmniNodeTree", "OmniNodeTree.py")


class _FakeTree:
    debug_compile = False

    def __init__(self, pointer, name):
        self._pointer = pointer
        self.name = name
        self.clear_run_state_count = 0

    def as_pointer(self):
        return self._pointer

    def _clear_run_state(self, full=True):
        self.clear_run_state_count += 1


class _CompiledGraph:
    def __init__(
        self,
        marker,
        signature=None,
        *,
        preservable=True,
        namespace_children=(),
    ):
        self.marker = marker
        self.clear_count = 0
        self.runtime_cache_contract = (
            {
                "schema": 1,
                "preservable": bool(preservable),
                "signature": signature,
            }
            if signature is not None else None
        )
        self.runtime_namespace_children = tuple(namespace_children)

    def clear_reg_arrays(self):
        self.clear_count += 1


class _Disposable:
    def __init__(self):
        self.reasons = []

    def omni_cache_dispose(self, reason):
        self.reasons.append(reason)


def _write_cache(tree, key, value):
    context = runtime_state.begin_run(tree)
    runtime_state.write_cache(context, key, value)
    runtime_state.finish_run(context)


def _read_cache(tree, key):
    context = runtime_state.begin_run(tree)
    hit, value = runtime_state.read_cache(context, key)
    runtime_state.finish_run(context)
    return hit, value


def _compile(tree, force=False):
    return tree_module.OmniNodeTree.compile_cached(tree, force=force)


def test_successful_compile_without_manifest_clears_only_its_root():
    tree = _FakeTree(1001, "compile-root")
    other_tree = _FakeTree(1002, "other-root")
    owner = _Disposable()
    other_owner = _Disposable()
    _write_cache(tree, "world", owner)
    _write_cache(other_tree, "world", other_owner)

    calls = []

    def compile_ok(compiled_tree, debug=False):
        calls.append((compiled_tree, debug))
        return _CompiledGraph("fresh")

    _Compiler.compile = staticmethod(compile_ok)
    compiled = _compile(tree, force=True)

    assert compiled.marker == "fresh"
    assert calls == [(tree, False)]
    assert tree.clear_run_state_count == 1
    assert _read_cache(tree, "world") == (False, None)
    assert owner.reasons == ["recompile_incompatible"]
    assert _read_cache(other_tree, "world") == (True, other_owner)
    assert other_owner.reasons == []


def test_compatible_force_compile_preserves_runtime_owner():
    tree = _FakeTree(1101, "compatible-root")
    owner = _Disposable()
    _write_cache(tree, "world", owner)
    previous = _CompiledGraph("previous", ("world-owner", "v1"))
    tree_module._COMPILED_TREE_CACHE[tree_module._tree_cache_key(tree)] = previous

    def compile_ok(*args, **kwargs):
        return _CompiledGraph("fresh", ("world-owner", "v1"))

    _Compiler.compile = staticmethod(compile_ok)
    compiled = _compile(tree, force=True)

    assert compiled.marker == "fresh"
    assert previous.clear_count == 1
    assert _read_cache(tree, "world") == (True, owner)
    assert owner.reasons == []


def test_incompatible_force_compile_disposes_runtime_owner():
    tree = _FakeTree(1201, "incompatible-root")
    owner = _Disposable()
    _write_cache(tree, "world", owner)
    previous = _CompiledGraph("previous", ("world-owner", "v1"))
    tree_module._COMPILED_TREE_CACHE[tree_module._tree_cache_key(tree)] = previous

    def compile_ok(*args, **kwargs):
        return _CompiledGraph("fresh", ("world-owner", "v2"))

    _Compiler.compile = staticmethod(compile_ok)
    _compile(tree, force=True)

    assert _read_cache(tree, "world") == (False, None)
    assert owner.reasons == ["recompile_incompatible"]


def test_non_preservable_contract_clears_runtime_owner():
    tree = _FakeTree(1301, "dynamic-key-root")
    owner = _Disposable()
    _write_cache(tree, "world", owner)
    previous = _CompiledGraph(
        "previous", ("dynamic-owner",), preservable=False
    )
    tree_module._COMPILED_TREE_CACHE[tree_module._tree_cache_key(tree)] = previous

    def compile_ok(*args, **kwargs):
        return _CompiledGraph("fresh", ("dynamic-owner",), preservable=False)

    _Compiler.compile = staticmethod(compile_ok)
    _compile(tree, force=True)

    assert _read_cache(tree, "world") == (False, None)
    assert owner.reasons == ["recompile_incompatible"]


def test_batch_namespace_follows_stable_item_identity():
    tree = _FakeTree(1401, "batch-root")
    child_tree = _FakeTree(1402, "batch-child")
    node = types.SimpleNamespace(omni_runtime_uid="batch-node")
    context = runtime_state.begin_run(tree)
    first_a = context.descend_batch_item(
        node, child_tree, 0, {"stable_id": "item-a"}
    ).namespace()
    first_b = context.descend_batch_item(
        node, child_tree, 1, {"stable_id": "item-b"}
    ).namespace()
    reordered_b = context.descend_batch_item(
        node, child_tree, 0, {"stable_id": "item-b"}
    ).namespace()
    reordered_a = context.descend_batch_item(
        node, child_tree, 1, {"stable_id": "item-a"}
    ).namespace()
    runtime_state.finish_run(context)

    assert first_a == reordered_a
    assert first_b == reordered_b
    assert first_a != first_b
    assert first_a[1][0].startswith("batchv2:batch-node:item:")
    duplicate_first = context.descend_batch_item(
        node,
        child_tree,
        0,
        {"stable_id": "duplicate"},
        identity_occurrence=0,
    ).namespace()
    duplicate_second = context.descend_batch_item(
        node,
        child_tree,
        1,
        {"stable_id": "duplicate"},
        identity_occurrence=1,
    ).namespace()
    assert duplicate_first != duplicate_second


def test_nested_namespace_contracts_reconcile_independently():
    tree = _FakeTree(1501, "nested-root")
    group_tree = _FakeTree(1502, "group-child")
    batch_tree = _FakeTree(1503, "batch-child")
    group_node = types.SimpleNamespace(omni_runtime_uid="group-node")
    batch_node = types.SimpleNamespace(omni_runtime_uid="batch-node")
    group_owner = _Disposable()
    batch_owner = _Disposable()

    context = runtime_state.begin_run(tree)
    group_context = context.descend_group(group_node, group_tree)
    batch_context = context.descend_batch_item(
        batch_node,
        batch_tree,
        0,
        {"stable_id": "item-a"},
    )
    runtime_state.write_cache(group_context, "world", group_owner)
    runtime_state.write_cache(batch_context, "world", batch_owner)
    runtime_state.finish_run(context)

    previous_group = _CompiledGraph("previous-group", ("group-owner", "v1"))
    previous_batch = _CompiledGraph("previous-batch", ("batch-owner", "v1"))
    previous = _CompiledGraph(
        "previous",
        ("root", "v1"),
        namespace_children=(
            (
                "group",
                "group-node",
                runtime_state.runtime_tree_key(group_tree),
                previous_group,
            ),
            (
                "batch",
                "batch-node",
                runtime_state.runtime_tree_key(batch_tree),
                previous_batch,
            ),
        ),
    )
    tree_module._COMPILED_TREE_CACHE[tree_module._tree_cache_key(tree)] = previous

    def compile_ok(*args, **kwargs):
        fresh_group = _CompiledGraph("fresh-group", ("group-owner", "v1"))
        fresh_batch = _CompiledGraph("fresh-batch", ("batch-owner", "v2"))
        return _CompiledGraph(
            "fresh",
            ("root", "v1"),
            namespace_children=(
                (
                    "group",
                    "group-node",
                    runtime_state.runtime_tree_key(group_tree),
                    fresh_group,
                ),
                (
                    "batch",
                    "batch-node",
                    runtime_state.runtime_tree_key(batch_tree),
                    fresh_batch,
                ),
            ),
        )

    _Compiler.compile = staticmethod(compile_ok)
    _compile(tree, force=True)

    context = runtime_state.begin_run(tree)
    group_context = context.descend_group(group_node, group_tree)
    batch_context = context.descend_batch_item(
        batch_node,
        batch_tree,
        0,
        {"stable_id": "item-a"},
    )
    assert runtime_state.read_cache(group_context, "world") == (
        True,
        group_owner,
    )
    assert runtime_state.read_cache(batch_context, "world") == (False, None)
    runtime_state.finish_run(context)
    assert group_owner.reasons == []
    assert batch_owner.reasons == ["recompile_incompatible"]


def test_compile_cache_hit_preserves_runtime_cache():
    tree = _FakeTree(2001, "cache-hit-root")
    owner = _Disposable()
    _write_cache(tree, "world", owner)
    cached = _CompiledGraph("cached")
    tree_module._COMPILED_TREE_CACHE[tree_module._tree_cache_key(tree)] = cached

    def compile_unexpected(*args, **kwargs):
        raise AssertionError("compiler must not run on a cache hit")

    _Compiler.compile = staticmethod(compile_unexpected)
    assert _compile(tree, force=False) is cached
    assert tree.clear_run_state_count == 0
    assert _read_cache(tree, "world") == (True, owner)
    assert owner.reasons == []


def test_failed_compile_preserves_runtime_and_previous_compiled_graph():
    tree = _FakeTree(3001, "failed-root")
    owner = _Disposable()
    _write_cache(tree, "world", owner)
    previous = _CompiledGraph("previous")
    cache_key = tree_module._tree_cache_key(tree)
    tree_module._COMPILED_TREE_CACHE[cache_key] = previous

    def compile_failed(*args, **kwargs):
        raise RuntimeError("expected compile failure")

    _Compiler.compile = staticmethod(compile_failed)
    try:
        _compile(tree, force=True)
    except RuntimeError as exc:
        assert str(exc) == "expected compile failure"
    else:
        raise AssertionError("failed compile did not raise")

    assert tree.clear_run_state_count == 1
    assert tree_module._COMPILED_TREE_CACHE[cache_key] is previous
    assert _read_cache(tree, "world") == (True, owner)
    assert owner.reasons == []


def main():
    tests = (
        test_successful_compile_without_manifest_clears_only_its_root,
        test_compatible_force_compile_preserves_runtime_owner,
        test_incompatible_force_compile_disposes_runtime_owner,
        test_non_preservable_contract_clears_runtime_owner,
        test_batch_namespace_follows_stable_item_identity,
        test_nested_namespace_contracts_reconcile_independently,
        test_compile_cache_hit_preserves_runtime_cache,
        test_failed_compile_preserves_runtime_and_previous_compiled_graph,
    )
    failures = []
    try:
        for test in tests:
            runtime_state.clear_all()
            tree_module._COMPILED_TREE_CACHE.clear()
            try:
                test()
                print(f"[PASS] {test.__name__}")
            except Exception as exc:
                failures.append((test.__name__, exc))
                print(f"[FAIL] {test.__name__}: {exc}")
    finally:
        runtime_state.clear_all()
        tree_module._COMPILED_TREE_CACHE.clear()

    if failures:
        raise SystemExit(1)
    print(f"compile cache lifecycle: {len(tests)}/{len(tests)} passed")


if __name__ == "__main__":
    main()
