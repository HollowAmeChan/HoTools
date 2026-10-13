"""UV coordinate tools with an explicit pivot and shared 4.5/5.x selection."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty

from Utils.mesh_uv import align_uv_selection, selected_uv_point_groups, uv_edit_poll, write_uv_points
from Utils.uv_math import bounds_center, mirror_points, translate_points


AXES = (('U', 'X / U', '左右方向'), ('V', 'Y / V', '上下方向'))
ALIGN_TYPES = (('MIN', '最小值', ''), ('MAX', '最大值', ''), ('AVERAGE', '平均值', ''),
               ('ZERO', '归零', ''), ('CURSOR', 'UV 光标', ''))


class OP_UVTools_Mirror(bpy.types.Operator):
    bl_idname = 'ho.uvtools_mirror'
    bl_label = '镜像所选 UV'
    bl_description = '直接翻转选中 UV 坐标，不受 Blender 变换轴心设置影响'
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(name='翻转方向', items=AXES, default='U')  # type: ignore
    center_mode: EnumProperty(name='镜像中心', items=(
        ('BOUNDS', '选区中心', '所选 UV 包围盒中心'),
        ('CURSOR', 'UV 光标', '明确使用 UV 光标作为镜像中心'),
        ('ORIGIN', '原点', '使用 UV 坐标 (0, 0)'),
        ('CUSTOM', '指定坐标', '自定义镜像中心'),
    ), default='BOUNDS')  # type: ignore
    center: FloatVectorProperty(name='指定中心', size=2, default=(0, 0))  # type: ignore
    per_island: BoolProperty(name='各岛分别镜像', default=False)  # type: ignore

    @classmethod
    def poll(cls, context):
        return uv_edit_poll(context)

    def draw(self, context):
        self.layout.prop(self, 'axis', expand=True)
        self.layout.prop(self, 'center_mode')
        if self.center_mode == 'CUSTOM':
            self.layout.prop(self, 'center')
        self.layout.prop(self, 'per_island')

    def execute(self, context):
        try:
            plans = []
            for group in selected_uv_point_groups(context, self.per_island):
                points = [point.coordinate for point in group]
                center = bounds_center(points) if self.center_mode == 'BOUNDS' else (
                    context.space_data.cursor_location if self.center_mode == 'CURSOR' else
                    (0, 0) if self.center_mode == 'ORIGIN' else self.center)
                plans.extend(zip(group, mirror_points(points, 0 if self.axis == 'U' else 1, center)))
            write_uv_points(plans)
        except (ValueError, RuntimeError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class OP_UVTools_Translate(bpy.types.Operator):
    bl_idname = 'ho.uvtools_translate'
    bl_label = '平移所选 UV'
    bl_description = '按明确方向与距离平移 UV，1 UV 单位等于一格 UDIM'
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(name='方向', items=(
        ('POS_U', '右 / +U', ''), ('NEG_U', '左 / −U', ''),
        ('POS_V', '上 / +V', ''), ('NEG_V', '下 / −V', ''),
    ), default='POS_U')  # type: ignore
    distance: FloatProperty(name='距离', min=0, default=1, soft_max=10)  # type: ignore
    unit: EnumProperty(name='单位', items=(('UV', 'UV', ''), ('PIXELS', '像素', '使用当前图像的宽高')), default='UV')  # type: ignore

    @classmethod
    def poll(cls, context):
        return uv_edit_poll(context)

    def execute(self, context):
        try:
            group = selected_uv_point_groups(context)[0]
            image_size = None
            if self.unit == 'PIXELS':
                image = context.space_data.image
                if image is None:
                    raise ValueError('像素平移需要 UV 编辑器中的有效图像')
                image_size = tuple(image.size)
            result = translate_points([point.coordinate for point in group], self.direction, self.distance, image_size)
            write_uv_points(zip(group, result))
        except (ValueError, RuntimeError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class OP_UVTools_Align(bpy.types.Operator):
    bl_idname = 'ho.uvtools_align'
    bl_label = '沿轴对齐所选 UV'
    bl_description = '固定 U 成为垂直线，固定 V 成为水平线；支持多物体与同步模式'
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(name='固定坐标', items=AXES, default='U')  # type: ignore
    type: EnumProperty(name='对齐到', items=ALIGN_TYPES, default='AVERAGE')  # type: ignore
    per_island: BoolProperty(name='各岛分别对齐', default=False)  # type: ignore

    @classmethod
    def poll(cls, context):
        return uv_edit_poll(context)

    def execute(self, context):
        try:
            align_uv_selection(context, self.axis, self.type, self.per_island)
        except (ValueError, RuntimeError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class IMAGE_MT_hotools_uv_align(bpy.types.Menu):
    bl_label = 'UV 对齐'

    def draw(self, context):
        for text, axis, method in (
            ('左侧', 'U', 'MIN'), ('右侧', 'U', 'MAX'), ('底部', 'V', 'MIN'), ('顶部', 'V', 'MAX'),
            ('水平线', 'V', 'AVERAGE'), ('垂直线', 'U', 'AVERAGE'),
            ('水平对齐到光标', 'V', 'CURSOR'), ('垂直对齐到光标', 'U', 'CURSOR'),
        ):
            op = self.layout.operator(OP_UVTools_Align.bl_idname, text=text)
            op.axis, op.type = axis, method


TRANSFORM_CLASSES = (OP_UVTools_Mirror, OP_UVTools_Translate, OP_UVTools_Align, IMAGE_MT_hotools_uv_align)
