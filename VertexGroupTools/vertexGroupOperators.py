import bpy
import bmesh
from mathutils.kdtree import KDTree
from bpy.types import PropertyGroup, UIList, Operator, Panel
from bpy.types import UILayout, Context
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, IntProperty, EnumProperty,FloatProperty
import json
import re
# TODO 对于在编辑模式中现场修改的数据，可能不能直接同步到obj.data中，下面都是两次切换模式刷新的，比较丑陋
# TODO 现在可以updatefromeditmode解决，有时间改改

def Updated_switch_only_activebone(self, context):
    """更新参数hoVertexGroupTools_switch_only_activebone调用"""
    switch_only_activebone = context.scene.hoVertexGroupTools_switch_only_activebone
    obj = context.active_object

    armature = None
    has_vg = False
    if len(obj.vertex_groups):
        has_vg = True

    for mod in obj.modifiers:
        if mod.type == 'ARMATURE':
            mod.show_on_cage = True
            mod.show_in_editmode = True
            armature = mod.object.data

    if switch_only_activebone == True and armature and has_vg:
        for bone in armature.bones:
            bone.hide = True

        if armature.bones.get(obj.vertex_groups.active.name):
            armature.bones.get(obj.vertex_groups.active.name).hide = False

    elif switch_only_activebone == False and armature and has_vg:
        for bone in armature.bones:
            bone.hide = False
    return 

def reg_props():
    bpy.types.Scene.hoVertexGroupTools_open_menu = BoolProperty(default=False)#启用属性下的操作菜单
    bpy.types.Scene.hoVertexGroupTools_remove_max = FloatProperty(
        name="最大值",
        description="顶点在此组中的权重，若小于等于这个值，则会被移除顶点组",
        default=0,
        min=0,
        max=1
    )
    bpy.types.Scene.hoVertexGroupTools_switch_only_activebone = BoolProperty(default=False,name="切换时独显骨骼",update=Updated_switch_only_activebone)
    bpy.types.Scene.hoVertexGroupTools_view_activevertex_weight = BoolProperty(default=False,name="显示活动顶点权重信息",description="很卡，不舒服自己关掉")

    bpy.types.Scene.hoVertexGroupTools_vg_increment1 = FloatProperty(name="权重增减量1",default=0.1,min=0,max=1)
    bpy.types.Scene.hoVertexGroupTools_vg_increment2 = FloatProperty(name="权重增减量2",default=0.05,min=0,max=1)
    bpy.types.Scene.hoVertexGroupTools_select_by_weightvalue = FloatProperty(name="选中权重小于",default=0.05,min=0,max=1)
    bpy.types.Scene.hoVertexGroupTools_max_vg_number = IntProperty(name="最多权重数",default=4)
    bpy.types.Scene.hoVertexGroupTools_isAutoNormalizeWeight = BoolProperty(name="Ho自动归一化",default=True,description="仅控制Hotools拓展中对权重的直接操作的是否自动归一化（不包括限制组、清除小于）")

def ureg_props():
    del bpy.types.Scene.hoVertexGroupTools_remove_max
    del bpy.types.Scene.hoVertexGroupTools_switch_only_activebone
    del bpy.types.Scene.hoVertexGroupTools_vg_increment1
    del bpy.types.Scene.hoVertexGroupTools_vg_increment2
    del bpy.types.Scene.hoVertexGroupTools_select_by_weightvalue
    del bpy.types.Scene.hoVertexGroupTools_max_vg_number
    del bpy.types.Scene.hoVertexGroupTools_view_activevertex_weight
    del bpy.types.Scene.hoVertexGroupTools_isAutoNormalizeWeight


class OP_VertexGroupTools_ExtractGroupValues_SelectedVertex(Operator):
    bl_idname = "ho.vertexgrouptools_extract_selectedvertex_groupvalues"
    bl_label = "复制权重"
    bl_description = "提取选中顶点的权重信息到剪切板，若多个顶点则会平均"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH' or obj.vertex_groups is None:
            self.report({'WARNING'}, "无效对象或对象无顶点组")
            return {'CANCELLED'}

         # 使用两次切换确保暂时修改的数据被应用
        if obj.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.mode_set(mode='EDIT')

        mesh = obj.data
        selected_verts = [v.index for v in mesh.vertices if v.select]

        if not selected_verts:
            self.report({'WARNING'}, "未选中任何顶点")
            return {'CANCELLED'}

        weight_dict = {}
        for vg in obj.vertex_groups:
            # 针对每个顶点，检查它是否在当前顶点组中，若不在则设置权重为0
            weights = []
            for v in selected_verts:
                group_found = False
                for g in mesh.vertices[v].groups:
                    if g.group == vg.index:
                        weights.append(g.weight)
                        group_found = True
                        break
                if not group_found:
                    weights.append(0)  # 默认权重为 0

            # 计算该顶点组的平均权重
            if weights:
                weight_dict[vg.name] = sum(weights) / len(weights)

        if not weight_dict:
            self.report({'WARNING'}, "选中的顶点无权重")
            return {'CANCELLED'}

        context.window_manager.clipboard = json.dumps(weight_dict)  # 直接存入剪贴板
        self.report({'INFO'}, "已复制权重信息")
        return {'FINISHED'}

class OP_VertexGroupTools_ApplyGroupValues_SelectedVertex(Operator):
    bl_idname = "ho.vertexgrouptools_applyt_selectedvertex_groupvalues"
    bl_label = "粘贴权重"
    bl_description = "从剪切板中粘贴权重信息到选中的顶点"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH' or obj.vertex_groups is None:
            self.report({'WARNING'}, "无效对象或对象无顶点组")
            return {'CANCELLED'}

        obj.update_from_editmode()
        mesh = obj.data
        selected_verts = [v.index for v in mesh.vertices if v.select]

        if not selected_verts:
            self.report({'WARNING'}, "未选中任何顶点")
            return {'CANCELLED'}

        clipboard_data = context.window_manager.clipboard
        if not clipboard_data:
            self.report({'WARNING'}, "剪贴板中无有效的权重数据")
            return {'CANCELLED'}

        try:
            weight_dict = json.loads(clipboard_data)
        except json.JSONDecodeError:
            self.report({'ERROR'}, "剪贴板中的数据无效")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='OBJECT')
        for vg_name, weight in weight_dict.items():
            vg = obj.vertex_groups.get(vg_name)
            if vg is None:
                vg = obj.vertex_groups.new(name=vg_name)

            for v in selected_verts:
                vg.add([v], weight, 'REPLACE')
        bpy.ops.object.mode_set(mode='EDIT')

        self.report({'INFO'}, "已粘贴权重信息")
        return {'FINISHED'}

class OP_VertexGroupTools_NormalizeGroupValues_SelectedVertex(Operator):
    bl_idname = "ho.vertexgrouptools_normalize_selectedvertex_groupvalues"
    bl_label = "规格化权重"
    bl_description = "规格化所选的所有顶点的骨骼权重（跳过锁定组，仅处理骨骼权重）"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH' or obj.vertex_groups is None:
            self.report({'WARNING'}, "无效对象或对象无顶点组")
            return {'CANCELLED'}

        # 切换模式确保顶点数据同步
        if obj.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')

        mesh = obj.data
        selected_verts = [v.index for v in mesh.vertices if v.select]

        if not selected_verts:
            self.report({'WARNING'}, "未选中任何顶点")
            bpy.ops.object.mode_set(mode='EDIT')
            return {'CANCELLED'}

        # 遍历顶点
        for v_idx in selected_verts:
            vert = mesh.vertices[v_idx]

            # 计算该顶点在骨骼且未锁定的顶点组中的总权重
            total_weight = 0.0
            valid_groups = []
            for g in vert.groups:
                vg = obj.vertex_groups[g.group]
                if vg.lock_weight:
                    continue  # 跳过锁定组
                # 这里假设骨骼顶点组的名字存在于对象的骨架中
                if context.object.find_armature() and vg.name not in context.object.find_armature().data.bones:
                    continue  # 跳过非骨骼顶点组
                total_weight += g.weight
                valid_groups.append((vg, g.weight))

            if total_weight == 0.0:
                continue  # 没有有效权重，跳过

            # 规范化权重
            for vg, weight in valid_groups:
                normalized_weight = weight / total_weight
                vg.add([v_idx], normalized_weight, 'REPLACE')

        bpy.ops.object.mode_set(mode='EDIT')
        self.report({'INFO'}, "所选顶点的骨骼权重已规格化（锁定组未动）")
        return {'FINISHED'}

class OP_VertexGroupTools_RemoveGroupVertex_by_value(Operator):
    bl_idname = "ho.vertexgrouptools_remove_group_vertex_byvalue"
    bl_label = "组中移除顶点"
    bl_description = "选中中的顶点，在所有顶点组中权重小于某值(0),此点将从那个顶点组中移除，跳过锁定组"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 确保在对象模式下应用修改
        if context.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.mode_set(mode='EDIT')

        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'WARNING'}, "请选中一个网格对象")
            return {'CANCELLED'}

        if not obj.vertex_groups:
            self.report({'WARNING'}, "对象没有顶点组")
            return {'CANCELLED'}

        threshold = context.scene.hoVertexGroupTools_remove_max

        removed_total = 0  # 统计总共移除的顶点数

        # 记录当前模式，并切换到对象模式
        prev_mode = obj.mode
        bpy.ops.object.mode_set(mode='OBJECT')

        # 遍历顶点组
        for vg in obj.vertex_groups:
            if vg.lock_weight:
                continue  # 跳过锁定的组

            if context.object.find_armature() and vg.name not in context.object.find_armature().data.bones:
                continue  # 跳过非骨骼顶点组

            verts_to_remove = []
            for vert in obj.data.vertices:
                if not vert.select:  # 跳过未选中定点
                    continue
                
                for g in vert.groups:
                    if g.group == vg.index and g.weight <= threshold:
                        verts_to_remove.append(vert.index)
                        break

            if verts_to_remove:
                vg.remove(verts_to_remove)
                removed_total += len(verts_to_remove)

        # 恢复原来的模式
        bpy.ops.object.mode_set(mode=prev_mode)

        self.report(
            {'INFO'}, f"移除了 {removed_total} 个权重小于 {threshold} 的顶点（所有非锁定组）"
        )
        return {'FINISHED'}

class OP_VertexGroupTools_RemoveEmptyVertexGroups(Operator):
    bl_idname = "ho.vertexgrouptools_remove_empty_vertex_groups"
    bl_label = "移除所有空组"
    bl_description = "移除所有选中物体的所有空组,跳过锁定组"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'OBJECT'

    def execute(self, context):
        original_active = context.view_layer.objects.active
        original_modes = {}

        # 保存所有选中物体的原始模式
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                original_modes[obj] = obj.mode

        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue

            context.view_layer.objects.active = obj
            if obj.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

            mesh = obj.data
            vgroups = obj.vertex_groups
            to_remove = []

            # 检查每个顶点组是否为空
            for vg in vgroups:
                vg_index = vg.index
                is_empty = True

                if vg.lock_weight:
                    continue  # 跳过锁定的组

                for v in mesh.vertices:
                    for g in v.groups:
                        if g.group == vg_index and g.weight > 0.0:
                            is_empty = False
                            break
                    if not is_empty:
                        break

                if is_empty:
                    to_remove.append(vg.index)

            # 从高到低删除索引，避免索引变化问题
            for index in sorted(to_remove, reverse=True):
                vgroups.remove(vgroups[index])

        # 恢复原始模式
        for obj, mode in original_modes.items():
            context.view_layer.objects.active = obj
            if obj.mode != mode:
                bpy.ops.object.mode_set(mode=mode)

        context.view_layer.objects.active = original_active

        return {'FINISHED'}

class OP_VertexGroupTools_BlendFromGroup(Operator):
    bl_idname = "ho.vertexgrouptools_blendfromgroup"
    bl_label = "权重从组混合"
    bl_description = "类似从形态键混合，将其他顶点组的所选顶点权重混合到当前组，可以指定模式"
    bl_options = {'REGISTER', 'UNDO'}

    group_name: StringProperty(
        name="源顶点组",
        default=""
    )  # type: ignore

    mode: EnumProperty(
        name="混合模式",
        items=[
            ('REPLACE', "替换", "完全替换目标组的权重"),
            ('ADD', "叠加", "将权重叠加到现有权重上"),
        ],
        default='REPLACE'
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def draw(self, context):
        layout = self.layout
        layout.prop_search(self, "group_name",
                           context.object, "vertex_groups",
                           text="来源组")
        layout.prop(self, "mode", expand=True)

    def invoke(self, context, event):
        # 自动设置默认源组为第一个非活动组
        groups = context.object.vertex_groups
        if groups and len(groups) > 1:
            active_group = groups.active
            for g in groups:
                if g != active_group:
                    self.group_name = g.name
                    break
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.active_object
        target_group = obj.vertex_groups.active

        # 参数有效性检查
        if not self.group_name:
            self.report({'ERROR'}, "必须选择源顶点组")
            return {'CANCELLED'}

        if not target_group:
            self.report({'ERROR'}, "没有活动组")
            return {'CANCELLED'}

        if self.group_name == target_group.name:
            self.report({'WARNING'}, "源和目标顶点组相同，操作已取消")
            return {'CANCELLED'}

        # 获取源顶点组
        try:
            source_group = obj.vertex_groups[self.group_name]
        except KeyError:
            self.report({'ERROR'}, f"找不到源顶点组：{self.group_name}")
            return {'CANCELLED'}

        # 检查当前模式（只能物体模式下修改）
        if obj.mode != 'OBJECT':
            # 如果不在物体模式，尝试切换到物体模式
            bpy.ops.object.mode_set(mode='OBJECT')

        # 优化：预先收集需要处理的数据
        selected_verts = [v.index for v in obj.data.vertices if v.select]
        total_processed = 0
        mode = self.mode

        # 批量操作提升性能
        for v_idx in selected_verts:
            try:
                src_weight = source_group.weight(v_idx)
            except RuntimeError:
                continue  # 跳过不在源组的顶点

            # 获取当前权重
            try:
                current_weight = target_group.weight(v_idx)
            except RuntimeError:
                current_weight = 0.0

            # 计算新权重
            if mode == 'REPLACE':
                new_weight = src_weight
            else:
                new_weight = min(current_weight + src_weight, 1.0)

            # 更新权重
            target_group.add([v_idx], new_weight, 'REPLACE')
            total_processed += 1

        # 切换回编辑模式
        bpy.ops.object.mode_set(mode='EDIT')
        self.report(
            {'INFO'}, f"成功处理 {total_processed}/{len(selected_verts)} 个顶点")
        return {'FINISHED'}

class OP_VertexGroupTools_mirror_to_other_group(Operator):
    """对称顶点组权重到对侧骨骼顶点组"""
    bl_idname = "ho.vertex_group_mirror_to_other"
    bl_label = "镜像权重到对侧组"
    bl_description = "处理选中顶点，将当前激活顶点组的权重镜像复制到另一侧的对应顶点组（例如 .L 到 .R），并激活目标组"
    bl_options = {'REGISTER', 'UNDO'}

    tolerance: FloatProperty(
        name="容差",
        default=0.001,
        min=0.0001,
        max=1.0
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def flip_group_name(self, name: str) -> str:
        patterns = [
            (r"\.l$", ".r"), (r"\.r$", ".l"),
            (r"\.L$", ".R"), (r"\.R$", ".L"),
            (r"_L$", "_R"), (r"_R$", "_L"),
            (r"Left", "Right"), (r"Right", "Left"),
            (r"left", "right"), (r"right", "left"),
            (r"LEFT", "RIGHT"), (r"RIGHT", "LEFT"),
        ]
        for pattern, replacement in patterns:
            if re.search(pattern, name):
                return re.sub(pattern, replacement, name)
        return name

    def execute(self, context):
        obj = context.active_object
        vg = obj.vertex_groups.active
        if not vg:
            self.report({'ERROR'}, "请先选择一个激活的顶点组")
            return {'CANCELLED'}

        target_group_name = self.flip_group_name(vg.name)
        if target_group_name == vg.name:
            self.report({'ERROR'}, "未检测到命名中的左右标识 (.L/_L/Left 等)")
            return {'CANCELLED'}

        if target_group_name not in obj.vertex_groups:
            obj.vertex_groups.new(name=target_group_name)

        target_vg = obj.vertex_groups[target_group_name]

        obj.update_from_editmode()
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.verts.ensure_lookup_table()

        coords = [v.co.copy() for v in bm.verts]
        kd = KDTree(len(coords))
        for i, co in enumerate(coords):
            kd.insert(co, i)
        kd.balance()

        deform_layer = bm.verts.layers.deform.verify()
        src_index = vg.index
        dst_index = target_vg.index

        to_write: list[tuple[int, float | None]] = []
        total = matched = skipped = not_found = 0

        for v in bm.verts:
            if not v.select:
                continue
            total += 1

            mirrored_co = v.co.copy()
            mirrored_co[0] *= -1
            hits = kd.find_range(mirrored_co, self.tolerance)
            if not hits:
                not_found += 1
                continue

            mirror_idx = hits[0][1]
            if mirror_idx == v.index:
                skipped += 1
                continue

            src_weights = v[deform_layer]
            if src_index in src_weights:
                to_write.append((mirror_idx, src_weights[src_index]))
            else:
                to_write.append((mirror_idx, None))
            matched += 1

        for idx, w in to_write:
            weights = bm.verts[idx][deform_layer]
            if w is not None:
                weights[dst_index] = w
            elif dst_index in weights:
                del weights[dst_index]

        bm.normal_update()
        bmesh.update_edit_mesh(mesh, loop_triangles=False)
        obj.update_from_editmode()

        obj.vertex_groups.active_index = target_vg.index

        self.report({'INFO'},
                    f"{vg.name} → {target_vg.name} | 处理 {total} 顶点，成功 {matched}，跳过 {skipped}，未找到 {not_found}")
        return {'FINISHED'}

class OP_VertexGroupTools_balanceVertexGroupWeight(Operator):
    """对称选中顶点的顶点组权重到 X 轴另一侧"""
    bl_idname = "ho.balance_vertex_group_weight"
    bl_label = "对称/翻转顶点组权重"
    bl_description = "仅处理选中的顶点,默认x轴向,全选进行翻转"
    bl_options = {'REGISTER', 'UNDO'}

    tolerance: FloatProperty(
        name="容差",
        default=0.001,
        min=0.0001,
        max=1.0
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.active_object
        vg = obj.vertex_groups.active
        if not vg:
            self.report({'ERROR'}, "请先选择一个激活的顶点组")
            return {'CANCELLED'}

        obj.update_from_editmode()
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.verts.ensure_lookup_table()

        coords = [v.co.copy() for v in bm.verts]
        kd = KDTree(len(coords))
        for i, co in enumerate(coords):
            kd.insert(co, i)
        kd.balance()

        deform_layer = bm.verts.layers.deform.verify()
        group_index = vg.index

        to_write: list[tuple[int, float | None]] = []
        total = matched = skipped = not_found = 0

        for v in bm.verts:
            if not v.select:
                continue
            total += 1

            src_idx = v.index
            target_co = coords[src_idx].copy()
            target_co[0] *= -1

            hits = kd.find_range(target_co, self.tolerance)
            if not hits:
                not_found += 1
                continue

            mirror_idx = hits[0][1]
            if mirror_idx == src_idx:
                skipped += 1
                continue

            src_weights = v[deform_layer]
            if group_index in src_weights:
                to_write.append((mirror_idx, src_weights[group_index]))
            else:
                to_write.append((mirror_idx, None))
            matched += 1

        for idx, w in to_write:
            weights = bm.verts[idx][deform_layer]
            if w is not None:
                weights[group_index] = w
            elif group_index in weights:
                del weights[group_index]

        bm.normal_update()
        bmesh.update_edit_mesh(mesh, loop_triangles=False)
        obj.update_from_editmode()

        self.report({'INFO'},
                    f"共 {total} 顶点 | 成功对称 {matched} | 未找到 {not_found} | 跳过 {skipped}")
        return {'FINISHED'}

class OP_VertexGroupTools_Switch_VG_byCursor(Operator):
    """切换到鼠标位置的骨骼/顶点组"""
    bl_idname = "ho.vertexgrouptools_switch_vg_bycursor"
    bl_label = "切换到鼠标位置的组/骨骼"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'MESH' and
            context.mode == 'EDIT_MESH'
        )

    def execute(self, context):
        obj = context.active_object
        only_activebone = context.scene.hoVertexGroupTools_switch_only_activebone
        rig = None
        for mod in obj.modifiers:
            if mod.type == 'ARMATURE' and mod.object:
                rig = mod.object

        # 强制寻找 VIEW_3D 区域
        for area in bpy.context.window.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        override = {
                            'window': bpy.context.window,
                            'screen': bpy.context.screen,
                            'area': area,
                            'region': region,
                        }
                        with bpy.context.temp_override(**override):
                            bpy.ops.view3d.cursor3d('INVOKE_DEFAULT')
                        break
                break
        else:
            self.report({'WARNING'}, "找不到 3D 视图区")
            return {'CANCELLED'}

        if rig:
            cursor_loc = context.scene.cursor.location.copy()
            min_distance = float('inf')
            active_bone = None

            for bone in rig.pose.bones:
                distance = (cursor_loc - bone.center).length
                if distance < min_distance and obj.vertex_groups.get(bone.name):
                    min_distance = distance
                    active_bone = bone.name

            if only_activebone:
                for bone in rig.data.bones:
                    bone.hide = True

            if active_bone:
                if obj.vertex_groups.get(active_bone):
                    obj.vertex_groups.active = obj.vertex_groups[active_bone]
                if rig.data.bones.get(active_bone):
                    rig.data.bones[active_bone].hide = False

        return {'FINISHED'}

class OP_VertexGroupTools_SoftWeight(Operator):
    bl_idname = "ho.vertexgrouptools_soft_weight"
    bl_label = "柔化权重"
    bl_description = "柔化所选的顶点的当前顶点组权重"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.edit_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)

        # 验证或创建 deform 层
        dvert_layer = bm.verts.layers.deform.verify()  # :contentReference[oaicite:0]{index=0}
        vg = obj.vertex_groups.active
        if not vg:
            self.report({'WARNING'}, "没有活跃的顶点组")
            return {'CANCELLED'}
        idx = vg.index

        # 对每个选中顶点，计算邻域平均值并赋予该顶点
        for v in bm.verts:
            if not v.select:
                continue
            # 原权重
            w = v[dvert_layer].get(idx, 0.0)
            # 收集邻居权重
            neigh_ws = []
            for e in v.link_edges:               # :contentReference[oaicite:1]{index=1}
                other = e.other_vert(v)
                neigh_ws.append(other[dvert_layer].get(idx, 0.0))
            if not neigh_ws:
                continue
            avg = sum(neigh_ws) / len(neigh_ws)
            # 赋值为邻域平均：柔化效果
            v[dvert_layer][idx] = avg

        #是否执行自动归一化
        if context.scene.hoVertexGroupTools_isAutoNormalizeWeight:
            bpy.ops.ho.vertexgrouptools_normalize_selectedvertex_groupvalues()


        bmesh.update_edit_mesh(me)
        return {'FINISHED'}

class OP_VertexGroupTools_SoftWeight_AllBone(Operator):
    bl_idname = "ho.vertexgrouptools_soft_weight_allbone"
    bl_label = "柔化骨骼顶点组权重"
    bl_description = "柔化所选顶点的全部骨骼顶点组权重"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.edit_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)

        # 验证或创建 deform 层
        dvert_layer = bm.verts.layers.deform.verify()

        # 找到骨骼绑定的顶点组
        arm = obj.find_armature()
        if not arm:
            self.report({'WARNING'}, "未找到绑定骨骼")
            return {'CANCELLED'}
        bone_vg_indices = {vg.index for vg in obj.vertex_groups if vg.name in arm.data.bones}
        if not bone_vg_indices:
            self.report({'WARNING'}, "没有匹配骨骼的顶点组")
            return {'CANCELLED'}

        # 获取所有选中顶点
        sel_verts = [v for v in bm.verts if v.select]
        if not sel_verts:
            self.report({'WARNING'}, "没有选中的顶点")
            return {'CANCELLED'}

        # 构建邻居索引列表
        neighbors = {v.index: [e.other_vert(v).index for e in v.link_edges] for v in sel_verts}

        # 构建权重矩阵，只包含骨骼顶点组
        weights = {}
        for v in sel_verts:
            w = {g: v[dvert_layer].get(g, 0.0) for g in bone_vg_indices}
            weights[v.index] = w

        # 新权重矩阵，计算邻居平均
        new_weights = {}
        for v in sel_verts:
            new_w = {}
            for g in bone_vg_indices:
                neigh_ws = [weights[n][g] for n in neighbors[v.index]]
                if neigh_ws:
                    avg = sum(neigh_ws) / len(neigh_ws)
                    new_w[g] = avg
                else:
                    new_w[g] = weights[v.index][g]  # 保留原权重
            new_weights[v.index] = new_w

        # 写回顶点权重
        for v in sel_verts:
            for g, w in new_weights[v.index].items():
                v[dvert_layer][g] = w

        # 自动归一化
        if getattr(context.scene, "hoVertexGroupTools_isAutoNormalizeWeight", False):
            bpy.ops.ho.vertexgrouptools_normalize_selectedvertex_groupvalues()

        bmesh.update_edit_mesh(me)
        return {'FINISHED'}
    
class OP_VertexGroupTools_SharpenWeight(Operator):
    #TODO 存在收缩出孤岛的问题
    bl_idname = "ho.vertexgrouptools_sharpen_weight"
    bl_label = "锐化权重"
    bl_description = "锐化所选的顶点的当前顶点组权重"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.edit_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)

        # 1. 获取 Deform 层和活跃顶点组索引
        dvert_layer = bm.verts.layers.deform.verify()  # 创建或获取 Deform 层 :contentReference[oaicite:2]{index=2}
        vg = obj.vertex_groups.active
        if vg is None:
            self.report({'WARNING'}, "没有活跃的顶点组")
            return {'CANCELLED'}
        idx = vg.index

        factor = 1.0  # 锐化强度，可改为属性

        # 2. 第一次遍历：计算所有选中顶点的新权重
        new_weights = {}
        for v in bm.verts:
            if not v.select:
                continue
            w = v[dvert_layer].get(idx, 0.0)
            # 收集邻域顶点权重
            neigh_ws = [
                e.other_vert(v)[dvert_layer].get(idx, 0.0)
                for e in v.link_edges
            ]
            if not neigh_ws:
                continue
            avg = sum(neigh_ws) / len(neigh_ws)
            # 锐化公式：放大偏差并 clamp 到 [0,1]
            w_new = max(0.0, min(1.0, w + (w - avg) * factor))
            new_weights[v] = w_new

        # 3. 第二次遍历：统一写回新权重
        for v, w_new in new_weights.items():
            v[dvert_layer][idx] = w_new

        #是否执行自动归一化
        if context.scene.hoVertexGroupTools_isAutoNormalizeWeight:
            bpy.ops.ho.vertexgrouptools_normalize_selectedvertex_groupvalues()
        # 4. 更新网格显示
        bmesh.update_edit_mesh(me)                   # 刷新编辑模式网格 :contentReference[oaicite:3]{index=3}

        return {'FINISHED'}

class OP_VertexGroupTools_SharpenWeight_AllBone(Operator):
    #TODO 存在收缩出孤岛的问题
    bl_idname = "ho.vertexgrouptools_sharpen_weight_allbone"
    bl_label = "锐化骨骼顶点组权重"
    bl_description = "锐化所选顶点的全部骨骼顶点组权重"
    bl_options = {'REGISTER', 'UNDO'}

    factor: bpy.props.FloatProperty(
        name="锐化强度",
        default=1.0,
        min=0.0,
        max=5.0,
        description="放大偏差的倍数"
    ) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.edit_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)

        dvert_layer = bm.verts.layers.deform.verify()

        # 找到骨骼绑定的顶点组
        arm = obj.find_armature()
        if not arm:
            self.report({'WARNING'}, "未找到绑定骨骼")
            return {'CANCELLED'}
        bone_vg_indices = {vg.index for vg in obj.vertex_groups if vg.name in arm.data.bones}
        if not bone_vg_indices:
            self.report({'WARNING'}, "没有匹配骨骼的顶点组")
            return {'CANCELLED'}

        # 选中顶点
        sel_verts = [v for v in bm.verts if v.select]
        if not sel_verts:
            self.report({'WARNING'}, "没有选中的顶点")
            return {'CANCELLED'}

        # 构建邻居索引列表
        neighbors = {v.index: [e.other_vert(v).index for e in v.link_edges] for v in sel_verts}

        # 构建权重矩阵
        weights = {}
        for v in sel_verts:
            w = {g: v[dvert_layer].get(g, 0.0) for g in bone_vg_indices}
            weights[v.index] = w

        # 计算锐化的新权重
        new_weights = {}
        for v in sel_verts:
            new_w = {}
            for g in bone_vg_indices:
                neigh_ws = [weights[n][g] for n in neighbors[v.index]]
                if neigh_ws:
                    avg = sum(neigh_ws) / len(neigh_ws)
                    w = weights[v.index][g]
                    w_new = max(0.0, min(1.0, w + (w - avg) * self.factor))
                    new_w[g] = w_new
                else:
                    new_w[g] = weights[v.index][g]
            new_weights[v.index] = new_w

        # 写回顶点权重
        for v in sel_verts:
            for g, w in new_weights[v.index].items():
                v[dvert_layer][g] = w

        # 自动归一化
        if getattr(context.scene, "hoVertexGroupTools_isAutoNormalizeWeight", False):
            bpy.ops.ho.vertexgrouptools_normalize_selectedvertex_groupvalues()

        bmesh.update_edit_mesh(me)
        return {'FINISHED'}

class OP_VertexGroupTools_Change_VG_weight(Operator):
    """改变顶点权重"""
    bl_idname = "ho.vertexgrouptools_change_vertexweight"
    bl_label = "改变顶点权重"
    bl_options = {'REGISTER', 'UNDO'}

    only_selected:BoolProperty(default=True) # type: ignore
    value:FloatProperty(default=0.1) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT' and obj.vertex_groups.active

    def execute(self, context):
        obj = context.active_object
        vg = obj.vertex_groups.active

        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        deform_layer = bm.verts.layers.deform.verify()

        for v in bm.verts:
            if self.only_selected and not v.select:
                continue

            d = v[deform_layer]
            current_weight = d.get(vg.index, 0.0)
            new_weight = current_weight + self.value

            if new_weight <= 0.0:
                # 移除该权重
                if vg.index in d:
                    del d[vg.index]
            else:
                d[vg.index] = min(new_weight, 1.0)

        #是否执行自动归一化
        if context.scene.hoVertexGroupTools_isAutoNormalizeWeight:
            bpy.ops.ho.vertexgrouptools_normalize_selectedvertex_groupvalues()
        bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}
            
class OP_VertexGroupTools_FloodFill_VG_weight(Operator):
    """漫延顶点权重"""
    bl_idname = "ho.vertexgrouptools_floodfill_vertexweight"
    bl_label = "漫延顶点权重"
    bl_options = {'REGISTER', 'UNDO'}

    only_selected: BoolProperty(default=True) # type: ignore
    value: FloatProperty(default=0.2, min=0.0, max=1.0) # type: ignore
    reverse: BoolProperty(
        name="反向传播",
        default=False,
        description="开启后将低权重向高权重传播"
    ) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT' and obj.vertex_groups.active

    def execute(self, context):
        obj = context.active_object
        vg = obj.vertex_groups.active

        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        vgroup_index = vg.index
        group_layer = bm.verts.layers.deform.verify()

        def get_weight(v):
            return v[group_layer].get(vgroup_index, 0.0)

        def set_weight(v, weight):
            v[group_layer][vgroup_index] = weight


        delta_total = 0.0
        new_weights = {}

        for v in bm.verts:
            if self.only_selected and not v.select:
                continue

            current_weight = get_weight(v)
            target_weight = current_weight

            for e in v.link_edges:
                other = e.other_vert(v)
                neighbor_weight = get_weight(other)

                # 判断传播方向
                if (not self.reverse and neighbor_weight > target_weight) or \
                    (self.reverse and neighbor_weight < target_weight):

                    delta = abs(neighbor_weight - current_weight) * self.value
                    target_weight = current_weight + delta if neighbor_weight > current_weight else current_weight - delta

            if abs(target_weight - current_weight) > 1e-6:
                new_weights[v.index] = target_weight
                delta_total += abs(target_weight - current_weight)
        for vidx, w in new_weights.items():
            set_weight(bm.verts[vidx], w)


        #是否执行自动归一化
        if context.scene.hoVertexGroupTools_isAutoNormalizeWeight:
            bpy.ops.ho.vertexgrouptools_normalize_selectedvertex_groupvalues()
        bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}

class OP_VertexGroupTools_Select_Vertices_halfside(Operator):
    """选择一半的网格"""
    bl_idname = "ho.vertexgrouptools_select_oneside"
    bl_label = "选择一半的网格"
    bl_options = {'REGISTER', 'UNDO'}

    reverse:BoolProperty(default=False,name="是否翻转(选择x-)") # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.active_object
        mesh = bmesh.from_edit_mesh(obj.data)
        # 取消所有顶点的选择
        for v in mesh.verts:
            v.select = False

        for v in mesh.verts:
            if not self.reverse:
                if v.co.x > 0.0001:
                    v.select = True
            else:
                if v.co.x < -0.0001:
                    v.select = True

        bmesh.update_edit_mesh(obj.data)
        obj.update_from_editmode()
        return {'FINISHED'}

class OP_VertexGroupTools_Select_Vertices_by_WeightValue(Operator):
    bl_idname = "ho.vertexgrouptools_select_by_weightvalue"
    bl_label = "选择小于"
    bl_description = "按阈值选择顶点"
    bl_options = {'REGISTER', 'UNDO'}

    value :FloatProperty(default=0.05) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT' and obj.vertex_groups.active is not None

    def execute(self, context):
        obj = context.active_object
        vg = obj.vertex_groups.active
        vg_index = vg.index

        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        deform_layer = bm.verts.layers.deform.verify()

        # 清除所有顶点的选择状态
        for v in bm.verts:
            v.select = False

        for v in bm.verts:
            d = v[deform_layer]
            if vg_index not in d:
                continue  # 跳过不在该组中的顶点

            weight = d[vg_index]
            if weight < self.value:
                v.select = True

        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        return {'FINISHED'}

class OP_VertexGroupTools_Max_VG_Limit(Operator):
    """限制顶点权重组数量"""
    bl_idname = "ho.vertexgrouptools_max_vg_limit"
    bl_label = "最多骨权重数"
    bl_options = {'REGISTER', 'UNDO'}

    num_max:IntProperty(default=4) # type: ignore
    
    @classmethod
    def poll(cls, context):
        return  True

    def execute(self, context):
        
        obj = context.active_object
        
        if not obj.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        if len(obj.vertex_groups):
            bpy.ops.object.vertex_group_limit_total(limit=self.num_max,group_select_mode='BONE_DEFORM')
        return {'FINISHED'}

class OP_SelectNonWeightVertices(Operator):
    """选择无骨骼权重的顶点"""
    bl_idname = "ho.vertexgrouptools_select_non_weight_vertices"
    bl_label = "选择无骨骼权重顶点"
    bl_description = "选择没有任何骨骼权重的顶点（忽略非骨骼组）"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'MESH' and
            context.mode == 'EDIT_MESH'
        )

    def execute(self, context):
        obj = context.active_object

        bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='VERT')

        arm = obj.find_armature()
        if not arm:
            self.report({'WARNING'}, "未找到绑定的骨架")
            return {'CANCELLED'}

        # 所有骨骼名称
        bone_names = {b.name for b in arm.data.bones}

        # 找到 mesh 中真正属于骨骼的 vertex group index
        bone_group_indices = {
            vg.index for vg in obj.vertex_groups
            if vg.name in bone_names
        }

        if not bone_group_indices:
            self.report({'WARNING'}, "未找到任何骨骼对应的顶点组")
            return {'CANCELLED'}

        bm = bmesh.from_edit_mesh(obj.data)
        deform_layer = bm.verts.layers.deform.verify()

        count = 0

        for v in bm.verts:
            dvert = v[deform_layer]

            has_bone_weight = False

            for group_index, weight in dvert.items():
                if group_index in bone_group_indices and weight > 0.0:
                    has_bone_weight = True
                    break

            if not has_bone_weight:
                v.select = True
                count += 1
            else:
                v.select = False

        bmesh.update_edit_mesh(obj.data)

        self.report({'INFO'}, f"已选择 {count} 个无骨骼权重顶点")
        return {'FINISHED'}

class OP_GenegateNoneMirroredGroup(Operator):
    """为没有镜像骨骼权重的顶点组生成镜像组"""
    bl_idname = "ho.vertexgrouptools_genegate_none_mirrored_group"
    bl_label = "生成镜像骨骼权重组"
    bl_description = "为没有镜像骨骼权重的顶点组生成镜像组，用于镜像修改器需要相应数据层的问题"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'MESH'
        )

    def execute(self, context):
        obj = context.active_object

        arm = obj.find_armature()
        if not arm:
            self.report({'WARNING'}, "未找到绑定的骨架")
            return {'CANCELLED'}

        bone_names = {b.name for b in arm.data.bones}

        # 现有顶点组名字
        existing_groups = {vg.name for vg in obj.vertex_groups}

        created_count = 0

        for bone_name in bone_names:

            # 只处理存在于mesh中的骨骼组
            if bone_name not in existing_groups:
                continue

            mirrored_name = bpy.utils.flip_name(bone_name)

            # 如果翻转后名字不同，且不存在，则创建
            if mirrored_name != bone_name and mirrored_name not in existing_groups:
                obj.vertex_groups.new(name=mirrored_name)
                created_count += 1

        if created_count == 0:
            self.report({'INFO'}, "没有需要生成的镜像顶点组")
        else:
            self.report({'INFO'}, f"已生成 {created_count} 个镜像顶点组")

        return {'FINISHED'}

class OP_RemoveNoneWeightGroup(Operator):
    """移除不是骨骼权重的顶点组"""
    bl_idname = "ho.vertexgrouptools_remove_none_weight_group"
    bl_label = "移除非骨骼权重组"
    bl_description = "移除所有不是骨骼权重的顶点组，使用前需要保证特殊用处的组处于锁定状态"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'MESH'
        )

    def invoke(self, context, event):
        # 弹出确认对话框
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.label(text="使用前检查功能用顶点组开启了锁定")
    def execute(self, context):
        obj = context.active_object

        arm = obj.find_armature()
        if not arm:
            self.report({'WARNING'}, "未找到绑定的骨架")
            return {'CANCELLED'}

        bone_names = {b.name for b in arm.data.bones}

        remove_count = 0

        # 收集需要删除的顶点组
        groups_to_remove = [
            vg for vg in obj.vertex_groups
            if vg.name not in bone_names and not vg.lock_weight
        ]

        for vg in groups_to_remove:
            obj.vertex_groups.remove(vg)
            remove_count += 1

        self.report({'INFO'}, f"已移除 {remove_count} 个非骨骼顶点组")
        return {'FINISHED'}

def draw_in_DATA_PT_vertex_groups(self, context: Context):
    """属性，数据-顶点组-(顶点组界面下部)"""
    scene = context.scene
    layout: bpy.types.UILayout = self.layout
    
    
    col = layout.column(align=True)
    col.prop(context.scene,"hoVertexGroupTools_view_activevertex_weight",text="活动顶点权重列表",toggle=True)
    col.prop(context.scene,"hoVertexGroupTools_open_menu",text="启用Hotools拓展",toggle=True)

    if context.scene.hoVertexGroupTools_view_activevertex_weight:
        # 活动顶点情况
        # 此办法比第二种快，只有在切换选择顶点的时候会卡
        obj = context.active_object
        if obj and obj.mode == 'EDIT' and len(obj.vertex_groups):
            box = layout.box()
            dic_v = []
            bm = bmesh.from_edit_mesh(obj.data)
            for v in bm.verts:
                if v.select:
                    dic_v.append(v.index)

            if len(dic_v) == 1:
                obj.update_from_editmode()
                v_grps = obj.data.vertices[dic_v[0]].groups
                o_grps = obj.vertex_groups
                for grp in o_grps:
                    for g in v_grps:
                        if g.group == grp.index:
                            row = box.row(align = True)
                            row.label(text= grp.name, translate=False)
                            row.label(text= f"{g.weight:.6f}", translate=False)
            else:
                box.label(text = '选择一个顶点')

        # obj = context.active_object
        # if obj and obj.mode == 'EDIT' and len(obj.vertex_groups):
        #     box = layout.box()
        #     obj.update_from_editmode()

        #     selected_indices = [v.index for v in obj.data.vertices if v.select]

        #     if len(selected_indices) == 1:
        #         v_grps = obj.data.vertices[selected_indices[0]].groups
        #         o_grps = obj.vertex_groups
        #         for grp in o_grps:
        #             for g in v_grps:
        #                 if g.group == grp.index:
        #                     row = box.row(align=True)
        #                     row.label(text=grp.name)
        #                     row.label(text=f"{g.weight:.6f}")
        #     else:
        #         box.label(text='选择一个顶点')
    if not context.scene.hoVertexGroupTools_open_menu:
        return
    
    row = layout.row(align=True)
    row.prop(scene, "hoVertexGroupTools_remove_max",
             icon_only=True, slider=True)
    row.operator(
        OP_VertexGroupTools_RemoveGroupVertex_by_value.bl_idname, text="从所有组中移除")

    row = layout.row(align=True)
    row.operator(OP_VertexGroupTools_ExtractGroupValues_SelectedVertex.bl_idname,
                 text="复制权重", icon="COPYDOWN")
    row.operator(OP_VertexGroupTools_ApplyGroupValues_SelectedVertex.bl_idname,
                 text="粘贴权重", icon="PASTEDOWN")
    
    col = layout.column(align=True)
    col.scale_y = 2.0
    row = col.row(align=True)
    row.prop(scene,"hoVertexGroupTools_isAutoNormalizeWeight",text="",icon="RECORD_ON",toggle=True)
    op = row.operator(OP_VertexGroupTools_Select_Vertices_halfside.bl_idname,text="左半")
    op.reverse = True
    op = row.operator(OP_VertexGroupTools_Select_Vertices_halfside.bl_idname,text="右半")
    op.reverse = False
    op2 = row.operator(OP_VertexGroupTools_Select_Vertices_by_WeightValue.bl_idname,text="选择小于")
    op2.value = scene.hoVertexGroupTools_select_by_weightvalue
    row.prop(scene,"hoVertexGroupTools_select_by_weightvalue",text="")

    row = col.row(align=True)
    op1 = row.operator(OP_VertexGroupTools_balanceVertexGroupWeight.bl_idname,text="组内翻转",icon="MOD_MIRROR")
    op2 = row.operator(OP_VertexGroupTools_mirror_to_other_group.bl_idname,text="同步到对称骨",icon="FUND")

    row = col.row(align=True)
    row.operator("object.vertex_group_remove_from", text="从组移除",
                 icon="CANCEL")
    row.operator(OP_VertexGroupTools_NormalizeGroupValues_SelectedVertex.bl_idname,
                 text="规格所选", icon="FUND")
    
    
    
    col = layout.column(align=True)
    col.scale_y = 2.0
    row = col.row(align=True)
    op1 = row.operator(OP_VertexGroupTools_Change_VG_weight.bl_idname,text="++")
    op1.value = scene.hoVertexGroupTools_vg_increment1
    op2 = row.operator(OP_VertexGroupTools_Change_VG_weight.bl_idname,text="--")
    op2.value = -scene.hoVertexGroupTools_vg_increment1
    row.prop(scene,"hoVertexGroupTools_vg_increment1",text="")
    row = col.row(align=True)
    op1 = row.operator(OP_VertexGroupTools_Change_VG_weight.bl_idname,text="+")
    op1.value = scene.hoVertexGroupTools_vg_increment2
    op2 = row.operator(OP_VertexGroupTools_Change_VG_weight.bl_idname,text="-")
    op2.value = -scene.hoVertexGroupTools_vg_increment2
    row.prop(scene,"hoVertexGroupTools_vg_increment2",text="")


    col = layout.column(align=True)
    col.scale_y = 2.0
    row = col.row(align=True)
    op1 = row.operator(OP_VertexGroupTools_FloodFill_VG_weight.bl_idname,text="膨胀")
    op1.reverse = False
    op2 = row.operator(OP_VertexGroupTools_FloodFill_VG_weight.bl_idname,text="侵蚀")
    op2.reverse = True
    row = col.row(align=True)
    row.operator(OP_VertexGroupTools_SoftWeight.bl_idname,text="柔化"
                    )
    row.operator(OP_VertexGroupTools_SharpenWeight.bl_idname,text="锐化"
                    )
    row = col.row(align=True)
    row.operator(OP_VertexGroupTools_SoftWeight_AllBone.bl_idname,text="柔化全部")   
    row.operator(OP_VertexGroupTools_SharpenWeight_AllBone.bl_idname,text="锐化全部")
    
    col = layout.column(align=True)
    col.scale_y = 2.0
    row = col.row(align=True)
    op1 = row.operator(OP_VertexGroupTools_Max_VG_Limit.bl_idname,text="限制顶点权重组数量"
                    )
    op1.num_max = scene.hoVertexGroupTools_max_vg_number
    row.scale_x = 0.5
    row.prop(scene,"hoVertexGroupTools_max_vg_number",text="",icon_only=True)

    
    #设置
    layout.label(text="参数设置:")
    layout.prop(scene,"hoVertexGroupTools_switch_only_activebone",text="切换时独显骨骼",toggle=True)
    row = layout.row(align=True)

    # #测试
    # row.template_list("UL_VertexGroup_AdvancedList", "",
    #                   obj,"vertex_groups",
    #                   obj.vertex_groups,"active_index",
    #                   rows=8)
    
def draw_in_MESH_MT_vertex_group_context_menu(self, context: Context):
    """属性，数据-顶点组-顶点组专用项-(顶点组下拉三角)"""
    layout: bpy.types.UILayout = self.layout
    layout.operator(OP_VertexGroupTools_RemoveEmptyVertexGroups.bl_idname,
                    icon="CANCEL")
    layout.operator(OP_SelectNonWeightVertices.bl_idname,text="选择无组顶点",icon="ERROR")
    layout.operator(OP_GenegateNoneMirroredGroup.bl_idname,text="生成镜像骨骼权重组",icon="MOD_MIRROR")
    layout.operator(OP_RemoveNoneWeightGroup.bl_idname,text="移除非骨骼权重组",icon="TRASH")

def draw_in_VIEW3D_MT_vertex_group(self, context: Context):
    """顶菜单，顶点-顶点组-(CtrlG展开菜单)"""
    layout: bpy.types.UILayout = self.layout
    layout.operator(OP_VertexGroupTools_BlendFromGroup.bl_idname)


cls = [
    OP_VertexGroupTools_RemoveGroupVertex_by_value,
    OP_VertexGroupTools_ExtractGroupValues_SelectedVertex, OP_VertexGroupTools_ApplyGroupValues_SelectedVertex,
    OP_VertexGroupTools_NormalizeGroupValues_SelectedVertex, OP_VertexGroupTools_RemoveEmptyVertexGroups,
    OP_VertexGroupTools_BlendFromGroup,OP_VertexGroupTools_balanceVertexGroupWeight,OP_VertexGroupTools_mirror_to_other_group,
    OP_VertexGroupTools_SoftWeight,OP_VertexGroupTools_SharpenWeight,
    OP_VertexGroupTools_Switch_VG_byCursor,
    OP_VertexGroupTools_Change_VG_weight,OP_VertexGroupTools_FloodFill_VG_weight,
    OP_VertexGroupTools_Select_Vertices_halfside,OP_VertexGroupTools_Select_Vertices_by_WeightValue,
    OP_VertexGroupTools_Max_VG_Limit,
    OP_SelectNonWeightVertices,
    OP_GenegateNoneMirroredGroup,
    OP_RemoveNoneWeightGroup,
    OP_VertexGroupTools_SoftWeight_AllBone,OP_VertexGroupTools_SharpenWeight_AllBone
]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()
    bpy.types.DATA_PT_vertex_groups.append(draw_in_DATA_PT_vertex_groups)
    bpy.types.MESH_MT_vertex_group_context_menu.append(
        draw_in_MESH_MT_vertex_group_context_menu)
    bpy.types.VIEW3D_MT_vertex_group.append(
        draw_in_VIEW3D_MT_vertex_group)
    
    # OP_Switch_VG_byCursor默认绑定 alt+ 右键
    km = bpy.context.window_manager.keyconfigs.addon.keymaps.new(name="Window", space_type="EMPTY", region_type="WINDOW")
    km.keymap_items.new(OP_VertexGroupTools_Switch_VG_byCursor.bl_idname,type='RIGHTMOUSE', value='PRESS', alt=True)


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
    bpy.types.DATA_PT_vertex_groups.remove(draw_in_DATA_PT_vertex_groups)
    bpy.types.MESH_MT_vertex_group_context_menu.remove(
        draw_in_MESH_MT_vertex_group_context_menu)
    bpy.types.VIEW3D_MT_vertex_group.remove(
        draw_in_VIEW3D_MT_vertex_group)

 # type: ignore
