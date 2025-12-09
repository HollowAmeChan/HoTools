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
    bl_label = "自动修复对称"
    bl_description = "使用UV快速匹配修复顶点对称"
    bl_options = {'REGISTER', 'UNDO'}

    isonlyselect:BoolProperty(default=True) # type: ignore
    checkuv_tolerance:FloatProperty(default=0.0000001) # type: ignore
    topu_ischeck:BoolProperty(default=False) # type: ignore
    mirroruv_ischeck:BoolProperty(default=True) # type: ignore
    stackuv_ischeck:BoolProperty(default=False) # type: ignore
    swapsign:BoolProperty(default=False) # type: ignore

    @classmethod
    def poll(cls, context):
        obj=context.active_object
        return obj and obj.type=="MESH" and obj.mode=="EDIT"

    # ---------------- UV处理加速核心 ---------------- #
    def calc_avg_uv(self,obj,precision=1e6):
        """
        返回:
            uv_map = {vert_index:Vector}
            uv_hash = {(ui,vi):[vert_index...]}
        """
        mesh=obj.data
        bm=bmesh.new(); bm.from_mesh(mesh)
        uv_layer=bm.loops.layers.uv.active
        if not uv_layer:
            bm.free();return None,None

        uv_acc=defaultdict(lambda:[0.0,0.0,0])
        for f in bm.faces:
            for l in f.loops:
                i=l.vert.index
                uv=l[uv_layer].uv
                uv_acc[i][0]+=uv.x;uv_acc[i][1]+=uv.y;uv_acc[i][2]+=1

        uv_map={};uv_hash=defaultdict(list)
        for i,(x,y,c) in uv_acc.items():
            uv=Vector((x/c,y/c))
            uv_map[i]=uv
            key=(int(uv.x*precision),int(uv.y*precision))
            uv_hash[key].append(i)

        bm.free()
        return uv_map,uv_hash

    def find_uv_match(self,vert_index,target_uv,uv_map,uv_hash,tolerance,precision=1e6):
        """模糊哈希桶+近邻搜索 → 近似O(1)"""
        cell_r=int(tolerance*precision)+1
        base=(int(target_uv.x*precision),int(target_uv.y*precision))
        best=None;best_d=tolerance**2

        for dx in range(-cell_r,cell_r+1):
            for dy in range(-cell_r,cell_r+1):
                key=(base[0]+dx,base[1]+dy)
                if key not in uv_hash:continue
                for idx in uv_hash[key]:
                    if idx==vert_index:continue
                    d=(uv_map[idx]-target_uv).length_squared
                    if d<best_d:
                        best=idx;best_d=d

        return [best] if best else []

    # ---------------- 对称处理 ---------------- #
    def fix_pos(self,v1,v2,axis,tol=1e-8,sw=False):
        """保持你原来的对称实现"""
        def pick(a,b,coord):
            return (a,b) if getattr(a.co,coord)<getattr(b.co,coord) else (b,a)

        if axis=="X":
            left,right=pick(v1,v2,"x")
            if right.co.x<=tol:return
            if sw:left,right=right,left
            right.co.x=-left.co.x;right.co.y=left.co.y;right.co.z=left.co.z

        if axis=="Y":
            left,right=pick(v1,v2,"y")
            if right.co.y<=tol:return
            if sw:left,right=right,left
            right.co.x=left.co.x;right.co.y=-left.co.y;right.co.z=left.co.z

        if axis=="Z":
            left,right=pick(v1,v2,"z")
            if right.co.z<=tol:return
            if sw:left,right=right,left
            right.co.x=left.co.x;right.co.y=left.co.y;right.co.z=-left.co.z

    # ---------------- 主执行 ---------------- #
    def execute(self,context):
        obj=context.active_object
        mesh=obj.data
        axis=context.scene.ho_MirrorCheckerAxis   # 与你原逻辑兼容
        tol=self.checkuv_tolerance

        # 对齐bl内部镜像轴设置
        obj.use_mesh_mirror_x=(axis=="X")
        obj.use_mesh_mirror_y=(axis=="Y")
        obj.use_mesh_mirror_z=(axis=="Z")

        # 可选拓扑镜像处理
        old=obj.data.use_mirror_topology
        if self.topu_ischeck:
            obj.data.use_mirror_topology=True
            bpy.ops.transform.translate(value=(0,0,0),mirror=True)
            obj.data.use_mirror_topology=old

        # --- UV预处理加速 --- #
        uv_map,uv_hash=self.calc_avg_uv(obj)
        if not uv_map:
            self.report({"ERROR"},"无UV层")
            return {'CANCELLED'}

        bm=bmesh.from_edit_mesh(mesh)
        verts=bm.verts

        # --- 按轴分区 (加速匹配) --- #
        left=[];right=[];center=[]
        for v in verts:
            if self.isonlyselect and not v.select:continue
            a={"X":v.co.x,"Y":v.co.y,"Z":v.co.z}[axis]
            if abs(a)<1e-8:center.append(v.index)
            elif a<0:left.append(v.index)
            else:right.append(v.index)

        paired=set();repaired=0

        # ====防呆，首先加入已经成对的顶点====
        def is_sym_pair(v1, v2, axis, tol=1e-6):
            a = v1.co
            b = v2.co
            if axis=="X":
                return (abs(a.y-b.y)<tol and abs(a.z-b.z)<tol and abs(a.x + b.x)<tol)
            if axis=="Y":
                return (abs(a.x-b.x)<tol and abs(a.z-b.z)<tol and abs(a.y + b.y)<tol)
            if axis=="Z":
                return (abs(a.x-b.x)<tol and abs(a.y-b.y)<tol and abs(a.z + b.z)<tol)
            return False

        right_by_axis = {}
        for r in right:
            v = verts[r]
            key = round(getattr(v.co,axis.lower()),6)  # 小数取精避免浮点误差
            right_by_axis.setdefault(abs(key), []).append(r)

        for l in left:
            lv = verts[l]
            sym_key = round(abs(getattr(lv.co,axis.lower())),6)
            if sym_key not in right_by_axis: 
                continue
            for r in right_by_axis[sym_key]:
                if is_sym_pair(lv, verts[r], axis):
                    paired.add(l); paired.add(r)
                    break


        def try_pair(v_idx,target_uv):
            if v_idx in paired:return None
            pair=self.find_uv_match(v_idx,target_uv,uv_map,uv_hash,tol)
            if not pair:return None
            p=pair[0]
            if p in paired:return None
            paired.add(v_idx);paired.add(p)
            return p

        # ---------------- UV镜像优先 ---------------- #
        if self.mirroruv_ischeck:
            for v_idx in left+right:
                uv=uv_map.get(v_idx,None)
                if uv is None:continue
                tgt=Vector((1-uv.x,uv.y))            # 你的原镜像uv逻辑，可扩展YZ
                p=try_pair(v_idx,tgt)
                if not p:continue
                self.fix_pos(verts[v_idx],verts[p],axis,tol,self.swapsign)
                repaired+=1

        # ---------------- UV重叠次之 ---------------- #
        if self.stackuv_ischeck:
            for v_idx in left+right+center:
                if v_idx in paired:continue
                uv=uv_map.get(v_idx,None)
                if uv is None:continue
                p=try_pair(v_idx,uv)
                if not p:continue
                self.fix_pos(verts[v_idx],verts[p],axis,tol,self.swapsign)
                repaired+=1

        bmesh.update_edit_mesh(mesh)
        self.report({'INFO'},f"增强版对称修复完成：{repaired} 点")
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