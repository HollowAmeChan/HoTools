import bpy
from mathutils import Vector
import numpy as np
from bpy.types import PropertyGroup, UIList, Operator, Panel
from bpy.types import UILayout, Context
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty,FloatProperty
from .boneSplit import OP_SplitBoneWithWeight
from .boneDissolve import OP_DissolveBoneWithWeight




class PG_Hotools_BoneProps(PropertyGroup):
    keepRotation: bpy.props.BoolProperty(
        name="保留旋转",
        description="在使用hotools fbx导出时,如果这段骨骼不保留旋转,将会自动将骨骼竖直，注意会导致这段骨骼后续的叶骨添加错误",
        default=True) # type: ignore
    endBone:bpy.props.BoolProperty(
        name="叶骨",
        description="Hotools是否将骨骼标记为叶骨",
        default=False) # type: ignore
    
def PF_armature_filter(self, obj):
    return obj.type == 'ARMATURE'

def reg_props():
    bpy.types.Scene.bone_constraint_resting_armature = PointerProperty(
        type=bpy.types.Object, poll=PF_armature_filter)
    bpy.types.Scene.bone_constraint_moving_armature = PointerProperty(
        type=bpy.types.Object, poll=PF_armature_filter)
    bpy.types.Bone.hotools_boneprops = bpy.props.PointerProperty(type=PG_Hotools_BoneProps)


def ureg_props():
    del bpy.types.Scene.bone_constraint_resting_armature
    del bpy.types.Scene.bone_constraint_moving_armature
    del bpy.types.Bone.hotools_boneprops


class OP_SameNameBone_addConstraint(Operator):
    bl_idname = "ho.samenamebone_addconstraint"
    bl_label = "同名骨添加约束"
    bl_description = "同名骨添加约束"
    constraint_type: bpy.props.StringProperty(
        name="Constraint Type", default="COPY_LOCATION")  # type: ignore

    def execute(self, context):
        scene = context.scene
        resting_armature = scene.bone_constraint_resting_armature
        moving_armature = scene.bone_constraint_moving_armature
        if not (resting_armature and moving_armature):
            self.report(
                {'WARNING'}, "需要指定两个骨架")
            return {'CANCELLED'}

        # 遍历目标骨架的每个骨骼，并在源骨架中查找同名的骨骼
        for moving_bone in moving_armature.pose.bones:
            resting_bone = resting_armature.pose.bones.get(moving_bone.name)

            if resting_bone:
                # 检查是否已有相同类型的约束，避免重复
                existing_constraints = [c for c in moving_bone.constraints if c.type ==
                                        self.constraint_type and c.subtarget == resting_bone.name]
                if not existing_constraints:
                    constraint = moving_bone.constraints.new(
                        self.constraint_type)
                    constraint.target = resting_armature
                    constraint.subtarget = resting_bone.name  # 直接使用目标骨骼的名称
                else:
                    print(
                        f"{moving_bone.name} 已经有 {self.constraint_type} 在 {resting_bone.name}")
            else:
                print(f"未找到骨骼： {moving_bone.name}")

        return {'FINISHED'}

class OP_BoneApplyConstraint(Operator):
    bl_idname = "ho.bone_apply_constraint"
    bl_label = "应用约束到骨骼"
    bl_description = "将选中骨骼的约束结果应用为当前姿态，并移除约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'ARMATURE' and
            context.mode == 'POSE'
        )

    def execute(self, context):
        obj = context.active_object
        pose_bones = context.selected_pose_bones

        if not pose_bones:
            self.report({'WARNING'}, "未选择任何骨骼")
            return {'CANCELLED'}

        # 确保在 Pose 模式
        bpy.ops.object.mode_set(mode='POSE')

        # 1. 应用视觉变换（约束结果）
        bpy.ops.pose.visual_transform_apply()

        # 2. 移除约束
        for pb in pose_bones:
            for c in reversed(pb.constraints):
                pb.constraints.remove(c)


        self.report({'INFO'}, f"已应用 {len(pose_bones)} 根骨骼的约束")
        return {'FINISHED'}
    


class OP_movingArmture_clear_constraint(Operator):
    bl_idname = "ho.movingarmture_clear_constraint"
    bl_label = "清空移动骨架中的所有约束"
    bl_description = "清空移动骨架中的所有约束"

    def execute(self, context):
        scene = context.scene
        moving_armature = scene.bone_constraint_moving_armature
        if not moving_armature:
            self.report({'WARNING'}, "需要指定移动骨架")
            return {'CANCELLED'}

        # 遍历目标骨架的每个骨骼，并删除所有指定类型的约束
        for moving_bone in moving_armature.pose.bones:
            # 直接删除目标骨骼上的所有指定类型的约束
            constraints_to_remove = [c for c in moving_bone.constraints]
            for constraint in constraints_to_remove:
                moving_bone.constraints.remove(constraint)
        return {'FINISHED'}

class OP_BoneRemoveConstraints(Operator):
    bl_idname = "ho.bone_remove_constraints"
    bl_label = "移除骨骼约束"
    bl_description = "移除选中骨骼上的全部约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'ARMATURE' and
            context.mode == 'POSE'
        )

    def execute(self, context):
        obj = context.active_object
        pose_bones = context.selected_pose_bones

        if not pose_bones:
            self.report({'WARNING'}, "未选择任何骨骼")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='POSE')

        for pb in pose_bones:
            if not pb.constraints:
                continue

            # 逐个移除约束（倒序，防炸）
            for c in reversed(pb.constraints):
                pb.constraints.remove(c)

        self.report({'INFO'}, "已移除选中骨骼的全部约束")
        return {'FINISHED'}
    
class OP_ApplyRestPose(Operator):
    bl_idname = "ho.apply_rest_pose"
    bl_label = "应用骨架与网格为当前姿势"
    bl_description = "与此同时会智能处理带形态键的绑定物体"
    bl_options = {'REGISTER', 'UNDO'}

    def draw(self, context):
        self.layout.label(text="本操作将应用骨架所有子级网格的全部'骨架'修改器")
        self.layout.label(text="同时应用掉现在的姿态为静置姿态")
        self.layout.label(text="如果子级网格物体有形态键，将会调用额外操作保证形态家的保留")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE'

    def process_object(self, context, obj):
        """智能处理单个物体"""

        # 检查是否需要特殊处理形态键
        needs_shapekey_processing = (
            obj.data.shape_keys and
            len(obj.data.shape_keys.key_blocks) > 1
        )

        # 如果有复杂形态键则使用新方法
        if needs_shapekey_processing:
            try:
                # 设置当前活动对象
                bpy.context.view_layer.objects.active = obj
                if obj.select_get() is False:
                    obj.select_set(True)

                # 调用形态键保留操作符
                bpy.ops.ho.apply_armature_modifiers_keepshapekeys()
                return True
            except Exception as e:
                self.report({'WARNING'}, f"形态键处理失败: {str(e)}")
                return False
        # 普通处理流程
        else:
            for mod in obj.modifiers[:]:
                if mod.type == 'ARMATURE' and mod.show_viewport:
                    try:
                        with bpy.context.temp_override(object=obj, modifier=mod):
                            bpy.ops.object.modifier_apply(modifier=mod.name)
                    except Exception as e:
                        self.report(
                            {'WARNING'}, f"应用失败: {obj.name} 的 {mod.name}")
                        continue
            return True

    def execute(self, context):

        armature = context.active_object
        original_mode = armature.mode

        # 获取所有绑定物体（包含间接子级）
        mesh_objects = [
            obj for obj in armature.children_recursive
            if obj.type == 'MESH' and
            any(m.type == 'ARMATURE' for m in obj.modifiers)
        ]
        # print(mesh_objects[:])

        if not mesh_objects:
            self.report({'WARNING'}, "没有找到绑定到该骨架的网格对象")
            return {'CANCELLED'}

        # 切换到 OBJECT 模式
        bpy.ops.object.mode_set(mode='OBJECT')

        # 处理所有网格物体
        success_count = 0
        for obj in mesh_objects:
            if self.process_object(context, obj):
                success_count += 1
                

        # 应用骨架姿态
        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode='POSE')
        bpy.ops.pose.armature_apply()
        bpy.ops.object.mode_set(mode=original_mode)

        # 再次获取绑定的物体(防止进行行改期应用过程中，有物体的变动的情况)#TODO 这里又不用看有没有骨架修改器了，一锅端不太好，但是没办法了
        mesh_objects = [
            obj for obj in armature.children_recursive if obj.type == 'MESH'
        ]

        # 重新添加骨架修改器
        for obj in mesh_objects:
            new_mod = obj.modifiers.new(
                name="Armature", type='ARMATURE')
            new_mod.object = armature
            print(obj.name,"恢复阶段成功")

        self.report({'INFO'}, "成功处理"+ str(success_count) + "/" + str(len(mesh_objects)) +"个物体")
        return {'FINISHED'}

class OP_ForceClearBoneRotation(Operator):
    bl_idname = "ho.force_clear_bone_rotation"
    bl_label = "强制骨骼变换"
    bl_description = "强制移除所选骨骼的变换,保证导出后旋转为0"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
       return True

    def execute(self, context):
        if bpy.context.mode != 'EDIT_ARMATURE':
            print("不在骨骼编辑模式下")
        else:
            armature = bpy.context.object.data
            armature.use_mirror_x = False #!!!必须关闭所有骨架的对称，否则处理会有底层逻辑上的问题
            selected_bones = [b for b in armature.edit_bones if b.select]

            for bone in selected_bones:
                for cb in bone.children:#清空所有子骨的相连，防止影响子骨头部位置
                    cb.use_connect = False
                original_length = (bone.tail - bone.head).length
                bone.roll = 0
                new_tail = bone.head + Vector((0, 0, original_length))
                bone.tail = new_tail
        return {'FINISHED'}
    
class MirrorBoneWeights:
    @staticmethod
    def objMirrorBoneWeights(obj:bpy.types.Object,bns,tolerance):
        #TODO 浮点数精度问题，匹配的不好
        #缓存模式
        old_mode = obj.mode
        if old_mode == 'EDIT':
            bpy.context.view_layer.objects.active = obj
            MirrorBoneWeights.set_object_mode(obj,'OBJECT')
             
        # 切到 Object 模式
        bpy.context.view_layer.objects.active = obj
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        
        # 1. 读取坐标到 NumPy
        verts = obj.data.vertices
        coords = np.array([v.co[:] for v in verts], dtype=np.float64)
        
        # 2. 量化
        q = np.rint(coords / tolerance).astype(np.int64)
        q2i = {tuple(qi): i for i, qi in enumerate(q)}
        
        for bone_name in bns:
            src = obj.vertex_groups.get(bone_name)
            if not src:
                continue
            # 推断镜像骨名
            def mirror_name(n:str):
                if n.endswith('.L'): return n[:-2] + '.R'
                if n.endswith('.R'): return n[:-2] + '.L'
                if n.endswith('.l'): return n[:-2] + '.r'
                if n.endswith('.r'): return n[:-2] + '.l'
                if n.endswith('_L'): return n[:-2] + '_R'
                if n.endswith('_R'): return n[:-2] + '_L'
                if n.endswith('_l'): return n[:-2] + '_r'
                if n.endswith('_r'): return n[:-2] + '_l'
                if n.startswith('Left'): return "Right" + n[4:]
                if n.startswith('Right'): return "Left" + n[4:]

                return None
            dst_name = mirror_name(bone_name)
            if not dst_name:
                continue
            dst = obj.vertex_groups.get(dst_name) 
            if not dst:
                dst = obj.vertex_groups.new(name=dst_name)
            
            # 清空目标组
            dst.remove([v.index for v in verts])
            
             # 批量写入权重
            for i, v in enumerate(verts):
                # 获取源组的权重，跳过不存在的顶点
                try:
                    w = src.weight(i)
                except RuntimeError:
                    continue

                # 计算量化后的镜像顶点索引
                qi = q[i].copy()
                qi[0] = -qi[0]
                mi = q2i.get(tuple(qi))
                # 跳过无对应或自身
                if mi is None or mi == i:
                    continue
                dst.add([mi], w, 'REPLACE')

        #还原模式
        if old_mode == 'EDIT':
            MirrorBoneWeights.set_object_mode(obj,'EDIT')
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

class OP_ForceMirrorBoneWeight(Operator):
    bl_idname = "ho.force_mirror_boneweight"
    bl_label = "覆盖对称骨权重"
    bl_description = "强制将选择的骨的权重对称到另一边，覆盖原骨骼，默认对所有骨架影响的物体操作"
    bl_options = {'REGISTER', 'UNDO'}

    only_selected:BoolProperty(name="仅选择的物体",description="未被选中的物体将不会生效", default=False) # type: ignore
    tolerance: FloatProperty(
            name="容差",
            default=0.001,
            min=0.000001,
            max=1.0
        ) # type: ignore

    @classmethod
    def poll(cls, context):
        """保证选择的物体中找得到一个骨架并且选择了至少一个骨，应用面为，骨架编辑模式/骨架姿态模式/有骨骼时的权重绘制模式"""
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
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self,"only_selected")
        layout.prop(self,"tolerance")

    def execute(self, context):
        original_active = context.active_object
        original_mode = original_active.mode

        #得到待处理的对象
        armature_obj:bpy.types.Object = None #处理的骨架
        mesh_objs :list[bpy.types.Object]= [] #要处理的子级物体
        bns:list[str] = [] #选择的骨骼
            
        if original_active.type == 'ARMATURE':
            armature_obj = original_active
            if armature_obj.mode == 'POSE':
                bns = [bone.name for bone in context.selected_pose_bones]
            elif armature_obj.mode == 'EDIT':
                bns = [bone.name for bone in armature_obj.data.edit_bones if bone.select]
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
            bns = [bone.name for bone in context.selected_pose_bones]

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

        #开始操作
        for obj in mesh_objs:
            MirrorBoneWeights.objMirrorBoneWeights(obj,bns,self.tolerance)


        #还原原本的视图状态
        context.view_layer.objects.active = original_active
        MirrorBoneWeights.set_object_mode(original_active,mode=original_mode)
        if original_mode == 'WEIGHT_PAINT':
            armature_obj.select_set(True)
            bpy.context.view_layer.objects.active = armature_obj
            MirrorBoneWeights.set_object_mode(armature_obj,'POSE')
            original_active.select_set(True)
            bpy.context.view_layer.objects.active = original_active
            MirrorBoneWeights.set_object_mode(original_active,'WEIGHT_PAINT')
        self.report({'INFO'},"对称成功")
        return {'FINISHED'}
        
class OP_AddEndBone(Operator):
    bl_idname = "ho.add_endbone"
    bl_label = "添加叶骨"
    bl_description = "给当前选中骨添加叶骨"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'ARMATURE'  and obj.mode == "EDIT" and context.active_bone is not None

    def execute(self, context):
        obj = context.object
        arm = obj.data
        ebones = arm.edit_bones

        selected_bones = [bone for bone in ebones if bone.select]
        end_bones = []
        for bone in selected_bones:
            end_bone_name = bone.name + "_end"
            if end_bone_name in ebones:
                self.report({'WARNING'}, f"{end_bone_name} 已存在，跳过")
                continue
            new_bone:bpy.types.EditBone  
            new_bone = ebones.new(end_bone_name)
            new_bone.head = bone.tail
            direction = (bone.tail - bone.head).normalized() if (bone.tail - bone.head).length > 0 else Vector((0, 0, 0.1))
            new_bone.tail = new_bone.head + direction * 0.1  # 可调长度
            new_bone.parent = bone
            new_bone.use_connect = True #相连项开
            new_bone.use_deform = False #形变关
            end_bones.append(new_bone.name)

        #刷新bones，再修改属性
        bpy.ops.object.mode_set(mode="OBJECT")
        for bn in end_bones:
            b = arm.bones[bn]
            b.hotools_boneprops.keepRotation = False
            b.hotools_boneprops.endBone = True
        bpy.ops.object.mode_set(mode="EDIT")

        return {'FINISHED'}

class OP_SelectBoneBy_by_KeepRotation(Operator):
    bl_idname = "ho.selectbone_by_keeprotation"
    bl_label = "选择相似骨骼-保留旋转"
    bl_description = "选择相似骨骼-按照Hotools骨骼keepRotation保留旋转属性"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_bone != None

    def execute(self, context):
        active_bone = context.active_bone
        bones = context.active_object.data.bones
        for bone in bones:
            if bone.hotools_boneprops.keepRotation == active_bone.hotools_boneprops.keepRotation:
                bone.select = True
        return {'FINISHED'}
    
class OP_SelectBone_by_endBone(Operator):
    bl_idname = "ho.selectbone_by_endbone"
    bl_label = "选择叶骨"
    bl_description = "选择所有的叶骨"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        arm_obj = context.object
        arm_data = arm_obj.data
        bones = arm_data.bones
        for b in bones:
            if b.hotools_boneprops.endBone:
                b.select = True

        return {'FINISHED'}

class OP_SelectBone_by_Nochild(Operator):
    bl_idname = "ho.selectbone_by_nochild"
    bl_label = "选择当前尾端骨"
    bl_description = "选择当前选中骨中的尾端骨"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_bone != None

    def execute(self, context):
        arm_obj = context.object
        arm_data = arm_obj.data
        bones = arm_data.bones
        end_bones = [eb for eb in bones if eb.select and len(eb.children) == 0]
        if not end_bones:
            self.report({'WARNING'}, "当前选中骨骼中没有末端骨")
            return {'CANCELLED'}
        for eb in bones:
            eb.select = False
        for eb in end_bones:
            eb.select = True
        arm_obj.data.bones.active = end_bones[0]
        return {'FINISHED'}

class OP_Fix_EmptyRotate_Bone(Operator):
    bl_idname = "ho.fix_empty_rotate_bone"
    bl_label = "修复空旋转的骨骼"
    bl_description = """另选中中骨骼的tail位置设定为子级骨骼的head位置(若有多个子级则设置为平均位置)
                        若没有子级则将tail位置设置在自己的父级与自己连线的延长线上(保持自己的骨骼长度)"""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_ARMATURE' and context.active_bone is not None

    def execute(self, context):
        armature = context.object.data
        armature.use_mirror_x = False  # 禁用对称，否则有同步问题

        selected_bones = [b for b in armature.edit_bones if b.select]

        for bone in selected_bones:
            children = [b for b in armature.edit_bones if b.parent == bone]
            
            if children:
                # 有子骨骼：取子骨骼 head 的平均值
                avg_head = Vector()
                for child in children:
                    avg_head += child.head
                avg_head /= len(children)
                bone.tail = avg_head
            elif bone.parent:
                # 没有子骨骼，有父骨骼：保持长度，延长方向
                direction = (bone.head - bone.parent.head).normalized()
                length = (bone.tail - bone.head).length
                bone.tail = bone.head + direction * length
            else:
                # 无父无子：默认方向向上的单位骨骼
                bone.tail = bone.head + Vector((0, 0.1, 0))

        return {'FINISHED'}

class PT_Hotools_PosebonePanel(Panel):
    bl_idname = "BONE_PT_Hotools_PoseBonePanel"
    bl_label = "HoTools骨骼"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "bone"                 # Bone 页签:contentReference[oaicite:6]{index=6}
    bl_options = {"DEFAULT_CLOSED"}     # 折叠:contentReference[oaicite:7]{index=7}

    @classmethod
    def poll(cls, context):
        return context.mode == "POSE"

    def draw(self, context):
        bone = context.active_bone
        layout = self.layout
        layout.prop(bone.hotools_boneprops, "keepRotation",toggle=False)
        layout.prop(bone.hotools_boneprops, "endBone",toggle=False)

def drawBoneOperatorsPanel(layout: UILayout, context: Context):
    scene = context.scene
     #细分骨骼
    row = layout.row(align=True)
    row.operator(OP_SplitBoneWithWeight.bl_idname,text="细分骨骼")
    row.operator(OP_DissolveBoneWithWeight.bl_idname,text="融并骨骼")
    #强制对称权重
    layout.operator(OP_ForceMirrorBoneWeight.bl_idname,text="所选骨骼权重对称到另一边")
    
    # 批量重命名选择和按钮
    layout.label(text="同名骨批量约束：")
    col = layout.column(align=True)
    col.prop_search(scene, "bone_constraint_resting_armature", scene,
                    "objects", text="固定骨架", icon="ARMATURE_DATA")
    col.prop_search(scene, "bone_constraint_moving_armature", scene,
                    "objects", text="移动骨架", icon="ARMATURE_DATA")
    # 映射约束
    col = layout.column(align=True)
    row = col.row(align=True)
    row.operator(
        OP_SameNameBone_addConstraint.bl_idname, text="约束-复制位置").constraint_type = 'COPY_LOCATION'
    row.operator(
        OP_SameNameBone_addConstraint.bl_idname, text="约束-复制旋转").constraint_type = 'COPY_ROTATION'
    row.operator(
        OP_movingArmture_clear_constraint.bl_idname, text="", icon="TRASH")
    
    row = layout.row(align=True)
    row.operator(OP_BoneApplyConstraint.bl_idname,text="应用约束到骨骼")
    row.operator(OP_BoneRemoveConstraints.bl_idname,text="移除骨骼约束")
    
   

def drawIn_VIEW3D_MT_edit_armature(self, context):
    layout: bpy.types.UILayout = self.layout
    layout.use_property_decorate = False  # 禁用关键帧动画
    """骨骼编辑模式下的顶菜单，骨架"""
    layout.operator(OP_ForceClearBoneRotation.bl_idname)
    layout.operator(OP_Fix_EmptyRotate_Bone.bl_idname)

def drawIn_VIEW3D_MT_select_edit_armature(self,context):
    layout: bpy.types.UILayout = self.layout
    layout.use_property_decorate = False  # 禁用关键帧动画
    """骨骼编辑模式下的顶菜单，选择"""
    layout.operator(OP_AddEndBone.bl_idname)

def drawIn_VIEW3D_MT_select_pose(self,context):
    layout: bpy.types.UILayout = self.layout
    layout.use_property_decorate = False  # 禁用关键帧动画
    """骨骼姿态模式下的顶菜单，选择"""
    layout.operator(OP_SelectBoneBy_by_KeepRotation.bl_idname)
    layout.operator(OP_SelectBone_by_Nochild.bl_idname)
    layout.operator(OP_SelectBone_by_endBone.bl_idname)

def drawIn_VIEW3D_MT_pose(self, context):
    layout: bpy.types.UILayout = self.layout
    layout.use_property_decorate = False  # 禁用关键帧动画
    """骨骼姿态模式下的顶菜单，姿态"""
    if context.active_object and context.active_object.type == 'ARMATURE':
        layout.operator(OP_ApplyRestPose.bl_idname)

cls = [
    OP_SameNameBone_addConstraint,
    OP_BoneApplyConstraint,
    OP_BoneRemoveConstraints,
    OP_movingArmture_clear_constraint, 
    OP_ApplyRestPose,
    OP_ForceClearBoneRotation,
    PG_Hotools_BoneProps,
    PT_Hotools_PosebonePanel,
    OP_SelectBoneBy_by_KeepRotation,
    OP_SelectBone_by_Nochild,
    OP_AddEndBone,
    OP_SelectBone_by_endBone,
    OP_ForceMirrorBoneWeight,
    OP_Fix_EmptyRotate_Bone,
]



def register():
    for i in cls:
        bpy.utils.register_class(i)

    bpy.types.VIEW3D_MT_pose.append(drawIn_VIEW3D_MT_pose)
    bpy.types.VIEW3D_MT_edit_armature.append(drawIn_VIEW3D_MT_edit_armature)
    bpy.types.VIEW3D_MT_select_pose.append(drawIn_VIEW3D_MT_select_pose)
    bpy.types.VIEW3D_MT_select_edit_armature.append(drawIn_VIEW3D_MT_select_edit_armature)

    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    bpy.types.VIEW3D_MT_pose.remove(drawIn_VIEW3D_MT_pose)
    bpy.types.VIEW3D_MT_edit_armature.remove(drawIn_VIEW3D_MT_edit_armature)
    bpy.types.VIEW3D_MT_select_pose.remove(drawIn_VIEW3D_MT_select_pose)
    bpy.types.VIEW3D_MT_select_edit_armature.remove(drawIn_VIEW3D_MT_select_edit_armature)

    ureg_props()
