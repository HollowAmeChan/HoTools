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

    # 矩阵大小：格点位置由它强制划分（列从左到右、行从上到下），
    # 新增点位自动占格点、重排按格点顺序铺、微调按格点步长走。
    matrix_columns: IntProperty(
        name="列数",
        description="矩阵横向格子数；格点均分横轴范围",
        default=3,
        min=_layout.MIN_MATRIX_SIZE,
        soft_max=8,
        max=_layout.MAX_MATRIX_SIZE,
    )  # type: ignore
    matrix_rows: IntProperty(
        name="行数",
        description="矩阵纵向格子数；格点均分纵轴范围",
        default=3,
        min=_layout.MIN_MATRIX_SIZE,
        soft_max=8,
        max=_layout.MAX_MATRIX_SIZE,
    )  # type: ignore


# endregion


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
        name="关闭其他",
        description=(
            "应用控制时，把没进矩阵的形态键值一律归零"
            "（含列表里没有的键、以及该物体上矩阵没覆盖到的键），让预览只由矩阵决定"
        ),
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


def occupied_coordinates(item, *, exclude=-1):
    """已占用的坐标格子（跳过错开的点位）。"""
    taken = {}
    for index, point in enumerate(item.points):
        if index == exclude:
            continue
        taken[(round(point.u, 4), round(point.v, 4))] = index
    return taken


def matrix_grid(item):
    """当前矩阵大小对应的格点坐标（左上起、行优先）。"""
    return _layout.matrix_grid(item.matrix_columns, item.matrix_rows)


def matrix_cell_count(item) -> int:
    """矩阵一共有多少个格点。"""
    return max(1, int(item.matrix_columns)) * max(1, int(item.matrix_rows))


def free_grid_coordinate(item, *, exclude=-1):
    """按矩阵格点顺序找第一个没被占用的格子，返回 ``(u, v)``。

    找不到空位（矩阵已铺满）就返回原点，由调用方决定怎么处理。
    """
    taken = occupied_coordinates(item, exclude=exclude)
    for coordinate in matrix_grid(item):
        if coordinate not in taken:
            return coordinate
    return 0.0, 0.0


def reorder_points_to_grid(item) -> int:
    """把所有点位按格点顺序（左上起、行优先）重新铺开，返回铺设数量。

    与「添加当前形态键」的占位规则一致：列表里第 n 个点放到第 n 个格点。
    超出格点数量的尾部点位会被吸附到最后一个格点（会重合，界面会提示）。
    """
    grid = matrix_grid(item)
    if not grid:
        return 0
    last = grid[-1]
    for index, point in enumerate(item.points):
        u, v = grid[index] if index < len(grid) else last
        point.u = u
        point.v = v
    return len(item.points)


def count_overflow(item) -> int:
    """控键数量溢出：点位比矩阵格点多了多少个（当前矩阵表达不了的点位数）。"""
    if item is None:
        return 0
    return max(0, len(item.points) - matrix_cell_count(item))


def count_duplicate_points(item) -> int:
    """控键重复：坐标完全重合的点位有几处（同一格点上挤了多个控键）。

    与 :func:`_layout.duplicate_coordinate_groups` 同源，这里只给界面一个总数。
    """
    if item is None:
        return 0
    return sum(len(group) - 1
               for group in _layout.duplicate_coordinate_groups(item))


def append_all_from_active(item, obj) -> int:
    """把 ``obj`` 上还没进矩阵的形态键全部追加进来，返回新增数量。

    新点位按矩阵格点顺序占空位；矩阵已满时后续点位会落到最后一个格点（界面提示溢出）。
    """
    if item is None or obj is None:
        return 0
    existing = {point.shape_key for point in item.points if point.shape_key}
    added = 0
    for name in _keys.shape_key_names(obj):
        if name in existing:
            continue
        _append_point(item, name)
        existing.add(name)
        added += 1
    return added


def _append_point(item, name: str, *, u=None, v=None):
    """往矩阵里加一个坐标点；``u/v`` 为 ``None`` 时按矩阵格点自动占位。"""
    if u is None or v is None:
        u, v = free_grid_coordinate(item)
    point = item.points.add()
    point.name = name
    point.shape_key = name
    point.u = round(float(u), 4)
    point.v = round(float(v), 4)
    item.point_index = len(item.points) - 1
    return point


def nudge_point(point, item, du: int, dv: int) -> bool:
    """按矩阵格点把点位挪动 ``du/dv`` 格（正数向右/向上），返回是否变化。

    只有一个格点的方向（列数或行数为 1）挪不动；``u/v`` 会被夹在矩阵范围内，
    已经贴边的方向也不再动。
    """
    if point is None or item is None:
        return False
    columns = max(1, int(item.matrix_columns))
    rows = max(1, int(item.matrix_rows))
    new_u, new_v = point.u, point.v
    if du and columns > 1:
        new_u = min(1.0, max(-1.0, point.u + du * _layout.matrix_unit(columns)))
    if dv and rows > 1:
        new_v = min(1.0, max(-1.0, point.v + dv * _layout.matrix_unit(rows)))
    if abs(new_u - point.u) < 1e-9 and abs(new_v - point.v) < 1e-9:
        return False
    point.u = round(new_u, 4)
    point.v = round(new_v, 4)
    return True


class OP_ShapekeyTools_BlendPointAddActive(Operator):
    bl_idname = "ho.shapekeytools_blend_point_add_active"
    bl_label = "添加当前形态键"
    bl_description = (
        "把当前活动形态键加进矩阵（自动占一个空格子），并把活动形态键切到下一个，"
        "方便一个一个往下点；活动物体不在操作物体列表里时会一并加进去"
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

        shape_keys = getattr(obj.data, "shape_keys", None)
        basis = shape_keys.reference_key if shape_keys is not None else None
        active = getattr(obj, "active_shape_key", None)
        if active is None:
            self.report({'WARNING'}, "活动物体没有活动形态键")
            return {'CANCELLED'}
        name = active.name
        if basis is not None and active == basis:
            # 停在基础键上时，从第一个可用的非基础键开始
            name = names[0]
        if shape_keys.key_blocks.get(name) is None:
            self.report({'WARNING'}, f"活动键 {name} 不在形态键列表里")
            return {'CANCELLED'}

        existing = next(
            (index for index, point in enumerate(item.points)
             if point.shape_key == name), None)
        if existing is None:
            _append_point(item, name)
        else:
            # 已经在矩阵里：不新建，只把活动行切过去，避免重复点位
            item.point_index = existing

        if not item.objects:
            before = len(item.objects)
            if _keys.append_object(item, obj):
                set_object_list_index(scene, before)

        # 切到下一个键，方便连续点击
        next_index = (names.index(name) + 1) % len(names)
        try:
            obj.active_shape_key_index = shape_keys.key_blocks.find(names[next_index])
            switched = names[next_index]
        except (AttributeError, ReferenceError, TypeError, ValueError):
            switched = "?"
        self.report({'INFO'}, f"已添加 {name}，活动键切到 {switched}")
        return {'FINISHED'}


class OP_ShapekeyTools_BlendPointAppendFromActive(Operator):
    bl_idname = "ho.shapekeytools_blend_point_append_active"
    bl_label = "追加活动物体所有键"
    bl_description = (
        "把当前活动物体上**还没进矩阵**的形态键全部追加到列表末尾（按矩阵格点占位），"
        "已经在矩阵里的键不会重复添加"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        item = active_item(scene)
        if item is None:
            self.report({'WARNING'}, "请先新建一个调试矩阵")
            return {'CANCELLED'}
        obj = context.object
        if not _keys.shape_key_names(obj):
            self.report({'WARNING'}, "活动物体没有可用的形态键")
            return {'CANCELLED'}

        added = append_all_from_active(item, obj)
        if not added:
            self.report({'INFO'}, "活动物体的形态键都已经在矩阵里了")
            return {'CANCELLED'}

        if not item.objects:
            before = len(item.objects)
            if _keys.append_object(item, obj):
                set_object_list_index(scene, before)

        overflow = count_overflow(item)
        if overflow:
            self.report({'WARNING'},
                        f"追加 {added} 个控键，已有 {overflow} 个超出矩阵格点")
        else:
            self.report({'INFO'}, f"已追加 {added} 个控键")
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


class OP_ShapekeyTools_BlendPointReorder(Operator):
    bl_idname = "ho.shapekeytools_blend_point_reorder"
    bl_label = "重排矩阵"
    bl_description = (
        "按当前矩阵大小，把点位从左上角开始按行优先顺序铺到格点上"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        item = active_item(context.scene)
        if item is None or not item.points:
            self.report({'WARNING'}, "没有点位可重排")
            return {'CANCELLED'}
        count = reorder_points_to_grid(item)
        overflow = count - matrix_cell_count(item)
        if overflow > 0:
            self.report(
                {'WARNING'},
                f"已重排 {count} 个点位，其中 {overflow} 个超出矩阵格点（会重合）")
        else:
            self.report({'INFO'}, f"已把 {count} 个点位铺到 "
                                  f"{item.matrix_columns}×{item.matrix_rows} 格点")
        return {'FINISHED'}


class OP_ShapekeyTools_BlendPointNudge(Operator):
    bl_idname = "ho.shapekeytools_blend_point_nudge"
    bl_label = "微调控制点"
    bl_description = "按矩阵格点把一个点位挪动一格（正数向右/向上）"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(name="下标", default=-1)  # type: ignore
    du: IntProperty(name="列方向", default=0, min=-1, max=1)  # type: ignore
    dv: IntProperty(name="行方向", default=0, min=-1, max=1)  # type: ignore

    def execute(self, context):
        item = active_item(context.scene)
        if item is None or not item.points:
            return {'CANCELLED'}
        index = self.index if self.index >= 0 else item.point_index
        if not 0 <= index < len(item.points):
            return {'CANCELLED'}
        if not nudge_point(item.points[index], item, self.du, self.dv):
            return {'CANCELLED'}
        return {'FINISHED'}


class OP_ShapekeyTools_BlendPointSetShapeKey(Operator):
    bl_idname = "ho.shapekeytools_blend_point_set_key"
    bl_label = "指定形态键"
    bl_description = "把该坐标点指向一个具体的形态键（从物体的键里选）"
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
    OP_ShapekeyTools_BlendPointAddActive,
    OP_ShapekeyTools_BlendPointAppendFromActive,
    OP_ShapekeyTools_BlendPointRemove,
    OP_ShapekeyTools_BlendPointReorder,
    OP_ShapekeyTools_BlendPointNudge,
    OP_ShapekeyTools_BlendPointSetShapeKey,
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
