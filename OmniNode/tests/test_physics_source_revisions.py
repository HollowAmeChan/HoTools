import importlib.util
from pathlib import Path
import sys


PATH = (
    Path(__file__).resolve().parents[1]
    / "NodeTree" / "Function" / "physicsWorld" / "source_revisions.py"
)
SPEC = importlib.util.spec_from_file_location("physics_source_revisions_test_module", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

Tracker = MODULE.BlenderSourceRevisionTracker


def test_external_updates_increment_only_the_reported_id_kind():
    tracker = Tracker()
    initial = tracker.revisions(101, 202)
    tracker.process_geometry_updates(source_pointers=(101, 101))
    assert tracker.revisions(101, 202) == (initial[0] + 1, initial[1])
    tracker.process_geometry_updates(data_pointers=(202, 202))
    assert tracker.revisions(101, 202) == (initial[0] + 1, initial[1] + 1)


def test_internal_writeback_consumes_exactly_one_object_and_data_update():
    tracker = Tracker()
    initial = tracker.revisions(101, 202)
    tracker.reserve_internal_geometry_update(101, 202)
    tracker.process_geometry_updates(source_pointers=(101,), data_pointers=(202,))
    assert tracker.revisions(101, 202) == initial
    assert tracker.inspect()["pending_source_count"] == 0
    assert tracker.inspect()["pending_data_count"] == 0

    tracker.process_geometry_updates(source_pointers=(101,), data_pointers=(202,))
    assert tracker.revisions(101, 202) == (initial[0] + 1, initial[1] + 1)


def test_unused_or_cancelled_reservations_cannot_swallow_later_user_edits():
    tracker = Tracker()
    reservation = tracker.reserve_internal_geometry_update(101, 202)
    tracker.cancel_reservation(reservation)
    initial = tracker.revisions(101, 202)
    tracker.process_geometry_updates(source_pointers=(101,), data_pointers=(202,))
    assert tracker.revisions(101, 202) == (initial[0] + 1, initial[1] + 1)

    tracker.reserve_internal_geometry_update(101, 202)
    tracker.process_geometry_updates(data_pointers=(303,))
    after_expiry = tracker.revisions(101, 202)
    tracker.process_geometry_updates(source_pointers=(101,), data_pointers=(202,))
    assert tracker.revisions(101, 202) == (
        after_expiry[0] + 1,
        after_expiry[1] + 1,
    )


def test_undo_load_epoch_invalidates_every_identity_without_object_refs():
    tracker = Tracker()
    before = tracker.revisions(101, 202)
    tracker.invalidate_all()
    after = tracker.revisions(101, 202)
    assert after[0] > before[0] and after[1] > before[1]
    assert tracker.inspect()["source_count"] == 0
    assert tracker.inspect()["data_count"] == 0


def main():
    tests = (
        test_external_updates_increment_only_the_reported_id_kind,
        test_internal_writeback_consumes_exactly_one_object_and_data_update,
        test_unused_or_cancelled_reservations_cannot_swallow_later_user_edits,
        test_undo_load_epoch_invalidates_every_identity_without_object_refs,
    )
    for test in tests:
        test()
    print(f"PASS: {len(tests)} Physics source revision tests")


if __name__ == "__main__":
    main()
