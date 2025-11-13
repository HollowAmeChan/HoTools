import bpy
import numpy as np
import math
from bpy.types import Operator
from bpy.props import BoolProperty,IntProperty,FloatProperty


def reg_props():
    return


def ureg_props():
    return

class BoneSplitCore:
    @staticmethod
    def split_bone(armature:bpy.types.Object, bn, count)->list[str]:
        """处理骨骼的细分，返回细分产生的骨骼"""
        #保证骨架显示并为活动物体
        was_hidden = armature.hide_viewport
        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()  
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
        BoneSplitCore.set_object_mode(armature,'EDIT')


        edit_bones = armature.data.edit_bones
        old_bone = edit_bones.get(bn)
        if old_bone is None:
            if was_hidden:
                armature.hide_set(True)
            raise Exception(f"In Edit Mode: Bone '{bn}' not found.")
        corrected_points = [old_bone.head.lerp(old_bone.tail, i / count) for i in range(count + 1)]
                
        new_bones = []
        new_bone_names = []
        #逐一分配新骨的属性
        for i in range(1, count + 1):
            new_name = bn+"_" + str(i)
            new_bone = edit_bones.new(new_name)
            new_bone.head = corrected_points[i - 1].copy()
            new_bone.tail = corrected_points[i].copy()
            new_bone.roll = old_bone.roll
            #父级指定
            if i > 1:
                new_bone.parent = new_bones[i - 2]
            #收集输出
            new_bones.append(new_bone)
            new_bone_names.append(new_name)
        #处理原骨的头尾关系
        orig_parent = old_bone.parent
        if orig_parent:
            new_bones[0].parent = orig_parent
        for child in old_bone.children:
            child.parent = new_bones[-1]
        #移除原骨
        edit_bones.remove(old_bone)

        #刷新
        bpy.context.view_layer.objects.active = armature
        BoneSplitCore.set_object_mode(armature,'OBJECT')   
           
        if was_hidden:
            armature.hide_set(True)

        return new_bone_names
    @staticmethod
    def splitVertexGroup_withTmp(obj, new_bone_names, count, armature, tmp_vg,soft_factor):
        """利用缓存顶点组，计算细分的顶点组权重"""
        #缓存模式
        old_mode = obj.mode
        if old_mode == 'EDIT':
            bpy.context.view_layer.objects.active = obj
            BoneSplitCore.set_object_mode(obj,'OBJECT')
        #新建顶点组
        new_vgs :list[bpy.types.VertexGroup]= []
        for new_name in new_bone_names:
            vg :bpy.types.VertexGroup = obj.vertex_groups.new(name=new_name)
            new_vgs.append(vg)
        #计算首尾骨端点与距离
        mesh_inv = obj.matrix_world.inverted()
        arm_data = armature.data
        bone_first = arm_data.bones.get(new_bone_names[0])
        bone_last  = arm_data.bones.get(new_bone_names[-1])
        if not bone_first or not bone_last:
            raise Exception("New bones were not created correctly.")
        chain_start_world = armature.matrix_world @ bone_first.head_local
        chain_end_world   = armature.matrix_world @ bone_last.tail_local
        chain_start_local = mesh_inv @ chain_start_world
        chain_end_local   = mesh_inv @ chain_end_world
        chain_vec = chain_end_local - chain_start_local
        chain_len_sq = chain_vec.length_squared
        if chain_vec.length == 0:
            raise Exception("Bone chain has zero length.")
        N = len(obj.data.vertices)

        #构造顶点位置矩阵
        verts_np = np.array([list(v.co) for v in obj.data.vertices])
        weight_list = []
        for i in range(N):
            try:
                w = tmp_vg.weight(i)
            except RuntimeError:
                w = 0.0
            weight_list.append(w)
        #构造顶点权重矩阵
        weights_np = np.array(weight_list)
        #计算位置因子
        diff = verts_np - np.array(list(chain_start_local))
        chain_vec_np = np.array(list(chain_vec))
        f = np.dot(diff, chain_vec_np) / chain_len_sq
        f = np.clip(f, 0.0, 1.0)
        pos = f * count - 0.5  
        pos = np.clip(pos, 0, count - 1)
        i_seg = np.floor(pos).astype(int)
        local_factor = pos - i_seg
        
        
        #使用位置因子给顶点赋予新权重
        for i in range(N):
            orig_w = weights_np[i]
            seg = i_seg[i]
            lf = local_factor[i]

            if seg == count - 1:
                new_vgs[seg].add([i], orig_w, 'REPLACE')
            else: 
                #单独处理01值的柔化
                if soft_factor == 0.0:
                    blend = 0.0 if lf < 0.5 else 1.0
                elif soft_factor == 1.0:
                    blend = 0.5 * (1 - math.cos(math.pi * lf))
                else:
                    step_val = 0.0 if lf < 0.5 else 1.0
                    cos_val = 0.5 * (1 - math.cos(math.pi * lf))
                    blend = (1 - soft_factor) * step_val + soft_factor * cos_val

                blend = max(0.0, min(blend, 1.0))

                left_val = 1.0 - blend
                right_val = blend

                new_vgs[seg].add([i], orig_w * left_val, 'REPLACE')
                new_vgs[seg+1].add([i], orig_w * right_val, 'REPLACE')
        
        #给新组内部进行归一化(会破坏权重总值)
        # for i in range(N):
        #     total = 0.0
        #     for vg in new_vgs:
        #         try:
        #             total += vg.weight(i)
        #         except RuntimeError:
        #             continue
        #     if total > 0:
        #         for vg in new_vgs:
        #             try:
        #                 w = vg.weight(i)
        #                 vg.add([i], w / total, 'REPLACE')
        #             except RuntimeError:
        #                 continue
        #移除缓存组
        obj.vertex_groups.remove(tmp_vg)
        #还原模式
        if old_mode == 'EDIT':
            BoneSplitCore.set_object_mode(obj,'EDIT')
    @staticmethod    
    def objs_bone_split(bn, count, armature,soft_factor,objs):
        """处理骨架-骨骼-物体的细分"""

        #由于首个细分破坏了原有的结构，导致后续需要单独处理
        obj = objs[0]
        b_vg = obj.vertex_groups.get(bn)
        tmp_vg = "TMP_" + bn
        #创建临时权重组
        if obj.vertex_groups.get(tmp_vg):
            obj.vertex_groups.remove(obj.vertex_groups.get(tmp_vg))
        tmp_vg = obj.vertex_groups.new(name=tmp_vg)
        #临时权重组替换为源组权重
        for v in obj.data.vertices:
            try:
                w = b_vg.weight(v.index)
                tmp_vg.add([v.index], w, 'REPLACE')
            except RuntimeError:
                continue
        #移除源组（源组骨骼在细分后被移除）
        obj.vertex_groups.remove(b_vg)
        #细分骨骼并计算权重
        new_bone_names = BoneSplitCore.split_bone(armature, bn, count)#这句只在第一次有
        BoneSplitCore.splitVertexGroup_withTmp(obj, new_bone_names, count, armature, tmp_vg,soft_factor)
        
        #后续的操作为第一次的变体(少了细分骨骼)
        for obj in objs[1:]:
            b_vg = obj.vertex_groups.get(bn)
            tmp_vg = "TMP_" + bn
            if obj.vertex_groups.get(tmp_vg):
                obj.vertex_groups.remove(obj.vertex_groups.get(tmp_vg))
            tmp_vg = obj.vertex_groups.new(name=tmp_vg)
            for v in obj.data.vertices:
                try:
                    w = b_vg.weight(v.index)
                    tmp_vg.add([v.index], w, 'REPLACE')
                except RuntimeError:
                    continue
            obj.vertex_groups.remove(b_vg)
            BoneSplitCore.splitVertexGroup_withTmp(obj, new_bone_names, count, armature,tmp_vg,soft_factor)
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

class OP_SplitBoneWithWeight(Operator):
    bl_idname = "ho.splitbone_withweight"
    bl_label = "细分骨骼与权重"
    bl_description = "面板按钮较为卡顿,不建议长期展示"
    bl_options = {'REGISTER', 'UNDO'}

    count: IntProperty(name="细分段数",description="细分后产生的新骨骼数量", default=3, min=1) # type: ignore
    process_symmetry: BoolProperty(name="对称操作",description="同时对镜像的骨骼进行操作", default=False) # type: ignore
    only_selected:BoolProperty(name="仅选择的物体",description="未被选中的物体将保留权重，但是由于骨骼已经消失将不再受到控制", default=False) # type: ignore
    soft_factor:FloatProperty(name="过渡",description="细分小骨骼间的权重过渡,建议0.5以上",min=0.0,max=1.0,step=0.05,default=0.5) # type: ignore

    def get_mirrored_bone(self, bone_name, armature)->list[str]:
        """获取对称的骨骼,返回一个或一对骨骼"""
        names = [bone_name]
        symmetrical_name = bpy.utils.flip_name(bone_name)
        if symmetrical_name != bone_name and symmetrical_name in armature.bones:
            names.append(symmetrical_name)
        return names
    

    @classmethod
    def poll(cls, context):
        """保证选择的物体中找得到一个骨架并且选择了至少一个骨"""
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
        #没有待处理的物体
        if not mesh_objs:
            self.report({'ERROR'}, "没有找到需要处理的mesh对象,仅细分骨骼请勿使用")
            return {'CANCELLED'}

        #清洗处理列表
        if self.only_selected:
            tmp = []
            obj:bpy.types.Object
            for obj in mesh_objs:
                if obj.select_get():
                    tmp.append(obj)
            mesh_objs = tmp

        if self.process_symmetry:
            tmp = []
            for bone_name in bones:
                if self.process_symmetry:                    
                    tmp.extend(self.get_mirrored_bone(bone_name, armature_obj.data))
            bones = tmp
        #逐骨骼
        for bn in bones:
            #仅处理找得到这个权重的物体
            objs_withBone=[]
            for obj in mesh_objs:
                if obj.vertex_groups.get(bn):
                    objs_withBone.append(obj)
            #物体总处理
            BoneSplitCore.objs_bone_split(bn, self.count, armature_obj,self.soft_factor,objs_withBone)
        
        #还原原本的视图状态
        context.view_layer.objects.active = original_active
        BoneSplitCore.set_object_mode(original_active,mode=original_mode)
        if original_mode == 'WEIGHT_PAINT':
            armature_obj.select_set(True)
            bpy.context.view_layer.objects.active = armature_obj
            BoneSplitCore.set_object_mode(armature_obj,'POSE')
            original_active.select_set(True)
            bpy.context.view_layer.objects.active = original_active
            BoneSplitCore.set_object_mode(original_active,'WEIGHT_PAINT')
        self.report({'INFO'},"细分成功")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self,"count")
        layout.prop(self,"process_symmetry")
        layout.prop(self,"only_selected")
        layout.prop(self,"soft_factor")

cls = [
    OP_SplitBoneWithWeight
]

def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()