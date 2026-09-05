import bpy
from bpy.types import Operator
from mathutils import Vector

from .properties import get_scene_settings


def _corner_angle(mesh, polygon, loop_offset):
    loop_index = polygon.loop_start + loop_offset
    vertex_index = mesh.loops[loop_index].vertex_index
    prev_index = mesh.loops[polygon.loop_start + (loop_offset - 1) % polygon.loop_total].vertex_index
    next_index = mesh.loops[polygon.loop_start + (loop_offset + 1) % polygon.loop_total].vertex_index
    vertex = mesh.vertices[vertex_index].co
    previous = mesh.vertices[prev_index].co - vertex
    following = mesh.vertices[next_index].co - vertex
    if previous.length_squared == 0.0 or following.length_squared == 0.0:
        return 0.0
    return previous.angle(following)


def bake_smoothnormal_os(mesh, attribute_name):
    accumulators = [Vector((0.0, 0.0, 0.0)) for _ in mesh.vertices]
    weights = [0.0 for _ in mesh.vertices]

    for polygon in mesh.polygons:
        if polygon.normal.length_squared == 0.0:
            continue
        face_normal = polygon.normal.normalized()
        for offset, loop_index in enumerate(polygon.loop_indices):
            vertex_index = mesh.loops[loop_index].vertex_index
            weight = _corner_angle(mesh, polygon, offset)
            if weight <= 0.0:
                continue
            accumulators[vertex_index] += face_normal * weight
            weights[vertex_index] += weight

    normals = []
    for vertex_index, vertex in enumerate(mesh.vertices):
        if accumulators[vertex_index].length_squared > 1e-12:
            normals.append(accumulators[vertex_index].normalized())
        elif vertex.normal.length_squared > 1e-12:
            normals.append(vertex.normal.normalized())
        else:
            normals.append(Vector((0.0, 0.0, 1.0)))

    existing = mesh.attributes.get(attribute_name)
    if existing is not None:
        if existing.data_type != "FLOAT_VECTOR" or existing.domain != "CORNER":
            raise RuntimeError(
                f"属性 {attribute_name} 已存在，但不是 FLOAT_VECTOR/CORNER，未覆盖"
            )
        attribute = existing
    else:
        attribute = mesh.attributes.new(
            name=attribute_name,
            type="FLOAT_VECTOR",
            domain="CORNER",
        )

    for loop in mesh.loops:
        attribute.data[loop.index].vector = normals[loop.vertex_index]
    mesh.update()
    return len(normals), len(mesh.loops)


class HO_OT_bake_smoothnormal_os(Operator):
    bl_idname = "ho.bake_smoothnormal_os"
    bl_label = "烘焙 smoothnormalOS"
    bl_description = "按邻接面角度加权烘焙对象空间平滑法线到 Face Corner 属性"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def execute(self, context):
        obj = context.object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, "请先选择一个网格物体")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        settings = get_scene_settings(context.scene)
        name = settings.smoothnormal_attribute_name.strip()
        if not name:
            self.report({"WARNING"}, "属性名不能为空")
            return {"CANCELLED"}
        try:
            vertex_count, loop_count = bake_smoothnormal_os(obj.data, name)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, f"已写入 {name}：{vertex_count} 个顶点，{loop_count} 个面角")
        return {"FINISHED"}


CLASSES = (HO_OT_bake_smoothnormal_os,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
