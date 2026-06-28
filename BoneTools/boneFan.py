import bpy
from bpy.types import Operator, UILayout, Context
from bpy.props import BoolProperty


def reg_props():
    return


def ureg_props():
    return


def drawBoneFanPanel(layout: UILayout, context: Context):
    fan_box = layout.box()

    row = fan_box.row(align=True)
    row.operator(OP_AddFanInBoneWithWeight.bl_idname, text="fanIn添加")
    row.operator(OP_AddFanOutBoneWithWeight.bl_idname, text="fanOut添加")

    row = fan_box.row(align=True)
    row.operator(OP_RemoveFanBoneWithWeight.bl_idname, text="清除Fan修正")


class BoneFanCore:
    """预留给四肢关节 fan 修正的核心入口。"""
    pass


class OP_AddFanBase(Operator):
    bl_options = {"REGISTER", "UNDO"}

    process_symmetry: BoolProperty(
        name="对称操作",
        description="同时处理镜像骨骼",
        default=False,
    )  # type: ignore
    only_selected: BoolProperty(
        name="仅选中的物体",
        description="只处理当前选中的网格物体",
        default=False,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj and obj.type in {"MESH", "ARMATURE"})

    def execute(self, context):
        self.report({"INFO"}, f"{self.bl_label} 已预留，后续补充具体逻辑")
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "process_symmetry")
        layout.prop(self, "only_selected")


class OP_AddFanInBoneWithWeight(OP_AddFanBase):
    bl_idname = "ho.add_fanin_bone_withweight"
    bl_label = "fanIn添加"
    bl_description = "fanIn添加入口，占位实现"


class OP_AddFanOutBoneWithWeight(OP_AddFanBase):
    bl_idname = "ho.add_fanout_bone_withweight"
    bl_label = "fanOut添加"
    bl_description = "fanOut添加入口，占位实现"


class OP_RemoveFanBoneWithWeight(Operator):
    bl_idname = "ho.removefanbone_withweight"
    bl_label = "清除Fan修正"
    bl_description = "清除fan修正，占位实现"
    bl_options = {"REGISTER", "UNDO"}

    only_selected: BoolProperty(
        name="仅选中的物体",
        description="只处理当前选中的网格物体",
        default=False,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj and obj.type in {"MESH", "ARMATURE"})

    def execute(self, context):
        self.report({"INFO"}, "清除fan修正功能已预留，后续补充具体逻辑")
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "only_selected")


cls = [
    OP_AddFanInBoneWithWeight,
    OP_AddFanOutBoneWithWeight,
    OP_RemoveFanBoneWithWeight,
]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
