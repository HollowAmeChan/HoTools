from ..OmniNodeSocketMapping import _OmniModifierType, _OmniModifier
from ..FunctionNodeCore import omni
from . import _Color

import bpy


def _require_modifier(modifier) -> bpy.types.Modifier:
    if modifier is None or not isinstance(modifier, bpy.types.Modifier):
        raise ValueError("修改器输入未连接或无效")
    return modifier


def _modifier_owner(modifier: bpy.types.Modifier) -> bpy.types.Object:
    owner = getattr(modifier, "id_data", None)
    if owner is None or not isinstance(owner, bpy.types.Object):
        raise ValueError("修改器没有有效的所属物体")
    return owner


def _ensure_modifier_name(modifier_type: str, modifier_name: str) -> str:
    modifier_name = str(modifier_name or "").strip()
    modifier_type = str(modifier_type or "").strip()
    if modifier_name:
        return modifier_name
    if modifier_type:
        return modifier_type.title().replace("_", " ")
    raise ValueError("修改器类型为空")


def _get_modifier_by_name(obj: bpy.types.Object, modifier_name: str) -> bpy.types.Modifier:
    modifier_name = str(modifier_name or "").strip()
    if obj is None:
        raise ValueError("物体为空")
    if not modifier_name:
        raise ValueError("修改器名称为空")

    modifier = obj.modifiers.get(modifier_name)
    if modifier is None:
        raise ValueError(f"物体 '{obj.name}' 上找不到修改器 '{modifier_name}'")
    return modifier


def _get_modifier_by_index(obj: bpy.types.Object, modifier_index: int) -> bpy.types.Modifier:
    if obj is None:
        raise ValueError("物体为空")
    if len(obj.modifiers) == 0:
        raise ValueError(f"物体 '{obj.name}' 没有任何修改器")

    modifier_index = int(modifier_index)
    if modifier_index < 0 or modifier_index >= len(obj.modifiers):
        raise ValueError(
            f"修改器索引超出范围: {modifier_index}，有效范围是 0 到 {len(obj.modifiers) - 1}"
        )
    return obj.modifiers[modifier_index]


def _get_modifier_by_type(
    obj: bpy.types.Object,
    modifier_type: str,
    match_index: int = 0,
) -> bpy.types.Modifier:
    if obj is None:
        raise ValueError("物体为空")

    modifier_type = str(modifier_type or "").strip()
    if not modifier_type:
        raise ValueError("修改器类型为空")

    match_index = int(match_index)
    if match_index < 0:
        raise ValueError("匹配索引不能小于 0")

    matches = [modifier for modifier in obj.modifiers if modifier.type == modifier_type]
    if not matches:
        raise ValueError(f"物体 '{obj.name}' 上找不到类型为 '{modifier_type}' 的修改器")
    if match_index >= len(matches):
        raise ValueError(
            f"类型 '{modifier_type}' 的匹配索引超出范围: {match_index}，有效范围是 0 到 {len(matches) - 1}"
        )
    return matches[match_index]


def _refetch_modifier(obj: bpy.types.Object, modifier_name: str) -> bpy.types.Modifier:
    modifier = obj.modifiers.get(modifier_name)
    if modifier is None:
        raise ValueError(f"物体 '{obj.name}' 上找不到修改器 '{modifier_name}'")
    return modifier


def _apply_modifier_operator(obj: bpy.types.Object, modifier: bpy.types.Modifier) -> None:
    view_layer = bpy.context.view_layer
    previous_active = view_layer.objects.active
    previous_selected = list(bpy.context.selected_objects)

    try:
        for selected_obj in previous_selected:
            try:
                selected_obj.select_set(False)
            except Exception:
                pass

        obj.select_set(True)
        view_layer.objects.active = obj

        with bpy.context.temp_override(
            object=obj,
            active_object=obj,
            selected_objects=[obj],
            selected_editable_objects=[obj],
            modifier=modifier,
        ):
            bpy.ops.object.modifier_apply(modifier=modifier.name)
    finally:
        try:
            obj.select_set(False)
        except Exception:
            pass

        for selected_obj in previous_selected:
            try:
                selected_obj.select_set(True)
            except Exception:
                pass

        try:
            view_layer.objects.active = previous_active
        except Exception:
            pass


@omni(
    enable=True,
    bl_label="添加修改器",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "修改器类型", "修改器名称"],
    _OUTPUT_NAME=["物体", "修改器名称", "修改器"],
    bl_icon="MODIFIER",
    omni_description="""
    给目标物体添加一个修改器。
    如果修改器名称为空，会根据修改器类型自动生成默认名称。
    """,
)
def objectAddModifier(
    obj: bpy.types.Object,
    modifier_type: _OmniModifierType,
    modifier_name: str = "",
) -> tuple[bpy.types.Object, str, bpy.types.Modifier]:
    modifier_name = _ensure_modifier_name(modifier_type, modifier_name)
    modifier = obj.modifiers.new(name=modifier_name, type=modifier_type)
    return obj, modifier.name, modifier


@omni(
    enable=True,
    bl_label="按名称获取修改器",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "修改器名称"],
    _OUTPUT_NAME=["修改器"],
    bl_icon="MODIFIER",
)
def objectGetModifierByName(
    obj: bpy.types.Object,
    modifier_name: str,
) -> bpy.types.Modifier:
    return _get_modifier_by_name(obj, modifier_name)


@omni(
    enable=True,
    bl_label="按索引获取修改器",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "修改器索引"],
    _OUTPUT_NAME=["修改器"],
    bl_icon="MODIFIER",
)
def objectGetModifierByIndex(
    obj: bpy.types.Object,
    modifier_index: int,
) -> bpy.types.Modifier:
    return _get_modifier_by_index(obj, modifier_index)


@omni(
    enable=True,
    bl_label="按类型获取修改器",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "修改器类型", "匹配索引"],
    _OUTPUT_NAME=["修改器"],
    bl_icon="MODIFIER",
    omni_description="""
    按修改器类型获取目标物体上的修改器。
    如果同类型有多个修改器，可以通过匹配索引指定第几个。
    """,
)
def objectGetModifierByType(
    obj: bpy.types.Object,
    modifier_type: _OmniModifierType,
    match_index: int = 0,
) -> bpy.types.Modifier:
    return _get_modifier_by_type(obj, modifier_type, match_index)


@omni(
    enable=True,
    bl_label="获取修改器名称",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["修改器"],
    _OUTPUT_NAME=["修改器名称"],
    bl_icon="MODIFIER",
)
def modifierGetName(
    modifier: _OmniModifier,
) -> str:
    modifier = _require_modifier(modifier)
    return modifier.name


@omni(
    enable=True,
    bl_label="获取修改器类型",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["修改器"],
    _OUTPUT_NAME=["修改器类型"],
    bl_icon="MODIFIER",
)
def modifierGetType(
    modifier: _OmniModifier,
) -> str:
    modifier = _require_modifier(modifier)
    return modifier.type


@omni(
    enable=True,
    bl_label="获取修改器索引",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["修改器"],
    _OUTPUT_NAME=["修改器索引"],
    bl_icon="MODIFIER",
)
def modifierGetIndex(
    modifier: _OmniModifier,
) -> int:
    modifier = _require_modifier(modifier)
    obj = _modifier_owner(modifier)
    return obj.modifiers.find(modifier.name)


@omni(
    enable=True,
    bl_label="获取修改器物体",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["修改器"],
    _OUTPUT_NAME=["物体"],
    bl_icon="MODIFIER",
)
def modifierGetObject(
    modifier: _OmniModifier,
) -> bpy.types.Object:
    modifier = _require_modifier(modifier)
    return _modifier_owner(modifier)


@omni(
    enable=True,
    bl_label="移除修改器对象",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["修改器"],
    _OUTPUT_NAME=["物体"],
    bl_icon="MODIFIER",
)
def modifierRemove(
    modifier: _OmniModifier,
) -> bpy.types.Object:
    modifier = _require_modifier(modifier)
    obj = _modifier_owner(modifier)
    obj.modifiers.remove(modifier)
    return obj


@omni(
    enable=True,
    bl_label="移动修改器对象",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["修改器", "目标索引"],
    _OUTPUT_NAME=["物体", "修改器"],
    bl_icon="MODIFIER",
    omni_description="""
    将修改器移动到指定的堆栈索引位置。
    目标索引会自动限制在有效范围内。
    """,
)
def modifierMove(
    modifier: _OmniModifier,
    target_index: int,
) -> tuple[bpy.types.Object, bpy.types.Modifier]:
    modifier = _require_modifier(modifier)
    obj = _modifier_owner(modifier)
    modifier_name = modifier.name
    from_index = obj.modifiers.find(modifier_name)
    if from_index < 0:
        raise ValueError(f"物体 '{obj.name}' 上找不到修改器 '{modifier_name}'")

    max_index = max(0, len(obj.modifiers) - 1)
    target_index = max(0, min(int(target_index), max_index))
    obj.modifiers.move(from_index, target_index)
    return obj, _refetch_modifier(obj, modifier_name)


@omni(
    enable=True,
    bl_label="应用修改器对象",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["修改器"],
    _OUTPUT_NAME=["物体"],
    bl_icon="MODIFIER",
    omni_description="""
    调用 Blender 的 modifier_apply 操作来应用目标修改器。
    目标物体需要在当前上下文中处于可编辑状态。
    """,
)
def modifierApply(
    modifier: _OmniModifier,
) -> bpy.types.Object:
    modifier = _require_modifier(modifier)
    obj = _modifier_owner(modifier)
    _apply_modifier_operator(obj, modifier)
    return obj


@omni(
    enable=True,
    bl_label="设置修改器对象显示",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["修改器", "视图显示", "渲染显示", "编辑模式显示", "On Cage"],
    _OUTPUT_NAME=["修改器"],
    bl_icon="MODIFIER",
    omni_description="""
    一次性设置修改器的多个显示开关。
    """,
)
def modifierSetDisplay(
    modifier: _OmniModifier,
    show_viewport: bool,
    show_render: bool,
    show_in_editmode: bool,
    show_on_cage: bool,
) -> bpy.types.Modifier:
    modifier = _require_modifier(modifier)
    modifier.show_viewport = show_viewport
    modifier.show_render = show_render
    modifier.show_in_editmode = show_in_editmode
    modifier.show_on_cage = show_on_cage
    return modifier


@omni(
    enable=True,
    bl_label="设置修改器对象视图显示",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["修改器", "状态"],
    _OUTPUT_NAME=["修改器"],
    bl_icon="MODIFIER",
)
def modifierSetViewport(
    modifier: _OmniModifier,
    state: bool,
) -> bpy.types.Modifier:
    modifier = _require_modifier(modifier)
    modifier.show_viewport = state
    return modifier


@omni(
    enable=True,
    bl_label="设置修改器对象渲染显示",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["修改器", "状态"],
    _OUTPUT_NAME=["修改器"],
    bl_icon="MODIFIER",
)
def modifierSetRender(
    modifier: _OmniModifier,
    state: bool,
) -> bpy.types.Modifier:
    modifier = _require_modifier(modifier)
    modifier.show_render = state
    return modifier


@omni(
    enable=True,
    bl_label="设置修改器对象编辑模式显示",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["修改器", "状态"],
    _OUTPUT_NAME=["修改器"],
    bl_icon="MODIFIER",
)
def modifierSetEditmode(
    modifier: _OmniModifier,
    state: bool,
) -> bpy.types.Modifier:
    modifier = _require_modifier(modifier)
    modifier.show_in_editmode = state
    return modifier


@omni(
    enable=True,
    bl_label="设置修改器对象On Cage",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["修改器", "状态"],
    _OUTPUT_NAME=["修改器"],
    bl_icon="MODIFIER",
)
def modifierSetOnCage(
    modifier: _OmniModifier,
    state: bool,
) -> bpy.types.Modifier:
    modifier = _require_modifier(modifier)
    modifier.show_on_cage = state
    return modifier
