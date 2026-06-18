import bpy
from bpy.types import Node, NodeSocket

from . import OmniNodeDraw
from .OmniNodeOperator import OmniNodeRebuild, NodeSetDefaultSize, NodeSetBiggerSize
import json
import uuid


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
    omni_runtime_uid: bpy.props.StringProperty(
        name="Runtime UID", default="", options={'HIDDEN'}
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
        OmniNodeDraw.sync_bug_text(self)

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
        for is_output, sockets in ((False, self.inputs), (True, self.outputs)):
            for index, item in enumerate(sockets):
                if item == sock:
                    side_order = 1 if is_output else 0
                    return index, side_order, str(getattr(item, "identifier", item.name))
        return 999999, 999999, str(getattr(sock, "identifier", sock.name))

    def omni_curve_preview_sockets(self, socket_types=None):
        socket_types = set(socket_types or self._curve_preview_socket_types)
        sockets = []
        for item in list(self.inputs) + list(self.outputs):
            if getattr(item, "hide", False):
                continue
            if not getattr(item, "preview_curve", False):
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
        if sock is None:
            return

        if getattr(sock, "bl_idname", "") in self._curve_preview_socket_types:
            OmniNodeDraw.DrawCurveSocket.sync(sock)

    def omni_sync_all_draw(self):
        for sock in list(self.inputs) + list(self.outputs):
            self.omni_sync_socket_draw(sock)

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
