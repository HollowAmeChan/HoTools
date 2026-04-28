import bpy
from bpy.types import Node, NodeSocket

from . import OmniNodeDraw
from .OmniNodeOperator import OmniNodeRebuild, NodeSetDefaultSize, NodeSetBiggerSize
import json


def setOutputNode(node: Node, context):
    node.updateColor()


def setBugNode(node: Node, context):
    node.updateColor()
    OmniNodeDraw.sync_bug_text(node)


def setBugText(node: Node, context):
    OmniNodeDraw.sync_bug_text(node)


class OmniNode(Node):
    """Node base class."""

    bug_color: bpy.props.FloatVectorProperty(
        name="Link Bug Color", size=3, subtype="COLOR", default=(1, 0, 0)
    )  # type: ignore
    bug_text: bpy.props.StringProperty(
        name="Bug Detail", default="", update=setBugText
    )  # type: ignore
    is_bug: bpy.props.BoolProperty(
        name="Is Bug", default=False, update=setBugNode
    )  # type: ignore
    debug: bpy.props.BoolProperty(name="Debug", default=False)  # type: ignore

    default_width: bpy.props.FloatProperty(default=250)  # type: ignore
    default_heigh: bpy.props.FloatProperty(default=100)  # type: ignore

    is_output_node: bpy.props.BoolProperty(
        name="Is Output Node", default=False, update=setOutputNode
    )  # type: ignore
    output_color: bpy.props.FloatVectorProperty(
        name="Output Color", size=3, subtype="COLOR", default=(0, 0.6, 0)
    )  # type: ignore
    base_color: bpy.props.FloatVectorProperty(
        name="Base Color", size=3, subtype="COLOR", default=(0.191, 0.061, 0.012)
    )  # type: ignore
    omni_description: bpy.props.StringProperty(
        name="Description", default="No description"
    )  # type: ignore

    _socket_is_multi = None
    _func = None

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
        self.color = self.base_color

    def set_bug_state(self, message, color=None):
        self.bug_text = str(message)
        if color is not None:
            self.bug_color = color
        self.is_bug = True

    def clear_bug_state(self):
        self.is_bug = False
        self.bug_text = ""
        OmniNodeDraw.sync_bug_text(self)

    def build(self):
        """
        Used both in node init and node rebuild.
        Subclasses should define sockets and default parameters here.
        """
        pass

    def init(self, context):
        self.id_data.doing_initNode = True
        self.use_custom_color = True
        self.build()
        self.updateColor()
        self.id_data.doing_initNode = False
        return
    
    def update(self):
        """
        Creat node instance
        Update instance socket(link/unlink)
        Open .blend project
        Rename instance name
        """
        return

    def draw_label(self):
        return f"{self.name}"

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        main_row = layout.row(align=False)

        row_L = main_row.row(align=True)
        row_L.alignment = 'LEFT'
        if self.is_bug:
            row_L.label(icon="ERROR")

        if self.debug:
            pass

    def draw_buttons_ext(self, context, layout: bpy.types.UILayout):
        lines = self.omni_description.splitlines()
        for line in lines:
            layout.label(text=line)

        if self.is_bug and self.bug_text:
            layout.separator()
            for index, line in enumerate(self.bug_text.splitlines()):
                layout.label(text=line, icon='ERROR' if index == 0 else 'BLANK1')
