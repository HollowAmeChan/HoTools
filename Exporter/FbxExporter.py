import bpy
import os
import mathutils
import math
import traceback
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


def report_exception(operator, prefix, exc):
    message = f"{prefix}: {type(exc).__name__}: {exc}"
    print(f"[HoTools FBX] {message}")
    traceback.print_exc()
    operator.report({"ERROR"}, message)


def reset_export_undo():
    bpy.ops.ed.undo_push(message="")
    bpy.ops.ed.undo()
    bpy.ops.ed.undo_push(message="Export Hotools FBX")


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
    @staticmethod
    def restore_selection(selection, active_object=None):
        bpy.ops.object.select_all(action='DESELECT')
        for ob in selection:
            if ob.name in bpy.context.view_layer.objects:
                ob.select_set(True)
        if active_object and active_object.name in bpy.context.view_layer.objects:
            bpy.context.view_layer.objects.active = active_object
    @staticmethod
    def set_armatures_pose_position(armature_objects, pose_position):
        state = []
        for ob in armature_objects:
            armature = ob.data
            if not hasattr(armature, "pose_position"):
                continue
            state.append((armature.name, armature.pose_position))
            armature.pose_position = pose_position
        return state
    @staticmethod
    def restore_armatures_pose_position(state):
        for armature_name, pose_position in state:
            armature = bpy.data.armatures.get(armature_name)
            if armature is None:
                continue
            try:
                armature.pose_position = pose_position
            except TypeError:
                pass
    @staticmethod
    def remove_hidden_modifiers(objects):
        removed = []
        failed = []

        for ob in objects:
            modifiers = getattr(ob, "modifiers", None)
            if not modifiers:
                continue

            for mod in list(modifiers):
                if getattr(mod, "show_viewport", True):
                    continue

                mod_name = mod.name
                try:
                    modifiers.remove(mod)
                    removed.append((ob.name, mod_name))
                except Exception as exc:
                    failed.append((ob.name, mod_name, exc))

        return removed, failed
    @staticmethod
    def iter_bone_collections(armature):
        collections = getattr(armature, "collections_all", None)
        if collections is not None:
            return list(collections)

        result = []
        pending = list(getattr(armature, "collections", []))
        while pending:
            collection = pending.pop(0)
            result.append(collection)
            pending.extend(getattr(collection, "children", []))
        return result
    @staticmethod
    def unhide_armature_bones(armature):
        state = {
            "armature": armature,
            "bones": [],
            "collections": [],
        }

        for bone in armature.bones:
            if hasattr(bone, "hide"):
                state["bones"].append((bone.name, bone.hide))
                bone.hide = False

        for collection in FBXExporter.iter_bone_collections(armature):
            collection_state = {}
            try:
                collection_state["is_visible"] = collection.is_visible
                collection.is_visible = True
            except (AttributeError, TypeError):
                pass
            try:
                collection_state["is_solo"] = collection.is_solo
                collection.is_solo = False
            except (AttributeError, TypeError):
                pass
            if collection_state:
                state["collections"].append((collection.name, collection_state))

        return state
    @staticmethod
    def restore_armature_bone_visibility(state):
        armature = state["armature"]

        for collection_name, collection_state in state["collections"]:
            collection = getattr(armature, "collections_all", {}).get(collection_name)
            if collection is None:
                continue
            for attr, value in collection_state.items():
                try:
                    setattr(collection, attr, value)
                except (AttributeError, TypeError, ReferenceError):
                    pass

        for bone_name, was_hidden in state["bones"]:
            bone = armature.bones.get(bone_name)
            if bone is None:
                continue
            try:
                bone.hide = was_hidden
            except ReferenceError:
                pass
    @staticmethod
    def clear_armatures_bone_rotation(armature_objects, selection, active_object):
        view_layer_armatures = [ob for ob in armature_objects if ob.name in bpy.context.view_layer.objects]
        if not view_layer_armatures:
            return

        visibility_states = []
        try:
            bpy.ops.object.select_all(action='DESELECT')
            for ob in view_layer_armatures:
                visibility_states.append(FBXExporter.unhide_armature_bones(ob.data))
                ob.data.use_mirror_x = False #!!!必须关闭所有骨架的对称，否则处理会有底层逻辑上的问题
                ob.select_set(True)
            bpy.context.view_layer.objects.active = view_layer_armatures[0]
            bpy.ops.object.mode_set(mode="EDIT")
            try:
                for ob in view_layer_armatures:
                    FBXExporter.clearArmatureBoneRoration(ob)
            finally:
                if bpy.ops.object.mode_set.poll():
                    bpy.ops.object.mode_set(mode="OBJECT")
        finally:
            for state in reversed(visibility_states):
                FBXExporter.restore_armature_bone_visibility(state)
            FBXExporter.restore_selection(selection, active_object)


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
    removeHiddenModifiers:BoolProperty(name="删除隐藏修改器",description="导出前临时删除视口隐藏的修改器，用于绕过隐藏 GN 阻塞形态键应用修改器的问题",default=True) # type: ignore

    def getParams(self,context, report_errors=True):
        # 寻找所选预设脚本文件
        preset_file = None
        for p in bpy.utils.preset_paths("operator/export_scene.fbx"):
            fp = os.path.join(p, self.preset + ".py")
            if os.path.isfile(fp):
                preset_file = fp
                break
        if not preset_file:
            if report_errors:
                self.report({'ERROR'}, f"找不到预设文件: {self.preset}.py")
            return None

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

        selection = list(bpy.context.selected_objects)
        active_object = bpy.context.view_layer.objects.active
        pose_position_state = []
        removed_hidden_modifiers = []

        #准备操作，全显场景中的对象与集合，并且全选
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")

        FBXExporter.unhide_collections(col=bpy.context.view_layer.layer_collection)
        FBXExporter.unhide_objects()
        
        try:
            pose_position_state = FBXExporter.set_armatures_pose_position(armature_objects, "REST")

            if self.removeHiddenModifiers:
                removed_hidden_modifiers, failed_hidden_modifiers = FBXExporter.remove_hidden_modifiers(bpy.context.scene.objects)
                if failed_hidden_modifiers:
                    print("[HoTools FBX] Failed to remove hidden modifiers:")
                    for ob_name, mod_name, exc in failed_hidden_modifiers:
                        print(f"  {ob_name}.{mod_name}: {type(exc).__name__}: {exc}")
                    self.report({"WARNING"}, f"{len(failed_hidden_modifiers)} 个隐藏修改器临时删除失败，详见控制台")

            # 修复骨骼旋转
            if self.cheekBoneKeepRotation and armature_objects !=[]:
                FBXExporter.clear_armatures_bone_rotation(armature_objects, selection, active_object)


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
            FBXExporter.restore_selection(selection, active_object)

            # 导出
            params = self.getParams(context)
            if params is None:
                raise RuntimeError("FBX 预设参数无效")
            bpy.ops.export_scene.fbx(**params)

        except Exception as e:
            report_exception(self, "导出失败", e)
            try:
                reset_export_undo()
                FBXExporter.restore_armatures_pose_position(pose_position_state)
            except Exception as reset_error:
                FBXExporter.restore_armatures_pose_position(pose_position_state)
                report_exception(self, "导出后重置场景失败", reset_error)
            return {'CANCELLED'}

        # 重置场景
        try:
            reset_export_undo()
            FBXExporter.restore_armatures_pose_position(pose_position_state)
        except Exception as e:
            FBXExporter.restore_armatures_pose_position(pose_position_state)
            report_exception(self, "导出后重置场景失败", e)
            return {'CANCELLED'}
        if removed_hidden_modifiers:
            self.report({"INFO"}, f"导出成功，临时删除隐藏修改器 {len(removed_hidden_modifiers)} 个")
        else:
            self.report({"INFO"},"导出成功")
        return {'FINISHED'}

    

    @classmethod
    def poll(cls, context):
        return True
    

    def execute(self, context):
        return self.export_fbx(context)
    def draw(self, context):
        layout = self.layout
        layout.prop(self,"preset")
        layout.label(text="↑↑↑此处预设与blender fbx导出共享↑↑↑")
        layout.label(text="==================================")
        layout.label(text="若没有选项，需要手动保存一个预设")
        layout.label(text="在blender原本的fbx导出界面添加预设")
        layout.label(text="==================================")
        layout.prop(self,"cheekBoneKeepRotation")
        layout.prop(self,"removeHiddenModifiers")
        
        params = self.getParams(context, report_errors=False)
        if params:
            for p in params.items():
                layout.label(text=(str(p[0]) + " = " + str(p[1])))

class OP_FinalFBXExport_only_preprocess(Operator):
    bl_idname = "ho.final_fbx_export_only_preprocess"
    bl_label = "Hotools导出FBX(仅预处理)"
    bl_description = ""
    bl_options = {'REGISTER', 'UNDO'}

    cheekBoneKeepRotation:BoolProperty(name="检查保留旋转",description="检查骨骼的hotools保留旋转属性,关闭的骨骼将会清空旋转",default=False) # type: ignore


    def export_fbx_preprocess(self,context):
        global hidden_collections
        global hidden_objects
        global disabled_collections
        global disabled_objects

        root_objects = [item for item in bpy.data.objects if (item.type == "EMPTY" or item.type == "MESH" or item.type == "ARMATURE" or item.type == "FONT" or item.type == "CURVE" or item.type == "SURFACE") and not item.parent]
        armature_objects = [item for item in bpy.data.objects if item.type == "ARMATURE"]
        
        hidden_collections = []
        hidden_objects = []
        disabled_collections = []
        disabled_objects = []

        selection = list(bpy.context.selected_objects)
        active_object = bpy.context.view_layer.objects.active

        #准备操作，全显场景中的对象与集合，并且全选
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")

        FBXExporter.unhide_collections(col=bpy.context.view_layer.layer_collection)
        FBXExporter.unhide_objects()
        pose_position_state = FBXExporter.set_armatures_pose_position(armature_objects, "REST")
        try:
            # 修复骨骼旋转
            if self.cheekBoneKeepRotation and armature_objects !=[]:
                FBXExporter.clear_armatures_bone_rotation(armature_objects, selection, active_object)


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
            FBXExporter.restore_selection(selection, active_object)
        finally:
            FBXExporter.restore_armatures_pose_position(pose_position_state)

    

    @classmethod
    def poll(cls, context):
        return True
    
    def execute(self, context):
        try:
            self.export_fbx_preprocess(context)
        except Exception as e:
            report_exception(self, "预处理失败", e)
            return {'CANCELLED'}
        self.report({"INFO"}, "预处理完成")
        return {'FINISHED'}
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self,"cheekBoneKeepRotation")


def OPF_FinalFBXExport(self, context):
    self.layout.operator_context = 'INVOKE_DEFAULT'
    self.layout.operator(OP_FinalFBXExport.bl_idname, text="Hotools-FBX(.fbx)")
    self.layout.operator(OP_FinalFBXExport_only_preprocess.bl_idname, text="Hotools-FBX(OnlyPreProcess)")


cls = [
    OP_FinalFBXExport,OP_FinalFBXExport_only_preprocess
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
