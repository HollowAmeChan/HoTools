import bpy
from bpy.types import Node, NodeSocket

from . import OmniNodeDraw
from .OmniNodeOperator import (
    OmniNodeApplyPreset,
    OmniNodeRebuild,
    OmniNodeToggleDescription,
    NodeSetDefaultSize,
    NodeSetBiggerSize,
    node_omni_preset_items,
)
import json
import uuid


def setOutputNode(node: Node, context):
    node.updateColor()


def setBugNode(node: Node, context):
    node.updateColor()
    OmniNodeDraw.DrawBug.sync(node)
    node.omni_sync_all_draw()


def setBugText(node: Node, context):
    OmniNodeDraw.DrawBug.sync(node)
    node.omni_sync_all_draw()


def setNodeSidePreview(node: Node, context):
    node.omni_sync_all_draw()


def omniPresetItems(node, context):
    return node_omni_preset_items(node)


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
    omni_runtime_uid: bpy.props.StringProperty(
        name="Runtime UID", default="", options={'HIDDEN'}
    )  # type: ignore
    omni_view_preview: bpy.props.BoolProperty(
        name="侧栏预览", default=False, update=setNodeSidePreview
    )  # type: ignore
    omni_preset_id: bpy.props.EnumProperty(
        name="预设", items=omniPresetItems
    )  # type: ignore

    _socket_is_multi = None
    _func = None
    _curve_preview_socket_types = {"OmniNodeSocketFloatCurve", "OmniNodeSocketColorCurve"}

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
        OmniNodeDraw.DrawBug.sync(self)
        self.omni_sync_all_draw()

    def build(self):
        """
        Used both in node init and node rebuild.
        Subclasses should define sockets and default parameters here.
        """
        pass

    def init(self, context):
        self.id_data.doing_initNode = True
        if not self.omni_runtime_uid:
            self.omni_runtime_uid = uuid.uuid4().hex
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

    def omni_socket_display_order(self, sock):
        for index, item in enumerate(self.inputs):
            if item == sock:
                return index, str(getattr(item, "identifier", item.name))
        return 999999, str(getattr(sock, "identifier", sock.name))

    def omni_curve_preview_sockets(self, socket_types=None):
        socket_types = set(socket_types or self._curve_preview_socket_types)
        sockets = []
        for item in self.inputs:
            if getattr(item, "hide", False):
                continue
            if getattr(item, "bl_idname", "") not in socket_types:
                continue
            sockets.append(item)
        sockets.sort(key=self.omni_socket_display_order)
        return sockets

    def omni_curve_preview_index(self, sock, socket_types=None):
        try:
            return self.omni_curve_preview_sockets(socket_types).index(sock)
        except ValueError:
            return 0

    def omni_sync_socket_draw(self, sock):
        OmniNodeDraw.DrawSidePanel.sync_node(self)

    def omni_sync_all_draw(self):
        OmniNodeDraw.DrawSidePanel.sync_node(self)

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        main_row = layout.row(align=False)

        row_L = main_row.row(align=True)
        row_L.alignment = 'LEFT'
        if self.is_bug:
            row_L.label(icon="ERROR")

        if self.debug:
            pass

        row_L.prop(
            self,
            "omni_view_preview",
            text="",
            icon="HIDE_OFF" if self.omni_view_preview else "HIDE_ON",
            toggle=True,
        )

        if OmniNodeDraw.DrawDescription.text(self):
            op = row_L.operator(OmniNodeToggleDescription.bl_idname, text="", icon="INFO")
            op.node_tree_name = getattr(self.id_data, "name_full", self.id_data.name)
            op.node_name = self.name
            op.show_description = not OmniNodeDraw.DrawDescription.is_visible(self)

        row_R = main_row.row(align=True)
        row_R.alignment = 'RIGHT'
        preset_items = node_omni_preset_items(self)
        if len(preset_items) > 1:
            row_R.prop(self, "omni_preset_id", text="")
            op = row_R.operator(OmniNodeApplyPreset.bl_idname, text="", icon="CHECKMARK")
            op.node_tree_name = getattr(self.id_data, "name_full", self.id_data.name)
            op.node_name = self.name
            op.preset_id = self.omni_preset_id

    def draw_buttons_ext(self, context, layout: bpy.types.UILayout):
        lines = self.omni_description.splitlines()
        for line in lines:
            layout.label(text=line)

        if self.is_bug and self.bug_text:
            layout.separator()
            for index, line in enumerate(self.bug_text.splitlines()):
                layout.label(text=line, icon='ERROR' if index == 0 else 'BLANK1')
