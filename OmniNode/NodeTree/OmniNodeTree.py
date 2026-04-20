import bpy
from bpy.types import NodeTree, Node, NodeSocket, NodeLink
from bpy.props import CollectionProperty,IntProperty
from .OmniNode import OmniNode
from .OmniCompiler import OmniCompiler
from .OmniExecutor import OmniExecutor
from .OmniNodeOperator import OmniGraphNodeIOItem,OP_IOItemAdd,OP_IOItemRemove,HO_UL_GraphNodeIO
import time
import traceback

TREE_ID = 'OMNINODE'  # 节点树系统注册进去的identifier
TREE_ID_NAME = 'OmniNodeTree'  # 节点树系统的标识符idname


class OmniNodeTree(NodeTree):  # 节点树
    bl_idname = TREE_ID_NAME
    bl_label = "Omni节点图"  # 界面显示名
    bl_icon = 'NODETREE'

    is_auto_update: bpy.props.BoolProperty(
        description="是否实时刷新", default=False)  # type: ignore
    doing_initNode: bpy.props.BoolProperty(
        description="阻止新建节点频繁回调", default=False)  # type: ignore
    # 用于tree的group化
    group_inputs: CollectionProperty(type=OmniGraphNodeIOItem) # type: ignore
    group_inputs_index: IntProperty(default=0) # type: ignore
    group_outputs: CollectionProperty(type=OmniGraphNodeIOItem) # type: ignore
    group_outputs_index: IntProperty(default=0) # type: ignore

    @classmethod
    def poll(self, context):
        return True

    def update(self):
        if self.doing_initNode:  # 树状态-正在新建节点时不回调
            return
        if self.is_auto_update:  # 如果节点树自动更新，则运行整个节点树
            print("树自动运行:", self.name, "\t", time.ctime())
            # TODO:巨量会触发update的东西，需要大量优化，但耦合程度较高
            self.run()
        if not self.use_fake_user: # 不是很优雅，但是够用了，新建nodegroup不会加，但是添加任何node了都会触发
            self.use_fake_user = True

    def interface_update(self, context):
        """被弃用的api，并且由于被弃用，导致完全无法使用interface的io功能了，只能手动写一个io"""
        print(self.name," interface_update")
        pass

    def run(self):
        for node in self.nodes:
            node.is_bug = False
            node.property_unset("bug_text")  # 清空bug 
        compiled = OmniCompiler.compile(self)
        # print(compiled.node_order)# TODO:比较简陋的debug
        OmniExecutor.run(compiled)

def draw_in_NODE_PT_node_tree_properties(self, context: bpy.types.Context):
    layout: bpy.types.UILayout = self.layout
    tree = context.space_data.node_tree

    layout.label(text="OmniTreeInputs:")
    row = layout.row()
    row.template_list(HO_UL_GraphNodeIO.__name__,"",
        tree,"group_inputs",
        tree,"group_inputs_index",
        rows=3
    )
    col = row.column(align=True)
    add = col.operator(OP_IOItemAdd.bl_idname, icon="ADD", text="")
    add.is_input = True
    remove = col.operator(OP_IOItemRemove.bl_idname, icon="REMOVE", text="")
    remove.is_input = True

    layout.label(text="OmniTreeOutputs:")
    row = layout.row()
    row.template_list(HO_UL_GraphNodeIO.__name__,"",
        tree,"group_outputs",
        tree,"group_outputs_index",
        rows=3
    )
    col = row.column(align=True)
    add = col.operator(OP_IOItemAdd.bl_idname, icon="ADD", text="")
    add.is_input = False
    remove = col.operator(OP_IOItemRemove.bl_idname, icon="REMOVE", text="")
    remove.is_input = False


    return


cls = [OmniNodeTree]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    bpy.types.NODE_PT_node_tree_properties.append(draw_in_NODE_PT_node_tree_properties)


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    bpy.types.NODE_PT_node_tree_properties.remove(draw_in_NODE_PT_node_tree_properties)

