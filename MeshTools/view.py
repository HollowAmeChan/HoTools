import bpy
from bpy.types import Operator
from mathutils import Vector


class OP_AlignViewToAvgNormal(Operator):
    bl_idname = "ho.align_to_avg_normal"
    bl_label = "视图对准面"
    bl_description = "根据当前选中面的平均法向，将视图对准法向的负方向"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # 只能在 3D 视图且编辑网格模式下启用
        return (context.area.type == 'VIEW_3D' and
                context.object is not None and
                context.object.type == 'MESH' and
                context.mode == 'EDIT_MESH')

    def execute(self, context):
        obj = context.object
        mesh = obj.data

        # 切换到 OBJECT 模式以便读取世界坐标下的法线
        bpy.ops.object.mode_set(mode='OBJECT')
        mat_world = obj.matrix_world

        # 计算选中面法线的世界空间平均向量
        normal_sum = Vector((0.0, 0.0, 0.0))
        for poly in mesh.polygons:
            if poly.select:
                normal_sum += mat_world.to_3x3() @ poly.normal

        if normal_sum.length == 0.0:
            self.report({'ERROR'}, "未选择任何面")
            bpy.ops.object.mode_set(mode='EDIT')
            return {'CANCELLED'}

        avg_normal = normal_sum.normalized()
        # 我们希望视图沿 avg_normal 的反方向（法向朝向视点）
        view_dir = -avg_normal

        # 获取 3D 视图的 Region3D，设置为正交并对准法向
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                region_3d = area.spaces.active.region_3d
                # # 切换到正交视图
                # region_3d.view_perspective = 'ORTHO'
                # 计算旋转四元数：将本地 -Z 轴（视图朝向）对齐到 view_dir
                rot_quat = view_dir.to_track_quat('-Z', 'Y')
                region_3d.view_rotation = rot_quat
                # 可选：调整缩放或距离，以便更好地查看
                # region_3d.view_distance = max(mesh.dimensions) * 2.0
                break

        # 切回编辑模式
        bpy.ops.object.mode_set(mode='EDIT')

        return {'FINISHED'}
