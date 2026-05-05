import bpy
from bpy.props import EnumProperty
from bpy.types import Operator
from mathutils import Vector

from .utils import get_active_corner_color_attribute, write_color_data

MODE_ITEMS = [
    ("CUSTOM2RAW", "自定义法线 -> 原始法线", ""),
    ("RAW2CUSTOM", "原始法线 -> 自定义法线", ""),
    ("OBJECT2SMOOTH", "其他物体自定义法线 -> 自定义法线", ""),
    ("SOLIDIFY_RAW2CUSTOM", "原始法线 -> 自定义法线(厚度均衡)", ""),
]


class HO_OT_bake_normal_to_vertex_color(Operator):
    bl_idname = "ho.bake_custom_normal_to_vertex_color"
    bl_label = "烘焙自定义法线到顶点色"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        name="法线空间转换",
        items=[
            (
                "CUSTOM2RAW",
                "custom -> raw",
                "将自定义平滑法线编码到原始 TBN 空间",
            ),
            (
                "RAW2CUSTOM",
                "raw -> custom",
                "将原始法线编码到当前自定义或平滑 TBN 空间",
            ),
            (
                "OBJECT2SMOOTH",
                "other smooth -> active smooth",
                "将另一个拓扑一致物体的平滑法线编码到当前物体",
            ),
            (
                "SOLIDIFY_RAW2CUSTOM",
                "solidify avg -> custom",
                "将近似实心化的平均方向编码到当前 TBN 空间，A 通道保存补偿",
            ),
        ],
        default="CUSTOM2RAW",
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def get_source_normal(self, normal_mesh, loop_index, use_vertex_normal=False):
        if use_vertex_normal:
            vertex_index = normal_mesh.loops[loop_index].vertex_index
            return normal_mesh.vertices[vertex_index].normal.normalized()
        return normal_mesh.loops[loop_index].normal

    def calc_shell_dist(self, normal_a, normal_b):
        dot_value = abs(normal_a.dot(normal_b))
        if dot_value <= 1e-8:
            return 1.0
        return 1.0 / dot_value

    def calc_hq_vertex_normals(self, mesh):
        face_normals = [polygon.normal.normalized() for polygon in mesh.polygons]
        edge_faces = {index: [] for index in range(len(mesh.edges))}
        for polygon in mesh.polygons:
            for loop_index in polygon.loop_indices:
                edge_index = mesh.loops[loop_index].edge_index
                edge_faces[edge_index].append(polygon.index)

        hq_normals = [Vector((0.0, 0.0, 0.0)) for _ in mesh.vertices]
        for edge_index, edge in enumerate(mesh.edges):
            linked_faces = edge_faces[edge_index]
            if len(linked_faces) == 0:
                continue

            if len(linked_faces) == 1:
                edge_normal = face_normals[linked_faces[0]].copy()
            elif len(linked_faces) == 2:
                normal_a = face_normals[linked_faces[0]]
                normal_b = face_normals[linked_faces[1]]
                edge_normal = normal_a + normal_b
                if edge_normal.length_squared == 0.0:
                    edge_normal = normal_a.copy()
                else:
                    edge_normal.normalize()
                    edge_normal *= normal_a.angle(normal_b)
            else:
                continue

            hq_normals[edge.vertices[0]] += edge_normal
            hq_normals[edge.vertices[1]] += edge_normal

        fallback_axis = Vector((0.0, 0.0, 1.0))
        for vertex_index, vertex in enumerate(mesh.vertices):
            if hq_normals[vertex_index].length_squared == 0.0:
                hq_normals[vertex_index] = vertex.normal.copy()
            if hq_normals[vertex_index].length_squared == 0.0:
                hq_normals[vertex_index] = fallback_axis.copy()
            hq_normals[vertex_index].normalize()

        return hq_normals

    def calc_vertex_curvature_signs(self, mesh, directions):
        vertex_neighbors = [[] for _ in mesh.vertices]
        for edge in mesh.edges:
            vertex_a, vertex_b = edge.vertices
            vertex_neighbors[vertex_a].append(vertex_b)
            vertex_neighbors[vertex_b].append(vertex_a)

        signs = []
        for vertex_index, vertex in enumerate(mesh.vertices):
            neighbors = vertex_neighbors[vertex_index]
            if not neighbors:
                signs.append(1.0)
                continue

            laplacian = Vector((0.0, 0.0, 0.0))
            for neighbor_index in neighbors:
                laplacian += mesh.vertices[neighbor_index].co - vertex.co
            laplacian /= len(neighbors)

            if laplacian.length_squared == 0.0:
                signs.append(1.0)
                continue

            signs.append(-1.0 if laplacian.dot(directions[vertex_index]) > 0.0 else 1.0)

        return signs

    def build_even_solidify_source(self, mesh):
        hq_normals = self.calc_hq_vertex_normals(mesh)
        curvature_signs = self.calc_vertex_curvature_signs(mesh, hq_normals)
        vertex_angle_weights = [0.0 for _ in mesh.vertices]
        vertex_angle_sums = [0.0 for _ in mesh.vertices]

        for polygon in mesh.polygons:
            if polygon.loop_total < 3 or polygon.normal.length_squared == 0.0:
                continue

            face_normal = polygon.normal.normalized()
            loop_indices = list(polygon.loop_indices)
            loop_count = len(loop_indices)

            for offset, loop_index in enumerate(loop_indices):
                vertex_index = mesh.loops[loop_index].vertex_index
                vertex_co = mesh.vertices[vertex_index].co

                prev_loop_index = loop_indices[offset - 1]
                next_loop_index = loop_indices[(offset + 1) % loop_count]
                prev_vertex_index = mesh.loops[prev_loop_index].vertex_index
                next_vertex_index = mesh.loops[next_loop_index].vertex_index

                prev_edge = mesh.vertices[prev_vertex_index].co - vertex_co
                next_edge = mesh.vertices[next_vertex_index].co - vertex_co

                if prev_edge.length_squared == 0.0 or next_edge.length_squared == 0.0:
                    corner_angle = 0.0
                else:
                    corner_angle = prev_edge.angle(next_edge)

                shell_factor = self.calc_shell_dist(hq_normals[vertex_index], face_normal)
                vertex_angle_weights[vertex_index] += shell_factor * corner_angle
                vertex_angle_sums[vertex_index] += corner_angle

        source_vectors = []
        source_alpha = []
        for vertex_index, direction in enumerate(hq_normals):
            if vertex_angle_sums[vertex_index] > 1e-8:
                shell_factor = vertex_angle_weights[vertex_index] / vertex_angle_sums[vertex_index]
            else:
                shell_factor = 1.0

            shell_factor = max(1.0, shell_factor)
            shell_strength = max(0.0, min(1.0, 1.0 - (1.0 / shell_factor)))
            signed_strength = shell_strength * curvature_signs[vertex_index]
            alpha = 0.5 + signed_strength * 0.5

            source_vectors.append(direction.copy())
            source_alpha.append(max(1e-4, min(1.0, alpha)))

        return source_vectors, source_alpha

    def get_other_selected_mesh_object(self, context, active_obj):
        other_mesh_objects = [
            obj for obj in context.selected_objects if obj.type == "MESH" and obj != active_obj
        ]
        if len(other_mesh_objects) != 1:
            raise RuntimeError("该模式需要额外且仅额外选择一个拓扑一致的参考网格")
        return other_mesh_objects[0]

    def ensure_same_topology(self, mesh_a, mesh_b):
        if len(mesh_a.vertices) != len(mesh_b.vertices):
            raise RuntimeError("两个物体的顶点数量不一致")
        if len(mesh_a.edges) != len(mesh_b.edges):
            raise RuntimeError("两个物体的边数量不一致")
        if len(mesh_a.loops) != len(mesh_b.loops):
            raise RuntimeError("两个物体的面角数量不一致")
        if len(mesh_a.polygons) != len(mesh_b.polygons):
            raise RuntimeError("两个物体的面数量不一致")

        for polygon_index, (polygon_a, polygon_b) in enumerate(zip(mesh_a.polygons, mesh_b.polygons)):
            if polygon_a.loop_total != polygon_b.loop_total:
                raise RuntimeError(f"第 {polygon_index} 个面的边数不一致")

            verts_a = [mesh_a.loops[index].vertex_index for index in polygon_a.loop_indices]
            verts_b = [mesh_b.loops[index].vertex_index for index in polygon_b.loop_indices]
            if verts_a != verts_b:
                raise RuntimeError(f"第 {polygon_index} 个面的拓扑顺序不一致")

    def create_raw_reference_object(self, context, obj):
        mesh = obj.data
        custom_normals = [loop.normal.copy() for loop in mesh.loops]

        bpy.ops.mesh.customdata_custom_splitnormals_clear()

        raw_obj = obj.copy()
        raw_obj.data = obj.data.copy()
        raw_obj.name = obj.name + "_raw"
        context.collection.objects.link(raw_obj)

        mesh.normals_split_custom_set(custom_normals)
        return raw_obj

    def bake_normal(
        self,
        dst_obj,
        tbn_obj,
        normal_obj=None,
        use_vertex_normal=False,
        source_vectors=None,
        source_alpha=None,
    ):
        dst_mesh = dst_obj.data
        tbn_mesh = tbn_obj.data
        normal_mesh = normal_obj.data if normal_obj is not None else None

        dst_mesh.calc_tangents()
        tbn_mesh.calc_tangents()
        if normal_mesh is not None:
            normal_mesh.calc_tangents()

        color_attribute = get_active_corner_color_attribute(dst_mesh)
        color_data = color_attribute.data

        for polygon in dst_mesh.polygons:
            for loop_index in polygon.loop_indices:
                tbn_loop = tbn_mesh.loops[loop_index]
                tangent = tbn_loop.tangent
                bitangent = tbn_loop.bitangent
                normal = tbn_loop.normal

                if source_vectors is not None:
                    vertex_index = dst_mesh.loops[loop_index].vertex_index
                    source_normal = source_vectors[vertex_index]
                    alpha = source_alpha[vertex_index] if source_alpha is not None else 1.0
                else:
                    source_normal = self.get_source_normal(
                        normal_mesh,
                        loop_index,
                        use_vertex_normal,
                    )
                    alpha = 1.0

                encoded_normal = (
                    source_normal.dot(tangent) * 0.5 + 0.5,
                    source_normal.dot(bitangent) * 0.5 + 0.5,
                    source_normal.dot(normal) * 0.5 + 0.5,
                    alpha,
                )
                write_color_data(color_data[loop_index], encoded_normal)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        column = layout.column(align=True)
        for identifier, label, _description in MODE_ITEMS:
            column.prop_enum(self, "mode", identifier, text=label)
        if self.mode == "CUSTOM2RAW":
            layout.label(text="当前自定义法线到原始法线，需要确保有自定义法线")
        elif self.mode == "RAW2CUSTOM":
            layout.label(text="原始法线到当前自定义法线，需要确保有自定义法线")
            layout.label(text="Liltoon使用此法烘焙的顶点色RGB修正描边挤出方向")
        elif self.mode == "OBJECT2SMOOTH":
            layout.label(text="另一个物体自定义法线到当前物体自定义法线")
            layout.label(text="需要额外选择一个拓扑一致的参考网格")
        elif self.mode == "SOLIDIFY_RAW2CUSTOM":
            layout.label(text="RAW2CUSTOM的加强版")
            layout.label(text="如果你正在使用Liltoon描边RGBA修正，请使用它")
            layout.label(text="A通道以0.5为基准保存厚度补偿，可以得到连续锐利的边缘")


    def execute(self, context):
        active_obj = context.object
        if active_obj is None or active_obj.type != "MESH":
            self.report({"WARNING"}, "请先选择一个网格物体")
            return {"CANCELLED"}

        active_mesh = active_obj.data
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        raw_obj = None

        try:
            if self.mode == "RAW2CUSTOM":
                if not active_mesh.has_custom_normals:
                    self.report({"WARNING"}, "当前网格没有自定义法线")
                    return {"CANCELLED"}

                raw_obj = self.create_raw_reference_object(context, active_obj)
                self.bake_normal(
                    dst_obj=active_obj,
                    tbn_obj=active_obj,
                    normal_obj=raw_obj,
                    use_vertex_normal=True,
                )

            elif self.mode == "CUSTOM2RAW":
                if not active_mesh.has_custom_normals:
                    self.report({"WARNING"}, "当前网格没有自定义法线")
                    return {"CANCELLED"}

                raw_obj = self.create_raw_reference_object(context, active_obj)
                self.bake_normal(
                    dst_obj=active_obj,
                    tbn_obj=raw_obj,
                    normal_obj=active_obj,
                    use_vertex_normal=False,
                )

            elif self.mode == "SOLIDIFY_RAW2CUSTOM":
                source_vectors, source_alpha = self.build_even_solidify_source(active_mesh)
                self.bake_normal(
                    dst_obj=active_obj,
                    tbn_obj=active_obj,
                    source_vectors=source_vectors,
                    source_alpha=source_alpha,
                )

            else:
                source_obj = self.get_other_selected_mesh_object(context, active_obj)
                self.ensure_same_topology(active_mesh, source_obj.data)

                raw_obj = self.create_raw_reference_object(context, active_obj)
                self.bake_normal(
                    dst_obj=active_obj,
                    tbn_obj=raw_obj,
                    normal_obj=source_obj,
                    use_vertex_normal=True,
                )

        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            if raw_obj is not None:
                bpy.data.objects.remove(raw_obj, do_unlink=True)
            return {"CANCELLED"}

        if raw_obj is not None:
            bpy.data.objects.remove(raw_obj, do_unlink=True)

        return {"FINISHED"}


CLASSES = (HO_OT_bake_normal_to_vertex_color,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
