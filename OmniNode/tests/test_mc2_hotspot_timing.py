import importlib.util
import os
import sys


_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(
    os.path.dirname(_TEST_DIR),
    "NodeTree",
    "Function",
    "physicsWorld",
    "mc2",
    "timing.py",
)
_SPEC = importlib.util.spec_from_file_location("mc2_hotspot_timing_test_module", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

MC2HotspotTimingProfile = _MODULE.MC2HotspotTimingProfile
MC2HotspotTimingSession = _MODULE.MC2HotspotTimingSession
MC2_HOTSPOT_TIMING_RESOURCE_KEY = _MODULE.MC2_HOTSPOT_TIMING_RESOURCE_KEY
make_mc2_hotspot_timing = _MODULE.make_mc2_hotspot_timing


class _Clock:
    def __init__(self, *values):
        self.values = iter(values)
        self.reads = 0

    def __call__(self):
        self.reads += 1
        return next(self.values)


class _Overlay:
    def __init__(self):
        self.records = []

    def record(self, stage, seconds):
        self.records.append((stage, seconds))


class _World:
    def __init__(self):
        self.backend_resources = {}


def _context(**overrides):
    value = {
        "frame": 42,
        "generation": 3,
        "dt": 1.0 / 60.0,
        "tasks": 2,
        "setup_counts": {"mesh_cloth": 1, "bone_cloth": 1},
        "particles": 1200,
        "scheduled_tasks": 2,
        "substeps": 4,
        "max_substeps": 2,
        "batches": 2,
        "colliders": 3,
        "interaction_tasks": 2,
        "created": 0,
        "rebuilt": 0,
        "updated": 1,
        "reused": 1,
        "pruned": 0,
        "reset_tasks": 0,
        "teleport_tasks": 1,
        "debug_tasks": 1,
        "native_group_frames": 1,
        "interaction_pairs": 1,
        "ready_frames": 1,
        "writeback_results": 2,
    }
    value.update(overrides)
    return value


def test_session_measures_once_and_fans_out_to_overlay_and_console():
    output = []
    profile = MC2HotspotTimingProfile(clock=lambda: 0.0, printer=output.append)
    profile.PRINT_INTERVAL = 0.0
    clock = _Clock(1.0, 1.002, 1.007, 1.008)
    overlay = _Overlay()
    session = MC2HotspotTimingSession(profile, overlay=overlay, clock=clock)

    session.restart()
    assert abs(session.checkpoint("输入与任务") - 0.002) < 1e-12
    assert abs(session.checkpoint("模拟求解") - 0.005) < 1e-12
    session.finish(_context())

    assert clock.reads == 4
    assert [stage for stage, _seconds in overlay.records] == [
        "输入与任务",
        "模拟求解",
        "其他",
    ]
    assert abs(overlay.records[0][1] - 0.002) < 1e-12
    assert abs(overlay.records[1][1] - 0.005) < 1e-12
    assert len(output) == 1
    assert "MC2 HOTSPOT TIMING" in output[0]
    assert "Scope:" in output[0]
    assert "State:" in output[0]
    assert "01. 模拟求解" in output[0]
    assert "max=5.000ms" in output[0]


def test_profile_aggregates_until_interval_and_reports_ranges():
    output = []
    profile = MC2HotspotTimingProfile(clock=lambda: 10.0, printer=output.append)
    profile.add_sample(
        {"模拟求解": 0.010, "结果发布": 0.001},
        {"native组求解": 0.009},
        0.012,
        _context(frame=10, tasks=1, particles=800, substeps=2),
        now=10.4,
    )
    assert output == []

    profile.add_sample(
        {"模拟求解": 0.020, "结果发布": 0.002},
        {"native组求解": 0.018},
        0.024,
        _context(frame=11, tasks=3, particles=1600, substeps=6),
        now=11.1,
    )

    assert len(output) == 1
    report = output[0]
    assert "samples=2" in report
    assert "tasks=1..3" in report
    assert "particles=800..1600" in report
    assert "substeps=2..6" in report
    assert "01. 模拟求解 = 15.000ms" in report
    assert "max=20.000ms" in report
    assert "Solve Detail (nested in 模拟求解)" in report
    assert "01. native组求解 = 13.500ms" in report


def test_world_factory_reuses_owned_profile_and_rejects_key_collision():
    world = _World()
    first = make_mc2_hotspot_timing(world)
    second = make_mc2_hotspot_timing(world)
    assert first._profile is second._profile
    assert world.backend_resources[MC2_HOTSPOT_TIMING_RESOURCE_KEY] is first._profile

    world.backend_resources[MC2_HOTSPOT_TIMING_RESOURCE_KEY] = object()
    try:
        make_mc2_hotspot_timing(world)
    except RuntimeError as exc:
        assert "occupied" in str(exc)
    else:
        raise AssertionError("MC2 timing resource ownership collision must fail")


def test_inactive_gap_discards_partial_window_before_reenable():
    output = []
    profile = MC2HotspotTimingProfile(clock=lambda: 0.0, printer=output.append)
    profile.add_sample(
        {"旧阶段": 0.010},
        {},
        0.010,
        _context(frame=1),
        now=0.2,
    )
    profile.add_sample(
        {"新阶段": 0.020},
        {},
        0.020,
        _context(frame=100),
        now=10.0,
    )
    assert output == []
    assert profile._samples == 1
    assert profile._stage_totals == {"新阶段": 0.020}


def main():
    tests = (
        test_session_measures_once_and_fans_out_to_overlay_and_console,
        test_profile_aggregates_until_interval_and_reports_ranges,
        test_world_factory_reuses_owned_profile_and_rejects_key_collision,
        test_inactive_gap_discards_partial_window_before_reenable,
    )
    for test in tests:
        test()
    print(f"PASS: {len(tests)} MC2 hotspot timing tests")


if __name__ == "__main__":
    main()
