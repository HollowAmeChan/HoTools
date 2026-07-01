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
    MCH_PREFIX = "MCH_"
    @staticmethod
    def build_mch_and_clear(ob):
        """给 generateMCH=True 的骨建 MCH 副本保活原始朝向，再把原骨清零竖直。

        必须在 EDIT 模式下调用。返回 {原骨名: MCH骨名} 映射，供约束/驱动转移使用。

        处理顺序（不可颠倒）：
        1. 建 MCH 副本，拷贝原骨此刻的 head/tail/roll（此时原骨尚未清零，拷到的是原始朝向），
           MCH 父级设为原骨、不形变、不相连；
        2. 把每根原骨的**原始子级**（排除刚建的 MCH）reparent 到它的 MCH，并断开相连；
        3. **最后**才把原骨清零竖直（roll=0，tail 指向 +Z）。
        """
        arm = ob.data
        edit_bones = arm.edit_bones

        # 读 data.bones 上的 generateMCH 属性（edit 模式下按名访问有效），确定待处理集合
        mch_source_names = [
            eb.name for eb in edit_bones
            if arm.bones[eb.name].hotools_boneprops.generateMCH
        ]
        if not mch_source_names:
            return {}

        name_map = {}  # 原骨名 -> MCH骨名

        # 1. 先建全部 MCH 副本，拷贝原始朝向
        for src_name in mch_source_names:
            src = edit_bones.get(src_name)
            if src is None:
                continue
            mch_name = FBXExporter.MCH_PREFIX + src_name
            existed = edit_bones.get(mch_name)
            if existed is not None:  # 防重名（理论上不该有，工程无残留）
                edit_bones.remove(existed)
            mch = edit_bones.new(mch_name)
            mch.head = src.head.copy()
            mch.tail = src.tail.copy()
            mch.roll = src.roll
            mch.use_deform = False
            mch.parent = src
            mch.use_connect = False
            name_map[src_name] = mch_name

        # 2. 把原始子级挂到 MCH 上（此时 src.children 含刚建的 MCH，需排除）
        for src_name, mch_name in name_map.items():
            src = edit_bones.get(src_name)
            mch = edit_bones.get(mch_name)
            if src is None or mch is None:
                continue
            original_children = [c for c in src.children if c.name != mch_name]
            for child in original_children:
                child.use_connect = False
                child.parent = mch

        # 3. 最后清零原骨竖直
        for src_name in name_map:
            src = edit_bones.get(src_name)
            if src is None:
                continue
            original_length = (src.tail - src.head).length
            src.roll = 0
            src.tail = src.head + Vector((0, 0, original_length))

        return name_map
    @staticmethod
    def transfer_constraints_to_mch(ob, name_map):
        """把本骨架内指向 name_map 里原骨的约束 subtarget / 驱动 bone_target 改指对应 MCH。

        只处理指向本骨架自身（target==ob）的引用，与 ConstraintAnalyzer 的单骨架范围一致；
        跨骨架引用不动。在 OBJECT 模式下调用。
        """
        if not name_map:
            return

        # 1. pose bone 约束：subtarget（及带极向目标的 pole_subtarget）
        for pbone in ob.pose.bones:
            for con in pbone.constraints:
                if getattr(con, "target", None) == ob:
                    sub = getattr(con, "subtarget", "")
                    if sub in name_map:
                        con.subtarget = name_map[sub]
                if getattr(con, "pole_target", None) == ob:
                    psub = getattr(con, "pole_subtarget", "")
                    if psub in name_map:
                        con.pole_subtarget = name_map[psub]

        # 2. 驱动器变量的 bone_target（指向本骨架的骨）
        anim = getattr(ob, "animation_data", None)
        if anim:
            for fcurve in anim.drivers:
                for var in fcurve.driver.variables:
                    for tgt in var.targets:
                        if getattr(tgt, "id", None) == ob and tgt.bone_target in name_map:
                            tgt.bone_target = name_map[tgt.bone_target]
    @staticmethod
    def export_armature_constraints_json(ob, fbx_filepath):
        """分析本骨架内的辅助骨约束并写出 Unity JSON。返回写出的文件路径，无约束则返回 None。

        约束的 target 已在 transfer_constraints_to_mch 中改指 MCH，故 analyze 读到的
        targetPath 天然指向 MCH 骨（Unity 端 RotationConstraint 的 source 即 MCH）。
        """
        from .ConstraintAnalyzer import ConstraintAnalyzer
        from .UnityConstraintMapper import UnityConstraintMapper

        constraints_list, twist_chains = ConstraintAnalyzer.analyze(ob)
        total = len(constraints_list) + sum(len(c.twist_bones) for c in twist_chains)
        if total == 0:
            return None

        json_str = UnityConstraintMapper.export_to_json(ob.name, constraints_list, twist_chains)
        base, _ = os.path.splitext(fbx_filepath)
        json_path = f"{base}_{ob.name}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(json_str)
        return json_path
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
    def remove_geometry_nodes_modifiers(objects):
        # 临时删除所有几何节点修改器（type == 'NODES'），不论是否显示在视口。
        # 几何节点会改变导出网格拓扑，且常与形态键、Unity 导入冲突；导出前整体去掉，
        # 靠导出后的 undo 恢复。返回 (已删列表, 失败列表)。
        removed = []
        failed = []

        for ob in objects:
            modifiers = getattr(ob, "modifiers", None)
            if not modifiers:
                continue

            for mod in list(modifiers):
                if mod.type != "NODES":
                    continue

                mod_name = mod.name
                try:
                    modifiers.remove(mod)
                    removed.append((ob.name, mod_name))
                except Exception as exc:
                    failed.append((ob.name, mod_name, exc))

        return removed, failed
    @staticmethod
    def remove_outline_modifiers(objects):
        # 临时删除描边修改器：实体化修改器（type == 'SOLIDIFY'）且开启了 use_flip_normals。
        # 这类修改器是翻转法线的外扩壳，属于渲染用描边，不应进入导出网格；导出后靠 undo 恢复。
        # 返回 (已删列表, 失败列表)。
        removed = []
        failed = []

        for ob in objects:
            modifiers = getattr(ob, "modifiers", None)
            if not modifiers:
                continue

            for mod in list(modifiers):
                if mod.type != "SOLIDIFY" or not getattr(mod, "use_flip_normals", False):
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
        """给各骨架建 MCH 并清零主骨，随后转移约束/驱动。返回 {骨架名: {原骨名: MCH骨名}}。

        流程：EDIT 模式建 MCH + 清零 → 回 OBJECT 模式转移约束/驱动。
        返回的映射供后续约束 JSON 导出参考（约束 subtarget 已改指 MCH）。
        """
        view_layer_armatures = [ob for ob in armature_objects if ob.name in bpy.context.view_layer.objects]
        if not view_layer_armatures:
            return {}

        name_maps = {}  # {骨架名: {原骨名: MCH骨名}}
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
                    name_maps[ob.name] = FBXExporter.build_mch_and_clear(ob)
            finally:
                if bpy.ops.object.mode_set.poll():
                    bpy.ops.object.mode_set(mode="OBJECT")

            # 回 OBJECT 模式后转移约束/驱动（subtarget/bone_target 改指 MCH）
            for ob in view_layer_armatures:
                FBXExporter.transfer_constraints_to_mch(ob, name_maps.get(ob.name, {}))
        finally:
            for state in reversed(visibility_states):
                FBXExporter.restore_armature_bone_visibility(state)
            FBXExporter.restore_selection(selection, active_object)

        return name_maps


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

    generateMCHBones:BoolProperty(name="生成MCH骨(动捕适配)",description="对勾选了generateMCH的骨:导出时清零竖直以适配动捕/humanoid,同时生成MCH_前缀副本保留原始朝向,子级挂到MCH上、指向该骨的约束/驱动改指MCH。仅存在于导出的FBX,工程不留痕",default=False) # type: ignore
    exportBoneConstraint:BoolProperty(name="导出骨骼约束(JSON)",description="导出各骨架内的HoTools辅助骨约束(fan/twist)为Unity可用的JSON,与FBX同目录同名(附骨架名后缀)。约束目标已随MCH转移",default=False) # type: ignore
    fixObjectTransform:BoolProperty(name="矫正物体变换",description="执行原有的物体变换/旋转矫正预处理",default=True) # type: ignore
    removeHiddenModifiers:BoolProperty(name="删除隐藏修改器",description="导出前临时删除视口隐藏的修改器，用于绕过隐藏 GN 阻塞形态键应用修改器的问题",default=True) # type: ignore
    ignoreGeometryNodes:BoolProperty(name="忽略几何节点",description="导出前临时删除所有几何节点修改器，避免几何节点改变导出网格拓扑；导出后自动恢复",default=True) # type: ignore
    ignoreOutlineModifiers:BoolProperty(name="忽略描边修改器",description="导出前临时删除描边修改器（开启了翻转法线的实体化修改器）；导出后自动恢复",default=True) # type: ignore

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
        exported_json = []

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

            if self.ignoreGeometryNodes:
                removed_gn, failed_gn = FBXExporter.remove_geometry_nodes_modifiers(bpy.context.scene.objects)
                if failed_gn:
                    print("[HoTools FBX] Failed to remove geometry nodes modifiers:")
                    for ob_name, mod_name, exc in failed_gn:
                        print(f"  {ob_name}.{mod_name}: {type(exc).__name__}: {exc}")
                    self.report({"WARNING"}, f"{len(failed_gn)} 个几何节点修改器临时删除失败，详见控制台")

            if self.ignoreOutlineModifiers:
                removed_outline, failed_outline = FBXExporter.remove_outline_modifiers(bpy.context.scene.objects)
                if failed_outline:
                    print("[HoTools FBX] Failed to remove outline modifiers:")
                    for ob_name, mod_name, exc in failed_outline:
                        print(f"  {ob_name}.{mod_name}: {type(exc).__name__}: {exc}")
                    self.report({"WARNING"}, f"{len(failed_outline)} 个描边修改器临时删除失败，详见控制台")

            # 生成 MCH 骨并清零主骨（动捕/humanoid 适配）；返回各骨架的 {原骨名: MCH名} 映射
            mch_name_maps = {}
            if self.generateMCHBones and armature_objects != []:
                mch_name_maps = FBXExporter.clear_armatures_bone_rotation(
                    armature_objects, selection, active_object
                )

            # 修复物体旋转（所有顶级父级物体）
            if self.fixObjectTransform:
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

            # 导出约束 JSON（约束 target 已在上一步改指 MCH，targetPath 天然指向 MCH）
            if self.exportBoneConstraint:
                for ob in armature_objects:
                    if ob.name not in bpy.context.view_layer.objects:
                        continue
                    json_path = FBXExporter.export_armature_constraints_json(ob, self.filepath)
                    if json_path:
                        exported_json.append(json_path)

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
        elif exported_json:
            self.report({"INFO"}, f"导出成功，同时导出约束 JSON {len(exported_json)} 个")
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
        layout.use_property_split = True
        layout.use_property_decorate = False

        preset_box = layout.box()
        preset_box.label(text="FBX 预设")
        preset_box.prop(self, "preset", text="预设")
        hint_col = preset_box.column(align=True)
        hint_col.label(text="共享BlenderFBX导出预设")
        hint_col.label(text="没有选项时，请在BlenderFBX面板保存预设")

        option_box = layout.box()
        option_box.label(text="预处理")
        option_col = option_box.column(align=True)
        option_col.prop(self, "generateMCHBones")
        option_col.prop(self, "exportBoneConstraint")
        option_col.prop(self, "fixObjectTransform")
        option_col.prop(self, "removeHiddenModifiers")
        option_col.prop(self, "ignoreGeometryNodes")
        option_col.prop(self, "ignoreOutlineModifiers")
        
        params = self.getParams(context, report_errors=False)
        params_box = layout.box()
        params_box.label(text="当前预设参数")
        if params:
            params_col = params_box.column(align=True)
            params_col.enabled = False
            for name, value in params.items():
                row = params_col.row(align=True)
                split = row.split(factor=0.36)
                split.label(text=str(name))
                split.label(text=str(value))
        else:
            params_box.label(text="未读取到预设参数")

class OP_FinalFBXExport_only_preprocess(Operator):
    bl_idname = "ho.final_fbx_export_only_preprocess"
    bl_label = "Hotools导出FBX(仅预处理)"
    bl_description = ""
    bl_options = {'REGISTER', 'UNDO'}

    generateMCHBones:BoolProperty(name="生成MCH骨(动捕适配)",description="对 generateMCH=True 的骨清零竖直并生成 MCH_ 副本保活原始朝向;仅预处理模式不会自动撤销,MCH 会留在工程里供检视,需手动 Ctrl+Z 还原",default=False) # type: ignore
    fixObjectTransform:BoolProperty(name="矫正物体变换",description="执行原有的物体变换/旋转矫正预处理",default=True) # type: ignore
    ignoreGeometryNodes:BoolProperty(name="忽略几何节点",description="导出前临时删除所有几何节点修改器（type==NODES），避免几何节点改变导出网格；预处理结束前生效",default=True) # type: ignore
    ignoreOutlineModifiers:BoolProperty(name="忽略描边修改器",description="导出前临时删除描边修改器（开启了翻转法线的实体化修改器）；预处理结束前生效",default=True) # type: ignore


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
            if self.ignoreGeometryNodes:
                removed_gn, failed_gn = FBXExporter.remove_geometry_nodes_modifiers(bpy.context.scene.objects)
                if failed_gn:
                    print("[HoTools FBX] Failed to remove geometry nodes modifiers:")
                    for ob_name, mod_name, exc in failed_gn:
                        print(f"  {ob_name}.{mod_name}: {type(exc).__name__}: {exc}")
                    self.report({"WARNING"}, f"{len(failed_gn)} 个几何节点修改器临时删除失败，详见控制台")

            if self.ignoreOutlineModifiers:
                removed_outline, failed_outline = FBXExporter.remove_outline_modifiers(bpy.context.scene.objects)
                if failed_outline:
                    print("[HoTools FBX] Failed to remove outline modifiers:")
                    for ob_name, mod_name, exc in failed_outline:
                        print(f"  {ob_name}.{mod_name}: {type(exc).__name__}: {exc}")
                    self.report({"WARNING"}, f"{len(failed_outline)} 个描边修改器临时删除失败，详见控制台")

            # 生成 MCH 骨并清零主骨（动捕/humanoid 适配）；仅预处理模式不撤销，MCH 留在工程供检视
            if self.generateMCHBones and armature_objects !=[]:
                FBXExporter.clear_armatures_bone_rotation(armature_objects, selection, active_object)


            # 修复物体旋转（所有顶级父级物体）
            if self.fixObjectTransform:
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
        layout.use_property_split = True
        layout.use_property_decorate = False

        option_box = layout.box()
        option_box.label(text="预处理")
        option_col = option_box.column(align=True)
        option_col.prop(self, "generateMCHBones")
        option_col.prop(self, "fixObjectTransform")
        option_col.prop(self, "ignoreGeometryNodes")
        option_col.prop(self, "ignoreOutlineModifiers")


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
