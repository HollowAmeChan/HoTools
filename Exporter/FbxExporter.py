import bpy
import os
import mathutils
import math
import traceback
from bpy.types import PropertyGroup, UIList, Operator, Panel
from mathutils import Vector
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
    def get_weighted_bone_names(armature_ob):
        """采集本骨架下"有权重"的骨名集合（供叶骨判定用）。

        遍历所有被该骨架形变的网格（骨架修改器指向本骨架，或以 ARMATURE 方式父级到本骨架），
        只要某骨名对应的顶点组存在 weight>0 的顶点，就算该骨有权重。必须在 OBJECT 模式采集。
        """
        bone_names = {b.name for b in armature_ob.data.bones}
        weighted = set()
        for mesh_ob in bpy.data.objects:
            if mesh_ob.type != 'MESH':
                continue
            # 判断该网格是否被本骨架形变
            deformed = any(
                mod.type == 'ARMATURE' and mod.object == armature_ob
                for mod in mesh_ob.modifiers
            )
            if not deformed and mesh_ob.parent == armature_ob and mesh_ob.parent_type == 'ARMATURE':
                deformed = True
            if not deformed or not mesh_ob.vertex_groups:
                continue

            group_names = {i: vg.name for i, vg in enumerate(mesh_ob.vertex_groups)}
            for v in mesh_ob.data.vertices:
                for g in v.groups:
                    gname = group_names.get(g.group)
                    if gname in bone_names and gname not in weighted:
                        try:
                            if g.weight > 0.0:
                                weighted.add(gname)
                        except (RuntimeError, AttributeError):
                            continue
            # 全部骨都已确认有权重则提前结束
            if bone_names <= weighted:
                break
        return weighted

    LEAF_SUFFIX = "_end"
    @staticmethod
    def build_leaf_bones(ob, weighted_names):
        """给无子级且有权重的骨末端补叶骨。必须在 EDIT 模式下调用。

        规则：
        - 只处理无子级的骨（先快照目标，避免边加边处理）；
        - 只处理 weighted_names 里的骨（无权重的骨不加）；
        - 叶骨长度为主体骨长度的一半，沿主体骨方向延伸（FBX 导出其实不在意长度，但仍写正确值）；
        - 叶骨归入主骨所属的**所有**骨骼集合（自带 add_leaf_bones 不处理集合，这是自实现的主因；
          集合 JSON 导出须排在本步之后才能收录叶骨）；
        - 叶骨 use_deform=False，不写任何 HoTools 属性，generateMCH 保持默认关闭
          （因此后续 MCH 步骤不会处理它；本步在 MCH 之前执行）。
        """
        edit_bones = ob.data.edit_bones
        targets = [
            eb.name for eb in edit_bones
            if not eb.children and eb.name in weighted_names
        ]
        for name in targets:
            eb = edit_bones.get(name)
            if eb is None:
                continue
            vec = eb.tail - eb.head
            length = vec.length
            if length <= 0.0:
                continue
            # 先取主骨所属的骨骼集合（Blender 4.0+；低版本无 collections 属性时为空）
            member_collections = list(getattr(eb, "collections", []) or [])
            leaf = edit_bones.new(name + FBXExporter.LEAF_SUFFIX)
            leaf.head = eb.tail.copy()
            leaf.tail = eb.tail + vec.normalized() * (length * 0.5)
            leaf.roll = eb.roll
            leaf.parent = eb
            leaf.use_connect = True
            leaf.use_deform = False
            # 叶骨与主骨同属一批骨骼集合
            for bcoll in member_collections:
                try:
                    bcoll.assign(leaf)
                except (RuntimeError, AttributeError):
                    continue

    @staticmethod
    def add_leaf_bones_to_armatures(armature_objects, selection, active_object):
        """给各骨架的无子级有权重骨补叶骨。须在 MCH 步骤之前调用。

        先在 OBJECT 模式采集每个骨架的有权重骨名，再进 EDIT 模式建叶骨。
        """
        view_layer_armatures = [ob for ob in armature_objects if ob.name in bpy.context.view_layer.objects]
        if not view_layer_armatures:
            return

        # OBJECT 模式采集有权重骨名（EDIT 模式下 data.bones/网格权重读取不可靠）
        weighted_maps = {
            ob.name: FBXExporter.get_weighted_bone_names(ob)
            for ob in view_layer_armatures
        }

        visibility_states = []
        try:
            bpy.ops.object.select_all(action='DESELECT')
            for ob in view_layer_armatures:
                visibility_states.append(FBXExporter.unhide_armature_bones(ob.data))
                ob.data.use_mirror_x = False  # 关对称，避免建骨受镜像干扰
                ob.select_set(True)
            bpy.context.view_layer.objects.active = view_layer_armatures[0]
            bpy.ops.object.mode_set(mode="EDIT")
            try:
                for ob in view_layer_armatures:
                    FBXExporter.build_leaf_bones(ob, weighted_maps.get(ob.name, set()))
            finally:
                if bpy.ops.object.mode_set.poll():
                    bpy.ops.object.mode_set(mode="OBJECT")
        finally:
            for state in reversed(visibility_states):
                FBXExporter.restore_armature_bone_visibility(state)
            FBXExporter.restore_selection(selection, active_object)

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
    def export_armature_constraints_json(ob, fbx_filepath, suffix):
        """分析本骨架内的辅助骨约束并写出 Unity JSON。返回写出的文件路径，无约束则返回 None。

        约束的 target 已在 transfer_constraints_to_mch 中改指 MCH，故 analyze 读到的
        targetPath 天然指向 MCH 骨（Unity 端 RotationConstraint 的 source 即 MCH）。
        文件名为 <fbx名>_<骨架名><suffix>.json，suffix 用于与集合 JSON 区分避免冲突。
        """
        from .ConstraintAnalyzer import ConstraintAnalyzer
        from .UnityConstraintMapper import UnityConstraintMapper

        constraints_list, twist_chains = ConstraintAnalyzer.analyze(ob)
        total = len(constraints_list) + sum(len(c.twist_bones) for c in twist_chains)
        if total == 0:
            return None

        json_str = UnityConstraintMapper.export_to_json(ob.name, constraints_list, twist_chains)
        base, _ = os.path.splitext(fbx_filepath)
        json_path = f"{base}_{ob.name}{suffix}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(json_str)
        return json_path
    @staticmethod
    def export_armature_collections_json(ob, fbx_filepath, suffix):
        """分析本骨架的骨骼集合并写出 JSON。返回写出的文件路径，无集合则返回 None。

        文件名为 <fbx名>_<骨架名><suffix>.json，suffix 用于与约束 JSON 区分避免冲突。
        """
        from .BoneCollectionExporter import BoneCollectionExporter

        collections_list = BoneCollectionExporter.build_collections_list(ob.data)
        if not collections_list:
            return None

        base, _ = os.path.splitext(fbx_filepath)
        json_path = f"{base}_{ob.name}{suffix}.json"
        BoneCollectionExporter.export_to_file(ob.data, json_path)
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

    addLeafBones:BoolProperty(name="添加叶骨",description="给无子级且有权重的骨末端补一根叶骨(HoTools自己的实现,长度为主体骨长的一半)。无权重骨不加,新叶骨不写HoTools属性、不参与MCH。在MCH步骤之前执行",default=True) # type: ignore
    generateMCHBones:BoolProperty(name="生成MCH骨(动捕适配)",description="对勾选了generateMCH的骨:导出时清零竖直以适配动捕/humanoid,同时生成MCH_前缀副本保留原始朝向,子级挂到MCH上、指向该骨的约束/驱动改指MCH。仅存在于导出的FBX,工程不留痕",default=False) # type: ignore
    exportBoneConstraint:BoolProperty(name="导出骨骼约束(JSON)",description="导出各骨架内的HoTools辅助骨约束(fan/twist)为Unity可用的JSON,与FBX同目录。约束目标已随MCH转移",default=False) # type: ignore
    boneConstraintSuffix:bpy.props.StringProperty(name="约束后缀",description="约束JSON文件名后缀:<FBX名>_<骨架名><后缀>.json",default="_constraint") # type: ignore
    exportBoneCollection:BoolProperty(name="导出骨骼集合(JSON)",description="导出各骨架的骨骼集合(Bone Collections)为JSON,记录每个集合持有的骨骼名称,与FBX同目录",default=False) # type: ignore
    boneCollectionSuffix:bpy.props.StringProperty(name="集合后缀",description="集合JSON文件名后缀:<FBX名>_<骨架名><后缀>.json",default="_collection") # type: ignore
    fixObjectTransform:BoolProperty(name="矫正物体变换",description="执行原有的物体变换/旋转矫正预处理",default=True) # type: ignore
    removeHiddenModifiers:BoolProperty(name="删除隐藏修改器",description="导出前临时删除视口隐藏的修改器，用于绕过隐藏 GN 阻塞形态键应用修改器的问题",default=True) # type: ignore
    ignoreGeometryNodes:BoolProperty(name="忽略几何节点",description="导出前临时删除所有几何节点修改器，避免几何节点改变导出网格拓扑；导出后自动恢复",default=True) # type: ignore
    ignoreOutlineModifiers:BoolProperty(name="忽略描边修改器",description="导出前临时删除描边修改器（开启了翻转法线的实体化修改器）；导出后自动恢复",default=True) # type: ignore

    def getParams(self,context, report_errors=True):
        """返回写死的 export_scene.fbx 参数。

        不再依赖 Blender 的 FBX 导出预设：关键参数全部固定（仅选中、仅
        MESH+ARMATURE、单位全部应用等）。add_leaf_bones 固定为 False——叶骨
        改由 HoTools 自己实现（build_leaf_bones，导出前已建好），不再走原生。
        """
        params = {
            "filepath": self.filepath,
            # 范围：仅选中物体，仅导出 MESH 与 ARMATURE
            "use_selection": True,
            "use_visible": False,
            "use_active_collection": False,
            "object_types": {'MESH', 'ARMATURE'},
            # 单位/变换：单位全部应用
            "global_scale": 1.0,
            "apply_unit_scale": True,
            "apply_scale_options": 'FBX_SCALE_ALL',
            "use_space_transform": True,
            "bake_space_transform": False,
            # 网格
            "use_mesh_modifiers": True,
            "use_mesh_modifiers_render": True,
            "mesh_smooth_type": 'OFF',
            "colors_type": 'SRGB',
            "prioritize_active_color": False,
            "use_subsurf": False,
            "use_mesh_edges": False,
            "use_tspace": False,
            "use_triangles": False,
            "use_custom_props": False,
            # 骨架
            # 叶骨改由 HoTools 自己实现（build_leaf_bones），关闭 Blender 自带
            "add_leaf_bones": False,
            "primary_bone_axis": 'Y',
            "secondary_bone_axis": 'X',
            "use_armature_deform_only": False,
            "armature_nodetype": 'NULL',
            # 动画烘焙
            "bake_anim": False,
            "bake_anim_use_all_bones": True,
            "bake_anim_use_nla_strips": True,
            "bake_anim_use_all_actions": True,
            "bake_anim_force_startend_keying": True,
            "bake_anim_step": 1.0,
            "bake_anim_simplify_factor": 1.0,
            # 输出
            "path_mode": 'AUTO',
            "embed_textures": False,
            "batch_mode": 'OFF',
            "use_batch_own_dir": True,
            "axis_forward": '-Z',
            "axis_up": 'Y',
        }
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

            # 补叶骨（须在 MCH 之前：新叶骨 generateMCH 默认关，不会被 MCH 处理）
            if self.addLeafBones and armature_objects != []:
                FBXExporter.add_leaf_bones_to_armatures(
                    armature_objects, selection, active_object
                )

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
                    json_path = FBXExporter.export_armature_constraints_json(
                        ob, self.filepath, self.boneConstraintSuffix
                    )
                    if json_path:
                        exported_json.append(json_path)

            # 导出骨骼集合 JSON
            if self.exportBoneCollection:
                for ob in armature_objects:
                    if ob.name not in bpy.context.view_layer.objects:
                        continue
                    json_path = FBXExporter.export_armature_collections_json(
                        ob, self.filepath, self.boneCollectionSuffix
                    )
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

        # FBX 导出参数已写死（仅选中、仅 MESH+ARMATURE、单位全部应用等），
        # 只暴露叶骨开关
        fbx_box = layout.box()
        fbx_box.label(text="FBX 导出")
        fbx_box.prop(self, "addLeafBones")

        option_box = layout.box()
        option_box.label(text="预处理")
        option_col = option_box.column(align=True)
        option_col.prop(self, "generateMCHBones")
        option_col.prop(self, "fixObjectTransform")
        option_col.prop(self, "removeHiddenModifiers")
        option_col.prop(self, "ignoreGeometryNodes")
        option_col.prop(self, "ignoreOutlineModifiers")

        # 附加 JSON 导出（影响导出文件数量）：勾选后展开对应的文件名后缀输入框
        json_box = layout.box()
        json_box.label(text="附加导出 (JSON)")
        json_col = json_box.column(align=True)
        json_col.prop(self, "exportBoneConstraint")
        if self.exportBoneConstraint:
            json_col.prop(self, "boneConstraintSuffix")
        json_col.prop(self, "exportBoneCollection")
        if self.exportBoneCollection:
            json_col.prop(self, "boneCollectionSuffix")

class OP_FinalFBXExport_only_preprocess(Operator):
    bl_idname = "ho.final_fbx_export_only_preprocess"
    bl_label = "Hotools导出FBX(仅预处理)"
    bl_description = ""
    bl_options = {'REGISTER', 'UNDO'}

    addLeafBones:BoolProperty(name="添加叶骨",description="给无子级且有权重的骨末端补一根叶骨(HoTools自实现,长度为主体骨的一半),在MCH步骤之前执行;仅预处理模式不撤销,叶骨会留在工程供检视",default=True) # type: ignore
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

            # 补叶骨（无子级且有权重的骨），须在 MCH 步骤之前
            if self.addLeafBones and armature_objects != []:
                FBXExporter.add_leaf_bones_to_armatures(armature_objects, selection, active_object)

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
        option_col.prop(self, "addLeafBones")
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
