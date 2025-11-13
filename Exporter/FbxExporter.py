import bpy
import os
import mathutils
import math
from bpy.types import PropertyGroup, UIList, Operator, Panel
from mathutils import Vector
from types import SimpleNamespace
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty


def reg_props():
    return


def ureg_props():
    return


'''https://github.com/EdyJ/blender-to-unity-fbx-exporter/blob/master/blender-to-unity-fbx-exporter.py#L258'''

#全局缓存
hidden_collections = []
hidden_objects = []
disabled_collections = []
disabled_objects = []

class FBXExporter:
    @staticmethod
    def unhide_collections(col):
        global hidden_collections
        global disabled_collections

        # No need to unhide excluded collections. Their objects aren't included in current view layer.
        if col.exclude:
            return

        # Find hidden child collections and unhide them
        hidden = [item for item in col.children if not item.exclude and item.hide_viewport]
        for item in hidden:
            item.hide_viewport = False

        # Add them to the list so they could be restored later
        hidden_collections.extend(hidden)

        # Same with the disabled collections
        disabled = [item for item in col.children if not item.exclude and item.collection.hide_viewport]
        for item in disabled:
            item.collection.hide_viewport = False

        disabled_collections.extend(disabled)

        # Recursively unhide child collections
        for item in col.children:
            FBXExporter.unhide_collections(item)
    @staticmethod
    def unhide_objects():
        global hidden_objects
        global disabled_objects

        view_layer_objects = [ob for ob in bpy.data.objects if ob.name in bpy.context.view_layer.objects]

        for ob in view_layer_objects:
            if ob.hide_get():
                hidden_objects.append(ob)
                ob.hide_set(False)
            if ob.hide_viewport:
                disabled_objects.append(ob)
                ob.hide_viewport = False
    @staticmethod
    def reset_parent_inverse(ob):
        if (ob.parent):
            mat_world = ob.matrix_world.copy()
            ob.matrix_parent_inverse.identity()
            ob.matrix_basis = ob.parent.matrix_world.inverted() @ mat_world
    @staticmethod
    def apply_rotation(ob):
        bpy.ops.object.select_all(action='DESELECT')
        ob.select_set(True)
        bpy.ops.object.transform_apply(location = False, rotation = True, scale = False)
    @staticmethod
    def fix_object(ob):
        # Only fix objects in current view layer
        if ob.name in bpy.context.view_layer.objects:

            # Reset parent's inverse so we can work with local transform directly
            FBXExporter.reset_parent_inverse(ob)

            # Create a copy of the local matrix and set a pure X-90 matrix
            mat_original = ob.matrix_local.copy()
            ob.matrix_local = mathutils.Matrix.Rotation(math.radians(-90.0), 4, 'X')

            # Apply the rotation to the object
            FBXExporter.apply_rotation(ob)

            # Reapply the previous local transform with an X+90 rotation
            ob.matrix_local = mat_original @ mathutils.Matrix.Rotation(math.radians(90.0), 4, 'X')

        # Recursively fix child objects in current view layer.
        # Children may be in the current view layer even if their parent isn't.
        for child in ob.children:
            FBXExporter.fix_object(child)
    @staticmethod
    def clearArmatureBoneRoration(ob):
        ob = ob.data
        notKeepRotation_bones = [b for b in ob.edit_bones if not ob.bones[b.name].hotools_boneprops.keepRotation]
        for bone in notKeepRotation_bones:
            for cb in bone.children:#清空所有子骨的相连，防止影响子骨头部位置
                cb.use_connect = False
            original_length = (bone.tail - bone.head).length
            bone.roll = 0
            new_tail = bone.head + Vector((0, 0, original_length))
            bone.tail = new_tail

fbx_presets = []

class OP_FinalFBXExport(Operator,ExportHelper):
    bl_idname = "ho.final_fbx_export"
    bl_label = "Hotools导出FBX"
    bl_description = ""
    bl_options = {'REGISTER', 'UNDO'}

    # ExportHelper 属性：文件后缀与过滤器 :contentReference[oaicite:1]{index=1}
    filename_ext = ".fbx"
    filter_glob: bpy.props.StringProperty(
        default="*.fbx", options={'HIDDEN'}, maxlen=255,
    ) # type: ignore

    
    def get_fbx_presets(self,context):
        '''
        利用原生fbx导出的预设
        扫描所有 operator/export_scene.fbx 预设目录，返回 EnumProperty items 列表
        '''
        presets = set()
        for p in bpy.utils.preset_paths("operator/export_scene.fbx"):
            if os.path.isdir(p):
                for fn in os.listdir(p):
                    if fn.endswith(".py"):
                        presets.add(os.path.splitext(fn)[0])
        global fbx_presets
        fbx_presets = [(name, name, "") for name in presets]
        return fbx_presets
    
    preset: bpy.props.EnumProperty(
        name="Preset",
        description="选择 FBX 导出预设",
        items=get_fbx_presets
    ) # type: ignore

    cheekBoneKeepRotation:BoolProperty(name="检查保留旋转",description="检查骨骼的hotools保留旋转属性,关闭的骨骼将会清空旋转",default=False) # type: ignore

    def getParams(self,context):
        # 寻找所选预设脚本文件
        preset_file = None
        for p in bpy.utils.preset_paths("operator/export_scene.fbx"):
            fp = os.path.join(p, self.preset + ".py")
            if os.path.isfile(fp):
                preset_file = fp
                break
        if not preset_file:
            self.report({'ERROR'}, f"找不到预设文件: {self.preset}.py")
            return {'CANCELLED'}

        # 只抽取 op.xxx 赋值语句
        with open(preset_file, 'r', encoding='utf-8') as f:
            lines = [l for l in f if l.strip().startswith("op.")]
        code = compile("".join(lines), preset_file, 'exec')

        # 解包参数
        op_props = SimpleNamespace()
        exec(code, {'op': op_props})
        params = vars(op_props)
        params['filepath'] = self.filepath
        return params
        

    def export_fbx(self,context):
        global hidden_collections
        global hidden_objects
        global disabled_collections
        global disabled_objects

        root_objects = [item for item in bpy.data.objects if (item.type == "EMPTY" or item.type == "MESH" or item.type == "ARMATURE" or item.type == "FONT" or item.type == "CURVE" or item.type == "SURFACE") and not item.parent]
        armature_objects = [item for item in bpy.data.objects if item.type == "ARMATURE"]
        

        bpy.ops.ed.undo_push(message="Prepare Hotools FBX")

        hidden_collections = []
        hidden_objects = []
        disabled_collections = []
        disabled_objects = []

        selection = bpy.context.selected_objects

        #准备操作，全显场景中的对象与集合，并且全选
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")

        FBXExporter.unhide_collections(col=bpy.context.view_layer.layer_collection)
        FBXExporter.unhide_objects()
        
        try:
            # 修复骨骼旋转
            if self.cheekBoneKeepRotation and armature_objects !=[]:
                #选择所有骨架进入编辑模式
                bpy.ops.object.select_all(action='DESELECT')
                for ob in armature_objects:
                    ob.data.use_mirror_x = False #!!!必须关闭所有骨架的对称，否则处理会有底层逻辑上的问题
                    ob.select_set(True)
                bpy.ops.object.mode_set(mode="EDIT")
                #TODO 没有处理活动物体不是骨架的问题
                #处理骨骼旋转
                for ob in armature_objects:
                    FBXExporter.clearArmatureBoneRoration(ob)
                #重置状态
                bpy.ops.object.mode_set(mode="OBJECT")
                for ob in selection:
                    ob.select_set(True)


            # 修复物体旋转（所有顶级父级物体）
            for ob in root_objects:
                FBXExporter.fix_object(ob)

            # 刷新场景防止变换没有应用
            bpy.context.view_layer.update()

            #重置物体与集合的可见可选
            for ob in hidden_objects:
                ob.hide_set(True)
            for ob in disabled_objects:
                ob.hide_viewport = True
            for col in hidden_collections:
                col.hide_viewport = True
            for col in disabled_collections:
                col.collection.hide_viewport = True

            # 重置选择状态
            bpy.ops.object.select_all(action='DESELECT')
            for ob in selection:
                ob.select_set(True)

            # 导出
            params = self.getParams(context)
            bpy.ops.export_scene.fbx(**params)

        except Exception as e:
            bpy.ops.ed.undo_push(message="")
            bpy.ops.ed.undo()
            bpy.ops.ed.undo_push(message="Export Hotools FBX")
            print(e)
            self.report({"ERROR"},"导出失败")

        # 重置场景
        bpy.ops.ed.undo_push(message="")
        bpy.ops.ed.undo()
        bpy.ops.ed.undo_push(message="Export Hotools FBX")
        self.report({"INFO"},"导出成功")

    

    @classmethod
    def poll(cls, context):
        return True
    

    def execute(self, context):
        self.export_fbx(context)
        return {'FINISHED'}
    def draw(self, context):
        layout = self.layout
        layout.prop(self,"preset")
        layout.label(text="↑↑↑此处预设与blender fbx导出共享↑↑↑")
        layout.label(text="==================================")
        layout.label(text="若没有选项，需要手动保存一个预设")
        layout.label(text="在blender原本的fbx导出界面添加预设")
        layout.label(text="==================================")
        layout.prop(self,"cheekBoneKeepRotation")
        
        params = self.getParams(context)
        if params:
            for p in params.items():
                layout.label(text=(str(p[0]) + " = " + str(p[1])))



def OPF_FinalFBXExport(self, context):
    self.layout.operator_context = 'INVOKE_DEFAULT'
    self.layout.operator(OP_FinalFBXExport.bl_idname, text="Hotools-FBX(.fbx)")


cls = [
    OP_FinalFBXExport,
]


def register():
    for i in cls:
        bpy.utils.register_class(i)

    bpy.types.TOPBAR_MT_file_export.append(OPF_FinalFBXExport)#导出菜单添加操作
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    bpy.types.TOPBAR_MT_file_export.remove(OPF_FinalFBXExport)
    ureg_props()
