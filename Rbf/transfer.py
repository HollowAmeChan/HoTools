import bpy
import bmesh
import numpy as np
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
from mathutils import Vector
from bpy.types import Panel, Operator
from bpy.props import PointerProperty, FloatProperty, IntProperty

def reg_props():
    bpy.types.Scene.ho_rbf_cage_ratio = FloatProperty(
        name="Ratio",
        description="塌陷度，越低面数越少",
        default=0.01,
        min=0.01,
        max=1.0
    )
    bpy.types.Scene.ho_rbf_snap_offset = FloatProperty(
        name="Offset",
        description="沿法线方向的偏移，让cage浮在表面上",
        default=0.001,
        min=-1.0,
        max=1.0,
        step=0.1
    )
    bpy.types.Scene.ho_rbf_srccage = PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.ho_rbf_destcage = PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.ho_rbf_knn = IntProperty(name="K",description="考虑的邻点数，增加会更加平滑但速度更慢（慎重增加）", default=24, min=4, max=64)


def ureg_props():
    del bpy.types.Scene.ho_rbf_cage_ratio
    del bpy.types.Scene.ho_rbf_snap_offset
    del bpy.types.Scene.ho_rbf_srccage
    del bpy.types.Scene.ho_rbf_destcage
    del bpy.types.Scene.ho_rbf_knn





def get_world_verts(obj):
    mw = obj.matrix_world
    return np.array([mw @ v.co for v in obj.data.vertices])


def get_evaluated_world_verts(obj, depsgraph):
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()

    mw = obj.matrix_world
    verts = np.array([mw @ v.co for v in mesh.vertices])

    eval_obj.to_mesh_clear()
    return verts


def write_to_shape_key(obj, new_positions, name="RBF_Result"):
    # 确保有 Basis
    if not obj.data.shape_keys:
        obj.shape_key_add(name="Basis")

    # 删除同名key（避免堆积）
    if name in obj.data.shape_keys.key_blocks:
        obj.shape_key_remove(obj.data.shape_keys.key_blocks[name])

    key = obj.shape_key_add(name=name)

    mw_inv = obj.matrix_world.inverted()

    for i, v in enumerate(key.data):
        v.co = mw_inv @ Vector(new_positions[i])

    key.value = 1.0


def build_bvh(obj, depsgraph):
    return BVHTree.FromObject(obj, depsgraph)


def phi(r, radius):
    return np.exp(-(r / radius) ** 2)

class OP_RbfTransferGenerateCage(Operator):
    bl_idname = "ho.rbftransfer_generatecage"
    bl_label = "生成低模cage"
    bl_description = "默认开启x方向对称与三角化"
    bl_options = {'REGISTER', 'UNDO'}
    ratio: FloatProperty(
        name="Cage Ratio",
        default=0.01,
        min=0.01,
        max=1.0
    ) # type: ignore

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH'

    def execute(self, context):
        src = context.object
        ratio = self.ratio

        # === 1. 复制对象 ===
        cage = src.copy()
        cage.data = src.data.copy()
        cage.name = src.name + "_cage"
        context.collection.objects.link(cage)

        # === 2. 如果有 Shape Keys → 烘焙当前形态 ===
        if cage.data.shape_keys:
            # 确保在对象模式
            bpy.ops.object.mode_set(mode='OBJECT')

            # 设为 active
            bpy.context.view_layer.objects.active = cage
            cage.select_set(True)

            # 删除 shape keys（会保留当前形态）
            bpy.ops.object.shape_key_remove(all=True)

        # === 3. 添加 Decimate ===
        mod = cage.modifiers.new("Decimate", 'DECIMATE')
        mod.ratio = ratio
        mod.use_symmetry = True
        mod.symmetry_axis = 'X'
        mod.use_collapse_triangulate = True

        # === 4. 应用 Modifier ===
        bpy.context.view_layer.objects.active = cage
        bpy.ops.object.modifier_apply(modifier=mod.name)

        self.report({'INFO'}, f"Cage created: {cage.name}")
        return {'FINISHED'}
    
class OP_RbfTransferSnapCage(Operator):
    bl_idname = "ho.rbftransfer_snapcage"
    bl_label = "吸附cage到物体"
    bl_description= "选择需要吸附上去的物体，再加选cage为活动物体，注意cage为活动物体"
    bl_options = {'REGISTER', 'UNDO'}

    offset: FloatProperty(
        name="Surface Offset",
        description="沿法线方向的偏移，让cage浮在表面上",
        default=0.01,
        min=-1.0,
        max=1.0,
        step=0.1
    ) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            return False

        return len(context.selected_objects) >= 2

    def execute(self, context):
        cage = context.object
        targets = [obj for obj in context.selected_objects if obj != cage and obj.type == 'MESH']

        if not targets:
            self.report({'ERROR'}, "需要选中一个目标Mesh物体")
            return {'CANCELLED'}
        if len(targets) > 1:
            self.report({'WARNING'}, "检测到多个目标，使用第一个")

        target = targets[0]

        # --- BVH ---
        depsgraph = context.evaluated_depsgraph_get()
        bvh = build_bvh(target, depsgraph)

        offset = self.offset

        cage_mw = cage.matrix_world
        cage_inv = cage_mw.inverted()

        verts = cage.data.vertices

        for v in verts:
            world_pos = cage_mw @ v.co
            loc, normal, index, dist = bvh.find_nearest(world_pos)

            if loc is not None:
                offset_loc = loc + normal * offset
                v.co = cage_inv @ offset_loc

        self.report({'INFO'}, f"Snap done -> {target.name}")
        return {'FINISHED'}
    
class OP_RbfTransferDoTrans(Operator):
    bl_idname = "ho.rbftransfer_dotrans"
    bl_label = "KNN传递(请看描述)"
    bl_description  = """
    需要两个顶点数与拓补一致的cage
    对被传递的身体执行一次生成cage，生成一个低模代理，此时可以对其进行调整（如部分区域加面，调整位置）
    复制一份cage，摆放到目标身体的位置（不要改变点序跟拓补，保证姿态没有旋转，也就是不要at互传，只能aa/tt传）
    此时新cage可以雕刻移动位置，也可以使用形变类型的修改器辅助吸附
    把这两个cage填入cage槽，选择所有需要传递的衣服执行KNN传递
        注意：
        所有的结果都存入一个新的形态键，如果原本就有一些开关类的形态键，可以配合使用hotools形态键模块进行修复与适配
        如果效果不好，使用雕刻功能局部调整cage的位置，或者直接调整结果的形态键，正常来说只有少量瑕疵
        如果有的地方过于贴合导致穿模，尝试使用snap并加大offset让cage浮在mesh上一点（也可以通过缩裹修改器+顶点组实现精细控制）
    """
    bl_options = {'REGISTER', 'UNDO'}

    knn_k: IntProperty(name="KNN", default=24, min=4, max=64)  # type: ignore

    @classmethod
    def poll(cls, context):
        return any(o.type == 'MESH' for o in context.selected_objects)

    def execute(self, context):

        cageA = context.scene.ho_rbf_srccage
        cageB = context.scene.ho_rbf_destcage

        if not cageA or not cageB:
            self.report({'ERROR'}, "需要两个cage")
            return {'CANCELLED'}

        if len(cageA.data.vertices) != len(cageB.data.vertices):
            self.report({'ERROR'}, "cage点数不一致")
            return {'CANCELLED'}

        C = get_world_verts(cageA)
        D = get_world_verts(cageB) - C

        N = len(C)
        K = min(self.knn_k, N)

        kd = KDTree(N)
        for i, co in enumerate(C):
            kd.insert(co, i)
        kd.balance()

        sample_count = min(N, 512)  # 防止太慢
        step = max(1, N // sample_count)

        dists = []
        for i in range(0, N, step):
            neighbors = kd.find_n(C[i], K)
            if neighbors:
                dists.append(neighbors[-1][2])

        if not dists:
            self.report({'ERROR'}, "KDTree构建失败")
            return {'CANCELLED'}
        
        depsgraph = context.evaluated_depsgraph_get()

        objs = [
            o for o in context.selected_objects
            if o.type == 'MESH' and o not in {cageA, cageB}
        ]

        if not objs:
            self.report({'WARNING'}, "没有可处理的物体")
            return {'CANCELLED'}

        wm = context.window_manager
        wm.progress_begin(0, len(objs))

        for oi, obj in enumerate(objs):
            wm.progress_update(oi)

            P = get_evaluated_world_verts(obj, depsgraph)

            if len(obj.data.vertices) != len(P):
                self.report({'WARNING'}, f"{obj.name} 顶点数变化，跳过")
                continue

            newP = np.zeros_like(P)

            for pi, p in enumerate(P):

                neighbors = kd.find_n(p, K)

                if not neighbors:
                    newP[pi] = p
                    continue

                # === 局部半径（改良版）===
                if len(neighbors) >= 2:
                    r1 = neighbors[-1][2]
                    r2 = neighbors[-2][2]
                    radius = (r1 + r2) * 0.5
                else:
                    radius = neighbors[-1][2]

                v = np.zeros(3)
                w_sum = 0.0

                for (_, index, dist) in neighbors:

                    t = dist / radius

                    if t < 1.0:
                        # Wendland C2
                        w = (1.0 - t) ** 4 * (4.0 * t + 1.0)
                    else:
                        w = 0.0

                    v += D[index] * w
                    w_sum += w

                if w_sum > 0.0:
                    v /= w_sum

                newP[pi] = p + v
            write_to_shape_key(obj, newP, name=f"ho_RBF_{obj.name}")

        wm.progress_end()

        self.report({'INFO'}, f"KNN RBF Done ({len(objs)} objects)")
        return {'FINISHED'}
    
def drawRbfTransferPanel(layout: bpy.types.UILayout, context: bpy.types.Context):
    scene = context.scene

    row = layout.row(align=True)
    row.prop(scene, "ho_rbf_cage_ratio")
    op = row.operator(OP_RbfTransferGenerateCage.bl_idname)
    op.ratio = context.scene.ho_rbf_cage_ratio

    row = layout.row(align=True)
    row.prop(scene,"ho_rbf_snap_offset")
    op = row.operator(OP_RbfTransferSnapCage.bl_idname)
    op.offset = scene.ho_rbf_snap_offset

    row = layout.row(align=True)
    row.prop(scene,"ho_rbf_srccage",text="原cage")
    row.prop(scene,"ho_rbf_destcage",text="目标cage")
    layout.prop(scene,"ho_rbf_knn")
    op = layout.operator(OP_RbfTransferDoTrans.bl_idname)
    op.knn_k = context.scene.ho_rbf_knn



cls = [
    OP_RbfTransferGenerateCage,
    OP_RbfTransferSnapCage,
    OP_RbfTransferDoTrans
]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()