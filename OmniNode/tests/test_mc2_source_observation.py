import importlib.util
from pathlib import Path
import sys


PATH = (
    Path(__file__).resolve().parents[1]
    / "NodeTree" / "Function" / "physicsWorld" / "mc2" / "source_observation.py"
)
SPEC = importlib.util.spec_from_file_location("mc2_source_observation_test_module", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

Token = MODULE.MC2SourceObservationToken
Value = MODULE.MC2SourceObservationValue
Cache = MODULE.MC2SourceObservationCache
RevisionTracker = MODULE.MC2SourceRevisionTracker


def _token(**overrides):
    values = {
        "world_generation": 3,
        "setup_type": "mesh_cloth",
        "source_pointer": 101,
        "data_pointer": 202,
        "source_revision": 4,
        "data_revision": 5,
        "config_signature": "config-a",
    }
    values.update(overrides)
    return Token(**values)


def _loader(calls, signature="static-a"):
    def load():
        calls.append(signature)
        return Value(signature, {"overall": signature}, ("snapshot", signature))
    return load


def test_identity_revision_config_and_generation_matrix():
    cache = Cache()
    calls = []
    first = cache.observe(_token(), _loader(calls))
    assert first.status == "miss" and not first.reused
    assert cache.observe(_token(), _loader(calls)).status == "hit"
    assert len(calls) == 1

    for token in (
        _token(source_revision=5),
        _token(source_revision=5, data_revision=6),
        _token(source_revision=5, data_revision=6, config_signature="config-b"),
        _token(
            world_generation=4,
            source_revision=5,
            data_revision=6,
            config_signature="config-b",
        ),
    ):
        assert cache.observe(token, _loader(calls)).status == "revision"
    assert len(calls) == 5

    replacement = _token(source_pointer=303, data_pointer=404)
    assert cache.observe(replacement, _loader(calls)).status == "miss"
    assert cache.inspect()["entries"] == 2
    assert cache.prune((replacement.identity,)) == 1
    assert cache.inspect()["entries"] == 1


def test_uncacheable_source_evicts_and_always_scans():
    cache = Cache()
    calls = []
    cache.observe(_token(), _loader(calls))
    bypass = _token(cacheable=False)
    assert cache.observe(bypass, _loader(calls)).status == "uncacheable"
    assert cache.observe(bypass, _loader(calls)).status == "uncacheable"
    assert len(calls) == 3
    assert cache.inspect()["entries"] == 0


def test_forced_audit_detects_missed_revision_without_changing_token():
    cache = Cache()
    calls = []
    token = _token()
    cache.observe(token, _loader(calls, "static-a"))
    matched = cache.observe(
        token, _loader(calls, "static-a"), force_audit=True
    )
    assert matched.status == "audit_match" and matched.reused
    changed = cache.observe(
        token, _loader(calls, "static-b"), force_audit=True
    )
    assert changed.status == "audit_mismatch" and not changed.reused
    assert changed.value.signature == "static-b"
    assert cache.inspect()["audit_matches"] == 1
    assert cache.inspect()["audit_mismatches"] == 1


def test_mc2_revision_tracker_is_local_and_epoch_invalidates_all_sources():
    tracker = RevisionTracker()
    initial = tracker.revisions(101, 202)
    tracker.process_geometry_updates(source_pointers=(101, 101))
    assert tracker.revisions(101, 202) == (initial[0] + 1, initial[1])
    tracker.process_geometry_updates(data_pointers=(202, 202))
    changed = tracker.revisions(101, 202)
    assert changed == (initial[0] + 1, initial[1] + 1)
    tracker.invalidate_all()
    invalidated = tracker.revisions(101, 202)
    assert invalidated[0] > changed[0] and invalidated[1] > changed[1]
    assert tracker.inspect()["source_count"] == 0
    assert tracker.inspect()["data_count"] == 0


def main():
    tests = (
        test_identity_revision_config_and_generation_matrix,
        test_uncacheable_source_evicts_and_always_scans,
        test_forced_audit_detects_missed_revision_without_changing_token,
        test_mc2_revision_tracker_is_local_and_epoch_invalidates_all_sources,
    )
    for test in tests:
        test()
    print(f"PASS: {len(tests)} MC2 source observation cache tests")


if __name__ == "__main__":
    main()
