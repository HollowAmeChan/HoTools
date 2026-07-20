import importlib.util
import os
import sys


_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(os.path.dirname(_TEST_DIR), "NodeTree", "OmniTiming.py")
_SPEC = importlib.util.spec_from_file_location("omni_runtime_timing_test_module", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
OmniRuntimeTiming = _MODULE.OmniRuntimeTiming


class _Tree:
    def __init__(self, pointer, *, show=False, sample_interval=3.0):
        self.pointer = pointer
        self.show_runtime_timing = show
        self.runtime_timing_sample_interval = sample_interval

    def as_pointer(self):
        return self.pointer


def test_overlay_sampling_defaults_to_three_seconds():
    tree = _Tree(42)
    OmniRuntimeTiming.clear()
    assert OmniRuntimeTiming.DEFAULT_OVERLAY_SAMPLE_INTERVAL == 3.0
    tree.show_runtime_timing = True
    assert OmniRuntimeTiming.take_overlay_sample(tree, now=10.0)
    assert not OmniRuntimeTiming.take_overlay_sample(tree, now=12.99)
    assert OmniRuntimeTiming.take_overlay_sample(tree, now=13.0)


def test_disabled_overlay_does_not_read_the_clock():
    tree = _Tree(63, show=False)
    original = _MODULE.time.perf_counter
    try:
        def unexpected_clock_read():
            raise AssertionError("disabled overlay must not read perf_counter")

        _MODULE.time.perf_counter = unexpected_clock_read
        assert not OmniRuntimeTiming.take_overlay_sample(tree)
    finally:
        _MODULE.time.perf_counter = original


def test_root_and_subtrees_share_one_gate_clock_read():
    root = _Tree(72, show=True)
    child = _Tree(73, show=True)
    OmniRuntimeTiming.clear()
    gate = {}
    clock_reads = []
    original = _MODULE.time.perf_counter
    try:
        def count_clock_read():
            clock_reads.append(True)
            return 30.0

        _MODULE.time.perf_counter = count_clock_read
        assert OmniRuntimeTiming.take_overlay_sample(root, gate=gate)
        assert OmniRuntimeTiming.take_overlay_sample(child, gate=gate)
    finally:
        _MODULE.time.perf_counter = original
    assert len(clock_reads) == 1
    assert gate == {"now": 30.0}


def test_console_aggregates_while_overlay_keeps_one_direct_sample():
    tree = _Tree(84)
    OmniRuntimeTiming.clear()
    OmniRuntimeTiming.record(
        "Tree",
        "frame:84",
        {"step1:Slow:call": 0.001, "total": 0.002},
        tree_ref=tree,
        interval=60.0,
        console_enabled=True,
    )
    OmniRuntimeTiming.record(
        "Tree",
        "frame:84",
        {"step1:Slow:call": 0.004, "total": 0.005},
        tree_ref=tree,
        interval=60.0,
        console_enabled=True,
        overlay_sampled=True,
        node_stages={"step1:Slow:call": "Slow"},
    )

    snapshots = OmniRuntimeTiming.flush()
    assert [item.consumer for item in snapshots] == [OmniRuntimeTiming.OVERLAY]
    assert snapshots[0].sample_count == 1
    assert snapshots[0].node_totals == {"Slow": 0.004}

    snapshots = OmniRuntimeTiming.flush(force=True)
    assert [item.consumer for item in snapshots] == [OmniRuntimeTiming.CONSOLE]
    assert snapshots[0].sample_count == 2
    assert snapshots[0].totals["total"] == 0.007


def test_new_overlay_sample_replaces_instead_of_averaging():
    tree = _Tree(126)
    OmniRuntimeTiming.clear()
    OmniRuntimeTiming.record(
        "Tree",
        "tree:126",
        {"step1:Node:call": 0.001},
        tree_ref=tree,
        overlay_sampled=True,
        node_stages={"step1:Node:call": "Node"},
    )
    OmniRuntimeTiming.record(
        "Tree",
        "tree:126",
        {"step1:Node:call": 0.005},
        tree_ref=tree,
        overlay_sampled=True,
        node_stages={"step1:Node:call": "Node"},
    )

    snapshots = OmniRuntimeTiming.flush()
    assert [item.consumer for item in snapshots] == [OmniRuntimeTiming.OVERLAY]
    assert snapshots[0].sample_count == 1
    assert snapshots[0].node_totals == {"Node": 0.005}


def test_clearing_overlay_resets_sampling_schedule():
    tree = _Tree(168, show=True)
    OmniRuntimeTiming.clear()
    assert OmniRuntimeTiming.take_overlay_sample(tree, now=20.0)
    assert not OmniRuntimeTiming.take_overlay_sample(tree, now=21.0)
    OmniRuntimeTiming.clear_tree(tree, consumer=OmniRuntimeTiming.OVERLAY)
    assert OmniRuntimeTiming.take_overlay_sample(tree, now=21.0)


def main():
    tests = (
        test_overlay_sampling_defaults_to_three_seconds,
        test_disabled_overlay_does_not_read_the_clock,
        test_root_and_subtrees_share_one_gate_clock_read,
        test_console_aggregates_while_overlay_keeps_one_direct_sample,
        test_new_overlay_sample_replaces_instead_of_averaging,
        test_clearing_overlay_resets_sampling_schedule,
    )
    for test in tests:
        test()
        print(f"[PASS] {test.__name__}")
    print(f"runtime timing: {len(tests)}/{len(tests)} passed")


if __name__ == "__main__":
    main()
