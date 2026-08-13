import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from bpy.types import Operator
from bpy.props import BoolProperty


# 根据 Blender 内置 Python 版本选择对应的原生模块目录。
_plugin_dir = os.path.dirname(os.path.dirname(__file__))
_lib_dir = os.path.join(_plugin_dir, "_Lib")
if sys.version_info[:2] == (3, 13):
    _python_lib = "py313"
elif sys.version_info[:2] == (3, 11):
    _python_lib = "py311"
else:
    raise RuntimeError(
        "HoTools 仅支持 Python 3.11 和 3.13，当前版本为 "
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )
_native_package_dir = os.path.join(_lib_dir, _python_lib, "HotoolsPackage")
if _native_package_dir not in sys.path:
    sys.path.insert(0, _native_package_dir)


def reg_props():
    return


def ureg_props():
    return


def _load_native_boolean():
    try:
        import hotools_boolean
    except ImportError as exc:
        raise RuntimeError(
            "缺少 hotools_boolean 原生模块，请先运行 _native\\build.bat 311 boolean"
        ) from exc
    return hotools_boolean


def _mesh_arrays(mesh):
    mesh.calc_loop_triangles()
    if not mesh.loop_triangles:
        raise RuntimeError("网格没有可处理的面")

    vertices = np.empty((len(mesh.vertices), 3), dtype=np.float64)
    mesh.vertices.foreach_get("co", vertices.ravel())

    triangles = np.empty((len(mesh.loop_triangles), 3), dtype=np.int32)
    triangle_polygons = np.empty(len(mesh.loop_triangles), dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", triangles.ravel())
    mesh.loop_triangles.foreach_get("polygon_index", triangle_polygons)

    loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
    polygon_starts = np.empty(len(mesh.polygons), dtype=np.int32)
    polygon_totals = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_vertices)
    mesh.polygons.foreach_get("loop_start", polygon_starts)
    mesh.polygons.foreach_get("loop_total", polygon_totals)

    polygon_offsets = np.empty(len(mesh.polygons) + 1, dtype=np.int32)
    polygon_offsets[0] = 0
    np.cumsum(polygon_totals, out=polygon_offsets[1:])
    if np.array_equal(polygon_starts, polygon_offsets[:-1]):
        polygon_vertices = np.ascontiguousarray(loop_vertices)
    else:
        polygon_vertices = np.empty(polygon_offsets[-1], dtype=np.int32)
        for polygon_index, (start, total) in enumerate(
            zip(polygon_starts, polygon_totals)
        ):
            target = polygon_offsets[polygon_index]
            polygon_vertices[target:target + total] = loop_vertices[start:start + total]

    return (
        vertices,
        triangles,
        triangle_polygons,
        polygon_vertices,
        polygon_offsets,
    )


def _build_mesh(source_mesh, result):
    vertices = result["vertices"]
    face_vertices = result["face_vertices"]
    face_offsets = result["face_offsets"]
    face_sources = result["face_sources"]
    face_totals = np.diff(face_offsets).astype(np.int32, copy=False)

    if len(vertices) == 0 or len(face_sources) == 0:
        raise RuntimeError("外壳运算没有生成任何面，请检查网格是否闭合")

    output = bpy.data.meshes.new(f"{source_mesh.name}_OuterHull")
    output.vertices.add(len(vertices))
    output.vertices.foreach_set("co", np.asarray(vertices).ravel())
    output.loops.add(len(face_vertices))
    output.loops.foreach_set("vertex_index", face_vertices)
    output.polygons.add(len(face_sources))
    output.polygons.foreach_set("loop_start", face_offsets[:-1])
    output.polygons.foreach_set("loop_total", face_totals)

    for material in source_mesh.materials:
        output.materials.append(material)

    source_materials = np.empty(len(source_mesh.polygons), dtype=np.int32)
    source_smooth = np.empty(len(source_mesh.polygons), dtype=np.bool_)
    source_mesh.polygons.foreach_get("material_index", source_materials)
    source_mesh.polygons.foreach_get("use_smooth", source_smooth)
    output.polygons.foreach_set("material_index", source_materials[face_sources])
    output.polygons.foreach_set("use_smooth", source_smooth[face_sources])
    output.update(calc_edges=True)
    return output


class OP_BooleanUnionReconstruction(Operator):
    bl_idname = "ho.boolean_union_reconstruction"
    bl_label = "并集重构"
    bl_description = "删除内部相交面和封闭空腔，仅在布尔交线附近生成三角面"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'MESH'

    def execute(self, context):
        obj = context.object
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        source_mesh = obj.data
        try:
            native = _load_native_boolean()
            result = native.outer_hull(*_mesh_arrays(source_mesh))
            output_mesh = _build_mesh(source_mesh, result)
        except Exception as exc:
            self.report({'ERROR'}, f"布尔并集重构失败: {exc}")
            return {'CANCELLED'}

        source_name = source_mesh.name
        obj.data = output_mesh
        if source_mesh.users == 0:
            bpy.data.meshes.remove(source_mesh)
            output_mesh.name = source_name

        self.report(
            {'INFO'},
            "外壳重构完成: "
            f"恢复 {result['restored_polygons']} 个原始多边形，"
            f"交线区 {result['seam_triangles']} 个三角面",
        )
        return {'FINISHED'}


def _active_and_cutters(context):
    """返回活动网格和所有选中的非活动网格。"""
    active = context.object
    if active is None or active.type != 'MESH':
        raise RuntimeError("活动物体必须是网格")
    if active.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    cutters = [
        obj for obj in context.selected_objects
        if obj != active and obj.type == 'MESH'
    ]
    if not cutters:
        raise RuntimeError("请至少再选择一个网格切割物体")
    return active, cutters


def _triangle_arrays(obj, matrix):
    mesh = obj.data
    mesh.calc_loop_triangles()
    if not mesh.loop_triangles:
        raise RuntimeError(f"物体「{obj.name}」没有可处理的三角面")
    vertices = np.empty((len(mesh.vertices), 3), dtype=np.float64)
    mesh.vertices.foreach_get("co", vertices.ravel())
    vertices = np.asarray([matrix @ Vector(v) for v in vertices], dtype=np.float64)
    faces = np.empty((len(mesh.loop_triangles), 3), dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", faces.ravel())
    return np.ascontiguousarray(vertices), np.ascontiguousarray(faces)


def _polygon_arrays(obj, matrix):
    mesh = obj.data
    vertices = np.empty((len(mesh.vertices), 3), dtype=np.float64)
    mesh.vertices.foreach_get("co", vertices.ravel())
    vertices = np.asarray([matrix @ Vector(v) for v in vertices], dtype=np.float64)
    loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
    polygon_starts = np.empty(len(mesh.polygons), dtype=np.int32)
    polygon_totals = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_vertices)
    mesh.polygons.foreach_get("loop_start", polygon_starts)
    mesh.polygons.foreach_get("loop_total", polygon_totals)
    offsets = np.empty(len(mesh.polygons) + 1, dtype=np.int32)
    offsets[0] = 0
    np.cumsum(polygon_totals, out=offsets[1:])
    polygon_vertices = np.empty(offsets[-1], dtype=np.int32)
    for index, (start, total) in enumerate(zip(polygon_starts, polygon_totals)):
        begin = offsets[index]
        polygon_vertices[begin:begin + total] = loop_vertices[start:start + total]
    return (
        np.ascontiguousarray(vertices),
        np.ascontiguousarray(polygon_vertices),
        np.ascontiguousarray(offsets),
    )


def _build_boolean_mesh(source_mesh, result, to_local):
    vertices = np.asarray(result["vertices"], dtype=np.float64)
    faces = np.asarray(result["faces"], dtype=np.int32)
    vertices = np.asarray([to_local @ Vector(vertex) for vertex in vertices], dtype=np.float64)
    if vertices.size == 0 or faces.size == 0:
        raise RuntimeError("布尔运算没有生成有效网格")
    output = bpy.data.meshes.new(f"{source_mesh.name}_布尔结果")
    output.from_pydata(vertices.tolist(), [], faces.tolist())
    for material in source_mesh.materials:
        output.materials.append(material)
    output.update(calc_edges=True)
    return output


def _build_optimized_mesh(source_mesh, result, to_local):
    vertices = np.asarray(result["vertices"], dtype=np.float64)
    faces = np.asarray(result["faces"], dtype=np.int32)
    vertices = np.asarray([to_local @ Vector(vertex) for vertex in vertices], dtype=np.float64)
    if vertices.size == 0 or faces.size == 0:
        raise RuntimeError("自动优化没有生成有效网格")
    output = bpy.data.meshes.new(f"{source_mesh.name}_自动优化")
    output.from_pydata(vertices.tolist(), [], faces.tolist())
    for material in source_mesh.materials:
        output.materials.append(material)
    output.update(calc_edges=True)
    return output


class OP_BooleanAutoOptimize(Operator):
    bl_idname = "ho.boolean_auto_optimize"
    bl_label = "自动优化"
    bl_description = "使用 CGAL 合并重复点、修复方向、自交和空洞，并检查封闭流形"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'MESH'

    def execute(self, context):
        obj = context.object
        try:
            native = _load_native_boolean()
            vertices, polygon_vertices, polygon_offsets = _polygon_arrays(obj, obj.matrix_world)
            result = native.auto_optimize(vertices, polygon_vertices, polygon_offsets)
            output_mesh = _build_optimized_mesh(obj.data, result, obj.matrix_world.inverted())
            source_mesh = obj.data
            obj.data = output_mesh
            if source_mesh.users == 0:
                bpy.data.meshes.remove(source_mesh)
        except Exception as exc:
            self.report({'ERROR'}, f"自动优化失败: {exc}")
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"自动优化完成：填洞 {result['filled_holes']}，"
            f"自交 {'已排除' if result['self_intersections_fixed'] else '仍存在'}，"
            f"封闭 {'是' if result['closed'] else '否'}，"
            f"流形 {'是' if result['manifold'] else '否'}",
        )
        return {'FINISHED'}


class OP_BooleanModifier(Operator):
    """使用 CGAL 精确布尔运算。"""

    bl_options = {'REGISTER', 'UNDO'}
    remove_cutter: BoolProperty(default=False, name="删除非活动物体")
    operation = 'DIFFERENCE'
    operation_label = "差集"

    @classmethod
    def poll(cls, context):
        return (
            context.object is not None
            and context.object.type == 'MESH'
            and context.object.mode == 'OBJECT'
        )

    def execute(self, context):
        try:
            active, cutters = _active_and_cutters(context)
            native = _load_native_boolean()
            source_mesh = active.data
            active_world = active.matrix_world.copy()
            world_to_active = active_world.inverted()
            result = None
            for cutter in cutters:
                vertices_a, faces_a = _triangle_arrays(active, active_world)
                vertices_b, faces_b = _triangle_arrays(cutter, cutter.matrix_world)
                result = native.boolean(vertices_a, faces_a, vertices_b, faces_b, self.operation)
                output_mesh = _build_boolean_mesh(source_mesh, result, world_to_active)
                active.data = output_mesh
                if source_mesh.users == 0:
                    bpy.data.meshes.remove(source_mesh)
                source_mesh = output_mesh

            if self.remove_cutter:
                for cutter in cutters:
                    if cutter.name in bpy.data.objects:
                        bpy.data.objects.remove(cutter, do_unlink=True)
            else:
                for cutter in cutters:
                    cutter.select_set(True)
        except Exception as exc:
            self.report({'ERROR'}, f"{self.operation_label}失败: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"{self.operation_label}完成")
        return {'FINISHED'}


class OP_BooleanIntersection(OP_BooleanModifier):
    bl_idname = "ho.boolean_intersection"
    bl_options = {'REGISTER', 'UNDO'}
    remove_cutter: BoolProperty(default=False, name="删除非活动物体")
    bl_label = "交集"
    operation = 0
    operation_label = "布尔交集"


class OP_BooleanUnion(OP_BooleanModifier):
    bl_idname = "ho.boolean_union"
    bl_options = {'REGISTER', 'UNDO'}
    remove_cutter: BoolProperty(default=False, name="删除非活动物体")
    bl_label = "并集"
    operation = 1
    operation_label = "布尔并集"


class OP_BooleanDifference(OP_BooleanModifier):
    bl_idname = "ho.boolean_difference"
    bl_options = {'REGISTER', 'UNDO'}
    remove_cutter: BoolProperty(default=False, name="删除非活动物体")
    bl_label = "差集"
    operation = 2
    operation_label = "布尔差集"


def draw_in_DATA_PT_remesh(self, context):
    layout: bpy.types.UILayout = self.layout
    layout.operator(OP_BooleanUnionReconstruction.bl_idname)


def draw_in_VIEW3D_MT_object_context_menu(self, context):
    if context.mode != 'OBJECT':
        return
    self.layout.menu(VIEW3D_MT_object_hotools_bool.bl_idname)


class VIEW3D_MT_object_hotools_bool(bpy.types.Menu):
    bl_idname = "VIEW3D_MT_object_hotools_bool"
    bl_label = "HoToolsBool"

    def draw(self, context):
        layout = self.layout
        layout.operator(OP_BooleanIntersection.bl_idname, icon='MOD_BOOLEAN')
        layout.operator(OP_BooleanUnion.bl_idname, icon='MOD_BOOLEAN')
        layout.operator(OP_BooleanDifference.bl_idname, icon='MOD_BOOLEAN')
        layout.separator()
        layout.operator("ho.visual_boolean_cut", icon='MOD_BOOLEAN')
        layout.separator()
        layout.operator(OP_BooleanAutoOptimize.bl_idname, icon='MOD_REMESH')
        layout.separator()
        layout.operator(OP_BooleanUnionReconstruction.bl_idname, icon='MOD_REMESH')


cls = [
    OP_BooleanUnionReconstruction,
    OP_BooleanIntersection,
    OP_BooleanUnion,
    OP_BooleanDifference,
    OP_BooleanAutoOptimize,
    VIEW3D_MT_object_hotools_bool,
]


def register():
    for item in cls:
        bpy.utils.register_class(item)
    bpy.types.DATA_PT_remesh.append(draw_in_DATA_PT_remesh)
    bpy.types.VIEW3D_MT_object_context_menu.prepend(
        draw_in_VIEW3D_MT_object_context_menu
    )
    reg_props()


def unregister():
    bpy.types.VIEW3D_MT_object_context_menu.remove(
        draw_in_VIEW3D_MT_object_context_menu
    )
    for item in cls:
        bpy.utils.unregister_class(item)
    bpy.types.DATA_PT_remesh.remove(draw_in_DATA_PT_remesh)
    ureg_props()
