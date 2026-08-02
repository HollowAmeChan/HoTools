"""公共 Field native runtime 的 ABI、数值与生命周期验收。"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import types

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get(
    "HOTOOLS_NATIVE_TEST_DIR",
    str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage"),
))

import hotools_native  # noqa: E402


FIELD_ROOT = ROOT / "OmniNode" / "PhysicsWorld" / "field"
PHYSICS_WORLD_ROOT = FIELD_ROOT.parent
PACKAGE_ROOT = "hotools_field_runtime_native_test"


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
field_volume = _load_module(
    f"{PACKAGE_ROOT}.field.volume", FIELD_ROOT / "volume.py"
)
_load_module(f"{PACKAGE_ROOT}.field.wind", FIELD_ROOT / "wind.py")
field_sampling = _load_module(
    f"{PACKAGE_ROOT}.field.sampling", FIELD_ROOT / "sampling.py"
)
field_native = _load_module(
    f"{PACKAGE_ROOT}.field.native", FIELD_ROOT / "native.py"
)


IDENTITY = field_specs.IDENTITY_MATRIX4
ROTATE_Y_180 = (
    (-1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, -1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def _translated(x: float, y: float = 0.0, z: float = 0.0):
    return (
        (1.0, 0.0, 0.0, float(x)),
        (0.0, 1.0, 0.0, float(y)),
        (0.0, 0.0, 1.0, float(z)),
        (0.0, 0.0, 0.0, 1.0),
    )


def _active_field(
    field_id: str,
    *,
    shape: str = field_names.VOLUME_SHAPE_SPHERE,
    transform=IDENTITY,
    speed_mps: float = 1.0,
    turbulence: float = 0.0,
    spatial_scale_m: float = 1.0,
    temporal_frequency_hz: float = 0.5,
    octaves: int = 3,
    lacunarity: float = 2.0,
    gain: float = 0.5,
    seed_u32: int = 0,
    blend_weight: float = 1.0,
    scope=None,
    priority: int = 0,
):
    return field_specs.FieldSpecV0(
        field_id,
        f"source:{field_id}",
        volume=field_specs.VolumeSpecV0(
            shape=shape,
            world_transform=transform,
        ),
        wind=field_specs.WindPayloadV0(
            speed_mps=speed_mps,
            turbulence=turbulence,
            spatial_scale_m=spatial_scale_m,
            temporal_frequency_hz=temporal_frequency_hz,
            octaves=octaves,
            lacunarity=lacunarity,
            gain=gain,
            seed_u32=seed_u32,
        ),
        scope=field_specs.FieldScopeV0() if scope is None else scope,
        status=field_names.FIELD_STATUS_ACTIVE,
        blend_weight=blend_weight,
        priority=priority,
    )


def _snapshot(fields, *, generation=1, frame=2, sample_time_seconds=0.25):
    return field_specs.FieldSnapshotV0(
        tuple(fields),
        generation=generation,
        frame=frame,
        sample_time_seconds=sample_time_seconds,
    )


def _raw_create_args(snapshot):
    return [
        field_native.FIELD_NATIVE_RUNTIME_ABI_VERSION,
        snapshot.signature,
        snapshot.config_signature,
        snapshot.value_signature,
        int(snapshot.generation),
        int(snapshot.frame),
        float(snapshot.sample_time_seconds),
        *field_native._runtime_payload(snapshot),
    ]


def _expect_error(exception_type, callback) -> None:
    try:
        callback()
    except exception_type:
        return
    raise AssertionError(f"预期抛出 {exception_type.__name__}")


def test_field_runtime_native_matches_python_v0_for_sphere_box_and_turbulence():
    sphere = _active_field(
        "sphere-turbulent",
        speed_mps=2.75,
        turbulence=0.65,
        spatial_scale_m=1.7,
        temporal_frequency_hz=0.8,
        octaves=4,
        lacunarity=2.3,
        gain=0.4,
        seed_u32=0xF00D1234,
        blend_weight=0.75,
        priority=-2,
    )
    box = _active_field(
        "box-uniform",
        shape=field_names.VOLUME_SHAPE_BOX,
        transform=_translated(3.0),
        speed_mps=1.25,
        blend_weight=1.1,
        priority=3,
    )
    snapshot = _snapshot((box, sphere), sample_time_seconds=1.25)
    positions = np.asarray(
        (
            (0.0, 0.0, 0.0),
            (0.5, -0.25, 0.1),
            (1.0, 0.0, 0.0),
            (3.0, 0.0, 0.0),
            (4.0, 0.25, -0.5),
            (5.0, 0.0, 0.0),
            (-0.4, 0.2, 0.3),
        ),
        dtype=np.float64,
    )
    runtime = field_native.NativeFieldRuntimeV1.create(snapshot)
    try:
        actual = runtime.sample_air_velocity(
            positions,
            sample_time_seconds=1.375,
        )
        expected = field_sampling.sample_air_velocity_v0(
            snapshot,
            positions,
            sample_time_seconds=1.375,
        )
        np.testing.assert_allclose(
            actual["air_velocity_world"],
            expected.values_world_f32,
            rtol=3.0e-6,
            atol=2.0e-6,
        )
        expected_participation = np.asarray(
            (1, 1, 0, 1, 1, 0, 1), dtype=np.uint8
        )
        assert np.array_equal(actual["participation"], expected_participation)
        assert actual["sampled_field_count"] == 2
        assert actual["sample_time_seconds"] == 1.375
        assert actual["air_velocity_world"].dtype == np.float32
        assert actual["participation"].dtype == np.uint8
        assert actual["air_velocity_world"].flags.c_contiguous
        assert actual["air_velocity_world"].flags.writeable is False
        assert actual["participation"].flags.writeable is False

        info = runtime.debug_snapshot()
        assert info["abi_version"] == 1
        assert info["field_ids"] == ["sphere-turbulent", "box-uniform"]
        assert info["sphere_field_count"] == 1
        assert info["box_field_count"] == 1
        assert info["turbulent_field_count"] == 1
        assert info["scope_mode"] == "field_scope_context_v0"
    finally:
        runtime.dispose("test_complete")


def test_field_runtime_native_scope_context_matches_public_field_scope():
    scope = field_specs.FieldScopeV0(
        solver_ids=("mc2",),
        collection_ids=("Garment",),
        include_ids=("Sleeve",),
        exclude_ids=("Blocked",),
        collision_groups=(3,),
    )
    snapshot = _snapshot((_active_field("scoped", scope=scope),))
    positions = np.asarray(((0.0, 0.0, 0.0),), dtype=np.float64)
    runtime = field_native.NativeFieldRuntimeV1.create(snapshot)
    try:
        matching = runtime.sample_air_velocity(
            positions,
            consumer_id="mc2",
            object_id="Sleeve",
            collection_ids=("Garment",),
            collision_groups=(3,),
        )
        np.testing.assert_array_equal(
            matching["air_velocity_world"], ((0.0, 0.0, 1.0),)
        )
        assert np.array_equal(matching["participation"], (1,))
        assert matching["sampled_field_count"] == 1

        mismatches = (
            {"consumer_id": "jolt", "object_id": "Sleeve", "collection_ids": ("Garment",), "collision_groups": (3,)},
            {"consumer_id": "mc2", "object_id": "Body", "collection_ids": ("Garment",), "collision_groups": (3,)},
            {"consumer_id": "mc2", "object_id": "Sleeve", "collection_ids": ("Other",), "collision_groups": (3,)},
            {"consumer_id": "mc2", "object_id": "Sleeve", "collection_ids": ("Garment",), "collision_groups": (4,)},
        )
        for context in mismatches:
            result = runtime.sample_air_velocity(positions, **context)
            assert np.array_equal(result["air_velocity_world"], ((0.0, 0.0, 0.0),))
            assert np.array_equal(result["participation"], (0,))
            assert result["sampled_field_count"] == 0
    finally:
        runtime.dispose("test_complete")


def test_field_runtime_native_participation_survives_cancellation_and_stationary_air():
    forward = _active_field("forward", speed_mps=2.0, priority=0)
    backward = _active_field(
        "backward",
        transform=ROTATE_Y_180,
        speed_mps=2.0,
        priority=1,
    )
    stationary = _active_field("stationary", speed_mps=0.0, priority=2)
    snapshot = _snapshot((stationary, backward, forward))
    positions = np.asarray(((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)), dtype=np.float64)
    runtime = field_native.NativeFieldRuntimeV1.create(snapshot)
    try:
        result = runtime.sample_air_velocity(positions)
        np.testing.assert_array_equal(
            result["air_velocity_world"],
            ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        )
        assert np.array_equal(result["participation"], (1, 0))
        assert result["sampled_field_count"] == 3
    finally:
        runtime.dispose("test_complete")

    zero_blend = _snapshot((_active_field("zero-blend", blend_weight=0.0),))
    runtime = field_native.NativeFieldRuntimeV1.create(zero_blend)
    try:
        result = runtime.sample_air_velocity(positions[:1])
        assert np.array_equal(result["air_velocity_world"], ((0.0, 0.0, 0.0),))
        assert np.array_equal(result["participation"], (0,))
        assert result["sampled_field_count"] == 1
    finally:
        runtime.dispose("test_complete")


def test_field_runtime_native_owns_inputs_outputs_and_frame_metadata():
    snapshot = _snapshot((_active_field("owned", speed_mps=1.5),))
    arguments = _raw_create_args(snapshot)
    world_to_local = np.array(arguments[10], copy=True)
    direction_world = np.array(arguments[11], copy=True)
    wind_values = np.array(arguments[12], copy=True)
    arguments[10] = world_to_local
    arguments[11] = direction_world
    arguments[12] = wind_values
    handle = hotools_native.field_runtime_v1_create(*arguments)
    try:
        world_to_local[0, 0, 3] = 100.0
        direction_world[0] = (1.0, 0.0, 0.0)
        wind_values[0, 0] = 99.0
        result = hotools_native.field_runtime_v1_sample_air_velocity(
            handle,
            np.asarray(((0.0, 0.0, 0.0),), dtype=np.float64),
            0.25,
            "",
            "",
            (),
            0,
        )
        np.testing.assert_array_equal(
            result["air_velocity_world"], ((0.0, 0.0, 1.5),)
        )
        values = result["air_velocity_world"]
        participation = result["participation"]
        assert values.flags.writeable is False
        assert participation.flags.writeable is False

        hotools_native.field_runtime_v1_update_frame(
            handle, "snapshot:next", 4, 9, 2.5
        )
        info = hotools_native.field_runtime_v1_inspect(handle)
        assert info["snapshot_signature"] == "snapshot:next"
        assert info["generation"] == 4
        assert info["frame"] == 9
        assert info["sample_time_seconds"] == 2.5
        _expect_error(
            ValueError,
            lambda: hotools_native.field_runtime_v1_update_frame(
                handle, "snapshot:bad", -1, 10, 3.0
            ),
        )
        unchanged = hotools_native.field_runtime_v1_inspect(handle)
        assert unchanged["snapshot_signature"] == "snapshot:next"
        assert unchanged["generation"] == 4
    finally:
        hotools_native.field_runtime_v1_dispose(handle)

    # 返回数组由独立 capsule 持有，runtime 销毁后仍然有效。
    np.testing.assert_array_equal(values, ((0.0, 0.0, 1.5),))
    assert np.array_equal(participation, (1,))


def test_field_runtime_native_monotonic_handle_rejects_stale_identity():
    before = hotools_native.field_runtime_v1_stats()["live_runtime_count"]
    snapshot = _snapshot((_active_field("lifecycle"),))
    first = hotools_native.field_runtime_v1_create(*_raw_create_args(snapshot))
    hotools_native.field_runtime_v1_dispose(first)
    hotools_native.field_runtime_v1_dispose(first)
    second = hotools_native.field_runtime_v1_create(*_raw_create_args(snapshot))
    try:
        assert second > first
        _expect_error(
            RuntimeError,
            lambda: hotools_native.field_runtime_v1_inspect(first),
        )
        assert hotools_native.field_runtime_v1_inspect(second)["live"] is True
    finally:
        hotools_native.field_runtime_v1_dispose(second)
    assert hotools_native.field_runtime_v1_stats()["live_runtime_count"] == before


def test_field_runtime_native_rejects_invalid_abi_shapes_values_and_samples():
    snapshot = _snapshot((_active_field("invalid-gate"),))
    before = hotools_native.field_runtime_v1_stats()["live_runtime_count"]

    bad_abi = _raw_create_args(snapshot)
    bad_abi[0] = 2
    _expect_error(
        ValueError,
        lambda: hotools_native.field_runtime_v1_create(*bad_abi),
    )

    bad_wind = _raw_create_args(snapshot)
    bad_wind[12] = np.array(bad_wind[12], copy=True)
    bad_wind[12][0, 1] = np.nan
    _expect_error(
        ValueError,
        lambda: hotools_native.field_runtime_v1_create(*bad_wind),
    )

    bad_octaves = _raw_create_args(snapshot)
    bad_octaves[13] = np.asarray((9,), dtype=np.uint32)
    _expect_error(
        ValueError,
        lambda: hotools_native.field_runtime_v1_create(*bad_octaves),
    )

    bad_shape = _raw_create_args(snapshot)
    bad_shape[10] = np.empty((1, 3, 3), dtype=np.float64)
    _expect_error(
        ValueError,
        lambda: hotools_native.field_runtime_v1_create(*bad_shape),
    )

    bad_scope_mask = _raw_create_args(snapshot)
    bad_scope_mask[19] = np.asarray((1 << 20,), dtype=np.uint32)
    _expect_error(
        ValueError,
        lambda: hotools_native.field_runtime_v1_create(*bad_scope_mask),
    )
    assert hotools_native.field_runtime_v1_stats()["live_runtime_count"] == before

    handle = hotools_native.field_runtime_v1_create(*_raw_create_args(snapshot))
    try:
        valid_positions = np.zeros((1, 3), dtype=np.float64)
        _expect_error(
            ValueError,
            lambda: hotools_native.field_runtime_v1_sample_air_velocity(
                handle, valid_positions, -0.1, "", "", (), 0
            ),
        )
        invalid_positions = valid_positions.copy()
        invalid_positions[0, 0] = np.inf
        _expect_error(
            ValueError,
            lambda: hotools_native.field_runtime_v1_sample_air_velocity(
                handle, invalid_positions, 0.1, "", "", (), 0
            ),
        )
        _expect_error(
            ValueError,
            lambda: hotools_native.field_runtime_v1_sample_air_velocity(
                handle, valid_positions, 0.1, "", "", (), 1 << 20
            ),
        )
    finally:
        hotools_native.field_runtime_v1_dispose(handle)


def test_field_runtime_native_empty_runtime_and_empty_batch_are_typed():
    snapshot = _snapshot(())
    runtime = field_native.NativeFieldRuntimeV1.create(snapshot)
    try:
        empty = runtime.sample_air_velocity(np.empty((0, 3), dtype=np.float64))
        assert empty["air_velocity_world"].shape == (0, 3)
        assert empty["air_velocity_world"].dtype == np.float32
        assert empty["participation"].shape == (0,)
        assert empty["participation"].dtype == np.uint8
        populated = runtime.sample_air_velocity(np.zeros((3, 3), dtype=np.float64))
        assert np.array_equal(populated["air_velocity_world"], np.zeros((3, 3)))
        assert np.array_equal(populated["participation"], np.zeros(3, dtype=np.uint8))
        assert populated["sampled_field_count"] == 0
        assert runtime.debug_snapshot()["field_count"] == 0
    finally:
        runtime.dispose("test_complete")
