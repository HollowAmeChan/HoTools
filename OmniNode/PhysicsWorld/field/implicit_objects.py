"""Blender Field 源到 Physics World 隐式对象的注册与对账。"""

from __future__ import annotations

from dataclasses import dataclass
import uuid

from .diagnostics import FieldDiagnosticV0
from .names import (
    FIELD_ABI_VERSION,
    FIELD_DIAGNOSTICS_CHANNEL,
    FIELD_INVALID_SPEC,
    FIELD_NATIVE_RUNTIME_CACHE_KEY_V1,
    FIELD_OBJECT_TAG,
    FIELD_SNAPSHOT_CACHE_KEY_V0,
)
from .native import NativeFieldRuntimeV1
from .properties import (
    FIELD_BLENDER_UNIT_POLICY_V0,
    FIELD_BLENDER_UNIT_TO_METER_V0,
    canonical_field_id_v0,
    evaluated_field_object_v0,
    resolve_field_spec_v0,
)
from .specs import FieldSpecV0, build_field_snapshot_v0


FIELD_IMPLICIT_SCHEMA_V1 = 1
FIELD_IMPLICIT_PRODUCER_V0 = "physics.field.scope.v0"
FIELD_MISSING_ID = "FIELD_MISSING_ID"
FIELD_DUPLICATE_ID = "FIELD_DUPLICATE_ID"
FIELD_INVALID_SOURCE = "FIELD_INVALID_SOURCE"
FIELD_UNIT_POLICY_PROVISIONAL = "FIELD_UNIT_POLICY_PROVISIONAL"


class FieldImplicitOwnershipConflict(RuntimeError):
    """同一个 tag/stable_id 已由其它 producer 拥有。"""


@dataclass(frozen=True, slots=True)
class FieldSourceStageV0:
    """对 Blender 源完成校验后的纯暂存结果。"""

    specs: tuple[FieldSpecV0, ...]
    disabled_field_ids: tuple[str, ...]
    diagnostics: tuple[FieldDiagnosticV0, ...]
    source_count: int


@dataclass(frozen=True, slots=True)
class FieldManifestReportV0:
    """一次隐式对象 manifest 对账的可检查结果。"""

    registered_ids: tuple[str, ...]
    removed_ids: tuple[str, ...]
    dirty_ids: tuple[str, ...]
    disabled_ids: tuple[str, ...]


def _flatten_sources(values) -> tuple:
    pending = list(values or ())
    result = []
    while pending:
        value = pending.pop(0)
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
        elif value is not None:
            result.append(value)
    return tuple(result)


def _source_label(obj) -> str:
    try:
        return str(obj.name_full)
    except (AttributeError, ReferenceError):
        return "<无效对象>"


def _authoring_object(obj):
    try:
        original = obj.original
    except (AttributeError, ReferenceError):
        original = None
    return original if original is not None else obj


def _candidate_identity(obj):
    authoring_obj = _authoring_object(obj)
    try:
        props = authoring_obj.hotools_field
    except (AttributeError, ReferenceError):
        return None
    raw_id = str(getattr(props, "field_id", "") or "").strip()
    enabled = bool(getattr(props, "enabled", False))
    if not raw_id and not enabled:
        return None
    if not raw_id:
        raise ValueError("缺少持久 field_id；请使用创建或修复操作生成 UUID")
    return canonical_field_id_v0(raw_id), enabled


def repair_duplicate_field_ids_v0(objects) -> tuple[FieldDiagnosticV0, ...]:
    """在 World Begin 边界修复 Blender 复制产生的重复 Field UUID。"""
    used_ids: set[str] = set()
    seen_objects: set[int] = set()
    diagnostics = []
    for obj in _flatten_sources(objects):
        authoring_obj = _authoring_object(obj)
        try:
            object_key = int(authoring_obj.as_pointer())
            if object_key in seen_objects:
                continue
            seen_objects.add(object_key)
            props = authoring_obj.hotools_field
            raw_id = str(getattr(props, "field_id", "") or "").strip()
            enabled = bool(getattr(props, "enabled", False))
        except (AttributeError, ReferenceError, TypeError):
            continue
        if not raw_id and not enabled:
            continue
        try:
            field_id = canonical_field_id_v0(raw_id)
        except ValueError:
            continue
        if field_id not in used_ids:
            used_ids.add(field_id)
            continue

        new_id = str(uuid.uuid4())
        while new_id in used_ids:
            new_id = str(uuid.uuid4())
        try:
            props.field_id = new_id
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            # linked/read-only 数据不能静默伪造身份；后续纯暂存会保留重复诊断。
            continue
        used_ids.add(new_id)
        diagnostics.append(FieldDiagnosticV0(
            code=FIELD_DUPLICATE_ID,
            field_id=new_id,
            message=(
                f"Field 源 {_source_label(authoring_obj)} 的重复 ID {field_id} "
                f"已在帧开始自动改为 {new_id}"
            ),
            severity="WARNING",
        ))
    return tuple(diagnostics)


def stage_field_sources_v0(objects, *, depsgraph=None) -> FieldSourceStageV0:
    """先完成全部身份与规格校验；本函数不修改 world 或 Blender。"""
    sources = _flatten_sources(objects)
    diagnostics = []
    candidates = []
    identities: dict[str, list[tuple[object, bool, str]]] = {}

    for obj in sources:
        label = _source_label(_authoring_object(obj))
        try:
            identity = _candidate_identity(obj)
        except ValueError as exc:
            diagnostics.append(FieldDiagnosticV0(
                code=FIELD_MISSING_ID if "缺少" in str(exc) else FIELD_INVALID_SOURCE,
                message=f"Field 源 {label} 无效：{exc}",
                severity="ERROR",
            ))
            continue
        if identity is None:
            continue
        field_id, enabled = identity
        # 身份校验通过后把 field_id 一并带入暂存，后续不再回读可能已被
        # Blender 删除的 RNA 对象；规格解析仍然只在当前对象有效时进行。
        entry = (obj, enabled, label, field_id)
        identity_entry = (obj, enabled, label)
        candidates.append(entry)
        identities.setdefault(field_id, []).append(identity_entry)

    duplicate_ids = {
        field_id
        for field_id, entries in identities.items()
        if len(entries) > 1
    }
    for field_id in sorted(duplicate_ids):
        labels = tuple(entry[2] for entry in identities[field_id])
        diagnostics.append(FieldDiagnosticV0(
            code=FIELD_DUPLICATE_ID,
            field_id=field_id,
            message=f"Field ID 重复，所有冲突源均已判为无效：{', '.join(labels)}",
            severity="ERROR",
        ))

    specs = []
    disabled_ids = []
    for obj, identity_enabled, label, field_id in candidates:
        if field_id in duplicate_ids:
            continue
        if not identity_enabled:
            disabled_ids.append(field_id)
            continue
        evaluated_obj = evaluated_field_object_v0(obj, depsgraph)
        try:
            specs.append(resolve_field_spec_v0(
                obj,
                evaluated_object=evaluated_obj,
                depsgraph=depsgraph,
            ))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            diagnostics.append(FieldDiagnosticV0(
                code=FIELD_INVALID_SPEC,
                field_id=field_id,
                message=f"Field 源 {label} 无法生成规格：{exc}",
                severity="ERROR",
            ))

    if candidates:
        diagnostics.append(FieldDiagnosticV0(
            code=FIELD_UNIT_POLICY_PROVISIONAL,
            message=(
                "Field V0 暂按 1 Blender unit = 1 m 解析位置、体积和空间尺度；"
                "Scene 单位换算所有权尚未冻结"
            ),
            severity="WARNING",
        ))

    return FieldSourceStageV0(
        specs=tuple(sorted(specs, key=lambda item: (item.priority, item.field_id))),
        disabled_field_ids=tuple(sorted(set(disabled_ids))),
        diagnostics=tuple(diagnostics),
        source_count=len(candidates),
    )


def field_implicit_entry_v0(
    spec: FieldSpecV0,
    *,
    producer: str = FIELD_IMPLICIT_PRODUCER_V0,
) -> dict:
    """构造 schema=1、payload ABI=0 且不含 live Blender 引用的 entry。"""
    if not isinstance(spec, FieldSpecV0):
        raise TypeError("Field implicit entry 只接受 FieldSpecV0")
    return {
        "tag": FIELD_OBJECT_TAG,
        "stable_id": spec.field_id,
        "schema": FIELD_IMPLICIT_SCHEMA_V1,
        "signature": spec.signature,
        "enabled": bool(spec.enabled),
        "producer": str(producer),
        "source_id": spec.source_id,
        "priority": spec.priority,
        "payload": {
            "abi_version": FIELD_ABI_VERSION,
            "field_spec": spec,
        },
        "metadata": {
            "status": spec.status,
            "channel_id": spec.channel_id,
            "generator_id": spec.generator_id,
            "unit_policy": FIELD_BLENDER_UNIT_POLICY_V0,
            "blender_unit_to_meter": FIELD_BLENDER_UNIT_TO_METER_V0,
            "unit_policy_provisional": True,
        },
    }


def _owned_entry(entry, producer: str) -> bool:
    return (
        isinstance(entry, dict)
        and entry.get("tag") == FIELD_OBJECT_TAG
        and entry.get("producer") == producer
    )


def reconcile_field_manifest_v0(
    world,
    specs,
    *,
    disabled_field_ids=(),
    producer: str = FIELD_IMPLICIT_PRODUCER_V0,
    _write_lock_held: bool = False,
) -> FieldManifestReportV0:
    """完整暂存后，对本 producer/tag 的 entry 做可回滚对账。"""
    append = getattr(world, "append_implicit_object", None)
    implicit_objects = getattr(world, "implicit_objects", None)
    if not callable(append) or not isinstance(implicit_objects, list):
        raise TypeError("world 必须提供 append_implicit_object 和 implicit_objects 列表")

    staged = tuple(specs or ())
    active_ids = set()
    envelopes = []
    for spec in staged:
        if not isinstance(spec, FieldSpecV0):
            raise TypeError("Field manifest 只接受 FieldSpecV0")
        if not spec.enabled:
            raise ValueError("禁用 Field 不得注册为活动 implicit object")
        if spec.field_id in active_ids:
            raise ValueError(f"Field manifest 含重复 stable_id：{spec.field_id}")
        active_ids.add(spec.field_id)
        envelopes.append(field_implicit_entry_v0(spec, producer=producer))

    previous = list(implicit_objects)
    for entry in previous:
        if not isinstance(entry, dict) or entry.get("tag") != FIELD_OBJECT_TAG:
            continue
        stable_id = str(entry.get("stable_id") or "")
        previous_producer = str(entry.get("producer") or "")
        if stable_id in active_ids and previous_producer != producer:
            raise FieldImplicitOwnershipConflict(
                f"Field {stable_id} 已由 producer {previous_producer!r} 注册，"
                f"{producer!r} 不得静默覆盖"
            )
    previous_owned_ids = {
        str(entry.get("stable_id") or "")
        for entry in previous
        if _owned_entry(entry, producer)
    }
    writer_id = f"_{producer}:manifest"
    acquire = getattr(world, "acquire_write", None)
    release = getattr(world, "release_write", None)
    if callable(acquire) and not _write_lock_held:
        acquire(writer_id)
    try:
        appended = []
        for envelope in envelopes:
            entry = append(
                item=envelope,
                tag=envelope["tag"],
                producer=envelope["producer"],
                stable_id=envelope["stable_id"],
                signature=envelope["signature"],
                enabled=envelope["enabled"],
                schema=envelope["schema"],
            )
            if not isinstance(entry, dict):
                raise RuntimeError(
                    f"world 拒绝注册 Field implicit object：{envelope['stable_id']}"
                )
            appended.append(entry)

        # 先追加/更新全部有效 entry，再一次性裁掉禁用、删除或本轮无效的旧源。
        reconciled = [
            entry
            for entry in world.implicit_objects
            if not (
                _owned_entry(entry, producer)
                and str(entry.get("stable_id") or "") not in active_ids
            )
        ]
        world.implicit_objects[:] = reconciled
    except Exception:
        world.implicit_objects[:] = previous
        raise
    finally:
        if callable(release) and not _write_lock_held:
            release(writer_id)

    dirty_ids = tuple(sorted(
        str(entry.get("stable_id") or "")
        for entry in appended
        if bool(entry.get("dirty", False))
    ))
    return FieldManifestReportV0(
        registered_ids=tuple(sorted(active_ids)),
        removed_ids=tuple(sorted(previous_owned_ids - active_ids)),
        dirty_ids=dirty_ids,
        disabled_ids=tuple(sorted(set(str(value) for value in disabled_field_ids))),
    )


def collect_scope_field_specs(world, scope) -> FieldManifestReportV0:
    """收集 Field，并把纯快照与公共 native runtime 一次性提交到 world。"""
    objects = (
        getattr(scope, "objects", ())
        if bool(getattr(scope, "include_field", True))
        else ()
    )
    identity_diagnostics = repair_duplicate_field_ids_v0(objects)
    try:
        import bpy

        # RNA 参数可能刚由面板或动画系统改写；先提交 View Layer，再读取
        # evaluated Object，避免用上一轮的 enabled/transform 继续注册旧场。
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
    except (AttributeError, RuntimeError):
        depsgraph = None

    staged_sources = stage_field_sources_v0(objects, depsgraph=depsgraph)
    stage = FieldSourceStageV0(
        specs=staged_sources.specs,
        disabled_field_ids=staged_sources.disabled_field_ids,
        diagnostics=identity_diagnostics + staged_sources.diagnostics,
        source_count=staged_sources.source_count,
    )
    frame_context = getattr(world, "frame_context", None)
    snapshot = build_field_snapshot_v0(
        stage.specs,
        generation=int(getattr(world, "generation", 0) or 0),
        frame=int(getattr(frame_context, "frame", 0) or 0),
        sample_time_seconds=float(
            getattr(frame_context, "sample_time_seconds", 0.0) or 0.0
        ),
        diagnostics=stage.diagnostics,
    )
    set_cache = getattr(world, "set_runtime_cache", None)
    runtime_caches = getattr(world, "runtime_caches", None)
    if not callable(set_cache) or not isinstance(runtime_caches, dict):
        raise TypeError("world 必须提供 set_runtime_cache 和 runtime_caches 字典")

    previous_runtime = runtime_caches.get(FIELD_NATIVE_RUNTIME_CACHE_KEY_V1)
    reuse_runtime = (
        isinstance(previous_runtime, NativeFieldRuntimeV1)
        and previous_runtime.matches_values(snapshot)
    )
    staged_runtime = (
        None if reuse_runtime else NativeFieldRuntimeV1.create(snapshot)
    )

    writer_id = f"_{FIELD_IMPLICIT_PRODUCER_V0}:manifest"
    acquire = getattr(world, "acquire_write", None)
    release = getattr(world, "release_write", None)
    previous_objects = list(getattr(world, "implicit_objects", ()))
    previous_caches = dict(runtime_caches)
    if callable(acquire):
        acquire(writer_id)
    try:
        report = reconcile_field_manifest_v0(
            world,
            stage.specs,
            disabled_field_ids=stage.disabled_field_ids,
            _write_lock_held=True,
        )
        set_cache(FIELD_SNAPSHOT_CACHE_KEY_V0, snapshot)
        set_cache(FIELD_DIAGNOSTICS_CHANNEL, stage.diagnostics)
        if reuse_runtime:
            previous_runtime.update_frame(snapshot)
        else:
            set_cache(FIELD_NATIVE_RUNTIME_CACHE_KEY_V1, staged_runtime)
    except Exception:
        world.implicit_objects[:] = previous_objects
        runtime_caches.clear()
        runtime_caches.update(previous_caches)
        if staged_runtime is not None:
            staged_runtime.dispose("field_runtime_stage_rollback")
        raise
    finally:
        if callable(release):
            release(writer_id)
    if (
        not reuse_runtime
        and previous_runtime is not None
        and previous_runtime is not staged_runtime
    ):
        dispose = (
            getattr(previous_runtime, "omni_cache_dispose", None)
            or getattr(previous_runtime, "dispose", None)
        )
        if callable(dispose):
            dispose("field_runtime_replaced")
    return report


__all__ = [
    "FIELD_DUPLICATE_ID",
    "FIELD_IMPLICIT_PRODUCER_V0",
    "FIELD_IMPLICIT_SCHEMA_V1",
    "FIELD_INVALID_SOURCE",
    "FIELD_MISSING_ID",
    "FIELD_SNAPSHOT_CACHE_KEY_V0",
    "FIELD_UNIT_POLICY_PROVISIONAL",
    "FieldImplicitOwnershipConflict",
    "FieldManifestReportV0",
    "FieldSourceStageV0",
    "collect_scope_field_specs",
    "field_implicit_entry_v0",
    "reconcile_field_manifest_v0",
    "repair_duplicate_field_ids_v0",
    "stage_field_sources_v0",
]
