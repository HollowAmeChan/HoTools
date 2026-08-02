"""不启动 Blender 的 Field Volume 与 WindV0 核心验收。"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sys
import types

import numpy as np


FIELD_ROOT = Path(__file__).parents[1]
PHYSICS_WORLD_ROOT = FIELD_ROOT.parent
PACKAGE_ROOT = "hotools_field_core_test"


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
names = _load_module(f"{PACKAGE_ROOT}.field.names", FIELD_ROOT / "names.py")
channels = _load_module(
    f"{PACKAGE_ROOT}.field.channels",
    FIELD_ROOT / "channels.py",
)
diagnostics = _load_module(
    f"{PACKAGE_ROOT}.field.diagnostics",
    FIELD_ROOT / "diagnostics.py",
)
specs = _load_module(f"{PACKAGE_ROOT}.field.specs", FIELD_ROOT / "specs.py")
volume = _load_module(f"{PACKAGE_ROOT}.field.volume", FIELD_ROOT / "volume.py")
wind = _load_module(f"{PACKAGE_ROOT}.field.wind", FIELD_ROOT / "wind.py")
sampling = _load_module(
    f"{PACKAGE_ROOT}.field.sampling",
    FIELD_ROOT / "sampling.py",
)


def _expect_error(exception_type, callback) -> None:
    try:
        callback()
    except exception_type:
        return
    raise AssertionError(f"预期抛出 {exception_type.__name__}")


def _matrix(*rows):
    return tuple(tuple(float(value) for value in row) for row in rows)


IDENTITY = specs.IDENTITY_MATRIX4
ROTATE_Z_TO_X = _matrix(
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (-1.0, 0.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


# Spec 的身份、值签名和失败边界。
default_field = specs.FieldSpecV0("field-a", "object-a")
assert default_field.status == names.FIELD_STATUS_PREVIEW_ONLY
assert default_field.field_type == names.FIELD_TYPE_WIND
assert default_field.channel_id == names.AIR_VELOCITY_CHANNEL_ID
assert default_field.generator_id == names.WIND_GENERATOR_ID

# 新增类型判别字段不得改变已经发布的 V0 位置构造顺序。
positional_v0 = specs.FieldSpecV0(
    "field-positional",
    "object-positional",
    specs.VolumeSpecV0(shape=names.VOLUME_SHAPE_BOX),
    specs.WindPayloadV0(speed_mps=2.0),
    specs.FieldScopeV0(solver_ids=("mc2",)),
    False,
    names.FIELD_STATUS_RESERVED,
    0.5,
    7,
    names.FIELD_ABI_VERSION,
)
assert positional_v0.field_type == names.FIELD_TYPE_WIND
assert positional_v0.volume.shape == names.VOLUME_SHAPE_BOX
assert positional_v0.wind.speed_mps == 2.0
assert positional_v0.scope.solver_ids == ("mc2",)
assert positional_v0.enabled is False
assert positional_v0.status == names.FIELD_STATUS_RESERVED
assert positional_v0.blend_weight == 0.5
assert positional_v0.priority == 7

faster_field = specs.FieldSpecV0(
    "field-a",
    "object-a",
    wind=specs.WindPayloadV0(speed_mps=4.0),
)
assert faster_field.config_signature == default_field.config_signature
assert faster_field.value_signature != default_field.value_signature
assert faster_field.wind.config_signature == default_field.wind.config_signature

box_field = specs.FieldSpecV0(
    "field-a",
    "object-a",
    volume=specs.VolumeSpecV0(shape="BOX"),
)
assert box_field.config_signature != default_field.config_signature

_expect_error(ValueError, lambda: specs.WindPayloadV0(turbulence=-0.01))
_expect_error(ValueError, lambda: specs.WindPayloadV0(turbulence=1.01))
_expect_error(ValueError, lambda: specs.WindPayloadV0(seed_u32=2**32))
_expect_error(ValueError, lambda: specs.WindPayloadV0(octaves=9))
_expect_error(
    ValueError,
    lambda: specs.FieldSpecV0("field-unsupported", "object-unsupported", field_type="SCALAR"),
)

channel_reports = channels.field_channel_reports_v0()
assert channel_reports[0]["channel_id"] == names.AIR_VELOCITY_CHANNEL_ID
assert channel_reports[0]["status"] == names.FIELD_STATUS_ACTIVE
assert channel_reports[0]["values_ready"] is True
assert {item["channel_id"] for item in channel_reports} >= {
    "acceleration",
    "mask",
    "sdf",
    "tensor",
}
assert all(
    item["status"] == names.FIELD_STATUS_RESERVED
    for item in channel_reports[1:]
)
_expect_error(
    ValueError,
    lambda: channels.FieldChannelDescriptorV0(
        channel_id="invalid-vector",
        display_name="非法向量",
        rank=channels.CHANNEL_RANK_VECTOR,
        unit="m/s",
        status=names.FIELD_STATUS_RESERVED,
        visualization_mode=channels.VISUALIZATION_SCALAR_SAMPLES,
    ),
)
_expect_error(ValueError, lambda: specs.FieldScopeV0(collision_groups=(17,)))
_expect_error(
    ValueError,
    lambda: specs.FieldSnapshotV0((default_field, default_field)),
)
scope_a = specs.FieldScopeV0(
    solver_ids=("rigid", "mc2"),
    collection_ids=("b", "a"),
    collision_groups=(4, 2),
)
scope_b = specs.FieldScopeV0(
    solver_ids=("mc2", "rigid"),
    collection_ids=("a", "b"),
    collision_groups=(2, 4),
)
assert scope_a.signature_payload() == scope_b.signature_payload()

snapshot_metadata_a = specs.FieldSnapshotV0(
    (default_field,), generation=1, frame=2, sample_time_seconds=0.1
)
snapshot_metadata_b = specs.FieldSnapshotV0(
    (default_field,), generation=7, frame=20, sample_time_seconds=3.0
)
assert snapshot_metadata_a.config_signature == snapshot_metadata_b.config_signature
assert snapshot_metadata_a.value_signature == snapshot_metadata_b.value_signature
assert snapshot_metadata_a.signature != snapshot_metadata_b.signature
snapshot_diagnostic = diagnostics.FieldDiagnosticV0(
    names.FIELD_PREVIEW_ONLY,
    "仅预览",
    field_id="field-a",
    severity="INFO",
)
diagnostic_snapshot = specs.FieldSnapshotV0(
    (default_field,), diagnostics=(snapshot_diagnostic,)
)
assert diagnostic_snapshot.diagnostics == (snapshot_diagnostic,)
assert diagnostic_snapshot.noise_algorithm_versions == (0,)
assert diagnostic_snapshot.attenuation_policy_versions == (0,)

near_affine = specs.VolumeSpecV0(
    world_transform=_matrix(
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (1.0e-9, 0.0, 0.0, 1.0),
    )
)
assert near_affine.world_transform[3] == (0.0, 0.0, 0.0, 1.0)


# Sphere 使用单位局部球和固定线性衰减。
sphere = specs.VolumeSpecV0()
sphere_weights = volume.sample_volume_weights_v0(
    sphere,
    ((0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (1.0, 0.0, 0.0), (1.1, 0.0, 0.0)),
)
np.testing.assert_array_equal(sphere_weights, (1.0, 0.5, 0.0, 0.0))
assert volume.sample_volume_weight_v0(sphere, (0.25, 0.0, 0.0)) == 0.75

translated_scaled_sphere = specs.VolumeSpecV0(
    world_transform=_matrix(
        (2.0, 0.0, 0.0, 1.0),
        (0.0, 2.0, 0.0, 2.0),
        (0.0, 0.0, 2.0, 3.0),
        (0.0, 0.0, 0.0, 1.0),
    )
)
np.testing.assert_array_equal(
    volume.sample_volume_weights_v0(
        translated_scaled_sphere,
        ((1.0, 2.0, 3.0), (2.0, 2.0, 3.0), (3.0, 2.0, 3.0)),
    ),
    (1.0, 0.5, 0.0),
)
_expect_error(
    ValueError,
    lambda: specs.VolumeSpecV0(
        world_transform=_matrix(
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 2.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    ),
)


# Box 允许非均匀 scale，但只有硬边界，没有伪造 falloff。
box = specs.VolumeSpecV0(
    shape="BOX",
    world_transform=_matrix(
        (2.0, 0.0, 0.0, 0.0),
        (0.0, 3.0, 0.0, 0.0),
        (0.0, 0.0, 4.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    ),
)
np.testing.assert_array_equal(
    volume.sample_volume_weights_v0(
        box,
        (
            (0.0, 0.0, 0.0),
            (1.9, 2.9, 3.9),
            (2.0, 3.0, 4.0),
            (2.00000001, 0.0, 0.0),
        ),
    ),
    (1.0, 1.0, 1.0, 0.0),
)
np.testing.assert_allclose(
    volume.wind_direction_world_v0(specs.VolumeSpecV0(world_transform=ROTATE_Z_TO_X)),
    (1.0, 0.0, 0.0),
    atol=1.0e-12,
    rtol=0.0,
)


# turbulence=0 必须走纯定向风，不依赖空间和时间。
uniform_payload = specs.WindPayloadV0(speed_mps=3.5, turbulence=0.0)
uniform_samples = wind.sample_wind_raw_v0(
    uniform_payload,
    (0.0, 0.0, 1.0),
    ((0.0, 0.0, 0.0), (20.0, -4.0, 7.0)),
    123.0,
)
np.testing.assert_array_equal(
    uniform_samples,
    ((0.0, 0.0, 3.5), (0.0, 0.0, 3.5)),
)


# 标量参考、批量算法和 golden samples 共同冻结 noise_algorithm_version=0。
noise_coordinates = np.asarray(
    (
        (0.0, 0.0, 0.0, 0.0),
        (0.25, -0.5, 1.75, 2.125),
        (-12.75, 8.5, 0.125, 19.0),
    ),
    dtype=np.float64,
)
noise_batch = wind.vector_value_noise4_v0(noise_coordinates, seed_u32=0x1234ABCD)
noise_reference = np.asarray(
    [
        wind.vector_value_noise4_reference_v0(value, seed_u32=0x1234ABCD)
        for value in noise_coordinates
    ]
)
np.testing.assert_allclose(noise_batch, noise_reference, atol=2.0e-15, rtol=0.0)
assert np.all(np.linalg.norm(noise_batch, axis=1) <= 1.0 + 1.0e-12)

GOLDEN_NOISE_V0 = np.asarray(
    (
        (-0.21435169936062012, -0.5206975097354146, -0.36823674215598584),
        (-0.12765207026469663, -0.32838804751566897, 0.021119964256022868),
        (0.367648567567327, 0.44485770952532994, -0.1965474443059929),
    ),
    dtype=np.float64,
)
np.testing.assert_allclose(noise_batch, GOLDEN_NOISE_V0, atol=2.0e-15, rtol=0.0)


turbulent_payload = specs.WindPayloadV0(
    speed_mps=2.0,
    turbulence=0.65,
    spatial_scale_m=1.25,
    temporal_frequency_hz=0.8,
    octaves=4,
    lacunarity=2.0,
    gain=0.5,
    seed_u32=987654321,
)
positions = np.asarray(
    ((0.1, 0.2, 0.3), (1.0, -2.0, 4.0), (-0.75, 0.5, 2.25)),
    dtype=np.float64,
)
whole = wind.sample_wind_raw_v0(
    turbulent_payload,
    (0.0, 0.0, 1.0),
    positions,
    1.75,
)
repeated = wind.sample_wind_raw_v0(
    turbulent_payload,
    (0.0, 0.0, 1.0),
    positions,
    1.75,
)
chunked = np.concatenate(
    [
        wind.sample_wind_raw_v0(
            turbulent_payload,
            (0.0, 0.0, 1.0),
            positions[index : index + 1],
            1.75,
        )
        for index in range(len(positions))
    ],
    axis=0,
)
np.testing.assert_array_equal(whole, repeated)
np.testing.assert_array_equal(whole, chunked)
whole_reference = np.asarray(
    [
        wind.sample_wind_raw_reference_v0(
            turbulent_payload,
            (0.0, 0.0, 1.0),
            position,
            1.75,
        )
        for position in positions
    ],
    dtype=np.float64,
)
np.testing.assert_allclose(whole, whole_reference, atol=2.0e-7, rtol=0.0)
np.testing.assert_array_equal(
    whole,
    np.asarray(
        (
            (-0.28094667196273804, -0.010294402949512005, 2.1440203189849854),
            (-0.22693201899528503, -0.18528668582439423, 1.9713077545166016),
            (-0.23273640871047974, 0.07900166511535645, 1.9297974109649658),
        ),
        dtype=np.float32,
    ),
)
assert not np.array_equal(
    whole,
    wind.sample_wind_raw_v0(
        turbulent_payload,
        (0.0, 0.0, 1.0),
        positions,
        1.8,
    ),
)


# 公共 sampler 固定预览状态、scope、叠加顺序与 selected 过滤。
field_z = specs.FieldSpecV0(
    "field-z",
    "object-z",
    volume=specs.VolumeSpecV0(shape="BOX"),
    wind=specs.WindPayloadV0(speed_mps=2.0),
    status=names.FIELD_STATUS_ACTIVE,
    priority=10,
)
field_x = specs.FieldSpecV0(
    "field-x",
    "object-x",
    volume=specs.VolumeSpecV0(shape="BOX", world_transform=ROTATE_Z_TO_X),
    wind=specs.WindPayloadV0(speed_mps=1.0),
    status=names.FIELD_STATUS_ACTIVE,
    priority=-10,
)
ordered_snapshot = specs.FieldSnapshotV0((field_z, field_x), sample_time_seconds=2.0)
assert tuple(item.field_id for item in ordered_snapshot.fields) == ("field-x", "field-z")
combined = sampling.sample_air_velocity_v0(
    ordered_snapshot,
    ((0.0, 0.0, 0.0), (0.5, 0.0, 0.0)),
)
np.testing.assert_array_equal(
    combined.values_world_f32,
    ((1.0, 0.0, 2.0), (1.0, 0.0, 2.0)),
)
assert combined.sampled_field_ids == ("field-x", "field-z")
assert not combined.values_world_f32.flags.writeable
assert len(combined.request_signature) == 16
assert len(combined.sample_signature) == 16
_expect_error(ValueError, lambda: combined.values_world_f32.__setitem__((0, 0), 9.0))
combined_reference = sampling.sample_air_velocity_reference_at_v0(
    ordered_snapshot,
    (0.0, 0.0, 0.0),
)
np.testing.assert_allclose(
    combined.values_world_f32[0],
    combined_reference,
    atol=2.0e-7,
    rtol=0.0,
)
different_substep = sampling.sample_air_velocity_v0(
    ordered_snapshot,
    (0.0, 0.0, 0.0),
    sample_time_seconds=2.01,
)
assert different_substep.snapshot_signature == combined.snapshot_signature
assert different_substep.sample_signature != combined.sample_signature

selected = sampling.sample_air_velocity_v0(
    ordered_snapshot,
    (0.0, 0.0, 0.0),
    selected_field_ids=("field-z",),
)
np.testing.assert_array_equal(selected.values_world_f32[0], (0.0, 0.0, 2.0))
selected_by_string = sampling.sample_air_velocity_v0(
    ordered_snapshot,
    (0.0, 0.0, 0.0),
    selected_field_ids="field-z",
)
selected_reference = sampling.sample_air_velocity_reference_at_v0(
    ordered_snapshot,
    (0.0, 0.0, 0.0),
    selected_field_ids="field-z",
)
np.testing.assert_array_equal(selected_by_string.values_world_f32[0], selected_reference)
point = sampling.sample_air_velocity_at_v0(
    ordered_snapshot,
    (0.0, 0.0, 0.0),
)
assert point.value_world_mps == (1.0, 0.0, 2.0)
assert point.request_signature
assert point.sample_signature

# 请求签名覆盖位置的精确 float64 布局以及全部筛选、作用域上下文。
signature_request_defaults = {
    "consumer_id": "mc2",
    "object_id": "shirt",
    "collection_ids": ("cloth", "hero"),
    "collision_groups": (3, 7),
    "include_preview": True,
    "selected_field_ids": ("field-x", "field-z"),
}


def _signature_request(position=(0.0, 0.0, 0.0), **overrides):
    kwargs = dict(signature_request_defaults)
    kwargs.update(overrides)
    return sampling.sample_air_velocity_v0(ordered_snapshot, position, **kwargs)


signature_base = _signature_request()
signature_same_semantics = _signature_request(
    consumer_id=" mc2 ",
    object_id=" shirt ",
    collection_ids=("hero", "cloth", "cloth"),
    collision_groups=(7, 3, 3),
    include_preview=1,
    selected_field_ids=("field-z", " field-x ", "field-z"),
)
assert signature_base.request_signature == "47ffead39d06c6b8"
assert signature_base.sample_signature == "2b609c49d9ba74a0"
assert signature_same_semantics.request_signature == signature_base.request_signature
assert signature_same_semantics.sample_signature == signature_base.sample_signature

signature_variants = (
    _signature_request((0.5, 0.0, 0.0)),
    _signature_request((-0.0, 0.0, 0.0)),
    _signature_request(consumer_id="rigid"),
    _signature_request(object_id="cape"),
    _signature_request(collection_ids=("cloth",)),
    _signature_request(collision_groups=(3,)),
    _signature_request(include_preview=False),
    _signature_request(selected_field_ids=("field-x", "field-z", "missing")),
)
for variant in signature_variants:
    # 这些请求可产生相同数值，但不允许共用请求或结果签名。
    np.testing.assert_array_equal(variant.values_world_f32, signature_base.values_world_f32)
    assert variant.request_signature != signature_base.request_signature
    assert variant.sample_signature != signature_base.sample_signature

no_selection = sampling.sample_air_velocity_v0(
    ordered_snapshot,
    (0.0, 0.0, 0.0),
    selected_field_ids=(),
)
all_selection = sampling.sample_air_velocity_v0(
    ordered_snapshot,
    (0.0, 0.0, 0.0),
    selected_field_ids=None,
)
assert no_selection.request_signature != all_selection.request_signature
assert no_selection.stats.sampled_field_count == 0
assert all_selection.stats.sampled_field_count == 2

preview_snapshot = specs.FieldSnapshotV0((default_field,))
preview_hidden = sampling.sample_air_velocity_v0(
    preview_snapshot,
    (0.0, 0.0, 0.0),
)
np.testing.assert_array_equal(preview_hidden.values_world_f32[0], (0.0, 0.0, 0.0))
assert preview_hidden.diagnostics[0].code == names.FIELD_PREVIEW_ONLY
preview_visible = sampling.sample_air_velocity_v0(
    preview_snapshot,
    (0.0, 0.0, 0.0),
    include_preview=True,
)
np.testing.assert_array_equal(preview_visible.values_world_f32[0], (0.0, 0.0, 1.0))

scoped = specs.FieldSpecV0(
    "scoped",
    "object-scoped",
    volume=specs.VolumeSpecV0(shape="BOX"),
    scope=specs.FieldScopeV0(
        solver_ids=("mc2",),
        collection_ids=("cloth",),
        include_ids=("shirt",),
        exclude_ids=("cape",),
        collision_groups=(3,),
    ),
    status=names.FIELD_STATUS_ACTIVE,
)
scoped_snapshot = specs.FieldSnapshotV0((scoped,))
allowed = sampling.sample_air_velocity_v0(
    scoped_snapshot,
    (0.0, 0.0, 0.0),
    consumer_id="mc2",
    object_id="shirt",
    collection_ids=("cloth",),
    collision_groups=(3,),
)
assert allowed.stats.sampled_field_count == 1
blocked = sampling.sample_air_velocity_v0(
    scoped_snapshot,
    (0.0, 0.0, 0.0),
    consumer_id="rigid",
    object_id="shirt",
    collection_ids=("cloth",),
    collision_groups=(3,),
)
assert blocked.stats.sampled_field_count == 0
assert blocked.diagnostics[0].code == names.FIELD_OUT_OF_SCOPE


# PhysicsFrameContext 只负责由 World 写入后的子步时间派生，不读取墙钟。
types_module = _load_module(
    f"{PACKAGE_ROOT}.types",
    PHYSICS_WORLD_ROOT / "types.py",
)
frame_context = types_module.PhysicsFrameContext()
frame_context.sample_time_seconds = 1.25
frame_context.frame_step_dt = 0.2
frame_context.substeps = 4
assert frame_context.substep_sample_time_seconds(0) == 1.25
assert frame_context.substep_sample_time_seconds(3) == 1.4
_expect_error(ValueError, lambda: frame_context.substep_sample_time_seconds(4))


print("Physics Field core: PASS")
