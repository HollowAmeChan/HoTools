"""FBSF 持久配置与形态键工具变基页面。"""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Context, Operator, PropertyGroup, UIList, UILayout

from Utils import shapekey_utils

try:
    from . import rebase_core as _core
except ImportError:  # 兼容旧工具直接导入脚本
    import rebase_core as _core


ShapeKeyRebaseError = _core.ShapeKeyRebaseError
FBSF_FUNCTION_ITEMS = _core.FBSF_FUNCTION_ITEMS
FBSF_FUNCTION_TAGS = _core.FBSF_FUNCTION_TAGS

_fbsf_tag_channels = _core._fbsf_tag_channels
_fbsf_auto_preset = _core._fbsf_auto_preset
_fbsf_classification_context = _core._fbsf_classification_context
_fbsf_resolve_target_side_tags = _core._fbsf_resolve_target_side_tags
_fbsf_resolve_keyword_eye_tags = _core._fbsf_resolve_keyword_eye_tags
_rebase_shape_keys_fbsf = _core._rebase_shape_keys_fbsf


REBASE_SCHEMA_VERSION = 1


class PG_ShapekeyTools_RebaseItem(PropertyGroup):
    """保存在网格 Key 数据块中的一行 FBSF 配置。"""

    shape_key_name: StringProperty(name="形态键")  # type: ignore
    key_index: IntProperty(name="索引", default=-1, options={'HIDDEN'})  # type: ignore
    selected: BoolProperty(
        name="选中",
        description="加入批量权能编辑范围",
        default=False,
    )  # type: ignore
    merge: BoolProperty(
        name="合并",
        description="烘焙进 Basis，并在成功后删除该来源键",
        default=False,
    )  # type: ignore
    mergeable: BoolProperty(
        name="可合并",
        description="只有直接相对 Basis 的键可以作为合并来源",
        default=True,
        options={'HIDDEN'},
    )  # type: ignore
    function_tag: EnumProperty(
        name="权能",
        description="该键参与 FBSF 的眼睛、嘴部或普通变基类别",
        items=FBSF_FUNCTION_ITEMS,
        default='OTHERS',
    )  # type: ignore
    reference_tag: EnumProperty(
        name="参考权能",
        description="用于构建 FBSF 参考定义的最终类别",
        items=FBSF_FUNCTION_ITEMS,
        default='OTHERS',
        options={'HIDDEN'},
    )  # type: ignore
    auto_function_tag: StringProperty(
        name="自动权能",
        default='OTHERS',
        options={'HIDDEN'},
    )  # type: ignore
    auto_reference_tag: StringProperty(
        name="自动参考权能",
        default='OTHERS',
        options={'HIDDEN'},
    )  # type: ignore
    initialized: BoolProperty(
        name="已初始化",
        description="自动预处理已经完成；刷新不会覆盖该行",
        default=False,
        options={'HIDDEN'},
    )  # type: ignore

    weight: FloatProperty(
        name="变基权重",
        description="合并来源烘焙进 Basis 时使用的权重",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )  # type: ignore


def _shape_key_data(obj):
    if obj is None or getattr(obj, "type", None) != 'MESH':
        return None
    return getattr(getattr(obj, "data", None), "shape_keys", None)


# region 属性更新回调

def _activate_selected_rebase_item(shape_keys, context):
    obj = getattr(context, "object", None)
    if _shape_key_data(obj) != shape_keys:
        return
    item_index = shape_keys.ho_rebase_item_index
    if not 0 <= item_index < len(shape_keys.ho_rebase_items):
        return
    item = shape_keys.ho_rebase_items[item_index]
    key_index = shape_keys.key_blocks.find(item.shape_key_name)
    if key_index >= 0:
        obj.active_shape_key_index = key_index


# endregion


# region 属性注册

def reg_props():
    bpy.types.Key.ho_rebase_items = CollectionProperty(
        type=PG_ShapekeyTools_RebaseItem)
    bpy.types.Key.ho_rebase_item_index = IntProperty(
        default=0,
        min=0,
        update=_activate_selected_rebase_item,
    )
    bpy.types.Key.ho_rebase_schema = IntProperty(
        default=REBASE_SCHEMA_VERSION, options={'HIDDEN'})
    bpy.types.Key.ho_rebase_left_is_positive = IntProperty(
        default=1, min=-1, max=1, options={'HIDDEN'})
    bpy.types.Key.ho_rebase_batch_function_tag = EnumProperty(
        name="批量权能",
        description="准备应用到选中形态键的权能类型",
        items=FBSF_FUNCTION_ITEMS,
        default='OTHERS',
    )
    bpy.types.Key.ho_rebase_correction_strength = FloatProperty(
        name="反向修正强度", default=1.0, min=0.0, max=1.0,
        subtype='FACTOR')
    bpy.types.Key.ho_rebase_side_smooth_width = FloatProperty(
        name="左右过渡宽度", default=0.0, min=0.0, soft_max=0.1,
        precision=4, unit='LENGTH')


def ureg_props():
    del bpy.types.Key.ho_rebase_items
    del bpy.types.Key.ho_rebase_item_index
    del bpy.types.Key.ho_rebase_schema
    del bpy.types.Key.ho_rebase_left_is_positive
    del bpy.types.Key.ho_rebase_batch_function_tag
    del bpy.types.Key.ho_rebase_correction_strength
    del bpy.types.Key.ho_rebase_side_smooth_width


# endregion


def _item_snapshot(item):
    return {
        "shape_key_name": item.shape_key_name,
        "key_index": item.key_index,
        "selected": item.selected,
        "merge": item.merge,
        "mergeable": item.mergeable,
        "function_tag": item.function_tag,
        "reference_tag": item.reference_tag,
        "auto_function_tag": item.auto_function_tag,
        "auto_reference_tag": item.auto_reference_tag,
        "initialized": item.initialized,
        "weight": item.weight,
    }


def _item_by_name(shape_keys):
    return {
        item.shape_key_name: _item_snapshot(item)
        for item in shape_keys.ho_rebase_items
        if item.shape_key_name
    }


def _new_item(shape_keys, key, index, context):
    item = shape_keys.ho_rebase_items.add()
    item.key_index = index
    item.merge = key.relative_key == shape_keys.reference_key and key.value > 1e-6
    item.weight = min(1.0, max(0.0, float(key.value))) if item.merge else 1.0
    item.mergeable = key.relative_key == shape_keys.reference_key
    preset = _fbsf_auto_preset(key.name, context=context)
    item.function_tag = preset.function_tag
    item.reference_tag = preset.reference_tag
    item.auto_function_tag = preset.function_tag
    item.auto_reference_tag = preset.reference_tag
    item.initialized = False
    item.shape_key_name = key.name
    return item


def _effective_reference_tag(item):
    return (
        item.reference_tag
        if item.function_tag == item.auto_function_tag
        else item.function_tag
    )


def _infer_uninitialized(obj, *, report=None):
    """只推断上次刷新后新增、尚未初始化的列表行。"""
    shape_keys = _shape_key_data(obj)
    if shape_keys is None:
        return 0
    basis = shape_keys.reference_key
    if basis is None:
        return 0
    pending = [item for item in shape_keys.ho_rebase_items if not item.initialized]
    if not pending:
        return 0

    shape_names = tuple(
        key.name for key in shape_keys.key_blocks if key != basis)
    classification_context = _fbsf_classification_context(shape_names)
    basis_positions = shapekey_utils.read_shape_key_positions(basis)
    keys_by_name = {
        key.name: key for key in shape_keys.key_blocks if key != basis
    }
    delta_cache = {}

    def target_delta(shape_name):
        delta = delta_cache.get(shape_name)
        if delta is None:
            key = keys_by_name[shape_name]
            relative = shapekey_utils.read_shape_key_positions(key.relative_key)
            delta = shapekey_utils.read_shape_key_positions(key) - relative
            delta_cache[shape_name] = delta
        return delta

    source_orientation = []
    for item in shape_keys.ho_rebase_items:
        if not item.merge or not item.mergeable:
            continue
        preset = _fbsf_auto_preset(
            item.shape_key_name, context=classification_context)
        channels = _fbsf_tag_channels(item.function_tag)
        if (
                'MMD' not in preset.standards
                and len(channels & {'LEFT_EYE', 'RIGHT_EYE'}) == 1):
            source_orientation.append(
                (item.function_tag, target_delta(item.shape_key_name)))

    target_tags = {
        item.shape_key_name: (
            item.function_tag,
            _effective_reference_tag(item),
        )
        for item in shape_keys.ho_rebase_items
        if item.shape_key_name in keys_by_name
    }
    left_is_positive, resolved = _fbsf_resolve_target_side_tags(
        target_tags,
        tuple(source_orientation),
        basis_positions,
        classification_context,
        target_delta,
        resolve_mmd=True,
    )
    resolved = _fbsf_resolve_keyword_eye_tags(
        resolved,
        basis_positions,
        left_is_positive,
        classification_context,
        target_delta,
    )
    for item in pending:
        resolved_tag = resolved.get(
            item.shape_key_name,
            (item.function_tag, item.reference_tag),
        )
        item.function_tag, item.reference_tag = resolved_tag
        item.auto_function_tag, item.auto_reference_tag = resolved_tag
        item.initialized = True
    shape_keys.ho_rebase_left_is_positive = 1 if left_is_positive else -1
    if report is not None:
        report(len(pending))
    return len(pending)


def sync_rebase_items(obj, *, infer=True):
    """同步持久列表；同名旧行原样保留，只初始化新增形态键。"""
    shape_keys = _shape_key_data(obj)
    if shape_keys is None or shape_keys.reference_key is None:
        return 0
    previous = _item_by_name(shape_keys)
    shape_keys.ho_rebase_items.clear()
    shape_names = tuple(
        key.name for key in shape_keys.key_blocks
        if key != shape_keys.reference_key
    )
    context = _fbsf_classification_context(shape_names)
    for index, key in enumerate(shape_keys.key_blocks):
        if key == shape_keys.reference_key:
            continue
        old = previous.get(key.name)
        if old is None:
            item = _new_item(shape_keys, key, index, context)
        else:
            # 重建列表顺序时复制持久值，不改变用户已经调整的配置。
            item = shape_keys.ho_rebase_items.add()
            for prop, value in old.items():
                setattr(item, prop, value)
            item.shape_key_name = key.name
            item.key_index = index
            item.mergeable = key.relative_key == shape_keys.reference_key
            if not item.mergeable:
                item.merge = False
        item.key_index = index
    if infer:
        _infer_uninitialized(obj)
    shape_keys.ho_rebase_schema = REBASE_SCHEMA_VERSION
    shape_keys.ho_rebase_item_index = min(
        shape_keys.ho_rebase_item_index,
        max(0, len(shape_keys.ho_rebase_items) - 1),
    )
    return len(shape_keys.ho_rebase_items)


def _current_item_names(shape_keys):
    return {
        key.name for key in shape_keys.key_blocks
        if key != shape_keys.reference_key
    }


def _active_rebase_item(obj):
    shape_keys = _shape_key_data(obj)
    active_key = getattr(obj, "active_shape_key", None)
    if (
            shape_keys is None
            or active_key is None
            or active_key == shape_keys.reference_key):
        return None
    return next(
        (
            item for item in shape_keys.ho_rebase_items
            if item.shape_key_name == active_key.name
        ),
        None,
    )


def _draw_rebase_item_controls(layout, item):
    row = layout.row(align=True)
    selected = row.row(align=True)
    selected.ui_units_x = 2.0
    selected.prop(item, "selected", text="")
    name = row.row(align=True)
    name.ui_units_x = 9.0
    name.label(text=item.shape_key_name, icon='SHAPEKEY_DATA')
    function = row.row(align=True)
    function.ui_units_x = 8.0
    function.prop(item, "function_tag", text="")
    weight = row.row(align=True)
    weight.ui_units_x = 4.0
    weight.enabled = item.merge and item.mergeable
    weight.prop(item, "weight", text="")
    merge = row.row(align=True)
    merge.ui_units_x = 2.0
    merge.enabled = item.mergeable
    merge.prop(item, "merge", text="")


def _draw_rebase_header(layout):
    row = layout.row(align=True)
    selected = row.row(align=True)
    selected.ui_units_x = 2.0
    selected.label(text="选中")
    name = row.row(align=True)
    name.ui_units_x = 9.0
    name.label(text="形态键")
    function = row.row(align=True)
    function.ui_units_x = 8.0
    function.label(text="权能")
    weight = row.row(align=True)
    weight.ui_units_x = 4.0
    weight.label(text="权重")
    merge = row.row(align=True)
    merge.ui_units_x = 2.0
    merge.label(text="合并")


class HO_UL_ShapekeyTools_RebaseItems(UIList):
    bl_idname = "HO_UL_ShapekeyTools_RebaseItems"

    def draw_item(
            self, context, layout, data, item, icon, active_data,
            active_property, index, flt_flag):
        _draw_rebase_item_controls(layout, item)


class OP_ShapekeyTools_RebaseRefresh(Operator):
    bl_idname = "ho.rebase_fbsf_refresh"
    bl_label = "刷新"
    bl_description = "同步当前形态键并只初始化新增配置"

    @classmethod
    def poll(cls, context):
        return _shape_key_data(context.object) is not None

    def execute(self, context):
        try:
            count = sync_rebase_items(context.object, infer=True)
        except (ShapeKeyRebaseError, KeyError, ValueError) as exc:
            self.report({'ERROR'}, f"变基列表刷新失败：{exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"已同步 {count} 个形态键；已有手调标签保持不变")
        return {'FINISHED'}


class OP_ShapekeyTools_RebaseInferUnknown(Operator):
    bl_idname = "ho.rebase_fbsf_infer_unknown"
    bl_label = "推断未知"
    bl_description = "只对尚未初始化的行进行保守名称和几何推断"

    @classmethod
    def poll(cls, context):
        shape_keys = _shape_key_data(context.object)
        return shape_keys is not None and len(shape_keys.ho_rebase_items) > 0

    def execute(self, context):
        try:
            count = _infer_uninitialized(context.object)
        except (ShapeKeyRebaseError, KeyError, ValueError) as exc:
            self.report({'ERROR'}, f"形态键推断失败：{exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"已推断 {count} 个未知形态键；已有标签未被覆盖")
        return {'FINISHED'}


class OP_ShapekeyTools_RebaseSelectAll(Operator):
    bl_idname = "ho.rebase_fbsf_select_all"
    bl_label = "全选"
    bl_description = "选中全部形态键配置行"

    @classmethod
    def poll(cls, context):
        shape_keys = _shape_key_data(context.object)
        return shape_keys is not None and len(shape_keys.ho_rebase_items) > 0

    def execute(self, context):
        shape_keys = context.object.data.shape_keys
        for item in shape_keys.ho_rebase_items:
            item.selected = True
        return {'FINISHED'}


class OP_ShapekeyTools_RebaseDeselectAll(Operator):
    bl_idname = "ho.rebase_fbsf_deselect_all"
    bl_label = "全弃"
    bl_description = "取消选中全部形态键配置行"

    @classmethod
    def poll(cls, context):
        shape_keys = _shape_key_data(context.object)
        return shape_keys is not None and len(shape_keys.ho_rebase_items) > 0

    def execute(self, context):
        shape_keys = context.object.data.shape_keys
        for item in shape_keys.ho_rebase_items:
            item.selected = False
        return {'FINISHED'}


class OP_ShapekeyTools_RebaseApplyBatchFunction(Operator):
    bl_idname = "ho.rebase_fbsf_apply_batch_function"
    bl_label = "应用权能"
    bl_description = "将指定权能应用到全部选中行"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        shape_keys = _shape_key_data(context.object)
        return shape_keys is not None and len(shape_keys.ho_rebase_items) > 0

    def execute(self, context):
        shape_keys = context.object.data.shape_keys
        function_tag = shape_keys.ho_rebase_batch_function_tag
        selected_items = [
            item for item in shape_keys.ho_rebase_items if item.selected
        ]
        if not selected_items:
            self.report({'WARNING'}, "没有选中的形态键配置")
            return {'CANCELLED'}
        for item in selected_items:
            item.function_tag = function_tag
        self.report({'INFO'}, f"已批量设置 {len(selected_items)} 个形态键的权能")
        return {'FINISHED'}


class OP_ShapekeyTools_RebaseApply(Operator):
    bl_idname = "ho.rebase_fbsf_apply"
    bl_label = "应用 FBSF"
    bl_description = "按当前持久列表状态执行 FBSF，不重新自动分类"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        shape_keys = _shape_key_data(context.object)
        return shape_keys is not None and len(shape_keys.key_blocks) >= 2

    def execute(self, context):
        obj = context.object
        shape_keys = _shape_key_data(obj)
        if shape_keys is None:
            self.report({'ERROR'}, "当前对象没有形态键")
            return {'CANCELLED'}
        current_names = _current_item_names(shape_keys)
        listed_names = {
            item.shape_key_name for item in shape_keys.ho_rebase_items
        }
        if current_names != listed_names:
            self.report({'WARNING'}, "形态键已变化，请先刷新变基列表")
            return {'CANCELLED'}
        if any(not item.initialized for item in shape_keys.ho_rebase_items):
            self.report({'WARNING'}, "仍有未初始化的形态键，请先推断未知")
            return {'CANCELLED'}

        source_specs = tuple(
            (item.shape_key_name, float(item.weight), item.function_tag)
            for item in shape_keys.ho_rebase_items
            if item.merge and item.mergeable
        )
        target_specs = tuple(
            (
                item.shape_key_name,
                item.function_tag,
                _effective_reference_tag(item),
            )
            for item in shape_keys.ho_rebase_items
            if not item.merge
        )
        if not source_specs:
            self.report({'WARNING'}, "请至少勾选一个可合并的来源键")
            return {'CANCELLED'}
        orientation_override = {
            -1: False,
            1: True,
        }.get(shape_keys.ho_rebase_left_is_positive)
        try:
            if obj.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            result = _rebase_shape_keys_fbsf(
                obj,
                source_specs,
                float(shape_keys.ho_rebase_correction_strength),
                float(shape_keys.ho_rebase_side_smooth_width),
                target_specs,
                orientation_override=orientation_override,
            )
        except (ShapeKeyRebaseError, KeyError, ValueError) as exc:
            self.report({'ERROR'}, f"FBSF 变基失败：{exc}")
            return {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, f"FBSF 变基失败：{exc}")
            return {'CANCELLED'}
        sync_rebase_items(obj, infer=False)
        self.report({'INFO'}, f"已应用 FBSF，重写 {result[1]} 个形态键")
        return {'FINISHED'}


def drawRebasePanel(layout: UILayout, context: Context):
    obj = context.object
    shape_keys = _shape_key_data(obj)
    if shape_keys is None or len(shape_keys.key_blocks) < 2:
        layout.label(text="当前对象没有可变基的形态键", icon='INFO')
        return
    toolbar = layout.row(align=True)
    toolbar.operator(OP_ShapekeyTools_RebaseRefresh.bl_idname, icon='FILE_REFRESH', text="")
    toolbar.operator(OP_ShapekeyTools_RebaseInferUnknown.bl_idname, icon='VIEWZOOM', text="")
    apply = toolbar.row(align=True)
    apply.alert = True
    apply.operator(OP_ShapekeyTools_RebaseApply.bl_idname, icon='CHECKMARK', text="应用 FBSF")
    apply.alert = False

    active_box = layout.box()
    active_row = active_box.row(align=True)
    active_label = active_row.row(align=True)
    active_label.ui_units_x = 5.0
    active_label.label(text="活动键", icon='RESTRICT_SELECT_OFF')
    active_item = _active_rebase_item(obj)
    if active_item is not None:
        _draw_rebase_item_controls(active_row, active_item)
    else:
        active_key = obj.active_shape_key
        active_row.label(
            text=active_key.name if active_key is not None else "无",
            icon='SHAPEKEY_DATA',
        )

    box = layout.box()
    batch = box.row(align=True)
    batch.label(text="批量")
    batch.operator(
        OP_ShapekeyTools_RebaseSelectAll.bl_idname,
        icon='CHECKBOX_HLT',
        text="",
    )
    batch.operator(
        OP_ShapekeyTools_RebaseDeselectAll.bl_idname,
        icon='CHECKBOX_DEHLT',
        text="",
    )
    batch.prop(shape_keys, "ho_rebase_batch_function_tag", text="")
    batch.operator(
        OP_ShapekeyTools_RebaseApplyBatchFunction.bl_idname,
        icon='CHECKMARK',
        text="应用",
    )
    box.separator()
    _draw_rebase_header(box)
    box.template_list(
        HO_UL_ShapekeyTools_RebaseItems.bl_idname,
        "",
        shape_keys,
        "ho_rebase_items",
        shape_keys,
        "ho_rebase_item_index",
        rows=16,
    )
    settings = layout.column(align=True)
    settings.prop(shape_keys, "ho_rebase_correction_strength")
    settings.prop(shape_keys, "ho_rebase_side_smooth_width")


cls = [
    PG_ShapekeyTools_RebaseItem,
    HO_UL_ShapekeyTools_RebaseItems,
    OP_ShapekeyTools_RebaseRefresh,
    OP_ShapekeyTools_RebaseInferUnknown,
    OP_ShapekeyTools_RebaseSelectAll,
    OP_ShapekeyTools_RebaseDeselectAll,
    OP_ShapekeyTools_RebaseApplyBatchFunction,
    OP_ShapekeyTools_RebaseApply,
]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    ureg_props()
    for i in reversed(cls):
        bpy.utils.unregister_class(i)


__all__ = (
    "PG_ShapekeyTools_RebaseItem",
    "HO_UL_ShapekeyTools_RebaseItems",
    "OP_ShapekeyTools_RebaseRefresh",
    "OP_ShapekeyTools_RebaseInferUnknown",
    "OP_ShapekeyTools_RebaseSelectAll",
    "OP_ShapekeyTools_RebaseDeselectAll",
    "OP_ShapekeyTools_RebaseApplyBatchFunction",
    "OP_ShapekeyTools_RebaseApply",
    "sync_rebase_items",
    "drawRebasePanel",
    "register",
    "unregister",
)
