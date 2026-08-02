"""Field 的 Blender RNA 与纯规格解析边界。

本模块可以读取 Blender 对象，但输出的 ``FieldSpecV0`` 不保留任何
``bpy`` 引用。持久身份只来自 ``field_id``，对象名称只用于错误提示。
"""

from __future__ import annotations

import re
import uuid

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from .names import FIELD_STATUS_ACTIVE
from .schema import FIELD_RNA_FIELDS
from .specs import FieldScopeV0, FieldSpecV0, VolumeSpecV0, WindPayloadV0


# Scene 单位到米的公共入口尚未冻结。V0 明确采用 1:1，避免同一 .blend
# 因隐式读取不同 Scene 的 unit_settings 而得到不同签名。
FIELD_BLENDER_UNIT_POLICY_V0 = "blender_unit_equals_one_meter_v0_provisional"
FIELD_BLENDER_UNIT_TO_METER_V0 = 1.0


class DuplicateFieldIdError(ValueError):
    """多个 Blender 源声明同一个持久 Field ID。"""

    def __init__(self, field_id: str, source_labels) -> None:
        labels = tuple(str(value) for value in source_labels)
        super().__init__(
            f"Field ID {field_id} 被多个对象重复使用：{', '.join(labels)}"
        )
        self.field_id = str(field_id)
        self.source_labels = labels


def _field_value_update(_owner=None, _context=None) -> None:
    try:
        from .visualization import mark_field_visualization_dirty

        mark_field_visualization_dirty()
    except Exception:
        pass


def _field_enabled_update(owner, context) -> None:
    if bool(getattr(owner, "enabled", False)) and not str(
        getattr(owner, "field_id", "") or ""
    ).strip():
        owner.field_id = str(uuid.uuid4())
    _field_value_update(owner, context)


_PROPERTY_FACTORIES = {
    "bool": BoolProperty,
    "enum": EnumProperty,
    "float": FloatProperty,
    "int": IntProperty,
    "string": StringProperty,
}

_UPDATE_CALLBACKS = {
    "enabled": _field_enabled_update,
    "visualization": _field_value_update,
}


def _field_property(field: dict):
    property_kind = str(field.get("property") or "")
    factory = _PROPERTY_FACTORIES.get(property_kind)
    if factory is None:
        raise ValueError(f"不支持的 Field RNA 属性类型：{property_kind}")
    kwargs = dict(field.get("kwargs") or {})
    update_kind = str(field.get("update") or "visualization")
    update = _UPDATE_CALLBACKS.get(update_kind)
    if update is None:
        raise ValueError(f"不支持的 Field RNA 更新策略：{update_kind}")
    kwargs["update"] = update
    return factory(**kwargs)


class PG_Hotools_Field(PropertyGroup):
    """Empty 上可保存、撤销并动画化的公共 Field 创作属性。"""


PG_Hotools_Field.__annotations__ = {
    str(field["name"]): _field_property(field)
    for field in FIELD_RNA_FIELDS
}


FIELD_BLENDER_PROPERTIES = {
    "classes": (PG_Hotools_Field,),
    "bindings": ({
        "owner": bpy.types.Object,
        "name": "hotools_field",
        "property": "pointer",
        "type": PG_Hotools_Field,
    },),
}


def _source_label(obj) -> str:
    try:
        return str(obj.name_full)
    except (AttributeError, ReferenceError):
        return "<无效对象>"


def _original_object(obj):
    try:
        original = obj.original
    except (AttributeError, ReferenceError):
        original = None
    return original if original is not None else obj


def _field_properties(obj):
    try:
        return obj.hotools_field
    except (AttributeError, ReferenceError):
        raise ValueError(f"对象 {_source_label(obj)} 没有注册 Object.hotools_field") from None


def canonical_field_id_v0(value) -> str:
    """校验并返回小写、带连字符的 UUID。"""
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError("Field 缺少持久 field_id；请使用创建或修复操作生成 UUID")
    try:
        parsed = uuid.UUID(text)
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"field_id 不是有效 UUID：{value!r}") from None
    canonical = str(parsed)
    if text != canonical:
        raise ValueError(f"field_id 必须使用规范 UUID 格式：{canonical}")
    return canonical


def ensure_field_id_v0(obj, *, force_new: bool = False) -> str:
    """为原始 Blender 对象创建持久 UUID；resolver 本身不会隐式修复身份。"""
    authoring_obj = _original_object(obj)
    props = _field_properties(authoring_obj)
    current = str(getattr(props, "field_id", "") or "").strip()
    if current and not force_new:
        return canonical_field_id_v0(current)
    field_id = str(uuid.uuid4())
    props.field_id = field_id
    return field_id


_LIST_SEPARATOR = re.compile(r"[,;\n\r]+")


def _string_ids(value) -> tuple[str, ...]:
    values = (
        str(item).strip()
        for item in _LIST_SEPARATOR.split(str(value or ""))
    )
    return tuple(item for item in values if item)


def _collision_groups(value) -> tuple[int, ...]:
    groups = []
    for item in _string_ids(value):
        try:
            groups.append(int(item))
        except ValueError:
            raise ValueError(f"碰撞组编号必须是整数：{item!r}") from None
    return tuple(groups)


def _matrix4_rows(matrix) -> tuple[tuple[float, float, float, float], ...]:
    try:
        return tuple(
            tuple(float(matrix[row][column]) for column in range(4))
            for row in range(4)
        )
    except (AttributeError, IndexError, ReferenceError, TypeError, ValueError):
        raise ValueError("Field Empty 的 matrix_world 不是有效 4x4 矩阵") from None


def evaluated_field_object_v0(obj, depsgraph=None):
    """返回用于读取动画值和 matrix_world 的求值对象。"""
    try:
        if bool(getattr(obj, "is_evaluated", False)):
            return obj
    except (AttributeError, ReferenceError):
        pass
    if depsgraph is not None:
        try:
            return obj.evaluated_get(depsgraph)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    return obj


def resolve_field_spec_v0(obj, *, evaluated_object=None, depsgraph=None) -> FieldSpecV0:
    """把一个原始或已求值 Empty 解析为不含 Blender 引用的纯规格。"""
    authoring_obj = _original_object(obj)
    evaluated_obj = evaluated_object or evaluated_field_object_v0(obj, depsgraph)
    try:
        object_type = str(evaluated_obj.type)
    except (AttributeError, ReferenceError):
        raise ValueError("Field 源必须是有效的 Blender Empty") from None
    if object_type != "EMPTY":
        raise ValueError(f"Field 源 {_source_label(authoring_obj)} 必须是 Empty")

    # 自定义 PointerProperty 的 evaluated 副本可能在面板改值后短暂滞后；
    # 持久/动画 RNA 由 original datablock 拥有，只有约束后的矩阵读 evaluated。
    identity_props = _field_properties(authoring_obj)
    value_props = identity_props
    field_id = canonical_field_id_v0(getattr(identity_props, "field_id", ""))

    scope = FieldScopeV0(
        solver_ids=_string_ids(value_props.scope_solver_ids),
        collection_ids=_string_ids(value_props.scope_collection_ids),
        include_ids=_string_ids(value_props.scope_include_ids),
        exclude_ids=_string_ids(value_props.scope_exclude_ids),
        collision_groups=_collision_groups(value_props.scope_collision_groups),
    )
    volume = VolumeSpecV0(
        shape=str(value_props.shape),
        world_transform=_matrix4_rows(evaluated_obj.matrix_world),
    )
    wind = WindPayloadV0(
        speed_mps=float(value_props.speed_mps),
        turbulence=float(value_props.turbulence),
        spatial_scale_m=float(value_props.spatial_scale_m),
        temporal_frequency_hz=float(value_props.temporal_frequency_hz),
        octaves=int(value_props.octaves),
        lacunarity=float(value_props.lacunarity),
        gain=float(value_props.gain),
        seed_u32=int(value_props.seed_u32),
    )
    return FieldSpecV0(
        field_id=field_id,
        source_id=f"blender.field:{field_id}",
        enabled=bool(value_props.enabled),
        status=FIELD_STATUS_ACTIVE,
        volume=volume,
        wind=wind,
        scope=scope,
        blend_weight=float(value_props.blend_weight),
        priority=int(value_props.priority),
        field_type=str(value_props.field_type),
    )


def resolve_field_specs_v0(objects, *, depsgraph=None) -> tuple[FieldSpecV0, ...]:
    """批量解析并在返回任何规格前拒绝重复 UUID。"""
    staged = []
    identities: dict[str, list[str]] = {}
    for obj in tuple(objects or ()):
        spec = resolve_field_spec_v0(obj, depsgraph=depsgraph)
        staged.append(spec)
        identities.setdefault(spec.field_id, []).append(_source_label(_original_object(obj)))
    for field_id, labels in identities.items():
        if len(labels) > 1:
            raise DuplicateFieldIdError(field_id, labels)
    return tuple(sorted(staged, key=lambda item: (item.priority, item.field_id)))


__all__ = [
    "DuplicateFieldIdError",
    "FIELD_BLENDER_PROPERTIES",
    "FIELD_BLENDER_UNIT_POLICY_V0",
    "FIELD_BLENDER_UNIT_TO_METER_V0",
    "FIELD_RNA_FIELDS",
    "PG_Hotools_Field",
    "canonical_field_id_v0",
    "ensure_field_id_v0",
    "evaluated_field_object_v0",
    "resolve_field_spec_v0",
    "resolve_field_specs_v0",
]
