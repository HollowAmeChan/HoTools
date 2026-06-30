import bpy
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    PointerProperty,
    StringProperty,
)

from .boneUtils import BoneUtils


# 辅助骨类型枚举：与命名体系中的 marker 一一对应。
# NONE 表示这不是 HoTools 生成的辅助骨。
AUX_BONE_TYPE_ITEMS = (
    ("NONE", "无", "非 HoTools 辅助骨"),
    ("FAN", "Fan", "两骨关节之间的 fan 辅助骨"),
    ("FAN_SINGLE", "FanSingle", "单骨 fan 辅助骨"),
    ("FAN_SIDE", "FanSide", "侧向 fan 辅助骨"),
    ("TWIST", "Twist", "扭转辅助骨"),
)


class PG_Hotools_BoneRef(PropertyGroup):
    """一个骨骼引用，仅保存骨名。用于辅助骨的关联骨集合。"""

    name: StringProperty(
        name="骨名",
        description="关联骨的名称",
        default="",
    )  # type: ignore


class PG_Hotools_AuxGroupState(PropertyGroup):
    """辅助骨总览面板里单个分组的展开状态。

    key 由 (类型, 关联骨组合) 拼成，用于在重绘之间记住该组是否折叠。
    """

    name: StringProperty(default="")  # type: ignore  # 复用 name 作为分组 key
    expanded: BoolProperty(default=True)  # type: ignore


class PG_Hotools_AuxBoneInfo(PropertyGroup):
    """辅助骨自描述属性。

    挂在每根辅助骨上，记录“它是什么辅助骨、和哪些骨关联”。
    关联骨用一个不定长集合 sourceBones 表示，不假设辅助骨一定对应关节：
    - Twist：单骨，集合里放 1 根；
    - Fan / FanSide：两骨之间，集合里放 2 根；
    - 将来三骨定义的辅助骨：放 3 根，依此类推。
    同一根骨上挂的多组辅助骨（例如大腿上既有大腿-胯之间的 fan，又有大腿-小腿
    之间的 fan）可凭各自的 sourceBones 组合精确区分。
    权重来源不在此记录：HoTools 强制辅助骨权重取自其直接父级。
    """

    isAuxBone: BoolProperty(
        name="是辅助骨",
        description="标记此骨为 HoTools 生成的辅助骨",
        default=False,
    )  # type: ignore
    auxType: EnumProperty(
        name="辅助骨类型",
        description="此辅助骨的种类",
        items=AUX_BONE_TYPE_ITEMS,
        default="NONE",
    )  # type: ignore
    sourceBones: CollectionProperty(
        name="关联骨",
        description="定义此辅助骨所依附的骨；数量不定（单骨1根、两骨2根、三骨3根……）",
        type=PG_Hotools_BoneRef,
    )  # type: ignore


class PG_Hotools_BoneProps(PropertyGroup):
    keepRotation: BoolProperty(
        name="保留旋转",
        description="在使用hotools fbx导出时,如果这段骨骼不保留旋转,将会自动将骨骼竖直，注意会导致这段骨骼后续的叶骨添加错误",
        default=True,
    )  # type: ignore
    endBone: BoolProperty(
        name="叶骨",
        description="Hotools是否将骨骼标记为叶骨",
        default=False,
    )  # type: ignore
    humanoidMapping: StringProperty(
        name="Humanoid映射",
        description="定义此骨对应Unity-Humannoid标准骨",
        default="",
    )  # type: ignore
    deformMappingTag: StringProperty(
        name="DeformMappingTag",
        description="目标形变骨名称，用于HoTools批量约束映射",
        default="",
    )  # type: ignore
    auxBone: PointerProperty(
        name="辅助骨信息",
        description="此骨作为 HoTools 辅助骨时的自描述信息",
        type=PG_Hotools_AuxBoneInfo,
    )  # type: ignore


def _active_aux(context):
    """取当前活动骨的辅助骨信息，取不到返回 None。"""
    bone = getattr(context, "active_bone", None)
    if bone is None:
        return None
    return bone.hotools_boneprops.auxBone


class OT_Hotools_AuxBoneClear(Operator):
    bl_idname = "hotools.aux_bone_clear"
    bl_label = "清除辅助骨信息"
    bl_description = "清空此骨的 HoTools 辅助骨标记、类型与关联骨"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_aux(context) is not None

    def execute(self, context):
        aux = _active_aux(context)
        if aux is None:
            return {"CANCELLED"}
        aux.sourceBones.clear()
        aux.auxType = "NONE"
        aux.isAuxBone = False
        return {"FINISHED"}


class PT_Hotools_PosebonePanel(Panel):
    bl_idname = "BONE_PT_Hotools_PoseBonePanel"
    bl_label = "HoTools骨骼"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "bone"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.mode == "POSE" and context.active_bone is not None

    def draw(self, context):
        bone = context.active_bone
        layout = self.layout
        props = bone.hotools_boneprops
        layout.prop(props, "keepRotation", toggle=False)
        layout.prop(props, "endBone", toggle=False)
        layout.prop(props, "humanoidMapping", toggle=False)
        layout.prop(props, "deformMappingTag", toggle=False)

        aux = props.auxBone
        if aux.isAuxBone:
            box = layout.box()
            # 辅助骨信息由 HoTools 创建流程写入，用户只读。
            box.label(text="辅助骨类型：" + aux.auxType)
            box.label(text="关联骨：")
            for ref in aux.sourceBones:
                box.label(text=ref.name, icon="BONE_DATA")
            box.operator("hotools.aux_bone_clear", icon="TRASH", text="清除辅助骨信息")


_AUX_TYPE_LABELS = dict((item[0], item[1]) for item in AUX_BONE_TYPE_ITEMS)


def _aux_group_key(aux_type, sources):
    """把 (类型, 关联骨组合) 拼成稳定的字符串 key，用于记忆折叠状态。"""
    return aux_type + "||" + "/".join(sources)


def _collect_aux_groups(armature_data):
    """遍历骨架，按 (类型, 关联骨组合) 聚合辅助骨。

    返回有序列表，每项为 dict：{auxType, sources(元组), bones(骨名列表), key}。
    关联骨组合保持创建时的顺序（父→子），不排序，以保留语义。
    """
    groups = {}
    order = []
    for bone in armature_data.bones:
        props = getattr(bone, "hotools_boneprops", None)
        aux = getattr(props, "auxBone", None) if props else None
        if not aux or not aux.isAuxBone:
            continue
        sources = tuple(ref.name for ref in aux.sourceBones)
        key = (aux.auxType, sources)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(bone.name)
    return [
        {
            "auxType": key[0],
            "sources": key[1],
            "bones": groups[key],
            "key": _aux_group_key(key[0], key[1]),
        }
        for key in order
    ]


def _aux_group_expanded(armature_data, key):
    """读某组的展开状态；没有记录默认折叠。"""
    state = armature_data.hotools_aux_group_states.get(key)
    return False if state is None else state.expanded


class OT_Hotools_AuxGroupToggle(Operator):
    bl_idname = "hotools.aux_group_toggle"
    bl_label = "展开/折叠辅助骨分组"
    bl_description = "展开或折叠该辅助骨分组"
    bl_options = {"REGISTER"}

    key: StringProperty(default="")  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        states = context.object.data.hotools_aux_group_states
        state = states.get(self.key)
        if state is None:
            # 没有记录说明当前是默认折叠，第一次点击即展开。
            state = states.add()
            state.name = self.key
            state.expanded = True
        else:
            state.expanded = not state.expanded
        return {"FINISHED"}


class AuxRemovalBlockedError(Exception):
    """当辅助骨无法安全删除时抛出（下面挂了外部子骨，或权重回收目标丢失）。"""


class AuxBoneRemover:
    """安全删除辅助骨的统一核心。

    一切以辅助骨自描述（auxBone）聚合为准，不再从当前选择反推：
    - 收集待删的辅助骨集合；
    - 阻断检查：待删骨下若挂着不在删除集合里的外部子骨，拒绝删除；
    - 权重回收：每根变形辅助骨（use_deform=True）把权重并回它的直接父级
      （父级指针由 Blender 维护，改名不失效），父级即生成时按通道分权的来源；
    - 目标丢失：父级缺失或父级本身也在删除集合里，无法确定回收目标时，
      列出这些骨并报错退出（本轮不做逐一手动指定）；
    - 非变形辅助骨（pin，use_deform=False）无顶点组，直接删除即可。
    """

    SAMPLE_COUNT = 8

    @staticmethod
    def collect_all_aux_names(armature: bpy.types.Object) -> list[str]:
        """遍历骨架，收集所有被标记为辅助骨的骨名。"""
        names = []
        for bone in armature.data.bones:
            props = getattr(bone, "hotools_boneprops", None)
            aux = getattr(props, "auxBone", None) if props else None
            if aux and aux.isAuxBone:
                names.append(bone.name)
        return names

    @staticmethod
    def _is_aux_bone(armature: bpy.types.Object, bone_name: str) -> bool:
        bone = armature.data.bones.get(bone_name)
        props = getattr(bone, "hotools_boneprops", None) if bone else None
        aux = getattr(props, "auxBone", None) if props else None
        return bool(aux and aux.isAuxBone)

    @classmethod
    def _find_child_blockers(
        cls,
        armature: bpy.types.Object,
        removal_names: list[str],
    ) -> list[tuple[str, str]]:
        # 待删骨下若挂着不在删除集合里的外部子骨，删除会孤立或意外改父，必须阻断。
        target = set(removal_names)
        bones = armature.data.edit_bones if armature.mode == "EDIT" else armature.data.bones
        blockers = []
        for name in removal_names:
            bone = bones.get(name)
            if bone is None:
                continue
            for child in bone.children:
                if child.name not in target:
                    blockers.append((name, child.name))
        return blockers

    @classmethod
    def _resolve_targets(
        cls,
        armature: bpy.types.Object,
        removal_names: list[str],
    ) -> tuple[dict[str, list[str]], list[str]]:
        # 在物体/姿态模式下用 data.bones 的父级指针确定每根变形辅助骨的回收目标。
        # 父级缺失，或父级本身也要被删除时，目标无法确定，记为孤儿。
        removal_set = set(removal_names)
        target_to_aux: dict[str, list[str]] = {}
        orphans: list[str] = []
        for name in removal_names:
            bone = armature.data.bones.get(name)
            if bone is None or not bone.use_deform:
                continue
            parent = bone.parent
            if parent is None or parent.name in removal_set:
                orphans.append(name)
                continue
            target_to_aux.setdefault(parent.name, []).append(name)
        return target_to_aux, orphans

    @classmethod
    def _assert_safe(cls, armature: bpy.types.Object, removal_names: list[str], orphans: list[str]) -> None:
        blockers = cls._find_child_blockers(armature, removal_names)
        if blockers:
            blocker_text = ", ".join(
                f"{aux} -> {child}" for aux, child in blockers[: cls.SAMPLE_COUNT]
            )
            if len(blockers) > cls.SAMPLE_COUNT:
                blocker_text += f"，等 {len(blockers)} 处"
            raise AuxRemovalBlockedError(
                "不能删除辅助骨：待删辅助骨下还挂着其他骨骼，"
                "请先解除这些骨骼的父子关系后再删除。"
                f"阻断项: {blocker_text}"
            )
        if orphans:
            orphan_text = ", ".join(orphans[: cls.SAMPLE_COUNT])
            if len(orphans) > cls.SAMPLE_COUNT:
                orphan_text += f"，等 {len(orphans)} 根"
            raise AuxRemovalBlockedError(
                "不能删除辅助骨：以下辅助骨找不到权重回收目标（父级已丢失或父级也在删除列表里），"
                "请先手动把它们重新挂回主骨，或单独处理这些骨。"
                f"问题骨: {orphan_text}"
            )

    @staticmethod
    def _restore_weights(obj: bpy.types.Object, target_to_aux: dict[str, list[str]]) -> int:
        # 把每根辅助骨的顶点组权重加合回它的目标（父）顶点组，再删掉辅助骨顶点组。
        # 这正是生成时按通道转移权重的逆操作。
        old_mode = obj.mode
        old_active = bpy.context.view_layer.objects.active
        mirror_state = BoneUtils.set_temp_mesh_mirror_off(obj)
        mode_changed = False
        removed_groups = 0

        try:
            if old_mode != "OBJECT":
                bpy.context.view_layer.objects.active = obj
                BoneUtils.set_object_mode(obj, "OBJECT")
                mode_changed = True

            for target_name, aux_names in target_to_aux.items():
                aux_vgs = [
                    vg for vg in (obj.vertex_groups.get(aux_name) for aux_name in aux_names)
                    if vg is not None
                ]
                target_vg = obj.vertex_groups.get(target_name)

                if target_vg is None and not aux_vgs:
                    continue

                if target_vg is None:
                    target_vg = obj.vertex_groups.new(name=target_name)

                for vertex in obj.data.vertices:
                    total_weight = 0.0
                    has_explicit_weight = False

                    try:
                        total_weight += target_vg.weight(vertex.index)
                        has_explicit_weight = True
                    except RuntimeError:
                        pass

                    for aux_vg in aux_vgs:
                        try:
                            total_weight += aux_vg.weight(vertex.index)
                            has_explicit_weight = True
                        except RuntimeError:
                            continue

                    if has_explicit_weight:
                        target_vg.add([vertex.index], total_weight, "REPLACE")

                for aux_name in aux_names:
                    aux_vg = obj.vertex_groups.get(aux_name)
                    if aux_vg:
                        obj.vertex_groups.remove(aux_vg)
                        removed_groups += 1
        finally:
            BoneUtils.restore_mesh_mirror_state(mirror_state)

            if mode_changed:
                bpy.context.view_layer.objects.active = obj
                BoneUtils.set_object_mode(obj, old_mode)

            if old_active:
                try:
                    bpy.context.view_layer.objects.active = old_active
                except Exception:
                    pass

        return removed_groups

    @classmethod
    def remove(
        cls,
        context,
        armature: bpy.types.Object,
        removal_names: list[str],
        process_vertex_groups: bool,
        only_selected: bool,
    ) -> dict:
        removal_names = list(dict.fromkeys(
            name for name in removal_names if cls._is_aux_bone(armature, name)
        ))
        if not removal_names:
            raise AuxRemovalBlockedError("没有找到可删除的辅助骨")

        original_mode = armature.mode
        old_active = bpy.context.view_layer.objects.active
        was_hidden = armature.hide_viewport
        mirror_state = BoneUtils.set_temp_armature_mirror_off(armature)

        # 阻断检查与目标解析都在数据层进行，避免无谓地切换模式。
        target_to_aux, orphans = cls._resolve_targets(armature, removal_names)
        cls._assert_safe(armature, removal_names, orphans)

        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        restored_objects = 0
        removed_groups = 0
        removed = 0

        try:
            if process_vertex_groups and target_to_aux:
                mesh_objs = BoneUtils.collect_mesh_objects_for_armature(armature)
                if only_selected:
                    mesh_objs = [obj for obj in mesh_objs if obj.select_get()]
                for obj in mesh_objs:
                    groups = cls._restore_weights(obj, target_to_aux)
                    if groups > 0:
                        restored_objects += 1
                    removed_groups += groups

            bpy.context.view_layer.objects.active = armature
            BoneUtils.set_object_mode(armature, "EDIT")
            edit_bones = armature.data.edit_bones
            for name in removal_names:
                bone = edit_bones.get(name)
                if bone is not None:
                    edit_bones.remove(bone)
                    removed += 1
            BoneUtils.set_object_mode(armature, "OBJECT")
        finally:
            BoneUtils.restore_armature_mirror_state(mirror_state)
            try:
                if armature.mode != original_mode:
                    bpy.context.view_layer.objects.active = armature
                    BoneUtils.set_object_mode(armature, original_mode)
            except Exception:
                pass
            if old_active is not None:
                try:
                    bpy.context.view_layer.objects.active = old_active
                except Exception:
                    pass
            if was_hidden:
                armature.hide_set(True)

        return {
            "removed_bones": removed,
            "restored_objects": restored_objects,
            "removed_groups": removed_groups,
        }


class OT_Hotools_AuxGroupRemove(Operator):
    bl_idname = "hotools.aux_group_remove"
    bl_label = "删除该组辅助骨"
    bl_description = "安全删除该分组下的全部辅助骨，并把权重恢复回主骨"
    bl_options = {"REGISTER", "UNDO"}

    key: StringProperty(default="")  # type: ignore
    process_vertex_groups: BoolProperty(
        name="处理顶点组",
        description="删除辅助骨时把权重并回主骨并清理对应顶点组",
        default=True,
    )  # type: ignore
    only_selected: BoolProperty(
        name="仅选中的物体",
        description="只处理当前被选中的网格物体",
        default=False,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "process_vertex_groups")
        sub = layout.column()
        sub.enabled = self.process_vertex_groups
        sub.prop(self, "only_selected")

    def execute(self, context):
        groups = _collect_aux_groups(context.object.data)
        removal_names = []
        for group in groups:
            if group["key"] == self.key:
                removal_names = list(group["bones"])
                break
        if not removal_names:
            self.report({"WARNING"}, "没有找到该分组的辅助骨")
            return {"CANCELLED"}

        try:
            result = AuxBoneRemover.remove(
                context, context.object, removal_names,
                self.process_vertex_groups, self.only_selected,
            )
        except AuxRemovalBlockedError as e:
            self.report({"WARNING"}, str(e))
            return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"已删除 {result['removed_bones']} 根辅助骨，"
            f"在 {result['restored_objects']} 个物体上恢复了权重"
            f"（{result['removed_groups']} 个顶点组）",
        )
        return {"FINISHED"}


class OT_Hotools_AuxRemoveAll(Operator):
    bl_idname = "hotools.aux_remove_all"
    bl_label = "删除全部辅助骨"
    bl_description = "安全删除骨架上所有 HoTools 辅助骨，并把权重恢复回主骨"
    bl_options = {"REGISTER", "UNDO"}

    process_vertex_groups: BoolProperty(
        name="处理顶点组",
        description="删除辅助骨时把权重并回主骨并清理对应顶点组",
        default=True,
    )  # type: ignore
    only_selected: BoolProperty(
        name="仅选中的物体",
        description="只处理当前被选中的网格物体",
        default=False,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "process_vertex_groups")
        sub = layout.column()
        sub.enabled = self.process_vertex_groups
        sub.prop(self, "only_selected")

    def execute(self, context):
        removal_names = AuxBoneRemover.collect_all_aux_names(context.object)
        if not removal_names:
            self.report({"WARNING"}, "未检测到辅助骨")
            return {"CANCELLED"}

        try:
            result = AuxBoneRemover.remove(
                context, context.object, removal_names,
                self.process_vertex_groups, self.only_selected,
            )
        except AuxRemovalBlockedError as e:
            self.report({"WARNING"}, str(e))
            return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"已删除 {result['removed_bones']} 根辅助骨，"
            f"在 {result['restored_objects']} 个物体上恢复了权重"
            f"（{result['removed_groups']} 个顶点组）",
        )
        return {"FINISHED"}


def draw_aux_overview(layout, context):
    """绘制活动骨架的辅助骨总览（分组、折叠、删除）。

    抽成模块级函数后，骨架数据属性页与 3D 视图的骨骼操作面板可共用同一套 UI。
    """
    obj = context.object
    if obj is None or obj.type != "ARMATURE":
        layout.label(text="请选择骨架", icon="INFO")
        return

    armature_data = obj.data
    groups = _collect_aux_groups(armature_data)
    if not groups:
        layout.label(text="未检测到辅助骨", icon="INFO")
        return

    total = sum(len(g["bones"]) for g in groups)
    header_row = layout.row(align=True)
    header_row.label(text=f"共 {len(groups)} 组 / {total} 根辅助骨")
    remove_all = header_row.row()
    remove_all.alignment = "RIGHT"
    remove_all.operator("hotools.aux_remove_all", icon="TRASH", text="全部删除")
    for group in groups:
        box = layout.box()
        type_label = _AUX_TYPE_LABELS.get(group["auxType"], group["auxType"])
        sources_text = " + ".join(group["sources"]) if group["sources"] else "（无关联骨）"
        expanded = _aux_group_expanded(armature_data, group["key"])

        # 表头铺满整行：左侧折叠箭头 + 标题，右侧数量。
        header = box.row(align=True)
        header.alignment = "EXPAND"
        toggle = header.operator(
            "hotools.aux_group_toggle",
            text=f"{type_label}：{sources_text}",
            icon="TRIA_DOWN" if expanded else "TRIA_RIGHT",
            emboss=False,
        )
        toggle.key = group["key"]
        count = header.row(align=True)
        count.alignment = "RIGHT"
        count.label(text=f"×{len(group['bones'])}")
        remove = count.operator("hotools.aux_group_remove", icon="TRASH", text="")
        remove.key = group["key"]

        if expanded:
            for bone_name in group["bones"]:
                box.label(text=bone_name, icon="BONE_DATA")


class PT_Hotools_ArmatureAuxPanel(Panel):
    bl_idname = "DATA_PT_Hotools_ArmatureAuxPanel"
    bl_label = "HoTools辅助骨总览"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def draw(self, context):
        draw_aux_overview(self.layout, context)


cls = [
    PG_Hotools_BoneRef,
    PG_Hotools_AuxGroupState,
    PG_Hotools_AuxBoneInfo,
    PG_Hotools_BoneProps,
    OT_Hotools_AuxBoneClear,
    OT_Hotools_AuxGroupToggle,
    OT_Hotools_AuxGroupRemove,
    OT_Hotools_AuxRemoveAll,
    PT_Hotools_PosebonePanel,
    PT_Hotools_ArmatureAuxPanel,
]


def reg_props():
    if hasattr(bpy.types.Bone, "hotools_boneprops"):
        del bpy.types.Bone.hotools_boneprops
    bpy.types.Bone.hotools_boneprops = PointerProperty(type=PG_Hotools_BoneProps)
    # 辅助骨总览面板的分组折叠状态，存在骨架数据上。
    if hasattr(bpy.types.Armature, "hotools_aux_group_states"):
        del bpy.types.Armature.hotools_aux_group_states
    bpy.types.Armature.hotools_aux_group_states = CollectionProperty(type=PG_Hotools_AuxGroupState)


def ureg_props():
    if hasattr(bpy.types.Bone, "hotools_boneprops"):
        del bpy.types.Bone.hotools_boneprops
    if hasattr(bpy.types.Armature, "hotools_aux_group_states"):
        del bpy.types.Armature.hotools_aux_group_states


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    ureg_props()
    for i in reversed(cls):
        bpy.utils.unregister_class(i)
