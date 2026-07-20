import importlib.util
import os
import sys


_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "OmniTiming.py")
_SPEC = importlib.util.spec_from_file_location("omni_runtime_timing_test_module", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
OmniRuntimeTiming = _MODULE.OmniRuntimeTiming


class _Tree:
    def __init__(self, pointer):
        self.pointer = pointer

    def as_pointer(self):
        return self.pointer


def test_consumers_aggregate_independently():
    tree = _Tree(42)
    OmniRuntimeTiming.clear()
    OmniRuntimeTiming.OVERLAY_INTERVAL = 0.0
    OmniRuntimeTiming.record(
        "Tree",
        "frame:42",
        {"step1:Slow:call": 0.004, "total": 0.005},
        tree_ref=tree,
        interval=60.0,
        console_enabled=True,
        overlay_enabled=True,
        node_stages={"step1:Slow:call": "Slow"},
    )

    snapshots = OmniRuntimeTiming.flush()
    assert [item.consumer for item in snapshots] == [OmniRuntimeTiming.OVERLAY]
    assert snapshots[0].sample_count == 1
    assert snapshots[0].node_totals == {"Slow": 0.004}

    snapshots = OmniRuntimeTiming.flush(force=True)
    assert [item.consumer for item in snapshots] == [OmniRuntimeTiming.CONSOLE]
    assert snapshots[0].totals["total"] == 0.005


def test_disabling_one_consumer_discards_its_pending_window():
    tree = _Tree(84)
    OmniRuntimeTiming.clear()
    OmniRuntimeTiming.record(
        "Tree",
        "tree:84",
        {"step1:Node:call": 0.002},
        tree_ref=tree,
        console_enabled=True,
    )
    OmniRuntimeTiming.record(
        "Tree",
        "tree:84",
        {"step1:Node:call": 0.003},
        tree_ref=tree,
        console_enabled=False,
        overlay_enabled=True,
        node_stages={"step1:Node:call": "Node"},
    )

    snapshots = OmniRuntimeTiming.flush(force=True)
    assert [item.consumer for item in snapshots] == [OmniRuntimeTiming.OVERLAY]
    assert snapshots[0].node_totals == {"Node": 0.003}


def test_overlay_reenable_emits_first_manual_sample_immediately():
    tree = _Tree(126)
    OmniRuntimeTiming.clear()
    OmniRuntimeTiming.OVERLAY_INTERVAL = 0.2
    OmniRuntimeTiming.record(
        "Tree",
        "tree:126",
        {"step1:Node:call": 0.001},
        tree_ref=tree,
        overlay_enabled=True,
        node_stages={"step1:Node:call": "Node"},
    )
    assert OmniRuntimeTiming.flush()
    OmniRuntimeTiming.clear_tree(tree, consumer=OmniRuntimeTiming.OVERLAY)

    OmniRuntimeTiming.record(
        "Tree",
        "tree:126",
        {"step1:Node:call": 0.002},
        tree_ref=tree,
        overlay_enabled=True,
        node_stages={"step1:Node:call": "Node"},
    )
    snapshots = OmniRuntimeTiming.flush()
    assert len(snapshots) == 1
    assert snapshots[0].node_totals == {"Node": 0.002}


def main():
    tests = (
        test_consumers_aggregate_independently,
        test_disabling_one_consumer_discards_its_pending_window,
        test_overlay_reenable_emits_first_manual_sample_immediately,
    )
    for test in tests:
        test()
        print(f"[PASS] {test.__name__}")
    print(f"runtime timing: {len(tests)}/{len(tests)} passed")


if __name__ == "__main__":
    main()
