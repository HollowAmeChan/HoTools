import bpy
from bpy.types import Operator,Panel,Menu
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty,FloatVectorProperty
import bmesh
from collections import defaultdict
from mathutils import Vector

def reg_props():

    return


def ureg_props():
    return

class OP_Checker_getActiveVertexIndex(Operator):
    bl_idname = "ho.checker_get_activevertex_index"
    bl_label = "选择点"
    bl_description = "填入活动顶点index"
    bl_options = {'REGISTER', 'UNDO'}

    is_target:BoolProperty(default=False) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        bm = bmesh.from_edit_mesh(obj.data)
        if self.is_target:
            context.scene.ho_mirrorchecker_target_vertex_index = bm.select_history.active.index
        else:
            context.scene.ho_mirrorchecker_base_vertex_index = bm.select_history.active.index
        return {'FINISHED'}
    
class OP_Checker_swapMirrorVertexIndex(Operator):
    bl_idname = "ho.checker_swap_mirrorvertex_index"
    bl_label = "交换"
    bl_description = "交换index"
    bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        t = context.scene.ho_mirrorchecker_target_vertex_index
        context.scene.ho_mirrorchecker_target_vertex_index =  context.scene.ho_mirrorchecker_base_vertex_index
        context.scene.ho_mirrorchecker_base_vertex_index = t
        return {'FINISHED'}

class OP_Checker_forceVertexMirror(Operator):
    bl_idname = "ho.checker_force_vertex_mirror"
    bl_label = "点强制对称"
    bl_description = "点强制对称"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        baseV_index = context.scene.ho_mirrorchecker_base_vertex_index
        targetV_index = context.scene.ho_mirrorchecker_target_vertex_index
        mirrorAxis = context.scene.ho_MirrorCheckerAxis
        
        if baseV_index >= len(bm.verts) or targetV_index >= len(bm.verts):
            self.report({'ERROR'}, "顶点索引超出范围")
            return {'CANCELLED'}

        base = bm.verts[baseV_index]
        target = bm.verts[targetV_index]

        x,y,z = base.co.x, base.co.y, base.co.z

        if mirrorAxis == "X":
            target.co = (-x, y, z)
        elif mirrorAxis == "Y":
            target.co = (x, -y, z)
        elif mirrorAxis == "Z":
            target.co = (x, y, -z)
        bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}
    
class OP_Checker_AutoForceVertexMirror(Operator):
    bl_idname = "ho.checker_auto_force_vertex_mirror"
    bl_label = "自动对称"
    bl_description = "自动对称mesh,需要注意会改变选中物体的对称模式(对齐到ho操作轴)"
    bl_options = {'REGISTER', 'UNDO'}

    isonlyselect:BoolProperty(description="仅检查选中顶点",default=True) # type: ignore
    checkuv_tolerance:FloatProperty(description="UV容差",default=0.00000001) # type: ignore
    topu_ischeck:BoolProperty(description="检查拓补",default=False) # type: ignore
    mirroruv_ischeck:BoolProperty(description="检查镜像UV",default=True) # type: ignore
    stackuv_ischeck:BoolProperty(description="检查重叠UV",default=True) # type: ignore
    swapsign:BoolProperty(description="翻转正负轴",default=False) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'



    def calc_avg_uv(self, obj):
        """返回 { vert_index : (avg_uv, count) }"""
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        uv_layer = bm.loops.layers.uv.active
        if not uv_layer:
            bm.free()
            return None

        uv_acc = defaultdict(lambda:[0.0,0.0,0])
        for f in bm.faces:
            for l in f.loops:
                i = l.vert.index
                uv = l[uv_layer].uv
                uv_acc[i][0]+=uv.x; uv_acc[i][1]+=uv.y; uv_acc[i][2]+=1

        uv_map = {
            i: (Vector((d[0]/d[2], d[1]/d[2])), d[2])  # ★ 返回UV与使用次数
            for i,d in uv_acc.items()
        }

        bm.free()
        return uv_map

    def find_uv_match(self, vert_index, target, uv_map, tolerance):
        """以距离与loop数量完全一致为前提匹配"""
        t_uv,t_cnt = target
        nearest = None
        nearest_dist = float('inf')

        for idx,(uv,cnt) in uv_map.items():
            if idx == vert_index:
                continue
            
            # ★ 必须loop计数相同，否则不作为候选
            if cnt != t_cnt:
                continue

            d = (uv - t_uv).length
            if d < tolerance and d < nearest_dist:
                nearest = idx
                nearest_dist = d

        return [nearest] if nearest is not None else []

    def fix_pos(self,v1,v2,mirror_axis="X",tolerance=0.00000001,swapsign=False):
        left =None
        right = None
        if mirror_axis=="X":
            if v1.co.x < v2.co.x:
                left = v1
                right = v2
            else:
                left = v2
                right = v1
            if right.co.x<=tolerance:return#剔除非常靠近轴的点
            if swapsign:
                t = right
                right = left
                left = t
            right.co.x = -left.co.x
            right.co.y = left.co.y
            right.co.z = left.co.z

        if mirror_axis=="Y":
            if v1.co.y < v2.co.y:
                left = v1
                right = v2
            else:
                left = v2
                right = v1
            if right.co.y<=tolerance:return#剔除非常靠近轴的点
            if swapsign:
                t = right
                right = left
                left = t
            right.co.x = left.co.x
            right.co.y = -left.co.y
            right.co.z = left.co.z

        if mirror_axis=="Z":
            if v1.co.z < v2.co.z:
                left = v1
                right = v2
            else:
                left = v2
                right = v1
            if right.co.z<=tolerance:return#剔除非常靠近轴的点
            if swapsign:
                t = right
                right = left
                left = t
            right.co.x = left.co.x
            right.co.y = left.co.y
            right.co.z = -left.co.z
        return
    
    def execute(self, context):
        scene = context.scene
        obj = context.active_object
        mesh = obj.data
        mirror_axis = scene.ho_MirrorCheckerAxis
        #对齐内部镜像轴向与ho镜像轴,记录旧的拓补检查状态
        if mirror_axis=="X":
            obj.use_mesh_mirror_x = True
            obj.use_mesh_mirror_y = False
            obj.use_mesh_mirror_z = False
        if mirror_axis=="Y":
            obj.use_mesh_mirror_x = False
            obj.use_mesh_mirror_y = True
            obj.use_mesh_mirror_z = False
        if mirror_axis=="Z":
            obj.use_mesh_mirror_x = False
            obj.use_mesh_mirror_y = False
            obj.use_mesh_mirror_z = True
        old_topumirror_state = obj.data.use_mirror_topology
        

        #1.使用内部的拓补镜像,对模型进行一次强制对称
        if self.topu_ischeck:
            obj.data.use_mirror_topology = True
            bpy.ops.transform.translate(value=(0, 0, 0), mirror=True)
            obj.data.use_mirror_topology = old_topumirror_state

        #2.检查UV，如果UV内成对，会强制对称
        bm = bmesh.from_edit_mesh(mesh)
        avg_uv = self.calc_avg_uv(obj)
        verts = bm.verts
        repaired=0
        if self.mirroruv_ischeck:
            for v in verts:
                if self.isonlyselect and not v.select:
                    continue
                # 镜像匹配
                uv, cnt = avg_uv.get(v.index,(None,0))
                pair_mirror = self.find_uv_match(v.index,(Vector((1-uv.x, uv.y)), cnt),avg_uv,self.checkuv_tolerance)

                if len(pair_mirror)==0: continue
                v1 = v
                v2 = verts[pair_mirror[0]]
                self.fix_pos(v1,v2,mirror_axis,self.checkuv_tolerance,self.swapsign)
                # print("UV对称:",v1.index,"  ",v2.index)
                repaired+=1

        if self.stackuv_ischeck:
            for v in verts:
                if self.isonlyselect and not v.select:
                    continue
                uv = avg_uv.get(v.index,None)
                # 重叠匹配
                uv, cnt = avg_uv.get(v.index,(None,0))
                pair_mirror = self.find_uv_match(v.index,(uv, cnt),avg_uv,self.checkuv_tolerance)

                if len(pair_mirror)==0: continue
                v1 = v
                v2 = verts[pair_mirror[0]]
                self.fix_pos(v1,v2,mirror_axis,self.checkuv_tolerance,self.swapsign)
                # print("UV重叠:",v1.index,"  ",v2.index)
                repaired+=1
        self.report({'INFO'},f"基于UV成功修复 {repaired} 个点")

        bmesh.update_edit_mesh(mesh)
        return {'FINISHED'}

cls = [OP_Checker_getActiveVertexIndex,OP_Checker_forceVertexMirror,OP_Checker_swapMirrorVertexIndex,
       OP_Checker_AutoForceVertexMirror
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()