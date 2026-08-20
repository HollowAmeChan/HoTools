"""Curve repair tools for paths with too few NURBS controls for their order."""

import bpy
from bpy.props import IntProperty


def _active_spline(curve):
    active = getattr(curve.splines, 'active', None)
    return active or (curve.splines[0] if curve.splines else None)


def _point_count(spline):
    if spline is None:
        return 0
    if spline.type == 'BEZIER':
        return len(spline.bezier_points)
    return len(spline.points)


DEFAULT_NURBS_ORDER = 5


def _repair_spline(spline, order_u):
    """Repair one spline and return its status and control count."""
    count = _point_count(spline)
    if spline is None or count <= 3:
        return 'TOO_FEW_POINTS', count
    if spline.type == 'NURBS':
        if count < order_u:
            return 'INSUFFICIENT_POINTS', count
        # Set order only when enough controls exist.  Blender otherwise clamps
        # it and the path remains at the wrong smoothness after a later edit.
        spline.order_u = order_u
        spline.use_endpoint_u = True
        if spline.resolution_u < 1:
            spline.resolution_u = 12
    elif spline.type == 'BEZIER':
        for point in spline.bezier_points:
            point.handle_left_type = 'AUTO_CLAMPED'
            point.handle_right_type = 'AUTO_CLAMPED'
    else:
        return 'UNSUPPORTED_SPLINE', count
    return 'FINISHED', count


def repair_curve(obj, order_u=DEFAULT_NURBS_ORDER):
    splines = list(obj.data.splines)
    if not splines:
        return 'TOO_FEW_POINTS', 0

    statuses = [_repair_spline(spline, order_u) for spline in splines]
    count = _point_count(_active_spline(obj.data))
    if any(status == 'FINISHED' for status, _ in statuses):
        result = 'FINISHED'
    elif any(status == 'INSUFFICIENT_POINTS' for status, _ in statuses):
        result = 'INSUFFICIENT_POINTS'
    elif all(status == 'TOO_FEW_POINTS' for status, _ in statuses):
        result = 'TOO_FEW_POINTS'
    else:
        result = 'UNSUPPORTED_SPLINE'
    obj.data.update_tag()
    return result, count


class OP_RepairCurvePath(bpy.types.Operator):
    bl_idname = 'ho.repair_curve_path'
    bl_label = '修复曲线平滑度'
    bl_description = '修复控制点较少的路径曲线，恢复平滑挤出'
    bl_options = {'REGISTER', 'UNDO'}

    order_u: IntProperty(
        name='NURBS 阶数',
        description='恢复曲线使用的 NURBS 阶数，控制点不足时不会执行',
        default=DEFAULT_NURBS_ORDER,
        min=2,
        max=6,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE'

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            return {'CANCELLED'}

        result, count = repair_curve(obj, self.order_u)
        if result == 'TOO_FEW_POINTS':
            self.report({'INFO'}, '控制点不超过 3 个，跳过曲线修复')
            return {'CANCELLED'}
        if result == 'INSUFFICIENT_POINTS':
            self.report(
                {'WARNING'},
                f'控制点不足：当前 {count} 个，需要 {self.order_u} 个',
            )
            return {'CANCELLED'}
        if result == 'UNSUPPORTED_SPLINE':
            self.report({'INFO'}, '当前样条不是 NURBS 或 Bézier，跳过曲线修复')
            return {'CANCELLED'}

        self.report({'INFO'}, '曲线平滑度已修复')
        return {'FINISHED'}


class HO_MT_curve(bpy.types.Menu):
    bl_idname = 'HO_MT_curve'
    bl_label = 'HoCurve'

    def draw(self, context):
        self.layout.operator(
            OP_RepairCurvePath.bl_idname,
            text='修复曲线平滑度',
        )


def draw_in_VIEW3D_MT_edit_curve_context_menu(self, context):
    obj = context.active_object
    if obj is not None and obj.type == 'CURVE':
        self.layout.separator()
        self.layout.menu(HO_MT_curve.bl_idname)


def register():
    bpy.utils.register_class(OP_RepairCurvePath)
    bpy.utils.register_class(HO_MT_curve)


def unregister():
    bpy.utils.unregister_class(HO_MT_curve)
    bpy.utils.unregister_class(OP_RepairCurvePath)
