"""形态键混合矩阵调试页的数据模型与数据算子。

这里只负责“数据”与“数据操作”：

- 调试项（``ho_bs_debug_items``）：一个混合矩阵，包含一组坐标点、每条轴的参数名、
  混合模式，以及它自己的操作物体对象列表；
- 坐标点（``PG_ShapekeyTools_BlendPoint``）：``(u, v)`` 坐标 + 目标形态键名，
  可逐点临时禁用；
- 操作物体（``PG_ShapekeyTools_BlendObject``）：参与混合的网格对象（只有物体指针 +
  名字兜底，没有其它行状态，列表里出现的行都参与混合）；
- 上面这些数据的新建/删除/清空/取键等算子。

取值与排布这类工具都在 ``blend_utils`` 里：

- ``shapekey_utils``：操作物体/点位取值、形态键名、往列表里加物体；
- ``point_layout``：坐标点位的矩阵排布与重合检测；
- ``blend_func``：权重求值缓存、权重写入形态键；
- ``draw_func``：视口/面板绘制原语。

界面在 ``blend_editor``，视口绘件在 ``blend_overlay``。
"""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, PropertyGroup

try:
    from .blend_utils import blend_space_math as _math
    from .blend_utils import point_layout as _layout
    from .blend_utils import shapekey_utils as _keys
except ImportError:  # 兼容旧工具直接导入脚本
    from blend_utils import blend_space_math as _math
    from blend_utils import point_layout as _layout
    from blend_utils import shapekey_utils as _keys


# region 属性组


class PG_ShapekeyTools_BlendPoint(PropertyGroup):
    """混合矩阵里的一个坐标点位，对应一个目标形态键。"""

    name: StringProperty(name="名称", default="")  # type: ignore
    u: FloatProperty(
        name="横坐标",
        description="第一参数轴上的坐标；对齐 Unity 混合树的 PosX",
        default=0.0,
        soft_min=-1.0,
        soft_max=1.0,
        precision=4,
    )  # type: ignore
    v: FloatProperty(
        name="纵坐标",
        description="第二参数轴上的坐标；对齐 Unity 混合树的 PosY",
        default=0.0,
        soft_min=-1.0,
        soft_max=1.0,
        precision=4,
    )  # type: ignore
    shape_key: StringProperty(
        name="形态键",
        description="该坐标点驱动的形态键名；用右侧菜单直接从物体的键里挑，也可以手打",
        default="",
    )  # type: ignore
    enabled: BoolProperty(
        name="启用",
        description="临时禁用该坐标点：不参与混合，也不会被写入",
        default=True,
    )  # type: ignore
    is_current: BoolProperty(
        name="当前",
        description="该坐标点与当前输入坐标重合（只读标记）",
        default=False,
        options={'HIDDEN'},
    )  # type: ignore


class PG_ShapekeyTools_BlendObject(PropertyGroup):
    """混合矩阵作用的一个网格对象。"""

    object: PointerProperty(
        type=bpy.types.Object,
        name="物体",
        description="参与混合的网格对象",
    )  # type: ignore
    object_name: StringProperty(
        name="物体名",
        description="object 指针失效（物体被删除或改名）时用于找回",
        default="",
        options={'HIDDEN'},
    )  # type: ignore


class PG_ShapekeyTools_BlendDebugItem(PropertyGroup):
    """一条混合矩阵调试配置。"""

    name: StringProperty(name="名称", default="")  # type: ignore
    u_name: StringProperty(
        name="横轴参数",
        description="第一参数（横轴）的名字，只用于显示",
        default="X",
    )  # type: ignore
    v_name: StringProperty(
        name="纵轴参数",
        description="第二参数（纵轴）的名字，只用于显示",
        default="Y",
    )  # type: ignore
    mix_mode: EnumProperty(
        name="混合模式",
        description="权重求解方式，对齐 Unity 混合树",
        items=_math.BLEND_MODE_ITEMS,
        default=_math.MODE_CARTESIAN_2D,
    )  # type: ignore
    cursor_u: FloatProperty(
        name="横轴输入",
        description="当前调试输入的横轴坐标（视口绘件可由中心点拖动改写）",
        default=0.0,
        soft_min=-1.0,
        soft_max=1.0,
        precision=4,
    )  # type: ignore
    cursor_v: FloatProperty(
        name="纵轴输入",
        description="当前调试输入的纵轴坐标（视口绘件可由中心点拖动改写）",
        default=0.0,
        soft_min=-1.0,
        soft_max=1.0,
        precision=4,
    )  # type: ignore
    points: CollectionProperty(type=PG_ShapekeyTools_BlendPoint)  # type: ignore
    point_index: IntProperty(name="当前坐标点", default=0)  # type: ignore
    objects: CollectionProperty(type=PG_ShapekeyTools_BlendObject)  # type: ignore
    objects_expanded: BoolProperty(
        name="展开操作物体对象列表",
        default=True,
    )  # type: ignore
    auto_fill_grid: BoolProperty(
        name="自动排布",
        description="从活动物体取键时，按行列矩阵自动铺开坐标点",
        default=True,
    )  # type: ignore


# region 属性注册


def reg_props():
    bpy.types.Scene.ho_bs_debug_items = CollectionProperty(
        type=PG_ShapekeyTools_BlendDebugItem)
    bpy.types.Scene.ho_bs_debug_index = IntProperty(name="当前调试项", default=0)
    # 「操作物体对象列表」用标准 UIList + template_list 绘制，活动行下标必须挂在 ID
    # （场景）上，且与列表数据同一层，这样 template_list 才能接管选中与滚动。
    # 注意：这个属性只能在算子里写，**绝不能在面板绘制回调里写** —— Blender 会抛
    # “Writing to ID classes in this context is not allowed”，整个面板会从那里断掉。
    bpy.types.Scene.ho_bs_object_list = IntProperty(name="当前操作物体", default=0)
    bpy.types.Scene.ho_bs_mute_others = BoolProperty(
        name="静音矩阵外的形态键",
        description="应用权重时，把不在矩阵里的形态键临时静音（调试预览用）",
        default=True,
    )
    bpy.types.Scene.ho_bs_apply_on_cursor = BoolProperty(
        name="拖动时实时写入",
        description="在视口里拖动中心点或坐标点时，实时把权重写进形态键",
        default=True,
    )


def ureg_props():
    del bpy.types.Scene.ho_bs_debug_items
    del bpy.types.Scene.ho_bs_debug_index
    del bpy.types.Scene.ho_bs_object_list
    del bpy.types.Scene.ho_bs_mute_others
    del bpy.types.Scene.ho_bs_apply_on_cursor


# region 取值辅助


def debug_items(scene):
    """返回场景中的调试项集合（属性未注册时返回空元组）。"""
    return getattr(scene, "ho_bs_debug_items", ())


def active_index(scene) -> int:
    return int(getattr(scene, "ho_bs_debug_index", 0))


def active_item(scene):
    """返回当前选中的调试项，越界时返回 ``None``。"""
    items = debug_items(scene)
    index = active_index(scene)
    if 0 <= index < len(items):
        return items[index]
    return None


def clamp_index(scene) -> None:
    """把当前调试项与操作物体行的下标都夹回合法范围。"""
    items = debug_items(scene)
    if not items:
        scene.ho_bs_debug_index = 0
    else:
        scene.ho_bs_debug_index = max(0, min(active_index(scene), len(items) - 1))
    item = active_item(scene)
    count = len(item.objects) if item is not None else 0
    scene.ho_bs_object_list = max(0, min(object_list_index(scene), count - 1)) \
        if count else 0


def object_list_index(scene) -> int:
    """操作物体对象列表的当前行下标（总在合法范围内）。"""
    return int(getattr(scene, "ho_bs_object_list", 0))


def set_object_list_index(scene, index: int) -> int:
    """设置当前行下标并夹回合法范围，返回实际写入的值。

    **只能在算子里调用**：这是 ID（场景）属性，面板绘制回调里写会直接抛异常。
    """
    item = active_item(scene)
    count = len(item.objects) if item is not None else 0
    if count <= 0:
        scene.ho_bs_object_list = 0
        return 0
    value = max(0, min(int(index), count - 1))
    scene.ho_bs_object_list = value
    return value


def _new_item(scene, name: str):
    items = scene.ho_bs_debug_items
    item = items.add()
    item.name = name
    scene.ho_bs_debug_index = len(items) - 1
    scene.ho_bs_object_list = 0
    return item


# endregion


# region 调试矩阵算子


class OP_ShapekeyTools_BlendDebugAdd(Operator):
    bl_idname = "ho.shapekeytools_blend_debug_add"
    bl_label = "新建设置"
    bl_description = "新建一个混合矩阵调试项"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        item = _new_item(scene, f"混合矩阵 {len(scene.ho_bs_debug_items)}")
        _keys.append_objects(item, _keys.mesh_candidates(context))
        if not item.objects and getattr(context, "object", None) is not None:
            self.report({'INFO'}, "已新建，但活动物体不是网格，未加入物体列表")
        return {'FINISHED'}


class OP_ShapekeyTools_BlendDebugRemove(Operator):
    bl_idname = "ho.shapekeytools_blend_debug_remove"
    bl_label = "删除设置"
    bl_description = "删除当前调试项"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        items = scene.ho_bs_debug_items
        if not items:
            return {'CANCELLED'}
        index = max(0, min(active_index(scene), len(items) - 1))
        items.remove(index)
        clamp_index(scene)
        return {'FINISHED'}


class OP_ShapekeyTools_BlendDebugClear(Operator):
    bl_idname = "ho.shapekeytools_blend_debug_clear"
    bl_label = "清空设置"
    bl_description = "删除全部调试项（不动物体与形态键数据）"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        scene.ho_bs_debug_items.clear()
        scene.ho_bs_debug_index = 0
        scene.ho_bs_object_list = 0
        return {'FINISHED'}


# endregion


# region 坐标点算子


def _rebuild_points(item, names) -> int:
    """用一组形态键名重建坐标点列表（含可选的矩阵自动排布），返回点位数量。"""
    item.points.clear()
    for name in names:
        point = item.points.add()
        point.name = name
        point.shape_key = name
        point.enabled = True
    if item.auto_fill_grid:
        _layout.assign_grid(item)
    item.point_index = 0
    return len(item.points)


class OP_ShapekeyTools_BlendPointAdd(Operator):
    bl_idname = "ho.shapekeytools_blend_point_add"
    bl_label = "添加坐标点"
    bl_description = "在原点附近添加一个坐标点"
    bl_options = {'REGISTER', 'UNDO'}

    shape_key: StringProperty(name="形态键", default="")  # type: ignore

    def execute(self, context):
        item = active_item(context.scene)
        if item is None:
            self.report({'WARNING'}, "请先新建一个调试项")
            return {'CANCELLED'}
        point = item.points.add()
        point.shape_key = self.shape_key
        point.name = self.shape_key or f"点位 {len(item.points)}"
        item.point_index = len(item.points) - 1
        return {'FINISHED'}


class OP_ShapekeyTools_BlendPointRemove(Operator):
    bl_idname = "ho.shapekeytools_blend_point_remove"
    bl_label = "删除坐标点"
    bl_description = "删除当前坐标点"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        item = active_item(context.scene)
        if item is None or not item.points:
            return {'CANCELLED'}
        index = max(0, min(item.point_index, len(item.points) - 1))
        item.points.remove(index)
        item.point_index = max(0, min(index, len(item.points) - 1))
        return {'FINISHED'}


class OP_ShapekeyTools_BlendPointClear(Operator):
    bl_idname = "ho.shapekeytools_blend_point_clear"
    bl_label = "清空坐标点"
    bl_description = "删除当前调试项的全部坐标点"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        item = active_item(context.scene)
        if item is None:
            return {'CANCELLED'}
        item.points.clear()
        item.point_index = 0
        return {'FINISHED'}


class OP_ShapekeyTools_BlendPointFromActive(Operator):
    bl_idname = "ho.shapekeytools_blend_point_from_active"
    bl_label = "从活动物体取键"
    bl_description = (
        "把活动物体的全部形态键（不含基础键）按顺序生成为坐标点，"
        "可选按行列矩阵自动铺开坐标"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        item = active_item(scene)
        if item is None:
            self.report({'WARNING'}, "请先新建一个调试矩阵")
            return {'CANCELLED'}
        obj = context.object
        names = _keys.shape_key_names(obj)
        if not names:
            self.report({'WARNING'}, "活动物体没有可用的形态键")
            return {'CANCELLED'}

        _rebuild_points(item, names)
        item.name = item.name or obj.name
        if not item.objects:
            before = len(item.objects)
            if _keys.append_objects(item, _keys.mesh_candidates(context)):
                set_object_list_index(context.scene, before)
        self.report({'INFO'}, f"已取入 {len(names)} 个形态键")
        return {'FINISHED'}


class OP_ShapekeyTools_BlendPointFromObject(Operator):
    bl_idname = "ho.shapekeytools_blend_point_from_object"
    bl_label = "从该物体取键"
    bl_description = "用指定网格对象的全部形态键（不含基础键）重建坐标点列表"
    bl_options = {'REGISTER', 'UNDO'}

    # 算子属性不支持 PointerProperty（数据块属性），所以按名字传。
    object_name: StringProperty(name="物体名", default="")  # type: ignore

    def _target(self):
        if self.object_name:
            return bpy.data.objects.get(self.object_name)
        return None

    def execute(self, context):
        item = active_item(context.scene)
        if item is None:
            self.report({'WARNING'}, "请先新建一个调试矩阵")
            return {'CANCELLED'}
        obj = self._target()
        names = _keys.shape_key_names(obj)
        if not names:
            self.report({'WARNING'}, "该物体没有可用的形态键")
            return {'CANCELLED'}
        _rebuild_points(item, names)
        if obj is not None:
            before = len(item.objects)
            if _keys.append_object(item, obj):
                set_object_list_index(context.scene, before)
        self.report({'INFO'}, f"已从 {obj.name if obj else '物体'} 取入 {len(names)} 个形态键")
        return {'FINISHED'}


class OP_ShapekeyTools_BlendPointApplyGrid(Operator):
    bl_idname = "ho.shapekeytools_blend_point_grid"
    bl_label = "重排为矩阵"
    bl_description = "按当前点位数量把坐标重新铺成居中的行列矩阵"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        item = active_item(context.scene)
        if item is None or len(item.points) < 2:
            self.report({'WARNING'}, "至少需要两个坐标点")
            return {'CANCELLED'}
        _layout.assign_grid(item)
        return {'FINISHED'}


class OP_ShapekeyTools_BlendPointToggle(Operator):
    bl_idname = "ho.shapekeytools_blend_point_toggle"
    bl_label = "启用/禁用坐标点"
    bl_description = "临时禁用坐标点：不参与混合，也不会被写入"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(name="下标", default=-1)  # type: ignore

    def execute(self, context):
        item = active_item(context.scene)
        if item is None:
            return {'CANCELLED'}
        index = self.index if self.index >= 0 else item.point_index
        if not 0 <= index < len(item.points):
            return {'CANCELLED'}
        point = item.points[index]
        point.enabled = not point.enabled
        return {'FINISHED'}


class OP_ShapekeyTools_BlendPointSetShapeKey(Operator):
    bl_idname = "ho.shapekeytools_blend_point_set_key"
    bl_label = "指定形态键"
    bl_description = "把该坐标点指向一个具体的形态键（从物体的键里选或直接填名字）"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(name="下标", default=-1)  # type: ignore
    shape_key: StringProperty(name="形态键", default="")  # type: ignore

    def execute(self, context):
        item = active_item(context.scene)
        if item is None:
            return {'CANCELLED'}
        index = self.index if self.index >= 0 else item.point_index
        if not 0 <= index < len(item.points):
            return {'CANCELLED'}
        point = item.points[index]
        point.shape_key = self.shape_key
        if self.shape_key:
            point.name = self.shape_key
        return {'FINISHED'}


class OP_ShapekeyTools_BlendPointNudge(Operator):
    bl_idname = "ho.shapekeytools_blend_point_nudge"
    bl_label = "微调坐标点"
    bl_description = "按步长微调当前坐标点位置"
    bl_options = {'REGISTER', 'UNDO'}

    du: FloatProperty(name="横轴步长", default=0.0)  # type: ignore
    dv: FloatProperty(name="纵轴步长", default=0.0)  # type: ignore

    def execute(self, context):
        item = active_item(context.scene)
        if item is None or not item.points:
            return {'CANCELLED'}
        index = max(0, min(item.point_index, len(item.points) - 1))
        point = item.points[index]
        point.u = round(point.u + self.du, 4)
        point.v = round(point.v + self.dv, 4)
        return {'FINISHED'}


# endregion


# region 操作物体算子


class OP_ShapekeyTools_BlendObjectAdd(Operator):
    bl_idname = "ho.shapekeytools_blend_object_add"
    bl_label = "添加物体"
    bl_description = "把当前选中的物体（以及活动物体）加入操作物体对象列表"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        item = active_item(context.scene)
        if item is None:
            self.report({'WARNING'}, "请先新建一个调试矩阵")
            return {'CANCELLED'}
        candidates = _keys.mesh_candidates(context)
        if not candidates:
            self.report({'WARNING'}, "没有选中任何网格物体")
            return {'CANCELLED'}
        before = len(item.objects)
        added = _keys.append_objects(item, candidates)
        if added:
            # 选中第一行新增的物体（列表由 template_list 绘制，下标存在场景上）
            set_object_list_index(context.scene, before)
        else:
            self.report({'INFO'}, "选中物体已经在列表里")
        return {'FINISHED'}


class OP_ShapekeyTools_BlendObjectRemove(Operator):
    bl_idname = "ho.shapekeytools_blend_object_remove"
    bl_label = "删除物体"
    bl_description = "从操作物体对象列表里移除该行（不删除真实物体）"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(name="下标", default=-1)  # type: ignore

    def execute(self, context):
        scene = context.scene
        item = active_item(scene)
        if item is None or not item.objects:
            return {'CANCELLED'}
        index = self.index if self.index >= 0 else object_list_index(scene)
        if not 0 <= index < len(item.objects):
            return {'CANCELLED'}
        item.objects.remove(index)
        set_object_list_index(scene, index)
        return {'FINISHED'}


class OP_ShapekeyTools_BlendObjectClear(Operator):
    bl_idname = "ho.shapekeytools_blend_object_clear"
    bl_label = "清空物体"
    bl_description = "清空当前调试项的操作物体对象列表"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        item = active_item(context.scene)
        if item is None:
            return {'CANCELLED'}
        item.objects.clear()
        set_object_list_index(context.scene, 0)
        return {'FINISHED'}


# endregion


cls = [
    PG_ShapekeyTools_BlendPoint,
    PG_ShapekeyTools_BlendObject,
    PG_ShapekeyTools_BlendDebugItem,
    OP_ShapekeyTools_BlendDebugAdd,
    OP_ShapekeyTools_BlendDebugRemove,
    OP_ShapekeyTools_BlendDebugClear,
    OP_ShapekeyTools_BlendPointAdd,
    OP_ShapekeyTools_BlendPointRemove,
    OP_ShapekeyTools_BlendPointClear,
    OP_ShapekeyTools_BlendPointFromActive,
    OP_ShapekeyTools_BlendPointFromObject,
    OP_ShapekeyTools_BlendPointApplyGrid,
    OP_ShapekeyTools_BlendPointToggle,
    OP_ShapekeyTools_BlendPointSetShapeKey,
    OP_ShapekeyTools_BlendPointNudge,
    OP_ShapekeyTools_BlendObjectAdd,
    OP_ShapekeyTools_BlendObjectRemove,
    OP_ShapekeyTools_BlendObjectClear,
]


def register():
    for item in cls:
        bpy.utils.register_class(item)
    reg_props()


def unregister():
    ureg_props()
    for item in reversed(cls):
        bpy.utils.unregister_class(item)
