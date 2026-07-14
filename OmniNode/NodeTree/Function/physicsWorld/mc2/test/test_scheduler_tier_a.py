"""Tier A checks for the MC2 fixed-step scheduler producer."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
import types

import numpy as np


MC2_ROOT = Path(__file__).resolve().parents[1]
PHYSICS_WORLD = MC2_ROOT.parent
FUNCTION = PHYSICS_WORLD.parent
NODETREE = FUNCTION.parent
OMNINODE = NODETREE.parent
HOTOOLS = OMNINODE.parent

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2", MC2_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [str(package_path)]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

scheduler = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.scheduler"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "tier_a"
    / "center_frame_shift_skip_count_001.json"
)
EXPECTED_COMMIT = "418f89ff31a45bb4b2336641ad5907a1110eabea"


def test_scheduler_matches_fixed_mc2_oracle() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    values = fixture["input"]
    expected = fixture["expected"]
    assert fixture["mc2_commit"] == EXPECTED_COMMIT
    assert fixture["source"]["producer"][0].endswith(
        "::AlwaysTeamUpdatePostJob.Execute"
    )
    state = scheduler.MC2TimeSchedulerState()
    frame = state.plan_frame(
        frame_delta_time=values["frame_delta_time"],
        now_time_scale=values["now_time_scale"],
        simulation_delta_time=values["simulation_delta_time"],
        max_simulation_count_per_frame=values[
            "max_simulation_count_per_frame"
        ],
    )
    assert frame.update_count == expected["update_count"]
    assert frame.skip_count == expected["skip_count"]
    assert frame.planned_update_count == (
        expected["update_count"] + expected["skip_count"]
    )
    for name in (
        "time",
        "old_time",
        "now_update_time",
        "old_update_time",
        "frame_update_time",
        "frame_old_time",
    ):
        np.testing.assert_allclose(
            getattr(frame, name), expected[name], rtol=1.0e-6, atol=1.0e-7
        )
    ratios = [state.advance_step(index) for index in range(frame.update_count)]
    np.testing.assert_allclose(
        ratios,
        expected["step_frame_interpolations"],
        rtol=1.0e-6,
        atol=1.0e-7,
    )
    assert state.frame_revision == 1
    assert state.step_revision == frame.update_count


def test_scheduler_rejects_overlapping_frames() -> None:
    state = scheduler.MC2TimeSchedulerState()
    frame = state.plan_frame(
        frame_delta_time=0.1,
        now_time_scale=1.0,
        simulation_delta_time=0.02,
        max_simulation_count_per_frame=3,
    )
    try:
        state.plan_frame(
            frame_delta_time=0.1,
            now_time_scale=1.0,
            simulation_delta_time=0.02,
            max_simulation_count_per_frame=3,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("scheduler accepted a frame with pending steps")
    for index in range(frame.update_count):
        state.advance_step(index)
    state.plan_frame(
        frame_delta_time=0.02,
        now_time_scale=1.0,
        simulation_delta_time=0.02,
        max_simulation_count_per_frame=3,
    )


def test_solver_settings_expose_source_scheduler_bounds() -> None:
    default = parameters.make_mc2_solver_settings()
    assert default.simulation_frequency == 90
    assert default.max_simulation_count_per_frame == 3
    configured = parameters.make_mc2_solver_settings(
        simulation_frequency=50,
        max_simulation_count_per_frame=3,
    )
    assert configured.debug_dict()["simulation_frequency"] == 50
    for name, value in (
        ("simulation_frequency", 29),
        ("simulation_frequency", 151),
        ("simulation_frequency", 50.5),
        ("max_simulation_count_per_frame", 0),
        ("max_simulation_count_per_frame", 6),
        ("max_simulation_count_per_frame", True),
    ):
        try:
            parameters.make_mc2_solver_settings(**{name: value})
        except ValueError:
            pass
        else:
            raise AssertionError(f"MC2 scheduler setting accepted {name}={value!r}")


if __name__ == "__main__":
    test_scheduler_matches_fixed_mc2_oracle()
    test_scheduler_rejects_overlapping_frames()
    test_solver_settings_expose_source_scheduler_bounds()
    print("PASS MC2 scheduler Tier A oracle")
