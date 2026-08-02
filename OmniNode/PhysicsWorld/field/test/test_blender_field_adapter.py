# -*- coding: utf-8 -*-
"""Field Blender 边界的后台集成测试。

用法：
    blender.exe --factory-startup --background --python test_blender_field_adapter.py
"""

from __future__ import annotations

import importlib
import math
import os
import sys
import types

import bpy
from mathutils import Matrix


FIELD_TEST_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD_ROOT = os.path.dirname(FIELD_TEST_ROOT)
OMNINODE_ROOT = os.path.dirname(PHYSICS_WORLD_ROOT)
HOTOOLS_ROOT = os.path.dirname(OMNINODE_ROOT)

for package_name, package_path in (
    ("HoTools", HOTOOLS_ROOT),
    ("HoTools.OmniNode", OMNINODE_ROOT),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)


field_properties = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.properties"
)
field_schema = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.schema"
)
field_capabilities = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.capabilities"
)
field_channels = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.channels"
)
field_package = importlib.import_module("HoTools.OmniNode.PhysicsWorld.field")
field_implicit = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.implicit_objects"
)
field_specs = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.specs"
)
field_visualization = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.visualization"
)
field_names = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.names"
)
world_types = importlib.import_module("HoTools.OmniNode.PhysicsWorld.types")


def _register_properties() -> None:
    cls = field_properties.PG_Hotools_Field
    try:
        bpy.utils.register_class(cls)
    except RuntimeError:
        pass
    if not hasattr(bpy.types.Object, "hotools_field"):
        bpy.types.Object.hotools_field = bpy.props.PointerProperty(type=cls)


def _unregister_properties() -> None:
    cls = field_properties.PG_Hotools_Field
    if hasattr(bpy.types.Object, "hotools_field"):
        del bpy.types.Object.hotools_field
    try:
        bpy.utils.unregister_class(cls)
    except RuntimeError:
        pass


def _new_empty(name: str):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _contains_blender_reference(value, seen=None) -> bool:
    seen = set() if seen is None else seen
    identity = id(value)
    if identity in seen:
        return False
    seen.add(identity)
    if isinstance(value, bpy.types.bpy_struct):
        return True
    if isinstance(value, dict):
        return any(
            _contains_blender_reference(key, seen)
            or _contains_blender_reference(item, seen)
            for key, item in value.items()
        )
    if isinstance(value, (tuple, list, set)):
        return any(_contains_blender_reference(item, seen) for item in value)
    fields = getattr(value, "__dataclass_fields__", None)
    if isinstance(fields, dict):
        return any(
            _contains_blender_reference(getattr(value, name), seen)
            for name in fields
        )
    return False


def test_property_defaults_and_uuid_lifecycle() -> None:
    obj = _new_empty("Field_Defaults")
    props = obj.hotools_field
    assert props.enabled is False
    assert not hasattr(props, "status")
    assert props.field_type == field_names.FIELD_TYPE_WIND
    assert props.shape == field_names.VOLUME_SHAPE_SPHERE
    assert props.turbulence == 0.0
    assert props.field_id == ""

    # 启用回调负责在第一次纳入物理世界时补齐身份。
    props.enabled = True
    field_id = props.field_id
    assert str(__import__("uuid").UUID(field_id)) == field_id
    assert field_properties.ensure_field_id_v0(obj) == field_id
    obj.name = "Field_Renamed"
    assert field_properties.ensure_field_id_v0(obj) == field_id

    replacement = field_properties.ensure_field_id_v0(obj, force_new=True)
    assert replacement != field_id
    assert str(__import__("uuid").UUID(replacement)) == replacement


def test_rna_and_capability_share_pure_schema() -> None:
    schema = field_schema.FIELD_RNA_FIELDS
    capability = field_capabilities.FIELD_AIR_VELOCITY_CAPABILITY
    fields = tuple(capability["fields"])
    names = tuple(str(item["name"]) for item in schema)

    assert field_properties.FIELD_RNA_FIELDS is schema
    assert "bpy" not in field_schema.__dict__
    assert len(schema) == 19
    assert all("factory" not in item for item in schema)
    assert tuple(field_properties.PG_Hotools_Field.__annotations__) == names
    assert tuple(str(item["name"]) for item in fields) == names
    for declaration, field in zip(schema, fields):
        assert field["rna"] == declaration["kwargs"]
        assert field["default"] == declaration["kwargs"].get("default")
        assert field["explicit_property"] == (
            f"Object.hotools_field.{declaration['name']}"
        )
        assert field["update_policy"] == declaration["update_policy"]

    shape = next(item for item in fields if item["name"] == "shape")
    assert tuple(shape["values"]) == capability["volume_shapes"]


def test_component_descriptor_exposes_rna_and_scope_collector() -> None:
    descriptor = field_package.COMPONENT_MODULE
    assert descriptor["blender_properties"] == ".properties:FIELD_BLENDER_PROPERTIES"
    assert descriptor["scope_collectors"] == (
        ".implicit_objects:collect_scope_field_specs",
        ".debug_draw:begin_field_runtime_debug_evaluation",
    )


def test_resolver_uses_evaluated_empty_and_keeps_one_to_one_unit_policy() -> None:
    obj = _new_empty("Field_Resolver")
    field_properties.ensure_field_id_v0(obj)
    obj.hotools_field.enabled = True
    obj.hotools_field.shape = field_names.VOLUME_SHAPE_BOX
    obj.hotools_field.speed_mps = 3.25
    obj.hotools_field.turbulence = 0.4
    obj.hotools_field.scope_solver_ids = "mc2, rigid"
    obj.matrix_world = Matrix.Translation((2.0, 3.0, 4.0)) @ Matrix.Diagonal(
        (2.0, 3.0, 4.0, 1.0)
    )
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 0.01
    bpy.context.view_layer.update()

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    spec = field_properties.resolve_field_spec_v0(
        obj,
        evaluated_object=evaluated,
    )
    assert spec.source_id == f"blender.field:{spec.field_id}"
    assert spec.status == field_names.FIELD_STATUS_ACTIVE
    assert spec.field_type == field_names.FIELD_TYPE_WIND
    assert spec.volume.world_transform[0][3] == 2.0
    assert spec.volume.world_scale == (2.0, 3.0, 4.0)
    assert spec.wind.speed_mps == 3.25
    assert math.isclose(spec.wind.turbulence, 0.4, rel_tol=0.0, abs_tol=1.0e-6)
    assert spec.scope.solver_ids == ("mc2", "rigid")
    assert not _contains_blender_reference(spec)


def test_sphere_non_uniform_scale_is_explicitly_invalid() -> None:
    obj = _new_empty("Field_InvalidSphere")
    field_properties.ensure_field_id_v0(obj)
    obj.hotools_field.enabled = True
    obj.hotools_field.shape = field_names.VOLUME_SHAPE_SPHERE
    obj.scale = (1.0, 2.0, 1.0)
    bpy.context.view_layer.update()
    try:
        field_properties.resolve_field_spec_v0(obj)
    except ValueError as exc:
        assert "非均匀" in str(exc)
    else:
        raise AssertionError("球形场的非均匀 scale 必须失败")


def test_visualization_uses_public_sampler_for_bounds_and_vectors() -> None:
    box = _new_empty("Field_VisualizationBox")
    field_properties.ensure_field_id_v0(box)
    box.hotools_field.enabled = True
    box.hotools_field.shape = field_names.VOLUME_SHAPE_BOX
    box.hotools_field.speed_mps = 2.0
    box.scale = (2.0, 1.0, 0.5)
    bpy.context.view_layer.update()

    box_spec = field_properties.resolve_field_spec_v0(box)
    snapshot = field_specs.build_field_snapshot_v0(
        (box_spec,),
        generation=1,
        frame=12,
        sample_time_seconds=0.5,
    )
    bounds, falloff, vectors = field_visualization.build_field_visualization_batches_v0(
        snapshot,
        density=3,
        glyph_scale=0.25,
    )
    assert bounds[0]
    assert falloff[0] == ()
    assert vectors[0]

    hidden = field_visualization.build_field_visualization_batches_v0(
        snapshot,
        selected_field_ids=("不存在的-field-id",),
    )
    assert all(lines == () for lines, _color, _width in hidden)

    sphere = _new_empty("Field_VisualizationSphere")
    field_properties.ensure_field_id_v0(sphere)
    sphere.hotools_field.enabled = True
    sphere.hotools_field.shape = field_names.VOLUME_SHAPE_SPHERE
    sphere.scale = (2.0, 2.0, 2.0)
    bpy.context.view_layer.update()
    sphere_snapshot = field_specs.build_field_snapshot_v0(
        (field_properties.resolve_field_spec_v0(sphere),),
        sample_time_seconds=0.0,
    )
    sphere_batches = field_visualization.build_field_visualization_batches_v0(
        sphere_snapshot,
        density=3,
    )
    assert sphere_batches[0][0]
    assert sphere_batches[1][0]
    assert sphere_batches[2][0]


def test_generic_channel_visualization_has_reserved_scalar_and_sdf_modes() -> None:
    positions = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0))
    vector = field_visualization.build_field_channel_visualization_v0(
        field_names.AIR_VELOCITY_CHANNEL_ID,
        positions,
        ((1.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 3.0)),
    )
    assert vector["status"] == field_names.FIELD_STATUS_ACTIVE
    assert vector["line_batches"] and vector["point_batches"] == ()

    scalar = field_visualization.build_field_channel_visualization_v0(
        "mask",
        positions,
        (0.0, 0.5, 1.0),
        scalar_range=(0.0, 1.0),
    )
    assert scalar["status"] == field_names.FIELD_STATUS_RESERVED
    assert scalar["point_batches"]
    assert sum(len(points) for points, _color, _size in scalar["point_batches"]) == 3

    sdf = field_visualization.build_field_channel_visualization_v0(
        "sdf",
        positions,
        (-1.0, 0.0, 1.0),
    )
    assert sdf["visualization_mode"] == field_channels.VISUALIZATION_SDF_ZERO_CROSSING
    assert len(sdf["point_batches"]) == 3
    assert sum(len(points) for points, _color, _size in sdf["point_batches"]) == 3

    reserved = field_visualization.build_field_channel_visualization_v0(
        "tensor",
        positions,
    )
    assert reserved["diagnostics"] == ("FIELD_RESERVED_CHANNEL",)
    assert reserved["line_batches"] == ()
    assert reserved["point_batches"] == ()

    empty_vector = field_visualization.build_field_channel_visualization_v0(
        field_names.AIR_VELOCITY_CHANNEL_ID,
        (),
        (),
    )
    assert empty_vector["sample_count"] == 0

    invalid_calls = (
        lambda: field_visualization.build_field_channel_visualization_v0(
            field_names.AIR_VELOCITY_CHANNEL_ID,
            positions,
            ((1.0, 0.0, 0.0),) * 3,
            glyph_scale=float("nan"),
        ),
        lambda: field_visualization.build_field_channel_visualization_v0(
            "mask",
            positions,
            (0.0, 0.5, 1.0),
            point_size=0.0,
        ),
        lambda: field_visualization.build_field_channel_visualization_v0(
            "sdf",
            positions,
            (-1.0, 0.0, 1.0),
            sdf_zero_tolerance=float("inf"),
        ),
    )
    for invalid_call in invalid_calls:
        try:
            invalid_call()
        except ValueError:
            pass
        else:
            raise AssertionError("无效可视化参数必须显式失败")


def test_batch_resolver_rejects_duplicate_uuid_before_returning() -> None:
    first = _new_empty("Field_DuplicateA")
    second = _new_empty("Field_DuplicateB")
    field_id = field_properties.ensure_field_id_v0(first)
    second.hotools_field.field_id = field_id
    first.hotools_field.enabled = True
    second.hotools_field.enabled = True
    try:
        field_properties.resolve_field_specs_v0((first, second))
    except field_properties.DuplicateFieldIdError as exc:
        assert exc.field_id == field_id
        assert set(exc.source_labels) == {first.name_full, second.name_full}
    else:
        raise AssertionError("重复 UUID 不得被 stable_id 静默覆盖")


def test_manifest_reconcile_removes_disabled_deleted_and_invalid_sources() -> None:
    active = _new_empty("Field_ManifestActive")
    disabled = _new_empty("Field_ManifestDisabled")
    duplicate = _new_empty("Field_ManifestDuplicate")
    active_id = field_properties.ensure_field_id_v0(active)
    disabled_id = field_properties.ensure_field_id_v0(disabled)
    duplicate.hotools_field.field_id = active_id
    active.hotools_field.enabled = True
    disabled.hotools_field.enabled = False
    duplicate.hotools_field.enabled = False

    world = world_types.PhysicsWorldCache()
    scope = world_types.PhysicsObjectScope((active, disabled))
    report = field_implicit.collect_scope_field_specs(world, scope)
    assert report.registered_ids == (active_id,)
    assert report.disabled_ids == (disabled_id,)
    assert len(world.implicit_objects) == 1

    entry = world.implicit_objects[0]
    assert entry["tag"] == field_names.FIELD_OBJECT_TAG
    assert entry["stable_id"] == active_id
    assert entry["schema"] == 1
    assert entry["payload"]["abi_version"] == 0
    assert entry["metadata"]["unit_policy_provisional"] is True
    assert not _contains_blender_reference(entry)
    snapshot = world.runtime_cache(field_implicit.FIELD_SNAPSHOT_CACHE_KEY_V0)
    assert tuple(item.field_id for item in snapshot.fields) == (active_id,)

    # Blender 复制对象会复制 UUID。World Begin 保留先出现的源，并给后续源重签。
    duplicate.hotools_field.enabled = True
    conflict_scope = world_types.PhysicsObjectScope((active, duplicate, disabled))
    conflict_report = field_implicit.collect_scope_field_specs(world, conflict_scope)
    duplicate_id = duplicate.hotools_field.field_id
    assert duplicate_id != active_id
    assert conflict_report.registered_ids == tuple(sorted((active_id, duplicate_id)))
    assert conflict_report.removed_ids == ()
    assert len(world.implicit_objects) == 2
    diagnostics = world.runtime_cache(field_names.FIELD_DIAGNOSTICS_CHANNEL)
    assert any(
        item.code == field_implicit.FIELD_DUPLICATE_ID
        and item.field_id == duplicate_id
        and item.severity == "WARNING"
        for item in diagnostics
    )

    # 后续源离开 scope、保留源禁用时，两个身份都必须从 manifest 删除。
    active.hotools_field.enabled = False
    disabled_report = field_implicit.collect_scope_field_specs(
        world,
        world_types.PhysicsObjectScope((active, disabled)),
    )
    assert disabled_report.removed_ids == tuple(sorted((active_id, duplicate_id)))
    assert world.implicit_objects == []

    # 源从 manifest 中删除时同样不能留下持久 entry。
    active.hotools_field.enabled = True
    field_implicit.collect_scope_field_specs(
        world,
        world_types.PhysicsObjectScope((active,)),
    )
    deleted_report = field_implicit.collect_scope_field_specs(
        world,
        world_types.PhysicsObjectScope(()),
    )
    assert deleted_report.removed_ids == (active_id,)
    assert world.implicit_objects == []


def test_scope_toggle_and_deleted_live_source_publish_safe_empty_runtime() -> None:
    obj = _new_empty("Field_RuntimeDelete")
    field_id = field_properties.ensure_field_id_v0(obj)
    obj.hotools_field.enabled = True
    world = world_types.PhysicsWorldCache()
    world.generation = 9
    world.frame_context.initialized = True
    world.frame_context.generation = 9
    world.frame_context.frame = 12

    disabled_scope = world_types.PhysicsObjectScope((obj,), include_field=False)
    disabled_report = field_implicit.collect_scope_field_specs(world, disabled_scope)
    assert disabled_report.registered_ids == ()
    disabled_runtime = world.runtime_cache(
        field_names.FIELD_NATIVE_RUNTIME_CACHE_KEY_V1
    )
    assert disabled_runtime.debug_snapshot()["field_count"] == 0

    active_scope = world_types.PhysicsObjectScope((obj,), include_field=True)
    active_report = field_implicit.collect_scope_field_specs(world, active_scope)
    assert active_report.registered_ids == (field_id,)
    active_runtime = world.runtime_cache(
        field_names.FIELD_NATIVE_RUNTIME_CACHE_KEY_V1
    )
    assert active_runtime is not disabled_runtime
    assert disabled_runtime.live is False
    assert active_runtime.debug_snapshot()["field_count"] == 1

    stale_reference = obj
    bpy.data.objects.remove(obj, do_unlink=True)
    deleted_report = field_implicit.collect_scope_field_specs(
        world,
        world_types.PhysicsObjectScope((stale_reference,), include_field=True),
    )
    empty_runtime = world.runtime_cache(field_names.FIELD_NATIVE_RUNTIME_CACHE_KEY_V1)
    assert deleted_report.removed_ids == (field_id,)
    assert active_runtime.live is False
    assert empty_runtime.live is True
    assert empty_runtime.debug_snapshot()["field_count"] == 0
    assert world.implicit_objects == []
    world.omni_cache_dispose("deleted_field_runtime_test")


def test_source_vanishing_between_identity_and_spec_becomes_diagnostic() -> None:
    field_id = "0c9e7832-3650-4f37-ae22-b821399904da"

    class _VanishingSource:
        name_full = "Field_VanishingDuringStage"
        type = "EMPTY"

        def __init__(self):
            self.read_count = 0

        @property
        def original(self):
            return self

        @property
        def hotools_field(self):
            self.read_count += 1
            if self.read_count > 1:
                raise ReferenceError("StructRNA of type Object has been removed")
            return types.SimpleNamespace(field_id=field_id, enabled=True)

    source = _VanishingSource()
    stage = field_implicit.stage_field_sources_v0((source,))
    assert stage.specs == ()
    assert stage.source_count == 1
    assert source.read_count == 2
    assert any(
        item.code == field_names.FIELD_INVALID_SPEC
        and item.field_id == field_id
        for item in stage.diagnostics
    )


def test_candidate_property_group_vanishing_is_ignored() -> None:
    class _VanishingProperties:
        @property
        def field_id(self):
            raise ReferenceError("StructRNA of type HotoolsField has been removed")

    class _VanishingCandidate:
        name_full = "Field_VanishingCandidateProperties"

        @property
        def original(self):
            return self

        @property
        def hotools_field(self):
            return _VanishingProperties()

    stage = field_implicit.stage_field_sources_v0((_VanishingCandidate(),))
    assert stage.specs == ()
    assert stage.source_count == 0


def test_stage_keeps_frozen_identity_when_rna_id_changes() -> None:
    frozen_id = "3620cc5e-eaef-4b1e-b341-4c61d83d9023"
    changed_id = "16bc953a-e065-455f-8080-8742e879a490"

    class _ChangingIdentitySource:
        name_full = "Field_ChangingIdentityDuringStage"
        type = "EMPTY"
        matrix_world = Matrix.Identity(4)

        def __init__(self):
            self.read_count = 0

        @property
        def original(self):
            return self

        @property
        def hotools_field(self):
            self.read_count += 1
            if self.read_count == 1:
                return types.SimpleNamespace(field_id=frozen_id, enabled=True)
            return types.SimpleNamespace(
                field_id=changed_id,
                enabled=True,
                field_type=field_names.FIELD_TYPE_WIND,
                shape=field_names.VOLUME_SHAPE_BOX,
                speed_mps=2.0,
                turbulence=0.0,
                spatial_scale_m=1.0,
                temporal_frequency_hz=1.0,
                octaves=1,
                lacunarity=2.0,
                gain=0.5,
                seed_u32=7,
                blend_weight=1.0,
                priority=0,
                scope_solver_ids="",
                scope_collection_ids="",
                scope_include_ids="",
                scope_exclude_ids="",
                scope_collision_groups="",
            )

    source = _ChangingIdentitySource()
    stage = field_implicit.stage_field_sources_v0((source,))
    assert len(stage.specs) == 1
    assert stage.specs[0].field_id == frozen_id
    assert stage.specs[0].source_id == f"blender.field:{frozen_id}"
    assert source.read_count == 2


def test_manifest_rejects_foreign_producer_without_mutation() -> None:
    obj = _new_empty("Field_ForeignProducer")
    field_id = field_properties.ensure_field_id_v0(obj)
    obj.hotools_field.enabled = True
    spec = field_properties.resolve_field_spec_v0(obj)
    world = world_types.PhysicsWorldCache()
    foreign = world.append_implicit_object(
        tag=field_names.FIELD_OBJECT_TAG,
        producer="foreign.field.writer",
        stable_id=field_id,
        signature="foreign-signature",
        payload={"abi_version": 0, "foreign": True},
    )
    before = list(world.implicit_objects)
    try:
        field_implicit.reconcile_field_manifest_v0(world, (spec,))
    except field_implicit.FieldImplicitOwnershipConflict as exc:
        assert field_id in str(exc)
    else:
        raise AssertionError("跨 producer 的同 stable_id 冲突必须失败")
    assert world.implicit_objects == before
    assert world.implicit_objects[0] is foreign


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


def main() -> None:
    _register_properties()
    passed = 0
    try:
        for name, test in TESTS:
            test()
            passed += 1
            print(f"[通过] {name}")
    finally:
        _unregister_properties()
    print(f"{passed}/{len(TESTS)} 项测试通过")
    if passed != len(TESTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
