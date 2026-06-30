import bpy
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    PointerProperty,
    StringProperty,
)


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
        layout = self.layout
        armature_data = context.object.data
        groups = _collect_aux_groups(armature_data)
        if not groups:
            layout.label(text="未检测到辅助骨", icon="INFO")
            return

        total = sum(len(g["bones"]) for g in groups)
        layout.label(text=f"共 {len(groups)} 组 / {total} 根辅助骨")
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
            count = header.row()
            count.alignment = "RIGHT"
            count.label(text=f"×{len(group['bones'])}")

            if expanded:
                for bone_name in group["bones"]:
                    box.label(text=bone_name, icon="BONE_DATA")


cls = [
    PG_Hotools_BoneRef,
    PG_Hotools_AuxGroupState,
    PG_Hotools_AuxBoneInfo,
    PG_Hotools_BoneProps,
    OT_Hotools_AuxBoneClear,
    OT_Hotools_AuxGroupToggle,
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
