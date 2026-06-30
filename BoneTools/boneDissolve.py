import bpy
import numpy as np
import math
from bpy.types import Operator
from bpy.props import BoolProperty,IntProperty,FloatProperty

from .boneUtils import BoneUtils


def reg_props():
    return


def ureg_props():
    return

class DissolveBoneCore:
    @staticmethod
    def _ensure_object_visible(obj: bpy.types.Object):
        """临时解除物体隐藏，返回可恢复的隐藏状态。"""
        state = {
            "hide_viewport": obj.hide_viewport,
            "hide_get": obj.hide_get(),
        }

        if state["hide_viewport"]:
            obj.hide_viewport = False
        if state["hide_get"]:
            obj.hide_set(False)

        if state["hide_viewport"] or state["hide_get"]:
            bpy.context.view_layer.update()

        return state

    @staticmethod
    def _restore_object_visibility(obj: bpy.types.Object, state):
        if state["hide_get"]:
            obj.hide_set(True)
        if state["hide_viewport"]:
            obj.hide_viewport = True

        if state["hide_viewport"] or state["hide_get"]:
            bpy.context.view_layer.update()

    @staticmethod
    def resolve_bone_chain(edit_bones, bns):
        """校验选中骨骼是否为单条父子链，并返回从根到末端的有序骨名。"""
        bn_set = set(bns)
        missing = [bn for bn in bns if edit_bones.get(bn) is None]
        if missing:
            return [], f"找不到选中的骨骼: {missing}"

        roots = []
        for bn in bns:
            bone = edit_bones[bn]
            if bone.parent is None or bone.parent.name not in bn_set:
                roots.append(bn)

        if len(roots) != 1:
            return [], f"必须只选择一条连续骨链，当前找到 {len(roots)} 个最高父级骨骼: {roots}"

        chain = []
        current = edit_bones[roots[0]]
        while current and current.name in bn_set:
            chain.append(current.name)

            child_in_set = [child for child in current.children if child.name in bn_set]
            if len(child_in_set) > 1:
                names = [child.name for child in child_in_set]
                return [], f"骨链在 {current.name} 处分叉，子骨骼: {names}"

            current = child_in_set[0] if child_in_set else None

        if len(chain) != len(bn_set):
            disconnected = [bn for bn in bns if bn not in chain]
            return [], f"选中骨骼不是一条连续父子链，未连接骨骼: {disconnected}"

        return chain, None

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
        BoneUtils.set_object_mode(armature,'EDIT')

        edit_bones = armature.data.edit_bones
        # 按父子链首尾决定新骨段，不再按世界轴高低推断。
        root_bone = edit_bones.get(bns[0])
        tail_bone = edit_bones.get(bns[-1])
        if root_bone is None or tail_bone is None:
            raise Exception("融并骨链数据无效")

        #添加骨骼
        new_name = bns[0]+"_HoDissolved"
        new_bone = edit_bones.new(new_name)
        new_name = new_bone.name

        head = root_bone.head.copy()
        tail = tail_bone.tail.copy()
        parent = root_bone.parent

        # 收集所有原本连接到 bottom_bone 的子骨骼
        childrens = [b for b in edit_bones if b.parent and b.parent.name in bns and b.name not in bns]

        # 设置新骨骼的属性，以及修改原本最低子级骨骼的父级
        new_bone.head = head
        new_bone.tail = tail
        new_bone.parent = parent
        new_bone.roll = root_bone.roll#取最浅根骨的扭转

        for child in childrens:
            child.parent = new_bone
            continue

        #刷新并回到物体模式
        bpy.context.view_layer.objects.active = armature
        BoneUtils.set_object_mode(armature,'OBJECT')   
        if was_hidden:
            armature.hide_set(True)
        
        return new_name
    
    @staticmethod
    def obj_bone_dissolve(bns,tmp_bn,obj:bpy.types.Object):
        """处理单物体的权重融并"""
        visibility_state = DissolveBoneCore._ensure_object_visible(obj)
        old_active = bpy.context.view_layer.objects.active

        try:
            #切换模式
            if obj.visible_get():
                bpy.context.view_layer.objects.active = obj
                BoneUtils.set_object_mode(obj,'OBJECT')
            else:
                return False

            #新建/清空目标组
            if obj.vertex_groups.get(tmp_bn):
                obj.vertex_groups.remove(obj.vertex_groups.get(tmp_bn))
            new_vg = obj.vertex_groups.new(name=tmp_bn)

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
        finally:
            if old_active:
                try:
                    bpy.context.view_layer.objects.active = old_active
                except Exception:
                    pass
            DissolveBoneCore._restore_object_visibility(obj, visibility_state)

        return True
    

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
        BoneUtils.set_object_mode(armature,'EDIT')
        edit_bones = armature.data.edit_bones
        for bn in bns:
            edit_bones.remove(edit_bones.get(bn))
        #改新骨骼名称为原本根骨名称
        if root_bn and new_bn:
            edit_bones.get(new_bn).name = root_bn

        #刷新并回到物体模式
        bpy.context.view_layer.objects.active = armature
        BoneUtils.set_object_mode(armature,'OBJECT')   
           
        if was_hidden:
            armature.hide_set(True)

        return

class OP_DissolveBoneWithWeight(Operator):
    bl_idname = "ho.dissolvebone_withweight"
    bl_label = "融并骨骼与权重"
    bl_description = """
    将选中的连续父子骨链融并成一根骨骼，并同步合并权重。
    使用方式:在姿态模式或编辑模式选择两根以上连续骨骼，或在权重绘制时使用当前选中的骨骼。
            选中骨骼必须是一条单独父子链；如果出现多个最高父级、断链或分叉，会取消并提示错误。
            新骨从最浅父级骨骼的 head 延伸到最深子级骨骼的 tail，roll 使用最浅父级骨骼。
            所有被融并骨骼的顶点组权重会相加到新骨顶点组，然后删除旧顶点组和旧骨骼。
            隐藏网格会临时显示后处理并恢复隐藏；不在当前视图层的网格会跳过。"""
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
        BoneUtils.set_object_mode(armature_obj,'EDIT')

        edit_bones = armature_obj.data.edit_bones
        chain_bones, chain_error = DissolveBoneCore.resolve_bone_chain(edit_bones, bones)
        if chain_error:
            self.report({'ERROR'}, chain_error)
            return {'CANCELLED'}

        root = chain_bones[0]

        #创建新的骨骼
        new_bone_name = DissolveBoneCore.addNewBone(armature_obj,chain_bones)
        #逐物体合并骨骼权重
        for obj in mesh_objs:
            DissolveBoneCore.obj_bone_dissolve(chain_bones,new_bone_name,obj)
        #移除骨架中的原骨骼
        DissolveBoneCore.removeOldBones(armature_obj,chain_bones,root,new_bone_name)

        #还原原本的视图状态
        context.view_layer.objects.active = original_active
        BoneUtils.set_object_mode(original_active,mode=original_mode)
        if original_mode == 'WEIGHT_PAINT':
            armature_obj.select_set(True)
            bpy.context.view_layer.objects.active = armature_obj
            BoneUtils.set_object_mode(armature_obj,'POSE')
            original_active.select_set(True)
            bpy.context.view_layer.objects.active = original_active
            BoneUtils.set_object_mode(original_active,'WEIGHT_PAINT')
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
