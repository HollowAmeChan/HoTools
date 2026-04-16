import bpy
from bpy.types import Node, NodeSocket
from .OmniNodeOperator import OmniNodeRebuild,NodeSetDefaultSize,NodeSetBiggerSize
import json

def setOutputNode(node, context):
    node.updateColor()


def setBugNode(node, context):
    node.updateColor()


class OmniNode(Node):
    '''节点基类'''
    bug_color: bpy.props.FloatVectorProperty(
        name="link连接bug", size=3, subtype="COLOR", default=(1, 0, 0))  # type: ignore
    bug_text: bpy.props.StringProperty(
        name="Bug详情", default="No bug")  # type: ignore
    is_bug: bpy.props.BoolProperty(
        name="是否bug", default=False, update=setBugNode)  # type: ignore TODO:也许应该使用内置的bug了的UI显示
    debug: bpy.props.BoolProperty(name="调试", default=False)  # type: ignore

    default_width: bpy.props.FloatProperty(default=250)  # type: ignore
    default_heigh: bpy.props.FloatProperty(default=100)  # type: ignore

    is_output_node: bpy.props.BoolProperty(
        name="是否是输出节点", default=False, update=setOutputNode)  # type: ignore
    output_color: bpy.props.FloatVectorProperty(
        name="作为输出节点的高亮颜色", size=3, subtype="COLOR", default=(0, 0.6, 0))  # type: ignore
    base_color: bpy.props.FloatVectorProperty(
        name="默认类型颜色", size=3, subtype="COLOR", default=(0.191, 0.061, 0.012))  # type: ignore
    omni_description: bpy.props.StringProperty(
        name="OMNI节点描述", default="没有使用描述")  # type: ignore
    

# --------------------------------自身基本特性相关------------------------------

    def size2default(self):
        self.width = self.default_width
        self.height = self.default_heigh

    def updateColor(self):
        if self.is_bug:
            self.color = self.bug_color
            return
        if self.is_output_node:
            self.color = self.output_color
            return
        else:
            self.color = self.base_color
# --------------------------------自身功能相关------------------------------

    def processUsingPool(self, func):
        """程序化节点独有调用,手动创建节点要模仿这个写
        使用pool中的数据,处理也返回到pool中
        """
        pool = self["fatherTree"].pool
        kargs = pool[self.name].inputs
        outputs = pool[self.name].outputs

        try:
            result = func(**kargs)
        except Exception as error:
            return error  # 有错误返回错误

        if not isinstance(result, tuple):
            outputs["_OUTPUT0"] = result
            return  # 单返回
        else:
            index = 0
            for i in result:
                outputs["_OUTPUT"+str(index)] = i
                index += 1
            return  # 多返回

    def process(self):
        self.is_bug = False
        self.property_unset("bug_text")  # 首先清空bug 
# --------------------------------原生方法重载------------------------------
    def build(self):
        """
        此方法同时用于节点init与noderebuild操作
        继承时，需要在这里定义socket的构建与node默认参数的指定
        """
        pass

    def init(self, context):
        fatherTree = self["fatherTree"] = bpy.context.space_data.node_tree

        fatherTree.doing_initNode = True  # 更新树状态-正在新建节点,子类定义init后要切回来
        self.use_custom_color = True
        self.build()
        self.updateColor()
        self.size2default()
        fatherTree.doing_initNode = False  # 更新树状态-新建节点完成

    def draw_label(self):
        '''动态标签'''
        return f"{self.name}"

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        '''绘制节点按钮'''
        # bug描述
        if self.is_bug:
            layout.label(text=f"{self.bug_text}")

        main_row = layout.row(align=False)

        row_L = main_row.row(align=True)  # 左侧按钮
        row_L.alignment = 'LEFT'
        if self.is_bug:
            row_L.label(icon="ERROR",)
        
        row_L.prop(self, "debug", text="", toggle=True, icon="FILE_SCRIPT")
        Rebuild = row_L.operator(
            OmniNodeRebuild.bl_idname, text="", icon="NODETREE")
        Rebuild.node_name = self.name
        Rebuild.node_tree_name = self.id_data.name
        SetDefaultSize = row_L.operator(
            NodeSetDefaultSize.bl_idname, text="", icon="REMOVE")
        SetDefaultSize.node_name = self.name
        SetBiggerSize = row_L.operator(
            NodeSetBiggerSize.bl_idname, text="", icon="ADD")
        SetBiggerSize.node_name = self.name


        row_R = main_row.row(align=True)  # 右侧按钮
        row_R.alignment = 'RIGHT'
        row_R.prop(self, "is_output_node", text="", icon="ANIM_DATA")
        
        # debug显示
        # TODO:目前显示的比较丑，列表太长会看不清楚（节点最大宽度不够用，应该要换行，或者有个按钮能看），同时英文变量名会被强制汉化（需要插入0长字符防止汉化）
        if self.debug:
            # 内部prop详情
            pool = self["fatherTree"].pool
            if pool[self.name]:
                inputsInfo: dict = pool[self.name].inputs
                outputInfo: dict = pool[self.name].outputs
                # 输入表
                col = layout.column(align=True)
                grid = col.grid_flow(columns=3, align=True)

                grid.label(text="[标识符]")
                for key in inputsInfo.keys():
                    grid.label(text=str(key))
                grid.label(text="[值]")
                for value in inputsInfo.values():
                    grid.label(text=str(value))
                grid.label(text="[类型]")
                for value in inputsInfo.values():
                    grid.label(text=type(value).__name__)
                # 输出表
                layout.label(text="")
                col = layout.column(align=True)
                grid = col.grid_flow(columns=3, align=True)

                grid.label(text="[标识符]")
                for key in outputInfo.keys():
                    grid.label(text=str(key))
                grid.label(text="[值]")
                for value in outputInfo.values():
                    grid.label(text=str(value))
                grid.label(text="[类型]")
                for value in outputInfo.values():
                    grid.label(text=type(value).__name__)
        pass


    def draw_buttons_ext(self, context, layout: bpy.types.UILayout):
        '''侧边栏中节点属性绘制'''
        row = layout.row(align=True)
        # 是否是自动更新的
        if context.space_data.node_tree.is_auto_update:
            row.alert = True
            row.prop(context.space_data.node_tree,
                    "is_auto_update", text="树自动更新", icon="DECORATE_LINKED")
            row.alert = False
        else:
            row.prop(context.space_data.node_tree,
                    "is_auto_update", text="树自动更新", icon="UNLINKED")
            
        # OMNI节点描述
        lines = self.omni_description.splitlines()
        for line in lines:
            layout.label(text=line)

        pass