# HoFBX 导出功能总览
#
# 这个导出器的目标是把 Blender 场景整理成更适合 Unity 使用的 FBX。
# 除了 Blender 原生 FBX 导出，还包含若干导出前预处理和兼容性修复。
# 主导出流程开始时会记录场景状态，结束时通过撤销回滚临时修改，尽量不污染工程。
#
# 一、导出范围与固定参数
# 1. 只导出当前选中的对象，并固定导出 MESH 与 ARMATURE。
#    解决误把场景中未选中的辅助物体、相机或灯光带入 FBX 的问题。
# 2. 固定单位、坐标轴、缩放和空间变换参数，并应用单位缩放。
#    解决 Blender、FBX 和 Unity 之间单位/轴向不一致导致的尺寸和朝向问题。
# 3. 关闭 Blender 原生叶骨和动画烘焙，FBX 导出使用 HoTools 预处理后的中立结果。
#    解决原生导出自动添加叶骨、带入不需要的动画数据等问题。
#
# 二、导出前几何与修改器处理
# 4. 网格化对象（默认开启）：把选中的 CURVE 转成 MESH，并为共享 Mesh 数据的对象
#    创建独立数据，覆盖 Alt+D 等链接网格实例。
#    解决 Blender/FBX 对曲线和共享网格实例支持不一致，导致对象漏导或结果互相影响的问题。
# 5. 数据传递修改器隐式修复：对选中导出网格，在完整视图层上下文中先手动应用
#    DATA_TRANSFER 修改器，再进入 FBX evaluated mesh 导出。
#    解决 FBX 导出阶段依赖图环境不完整时，数据传递结果与 Blender 手动应用差异很大的问题。
#    应用失败时保留修改器、继续导出，并在控制台和导出报告中提示。
# 6. 按材质整理面顺序隐式修复：对所有选中的导出 Mesh 执行
#    Sort Elements > Material（仅 FACE）。
#    解决多物体 FBX 导入 Unity 后，Unity 根据面/子网格顺序重建材质列表，
#    导致各物体材质 slot 顺序出现不一致的问题；不改变材质槽本身。
# 7. 三角化（默认开启）：使用 Blender Triangulate 修改器固定四边形分割方式为
#    FIXED，多边形分割为 BEAUTY，最少顶点为 4，并开启保持法向。
#    解决 Blender 导出四边面后，Substance Painter 等软件因空间划分算法不同，
#    重新三角化后产生法线、贴图或烘焙结果扭曲的问题。
# 8. 清理未使用材质槽（默认开启）：删除没有被任何面使用的全部材质槽，
#    不区分槽中是否已有材质。
#    解决空槽或未被面引用的槽进入 FBX 后，造成 Unity 子网格和材质列表错位的问题。
# 9. 忽略几何节点（默认开启）：导出前临时移除 NODES 修改器。
#    解决几何节点改变导出拓扑、实例结果或形态键兼容性的问题。
#    gn无法被区分是否修改拓补，bl内部导出器选择保守方案认为他是拓补修改
# 9.1 烘焙形态键穿过修改器（隐式操作，无开关）：物体既有形态键、又还有会被导出的修改器
#    （几何节点、数据传递等，骨架修改器除外），或需要三角化时，逐个形态键求值一遍修改器栈，
#    再用结果替换基础网格并重建同名形态键，最后移除已烘焙的修改器。
#    复用 Utils.shapekey_utils.bake_modifiers_keeping_shape_keys——与修改器面板的
#    「保持形态键应用」按钮是同一套实现，差别只在参数：导出按“FBX 会评估的修改器”
#    （含只在渲染中显示的）、并保留骨架修改器给蒙皮；按钮按“视图显示中”的、连骨架一起烘。
#    解决“形态键 + 几何节点”物体导出后 BlendShape 静默丢失的问题：Blender 原生导出
#    在有修改器要应用时走 evaluated mesh（new_from_object），求值网格不带形态键
#    （Blender 议题 #104714），物体本身能导出但形变数据没了。前提是各形态键求值后的
#    顶点数一致；不一致会跳过并报warning。不留痕。
# 9.2 约束处理（开关「应用约束」，默认关闭 = 删除）：与应用骨架姿态是同一件事的两面
#    （都是“当前求值状态要不要固化”），所以开关在应用姿态那一步就生效——
#    关闭时先静音姿态约束，避免约束结果被 ho.apply_rest_pose 烘进静置/网格（否则会与
#    JSON 里的约束在运行时重复生效）；姿态应用完立刻还原静音，约束照常写进 JSON。
#    真正的删除排在 MCH（要把约束转移到 MCH 骨）与约束 JSON（约束的唯一载体）之后，
#    且必须早于还会读变换的预处理（矫正物体变换用 matrix_world 复原父级逆矩阵）与内置导出：
#    内置导出不会删约束，会把约束结果当成实际变换写进 FBX（物体级 matrix_world、
#    骨骼级 pose matrix），导致 FBX 与 JSON 内外不一致（实测隐患）。
#    开：约束参与应用姿态的求值，并保留到内置导出应用（资产本来就靠约束摆位时用）。
# 10. 忽略描边修改器（默认开启）：临时移除开启翻转法线的 SOLIDIFY 描边修改器。
#    解决渲染用外壳被误当成模型几何导出，导致重复表面和法线异常的问题。
# 11. 删除隐藏修改器（默认开启）：临时移除视口隐藏的修改器。
#     解决隐藏修改器仍参与 FBX 评估，阻塞形态键/骨架等预处理或产生意外导出结果的问题。
#
# 三、骨架与蒙皮处理
# 12. 应用骨架姿态（默认开启）：对当前选中的骨架调用 HoTools 内部的
#     应用骨架姿态操作，把当前 Pose 应用为静置姿态，再以 REST 状态导出。
#     解决 Blender FBX 导出骨架时忽略当前姿态、自动回到原始静置姿态的问题。
#     内部操作失败时只跳过该骨架并警告，不使用 pose.armature_apply() 兜底。
# 13. 清理权重（默认关闭）：删除极小权重、限制每顶点最多 4 个骨骼影响并归一化。
#     解决 Unity/运行时对骨骼影响数量有限制，以及微小权重造成不稳定变形的问题。
# 14. 添加叶骨（默认开启）：为无子级且确实有权重的末端骨补充叶骨，并加入原骨骼集合。
#     解决 FBX/Unity 末端骨方向或层级显示不完整，同时避免给无权重骨和辅助骨乱加叶骨。
#     “有权重”按导出时的求值网格判定：镜像修改器翻转顶点组、几何节点写出的权重都算。
#     否则半身几何 + 镜像修改器的资源会被误判成只有一侧有权重，只给一侧加叶骨（与导出结果不符）。
# 15. 生成 MCH 骨（默认开启）：为标记的骨创建 MCH 旁路骨，清理主骨变换并转移约束引用。
#     解决动捕/运行时需要中立主骨、同时保留原始约束关系的问题；结果只存在于导出副本。
#
# 四、对象变换与附加元数据
# 16. 矫正物体变换（默认开启）：按 HoTools 的导出约定修正顶级对象变换。
#     解决 Blender 对象局部变换、父子逆矩阵和 Unity 导入朝向不一致的问题。
#     尤其解决骨架物体进unity还带旋转的问题
# 17. 导出 Unity 元数据（默认开启）：在 FBX 旁的 HoFBX 文件夹生成约束 IR、
#     骨骼集合和 Humanoid 映射等 JSON；也可分别关闭各类 JSON。
#     解决 FBX 本身无法完整表达 HoTools 约束、骨骼集合和精确 Humanoid 映射的问题，
#     让 Unity 导入端可以按原始语义重建运行时信息。
# 18. 导出预设：保存主导出器的开关和 JSON 后缀设置。
#     解决不同资产重复配置导出参数、容易漏勾选的问题。
#
# 五、临时状态原则
# 19. 导出期间会临时解除隐藏、切换选择/活动对象、修改修改器、Mesh 数据和骨架状态；
#     主导出结束后统一撤销，并恢复骨架 pose_position、选择状态和可见性。
#     这些预处理主要服务于导出文件，不应把临时修复结果永久写回 Blender 工程。

import bpy
import os
import json
import mathutils
import math
import traceback
from datetime import datetime, timezone
from bpy.types import PropertyGroup, UIList, Operator, Panel, Menu
from mathutils import Vector
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty
from bl_operators.presets import AddPresetBase
from Utils import bone_utils
from .HumanoidMappingExporter import HumanoidMappingExporter


# ── 预设：主导出器 ─────────────────────────────────────────
class HO_MT_FBXExportPresets(Menu):
    """主 FBX 导出器预设菜单"""
    bl_label = ""
    preset_subdir = "hotools/fbx_export"
    preset_operator = "script.execute_preset"
    draw = Menu.draw_preset


class OP_AddFBXExportPreset(AddPresetBase, Operator):
    """保存/删除 HoTools FBX 导出预设"""
    bl_idname = "ho.fbx_export_preset_add"
    bl_label = "添加FBX导出预设"
    preset_menu = "HO_MT_FBXExportPresets"
    preset_subdir = "hotools/fbx_export"

    # 预设文件头部：获取当前活动操作器
    preset_defines = ["op = bpy.context.active_operator"]

    # 需要保存/恢复的属性
    preset_values = [
        "op.meshifyCurves",
        "op.triangulateMeshes",
        "op.applyArmaturePose",
        "op.addLeafBones",
        "op.generateMCHBones",
        "op.cleanWeights",
        "op.cleanEmptyMaterialSlots",
        "op.fixObjectTransform",
        "op.removeHiddenModifiers",
        "op.ignoreGeometryNodes",
        "op.ignoreOutlineModifiers",
        "op.exportBoneConstraint",
        "op.boneConstraintSuffix",
        "op.exportBoneCollection",
        "op.boneCollectionSuffix",
        "op.exportHumanoidMapping",
        "op.humanoidMappingSuffix",
        "op.exportUnityMetadata",
    ]


# ── 预设：仅预处理器 ──────────────────────────────────────
class HO_MT_FBXPreprocessPresets(Menu):
    """仅预处理器预设菜单"""
    bl_label = ""
    preset_subdir = "hotools/fbx_preprocess"
    preset_operator = "script.execute_preset"
    draw = Menu.draw_preset


class OP_AddFBXPreprocessPreset(AddPresetBase, Operator):
    """保存/删除 HoTools FBX 仅预处理预设"""
    bl_idname = "ho.fbx_preprocess_preset_add"
    bl_label = "添加预处理预设"
    preset_menu = "HO_MT_FBXPreprocessPresets"
    preset_subdir = "hotools/fbx_preprocess"

    preset_defines = ["op = bpy.context.active_operator"]

    preset_values = [
        "op.addLeafBones",
        "op.generateMCHBones",
        "op.cleanWeights",
        "op.fixObjectTransform",
        "op.ignoreGeometryNodes",
        "op.ignoreOutlineModifiers",
    ]


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

# 生成的 MCH 骨统一归入此骨骼集合（Bone Collection），便于导出后检视/清理
MCH_BONE_COLLECTION_NAME = "HoRig_MCH"


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
    UNITY_METADATA_DIRECTORY = "HoFBX"
    CURVE_OBJECT_TYPES = {"CURVE"}

    @staticmethod
    def unity_metadata_directory(fbx_filepath):
        """Return and create the folder that contains all HoFBX sidecar files."""
        directory = os.path.join(
            os.path.dirname(fbx_filepath),
            FBXExporter.UNITY_METADATA_DIRECTORY,
        )
        os.makedirs(directory, exist_ok=True)
        return directory

    @staticmethod
    def unity_metadata_path(fbx_filepath, file_name):
        return os.path.join(
            FBXExporter.unity_metadata_directory(fbx_filepath),
            file_name,
        )

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
    def restore_selection_by_names(object_names, active_object_name=None):
        bpy.ops.object.select_all(action='DESELECT')
        for object_name in object_names:
            ob = bpy.data.objects.get(object_name)
            if ob and ob.name in bpy.context.view_layer.objects:
                ob.select_set(True)
        if active_object_name:
            active_object = bpy.data.objects.get(active_object_name)
            if active_object and active_object.name in bpy.context.view_layer.objects:
                bpy.context.view_layer.objects.active = active_object

    @staticmethod
    def meshify_selected_objects(selection, active_object):
        """把选中的曲线类对象转成 Mesh，并解除 Alt+D 网格对象的数据共享。"""
        selection_names = [ob.name for ob in selection]
        active_object_name = active_object.name if active_object else None
        convertible_names = [
            ob.name
            for ob in selection
            if ob.type in FBXExporter.CURVE_OBJECT_TYPES
            and ob.name in bpy.context.view_layer.objects
        ]
        shared_mesh_names = [
            ob.name
            for ob in selection
            if ob.type == "MESH"
            and getattr(getattr(ob, "data", None), "users", 1) > 1
            and ob.name in bpy.context.view_layer.objects
        ]
        if not convertible_names and not shared_mesh_names:
            return 0, 0, [], selection, active_object

        converted_objects = 0
        made_single_user = 0
        failed = []
        try:
            for object_name in shared_mesh_names:
                ob = bpy.data.objects.get(object_name)
                if ob is None or ob.name not in bpy.context.view_layer.objects:
                    continue
                try:
                    if ob.data and ob.data.users > 1:
                        ob.data = ob.data.copy()
                        made_single_user += 1
                except Exception as exc:
                    failed.append((object_name, exc))

            for object_name in convertible_names:
                ob = bpy.data.objects.get(object_name)
                if ob is None or ob.name not in bpy.context.view_layer.objects:
                    continue
                try:
                    bpy.ops.object.select_all(action='DESELECT')
                    ob.select_set(True)
                    bpy.context.view_layer.objects.active = ob
                    bpy.ops.object.convert(target='MESH')
                    converted_objects += 1
                except Exception as exc:
                    failed.append((object_name, exc))
        finally:
            FBXExporter.restore_selection_by_names(selection_names, active_object_name)

        selection = [
            ob
            for object_name in selection_names
            if (ob := bpy.data.objects.get(object_name))
            and ob.name in bpy.context.view_layer.objects
        ]
        active_object = bpy.context.view_layer.objects.active
        return converted_objects, made_single_user, failed, selection, active_object

    @staticmethod
    def apply_data_transfer_modifiers(mesh_objects, selection, active_object):
        """在完整视图层上下文中手动应用数据传递修改器，规避 FBX 评估差异。"""
        selection_names = [ob.name for ob in selection]
        active_object_name = active_object.name if active_object else None
        applied = 0
        failed = []

        target_names = [
            ob.name
            for ob in mesh_objects
            if ob.type == "MESH"
            and ob.name in bpy.context.view_layer.objects
            and any(
                mod.type == "DATA_TRANSFER"
                and (mod.show_viewport or mod.show_render)
                for mod in ob.modifiers
            )
        ]
        if not target_names:
            return 0, [], selection, active_object

        try:
            for object_name in target_names:
                ob = bpy.data.objects.get(object_name)
                if ob is None or ob.name not in bpy.context.view_layer.objects:
                    continue

                modifier_names = [
                    mod.name
                    for mod in ob.modifiers
                    if mod.type == "DATA_TRANSFER"
                    and (mod.show_viewport or mod.show_render)
                ]
                if not modifier_names:
                    continue

                try:
                    bpy.ops.object.select_all(action="DESELECT")
                    ob.select_set(True)
                    bpy.context.view_layer.objects.active = ob
                    bpy.context.view_layer.update()

                    # 隐式修复：FBX 通过 evaluated mesh 自动应用 DATA_TRANSFER
                    # 时，结果可能与界面中手动应用不同；先在完整视图层中
                    # 走标准 modifier_apply，避免导出阶段的隔离评估差异。
                    for modifier_name in modifier_names:
                        mod = ob.modifiers.get(modifier_name)
                        if mod is None or mod.type != "DATA_TRANSFER":
                            continue
                        if not (mod.show_viewport or mod.show_render):
                            continue
                        try:
                            result = bpy.ops.object.modifier_apply(
                                modifier=modifier_name,
                                merge_customdata=True,
                            )
                            if "FINISHED" not in result:
                                raise RuntimeError(
                                    f"modifier_apply returned {result}"
                                )
                            applied += 1
                            bpy.context.view_layer.update()
                        except Exception as exc:
                            failed.append((object_name, modifier_name, exc))
                except Exception as exc:
                    failed.append((object_name, "<准备应用>", exc))
        finally:
            FBXExporter.restore_selection_by_names(selection_names, active_object_name)

        selection = [
            ob
            for object_name in selection_names
            if (ob := bpy.data.objects.get(object_name))
            and ob.name in bpy.context.view_layer.objects
        ]
        active_object = bpy.context.view_layer.objects.active
        return applied, failed, selection, active_object

    @staticmethod
    def apply_selected_armature_poses(armature_objects, selection, active_object):
        """将选中骨架的当前 Pose 临时应用为静置姿态。"""
        selection_names = [ob.name for ob in selection]
        active_object_name = active_object.name if active_object else None
        applied = 0
        failed = []

        try:
            for armature in armature_objects:
                if armature.name not in bpy.context.view_layer.objects:
                    continue

                try:
                    bpy.ops.object.select_all(action='DESELECT')
                    armature.select_set(True)
                    bpy.context.view_layer.objects.active = armature

                    result = bpy.ops.ho.apply_rest_pose("EXEC_DEFAULT")

                    if "FINISHED" not in result:
                        raise RuntimeError(f"operator returned {result}")
                    applied += 1
                except Exception as exc:
                    failed.append((armature.name, exc))
                    if bpy.context.mode != "OBJECT" and bpy.ops.object.mode_set.poll():
                        bpy.ops.object.mode_set(mode="OBJECT")
        finally:
            FBXExporter.restore_selection_by_names(selection_names, active_object_name)

        selection = [
            ob
            for object_name in selection_names
            if (ob := bpy.data.objects.get(object_name))
            and ob.name in bpy.context.view_layer.objects
        ]
        active_object = bpy.context.view_layer.objects.active
        return applied, failed, selection, active_object

    @staticmethod
    def _weighted_names_from_mesh(mesh, group_names, bone_names) -> set:
        """扫描一份网格数据，返回其中存在 weight>0 顶点的骨名集合。"""
        found = set()
        for v in mesh.vertices:
            for g in v.groups:
                gname = group_names.get(g.group)
                if gname is None or gname not in bone_names or gname in found:
                    continue
                try:
                    if g.weight > 0.0:
                        found.add(gname)
                except (RuntimeError, AttributeError):
                    continue
        return found

    @staticmethod
    def _modifiers_regroup_weights(ob) -> bool:
        """物体是否存在会改变“顶点组 → 顶点”映射的修改器。

        镜像修改器开启“翻转顶点组”时会按 .L/.R 互换顶点组索引，几何节点也可能写出
        原始数据里没有的权重；二者都只在求值结果里存在。
        """
        for modifier in ob.modifiers:
            if modifier.type == 'MIRROR' and getattr(modifier, "use_mirror_vertex_groups", False):
                return True
            if modifier.type == 'NODES':
                return True
        return False

    @staticmethod
    def get_weighted_bone_names(armature_ob):
        """采集本骨架下"有权重"的骨名集合（供叶骨判定用）。

        遍历所有被该骨架形变的网格（骨架修改器指向本骨架，或以 ARMATURE 方式父级到本骨架），
        只要某骨名对应的顶点组存在 weight>0 的顶点，就算该骨有权重。必须在 OBJECT 模式采集。

        FBX 导出会应用修改器（use_mesh_modifiers=True），所以“有权重”必须按求值结果判断：
        只做了半身几何 + 镜像修改器（翻转顶点组）的网格，另一侧的权重只存在于求值网格里，
        只扫原始数据会把整侧骨骼判成无权重，于是只给一侧加叶骨。
        """
        bone_names = {b.name for b in armature_ob.data.bones}
        weighted = set()
        depsgraph = None
        for mesh_ob in bone_utils.collect_mesh_objects_for_armature(armature_ob):
            if not mesh_ob.vertex_groups:
                continue

            group_names = {i: vg.name for i, vg in enumerate(mesh_ob.vertex_groups)}
            weighted |= FBXExporter._weighted_names_from_mesh(
                mesh_ob.data, group_names, bone_names
            )

            # 求值网格：覆盖镜像翻转顶点组、几何节点生成的权重
            if FBXExporter._modifiers_regroup_weights(mesh_ob):
                if depsgraph is None:
                    depsgraph = bpy.context.evaluated_depsgraph_get()
                eval_ob = mesh_ob.evaluated_get(depsgraph)
                eval_mesh = getattr(eval_ob, "data", None)
                if eval_mesh is not None and eval_mesh is not mesh_ob.data:
                    eval_group_names = {
                        i: vg.name
                        for i, vg in enumerate(getattr(eval_ob, "vertex_groups", ()) or ())
                    }
                    weighted |= FBXExporter._weighted_names_from_mesh(
                        eval_mesh, eval_group_names or group_names, bone_names
                    )

            # 全部骨都已确认有权重则提前结束
            if bone_names <= weighted:
                break
        return weighted

    WEIGHT_CLEAN_LIMIT = 0.0001
    WEIGHT_MAX_GROUPS = 4
    @staticmethod
    def clean_export_weights(mesh_objects):
        """对将导出的形变网格做权重清理：删微小权重 → 钳制骨权重组数 → 归一化。

        三步全部走 Blender 原生算子的 group_select_mode='BONE_DEFORM'：只处理与形变骨
        对应的顶点组，非骨骼组（形态键遮罩、GN 属性组等）一律不动——这就是“先判定是不是
        骨骼权重”的落点。须在 OBJECT 模式调用；会临时切换 active 物体，由导出流程统一恢复，
        且本步随导出末尾 undo 回滚，工程不留痕。返回实际处理的网格数。

        执行前临时关闭会干扰结果的开关，结束后恢复：
        - scene.tool_settings.use_auto_normalize：内置自动归一化会在每步后自动重算，
          干扰“删微小权重/限制组数”的中间态，须整体关闭，最后由第 3 步显式归一化；
        - 每个物体的网格镜像（use_mesh_mirror_x/y/z）：对称模式会把操作镜像到对侧，
          污染清理结果。复用公共 bone_utils 的探测/恢复（属性可能挂物体或数据块）。
        """
        processed = 0
        prev_active = bpy.context.view_layer.objects.active
        tool_settings = bpy.context.scene.tool_settings
        prev_auto_normalize = getattr(tool_settings, "use_auto_normalize", None)
        if prev_auto_normalize is not None:
            tool_settings.use_auto_normalize = False
        mirror_states = []  # bone_utils.set_temp_mesh_mirror_off 返回的状态，逐物体恢复
        try:
            for ob in mesh_objects:
                if ob.type != 'MESH' or not ob.vertex_groups:
                    continue
                if ob.name not in bpy.context.view_layer.objects:
                    continue
                # 没有骨架形变就谈不上骨骼权重，跳过（BONE_DEFORM 也需要绑定骨架）
                if not bone_utils.find_deforming_armatures_for_object(ob):
                    continue
                # 临时关闭该物体的网格镜像，避免清理被镜像到对侧
                mirror_states.append(bone_utils.set_temp_mesh_mirror_off(ob))
                bpy.context.view_layer.objects.active = ob
                # 1. 删微小权重
                try:
                    bpy.ops.object.vertex_group_clean(
                        group_select_mode='BONE_DEFORM',
                        limit=FBXExporter.WEIGHT_CLEAN_LIMIT,
                        keep_single=False,
                    )
                except RuntimeError as exc:
                    print(f"[HoTools FBX] vertex_group_clean 失败 {ob.name}: {exc}")
                # 2. 钳制每顶点最多 N 个骨权重组
                try:
                    bpy.ops.object.vertex_group_limit_total(
                        group_select_mode='BONE_DEFORM',
                        limit=FBXExporter.WEIGHT_MAX_GROUPS,
                    )
                except RuntimeError as exc:
                    print(f"[HoTools FBX] vertex_group_limit_total 失败 {ob.name}: {exc}")
                # 3. 归一化骨骼权重
                try:
                    bpy.ops.object.vertex_group_normalize_all(
                        group_select_mode='BONE_DEFORM',
                        lock_active=False,
                    )
                except RuntimeError as exc:
                    print(f"[HoTools FBX] vertex_group_normalize_all 失败 {ob.name}: {exc}")
                processed += 1
        finally:
            # 恢复网格镜像与自动归一化开关
            for mirror_state in mirror_states:
                try:
                    bone_utils.restore_mesh_mirror_state(mirror_state)
                except (AttributeError, ReferenceError):
                    pass
            if prev_auto_normalize is not None:
                tool_settings.use_auto_normalize = prev_auto_normalize
            bpy.context.view_layer.objects.active = prev_active
        return processed

    @staticmethod
    def clean_unused_material_slots(mesh_objects):
        """删除导出网格中没有被任何面使用的材质槽。

        不论槽中是否已有材质，只保留被面材质索引引用的槽；导出结束后由统一的
        undo 回滚。返回 (处理网格数, 删除槽数)。
        """
        processed = 0
        removed = 0
        visited_meshes = set()

        for ob in mesh_objects:
            if ob.type != "MESH" or ob.name not in bpy.context.view_layer.objects:
                continue

            mesh = getattr(ob, "data", None)
            if mesh is None:
                continue
            mesh_id = mesh.as_pointer()
            if mesh_id in visited_meshes:
                continue
            visited_meshes.add(mesh_id)

            slot_count = len(mesh.materials)
            if not slot_count:
                continue

            used_indices = {
                polygon.material_index
                for polygon in mesh.polygons
                if 0 <= polygon.material_index < slot_count
            }
            removable_indices = [
                index for index in range(slot_count) if index not in used_indices
            ]
            if not removable_indices:
                continue

            for index in reversed(removable_indices):
                mesh.materials.pop(index=index)
            processed += 1
            removed += len(removable_indices)

        return processed, removed

    @staticmethod
    def sort_export_meshes_by_material(mesh_objects, selection, active_object):
        """按材质索引统一整理导出网格的面顺序，规避 Unity 的材质槽重排。"""
        selection_names = [ob.name for ob in selection]
        active_object_name = active_object.name if active_object else None
        target_objects = []
        visited_meshes = set()
        failed = []

        for ob in mesh_objects:
            if ob.type != "MESH" or ob.name not in bpy.context.view_layer.objects:
                continue
            mesh = getattr(ob, "data", None)
            if mesh is None or not mesh.polygons:
                continue
            mesh_id = mesh.as_pointer()
            if mesh_id in visited_meshes:
                continue
            visited_meshes.add(mesh_id)
            target_objects.append(ob)

        if not target_objects:
            return 0, [], selection, active_object

        processed = 0
        try:
            bpy.ops.object.select_all(action="DESELECT")
            for ob in target_objects:
                ob.select_set(True)
            bpy.context.view_layer.objects.active = target_objects[0]
            bpy.context.view_layer.update()

            result = bpy.ops.object.mode_set(mode="EDIT")
            if "FINISHED" not in result:
                raise RuntimeError(f"mode_set returned {result}")

            # 隐式修复：Unity 对 FBX 多物体材质列表的重建会受每个网格
            # 的面首次出现顺序影响。Blender 的 Sort Elements > Material
            # 会按材质索引统一整理面顺序，避免同组网格导入 Unity 后
            # 出现材质 slot 顺序不一致。只整理 FACE，不改变材质槽。
            result = bpy.ops.mesh.select_all(action="SELECT")
            if "FINISHED" not in result:
                raise RuntimeError(f"mesh.select_all returned {result}")
            result = bpy.ops.mesh.sort_elements(
                type="MATERIAL",
                elements={"FACE"},
                reverse=False,
            )
            if "FINISHED" not in result:
                raise RuntimeError(f"mesh.sort_elements returned {result}")

            result = bpy.ops.object.mode_set(mode="OBJECT")
            if "FINISHED" not in result:
                raise RuntimeError(f"mode_set returned {result}")
            processed = len(target_objects)
        except Exception as exc:
            failed.append(("<所有导出网格>", exc))
            if bpy.context.mode != "OBJECT" and bpy.ops.object.mode_set.poll():
                try:
                    bpy.ops.object.mode_set(mode="OBJECT")
                except Exception as mode_exc:
                    failed.append(("<退出编辑模式>", mode_exc))
        finally:
            FBXExporter.restore_selection_by_names(selection_names, active_object_name)

        selection = [
            ob
            for object_name in selection_names
            if (ob := bpy.data.objects.get(object_name))
            and ob.name in bpy.context.view_layer.objects
        ]
        active_object = bpy.context.view_layer.objects.active
        return processed, failed, selection, active_object

    TRIANGULATE_MODIFIER_NAME = "HoFBX Triangulate"
    @staticmethod
    def remove_modifier_if_present(ob, modifier):
        """存在则移除指定修改器（用于撤销临时添加的三角化修改器）。"""
        if modifier is None:
            return
        name = getattr(modifier, "name", None)
        if not name:
            return
        current = ob.modifiers.get(name)
        if current is None:
            return
        try:
            ob.modifiers.remove(current)
        except (ReferenceError, RuntimeError):
            pass

    @staticmethod
    def add_export_triangulate_modifier(ob):
        """按导出约定添加三角化修改器（FIXED + BEAUTY + 最少顶点 4 + 保持法向）。"""
        modifier = ob.modifiers.new(
            name=FBXExporter.TRIANGULATE_MODIFIER_NAME,
            type="TRIANGULATE",
        )
        modifier.quad_method = "FIXED"
        modifier.ngon_method = "BEAUTY"
        modifier.min_vertices = 4
        modifier.keep_custom_normals = True
        return modifier

    @staticmethod
    def triangulate_export_meshes(mesh_objects, selection, active_object):
        """用 Blender Triangulate 修改器固定导出网格的三角形分割方式。

        带形态键的网格不能应用修改器（Blender 限制），这类网格改由
        bake_shape_keys_through_modifiers 在烘焙形态键时一并三角化，这里只报告跳过，
        不再算作失败。
        """
        selection_names = [ob.name for ob in selection]
        active_object_name = active_object.name if active_object else None
        target_objects = []
        visited_meshes = set()
        shape_key_objects = []
        failed = []

        for ob in mesh_objects:
            if ob.type != "MESH" or ob.name not in bpy.context.view_layer.objects:
                continue
            mesh = getattr(ob, "data", None)
            if mesh is None or not mesh.polygons:
                continue
            mesh_id = mesh.as_pointer()
            if mesh_id in visited_meshes:
                continue
            visited_meshes.add(mesh_id)
            if getattr(mesh, "shape_keys", None) is not None:
                shape_key_objects.append(ob.name)
                continue
            target_objects.append(ob)

        if shape_key_objects:
            print(
                f"[HoTools FBX] 三角化：跳过 {len(shape_key_objects)} 个带形态键的网格"
                f"（形态键会阻止应用修改器，改由形态键烘焙步骤处理）："
                f"{'、'.join(shape_key_objects)}"
            )

        if not target_objects:
            return 0, [], selection, active_object

        processed = 0
        for ob in target_objects:
            triangulate_modifier = None
            triangulate_modifier_name = None
            try:
                bpy.ops.object.select_all(action="DESELECT")
                ob.select_set(True)
                bpy.context.view_layer.objects.active = ob
                bpy.context.view_layer.update()

                triangulate_modifier = FBXExporter.add_export_triangulate_modifier(ob)
                triangulate_modifier_name = triangulate_modifier.name
                bpy.context.view_layer.update()

                result = bpy.ops.object.modifier_apply(
                    modifier=triangulate_modifier_name,
                )
                if "FINISHED" not in result:
                    raise RuntimeError(f"modifier_apply returned {result}")
                processed += 1
            except Exception as exc:
                failed.append((ob.name, exc))
                if (
                    triangulate_modifier_name is not None
                    and ob.modifiers.get(triangulate_modifier_name) is not None
                ):
                    try:
                        ob.modifiers.remove(
                            ob.modifiers.get(triangulate_modifier_name)
                        )
                    except (ReferenceError, RuntimeError):
                        pass

        FBXExporter.restore_selection_by_names(selection_names, active_object_name)

        selection = [
            ob
            for object_name in selection_names
            if (ob := bpy.data.objects.get(object_name))
            and ob.name in bpy.context.view_layer.objects
        ]
        active_object = bpy.context.view_layer.objects.active
        return processed, failed, selection, active_object

    LEAF_SUFFIX = "_end"
    @staticmethod
    def build_leaf_bones(ob, weighted_names):
        """给无子级且有权重的骨末端补叶骨。必须在 EDIT 模式下调用。

        规则：
        - 只处理无子级的骨（先快照目标，避免边加边处理）；
        - 只处理 weighted_names 里的骨（无权重的骨不加）。这里的“有权重”是**导出时求值网格**
          的口径，由 get_weighted_bone_names 采集：只扫原始网格数据会漏掉修改器生成的权重——
          镜像修改器开启“翻转顶点组”时把 _R 顶点翻成 _L 组、几何节点写出的权重，
          都只存在于求值结果里，而 FBX 导出恰恰是应用修改器（use_mesh_modifiers=True）的。
          典型坑：只做了右半身几何 + 镜像修改器的网格，若按原始数据判定，_L 整侧会被当成
          无权重，于是只给 _R 一侧加叶骨，与导出的实际蒙皮不一致；
        - 排除 HoTools 约束骨（辅助骨 auxBone.isAuxBone）：fan/twist 等约束骨即使有权重
          也不该补叶骨，否则会污染约束骨末端；
        - 无权重、辅助骨、零长度、建骨失败都记进 skipped，并在末尾打印一行摘要，
          便于反查“为什么这一侧没加叶骨”，不再静默跳过；
        - 叶骨长度为主体骨长度的一半，沿主体骨方向延伸（FBX 导出其实不在意长度，但仍写正确值）；
        - 叶骨归入主骨所属的**所有**骨骼集合（自带 add_leaf_bones 不处理集合，这是自实现的主因；
          集合 JSON 导出须排在本步之后才能收录叶骨）；
        - 叶骨 use_deform=False，不写任何 HoTools 属性，generateMCH 保持默认关闭
          （因此后续 MCH 步骤不会处理它；本步在 MCH 之前执行）。
        """
        from Utils import bone_utils

        edit_bones = ob.data.edit_bones
        data_bones = ob.data.bones

        def _is_aux_bone(bone_name):
            """按名从 data.bones 读辅助骨标记（EDIT 模式下按名访问有效）。"""
            bone = data_bones.get(bone_name)
            props = getattr(bone, "hotools_boneprops", None) if bone else None
            aux = getattr(props, "auxBone", None) if props else None
            return bool(aux and aux.isAuxBone)

        # 先快照目标，避免边加边处理；同时记录每根末端骨被跳过的原因，便于排查“只加了一侧”
        targets = []
        skipped = []
        for eb in edit_bones:
            if eb.children:
                continue
            if eb.name not in weighted_names:
                skipped.append(f"{eb.name}(无权重)")
                continue
            if _is_aux_bone(eb.name):
                skipped.append(f"{eb.name}(辅助骨)")
                continue
            targets.append(eb.name)

        created = 0
        for name in targets:
            eb = edit_bones.get(name)
            if eb is None:
                continue
            vec = eb.tail - eb.head
            length = vec.length
            if length <= 0.0:
                skipped.append(f"{name}(零长度)")
                continue
            try:
                leaf = edit_bones.new(name + FBXExporter.LEAF_SUFFIX)
                leaf.head = eb.tail.copy()
                leaf.tail = eb.tail + vec.normalized() * (length * 0.5)
                leaf.roll = eb.roll
                leaf.parent = eb
                leaf.use_connect = True
                leaf.use_deform = False
                bone_utils.inherit_bone_collections(eb, leaf)
                created += 1
            except Exception as exc:  # 单根失败不应中断其余骨骼
                skipped.append(f"{name}(建骨失败:{exc})")

        summary = f"[HoTools FBX] 叶骨 {ob.name}：新建 {created} 根（候选 {len(targets)}）"
        if skipped:
            shown = "、".join(skipped[:20])
            summary += f"，跳过 {len(skipped)} 根：{shown}" + ("…" if len(skipped) > 20 else "")
        print(summary)

    @staticmethod
    def add_leaf_bones_to_armatures(armature_objects, selection, active_object):
        """给各骨架的无子级有权重骨补叶骨。须在 MCH 步骤之前调用。

        先在 OBJECT 模式按“导出时的求值网格”采集每个骨架的有权重骨名
        （见 get_weighted_bone_names：镜像修改器翻转顶点组、几何节点写出的权重都算），
        再进 EDIT 模式建叶骨。判定口径与 build_leaf_bones 的规则一致。
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
    MCH_PARENT_CONSTRAINT_NAME = "HoTools_MCH_Parent"
    @staticmethod
    def collect_mch_source_bones(armature_objects):
        """收集场景中勾了 generateMCH 的骨，按骨架分组返回 [(骨架名, [骨名,...]), ...]。

        仅用于 UI 预览：读 data.bones 上的 hotools_boneprops.generateMCH，不改任何数据。
        只返回有命中的骨架，骨名按字母排序。
        """
        result = []
        for ob in armature_objects:
            if ob.type != 'ARMATURE':
                continue
            names = [
                b.name for b in ob.data.bones
                if getattr(b, "hotools_boneprops", None) and b.hotools_boneprops.generateMCH
            ]
            if names:
                result.append((ob.name, sorted(names)))
        return result

    @staticmethod
    def no_i18n(name):
        """在每个字符间插入零宽空格，阻止 Blender 界面翻译把骨名等标识符汉化。

        与 VertexGroupTools 那边同款做法：ZWSP 不显示、不影响复制观感，但会打断
        i18n 的整串匹配。仅用于 UI label 展示，不改任何数据。
        """
        return "​".join(name or "")

    @staticmethod
    def preview_armatures():
        """预览用：只取将被导出的骨架 = 当前选中的骨架（导出参数 use_selection=True）。

        预览应与实际导出范围一致，不扫全场景。
        """
        return [ob for ob in bpy.context.selected_objects if ob.type == 'ARMATURE']

    @staticmethod
    def draw_mch_preview(parent_layout, op, toggle_prop):
        """在给定布局里画 MCH 骨折叠预览。op.<toggle_prop> 控制展开/收起。

        列出场景中勾了 generateMCH 的骨，按骨架分组。纯展示，不改数据。
        """
        armature_objects = FBXExporter.preview_armatures()
        groups = FBXExporter.collect_mch_source_bones(armature_objects)
        total = sum(len(names) for _, names in groups)

        box = parent_layout.box()
        header = box.row(align=True)
        expanded = getattr(op, toggle_prop)
        header.prop(
            op, toggle_prop,
            text="", emboss=False,
            icon='DISCLOSURE_TRI_DOWN' if expanded else 'DISCLOSURE_TRI_RIGHT',
        )
        header.label(text=f"MCH 骨预览 ({total})", icon='BONE_DATA')

        if not expanded:
            return
        if not groups:
            info = box.row()
            info.enabled = False
            info.label(text="没有勾选 generateMCH 的骨", icon='INFO')
            return
        for arm_name, names in groups:
            col = box.column(align=True)
            col.label(text=f"{FBXExporter.no_i18n(arm_name)} ({len(names)})", icon='ARMATURE_DATA')
            sub = col.column(align=True)
            sub.enabled = False
            for name in names:
                sub.label(text=FBXExporter.no_i18n(name), icon='BONE_DATA')

    @staticmethod
    def draw_aux_preview(parent_layout, op, toggle_prop):
        """在给定布局里画次级骨（HoTools 辅助骨）折叠预览。op.<toggle_prop> 控制展开/收起。

        复用骨架数据面板那套 _collect_aux_groups 聚合逻辑（按类型+关联骨分组），
        但只做结构展示、不带任何交互（无删除/选择/约束开关）。延迟 import 避免循环依赖。
        """
        try:
            from ..BoneTools.boneProperty import _collect_aux_groups, _AUX_TYPE_LABELS
        except Exception:
            _collect_aux_groups = None
            _AUX_TYPE_LABELS = {}

        armature_objects = FBXExporter.preview_armatures()
        # [(骨架名, [group,...]), ...]，只保留有次级骨的骨架
        arm_groups = []
        total = 0
        if _collect_aux_groups is not None:
            for ob in armature_objects:
                groups = _collect_aux_groups(ob.data)
                if groups:
                    arm_groups.append((ob.name, groups))
                    total += sum(len(g["bones"]) for g in groups)

        box = parent_layout.box()
        header = box.row(align=True)
        expanded = getattr(op, toggle_prop)
        header.prop(
            op, toggle_prop,
            text="", emboss=False,
            icon='DISCLOSURE_TRI_DOWN' if expanded else 'DISCLOSURE_TRI_RIGHT',
        )
        header.label(text=f"次级骨预览 ({total})", icon='GROUP_BONE')

        if not expanded:
            return
        if not arm_groups:
            info = box.row()
            info.enabled = False
            info.label(text="没有检测到 HoTools 次级骨", icon='INFO')
            return
        for arm_name, groups in arm_groups:
            arm_total = sum(len(g["bones"]) for g in groups)
            col = box.column(align=True)
            col.label(text=f"{FBXExporter.no_i18n(arm_name)} ({arm_total})", icon='ARMATURE_DATA')
            for group in groups:
                type_label = _AUX_TYPE_LABELS.get(group["auxType"], group["auxType"])
                sources_text = " + ".join(FBXExporter.no_i18n(s) for s in group["sources"]) if group["sources"] else "（无关联骨）"
                grp = col.column(align=True)
                grp.enabled = False
                grp.label(text=f"{type_label}：{sources_text} ×{len(group['bones'])}")
                for bone_name in group["bones"]:
                    grp.label(text="    " + FBXExporter.no_i18n(bone_name), icon='BONE_DATA')

    @staticmethod
    def draw_collection_preview(parent_layout, op, toggle_prop):
        """在给定布局里画骨骼集合折叠预览。op.<toggle_prop> 控制展开/收起。

        复用 BoneCollectionExporter.build_collections_list（与集合 JSON 导出同源），
        按骨架列出每个集合及其直接持有的骨数量。纯结构展示，不带交互。延迟 import。
        """
        try:
            from .BoneCollectionExporter import BoneCollectionExporter
        except Exception:
            BoneCollectionExporter = None

        armature_objects = FBXExporter.preview_armatures()
        arm_collections = []
        total = 0
        if BoneCollectionExporter is not None:
            for ob in armature_objects:
                cols = BoneCollectionExporter.build_collections_list(ob.data)
                if cols:
                    arm_collections.append((ob.name, cols))
                    total += len(cols)

        box = parent_layout.box()
        header = box.row(align=True)
        expanded = getattr(op, toggle_prop)
        header.prop(
            op, toggle_prop,
            text="", emboss=False,
            icon='DISCLOSURE_TRI_DOWN' if expanded else 'DISCLOSURE_TRI_RIGHT',
        )
        header.label(text=f"骨骼集合预览 ({total})", icon='GROUP_BONE')

        if not expanded:
            return
        if not arm_collections:
            info = box.row()
            info.enabled = False
            info.label(text="没有检测到骨骼集合", icon='INFO')
            return
        for arm_name, cols in arm_collections:
            col = box.column(align=True)
            col.label(text=f"{FBXExporter.no_i18n(arm_name)} ({len(cols)})", icon='ARMATURE_DATA')
            sub = col.column(align=True)
            sub.enabled = False
            for coll in cols:
                sub.label(
                    text=f"{FBXExporter.no_i18n(coll['name'])} ×{len(coll['bones'])}",
                    icon='GROUP_BONE',
                )

    @staticmethod
    def collect_mch_source_edit_bone_names(arm, edit_bones):
        """Collect generateMCH source bones while in EDIT mode."""
        names = []
        for eb in edit_bones:
            bone = arm.bones.get(eb.name)
            props = getattr(bone, "hotools_boneprops", None) if bone else None
            if props and props.generateMCH:
                names.append(eb.name)
        return names

    @staticmethod
    def clear_edit_bones_local_rotation(edit_bones, bone_names):
        """Clear each bone's rest rotation relative to its final export parent."""
        return bone_utils.clear_edit_bone_local_rotations(edit_bones, bone_names)

    @staticmethod
    def build_mch_and_clear(ob):
        """给 generateMCH=True 的骨建 MCH 副本，再把原骨局部旋转清零。

        必须在 EDIT 模式下调用。返回 {原骨名: MCH骨名} 映射，供约束/驱动转移使用。

        处理顺序（不可颠倒）：
        1. 建 MCH 副本，拷贝原骨此刻的 head/tail/roll（此时原骨尚未清零，
           拷到的是原始朝向），MCH 父级设为原主骨的父级、不形变、不相连；
        2. 原始子级保持直接挂在原骨下，MCH 与它们平行，不插入原有父子链；
        3. 全部 MCH 创建完成后，清除 generateMCH 主骨相对原父骨的局部旋转。
        """
        from Utils import bone_utils

        arm = ob.data
        edit_bones = arm.edit_bones

        # 读 data.bones 上的 generateMCH 属性（edit 模式下按名访问有效），确定待处理集合。
        mch_source_names = FBXExporter.collect_mch_source_edit_bone_names(arm, edit_bones)
        if not mch_source_names:
            return {}

        name_map = {}  # 原骨名 -> MCH骨名

        # 先完成全部名称预检，避免处理到一半才发现冲突而留下半成品。
        for src_name in mch_source_names:
            preferred_name = FBXExporter.MCH_PREFIX + src_name
            existing_names = sorted(
                bone.name
                for bone in arm.bones
                if FBXExporter.is_mch_aux_bone_for_source(bone, src_name)
                and edit_bones.get(bone.name) is not None
            )
            if len(existing_names) > 1:
                raise RuntimeError(
                    f"骨架 {getattr(ob, 'name', '<未知>')} 的主骨 {src_name} "
                    "存在多个显式 MCH 辅助骨：" + "、".join(existing_names)
                )
            if existing_names and existing_names[0] != preferred_name:
                raise RuntimeError(
                    f"骨架 {getattr(ob, 'name', '<未知>')} 的主骨 {src_name} "
                    f"已有非标准名称的显式 MCH：{existing_names[0]}；"
                    f"期望名称为 {preferred_name}，创建已终止。"
                )
            if not existing_names and edit_bones.get(preferred_name) is not None:
                raise RuntimeError(
                    f"骨架 {getattr(ob, 'name', '<未知>')} 的主骨 {src_name} "
                    f"生成 MCH 时发生骨名冲突：{preferred_name}；"
                    "创建已终止，请先改名或删除冲突骨。"
                )

        # 所有 MCH 骨归入专属骨骼集合（Blender 4.0+）。没有则新建；低版本无 collections 属性时为 None
        mch_collection = None
        collections = getattr(arm, "collections", None)
        if collections is not None:
            mch_collection = collections.get(MCH_BONE_COLLECTION_NAME)
            if mch_collection is None:
                try:
                    mch_collection = collections.new(MCH_BONE_COLLECTION_NAME)
                except (RuntimeError, AttributeError):
                    mch_collection = None

        # 1. 先建全部 MCH 副本，拷贝原始朝向。只按 Aux 属性复用既有 MCH；
        # 同名普通骨必须保留，Blender 会为新 MCH 分配唯一名称。
        for src_name in mch_source_names:
            src = edit_bones.get(src_name)
            if src is None:
                continue
            existing_names = sorted(
                bone.name
                for bone in arm.bones
                if FBXExporter.is_mch_aux_bone_for_source(bone, src_name)
                and edit_bones.get(bone.name) is not None
            )
            if existing_names:
                mch = edit_bones.get(existing_names[0])
            else:
                mch = edit_bones.new(FBXExporter.MCH_PREFIX + src_name)
                mch.head = src.head.copy()
                mch.tail = src.tail.copy()
                mch.roll = src.roll
            mch.use_deform = False
            # Keep MCH outside the deform chain.  Its runtime relationship to
            # the source bone is supplied by a Parent/Child Of constraint.
            mch.parent = src.parent
            mch.use_connect = False
            # 归入 MCH 专属集合
            if mch_collection is not None:
                try:
                    bone_utils.replace_bone_collections(mch, [mch_collection])
                except (RuntimeError, AttributeError):
                    pass
            name_map[src_name] = mch.name

        # 2. 原始子级保持原父级，MCH 只作为主骨下的平行旁路骨。

        # 3. MCH 全部创建后，沿原主骨链清除主骨的局部旋转。
        mch_main_names = FBXExporter.collect_mch_source_edit_bone_names(arm, edit_bones)
        FBXExporter.clear_edit_bones_local_rotation(edit_bones, mch_main_names)

        return name_map
    @staticmethod
    def clear_pose_bone_transform(pose_bone):
        """Reset one pose bone's local L/R/S and matrix basis to identity."""
        bone_utils.clear_pose_bone_transform(pose_bone)

    @staticmethod
    def clear_pose_bone_transforms(ob, bone_names):
        """Clear pose transforms for the original main bones after EDIT changes."""
        return bone_utils.clear_pose_bone_transforms(ob, bone_names)

    @staticmethod
    def transfer_constraints_to_mch(ob, name_map):
        """把本骨架内指向 name_map 里原骨的约束 subtarget / 驱动 bone_target 改指对应 MCH。

        只处理指向本骨架自身（target==ob）的引用，与 Rig 约束 IR 的单骨架范围一致；
        跨骨架引用不动。在 OBJECT 模式下调用。
        """
        if not name_map:
            return

        # 1. pose bone 约束：subtarget（及带极向目标的 pole_subtarget）。
        # 本函数在 MCH Parent 创建前执行，因此无需按显示名称排除生成约束。
        for pbone in ob.pose.bones:
            for con in pbone.constraints:
                if FBXExporter.is_registered_mch_parent_constraint(ob, pbone, con):
                    continue
                if getattr(con, "target", None) == ob:
                    sub = getattr(con, "subtarget", "")
                    if sub in name_map and name_map[sub] != pbone.name:
                        con.subtarget = name_map[sub]
                if getattr(con, "pole_target", None) == ob:
                    psub = getattr(con, "pole_subtarget", "")
                    if psub in name_map and name_map[psub] != pbone.name:
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
    def add_mch_parent_constraints(ob, name_map):
        """Bind each MCH sidecar to its source with a preserved bind offset."""
        if not name_map:
            return 0

        # Preflight every owner before changing metadata or adding the first
        # Parent constraint. A later collision must not leave earlier MCH bones
        # partially rewritten.
        from BoneTools.boneProperty import _ensure_aux_constraint_name_available
        for _source_name, mch_name in name_map.items():
            mch = ob.pose.bones.get(mch_name)
            if mch is not None:
                _ensure_aux_constraint_name_available(
                    mch,
                    FBXExporter.MCH_PARENT_CONSTRAINT_NAME,
                    "CHILD_OF",
                )

        count = 0
        pending_inverse = []
        for source_name, mch_name in name_map.items():
            source = ob.pose.bones.get(source_name)
            mch = ob.pose.bones.get(mch_name)
            if source is None or mch is None:
                continue

            mch_bone = ob.data.bones.get(mch_name)
            mch_props = getattr(mch_bone, "hotools_boneprops", None)
            mch_aux = getattr(mch_props, "auxBone", None) if mch_props else None
            registered_names = {
                str(getattr(item, "name", ""))
                for item in getattr(mch_aux, "constraintNames", ())
                if getattr(item, "name", "")
            }
            constraint = next(
                (
                    item
                    for item in mch.constraints
                    if item.type == "CHILD_OF" and item.name in registered_names
                ),
                None,
            )
            from BoneTools.boneProperty import _register_aux_constraint
            if mch_props is not None and hasattr(mch_props, "generateMCH"):
                mch_props.generateMCH = False
            if mch_aux is not None:
                mch_aux.isAuxBone = True
                mch_aux.auxType = "MCH"
                mch_aux.sourceBones.clear()
                mch_aux.constraintNames.clear()
                source_ref = mch_aux.sourceBones.add()
                source_ref.name = source_name

            if constraint is None:
                constraint = mch.constraints.new("CHILD_OF")
            constraint.name = FBXExporter.MCH_PARENT_CONSTRAINT_NAME
            constraint.target = ob
            constraint.subtarget = source_name
            constraint.influence = 1.0
            constraint.use_location_x = True
            constraint.use_location_y = True
            constraint.use_location_z = True
            constraint.use_rotation_x = True
            constraint.use_rotation_y = True
            constraint.use_rotation_z = True
            constraint.use_scale_x = False
            constraint.use_scale_y = False
            constraint.use_scale_z = False
            _register_aux_constraint(mch, constraint)

            pending_inverse.append((mch_name, constraint.name))
            count += 1

        if pending_inverse:
            previous_active = bpy.context.view_layer.objects.active
            ob.select_set(True)
            bpy.context.view_layer.objects.active = ob
            bpy.ops.object.mode_set(mode="POSE")
            try:
                for bone in ob.data.bones:
                    bone.select = False
                for mch_name, constraint_name in pending_inverse:
                    active_bone = ob.data.bones.get(mch_name)
                    if active_bone is None:
                        continue
                    active_bone.select = True
                    ob.data.bones.active = active_bone
                    result = bpy.ops.constraint.childof_set_inverse(
                        constraint=constraint_name,
                        owner="BONE",
                    )
                    if result != {"FINISHED"}:
                        raise RuntimeError(
                            f"Failed to preserve CHILD_OF offset for {mch_name}"
                        )
            finally:
                bpy.ops.object.mode_set(mode="OBJECT")
                if previous_active is not None:
                    bpy.context.view_layer.objects.active = previous_active

        bpy.context.view_layer.update()
        return count

    @staticmethod
    def is_mch_aux_bone_for_source(data_bone, source_name):
        """Return whether one data Bone explicitly describes this MCH relation."""
        props = getattr(data_bone, "hotools_boneprops", None)
        aux = getattr(props, "auxBone", None) if props is not None else None
        if aux is None or not bool(getattr(aux, "isAuxBone", False)):
            return False
        if str(getattr(aux, "auxType", "")).strip().upper() != "MCH":
            return False
        source_names = [
            str(getattr(item, "name", ""))
            for item in getattr(aux, "sourceBones", ())
            if getattr(item, "name", "")
        ]
        return source_names == [source_name]

    @staticmethod
    def is_registered_mch_parent_constraint(ob, pose_bone, constraint):
        """Identify an existing generated Parent by owner-local Aux metadata."""
        data_bone = ob.data.bones.get(getattr(pose_bone, "name", ""))
        props = getattr(data_bone, "hotools_boneprops", None)
        aux = getattr(props, "auxBone", None) if props is not None else None
        if aux is None or not bool(getattr(aux, "isAuxBone", False)):
            return False
        if str(getattr(aux, "auxType", "")).strip().upper() != "MCH":
            return False
        registered_names = {
            str(getattr(item, "name", ""))
            for item in getattr(aux, "constraintNames", ())
            if getattr(item, "name", "")
        }
        source_names = [
            str(getattr(item, "name", ""))
            for item in getattr(aux, "sourceBones", ())
            if getattr(item, "name", "")
        ]
        return (
            getattr(constraint, "type", "") == "CHILD_OF"
            and getattr(constraint, "name", "") in registered_names
            and getattr(constraint, "target", None) == ob
            and source_names == [getattr(constraint, "subtarget", "")]
        )

    @staticmethod
    def export_armature_constraint_ir(ob, fbx_filepath, suffix):
        """Write the armature's neutral rig constraint IR next to the FBX."""
        from .ConstraintIRExporter import ConstraintIRExporter

        constraint_ir = ConstraintIRExporter.build_ir(ob)
        if constraint_ir.is_empty():
            return None

        base_name = os.path.splitext(os.path.basename(fbx_filepath))[0]
        json_path = FBXExporter.unity_metadata_path(
            fbx_filepath,
            f"{base_name}_{ob.name}{suffix}.json",
        )
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                constraint_ir.to_dict(),
                f,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            f.write("\n")
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

        base_name = os.path.splitext(os.path.basename(fbx_filepath))[0]
        json_path = FBXExporter.unity_metadata_path(
            fbx_filepath,
            f"{base_name}_{ob.name}{suffix}.json",
        )
        BoneCollectionExporter.export_to_file(ob.data, json_path)
        return json_path

    @staticmethod
    def export_humanoid_mapping_json(mapping_data, fbx_filepath, suffix):
        """Write authored Humanoid labels captured before the MCH rewrite."""
        if not mapping_data:
            return None

        base_name = os.path.splitext(os.path.basename(fbx_filepath))[0]
        json_path = FBXExporter.unity_metadata_path(
            fbx_filepath,
            f"{base_name}{suffix}.json",
        )
        data = HumanoidMappingExporter.write_export_dict(mapping_data, json_path)
        return json_path if data is not None else None

    @staticmethod
    def export_unity_metadata_manifest(fbx_filepath, entries):
        """Write the sidecar index consumed by Unity asset post-processing."""
        base_name = os.path.splitext(os.path.basename(fbx_filepath))[0]
        json_path = FBXExporter.unity_metadata_path(
            fbx_filepath,
            f"{base_name}_unity.json",
        )
        manifest = {
            "version": "3.0",
            "exportTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "fbxFile": os.path.basename(fbx_filepath),
            "files": entries,
        }
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
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
    def capture_armatures_pose_position(armature_objects):
        state = []
        for ob in armature_objects:
            armature = ob.data
            if not hasattr(armature, "pose_position"):
                continue
            state.append((armature.name, armature.pose_position))
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
    def mesh_has_evaluated_modifiers(ob) -> bool:
        """是否存在会被 FBX 导出评估的修改器（骨架修改器由导出单独处理，不算）。"""
        for modifier in ob.modifiers:
            if modifier.type == "ARMATURE":
                continue
            if modifier.show_viewport or modifier.show_render:
                return True
        return False

    @staticmethod
    def bake_shape_keys_through_modifiers(objects, triangulate=False):
        """导出前把形态键烘焙穿过修改器栈，返回 (已烘焙, 已跳过, 失败)。

        隐式操作：没有开关，导出流程无条件调用（用户不需要知道这件事，但一旦漏掉
        就会表现为“形态键没了”）。

        真正的实现在 ``Utils.shapekey_utils.bake_modifiers_keeping_shape_keys``——
        和修改器面板的「保持形态键应用」按钮**共用同一套逻辑**，这里只负责导出侧的
        取舍与报告：
        - 口径按“FBX 会评估的修改器”（show_viewport or show_render），
          骨架修改器保留给导出做蒙皮（对应 core 的 include_render_only=True / keep_armature=True）；
        - 需要三角化时先补一个三角化修改器一起烘焙：形态键会阻止单独应用三角化修改器，
          已经是三角面的网格则不必为三角化多烘一遍；
        - 未成功烘焙的物体要撤掉临时三角化修改器，避免残留在工程里影响导出。

        必须处理的原因：Blender 原生 FBX 导出在“物体还有修改器要应用”时走 evaluated mesh
        （io_scene_fbx 的 bpy.data.meshes.new_from_object 分支），而求值网格不带形态键
        （见 Blender 议题 #104714），于是“形态键 + 几何节点”这类物体导出的 FBX 里
        BlendShape 会被静默丢掉——物体本身能导出，但形变数据没了。

        触发条件：网格有形态键，且（有待评估的修改器，或开启了三角化）。
        只带形态键、没有其它修改器、也不需要三角化的网格不会被碰。
        全部改动随导出末尾的 undo 回滚，工程不留痕。
        """
        from Utils import shapekey_utils

        baked = []
        skipped = []
        failed = []
        if not objects:
            return baked, skipped, failed

        for ob in objects:
            if ob.type != "MESH" or ob.name not in bpy.context.view_layer.objects:
                continue
            mesh = getattr(ob, "data", None)
            shape_keys = getattr(mesh, "shape_keys", None)
            if shape_keys is None or len(shape_keys.key_blocks) < 2:
                continue
            if not FBXExporter.mesh_has_evaluated_modifiers(ob):
                # 没有要评估的修改器时，只有“需要三角化”才值得烘焙：
                # 形态键会阻止三角化修改器单独应用，只能连形态键一起烘。
                if not triangulate:
                    continue
                if all(len(polygon.vertices) == 3 for polygon in mesh.polygons):
                    continue

            temp_triangulate = (
                FBXExporter.add_export_triangulate_modifier(ob) if triangulate else None
            )
            # 烘焙的是“修改器结果”，必须排除骨架形变：导出流程此时按 applyArmaturePose
            # 的需要把骨架放在 POSE 显示，直接求值会把当前姿态（含约束结果）烘进基础网格，
            # 而骨架修改器还留在网格上，导出后会被再形变一次（双重形变）。
            # Blender 内置导出也是临时切 REST 再求值网格（io_scene_fbx 的 backup_pose_positions），
            # 这里照做，求值完立刻还原，不影响后面的应用姿态步骤。
            pose_position_states = []
            for modifier in ob.modifiers:
                if modifier.type != "ARMATURE":
                    continue
                armature_data = getattr(getattr(modifier, "object", None), "data", None)
                if armature_data is None or not hasattr(armature_data, "pose_position"):
                    continue
                pose_position_states.append((armature_data, armature_data.pose_position))
                armature_data.pose_position = "REST"
            try:
                ob_baked, ob_skipped, ob_failed = (
                    shapekey_utils.bake_modifiers_keeping_shape_keys(
                        [ob],
                        include_render_only=True,
                        keep_armature=True,
                    )
                )
            except Exception as exc:  # core 内部已尽量自恢复，这里兜底
                FBXExporter.remove_modifier_if_present(ob, temp_triangulate)
                failed.append((ob.name, exc))
                continue
            finally:
                for armature_data, pose_position in pose_position_states:
                    try:
                        armature_data.pose_position = pose_position
                    except (ReferenceError, TypeError):
                        pass

            if ob_baked:
                baked.extend(ob_baked)
            else:
                # 没烘成：临时三角化修改器不能留在工程里
                FBXExporter.remove_modifier_if_present(ob, temp_triangulate)
                skipped.extend(ob_skipped)
                failed.extend(ob_failed)

        return baked, skipped, failed

    @staticmethod
    def mute_pose_constraints(armature_objects) -> list[tuple]:
        """临时静音骨架上的全部姿态骨约束，返回可还原的状态列表。

        用途：应用骨架姿态（ho.apply_rest_pose）会把骨架修改器的求值结果烘进子级网格，
        而求值时约束是生效的——约束结果就这样进了静置/网格，运行时再按 JSON 应用一次就重复了。
        所以「删除约束」语义下，要在应用姿态这一步先把约束静音，让它不参与这次求值；
        真正的删除仍放在 MCH 与约束 JSON 之后（那两处都必须看到约束），静音在这里用完即还。
        """
        states = []
        for ob in armature_objects:
            pose = getattr(ob, "pose", None)
            if pose is None:
                continue
            for pose_bone in pose.bones:
                for constraint in pose_bone.constraints:
                    states.append((constraint, bool(getattr(constraint, "mute", False))))
                    try:
                        constraint.mute = True
                    except (AttributeError, ReferenceError, TypeError):
                        continue
        return states

    @staticmethod
    def restore_pose_constraint_mute(states) -> None:
        """还原 mute_pose_constraints 记录的约束静音状态。"""
        for constraint, was_muted in states or ():
            try:
                constraint.mute = was_muted
            except (AttributeError, ReferenceError, TypeError):
                continue

    @staticmethod
    def clear_exported_constraints(objects) -> tuple[int, int]:
        """清空即将导出对象上的全部约束，返回 (涉及物体数, 删除的约束数)。

        为什么需要清（实测隐患）：HoTools 的约束只通过 JSON（Rig 约束 IR）中转给运行时，
        FBX 里不该再有一份；但 Blender 内置 FBX 导出不会删掉约束——它把约束后的结果当成
        物体/骨骼的实际变换写进 FBX（物体级取 matrix_world、骨骼级取 pose matrix），
        于是导入引擎后约束效果被“应用”了一次，和 JSON 描述对不上，内外不一致。
        反过来，如果骨架/物体本来就靠约束摆位（例如被约束驱动的 Empty），清掉约束又会
        改变导出位置——所以这一步由「导出前清空约束」开关决定（默认清空，保持 JSON 唯一来源）。

        调用时机：MCH 之后（MCH 要把原始约束转移到 MCH 骨上，约束 IR 记录的是转移后的事实）、
        约束 JSON 写完之后（JSON 是约束的唯一载体），以及所有还会读变换/求值的预处理
        （矫正物体变换会用 matrix_world 复原父级逆矩阵）与内置导出之前。
        清空范围：导出范围内的物体级约束 + 其姿态骨约束（含 MCH 步骤刚加的 MCH Parent 约束，
        因为约束 IR 已经记录了 MCH 预处理后的事实）。
        本步是临时修改，随导出末尾的 undo 一起回滚，工程不留痕。
        """
        cleared_objects: set[str] = set()
        cleared_constraints = 0

        for ob in objects:
            if ob is None:
                continue

            object_constraints = getattr(ob, "constraints", None)
            if object_constraints is not None:
                for constraint in list(object_constraints):
                    try:
                        object_constraints.remove(constraint)
                    except (ReferenceError, RuntimeError):
                        continue
                    cleared_constraints += 1
                    cleared_objects.add(ob.name)

            pose = getattr(ob, "pose", None)
            if pose is None:
                continue
            for pose_bone in pose.bones:
                for constraint in list(pose_bone.constraints):
                    try:
                        pose_bone.constraints.remove(constraint)
                    except (ReferenceError, RuntimeError):
                        continue
                    cleared_constraints += 1
                    cleared_objects.add(ob.name)

        return len(cleared_objects), cleared_constraints

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
        """给各骨架建 MCH 并清零主骨，随后转移约束/驱动。
        返回 {骨架名: {原骨名: MCH骨名}}。

        流程：EDIT 模式建 MCH + 清零静置朝向 → 回 OBJECT 模式清 pose 变换并转移约束/驱动。
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

            # 回 OBJECT 模式后 pose bones 才刷新。先清主骨 pose 变换并转移既有引用，
            # 最后创建 MCH Parent；这样无需用约束显示名称识别并排除生成约束。
            for ob in view_layer_armatures:
                name_map = name_maps.get(ob.name, {})
                FBXExporter.clear_pose_bone_transforms(ob, name_map.keys())
                FBXExporter.transfer_constraints_to_mch(ob, name_map)
                FBXExporter.add_mch_parent_constraints(ob, name_map)
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

    addLeafBones:BoolProperty(name="添加叶骨",description="给无子级且有权重的骨末端补一根叶骨(HoTools自己的实现,长度为主体骨长的一半)。权重按导出时的求值网格判定(镜像修改器/几何节点生成的权重也算),无权重骨与辅助骨不加,新叶骨不写HoTools属性、不参与MCH。在MCH步骤之前执行",default=True) # type: ignore
    generateMCHBones:BoolProperty(name="生成MCH骨(动捕适配)",description="为勾选了generateMCH的骨生成MCH_前缀同级旁路骨、清空主骨变换并写入HoTools_MCH_Parent绑定。不留痕",default=True) # type: ignore
    showMCHPreview:BoolProperty(name="MCH 骨预览",description="展开/收起：列出场景中勾了 generateMCH 的骨（按骨架分组）",default=False) # type: ignore
    showAuxPreview:BoolProperty(name="次级骨预览",description="展开/收起：列出场景中各骨架的 HoTools 次级骨（辅助骨，按类型+关联骨分组），仅结构展示不可交互",default=False) # type: ignore
    showCollectionPreview:BoolProperty(name="骨骼集合预览",description="展开/收起：列出场景中各骨架的骨骼集合（Bone Collections）及每个集合持有的骨数量，仅结构展示不可交互",default=False) # type: ignore
    exportBoneConstraint:BoolProperty(name="导出Rig约束IR(JSON)",description="导出Aux骨、原始Blender约束参数和MCH绑定的中立IR；最终运行时方案由导入端决定",default=False) # type: ignore
    boneConstraintSuffix:bpy.props.StringProperty(name="约束IR后缀",description="HoFBX文件夹内的Rig约束IR文件名后缀:<FBX名>_<骨架名><后缀>.json",default="_constraint") # type: ignore
    exportBoneCollection:BoolProperty(name="导出骨骼集合(JSON)",description="导出各骨架的骨骼集合(Bone Collections)为JSON,统一写入FBX旁的HoFBX文件夹",default=False) # type: ignore
    boneCollectionSuffix:bpy.props.StringProperty(name="集合后缀",description="HoFBX文件夹内的集合JSON文件名后缀:<FBX名>_<骨架名><后缀>.json",default="_collection") # type: ignore
    exportHumanoidMapping:BoolProperty(name="导出Humanoid映射(JSON)",description="导出 Blender 中已标记的 Humanoid mapping，让 Unity 导入时按准确的 boneName 配置 Avatar，避免 MCH 骨名猜测",default=True) # type: ignore
    humanoidMappingSuffix:bpy.props.StringProperty(name="Humanoid后缀",description="HoFBX文件夹内的Humanoid mapping JSON文件后缀",default="_humanoid") # type: ignore
    exportUnityMetadata:BoolProperty(name="自动导出Unity元数据",description="一次FBX导出自动生成Rig约束IR、骨骼集合和Humanoid映射JSON；关闭后可用下面的细分开关选择性导出",default=True) # type: ignore
    applyArmaturePose:BoolProperty(name="应用骨架姿态",description="导出前调用 HoTools 的应用骨架姿态操作，将当前选中骨架的 Pose 应用为静置姿态。操作失败时跳过该骨架并提示警告。不留痕",default=True) # type: ignore
    # 保留 RNA 属性名以兼容已保存的预设；界面名称已扩展为同时处理曲线和共享网格对象。
    meshifyCurves:BoolProperty(name="网格化对象",description="导出前把选中的曲线临时转换为网格，并为共享 Mesh 数据的对象（包括 Alt+D）创建独立数据，让 HoFBX 能正确导出。不留痕",default=True) # type: ignore
    triangulateMeshes:BoolProperty(name="三角化",description="导出前使用 Blender Triangulate 修改器固定四边形为 FIXED、多边形为 BEAUTY、最少顶点为4，并开启保持法向。不留痕",default=False) # type: ignore
    fixObjectTransform:BoolProperty(name="矫正物体变换",description="执行原有的物体变换/旋转矫正预处理",default=True) # type: ignore
    cleanWeights:BoolProperty(name="清理权重",description="导出前清理形变网格权重(仅骨骼权重组,非骨骼组不动):删除<0.0001的微小权重→每顶点最多保留4个骨权重组→归一化。不留痕",default=False) # type: ignore
    cleanEmptyMaterialSlots:BoolProperty(name="清理未使用材质槽",description="导出前删除选中网格中没有被任何面使用的材质槽（无论槽中是否已有材质）。不留痕",default=True) # type: ignore
    removeHiddenModifiers:BoolProperty(name="删除隐藏修改器",description="导出前临时删除视口隐藏的修改器，用于绕过隐藏 GN 阻塞形态键应用修改器的问题",default=True) # type: ignore
    ignoreGeometryNodes:BoolProperty(name="忽略几何节点",description="导出前临时删除所有几何节点修改器，避免几何节点改变导出网格拓扑。不留痕",default=True) # type: ignore
    applyExportConstraints:BoolProperty(name="应用约束",description="关(默认):约束JSON写完后删除导出范围内的全部约束(物体级+姿态骨),约束只走JSON,避免内置导出把约束结果当成实际变换写进FBX造成内外不一致。开:保留约束交给内置导出应用(资产靠约束摆位时用)。不留痕",default=False) # type: ignore
    ignoreOutlineModifiers:BoolProperty(name="忽略描边修改器",description="导出前临时删除描边修改器（开启了翻转法线的实体化修改器）。不留痕",default=True) # type: ignore

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
        metadata_entries = []
        selected_armature_objects = [
            ob for ob in selection if ob.type == "ARMATURE"
        ]
        humanoid_mapping_data = None
        failed_data_transfer_count = 0
        failed_material_sort_count = 0
        failed_triangulate_count = 0
        failed_armature_pose_count = 0

        #准备操作，全显场景中的对象与集合，并且全选
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")

        FBXExporter.unhide_collections(col=bpy.context.view_layer.layer_collection)
        FBXExporter.unhide_objects()

        try:
            pose_position_state = FBXExporter.capture_armatures_pose_position(
                armature_objects
            )
            if self.applyArmaturePose:
                # Keep the authored Pose evaluated while mesh modifiers are baked
                # by ho.apply_rest_pose below.
                FBXExporter.set_armatures_pose_position(armature_objects, "POSE")
            else:
                FBXExporter.set_armatures_pose_position(armature_objects, "REST")

            # Capture authored labels while the original Blender hierarchy and
            # bone properties are still intact.  MCH generation below changes
            # only the temporary export scene, not this mapping data.
            humanoid_mapping_data = HumanoidMappingExporter.build_export_dict(
                selected_armature_objects
            )

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

            if self.meshifyCurves:
                converted_objects, made_single_user, failed_meshify, selection, active_object = (
                    FBXExporter.meshify_selected_objects(selection, active_object)
                )
                if failed_meshify:
                    print("[HoTools FBX] Failed to meshify objects:")
                    for ob_name, exc in failed_meshify:
                        print(f"  {ob_name}: {type(exc).__name__}: {exc}")
                    self.report({"WARNING"}, f"{len(failed_meshify)} 个对象网格化失败，详见控制台")
                print(
                    f"[HoTools FBX] 对象网格化：转换了 {converted_objects} 个曲线类对象，"
                    f"创建了 {made_single_user} 个独立 Mesh 数据"
                )

            # 形态键 + 待评估修改器（几何节点等）：先烘焙再导出，否则 Blender 原生导出
            # 走求值网格会把形态键静默丢掉（物体能导出，但 BlendShape 没了）。
            # 隐式操作、无开关：用户不需要知道这件事，但一旦出问题就会“形态键没了”。
            # 须在数据传递/三角化等“应用修改器”步骤之前：烘焙后这些步骤才能正常生效；
            # 三角化一并交给烘焙步骤（形态键会阻止单独应用三角化修改器）。
            (
                baked_shape_keys,
                skipped_shape_keys,
                failed_shape_keys,
            ) = FBXExporter.bake_shape_keys_through_modifiers(
                selection, triangulate=self.triangulateMeshes
            )
            if baked_shape_keys:
                print("[HoTools FBX] 形态键烘焙穿过修改器：")
                for line in baked_shape_keys:
                    print(f"  {line}")
            for ob_name, reason in skipped_shape_keys:
                print(f"[HoTools FBX] 形态键烘焙跳过 {ob_name}：{reason}")
            for ob_name, exc in failed_shape_keys:
                print(f"[HoTools FBX] 形态键烘焙失败 {ob_name}：{type(exc).__name__}: {exc}")
            if skipped_shape_keys or failed_shape_keys:
                self.report(
                    {"WARNING"},
                    f"{len(skipped_shape_keys) + len(failed_shape_keys)} 个物体的形态键"
                    f"未能烘焙穿过修改器，详见控制台",
                )

            # blender数据传递修改器在fbx导出时应用环境不齐全需要手动应用防止错误效果
            (
                data_transfer_applied,
                failed_data_transfer,
                selection,
                active_object,
            ) = (
                FBXExporter.apply_data_transfer_modifiers(
                    selection,
                    selection,
                    active_object,
                )
            )
            failed_data_transfer_count = len(failed_data_transfer)
            if failed_data_transfer:
                print("[HoTools FBX] Failed to apply data transfer modifiers:")
                for ob_name, modifier_name, exc in failed_data_transfer:
                    print(
                        f"  {ob_name}.{modifier_name}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                self.report(
                    {"WARNING"},
                    f"{len(failed_data_transfer)} 个数据传递修改器隐式修复失败，详见控制台",
                )
            if data_transfer_applied:
                print(
                    f"[HoTools FBX] 数据传递修改器隐式修复：手动应用了 "
                    f"{data_transfer_applied} 个修改器"
                )
            if self.applyArmaturePose:
                # 约束处理与应用骨架姿态是同一件事的两面：都是“当前求值状态要不要固化”。
                # ho.apply_rest_pose 会把骨架修改器的求值结果烘进子级网格 + 把姿态应用成静置，
                # 而求值时约束是生效的。所以「应用约束」开关在这里生效：
                #   关（默认，删除语义）→ 应用姿态这一步先静音约束，让约束结果不进入静置/网格，
                #                        约束只走 JSON（真正删除排在 MCH 与 JSON 之后）；
                #   开（应用语义）    → 约束照常参与这次求值，并保留给内置导出应用。
                muted_states = []
                if not self.applyExportConstraints and selected_armature_objects:
                    muted_states = FBXExporter.mute_pose_constraints(
                        selected_armature_objects
                    )
                    if muted_states:
                        print(
                            f"[HoTools FBX] 应用姿态前静音 {len(muted_states)} 条姿态约束"
                            f"（约束不参与本次固化，之后仍会写进 JSON）"
                        )
                try:
                    applied_armatures, failed_armatures, selection, active_object = (
                        FBXExporter.apply_selected_armature_poses(
                            selected_armature_objects,
                            selection,
                            active_object,
                        )
                    )
                finally:
                    FBXExporter.restore_pose_constraint_mute(muted_states)
                failed_armature_pose_count = len(failed_armatures)
                if failed_armatures:
                    print("[HoTools FBX] Failed to apply armature poses:")
                    for ob_name, exc in failed_armatures:
                        print(f"  {ob_name}: {type(exc).__name__}: {exc}")
                    self.report(
                        {"WARNING"},
                        f"{len(failed_armatures)} 个骨架应用姿态失败，已跳过，详见控制台",
                    )
                print(f"[HoTools FBX] 应用骨架姿态：成功处理 {applied_armatures} 个骨架")

            # 应用姿态后再切换到 REST 显示，避免 FBX 导出时回到原始静置姿态。
            FBXExporter.set_armatures_pose_position(armature_objects, "REST")

            if self.triangulateMeshes:
                (
                    triangulated_meshes,
                    failed_triangulate,
                    selection,
                    active_object,
                ) = FBXExporter.triangulate_export_meshes(
                    selection,
                    selection,
                    active_object,
                )
                failed_triangulate_count = len(failed_triangulate)
                if failed_triangulate:
                    print("[HoTools FBX] Failed to triangulate meshes:")
                    for ob_name, exc in failed_triangulate:
                        print(
                            f"  {ob_name}: {type(exc).__name__}: {exc}"
                        )
                    self.report(
                        {"WARNING"},
                        "导出网格三角化失败，详见控制台",
                    )
                elif triangulated_meshes:
                    print(
                        f"[HoTools FBX] 三角化：处理了 "
                        f"{triangulated_meshes} 个 Mesh"
                    )

            # blender默认的fbx导出对材质slot顺序的处理不是unity喜欢的按面排序，
            # 会导致多物体多材质fbx导出进unity时材质slot顺序不对（同fbx导回bl正常）。
            # 这不是材质引用丢失，而是两边对面/子网格顺序的处理习惯不同。
            (
                material_sort_processed,
                failed_material_sort,
                selection,
                active_object,
            ) = FBXExporter.sort_export_meshes_by_material(
                selection,
                selection,
                active_object,
            )
            failed_material_sort_count = len(failed_material_sort)
            if failed_material_sort:
                print("[HoTools FBX] Failed to sort mesh faces by material:")
                for target_name, exc in failed_material_sort:
                    print(
                        f"  {target_name}: {type(exc).__name__}: {exc}"
                    )
                self.report(
                    {"WARNING"},
                    "导出网格按材质整理面顺序失败，详见控制台",
                )
            elif material_sort_processed:
                print(
                    f"[HoTools FBX] 材质面顺序隐式修复：整理了 "
                    f"{material_sort_processed} 个 Mesh"
                )

            if self.cleanEmptyMaterialSlots:
                cleaned_meshes, removed_slots = FBXExporter.clean_unused_material_slots(
                    selection
                )
                print(
                    f"[HoTools FBX] 未使用材质槽清理：处理了 {cleaned_meshes} 个网格，"
                    f"删除了 {removed_slots} 个槽"
                )

            # 清理权重（须在补叶骨之前：叶骨依据"有权重"判定，清理后判定更准；仅动骨骼权重组）
            if self.cleanWeights:
                cleaned = FBXExporter.clean_export_weights(bpy.context.scene.objects)
                print(f"[HoTools FBX] 权重清理：处理了 {cleaned} 个网格")

            # 补叶骨（须在 MCH 之前：新叶骨 generateMCH 默认关，不会被 MCH 处理）
            if self.addLeafBones and armature_objects != []:
                FBXExporter.add_leaf_bones_to_armatures(
                    armature_objects, selection, active_object
                )

            # 生成 MCH 骨并清零主骨；返回各骨架的 {原骨名: MCH名} 映射
            mch_name_maps = {}
            if self.generateMCHBones and armature_objects != []:
                mch_name_maps = FBXExporter.clear_armatures_bone_rotation(
                    armature_objects,
                    selection,
                    active_object,
                )

            # JSON 只针对将被导出的骨架 = 原始选中的骨架（与 FBX use_selection=True 一致）
            selected_armature_names = {
                ob.name for ob in selection if ob.type == "ARMATURE"
            }

            # 导出中立 Rig 约束 IR。约束目标保留 MCH 预处理后的 Blender 事实
            # （所以必须排在 MCH 之后），且必须早于下面清空约束——JSON 是约束的唯一载体。
            # 这里也不依赖可见性/选择状态，提前写不会影响后面的预处理。
            export_constraints = self.exportUnityMetadata or self.exportBoneConstraint
            export_collections = self.exportUnityMetadata or self.exportBoneCollection
            export_humanoid = self.exportUnityMetadata or self.exportHumanoidMapping

            if export_constraints:
                for ob in armature_objects:
                    if ob.name not in selected_armature_names:
                        continue
                    if ob.name not in bpy.context.view_layer.objects:
                        continue
                    json_path = FBXExporter.export_armature_constraint_ir(
                        ob, self.filepath, self.boneConstraintSuffix
                    )
                    if json_path:
                        exported_json.append(json_path)
                        metadata_entries.append({
                            "kind": "rigConstraintIR",
                            "armatureName": ob.name,
                            "file": os.path.basename(json_path),
                        })

            # 导出骨骼集合 JSON
            if export_collections:
                for ob in armature_objects:
                    if ob.name not in selected_armature_names:
                        continue
                    if ob.name not in bpy.context.view_layer.objects:
                        continue
                    json_path = FBXExporter.export_armature_collections_json(
                        ob, self.filepath, self.boneCollectionSuffix
                    )
                    if json_path:
                        exported_json.append(json_path)
                        metadata_entries.append({
                            "kind": "collections",
                            "armatureName": ob.name,
                            "file": os.path.basename(json_path),
                        })

            if export_humanoid:
                json_path = FBXExporter.export_humanoid_mapping_json(
                    humanoid_mapping_data,
                    self.filepath,
                    self.humanoidMappingSuffix,
                )
                if json_path:
                    exported_json.append(json_path)
                    metadata_entries.append({
                        "kind": "humanoid",
                        "file": os.path.basename(json_path),
                    })

            if self.exportUnityMetadata:
                manifest_path = FBXExporter.export_unity_metadata_manifest(
                    self.filepath,
                    metadata_entries,
                )
                exported_json.append(manifest_path)

            # 约束处理：开关「应用约束」决定语义（默认关 = 删除）。
            # 与应用骨架姿态是同一件事的两面（都是“当前求值状态要不要固化”），所以在应用姿态
            # 那一步就已经按开关静音过约束了；这里是“删除语义”下的真正删除。
            # 为什么删除必须留在这里（不能跟应用姿态放一起）：
            #   - MCH 要把原始约束转移到 MCH 骨上，约束 IR 记录的也是转移后的事实，删早了 MCH 无约束可转；
            #   - 约束 JSON 是约束的唯一载体，删早了就没东西可写。
            # 为什么又必须早于下面：内置导出不会删约束，会把约束结果当成实际变换写进 FBX
            # （物体级 matrix_world、骨骼级 pose matrix）；矫正物体变换也用 matrix_world 复原
            # 父级逆矩阵，带约束的 matrix_world 会把约束结果烘进 matrix_basis。
            # 开着「应用约束」时保留约束，交给内置导出应用（资产本来就靠约束摆位时用）。
            # 本步随导出末尾的 undo 一起回滚，工程不留痕。
            if self.applyExportConstraints:
                print(
                    "[HoTools FBX] 应用约束（开关开启）：约束参与应用姿态的求值，"
                    "并保留到内置导出，约束结果会被当作实际变换写进 FBX"
                )
            else:
                cleared_objects, cleared_constraints = FBXExporter.clear_exported_constraints(selection)
                if cleared_constraints:
                    print(
                        f"[HoTools FBX] 删除导出范围内的约束（开关关闭）："
                        f"{cleared_objects} 个物体、{cleared_constraints} 条约束"
                        f"（约束内容见同名 JSON）"
                    )
                    # 删完必须立刻刷新求值：无父级物体的 matrix_local 取的是求值后的世界矩阵
                    # （含约束结果），不刷新的话后面读矩阵的步骤（矫正物体变换）会把约束生效时
                    # 的旧矩阵烘进 matrix_basis，删除就白做了。
                    bpy.context.view_layer.update()

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
        if (
            failed_data_transfer_count
            or failed_material_sort_count
            or failed_triangulate_count
            or failed_armature_pose_count
        ):
            warning_parts = []
            if failed_data_transfer_count:
                warning_parts.append(
                    f"{failed_data_transfer_count} 个数据传递修改器隐式修复失败"
                )
            if failed_material_sort_count:
                warning_parts.append("导出网格按材质整理面顺序失败")
            if failed_triangulate_count:
                warning_parts.append("导出网格三角化失败")
            if failed_armature_pose_count:
                warning_parts.append(
                    f"{failed_armature_pose_count} 个骨架应用姿态失败"
                )
            self.report(
                {"WARNING"},
                f"导出成功，但 {'，'.join(warning_parts)}，详见控制台",
            )
        elif removed_hidden_modifiers:
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

        # 预设行：菜单 + 保存按钮 + 删除按钮
        preset_row = layout.row(align=True)
        preset_row.menu(
            HO_MT_FBXExportPresets.__name__,
            text=bpy.types.HO_MT_FBXExportPresets.bl_label or "导出预设",
        )
        preset_row.operator(
            OP_AddFBXExportPreset.bl_idname,
            text="",
            icon='ADD',
        )
        op_remove = preset_row.operator(
            OP_AddFBXExportPreset.bl_idname,
            text="",
            icon='REMOVE',
        )
        op_remove.remove_active = True

        # 预处理（FBX 参数已写死，只暴露预处理开关；叶骨也是预处理的一步）
        option_box = layout.box()
        option_box.label(text="预处理", icon='MODIFIER')
        option_col = option_box.column(align=True, heading="")
        option_col.prop(self, "triangulateMeshes")
        if self.triangulateMeshes:
            info = option_col.row()
            info.enabled = False
            info.label(
                text="blender预览时遇到三角化不一致时，可添加同样设置的 Triangulate 修改器对齐",
                icon='INFO',
            )
        option_col.prop(self, "cleanWeights")
        option_col.prop(self, "meshifyCurves")
        option_col.prop(self, "applyArmaturePose")
        option_col.prop(self, "addLeafBones")
        option_col.prop(self, "generateMCHBones")
        option_col.prop(self, "cleanEmptyMaterialSlots")
        option_col.prop(self, "fixObjectTransform")
        option_col.prop(self, "removeHiddenModifiers")
        option_col.prop(self, "ignoreGeometryNodes")
        option_col.prop(self, "applyExportConstraints")
        option_col.prop(self, "ignoreOutlineModifiers")

        # MCH 骨列表折叠预览（勾了生成 MCH 才有意义）
        if self.generateMCHBones:
            FBXExporter.draw_mch_preview(option_box, self, "showMCHPreview")

        # 次级骨（辅助骨）结构预览，仅展示不交互
        FBXExporter.draw_aux_preview(option_box, self, "showAuxPreview")

        # 骨骼集合结构预览，仅展示每个集合持有多少骨
        FBXExporter.draw_collection_preview(option_box, self, "showCollectionPreview")

        # 附加 JSON 导出（影响导出文件数量）：勾选后展开对应的文件名后缀输入框
        json_box = layout.box()
        json_box.label(text="附加导出 (JSON)", icon='FILE_TEXT')
        json_col = json_box.column(align=True)
        json_col.prop(self, "exportUnityMetadata")
        if self.exportUnityMetadata:
            info = json_col.row()
            info.enabled = False
            info.label(text="将自动生成Rig约束IR、集合和Humanoid映射 JSON", icon='INFO')
        else:
            json_col.prop(self, "exportBoneConstraint")
            if self.exportBoneConstraint:
                json_col.prop(self, "boneConstraintSuffix")
            json_col.prop(self, "exportBoneCollection")
            if self.exportBoneCollection:
                json_col.prop(self, "boneCollectionSuffix")
            json_col.prop(self, "exportHumanoidMapping")
            if self.exportHumanoidMapping:
                json_col.prop(self, "humanoidMappingSuffix")

class OP_FinalFBXExport_only_preprocess(Operator):
    bl_idname = "ho.final_fbx_export_only_preprocess"
    bl_label = "Hotools导出FBX(仅预处理)"
    bl_description = ""
    bl_options = {'REGISTER', 'UNDO'}

    addLeafBones:BoolProperty(name="添加叶骨",description="给无子级且有权重的骨末端补一根叶骨(HoTools自实现,长度为主体骨的一半)。权重按导出时的求值网格判定(镜像修改器/几何节点生成的权重也算),无权重骨与辅助骨不加,在MCH步骤之前执行;仅预处理模式不撤销,叶骨会留在工程供检视",default=True) # type: ignore
    generateMCHBones:BoolProperty(name="生成MCH骨",description="对 generateMCH=True 的骨生成 MCH_ 同级旁路骨、清空主骨变换并写入HoTools_MCH_Parent绑定;仅预处理模式不会自动撤销",default=False) # type: ignore
    cleanWeights:BoolProperty(name="清理权重",description="清理形变网格权重(仅骨骼权重组,非骨骼组不动):删除<0.0001的微小权重→每顶点最多保留4个骨权重组→归一化。仅预处理模式不自动撤销,修改会留在工程里,需手动 Ctrl+Z 还原",default=False) # type: ignore
    fixObjectTransform:BoolProperty(name="矫正物体变换",description="执行原有的物体变换/旋转矫正预处理",default=True) # type: ignore
    ignoreGeometryNodes:BoolProperty(name="忽略几何节点",description="导出前临时删除所有几何节点修改器（type==NODES），避免几何节点改变导出网格；预处理结束前生效",default=True) # type: ignore
    ignoreOutlineModifiers:BoolProperty(name="忽略描边修改器",description="导出前临时删除描边修改器（开启了翻转法线的实体化修改器）；预处理结束前生效",default=True) # type: ignore
    showMCHPreview:BoolProperty(name="MCH 骨预览",description="展开/收起：列出场景中勾了 generateMCH 的骨（按骨架分组）",default=False) # type: ignore
    showAuxPreview:BoolProperty(name="次级骨预览",description="展开/收起：列出场景中各骨架的 HoTools 次级骨（辅助骨，按类型+关联骨分组），仅结构展示不可交互",default=False) # type: ignore
    showCollectionPreview:BoolProperty(name="骨骼集合预览",description="展开/收起：列出场景中各骨架的骨骼集合（Bone Collections）及每个集合直接持有的骨数量，仅结构展示不可交互",default=False) # type: ignore


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

            # 形态键 + 待评估修改器：烘焙穿过修改器，避免导出丢 BlendShape（隐式操作）
            (
                baked_shape_keys,
                skipped_shape_keys,
                failed_shape_keys,
            ) = FBXExporter.bake_shape_keys_through_modifiers(selection)
            if baked_shape_keys:
                print("[HoTools FBX] 形态键烘焙穿过修改器：")
                for line in baked_shape_keys:
                    print(f"  {line}")
            for ob_name, reason in skipped_shape_keys:
                print(f"[HoTools FBX] 形态键烘焙跳过 {ob_name}：{reason}")
            for ob_name, exc in failed_shape_keys:
                print(f"[HoTools FBX] 形态键烘焙失败 {ob_name}：{type(exc).__name__}: {exc}")

            # 清理权重（须在补叶骨之前；仅动骨骼权重组，非骨骼组不碰）
            if self.cleanWeights:
                cleaned = FBXExporter.clean_export_weights(bpy.context.scene.objects)
                print(f"[HoTools FBX] 权重清理：处理了 {cleaned} 个网格")

            # 补叶骨（无子级且有权重的骨），须在 MCH 步骤之前
            if self.addLeafBones and armature_objects != []:
                FBXExporter.add_leaf_bones_to_armatures(armature_objects, selection, active_object)

            # 生成 MCH 骨并清零主骨；仅预处理模式不撤销，MCH 留在工程供检视
            if self.generateMCHBones and armature_objects !=[]:
                FBXExporter.clear_armatures_bone_rotation(
                    armature_objects,
                    selection,
                    active_object,
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

        # 预设行
        preset_row = layout.row(align=True)
        preset_row.menu(
            HO_MT_FBXPreprocessPresets.__name__,
            text=bpy.types.HO_MT_FBXPreprocessPresets.bl_label or "预处理预设",
        )
        preset_row.operator(
            OP_AddFBXPreprocessPreset.bl_idname,
            text="",
            icon='ADD',
        )
        op_remove = preset_row.operator(
            OP_AddFBXPreprocessPreset.bl_idname,
            text="",
            icon='REMOVE',
        )
        op_remove.remove_active = True

        option_box = layout.box()
        option_box.label(text="预处理")
        option_col = option_box.column(align=True)
        option_col.prop(self, "addLeafBones")
        option_col.prop(self, "generateMCHBones")
        option_col.prop(self, "cleanWeights")
        option_col.prop(self, "fixObjectTransform")
        option_col.prop(self, "ignoreGeometryNodes")
        option_col.prop(self, "ignoreOutlineModifiers")

        # MCH 骨列表折叠预览（勾了生成 MCH 才有意义）
        if self.generateMCHBones:
            FBXExporter.draw_mch_preview(option_box, self, "showMCHPreview")

        # 次级骨（辅助骨）结构预览，仅展示不交互
        FBXExporter.draw_aux_preview(option_box, self, "showAuxPreview")

        # 骨骼集合结构预览，仅展示每个集合持有多少骨
        FBXExporter.draw_collection_preview(option_box, self, "showCollectionPreview")


def OPF_FinalFBXExport(self, context):
    self.layout.operator_context = 'INVOKE_DEFAULT'
    self.layout.operator(OP_FinalFBXExport.bl_idname, text="Hotools-FBX(.fbx)")
    self.layout.operator(OP_FinalFBXExport_only_preprocess.bl_idname, text="Hotools-FBX(OnlyPreProcess)")


cls = [
    HO_MT_FBXExportPresets,
    OP_AddFBXExportPreset,
    HO_MT_FBXPreprocessPresets,
    OP_AddFBXPreprocessPreset,
    OP_FinalFBXExport,
    OP_FinalFBXExport_only_preprocess,
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
