import bmesh
import blf
import bpy
import gpu
from bpy.props import BoolProperty, EnumProperty, IntProperty
from bpy.types import Operator
from gpu_extras.batch import batch_for_shader
from mathutils import Vector


class OP_CreatBoneChainByMeshFlow(Operator):
    bl_idname = "ho.create_bone_chain_by_meshflow"
    bl_label = "根据选中的线段创建骨骼链"
    bl_options = {'REGISTER', 'UNDO'}

    num_segments: IntProperty(
        name="段数",
        default=4,
        min=1,
    )  # type: ignore

    direction_mode: EnumProperty(
        name="方向模式",
        items=[
            ('FORWARD', "正向", ""),
            ('REVERSE', "反向", ""),
            ('CURSOR', "指向游标", ""),
            ('CURSORMINUS', "远离游标", ""),
        ],
        default='FORWARD'
    )  # type: ignore

    auto_rename: bpy.props.BoolProperty(
        name="自动重命名",
        description="创建完成后自动联动hotools规则重命名",
        default=False
    )  # type: ignore

    # 获取所有连通 flow

    align_roll_to_normal: BoolProperty(
        name="扭转对齐法线",
        description="创建骨骼时让每段骨骼的扭转对齐到对应边的法线",
        default=True
    )  # type: ignore

    def get_edge_world_normal(self, normal_matrix, edge):
        normal_sum = Vector((0.0, 0.0, 0.0))

        for face in edge.link_faces:
            normal_sum += (normal_matrix @ face.normal).normalized()

        if normal_sum.length <= 1e-6:
            return None

        return normal_sum.normalized()

    def build_sampled_segment_normals(self, lengths, edge_normals, total_length):
        if not edge_normals or len(edge_normals) != len(lengths):
            return [None] * self.num_segments

        sampled_normals = []
        edge_ranges = []
        start = 0.0

        for length, normal in zip(lengths, edge_normals):
            edge_ranges.append((start, start + length, normal))
            start += length

        step = total_length / self.num_segments

        for index in range(self.num_segments):
            seg_start = index * step
            seg_end = total_length if index == self.num_segments - 1 else (index + 1) * step
            normal_sum = Vector((0.0, 0.0, 0.0))

            for edge_start, edge_end, edge_normal in edge_ranges:
                if edge_normal is None:
                    continue

                overlap = min(seg_end, edge_end) - max(seg_start, edge_start)
                if overlap > 1e-6:
                    normal_sum += edge_normal * overlap

            if normal_sum.length <= 1e-6:
                center = (seg_start + seg_end) * 0.5
                for edge_start, edge_end, edge_normal in edge_ranges:
                    if edge_normal is None:
                        continue
                    if edge_start - 1e-6 <= center <= edge_end + 1e-6:
                        normal_sum = edge_normal.copy()
                        break

            sampled_normals.append(
                normal_sum.normalized() if normal_sum.length > 1e-6 else None
            )

        return sampled_normals

    def get_roll_align_vector(self, head, tail, normal):
        axis = tail - head
        if axis.length <= 1e-6:
            return None

        axis.normalize()

        candidates = []
        if normal is not None and normal.length > 1e-6:
            candidates.append(normal)
        candidates.extend((
            Vector((0.0, 0.0, 1.0)),
            Vector((1.0, 0.0, 0.0)),
            Vector((0.0, 1.0, 0.0)),
        ))

        for candidate in candidates:
            projected = candidate - axis * axis.dot(candidate)
            if projected.length > 1e-6:
                return projected.normalized()

        return None

    def get_edge_flows(self, context):
        import bmesh
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)

        # 必须刷新，否则索引和选择状态可能不对
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        # 1. 获取当前所有选中的边
        selected_edges = [e for e in bm.edges if e.select]
        if not selected_edges:
            return None

        unvisited = set(selected_edges)
        world = obj.matrix_world
        normal_matrix = world.to_3x3().inverted().transposed()
        all_chains = []

        # 2. 提取选择历史中的边，作为排序种子
        # history 记录了用户点击的先后顺序
        seeds_from_history = []
        for elem in bm.select_history:
            if isinstance(elem, bmesh.types.BMEdge) and elem.select:
                if elem in unvisited:
                    seeds_from_history.append(elem)

        # 3. 构建完整的种子队列：历史种子 + 剩余选中的边
        seeds_queue = seeds_from_history + \
            [e for e in selected_edges if e not in set(seeds_from_history)]

        # 4. 开始按种子顺序遍历连通分支
        for start_edge in seeds_queue:
            if start_edge not in unvisited:
                continue

            # --- 寻找当前连通分支 (BFS) ---
            stack = [start_edge]
            component = {start_edge}
            unvisited.remove(start_edge)

            while stack:
                e = stack.pop()
                for v in e.verts:
                    for linked in v.link_edges:
                        if linked.select and linked in unvisited:
                            unvisited.remove(linked)
                            component.add(linked)
                            stack.append(linked)

            # --- 确定链条的逻辑顺序 ---
            # 计算分支内每个顶点的度
            vert_count = {}
            for e in component:
                for v in e.verts:
                    vert_count[v] = vert_count.get(v, 0) + 1

            # 找到端点（度为1的点）
            start_verts = [v for v, c in vert_count.items() if c == 1]

            is_closed = False
            if not start_verts:
                # 如果没有端点，说明是闭合环
                current_vert = start_edge.verts[0]
                is_closed = True
            else:
                # 如果是开链，选择离“种子边”最近的那个端点作为起点
                # 这样可以保证骨骼链的方向更符合用户点击时的直觉
                v1, v2 = start_verts[0], start_verts[-1]
                mid_seed = (start_edge.verts[0].co +
                            start_edge.verts[1].co) / 2
                if (v1.co - mid_seed).length <= (v2.co - mid_seed).length:
                    current_vert = v1
                else:
                    current_vert = v2

            # --- 按照拓扑顺序排列顶点 ---
            ordered_verts = [current_vert]
            ordered_edge_normals = []
            visited_edges_in_comp = set()

            while True:
                next_edge = None
                for e in current_vert.link_edges:
                    if e in component and e not in visited_edges_in_comp:
                        next_edge = e
                        break

                if not next_edge:
                    break

                visited_edges_in_comp.add(next_edge)
                ordered_edge_normals.append(
                    self.get_edge_world_normal(normal_matrix, next_edge)
                )
                # 移动到下一个顶点
                v_other = next_edge.other_vert(current_vert)
                current_vert = v_other
                ordered_verts.append(current_vert)

            # 转换为世界坐标
            chain_points = [world @ v.co.copy() for v in ordered_verts]

            if len(chain_points) > 1:
                all_chains.append({
                    "points": chain_points,
                    "edge_normals": ordered_edge_normals,
                    "is_closed": is_closed,
                })

        return all_chains

    def resample_chain(self, pts, edge_normals=None):

        if len(pts) < 2:
            return None

        lengths = []
        total = 0.0

        for i in range(len(pts) - 1):
            l = (pts[i + 1] - pts[i]).length
            lengths.append(l)
            total += l

        if total <= 1e-6:
            return None

        step = total / self.num_segments

        result = [pts[0]]
        accumulated = 0.0
        index = 0

        for i in range(1, self.num_segments):
            target = i * step

            while index < len(lengths) - 1 and accumulated + lengths[index] < target:
                accumulated += lengths[index]
                index += 1

            remain = target - accumulated
            direction = (pts[index + 1] - pts[index]).normalized()
            result.append(pts[index] + direction * remain)

        result.append(pts[-1])
        sampled_normals = self.build_sampled_segment_normals(
            lengths, edge_normals, total
        )
        return result, sampled_normals

    def apply_direction(self, chain, segment_normals=None):

        points = list(chain)
        normals = list(segment_normals) if segment_normals is not None else None

        if self.direction_mode == 'FORWARD':
            return (points, normals) if normals is not None else points

        if self.direction_mode == 'REVERSE':
            points.reverse()
            if normals is not None:
                normals.reverse()
            return (points, normals) if normals is not None else points

        if self.direction_mode == 'CURSOR':

            cursor = bpy.context.scene.cursor.location

            start = points[0]
            end = points[-1]

            d_start = (start - cursor).length
            d_end = (end - cursor).length

            if d_start > d_end:
                points.reverse()
                if normals is not None:
                    normals.reverse()

            return (points, normals) if normals is not None else points

        if self.direction_mode == 'CURSORMINUS':

            cursor = bpy.context.scene.cursor.location

            start = points[0]
            end = points[-1]

            d_start = (start - cursor).length
            d_end = (end - cursor).length

            if d_start < d_end:
                points.reverse()
                if normals is not None:
                    normals.reverse()

            return (points, normals) if normals is not None else points

        return (points, normals) if normals is not None else points

    def update_preview(self, context):

        self.preview_points = []

        for chain_data in self.base_chains:
            sampled = self.resample_chain(
                chain_data["points"],
                chain_data["edge_normals"],
            )
            if sampled:
                sampled_points, sampled_normals = sampled
                self.preview_points.append({
                    "points": sampled_points,
                    "segment_normals": sampled_normals,
                    "is_closed": chain_data["is_closed"],
                })

        context.area.tag_redraw()

    def draw_preview(self):

        if not self.preview_points:
            return

        shader = gpu.shader.from_builtin('SMOOTH_COLOR')
        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(4.0)

        rv3d = bpy.context.region_data
        if not rv3d:
            return

        view_dir = rv3d.view_rotation @ Vector((0, 0, -1))

        for preview_data in self.preview_points:

            points, segment_normals = self.apply_direction(
                preview_data["points"],
                preview_data["segment_normals"],
            )
            total = len(points) - 1
            if total <= 0:
                continue

            # ----- 线 -----
            coords = []
            colors = []

            for i in range(total):
                p1 = points[i]
                p2 = points[i + 1]

                t1 = i / total
                t2 = (i + 1) / total

                col1 = (t1, 1 - t1, 0.2, 1)
                col2 = (t2, 1 - t2, 0.2, 1)

                coords.extend([p1, p2])
                colors.extend([col1, col2])

            batch = batch_for_shader(shader, 'LINES', {
                "pos": coords,
                "color": colors,
            })

            shader.bind()
            batch.draw(shader)

            # ----- 箭头 -----
            arrow_coords = []
            arrow_colors = []

            for i in range(total):

                head = points[i]
                tail = points[i + 1]

                direction = (tail - head).normalized()
                length = (tail - head).length

                arrow_size = length * 0.25
                base = tail - direction * arrow_size

                side = direction.cross(view_dir)

                if side.length < 0.0001:
                    side = Vector((1, 0, 0))

                side.normalize()
                side *= arrow_size * 0.5

                left = base + side
                right = base - side

                t = (i + 1) / total
                col = (t, 1 - t, 0.2, 1)

                arrow_coords.extend([left, tail, right])
                arrow_colors.extend([col, col, col])

            arrow_batch = batch_for_shader(shader, 'TRIS', {
                "pos": arrow_coords,
                "color": arrow_colors,
            })

            arrow_batch.draw(shader)

            if self.align_roll_to_normal:
                z_axis_coords = []
                z_axis_colors = []

                for i in range(total):
                    head = points[i]
                    tail = points[i + 1]
                    segment_normal = segment_normals[i] if segment_normals else None
                    z_axis = self.get_roll_align_vector(head, tail, segment_normal)

                    if z_axis is None:
                        continue

                    mid = (head + tail) * 0.5
                    z_axis_length = (tail - head).length * 0.2
                    z_axis_end = mid + z_axis * z_axis_length
                    z_col = (0.2, 0.55, 1.0, 1.0)

                    z_axis_coords.extend([mid, z_axis_end])
                    z_axis_colors.extend([z_col, z_col])

                if z_axis_coords:
                    z_axis_batch = batch_for_shader(shader, 'LINES', {
                        "pos": z_axis_coords,
                        "color": z_axis_colors,
                    })
                    z_axis_batch.draw(shader)

        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')

    def draw_text(self):
        font_id = 0
        blf.size(font_id, 16)

        x = self.mouse_x + 20
        y = self.mouse_y + 20

        # ===== 开启阴影 =====
        blf.enable(font_id, blf.SHADOW)
        blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 0.6)
        blf.shadow_offset(font_id, 1, -1)

        key_text = "滚轮:"
        blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
        blf.position(font_id, x, y, 0)
        blf.draw(font_id, key_text)
        key_width, _ = blf.dimensions(font_id, key_text)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.position(font_id, x + key_width, y, 0)
        blf.draw(font_id, f"分段: {self.num_segments}")

        key_text = "F键:"
        blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
        blf.position(font_id, x, y + 22, 0)
        blf.draw(font_id, key_text)
        key_width, _ = blf.dimensions(font_id, key_text)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.position(font_id, x + key_width, y + 22, 0)
        blf.draw(font_id, f"方向模式: {self.direction_mode}")

        key_text = "R键:"
        blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
        blf.position(font_id, x, y + 44, 0)
        blf.draw(font_id, key_text)
        key_width, _ = blf.dimensions(font_id, key_text)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.position(font_id, x + key_width, y + 44, 0)
        blf.draw(font_id, f"联动重命名: {'开' if self.auto_rename else '关'}")

        key_text = "N键:"
        blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
        blf.position(font_id, x, y + 66, 0)
        blf.draw(font_id, key_text)
        key_width, _ = blf.dimensions(font_id, key_text)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.position(font_id, x + key_width, y + 66, 0)
        blf.draw(
            font_id,
            f"扭转对齐法线: {'开' if self.align_roll_to_normal else '关'}"
        )

    def modal(self, context, event):

        if event.type == 'MOUSEMOVE':
            self.mouse_x = event.mouse_region_x
            self.mouse_y = event.mouse_region_y
            context.area.tag_redraw()

        if event.type in {'ESC', 'RIGHTMOUSE'}:
            self.finish(context)
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.finish(context)
            self.create_bones(context)
            return {'FINISHED'}

        if event.type == 'WHEELUPMOUSE':
            self.num_segments += 1
            self.update_preview(context)

        if event.type == 'WHEELDOWNMOUSE':
            if self.num_segments > 1:
                self.num_segments -= 1
                self.update_preview(context)

        if event.type == 'F' and event.value == 'PRESS':
            modes = ['FORWARD', 'REVERSE', 'CURSOR', 'CURSORMINUS']
            i = modes.index(self.direction_mode)
            self.direction_mode = modes[(i + 1) % 4]
            context.area.tag_redraw()

        if event.type == 'R' and event.value == 'PRESS':
            self.auto_rename = not self.auto_rename
            context.area.tag_redraw()

        if event.type == 'N' and event.value == 'PRESS':
            self.align_roll_to_normal = not self.align_roll_to_normal
            context.area.tag_redraw()

        return {'RUNNING_MODAL'}

    def finish(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle_3d, 'WINDOW')
        bpy.types.SpaceView3D.draw_handler_remove(self._handle_text, 'WINDOW')
        context.area.tag_redraw()

    def create_bones(self, context):
        bpy.ops.object.mode_set(mode='OBJECT')

        arm_data = bpy.data.armatures.new("FlowArmature")
        arm_obj = bpy.data.objects.new("FlowArmature", arm_data)
        context.collection.objects.link(arm_obj)

        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='EDIT')

        # 用于存储所有新生成的骨骼名，保持创建顺序
        new_bone_names = []

        for chain_index, preview_data in enumerate(self.preview_points):
            points, segment_normals = self.apply_direction(
                preview_data["points"],
                preview_data["segment_normals"],
            )
            previous = None

            for i in range(len(points) - 1):
                bone_name = f"Flow_{chain_index}_{i}"
                bone = arm_data.edit_bones.new(bone_name)
                bone.head = points[i]
                bone.tail = points[i + 1]

                if self.align_roll_to_normal:
                    align_vector = self.get_roll_align_vector(
                        bone.head,
                        bone.tail,
                        segment_normals[i] if segment_normals else None,
                    )
                    if align_vector is not None:
                        bone.align_roll(align_vector)

                if previous:
                    bone.parent = previous
                    bone.use_connect = True

                previous = bone
                new_bone_names.append(bone.name)  # 记录顺序

        if self.auto_rename:
            # TODO:由于未知原因，5.1版本无法使用autorename功能
            arm_obj.data.show_names = True # TODO:由于未知原因，5.1-中show_names无法在模态中修改
            bpy.ops.armature.select_all(action='DESELECT')
            # 按照创建顺序（权重）选中骨骼
            for b_name in new_bone_names:
                eb = arm_data.edit_bones.get(b_name)
                if eb:
                    eb.select = True
            arm_data.edit_bones.active = arm_data.edit_bones[new_bone_names[0]]
            bpy.ops.ho.rename_rulerenameboneselected()
            bpy.ops.object.mode_set(mode='OBJECT')
        else:
            bpy.ops.object.mode_set(mode='OBJECT')

    def invoke(self, context, event):

        self.base_chains = self.get_edge_flows(context)

        if not self.base_chains:
            self.report({'WARNING'}, "请选择连续边")
            return {'CANCELLED'}

        self.mouse_x = event.mouse_region_x
        self.mouse_y = event.mouse_region_y

        self.update_preview(context)

        self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_preview, (), 'WINDOW', 'POST_VIEW'
        )

        self._handle_text = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_text, (), 'WINDOW', 'POST_PIXEL'
        )

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
