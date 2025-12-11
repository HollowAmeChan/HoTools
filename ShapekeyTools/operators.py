import bpy
import bmesh
from bpy.types import Operator, UILayout, Context, Object, UIList,PropertyGroup
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty
from mathutils.kdtree import KDTree
import json
import math
from mathutils import Vector


SHAPE_KEY_RENAME_MAP = {
    'Left': 'Right',
    'left': 'right',
    'Right': 'Left',
    'right': 'left',
    '.l': '.r',
    '.r': '.l',
    '.R': '.L',
    '.L': '.R'
}  # 用于OP_GenerateMirroredShapekey，镜像并修改名称
ARKIT_SHAPEKEYS = [
    "browInnerUp",
    "browDownLeft",
    "browDownRight",
    "browOuterUpLeft",
    "browOuterUpRight",
    "eyeLookUpLeft",
    "eyeLookUpRight",
    "eyeLookDownLeft",
    "eyeLookDownRight",
    "eyeLookInLeft",
    "eyeLookInRight",
    "eyeLookOutLeft",
    "eyeLookOutRight",
    "eyeBlinkLeft",
    "eyeBlinkRight",
    "eyeSquintLeft",
    "eyeSquintRight",
    "eyeWideLeft",
    "eyeWideRight",
    "cheekPuff",
    "cheekSquintLeft",
    "cheekSquintRight",
    "noseSneerLeft",
    "noseSneerRight",
    "jawOpen",
    "jawForward",
    "jawLeft",
    "jawRight",
    "mouthFunnel",
    "mouthPucker",
    "mouthLeft",
    "mouthRight",
    "mouthRollUpper",
    "mouthRollLower",
    "mouthShrugUpper",
    "mouthShrugLower",
    "mouthClose",
    "mouthSmileLeft",
    "mouthSmileRight",
    "mouthFrownLeft",
    "mouthFrownRight",
    "mouthDimpleLeft",
    "mouthDimpleRight",
    "mouthUpperUpLeft",
    "mouthUpperUpRight",
    "mouthLowerDownLeft",
    "mouthLowerDownRight",
    "mouthPressLeft",
    "mouthPressRight",
    "mouthStretchLeft",
    "mouthStretchRight",
    "tongueOut",
]
VRCHAT_SHAPEKEYS = [
    "vrc.v_aa",
    "vrc.v_ih",
    "vrc.v_ou",
    "vrc.v_e",
    "vrc.v_oh",

    "vrc.v_sil",
    "vrc.v_pp",
    "vrc.v_ff",
    "vrc.v_th",
    "vrc.v_dd",
    "vrc.v_kk",
    "vrc.v_ch",
    "vrc.v_ss",
    "vrc.v_nn",
    "vrc.v_rr",
    
    "vrc.looking_up",
    "vrc.looking_down",
    "vrc.blink",
]
MMD_SHAPEKEYS = [
    "まばたき", "笑い", "ウィンク", "ウィンク右", "ウィンク２", "ｳｨﾝｸ２右", "なごみ", "はぅ",
    "びっくり", "じと目", "ｷﾘｯ", "はちゅ目", "星目", "はぁと", "瞳小", "瞳縦潰れ",
    "光下", "恐ろしい子！", "ハイライト消", "映り込み消", "喜び", "わぉ?!", "なごみω",
    "悲しむ", "敵意",
    "あ", "い", "う", "え", "お", "あ２", "ん", "▲", "∧", "□",
    "ワ", "ω", "ω□", "にやり", "にやり２", "にっこり", "ぺろっ", "てへぺろ", "てへぺろ２",
    "口角上げ", "口角下げ", "口横広げ", "歯無し上", "歯無し下",
    "真面目", "困る", "にこり",
    "怒り", "上", "下"
]
VRM_SHAPEKEYS = [
    "A", "I", "U", "E", "O",
    "Blink", "Joy", "Angry", "Sorrow", "Fun",
    "LookUp", "LookDown", "LookLeft", "LookRight",
    "Blink_L", "Blink_R"
]

# 监听器缓存（存在scene中报错）
LISTENER_CACHE = {
    "key_name": "",
    "key_value": 0.0,
    "lock": False,
    "edit_mode": False,
}



class PG_ShapeKeyTools_ListenerCache(PropertyGroup):
        key_name: bpy.props.StringProperty(name="键名", default="") # type: ignore
        key_value: bpy.props.FloatProperty(name="键值", default=0.0) # type: ignore
        lock: bpy.props.BoolProperty(name="是否锁定", default=False) # type: ignore
        edit_mode: bpy.props.BoolProperty(name="是否编辑模式", default=False) # type: ignore


def reg_props():
    bpy.types.Scene.hoShapekeyTools_open_menu = BoolProperty(default=False)#启用属性下的操作菜单
    
    bpy.types.Scene.hoShapekeyTools_chooseVertexByIndex = IntProperty(
        default=0)  # 按照顶点索引选择顶点的UI参数
    bpy.types.Scene.hoShapekeyTools_selectedBaseShapekey = StringProperty(
        description="清除形态键时基于的基型")  # 清除形态键数据时依赖的形态键,再UI的绘制
    bpy.types.Scene.hoShapekeyTools_mirrorAxis = bpy.props.EnumProperty(
        name="轴向",
        description="选择对称轴向",
        items=[
            ('X', "X", "沿 X 轴对称"),
            ('Y', "Y", "沿 Y 轴对称"),
            ('Z', "Z", "沿 Z 轴对称")
        ],
        default='X'
    )

    bpy.types.Scene.hoShapekeyTools_mirrorTolerance = bpy.props.FloatProperty(
        name="容差",
        description="查找对称顶点时的容差，允许一定范围内的不对称",
        default=0.001,
        soft_min=0.0001,
        soft_max=1.0,
        precision=4
    )
    bpy.types.Scene.hoShapekeyTools_isMirrorRename = BoolProperty(
        name="是否自动重命名",
        description="生成的形态键是否自动将Right与Left互相转换",
        default=True)
    bpy.types.Scene.hoShapekeyTools_isMirrorOverwrite = BoolProperty(
        name="是否覆盖已有",
        description="如果这个形态键已经存在,是否不新建而直接使用这个已经有的键",
        default=False)

    bpy.types.Scene.hoShapekeyTools_splitShapeKey_namesuffix_viewLeft = StringProperty(
        description="拆分形态键时,-X方向(我们左手边)形态键的后缀", default="Right")  # UI绘制使用
    bpy.types.Scene.hoShapekeyTools_splitShapeKey_namesuffix_viewRight = StringProperty(
        description="拆分形态键时,+X方向(我们右手边)形态键的后缀", default="Left")  # UI绘制使用
    
    bpy.types.Scene.hoShapekeyTools_copy_is_abs = BoolProperty(
        name="是否绝对复制粘贴",
        description="开启后的复制粘贴将会视形态键位绝对位置进行复制粘贴,如果你看不懂，不要开，注意不要混用两种复制与粘贴",
        default=False)

    #======================================================================#
    # 监听器(每帧执行)
    def shape_key_listener(scene):
        global LISTENER_CACHE

        active_obj = bpy.context.object
        if not active_obj or not active_obj.data.shape_keys:
            return
        active_sk = active_obj.active_shape_key
        if not active_sk:
            return 

        current_name = active_sk.name
        current_value = round(active_sk.value, 6)
        current_lock = active_obj.show_only_shape_key
        current_edit_mode = active_obj.use_shape_key_edit_mode

        if (LISTENER_CACHE["key_name"] == current_name and
            LISTENER_CACHE["key_value"] == current_value and
            LISTENER_CACHE["lock"] == current_lock and
            LISTENER_CACHE["edit_mode"] == current_edit_mode):
            return

        # 更新缓存
        LISTENER_CACHE.update({
            "key_name": current_name,
            "key_value": current_value,
            "lock": current_lock,
            "edit_mode": current_edit_mode
        })

        # 执行更新
        for obj in bpy.context.selected_objects:
            if not obj.data.shape_keys:
                continue
            # 设置锁定与编辑模式启用与否
            obj.show_only_shape_key = current_lock
            obj.use_shape_key_edit_mode = current_edit_mode

            # 设置活动键与活动键值
            sk_block_idx = obj.data.shape_keys.key_blocks.find(current_name)
            sk_block = obj.data.shape_keys.key_blocks[sk_block_idx]
            if sk_block:
                #设置对应键值
                sk_block.value = active_sk.value
                #设置为活动键
                obj.active_shape_key_index = sk_block_idx

            # 同步其他所有键值（可选）
            for sk in active_obj.data.shape_keys.key_blocks:
                if sk == active_obj.data.shape_keys.reference_key:#跳过基型
                    continue
                #获取目标键
                tgt_sk = obj.data.shape_keys.key_blocks.get(sk.name)
                if not tgt_sk:
                    continue
                if tgt_sk == obj.data.shape_keys.reference_key:#跳过目标基型
                    continue

                tgt_sk.value = sk.value

    # 开关更新函数-用于监听器的注册于注销
    def update_listener_switch(self, context):
        enabled = context.scene.hoShapekeyTools_control_shape_key_listener
        if enabled:
            if shape_key_listener not in bpy.app.handlers.depsgraph_update_post:
                bpy.app.handlers.depsgraph_update_post.append(shape_key_listener)
                print("监听器已启用")
        else:
            if shape_key_listener in bpy.app.handlers.depsgraph_update_post:
                bpy.app.handlers.depsgraph_update_post.remove(shape_key_listener)
                print("监听器已禁用")
    #开关
    bpy.types.Scene.hoShapekeyTools_control_shape_key_listener = bpy.props.BoolProperty(
        name="同步模式",
        description="""
        启用后监听活动物体的形态键设置变化
        需要注意监听不到非活动键的值修改，此时点击任意键可以刷新
        """,
        default=False,
        update=update_listener_switch
    )
    #======================================================================#

    return


def ureg_props():
    del bpy.types.Scene.hoShapekeyTools_open_menu
    del bpy.types.Scene.hoShapekeyTools_chooseVertexByIndex
    del bpy.types.Scene.hoShapekeyTools_selectedBaseShapekey
    del bpy.types.Scene.hoShapekeyTools_mirrorAxis
    del bpy.types.Scene.hoShapekeyTools_mirrorTolerance
    del bpy.types.Scene.hoShapekeyTools_isMirrorRename
    del bpy.types.Scene.hoShapekeyTools_isMirrorOverwrite
    del bpy.types.Scene.hoShapekeyTools_splitShapeKey_namesuffix_viewLeft
    del bpy.types.Scene.hoShapekeyTools_splitShapeKey_namesuffix_viewRight
    del bpy.types.Scene.hoShapekeyTools_control_seleted_object_SKValue
    del bpy.types.Scene.hoShapekeyTools_control_seleted_object_SKLock
    del bpy.types.Scene.hoShapekeyTools_copy_is_abs

    del bpy.types.Scene.hoShapekeyTools_control_shape_key_listener_cache
    del bpy.types.Scene.hoShapekeyTools_control_shape_key_listener
    return


class OP_SelectVertexByIndex(Operator):
    bl_idname = "ho.select_vertex_by_index"
    bl_label = "通过顶点索引选择顶点"

    # 定义一个属性用于接收顶点索引列表
    vertex_index: bpy.props.IntProperty(
        name="Vertex Index", default=0)  # type: ignore

    def execute(self, context):
        # 获取活动物体
        obj = context.active_object

        # 确保活动物体是网格类型
        if obj and obj.type == 'MESH':
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_mode(type='VERT')
            bpy.ops.object.mode_set(mode='OBJECT')
            for v in obj.data.vertices:
                v.select = False
            # 选择指定的顶点

            if 0 <= context.scene.hoShapekeyTools_chooseVertexByIndex < len(obj.data.vertices):
                obj.data.vertices[context.scene.hoShapekeyTools_chooseVertexByIndex].select = True
            # 进入编辑模式显示选择结果
            bpy.ops.object.mode_set(mode='EDIT')
            return {'FINISHED'}
        return {'CANCELLED'}

class OP_SelectShapekeyOffsetedVerticex(Operator):
    """选择当前活动形态键中偏移量大于 0 的顶点"""
    bl_idname = "ho.select_positive_offset_vertices"
    bl_label = "选择形态键偏移大于0的顶点"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'MESH' and obj.data.shape_keys

    def execute(self, context):
        # 获取活动对象
        obj = context.object

        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "请选中一个网格对象！")
            return {'CANCELLED'}
        if obj.data.shape_keys is None or obj.data.shape_keys.key_blocks is None:
            self.report({'ERROR'}, "当前对象没有形态键！")
            return {'CANCELLED'}
        active_key = obj.active_shape_key
        if active_key is None:
            self.report({'ERROR'}, "未找到活动形态键！")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='EDIT')
        mesh = bmesh.from_edit_mesh(obj.data)

        # 遍历形态键数据并选中对应顶点
        for i, shape_vert in enumerate(active_key.data):
            if shape_vert.co != obj.data.vertices[i].co:
                mesh.verts[i].select = True

        # 更新编辑网格以反映选择状态
        bmesh.update_edit_mesh(obj.data)
        bpy.ops.mesh.select_mode(
            use_extend=False, use_expand=False, type='VERT')  # 强制进入顶点选择模式
        obj.update_from_editmode()  # 刷新顶点选择态
        self.report({'INFO'}, "已选择形态键所有顶点")
        return {'FINISHED'}


class OP_RemoveSelectedVerticesInActiveShapekey(Operator):
    """清除活动形态键中，选择的顶点的偏移"""
    bl_idname = "ho.remove_selected_vertices_in_activeshapekey"
    bl_label = "清除/替换活动形态键中，选择的顶点的偏移"
    bl_options = {'REGISTER', 'UNDO'}

    shape_key: bpy.props.StringProperty(name="形态键")  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'MESH' and obj.data.shape_keys and context.mode == "EDIT_MESH"

    def execute(self, context):

        obj = context.object
        # 检查形态键是否存在
        if self.shape_key not in obj.data.shape_keys.key_blocks:
            self.report(
                {'WARNING'}, f"使用的形态键'{self.shape_key}'不存在,请选择")
            return {'CANCELLED'}
        bpy.ops.mesh.blend_from_shape(shape=self.shape_key, add=False)

        return {'FINISHED'}


class OP_SmoothShapekey(Operator):
    """平滑形态键，使用距离平滑偏移量"""
    bl_idname = "ho.smooth_shapekey"
    bl_label = "平滑形态键，使用距离平滑偏移量"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode != "EDIT_MESH":
            return False
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            return False
        if not obj.data.shape_keys or not obj.active_shape_key:
            return False
        if obj.data.shape_keys.reference_key == obj.active_shape_key:
            return False
        return True
    
    def get_selected_bbox_diagonal(self, bm):
        selected_verts = [v for v in bm.verts if v.select]
        if not selected_verts:
            return 0.0
            
        min_co = Vector(selected_verts[0].co)
        max_co = Vector(selected_verts[0].co)
        
        for v in selected_verts[1:]:
            min_co.x = min(min_co.x, v.co.x)
            min_co.y = min(min_co.y, v.co.y)
            min_co.z = min(min_co.z, v.co.z)
            
            max_co.x = max(max_co.x, v.co.x)
            max_co.y = max(max_co.y, v.co.y)
            max_co.z = max(max_co.z, v.co.z)
            
        return (max_co - min_co).length

    def smooth_vertex(self, vert_index, offsets, basis_coords, kd, radius, smooth_factor):
        original_offset = offsets[vert_index]
        co = basis_coords[vert_index]
        total_weight = 0.0
        weighted_sum = Vector((0.0, 0.0, 0.0))

        for found_co, found_index, dist in kd.find_range(co, radius):
            weight = math.exp(-(dist * dist) / (2 * (radius * 0.333) ** 2))
            weighted_sum += offsets[found_index] * weight
            total_weight += weight

        if total_weight > 0.0:
            average_offset = weighted_sum / total_weight
            return original_offset.lerp(average_offset, smooth_factor)
        return original_offset

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        obj.update_from_editmode()

        basis = mesh.shape_keys.reference_key
        active = obj.active_shape_key

        bm = bmesh.from_edit_mesh(mesh)
        bm.verts.ensure_lookup_table()

        basis_co = [Vector(basis.data[v.index].co) for v in bm.verts]
        offsets = [active.data[v.index].co - basis.data[v.index].co for v in bm.verts]

        max_dist = self.get_selected_bbox_diagonal(bm)
        if max_dist == 0:
            self.report({'WARNING'}, "没有选中顶点或选中顶点距离为 0")
            return {'CANCELLED'}
        radius = max_dist * 0.2
        smooth_factor = 0.5

        # 建立KDTree
        size = len(bm.verts)
        kd = KDTree(size)
        for i, co in enumerate(basis_co):
            kd.insert(co, i)
        kd.balance()

        for _ in range(1):
            new_offsets = offsets.copy()
            for i in range(size):
                new_offsets[i] = self.smooth_vertex(i, offsets, basis_co, kd, radius, smooth_factor)
            offsets = new_offsets

        # 写回偏移量
        for v in bm.verts:
            if v.select:
                v.co = basis.data[v.index].co + offsets[v.index]

        bm.normal_update()
        bmesh.update_edit_mesh(mesh, loop_triangles=False)
        obj.update_from_editmode()

        return {'FINISHED'}



class OP_balanceShapekey(Operator):
    """对称当前形态键，将选中的顶点对称到另一侧,全选则为镜像，可以指定轴向，轴向正负为所选的方向"""
    bl_idname = "ho.balance_shapekey"
    bl_label = "对称当前形态键，将选中的顶点对称到另一侧,全选则为镜像，可以指定轴向，轴向正负为所选的方向"
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(
        name="轴向",
        description="选择对称轴向",
        items=[
            ('X', "X 轴", "沿 X 轴对称"),
            ('Y', "Y 轴", "沿 Y 轴对称"),
            ('Z', "Z 轴", "沿 Z 轴对称")
        ],
        default='X'
    )  # type: ignore

    tolerance: FloatProperty(
        name="容差",
        description="查找对称顶点时的容差，允许一定范围内的不对称",
        default=0.001,
        min=0.0001,
        max=1.0
    )  # type: ignore

    # only_selected: BoolProperty(
    #     name="仅选中顶点",
    #     default=True
    # )  # type: ignore

    @classmethod
    def poll(cls, context):
        if not context.mode == "EDIT_MESH":
            return False
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            return False
        if not obj.data.shape_keys or obj.data.shape_keys.reference_key == obj.active_shape_key:
            return False
        return True

    def execute(self, context):

        obj = context.active_object
        mesh = obj.data
        # 轴向索引
        axis_index = {'X': 0, 'Y': 1, 'Z': 2}.get(self.axis.upper(), 0)

        if not obj or obj.type != 'MESH' or not mesh.shape_keys:
            self.report(
                {'ERROR'}, "活动物体必须是有形态键的网格物体")
            return {'CANCELLED'}
        obj.update_from_editmode()  # 同步网格数据，确保 mesh 数据是最新的

        # 获取形态键数据
        basis_shape_key = mesh.shape_keys.reference_key
        active_shape_key = obj.active_shape_key

        # 创建 bmesh（使用当前编辑模式下的物体网格）
        bm = bmesh.from_edit_mesh(mesh)
        bm.verts.ensure_lookup_table()  # 保证刷新，不加这句在其他ops中调用无法成功

        # 基型位置KDTree,用于查找匹配顶点
        basis_verts = [basis_shape_key.data[i].co for i in range(
            len(basis_shape_key.data))]
        kd_tree = KDTree(len(basis_verts))
        for i, vert in enumerate(basis_verts):  # 填充 KDTree，使用基型位置
            kd_tree.insert(vert, i)
        kd_tree.balance()

        # 创建需要处理的顶点清单（使用bmesh中选择的顶点）
        # verts = []
        # if self.only_selected:
        #     verts = [v for v in bm.verts if v.select]
        # else:
        #     verts = list(bm.verts)
        verts = [v for v in bm.verts if v.select]  # 只处理选择

        if not verts:
            self.report({'INFO'}, "没有检查到需要处理的顶点！")
            return {'FINISHED'}

        # 逐个处理顶点
        for vert in verts:
            vert_idx = vert.index

            # 获取源顶点位置
            source_basis_co = basis_shape_key.data[vert_idx].co
            source_key_co = active_shape_key.data[vert_idx].co

            # 计算对称位置
            co_mirrored = source_basis_co.copy()
            co_mirrored[axis_index] *= -1

            # 在 基型位置KDTree 中查找对称顶点
            result = kd_tree.find_range(co_mirrored, self.tolerance)
            if result:
                mirror_idx = result[0][1]  # 最近点的索引
                mirrored_basis_co = basis_shape_key.data[mirror_idx].co
                mirrored_vert = bm.verts[mirror_idx]

                # 计算偏移并更新 BMesh 顶点位置
                offset = source_key_co - source_basis_co
                offset[axis_index] *= -1
                mirrored_vert.co = mirrored_basis_co + offset

        # 将 BMesh 数据写回 mesh
        bm.normal_update()
        bmesh.update_edit_mesh(mesh, loop_triangles=False)
        obj.update_from_editmode()

        self.report({'INFO'}, "Symmetry operation completed.")
        return {'FINISHED'}


class OP_GenerateMirroredShapekey(Operator):
    """直接生成活动形态键的镜像形态键,并改名,不使用bl的镜像,而使用hotools的镜像,因此面板中的容差/轴向参数可用"""
    bl_idname = "ho.generate_mirrored_shapekey"
    bl_label = "直接生成活动形态键的镜像形态键,并改名,不使用bl的镜像,而使用hotools的镜像,因此面板中的容差/轴向参数可用"
    bl_options = {'REGISTER', 'UNDO'}

    auto_rename: BoolProperty(
        name="自动改名",
        description="自动将名称中Left/left与Right/right交换",
        default=True
    )  # type: ignore

    overwrite: BoolProperty(
        name="直接使用已存在的形态键",
        description="如果目标形态键已存在，则直接使用它而不新建",
        default=False
    )  # type: ignore

    def rename_shape_key(self, name: str):
        """根据全局字典自动交换名称中的Left与Right"""
        global SHAPE_KEY_RENAME_MAP
        for old, new in SHAPE_KEY_RENAME_MAP.items():
            if old in name:
                return name.replace(old, new)  # 只替换第一个，防止循环
        return name

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            context.mode == "OBJECT" and
            obj and
            obj.type == 'MESH' and
            obj.data.shape_keys and
            obj.data.shape_keys.reference_key != obj.active_shape_key
        )

    def execute(self, context):
        obj = context.active_object
        active_key = obj.active_shape_key

        # 生成目标形态键名称
        new_name = active_key.name
        if self.auto_rename:
            new_name = self.rename_shape_key(active_key.name)

        # 检查形态键是否已存在
        key_blocks = obj.data.shape_keys.key_blocks
        target_key = key_blocks.get(new_name)

        # 处理形态键
        if target_key and self.overwrite:
            for i in range(len(active_key.data)):
                target_key.data[i].co = active_key.data[i].co.copy()
            msg = f"已覆盖: {target_key.name}"
        else:
            # 创建新形态键
            target_key = obj.shape_key_add(from_mix=False, name=new_name)
            for i in range(len(active_key.data)):
                target_key.data[i].co = active_key.data[i].co.copy()
            msg = f"已创建: {target_key.name}"

        # 设置活动形态键
        obj.active_shape_key_index = key_blocks.find(target_key.name)

        # 执行hotools镜像操作
        if obj.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        obj.update_from_editmode()
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.ho.balance_shapekey(
            axis=context.scene.hoShapekeyTools_mirrorAxis,
            tolerance=context.scene.hoShapekeyTools_mirrorTolerance
        )
        bpy.ops.object.mode_set(mode='OBJECT')

        # 显式提示用户
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class OP_SplitShapekey(Operator):
    """拆分形态键为左右两份"""
    bl_idname = "ho.split_shapekey"
    bl_label = "将形态键拆为左右两份，并改名,对于中线处的顶点会均分到两侧的形态键（以减少断裂感）"
    bl_options = {'REGISTER', 'UNDO'}

    # 添加两个属性供外部传入
    suffix_viewLeft: StringProperty(
        name="Left Suffix",
        description="拆分形态键时，左侧(-X方向)形态键的后缀",
        default="Left"
    )  # type: ignore
    suffix_viewRight: StringProperty(
        name="Right Suffix",
        description="拆分形态键时，右侧(+X方向)形态键的后缀",
        default="Right"
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj: object = context.active_object
        if not obj:
            return False
        if not obj.type == 'MESH':
            return False
        if not obj.data.shape_keys:
            return False
        if obj.data.shape_keys.reference_key == obj.active_shape_key:
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        active_key = obj.active_shape_key

        # 获取形态键的名称
        key_name = active_key.name

        # 复制形态键，创建左右两份
        view_left_key = obj.shape_key_add(
            name=key_name+self.suffix_viewLeft, from_mix=False)
        view_right_key = obj.shape_key_add(
            name=key_name+self.suffix_viewRight, from_mix=False)

        # 获取形态键的原始数据
        original_data = active_key.data

        # 遍历形态键的顶点数据并进行拆分
        for vert in obj.data.vertices:
            # index = vert.index
            # co = original_data[index].co
            # if co.x < 0:
            #     view_left_key.data[index].co = co
            #     view_right_key.data[index].co = vert.co  # 右侧保持不变
            # else:
            #     view_right_key.data[index].co = co
            #     view_left_key.data[index].co = vert.co  # 左侧保持不变

            idx = vert.index
            # 基础坐标和当前形态键坐标
            co = original_data[idx].co

            # 判断中线顶点（基础网格x=0）
            if abs(vert.co.x) < 1e-6:
                # 计算偏移量并均分
                delta = co - vert.co
                half_co = vert.co + delta * 0.5
                view_left_key.data[idx].co = half_co
                view_right_key.data[idx].co = half_co
            else:
                # 非中线顶点按基础坐标划分
                if co.x < 0:
                    view_left_key.data[idx].co = co
                    view_right_key.data[idx].co = vert.co  # 右侧保持基础
                else:
                    view_right_key.data[idx].co = co
                    view_left_key.data[idx].co = vert.co    # 左侧保持基础

        self.report(
            {'INFO'}, f"形态键 '{key_name}' 已拆分为 '{key_name}_L' 和 '{key_name}_R'。")
        return {'FINISHED'}


class OP_RemoveEmptyShapekeys(Operator):
    """删除活动物体中所有的空形态键"""
    bl_idname = "ho.remove_empty_shapekey"
    bl_label = "删除物体中的空形态键"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # 只检查是否存在活动对象和选中对象，不进行深入检查
        return context.active_object is not None and context.selected_objects

    def execute(self, context):
        total_removed_keys = 0  # 统计总共删除的形态键数量
        processed_objects = 0  # 统计处理的物体数量

        for obj in context.selected_objects:
            # 检查物体是否为网格类型且具有形态键
            if obj.type == 'MESH' and obj.data.shape_keys:
                shape_keys = obj.data.shape_keys
                empty_keys = []

                # 遍历形态键，找出空的形态键
                for key in shape_keys.key_blocks:
                    # 跳过基型和锁定的形态键 
                    if key == shape_keys.reference_key or key.lock_shape: continue

                    is_empty = True
                    for i, shape_vert in enumerate(key.data):
                        if shape_vert.co != obj.data.vertices[i].co:
                            is_empty = False
                            break
                    if is_empty:
                        empty_keys.append(key)

                # 删除空的形态键
                for empty_key in empty_keys:
                    obj.shape_key_remove(empty_key)

                if empty_keys:
                    total_removed_keys += len(empty_keys)
                    processed_objects += 1

        # 根据结果显示反馈信息
        if total_removed_keys > 0:
            self.report(
                {'INFO'}, f"已删除 {total_removed_keys} 个空形态键，共处理 {processed_objects} 个物体")
        else:
            self.report({'WARNING'}, "所选物体中没有找到空形态键")

        return {'FINISHED'}


class OP_ClearAllShapekeyValue(Operator):
    """清除选择的所有物体的所有形态键值,设置为0"""
    bl_idname = "ho.clear_all_shapekey_value"
    bl_label = "清除选择的所有物体的所有形态键值,设置为0"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # 只检查是否存在活动对象和选中对象，不再深入检查
        return context.active_object is not None and context.selected_objects

    def execute(self, context):
        # 遍历选中物体，清除非基型形态键值
        cleared_objects = 0
        # 遍历选中的物体，处理每个物体的形态键
        for obj in context.selected_objects:
            if obj.type == 'MESH' and obj.data.shape_keys:
                shape_keys = obj.data.shape_keys
                basis_key = shape_keys.reference_key  # 获取基型形态键

                if basis_key:  # 确保基型形态键存在
                    # 遍历非基型形态键，清零值
                    non_basis_keys = [
                        key for key in shape_keys.key_blocks if key != basis_key]

                    for key in non_basis_keys:
                        key.value = 0
                    cleared_objects += 1

        # 根据结果显示反馈信息
        if cleared_objects > 0:
            self.report({'INFO'}, f"已清除 {cleared_objects} 个物体的非基型形态键值")
        else:
            self.report({'WARNING'}, "没有找到包含非基型形态键的物体")

        return {'FINISHED'}

class OP_SetBasisShapekeyActive(Operator):
    """设置选择的所有物体的活动形态键为基型"""
    bl_idname = "ho.set_basis_shapekey_active"
    bl_label = "设置选择的所有物体的活动形态键为基型"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # 检查是否有活动对象和选中对象
        return context.active_object is not None and context.selected_objects

    def execute(self, context):
        # 统计成功设置基型形态键的物体数量
        updated_objects = 0

        # 遍历选中的物体
        for obj in context.selected_objects:
            # 确保物体是网格类型且有形态键
            if obj.type == 'MESH' and obj.data.shape_keys:
                shape_keys = obj.data.shape_keys
                # 直接访问第一个形态键（基型形态键）
                if shape_keys.key_blocks:
                    # 将基型设置为活动形态键
                    obj.active_shape_key_index = 0  # 基型是第一个形态键
                    updated_objects += 1

        # 根据操作结果输出反馈信息
        if updated_objects > 0:
            self.report({'INFO'}, f"已设置 {updated_objects} 个物体的活动形态键为基型")
        else:
            self.report({'WARNING'}, "没有找到包含基型形态键的物体")

        return {'FINISHED'}


class OP_applyShowingModifiersKeepShapekeys(Operator):
    """
    应用视图显示的修改器并保持形态键
    原理:
    一个拥有多个形态键的物体无法应用修改器
    相同拓补的物体可以使用“形态键-合并”将位置传递过来变为形态键
    可以将每个形态键的位置都新建一个物体，他们只有一个形态键，就可以应用修改器

    复制n个物体,n为形态键数量,全部删除掉形态键保留目标形态键位置为基础位置
    应用这些物体的修改器
    复制1个物体作为接收器,删除形态键到只有基型，应用掉修改器
    使用原生的合并api传递形态键,删除多余的物体
    """
    bl_idname = "ho.apply_showing_modifiers_keepshapekeys"
    bl_label = "应用视图显示中的修改器"
    bl_options = {'REGISTER', 'UNDO'}

    def copy_object(self, obj, times=1, offset=0) -> list[Object]:
        """复制传入的物体多份返回,并在x轴上偏移,可以指定偏移的起始量"""
        objects = []
        for i in range(0, times):
            copy_obj = obj.copy()
            copy_obj.data = obj.data.copy()
            copy_obj.name = obj.name + "_shapekey_" + str(i+1)
            copy_obj.location.x += offset*(i+1)

            bpy.context.collection.objects.link(copy_obj)
            objects.append(copy_obj)

        return objects

    def apply_shapekey(self, obj, sk_keep):
        """等效于应用形态键，删除某个形态键以外的全部键，总而达到保留那一个键的位置的效果"""
        shapekeys = obj.data.shape_keys.key_blocks

        if sk_keep < 0 or sk_keep > len(shapekeys):
            return
        # 倒着删保证目标键最后删，等效应用
        for i in reversed(range(0, len(shapekeys))):
            if i != sk_keep:
                obj.shape_key_remove(shapekeys[i])
        obj.shape_key_remove(shapekeys[0])

    def apply_modifier(self, obj, modifier_name: str):
        """应用单独的一个修改器"""
        modifier = [
            mod for mod in obj.modifiers if mod.name == modifier_name][0]
        for o in bpy.context.scene.objects:
            o.select_set(False)
        bpy.context.view_layer.objects.active = obj  # 保证只有这个物体选中且为活动项

        with bpy.context.temp_override(object=obj, modifier=obj.modifiers):
            bpy.ops.object.modifier_apply(modifier=modifier_name)
        # bpy.ops.object.modifier_apply(modifier=modifier.name)

    def remove_modifiers(self, obj):
        """倒序移除物体的全部修改器"""
        for i in reversed(range(0, len(obj.modifiers))):  # 倒序移除防止出问题
            modifier = obj.modifiers[i]
            obj.modifiers.remove(modifier)

    def add_objs_shapekeys(self, destination: Object, sources: list[Object]):
        """
        批量选择sources物体,将destination物体设置为活动,调用bl的合并形态键合并到活动物体
        这些物体的拓补一致
        """
        # 保证物体的选择是正确的
        for o in bpy.context.scene.objects:
            o.select_set(False)
        for src in sources:
            src.select_set(True)

        bpy.context.view_layer.objects.active = destination
        # bpy.ops.object.join_shapes()  # bl原生api
        # 尝试调用合并操作
        try:
            bpy.ops.object.join_shapes()
        except:
            return sources[0].name  # 出错的通常就是正在尝试合并的源物体
        return None  # 成功
    
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not obj:
            return False
        if obj.type != 'MESH':
            return False
        if not obj.data.shape_keys:
            return False
        if len(obj.data.shape_keys.key_blocks) == 1:
            return False
        if len(obj.modifiers) == 0:
            return False

        return True

    def execute(self, context):

        shapekey_names = []
        obj = context.active_object
        for block in obj.data.shape_keys.key_blocks:
            shapekey_names.append(block.name)

        # 创建新物体（接收对象）
        receiver = self.copy_object(obj, times=1, offset=0)[0]
        receiver.name = "sk_receiver"
        # 烘焙形态键
        self.apply_shapekey(receiver, 0)

        # 只应用自己显示在视图中的修改器（.show_viewport = True）
        for modifier in obj.modifiers:
            if modifier.show_viewport:  # 只应用视图中可见的修改器
                self.apply_modifier(receiver, modifier.name)

        # 每个形态键都创建一个新物体作为副本来传输，跳过基型
        for i in range(1, len(obj.data.shape_keys.key_blocks)):
            blendshapeObject = self.copy_object(obj, times=1, offset=0)[0]
            # 烘焙形态键
            self.apply_shapekey(blendshapeObject, i)
            # 应用显示在视图中的所有修改器
            for modifier in obj.modifiers:
                if modifier.show_viewport:  # 只应用视图中可见的修改器
                    self.apply_modifier(blendshapeObject, modifier.name)

            # 删除其他的全部修改器
            self.remove_modifiers(blendshapeObject)

            # 将副本作为形态键添加到接收物体
            # self.add_objs_shapekeys(receiver, [blendshapeObject])
            if self.add_objs_shapekeys(receiver, [blendshapeObject]):
                self.report({'ERROR'}, f"形态键 '{shapekey_names[i]}' 添加失败，可能是形态键下修改器应用后与基型修改器应用后拓扑不一致。")
                # 清理临时物体再退出
                bpy.data.objects.remove(blendshapeObject)
                bpy.context.view_layer.objects.active = obj
                bpy.context.view_layer.update()
                return {'CANCELLED'}

        
            # 恢复名字
            receiver.data.shape_keys.key_blocks[i].name = shapekey_names[i] #TODO

            # 删除临时物体
            mesh_data = blendshapeObject.data
            bpy.data.objects.remove(blendshapeObject)
            bpy.data.meshes.remove(mesh_data)

        # 移除原始物体
        orig_name = obj.name
        orig_data = obj.data
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(orig_data)

        # 重命名新物体
        receiver.name = orig_name

        return {'FINISHED'}


class OP_ApplyArmatureModifiersKeepShapekeys(Operator):
    """仅应用骨架修改器并保持形态键和其他修改器状态"""
    bl_idname = "ho.apply_armature_modifiers_keepshapekeys"
    bl_label = "应用骨架修改器并保留形态键"
    bl_options = {'REGISTER', 'UNDO'}

    def copy_object(self, obj) -> bpy.types.Object:
        """深度复制物体并保留所有修改器状态"""
        copy_obj = obj.copy()
        copy_obj.data = obj.data.copy()

        # 复制修改器状态
        for orig_mod, new_mod in zip(obj.modifiers, copy_obj.modifiers):
            new_mod.show_viewport = orig_mod.show_viewport
            new_mod.show_render = orig_mod.show_render

        bpy.context.collection.objects.link(copy_obj)
        return copy_obj

    def apply_shapekey(self, obj, sk_keep):
        """保留指定形态键并删除其他"""
        shapekeys = obj.data.shape_keys.key_blocks
        if not shapekeys or sk_keep >= len(shapekeys):
            return

        # 倒序删除避免索引错位
        for i in reversed(range(len(shapekeys))):
            if i != sk_keep:
                obj.shape_key_remove(shapekeys[i])

        # 删除基型（如果有剩余）
        if len(obj.data.shape_keys.key_blocks) > 0:
            obj.shape_key_remove(obj.data.shape_keys.key_blocks[0])

    def apply_armature_modifiers(self, obj):
        """仅处理Armature类型且可见的修改器"""
        applied_mods = []
        for mod in obj.modifiers[:]:  # 遍历副本防止修改影响循环
            if mod.type == 'ARMATURE' and mod.show_viewport:
                mod_name = mod.name
                try:
                    # 保留修改器原始可见状态
                    orig_show = mod.show_viewport
                    
                    with bpy.context.temp_override(object=obj, modifier=mod):
                        bpy.ops.object.modifier_apply(modifier=mod_name)

                    # 记录已应用的修改器
                    applied_mods.append(mod_name)
                except Exception as e:
                    print(f" {obj.name}无法应用修改器 {mod_name}: {str(e)}")

        return applied_mods

    def add_shapekeys(self, dest_obj, src_objects):
        """合并形态键并保持其他修改器"""
        # 保存目标物体修改器状态
        dest_mod_states = {
            mod.name: mod.show_viewport for mod in dest_obj.modifiers}

        # 执行合并操作
        for o in bpy.context.scene.objects:
            o.select_set(False)
        for src in src_objects:
            src.select_set(True)
        bpy.context.view_layer.objects.active = dest_obj
        bpy.ops.object.join_shapes()

        # 恢复修改器可见状态
        for mod in dest_obj.modifiers:
            if mod.name in dest_mod_states:
                mod.show_viewport = dest_mod_states[mod.name]

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj and obj.type == 'MESH' and
                obj.data.shape_keys and
                len(obj.data.shape_keys.key_blocks) > 1 and
                any(m.type == 'ARMATURE' and m.show_viewport for m in obj.modifiers))

    def execute(self, context):
        orig_obj = context.active_object
        shapekey_names = [
            kb.name for kb in orig_obj.data.shape_keys.key_blocks]

        # 步骤1：创建接收器物体
        receiver = self.copy_object(orig_obj)
        receiver.name = "ArmatureReceiver"

        # 步骤2：处理基型
        self.apply_shapekey(receiver, 0)
        applied_mods = self.apply_armature_modifiers(receiver)

        # 步骤3：处理其他形态键
        for sk_idx in range(1, len(shapekey_names)):
            temp_obj = self.copy_object(orig_obj)

            # 保留目标形态键
            self.apply_shapekey(temp_obj, sk_idx)

            # 应用骨架修改器
            self.apply_armature_modifiers(temp_obj)

            # 合并形态键（同时保留其他修改器）
            self.add_shapekeys(receiver, [temp_obj])

            # 清理临时物体
            bpy.data.objects.remove(temp_obj, do_unlink=True)

        # 步骤4：替换原始物体
        # 保存原始修改器状态
        orig_mod_states = {
            mod.name: mod.show_viewport for mod in orig_obj.modifiers}

        # 创建最终物体
        final_obj = self.copy_object(receiver)
        final_obj.name = orig_obj.name

        # 恢复原始修改器可见状态（除了已应用的）
        for mod in final_obj.modifiers:
            if mod.name in orig_mod_states and mod.name not in applied_mods:
                mod.show_viewport = orig_mod_states[mod.name]

        # 清理中间物体
        bpy.data.objects.remove(orig_obj, do_unlink=True)
        bpy.data.objects.remove(receiver, do_unlink=True)

        # 恢复形态键名称
        for idx, name in enumerate(shapekey_names):
            if idx < len(final_obj.data.shape_keys.key_blocks):
                final_obj.data.shape_keys.key_blocks[idx].name = name

        return {'FINISHED'}


class OP_deleteUnusingShapeKeys(Operator):
    """删除所有未启用的形态键"""
    bl_idname = "ho.delete_unusing_shapekeys"
    bl_label = "删除所有未启用的形态键"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # 确保当前有活动的对象，并且该对象有形态键
        return (context.object is not None and
                context.object.data.shape_keys is not None and
                context.object.data.shape_keys.key_blocks is not None)

    def execute(self, context):
        obj = context.object
        shape_keys = obj.data.shape_keys.key_blocks

        # 遍历所有形态键，删除未启用的形态键
        for shape_key in shape_keys[:]:  # 使用[:]创建副本以避免在遍历时修改列表
            if not shape_key.mute:  # 如果形态键未被禁用（即启用状态）
                continue  # 跳过启用的形态键
            # 删除未启用的形态键
            obj.shape_key_remove(shape_key)

        self.report({'INFO'}, "已删除所有未启用的形态键")
        return {'FINISHED'}


class OP_AddShapekeysByTemplate(Operator):
    """批量添加形态键"""
    bl_idname = "ho.add_shapekeys_by_template"
    bl_label = "批量添加形态键"
    bl_options = {'REGISTER', 'UNDO'}

    shapekey_list: bpy.props.EnumProperty(
        name="预设",
        description="选择要添加的预设列表",
        items=[
            ('ARKIT', "ARKit", "ARKit 形态键列表"),
            ('VRCHAT', "VRChat", "VRChat 形态键列表"),
            ('MMD', "MMD", "MMD 形态键列表"),
            ('VRM', "Vrm", "Vrm 形态键列表"),
        ],
        default='ARKIT',
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'MESH'

    def execute(self, context):
        # 获取活动对象
        obj = context.object

        # 确保对象有形态键数据
        if not obj.data.shape_keys:
            obj.shape_key_add(name="Basis")

        # 根据用户选择的列表获取形态键名称
        if self.shapekey_list == 'ARKIT':
            shapekey_names = ARKIT_SHAPEKEYS
        elif self.shapekey_list == 'VRCHAT':
            shapekey_names = VRCHAT_SHAPEKEYS
        elif self.shapekey_list == 'MMD':
            shapekey_names = MMD_SHAPEKEYS
        elif self.shapekey_list == 'VRM':
            shapekey_names = VRM_SHAPEKEYS
        else:
            self.report({'ERROR'}, "无效的形态键列表")
            return {'CANCELLED'}

        # 获取形态键数据
        shape_keys = obj.data.shape_keys.key_blocks

        # 遍历形态键名称列表
        for shapekey_name in shapekey_names:
            if shapekey_name not in shape_keys:
                # 添加形态键
                new_shapekey = obj.shape_key_add(name=shapekey_name)
                new_shapekey.value = 0  # 默认值为0

        self.report({'INFO'}, f"成功添加 {self.shapekey_list} 形态键")
        return {'FINISHED'}

    def invoke(self, context, event):
        # 弹出对话框让用户选择形态键列表
        return context.window_manager.invoke_props_dialog(self)


class OP_ShapekeyTools_copyShapekey2ShearPlate(Operator):
    bl_idname = "ho.shapekeytools_copyshapekey2shearplate"
    bl_label = "复制形态键到剪切板"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "默认为相对基型的位移，开启绝对后复制绝对位置,要确保点序一致"

    is_abs:BoolProperty(name="是否绝对复制",default=False) # type: ignore


    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "必须是一个Mesh物体")
            return {'CANCELLED'}
        if not obj.data.shape_keys or not obj.data.shape_keys.key_blocks:
            self.report({'ERROR'}, "没有找到形态键")
            return {'CANCELLED'}
        
        active_sk = obj.active_shape_key
        basis_key = obj.data.shape_keys.reference_key

        # 提取形态键数据
        coords = []
        if self.is_abs:
            coords = [list(v.co) for v in active_sk.data]
        else :
            for base_v, active_v in zip(basis_key.data, active_sk.data):
                delta = active_v.co - base_v.co
                coords.append([delta.x, delta.y, delta.z])


        # 使用JSON存储并复制到剪切板
        json_str = json.dumps(coords)
        context.window_manager.clipboard = json_str
        self.report({'INFO'}, f"已复制形态键 '{active_sk.name}' 数据到剪切板")
        return {'FINISHED'}

class OP_ShapekeyTools_importShapekeyFromShearPlate(Operator):
    bl_idname = "ho.shapekeytools_importshapekey_from_shearplate"
    bl_label = "从剪切板粘贴形态键"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "默认为相对基型的位移，开启绝对后粘贴绝对位置,要确保点序一致"

    is_abs:BoolProperty(name="是否粘贴绝对位置",default=False) # type: ignore

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "必须是一个Mesh物体")
            return {'CANCELLED'}
        if not obj.data.shape_keys or not obj.data.shape_keys.key_blocks:
            self.report({'ERROR'}, "没有找到形态键")
            return {'CANCELLED'}
        
        active_sk = obj.active_shape_key
        basis_key = obj.data.shape_keys.reference_key


        try:
            data = json.loads(context.window_manager.clipboard)
            if len(data) != len(active_sk.data):
                self.report({'ERROR'}, "粘贴数据与形态键顶点数量不匹配")
                return {'CANCELLED'}
            
            if self.is_abs:
                for i, co in enumerate(data):
                    active_sk.data[i].co = co
            else:
                for i, delta in enumerate(data):
                    base = basis_key.data[i].co
                    active_sk.data[i].co = Vector(base) + Vector(delta)
                
            self.report({'INFO'}, f"成功粘贴到形态键 '{active_sk.name}'")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"粘贴失败: {str(e)}")
            return {'CANCELLED'}

class OP_ShapekeyTools_importShapekeyFromShearPlate_Relative_add(Operator):
    bl_idname = "ho.shapekeytools_importshapekey_from_shearplate_relatove_add"
    bl_label = "从剪切板粘贴相对形态键进行叠加"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "粘贴相对基型的位移，会直接叠加到当前活动键上，开启绝对后不要使用,要确保点序一致"

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "必须是一个Mesh物体")
            return {'CANCELLED'}
        if not obj.data.shape_keys or not obj.data.shape_keys.key_blocks:
            self.report({'ERROR'}, "没有找到形态键")
            return {'CANCELLED'}
        #检测键
        basis_key = obj.data.shape_keys.reference_key
        active_sk = obj.active_shape_key

        if not active_sk:
            self.report({'ERROR'}, "当前没有活动形态键")
            return {'CANCELLED'}

        try:
            data = json.loads(context.window_manager.clipboard)
            if len(data) != len(active_sk.data):
                self.report({'ERROR'}, "粘贴数据与形态键顶点数量不匹配")
                return {'CANCELLED'}
            
            for i, delta in enumerate(data):
                active_sk.data[i].co += Vector(delta)
            
            self.report({'INFO'}, f"成功粘贴到形态键 '{active_sk.name}'")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"粘贴失败: {str(e)}")
            return {'CANCELLED'}

class OP_ShapekeyTools_CopyList2selectedObjects(Operator):
    bl_idname = "ho.shapekeytools_copylist2selectedobjects"
    bl_label = "复制列表到选中物体"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "复制活动物体的整个形态键列表（仅名称与顺序），使选中的其他物体的形态键按照此顺序排列，不存在的会添加，额外的会排列在末尾"


    @classmethod
    def poll(cls, context):
        return (context.object is not None and
                context.object.data.shape_keys is not None and
                context.object.data.shape_keys.key_blocks is not None)

    def execute(self, context):
        source_obj = context.object
        source_sk = source_obj.data.shape_keys
        source_basis = source_sk.reference_key

        # 获取源形态键顺序（不含基型）
        source_keys = [k.name for k in source_sk.key_blocks if k != source_basis]

        if not source_keys:
            self.report({'WARNING'}, "源物体没有非基型的形态键")
            return {'CANCELLED'}

        selected_objs = [o for o in context.selected_objects if o != source_obj]

        if not selected_objs:
            self.report({'WARNING'}, "没有其他被选中的物体")
            return {'CANCELLED'}

        for target in selected_objs:
            if target.data.shape_keys is None:
                target.shape_key_add(name="Basis")

            target_sk = target.data.shape_keys
            target_basis = target_sk.reference_key

            # 补齐缺失形态键
            for key_name in source_keys:
                if key_name not in target_sk.key_blocks:
                    target.shape_key_add(name=key_name)

            # 生成新顺序（基型 + 源顺序 + 目标额外键）
            #current_keys与source_keys中均无基型
            current_keys = [k.name for k in target_sk.key_blocks if k != target_basis]
            extra_keys = [k for k in current_keys if k not in source_keys]
            new_order = [target_basis.name] + source_keys + extra_keys

            # 真正重排（使用 bpy.ops.object.shape_key_move）
            self.reorder_shape_keys(target, new_order)


        
        self.report({'INFO'}, f"已复制形态键顺序到 {len(selected_objs)} 个物体（跳过基型）")
        return {'FINISHED'}
    
    def reorder_shape_keys(self, obj, new_order):
        """按照 new_order 对 obj 的形态键顺序进行重排"""
        shape_keys = obj.data.shape_keys.key_blocks
        # 用临时上下文覆盖执行
        with bpy.context.temp_override(object=obj, active_object=obj):
            for target_index, target_name in enumerate(new_order):
                current_index = next((i for i, key in enumerate(shape_keys) if key.name == target_name), None)
                if current_index is None or current_index == target_index:
                    continue
                bpy.context.object.active_shape_key_index = current_index
                # 按方向移动
                while current_index < target_index:
                    bpy.ops.object.shape_key_move(type='DOWN')
                    current_index += 1
                while current_index > target_index:
                    bpy.ops.object.shape_key_move(type='UP')
                    current_index -= 1
        obj.active_shape_key_index = 0  # 选中基型


def draw_in_DATA_PT_modifiers(self, context):
    """修改器顶上"""
    layout: bpy.types.UILayout = self.layout
    layout.use_property_decorate = False  # 禁用关键帧动画

    obj = context.object

    if not obj:
        return  # 未选物体不显示
    if not obj.modifiers:
        return  # 物体没有修改器不显示
    if obj.type != "MESH":
        return  # 不是网格的不显示
    if not obj.data.shape_keys:
        return  # 没有形态键不显示
    if len(obj.data.shape_keys.key_blocks) == 1:
        return  # 只有一个基型的不显示

    row = layout.row(align=True)
    row.alert = True
    row.label(text="形态键修改器共存")
    row.alert = False
    row.operator(OP_applyShowingModifiersKeepShapekeys.bl_idname,
                 text="应用")


def draw_in_DATA_PT_shape_keys(self, context: Context):
    """属性形态键下"""
    layout: bpy.types.UILayout = self.layout
    layout.use_property_decorate = False  # 禁用关键帧动画


    row = layout.row(align=True)
    row.prop(context.scene,"hoShapekeyTools_open_menu",text="启用Hotools拓展",toggle=True)
    if not context.scene.hoShapekeyTools_open_menu:
        return

    row = layout.row(align=True)
    row.scale_y = 2.0
    if context.scene.hoShapekeyTools_control_shape_key_listener:
        row.alert = True
    row.prop(context.scene,"hoShapekeyTools_control_shape_key_listener",text="全局多物体同步",toggle=True,icon="FILE_REFRESH")
    row.alert =False

    # # 绘制开关编号显示
    # area = context.area
    # if area.type == 'VIEW_3D':
    #     space = area.spaces.active
    #     if space.type == 'VIEW_3D':
    #         overlay = space.overlay
    #         row.prop(overlay, "show_extra_indices",
    #                  text="", icon="INFO_LARGE", icon_only=True, toggle=True)
    # row.prop(context.scene, "hoShapekeyTools_chooseVertexByIndex", text="")
    # row.operator(OP_SelectVertexByIndex.bl_idname, text="选择索引顶点")

    # 形态键操作
    col = layout.column(align=True)
    col.scale_y = 2.0
    row = col.row(align=True)
    row.prop(context.scene,"hoShapekeyTools_copy_is_abs",text="",icon="QUESTION",icon_only=True)
    is_abs = context.scene.hoShapekeyTools_copy_is_abs
    op = row.operator(OP_ShapekeyTools_copyShapekey2ShearPlate.bl_idname,text="复制",icon="COPYDOWN")
    op.is_abs = is_abs
    op = row.operator(OP_ShapekeyTools_importShapekeyFromShearPlate.bl_idname,text="粘贴",icon="PASTEDOWN")
    op.is_abs = is_abs
    if not is_abs:
        row.operator(OP_ShapekeyTools_importShapekeyFromShearPlate_Relative_add.bl_idname,text="叠加",icon="FUND")


    row = layout.row(align=True)
    row.scale_y = 2.0
    split = row.split()
    split.scale_x = 3.0
    row.operator(OP_ClearAllShapekeyValue.bl_idname,
                 text="全键归零", icon="FUND")
    row.operator(OP_SetBasisShapekeyActive.bl_idname,
                 text="选中基型", icon="FUND")
    

    # 形态键混合/清除
    row = layout.row(align=True)
    row.scale_y = 2.0
    obj = context.object
    if obj and obj.type == 'MESH' and obj.data.shape_keys:
        row.prop_search(context.scene, "hoShapekeyTools_selectedBaseShapekey", obj.data.shape_keys,
                        "key_blocks", text="")
        row.operator(OP_SelectShapekeyOffsetedVerticex.bl_idname,
                     text="选择位移点")
        row.operator(OP_SmoothShapekey.bl_idname,text="平滑")
        row.operator(
            OP_RemoveSelectedVerticesInActiveShapekey.bl_idname, text="清除/替换").shape_key = context.scene.hoShapekeyTools_selectedBaseShapekey
    # 对称形态键
    row = layout.row(align=True)
    row.scale_y = 2.0
    row.prop(context.scene, "hoShapekeyTools_mirrorAxis", text="")
    row.prop(context.scene, "hoShapekeyTools_mirrorTolerance", text="")
    op = row.operator(OP_balanceShapekey.bl_idname,
                      text="镜像/对称", icon="MOD_MIRROR")
    op.axis = context.scene.hoShapekeyTools_mirrorAxis
    op.tolerance = context.scene.hoShapekeyTools_mirrorTolerance

    # 生成镜像形态键
    row = layout.row(align=True)
    row.scale_y = 2.0
    split = row.split(align=True)
    split.scale_x = 1.5
    split.prop(context.scene, "hoShapekeyTools_isMirrorRename",
               icon="SORTALPHA", icon_only=True)
    split.prop(context.scene, "hoShapekeyTools_isMirrorOverwrite",
               icon="ERROR", icon_only=True)

    op = row.operator(OP_GenerateMirroredShapekey.bl_idname,
                      text="生成镜像键", icon="ARROW_LEFTRIGHT",)
    op.auto_rename = context.scene.hoShapekeyTools_isMirrorRename
    op.overwrite = context.scene.hoShapekeyTools_isMirrorOverwrite

    row = layout.row(align=True)
    row.scale_y = 2.0
    row.prop(context.scene,
             "hoShapekeyTools_splitShapeKey_namesuffix_viewLeft", text="")
    row.prop(context.scene,
             "hoShapekeyTools_splitShapeKey_namesuffix_viewRight", text="")
    op = row.operator(OP_SplitShapekey.bl_idname,
                      text="生成拆分键", icon="UNLINKED")
    op.suffix_viewLeft = context.scene.hoShapekeyTools_splitShapeKey_namesuffix_viewLeft
    op.suffix_viewRight = context.scene.hoShapekeyTools_splitShapeKey_namesuffix_viewRight


def draw_in_MESH_MT_shape_key_context_menu(self, context):
    """形态键下拉菜单"""
    layout: bpy.types.UILayout = self.layout
    layout.operator(OP_RemoveEmptyShapekeys.bl_idname,text="删除空键",icon="X")
    layout.operator(OP_deleteUnusingShapeKeys.bl_idname,icon="X")
    layout.operator(OP_AddShapekeysByTemplate.bl_idname,icon="ADD")
    layout.operator(OP_ShapekeyTools_CopyList2selectedObjects.bl_idname,icon="FORWARD")
    
    


cls = [PG_ShapeKeyTools_ListenerCache,
    OP_SelectVertexByIndex, OP_SelectShapekeyOffsetedVerticex,
    OP_RemoveEmptyShapekeys, OP_RemoveSelectedVerticesInActiveShapekey,
    OP_SmoothShapekey,OP_balanceShapekey, OP_GenerateMirroredShapekey, OP_SplitShapekey,
    OP_ClearAllShapekeyValue, OP_SetBasisShapekeyActive,
    OP_applyShowingModifiersKeepShapekeys, OP_ApplyArmatureModifiersKeepShapekeys,
    OP_deleteUnusingShapeKeys, OP_AddShapekeysByTemplate,
    OP_ShapekeyTools_copyShapekey2ShearPlate,OP_ShapekeyTools_importShapekeyFromShearPlate,
    OP_ShapekeyTools_importShapekeyFromShearPlate_Relative_add,OP_ShapekeyTools_CopyList2selectedObjects
]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()
    bpy.types.DATA_PT_modifiers.append(draw_in_DATA_PT_modifiers)
    bpy.types.DATA_PT_shape_keys.append(draw_in_DATA_PT_shape_keys)
    bpy.types.MESH_MT_shape_key_context_menu.append(
        draw_in_MESH_MT_shape_key_context_menu)


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
    bpy.types.DATA_PT_modifiers.remove(draw_in_DATA_PT_modifiers)
    bpy.types.DATA_PT_shape_keys.remove(draw_in_DATA_PT_shape_keys)
    bpy.types.MESH_MT_shape_key_context_menu.remove(
        draw_in_MESH_MT_shape_key_context_menu)

 # type: ignore
