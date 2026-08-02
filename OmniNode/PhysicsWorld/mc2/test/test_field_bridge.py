"""不启动 Blender 的 MC2 Field sample packet 与作用域桥验收。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

import numpy as np


MC2_ROOT = Path(__file__).parents[1]
PHYSICS_WORLD_ROOT = MC2_ROOT.parent
FIELD_ROOT = PHYSICS_WORLD_ROOT / "field"
PACKAGE_ROOT = "hotools_mc2_field_bridge_test"


def _ensure_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_ensure_package(PACKAGE_ROOT, PHYSICS_WORLD_ROOT)
_ensure_package(f"{PACKAGE_ROOT}.collision", PHYSICS_WORLD_ROOT / "collision")
_ensure_package(f"{PACKAGE_ROOT}.field", FIELD_ROOT)
_ensure_package(f"{PACKAGE_ROOT}.mc2", MC2_ROOT)
_load_module(
    f"{PACKAGE_ROOT}.collision.groups",
    PHYSICS_WORLD_ROOT / "collision" / "groups.py",
)
field_names = _load_module(
    f"{PACKAGE_ROOT}.field.names", FIELD_ROOT / "names.py"
)
_load_module(
    f"{PACKAGE_ROOT}.field.diagnostics", FIELD_ROOT / "diagnostics.py"
)
field_specs = _load_module(
    f"{PACKAGE_ROOT}.field.specs", FIELD_ROOT / "specs.py"
)
_load_module(f"{PACKAGE_ROOT}.field.volume", FIELD_ROOT / "volume.py")
_load_module(f"{PACKAGE_ROOT}.field.wind", FIELD_ROOT / "wind.py")
_load_module(
    f"{PACKAGE_ROOT}.field.sampling", FIELD_ROOT / "sampling.py"
)
_load_module(f"{PACKAGE_ROOT}.mc2.names", MC2_ROOT / "names.py")
capabilities = _load_module(
    f"{PACKAGE_ROOT}.mc2.capabilities", MC2_ROOT / "capabilities.py"
)
bridge = _load_module(
    f"{PACKAGE_ROOT}.mc2.field_bridge", MC2_ROOT / "field_bridge.py"
)


def _expect_error(exception_type, callback) -> None:
    try:
        callback()
    except exception_type:
        return
    raise AssertionError(f"预期抛出 {exception_type.__name__}")


def _active_wind(
    field_id: str,
    *,
    speed_mps: float = 1.0,
    turbulence: float = 0.0,
    scope=None,
):
    return field_specs.FieldSpecV0(
        field_id,
        f"object-{field_id}",
        volume=field_specs.VolumeSpecV0(shape=field_names.VOLUME_SHAPE_BOX),
        wind=field_specs.WindPayloadV0(
            speed_mps=speed_mps,
            turbulence=turbulence,
            spatial_scale_m=0.75,
            temporal_frequency_hz=1.25,
            seed_u32=17,
        ),
        scope=scope or field_specs.FieldScopeV0(),
        status=field_names.FIELD_STATUS_ACTIVE,
    )


def _packet(values, **overrides):
    kwargs = {
        "abi_version": bridge.MC2_FIELD_SAMPLE_PACKET_ABI_VERSION,
        "field_snapshot_signature": "snapshot-a",
        "sample_time_seconds": 0.25,
        "particle_count": len(values),
        "air_velocity_world_f32": values,
    }
    kwargs.update(overrides)
    return bridge.MC2FieldSamplePacketV0(**kwargs)


def test_packet_freezes_exact_float32_c_array_and_copies_input():
    source = np.asarray(((1.0, 2.0, 3.0), (4.0, 5.0, 6.0)), dtype=np.float32)
    packet = _packet(source)
    source[0, 0] = 99.0
    np.testing.assert_array_equal(
        packet.air_velocity_world_f32,
        ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0)),
    )
    assert packet.air_velocity_world_f32.dtype == np.float32
    assert packet.air_velocity_world_f32.flags.c_contiguous
    assert packet.air_velocity_world_f32.flags.writeable is False
    _expect_error(
        ValueError,
        lambda: packet.air_velocity_world_f32.__setitem__((0, 0), 8.0),
    )


def test_packet_rejects_invalid_abi_shape_dtype_layout_count_and_finite_values():
    valid = np.zeros((2, 3), dtype=np.float32)
    _expect_error(ValueError, lambda: _packet(valid, abi_version=1))
    _expect_error(TypeError, lambda: _packet(valid, abi_version=True))
    _expect_error(ValueError, lambda: _packet(valid, field_snapshot_signature=" "))
    _expect_error(ValueError, lambda: _packet(valid, sample_time_seconds=-0.1))
    _expect_error(ValueError, lambda: _packet(valid, sample_time_seconds=np.inf))
    _expect_error(TypeError, lambda: _packet(valid, particle_count=2.0))
    _expect_error(
        TypeError,
        lambda: _packet(valid.astype(np.float64)),
    )
    _expect_error(
        ValueError,
        lambda: _packet(np.zeros((3, 2), dtype=np.float32)),
    )
    non_contiguous = np.zeros((2, 6), dtype=np.float32)[:, ::2]
    assert non_contiguous.shape == (2, 3) and not non_contiguous.flags.c_contiguous
    _expect_error(ValueError, lambda: _packet(non_contiguous))
    non_finite = valid.copy()
    non_finite[1, 2] = np.nan
    _expect_error(ValueError, lambda: _packet(non_finite))


def test_empty_domain_builds_an_exact_read_only_zero_particle_packet():
    snapshot = field_specs.FieldSnapshotV0(())
    packet = bridge.build_mc2_field_sample_packet_v0(
        snapshot,
        np.empty((0, 3), dtype=np.float32),
        0.0,
    )
    assert packet.particle_count == 0
    assert packet.air_velocity_world_f32.shape == (0, 3)
    assert packet.air_velocity_world_f32.dtype == np.float32
    assert packet.air_velocity_world_f32.flags.c_contiguous
    assert packet.air_velocity_world_f32.flags.writeable is False


def test_uniform_and_turbulent_wind_use_the_same_builder():
    positions = np.asarray(
        ((0.0, 0.0, 0.0), (0.25, -0.5, 0.75)), dtype=np.float64
    )
    uniform = bridge.build_mc2_field_sample_packet_v0(
        field_specs.FieldSnapshotV0((_active_wind("uniform", speed_mps=2.0),)),
        positions,
        0.5,
    )
    turbulent = bridge.build_mc2_field_sample_packet_v0(
        field_specs.FieldSnapshotV0((
            _active_wind("turbulent", speed_mps=2.0, turbulence=0.8),
        )),
        positions,
        0.5,
    )
    np.testing.assert_array_equal(
        uniform.air_velocity_world_f32,
        ((0.0, 0.0, 2.0), (0.0, 0.0, 2.0)),
    )
    assert turbulent.air_velocity_world_f32.shape == (2, 3)
    assert np.isfinite(turbulent.air_velocity_world_f32).all()
    assert not np.array_equal(
        turbulent.air_velocity_world_f32,
        uniform.air_velocity_world_f32,
    )
    assert uniform.field_snapshot_signature
    assert uniform.request_signatures and turbulent.request_signatures


def test_consumer_partitions_apply_scope_and_restore_logical_order():
    field = _active_wind(
        "shirt-only",
        speed_mps=3.0,
        scope=field_specs.FieldScopeV0(
            solver_ids=("mc2",),
            collection_ids=("cloth",),
            include_ids=("shirt",),
            collision_groups=(3,),
        ),
    )
    snapshot = field_specs.FieldSnapshotV0((field,))
    positions = np.asarray(
        ((0.0, 0.0, 0.0),) * 4,
        dtype=np.float32,
    )
    shirt = bridge.MC2FieldConsumerPartitionV0(
        np.asarray((2, 0), dtype=np.uint32),
        object_id=" shirt ",
        collection_ids=("cloth", "cloth"),
        collision_groups=(3, 3),
    )
    cape = bridge.MC2FieldConsumerPartitionV0(
        np.asarray((3, 1), dtype=np.int64),
        object_id="cape",
        collection_ids=("cloth",),
        collision_groups=(3,),
    )
    assert shirt.particle_indices.tolist() == [0, 2]
    assert shirt.particle_indices.flags.writeable is False
    assert shirt.object_id == "shirt"
    assert shirt.collection_ids == ("cloth",)
    assert shirt.collision_groups == (3,)

    packet = bridge.build_mc2_field_sample_packet_v0(
        snapshot,
        positions,
        0.0,
        consumer_partitions=(cape, shirt),
    )
    np.testing.assert_array_equal(
        packet.air_velocity_world_f32,
        (
            (0.0, 0.0, 3.0),
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 3.0),
            (0.0, 0.0, 0.0),
        ),
    )


def test_partition_reorder_does_not_change_packet_values_or_request_order():
    snapshot = field_specs.FieldSnapshotV0((_active_wind("all", speed_mps=2.0),))
    positions = np.asarray(
        ((0.0, 0.0, 0.0), (0.2, 0.0, 0.0), (0.4, 0.0, 0.0)),
        dtype=np.float64,
    )
    first = bridge.MC2FieldConsumerPartitionV0(
        np.asarray((2, 0), dtype=np.int32), object_id="first"
    )
    second = bridge.MC2FieldConsumerPartitionV0(
        np.asarray((1,), dtype=np.int32), object_id="second"
    )
    packet_a = bridge.build_mc2_field_sample_packet_v0(
        snapshot, positions, 1.0, (first, second)
    )
    packet_b = bridge.build_mc2_field_sample_packet_v0(
        snapshot, positions, 1.0, (second, first)
    )
    np.testing.assert_array_equal(
        packet_a.air_velocity_world_f32,
        packet_b.air_velocity_world_f32,
    )
    assert packet_a.request_signatures == packet_b.request_signatures


def test_partition_indices_must_be_integer_disjoint_complete_and_in_range():
    _expect_error(
        TypeError,
        lambda: bridge.MC2FieldConsumerPartitionV0(
            np.asarray((0.0, 1.0), dtype=np.float64)
        ),
    )
    _expect_error(
        ValueError,
        lambda: bridge.MC2FieldConsumerPartitionV0(
            np.asarray((0, 0), dtype=np.int32)
        ),
    )
    snapshot = field_specs.FieldSnapshotV0((_active_wind("all"),))
    positions = np.zeros((3, 3), dtype=np.float32)
    p01 = bridge.MC2FieldConsumerPartitionV0(
        np.asarray((0, 1), dtype=np.int32)
    )
    p12 = bridge.MC2FieldConsumerPartitionV0(
        np.asarray((1, 2), dtype=np.int32)
    )
    p3 = bridge.MC2FieldConsumerPartitionV0(
        np.asarray((3,), dtype=np.int32)
    )
    _expect_error(
        ValueError,
        lambda: bridge.build_mc2_field_sample_packet_v0(
            snapshot, positions, 0.0, (p01, p12)
        ),
    )
    _expect_error(
        ValueError,
        lambda: bridge.build_mc2_field_sample_packet_v0(
            snapshot, positions, 0.0, (p01,)
        ),
    )
    _expect_error(
        ValueError,
        lambda: bridge.build_mc2_field_sample_packet_v0(
            snapshot,
            positions,
            0.0,
            (p01, p3),
        ),
    )


def test_builder_strictly_validates_snapshot_positions_and_time():
    snapshot = field_specs.FieldSnapshotV0((_active_wind("all"),))
    _expect_error(
        TypeError,
        lambda: bridge.build_mc2_field_sample_packet_v0(
            object(), np.zeros((1, 3)), 0.0
        ),
    )
    _expect_error(
        ValueError,
        lambda: bridge.build_mc2_field_sample_packet_v0(
            snapshot, np.zeros(3), 0.0
        ),
    )
    invalid = np.zeros((1, 3), dtype=np.float64)
    invalid[0, 0] = np.inf
    _expect_error(
        ValueError,
        lambda: bridge.build_mc2_field_sample_packet_v0(snapshot, invalid, 0.0),
    )
    _expect_error(
        ValueError,
        lambda: bridge.build_mc2_field_sample_packet_v0(
            snapshot, np.zeros((1, 3)), np.nan
        ),
    )


def test_preview_only_field_is_not_silently_consumed():
    preview = field_specs.FieldSpecV0(
        "preview",
        "preview-object",
        volume=field_specs.VolumeSpecV0(shape=field_names.VOLUME_SHAPE_BOX),
        wind=field_specs.WindPayloadV0(speed_mps=5.0),
    )
    packet = bridge.build_mc2_field_sample_packet_v0(
        field_specs.FieldSnapshotV0((preview,)),
        np.zeros((2, 3), dtype=np.float32),
        0.0,
    )
    np.testing.assert_array_equal(
        packet.air_velocity_world_f32,
        np.zeros((2, 3), dtype=np.float32),
    )
    assert packet.diagnostics
    assert packet.diagnostics[0].code == field_names.FIELD_PREVIEW_ONLY


def test_mc2_field_capability_is_declared_with_frozen_semantics():
    capability = capabilities.MC2_FIELD_AIR_VELOCITY_CAPABILITY
    assert capability["capability_id"] == "mc2_field_air_velocity"
    assert capability["channel"] == field_names.AIR_VELOCITY_CHANNEL_ID
    assert capability["unit"] == "m/s"
    assert capability["sample_mode"] == "per_particle"
    assert capability["sample_phase"] == "pre_substep"
    assert capability["response"] == "hotools_relative_air_velocity_v0"
    assert capabilities.MC2_CAPABILITIES[capability["capability_id"]] is capability


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"MC2 Field bridge: {len(TESTS)} passed")
