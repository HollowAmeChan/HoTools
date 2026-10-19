"""Manual selected-edge line unwrap and automatic threshold straightening."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty

from Utils.mesh_uv import collect_uv_islands, iter_edit_uv_meshes, selected_uv_edge_loops, uv_edit_poll, write_uv_points
from Utils.uv_chains import find_straight_chains, trace_open_chains
from Utils.uv_topology import IslandTopology, TopologyError
from Utils.uv_quad import QuadLayoutError
from Utils.uv_state import UVSceneState
from .unwrap import unwrap_line_islands
from .quadrify import quad_uv_points, quadrify_island_plan


DIRECTIONS = (('AUTO', '最近 U/V 轴', ''), ('U', '水平 / U', ''),
              ('V', '垂直 / V', ''), ('KEEP', '保留线方向', '拟合直线，不吸附坐标轴'))
METHODS = (('ANGLE_BASED', '角度展开', ''), ('CONFORMAL', '保形展开', ''))


def _finish(operator, context, requests, rejected, method, direction, respect_pins, preserve_lengths):
    try:
        count, failures = unwrap_line_islands(context, requests, method, direction, respect_pins, preserve_lengths)
    except (ValueError, RuntimeError) as exc:
        operator.report({'WARNING'}, str(exc))
        return {'CANCELLED'}
    rejected.extend(reason for key, reason in failures)
    message = f'处理 {count} 岛，跳过 {len(rejected)} 岛'
    if rejected:
        message += '；' + '；'.join(dict.fromkeys(rejected))
    operator.report({'INFO'} if count else {'WARNING'}, message)
    return {'FINISHED'} if count else {'CANCELLED'}


class OP_UVTools_LineUnwrap(bpy.types.Operator):
    bl_idname = 'ho.uvtools_line_unwrap'
    bl_label = '线展开所选 UV 岛'
    bl_description = '将选中的 UV 开链拉直并展开周围区域；支持同岛多条不相交内部线，保持 UV 朝向'
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(name='直线方向', items=DIRECTIONS, default='AUTO')  # type: ignore
    method: EnumProperty(name='展开方法', items=METHODS, default='ANGLE_BASED')  # type: ignore
    respect_pins: BoolProperty(name='尊重原固定点', default=True)  # type: ignore

    @classmethod
    def poll(cls, context):
        return uv_edit_poll(context)

    def execute(self, context):
        settings = context.scene.tool_settings
        if (settings.use_uv_select_sync and not settings.mesh_select_mode[1]) or (
                not settings.use_uv_select_sync and settings.uv_select_mode != 'EDGE'):
            self.report({'WARNING'}, '请在边选择模式选择需要拉直的 UV 开链')
            return {'CANCELLED'}
        requests, rejected = [], []
        for obj, bm, uv in iter_edit_uv_meshes(context):
            edges = selected_uv_edge_loops(bm, uv, settings)
            for island in collect_uv_islands(obj, bm, uv, settings):
                loop_node = {loop: v for v, loops in enumerate(island.vertex_loops) for loop in loops}
                chosen = {tuple(sorted((loop_node[loop], loop_node[loop.link_loop_next])))
                          for face in island.faces for loop in face.loops if loop in edges}
                if not chosen:
                    continue
                try:
                    requests.append((island, trace_open_chains(chosen)))
                except ValueError as exc:
                    rejected.append(str(exc))
        if not requests and not rejected:
            rejected.append('没有选中的 UV 开链')
        return _finish(self, context, requests, rejected, self.method, self.direction, self.respect_pins, True)


class OP_UVTools_StraightenIsland(bpy.types.Operator):
    bl_idname = 'ho.uvtools_straighten_island'
    bl_label = '直化所选 UV 岛'
    bl_description = '四边形岛优先按拓扑生成严格矩形行列；其他岛可按近直线阈值直化，保持原UV旋转与镜像朝向'
    bl_options = {'REGISTER', 'UNDO'}

    algorithm: EnumProperty(name='直化算法', items=(
        ('AUTO', '四边形优先', '规则四边形岛按拓扑四边化，其他岛使用阈值直化'),
        ('QUAD', '拓扑四边化', '按四边形连接关系生成笔直、正交的行列；3D边长按行列平均'),
        ('THRESHOLD', '阈值直化', '只直化符合转角与全链偏差阈值的线，适合三角面和混合面'),
    ), default='AUTO')  # type: ignore

    angle_threshold: FloatProperty(name='转角阈值', default=10, min=0, max=45,
                                  description='相邻边允许偏离直线的最大角度，单位为度')  # type: ignore
    deviation_threshold: FloatProperty(name='全链偏差', default=.005, min=0, max=.1, subtype='FACTOR',
                                      description='全链最大垂直偏差与链长的比值，防止密集圆弧被误判')  # type: ignore
    include_internal: BoolProperty(name='包含内部线', default=True,
                                  description='四边形优先模式关闭此项时仅使用边界阈值直化')  # type: ignore
    direction: EnumProperty(name='直线方向', items=(DIRECTIONS[3], DIRECTIONS[0]), default='KEEP')  # type: ignore
    method: EnumProperty(name='展开方法', items=METHODS, default='ANGLE_BASED')  # type: ignore
    respect_pins: BoolProperty(name='尊重原固定点', default=True)  # type: ignore

    @classmethod
    def poll(cls, context):
        return uv_edit_poll(context)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'algorithm')
        layout.prop(self, 'direction')
        layout.prop(self, 'respect_pins')
        if self.algorithm != 'QUAD':
            layout.prop(self, 'include_internal')
            box = layout.box()
            box.label(text='阈值直化参数')
            box.prop(self, 'angle_threshold')
            box.prop(self, 'deviation_threshold')
            box.prop(self, 'method')

    def execute(self, context):
        requests, rejected, quad_plans, quad_count = [], [], [], 0
        for obj, bm, uv in iter_edit_uv_meshes(context):
            for island in collect_uv_islands(obj, bm, uv, context.scene.tool_settings, split_overlaps=True):
                if not island.selected:
                    continue
                try:
                    topology = IslandTopology(island.coordinates, island.polygons)
                    if self.algorithm == 'QUAD' or (self.algorithm == 'AUTO' and self.include_internal
                                                   and all(len(face) == 4 for face in island.polygons)):
                        try:
                            quad_plans.append(quadrify_island_plan(context, island, self.direction, self.respect_pins, topology))
                            quad_count += 1
                            continue
                        except QuadLayoutError:
                            if self.algorithm == 'QUAD':
                                raise
                    chains = find_straight_chains(topology, self.angle_threshold, self.deviation_threshold, self.include_internal)
                    if not chains:
                        raise ValueError('岛内没有满足阈值的近直线开链')
                    requests.append((island, chains))
                except (TopologyError, ValueError) as exc:
                    rejected.append(str(exc))
        if not requests and not rejected and not quad_count:
            rejected.append('没有选中的 UV 岛')
        # The legacy solver temporarily restores coordinates. Run it before the
        # final direct quad write so its transaction cannot overwrite quad plans.
        scene_state = UVSceneState(context) if requests and quad_plans else None
        try:
            count, failures = unwrap_line_islands(context, requests, self.method, self.direction, self.respect_pins, False)
            write_uv_points(quad_uv_points(quad_plans))
        except (ValueError, RuntimeError) as exc:
            if scene_state is not None:
                scene_state.restore()
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        rejected.extend(reason for key, reason in failures)
        message = f'四边化 {quad_count} 岛，阈值直化 {count} 岛，跳过 {len(rejected)} 岛'
        if rejected:
            message += '；'+'；'.join(dict.fromkeys(rejected))
        self.report({'INFO'} if quad_count+count else {'WARNING'}, message)
        return {'FINISHED'} if quad_count+count else {'CANCELLED'}


STRAIGHTEN_CLASSES = (OP_UVTools_LineUnwrap, OP_UVTools_StraightenIsland)
