import bpy
import numpy as np
import math
from bpy.types import Operator
from bpy.props import BoolProperty,IntProperty,FloatProperty


def reg_props():
    return


def ureg_props():
    return

class DissolveBoneCore:
    @staticmethod
    def addNewBone(armature:bpy.types.Object,bns)->str:
        """添加一个新的骨骼（已经提前确认可以添加）"""
        #强制进入骨架编辑模式
        was_hidden = armature.hide_viewport
        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()  
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
        DissolveBoneCore.set_object_mode(armature,'EDIT')

        #添加骨骼
        edit_bones = armature.data.edit_bones
        new_name = bns[0]+"_HoDissolved"
        new_bone = edit_bones.new(new_name)
        new_name = new_bone.name

        #计算得到选择的骨骼中的最高父级与最低子级，以及新骨骼需要的属性
        b_bone = edit_bones[bns[0]]#0开缓存
        t_bone = edit_bones[bns[0]]#0开缓存
        for bn in bns:
            bone = edit_bones.get(bn)
            if bone is None:
                continue
            if bone.head[2] > b_bone.head[2]:
                b_bone = bone
            if bone.tail[2] < t_bone.tail[2]:
                t_bone = bone

        head = t_bone.head.copy()
        tail = b_bone.tail.copy()
        parent = b_bone.parent

        # 收集所有原本连接到 bottom_bone 的子骨骼
        childrens = [b for b in edit_bones if b.parent and b.parent.name in bns and b.name not in bns]

        # 设置新骨骼的属性，以及修改原本最低子级骨骼的父级
        new_bone.head = head
        new_bone.tail = tail
        new_bone.parent = parent
        new_bone.roll = b_bone.roll#取第一根骨的扭转

        for child in childrens:
            child.parent = new_bone
            continue

        #刷新并回到物体模式
        bpy.context.view_layer.objects.active = armature
        DissolveBoneCore.set_object_mode(armature,'OBJECT')   
        if was_hidden:
            armature.hide_set(True)
        
        return new_name
    
    @staticmethod
    def obj_bone_dissolve(bns,tmp_bn,obj:bpy.types.Object):
        """处理单物体的权重融并"""
        #新建/清空目标组
        if obj.vertex_groups.get(tmp_bn):
            obj.vertex_groups.remove(obj.vertex_groups.get(tmp_bn))
        new_vg = obj.vertex_groups.new(name=tmp_bn)

        #切换模式
        bpy.context.view_layer.objects.active = obj
        DissolveBoneCore.set_object_mode(obj,'OBJECT')  

        verts = obj.data.vertices
        N = len(verts)
        M = len(bns)

        #np矩阵处理
        W = np.zeros((N, M), dtype=float)
        P = np.zeros((N, M), dtype=bool)

        for j, group_name in enumerate(bns):
            vg = obj.vertex_groups.get(group_name)
            if not vg:
                continue
            # 对于每个顶点，尝试读取权重
            for i, v in enumerate(verts):
                try:
                    w = vg.weight(i)
                    # 只要没抛异常，就算“显式归属”，即便 w==0
                    P[i, j] = True
                except RuntimeError:
                    w = 0.0
                W[i, j] = w

        # 叠加和掩码
        merged = W.sum(axis=1)            # 合并后权重 (N,)
        has_explicit = P.any(axis=1)      # 哪些顶点显式属于至少一个旧组

        # 批量写入：只写那些 has_explicit 的顶点，写入它们的 merged 权重
        idxs = np.nonzero(has_explicit)[0]
        weights = merged[has_explicit]
        for i, w in zip(idxs, weights):
            new_vg.add([int(i)], float(w), 'REPLACE')

        # 删除旧组
        for old in bns:
            vg = obj.vertex_groups.get(old)
            if vg:
                obj.vertex_groups.remove(vg)
        return 
    

    @staticmethod
    def removeOldBones(armature:bpy.types.Object,bns,root_bn,new_bn):
        """删除旧骨骼并改新骨骼名"""
        #强制进入骨架编辑模式
        was_hidden = armature.hide_viewport
        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()  
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
        DissolveBoneCore.set_object_mode(armature,'EDIT')
        edit_bones = armature.data.edit_bones
        for bn in bns:
            edit_bones.remove(edit_bones.get(bn))
        #改新骨骼名称为原本根骨名称
        if root_bn and new_bn:
            edit_bones.get(new_bn).name = root_bn

        #刷新并回到物体模式
        bpy.context.view_layer.objects.active = armature
        DissolveBoneCore.set_object_mode(armature,'OBJECT')   
           
        if was_hidden:
            armature.hide_set(True)

        return
    
    @staticmethod  
    def set_object_mode(obj, mode):
        """暴力设置物体模式"""
        ctx = bpy.context
        view3d_ctx = bpy.context.copy()
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        view3d_ctx =  {
                            "area": area,
                            "region": region,
                            "window": bpy.context.window,
                            "screen": bpy.context.screen,
                            "active_object": obj,
                        }
        if "area" in view3d_ctx and "region" in view3d_ctx:
            if hasattr(ctx, "temp_override"):
                with ctx.temp_override(**view3d_ctx):
                    bpy.ops.object.mode_set(mode=mode)
            else:
                bpy.ops.object.mode_set(view3d_ctx, mode=mode)
        else:
            bpy.ops.object.mode_set(mode=mode)

class OP_DissolveBoneWithWeight(Operator):
    bl_idname = "ho.dissolvebone_withweight"
    bl_label = "融并骨骼与权重"
    bl_description = "！无法处理镜像骨骼！面板按钮较为卡顿,不建议长期展示"
    bl_options = {'REGISTER', 'UNDO'}

    only_selected:BoolProperty(name="仅选择的物体",description="未被选中的物体将保留权重，但是由于骨骼已经消失将不再受到控制", default=False) # type: ignore

    @classmethod
    def poll(cls, context):
        """保证选择的物体中找得到一个骨架并且选择了至少一个骨,判断逻辑与细分完全一致"""
        
        obj = context.active_object

        # 选择物体不是mesh物体/骨架，跳过
        if not obj or obj.type not in {'MESH', 'ARMATURE'}:
            return False

        #选择骨架时,没有选中骨骼，跳过
        if obj.type == 'ARMATURE':
            if obj.mode == 'POSE':
                return bool(context.selected_pose_bones)
            elif obj.mode == 'EDIT':
                return any(b.select for b in obj.data.edit_bones)
            else:
                return False
        
        #选择物体时（仅考虑多选了骨架并且在权重绘制模式的情况）
        else :            
            armature = None
            #找到活动物体的第一个骨架
            for mod in obj.modifiers:
                if mod.type == 'ARMATURE' and mod.object:
                    armature = mod.object
                    break
            #没找到骨架跳过
            if not armature:
                return False
            #活动组是骨架的骨权重时，说明有一个骨被选中了
            active_group = obj.vertex_groups.active
            if not active_group:
                return False
            for bone in armature.data.bones:
                if active_group.name == bone.name:
                    return True
            return False

    def execute(self, context):
        original_active = context.active_object
        original_mode = original_active.mode
        #得到待处理的对象
        armature_obj:bpy.types.Object = None #处理的骨架
        mesh_objs :list[bpy.types.Object]= [] #要处理的子级物体
        bones:list[str] = [] #选择的骨骼
            
        if original_active.type == 'ARMATURE':
            armature_obj = original_active
            if armature_obj.mode == 'POSE':
                bones = [bone.name for bone in context.selected_pose_bones]
            elif armature_obj.mode == 'EDIT':
                bones = [bone.name for bone in armature_obj.data.edit_bones if bone.select]
            #搜索所有子级物体
            for obj in bpy.data.objects:
                if obj.type != 'MESH':
                    continue
                for mod in obj.modifiers:
                    if mod.type == 'ARMATURE' and mod.object == armature_obj:
                        mesh_objs.append(obj)
                        break

        elif original_active.type == 'MESH':
            mesh_obj = original_active
            #找到选择物体的骨架
            for mod in mesh_obj.modifiers:
                if mod.type == 'ARMATURE' and mod.object:
                    armature_obj = mod.object
                    break
            #直接拿到选择的骨（必定权重绘制模式）
            bones = [bone.name for bone in context.selected_pose_bones]

            for obj in bpy.data.objects:
                if obj.type != 'MESH':
                    continue                
                for mod in obj.modifiers:
                    if mod.type == 'ARMATURE' and mod.object == armature_obj:
                        mesh_objs.append(obj)
                        break

        else:
            self.report({'ERROR'}, "不支持的对象")
            return {'CANCELLED'}
        #清洗处理列表
        if self.only_selected:
            tmp = []
            obj:bpy.types.Object
            for obj in mesh_objs:
                if obj.select_get():
                    tmp.append(obj)
            mesh_objs = tmp

        #检查选择的骨骼是否合乎融并的需求
        if len(bones)==1:
            self.report({'ERROR'}, "只有一个选中的骨骼")
            return {'CANCELLED'}
        bpy.context.view_layer.objects.active = armature_obj
        DissolveBoneCore.set_object_mode(armature_obj,'EDIT')

        edit_bones = armature_obj.data.edit_bones
        bn_set = set(bones)

        # 1) 必须有且仅有一个根
        roots = [
            bn for bn in bones
            if (edit_bones[bn].parent is None) or (edit_bones[bn].parent.name not in bn_set)
        ]
        if len(roots) != 1:
            self.report({'ERROR'}, f"必须只有一个骨骼的父级(parent)不在选集中，当前找到 {len(roots)} 个")
            return {'CANCELLED'}

        # 2) 每个非根骨骼必须 parent 在集合内
        root = roots[0]
        for bn in bones:
            if bn == root:
                continue
            pb = edit_bones[bn].parent
            # 只有当存在 parent 时，才必须在选集中
            if not pb or pb.name not in bn_set:
                self.report(
                   {'ERROR'},
                    f"非根骨骼 {bn} 的 parent 不在选中集合中：" +
                    (pb.name if pb else "无 parent")
                )
                return {'CANCELLED'}

        # 3) 不允许分叉：每个骨骼在集合内的子数 ≤ 1
        for bn in bones:
            child_in_set = [c for c in edit_bones[bn].children if c.name in bn_set]
            if len(child_in_set) > 1:
                names = [c.name for c in child_in_set]
                self.report({'ERROR'}, f"骨链在 “{bn}” 处分叉，子骨骼：{names}")
                return {'CANCELLED'}

        #创建新的骨骼
        new_bone_name = DissolveBoneCore.addNewBone(armature_obj,bones)
        #逐物体合并骨骼权重
        for obj in mesh_objs:
            DissolveBoneCore.obj_bone_dissolve(bones,new_bone_name,obj)
        #移除骨架中的原骨骼
        DissolveBoneCore.removeOldBones(armature_obj,bones,root,new_bone_name)        

        #还原原本的视图状态
        context.view_layer.objects.active = original_active
        DissolveBoneCore.set_object_mode(original_active,mode=original_mode)
        if original_mode == 'WEIGHT_PAINT':
            armature_obj.select_set(True)
            bpy.context.view_layer.objects.active = armature_obj
            DissolveBoneCore.set_object_mode(armature_obj,'POSE')
            original_active.select_set(True)
            bpy.context.view_layer.objects.active = original_active
            DissolveBoneCore.set_object_mode(original_active,'WEIGHT_PAINT')
        self.report({'INFO'},"融并成功")

    
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self,"only_selected")


cls = [
    OP_DissolveBoneWithWeight
]

def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()