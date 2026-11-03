"""HoFace: thin Blender endpoint for HoFaceStudio final-weight preview.

This module receives final shape-key weights only. It does not parse or
evaluate .hoface.value.json / .hoface.ir.json and therefore cannot drift from
the desktop/runtime evaluator.
"""

from __future__ import annotations

import json
import socket
from typing import Optional

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList


_SOCKET = None
_TIMER_REGISTERED = False
_LAST_STATUS = "未启动"
_LAST_SEQUENCE = -1
_PACKETS = 0
_INVALID = 0


def _targets(scene):
    return scene.ho_face_targets


def _clear_object_keys(obj):
    shape_keys = getattr(getattr(obj, "data", None), "shape_keys", None)
    if shape_keys is None:
        return 0
    count = 0
    for key in shape_keys.key_blocks:
        key.value = 0.0
        count += 1
    return count


def _apply_packet(scene, packet):
    global _LAST_SEQUENCE, _PACKETS
    if packet.get("type") != "hoface.preview" or packet.get("version") != 2:
        return False
    weights = packet.get("weights") or {}
    tracked = bool(packet.get("tracked", False))
    for item in _targets(scene):
        obj = item.object
        if not item.enabled or obj is None or obj.type != "MESH":
            continue
        shape_keys = getattr(getattr(obj, "data", None), "shape_keys", None)
        if shape_keys is None:
            continue
        for target_id, weight in weights.items():
            key = shape_keys.key_blocks.get(target_id)
            if key is None:
                continue
            value = float(weight) if tracked else 0.0
            key.value = max(key.slider_min, min(key.slider_max, value))
    _LAST_SEQUENCE = int(packet.get("sequence", _LAST_SEQUENCE))
    _PACKETS += 1
    return True


def _poll_timer():
    global _SOCKET, _LAST_STATUS, _INVALID
    if _SOCKET is None:
        return None
    scene = bpy.context.scene
    try:
        while True:
            payload, _address = _SOCKET.recvfrom(1024 * 1024)
            try:
                packet = json.loads(payload.decode("utf-8"))
                if _apply_packet(scene, packet):
                    _LAST_STATUS = "运行中 · 序号 {}".format(_LAST_SEQUENCE)
                else:
                    _INVALID += 1
                    _LAST_STATUS = "收到不支持的预览帧"
            except Exception as error:
                _INVALID += 1
                _LAST_STATUS = "帧错误：" + str(error)
    except BlockingIOError:
        pass
    except OSError:
        _SOCKET = None
        _LAST_STATUS = "监听已断开"
        return None
    return 0.03


def _start(port):
    global _SOCKET, _TIMER_REGISTERED, _LAST_STATUS, _LAST_SEQUENCE, _PACKETS, _INVALID
    _stop()
    _SOCKET = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _SOCKET.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _SOCKET.bind(("127.0.0.1", int(port)))
    _SOCKET.setblocking(False)
    _LAST_STATUS = "监听 127.0.0.1:{}".format(port)
    _LAST_SEQUENCE = -1
    _PACKETS = 0
    _INVALID = 0
    if not bpy.app.timers.is_registered(_poll_timer):
        bpy.app.timers.register(_poll_timer, first_interval=0.03, persistent=True)
        _TIMER_REGISTERED = True


def _stop():
    global _SOCKET, _TIMER_REGISTERED, _LAST_STATUS
    if _SOCKET is not None:
        try:
            _SOCKET.close()
        except OSError:
            pass
    _SOCKET = None
    if _TIMER_REGISTERED and bpy.app.timers.is_registered(_poll_timer):
        bpy.app.timers.unregister(_poll_timer)
    _TIMER_REGISTERED = False
    _LAST_STATUS = "未启动"


class PG_HoFaceTarget(PropertyGroup):
    object: PointerProperty(type=bpy.types.Object, name="物体")
    enabled: BoolProperty(name="启用", default=True)


class HO_UL_HoFaceTargets(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.prop(item, "object", text="", emboss=False, icon="MESH_DATA")


class HO_OT_HoFaceStart(Operator):
    bl_idname = "ho.hoface_start"
    bl_label = "开始 HoFace"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            _start(context.scene.ho_face_port)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class HO_OT_HoFaceStop(Operator):
    bl_idname = "ho.hoface_stop"
    bl_label = "停止 HoFace"

    def execute(self, context):
        _stop()
        return {"FINISHED"}


class HO_OT_HoFaceAddSelected(Operator):
    bl_idname = "ho.hoface_add_selected"
    bl_label = "添加选中物体"

    def execute(self, context):
        existing = {item.object for item in _targets(context.scene) if item.object}
        added = 0
        for obj in context.selected_objects:
            if obj.type != "MESH" or obj in existing:
                continue
            item = _targets(context.scene).add()
            item.object = obj
            existing.add(obj)
            added += 1
        if added == 0:
            self.report({"WARNING"}, "没有添加新的网格物体。")
        return {"FINISHED"}


class HO_OT_HoFaceRemoveTarget(Operator):
    bl_idname = "ho.hoface_remove_target"
    bl_label = "移除目标"

    def execute(self, context):
        targets = _targets(context.scene)
        index = context.scene.ho_face_target_index
        if 0 <= index < len(targets):
            targets.remove(index)
            context.scene.ho_face_target_index = min(index, max(0, len(targets) - 1))
        return {"FINISHED"}


class HO_OT_HoFaceClearTargets(Operator):
    bl_idname = "ho.hoface_clear_targets"
    bl_label = "清空目标列表"

    def execute(self, context):
        _targets(context.scene).clear()
        context.scene.ho_face_target_index = 0
        return {"FINISHED"}


class HO_OT_HoFaceClearKeys(Operator):
    bl_idname = "ho.hoface_clear_keys"
    bl_label = "清空选中物体全部形态键"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = sum(_clear_object_keys(obj) for obj in context.selected_objects if obj.type == "MESH")
        self.report({"INFO"}, "已清空 {} 个形态键值。".format(count))
        return {"FINISHED"}


class HO_PT_HoFace(Panel):
    bl_idname = "HO_PT_hoface"
    bl_label = "HoFace"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HoFace"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        status = layout.box()
        status.label(text=_LAST_STATUS, icon="LINKED" if _SOCKET else "UNLINKED")
        row = status.row(align=True)
        row.prop(scene, "ho_face_port", text="端口")
        row.operator(HO_OT_HoFaceStart.bl_idname, text="开始", icon="PLAY")
        row.operator(HO_OT_HoFaceStop.bl_idname, text="停止", icon="PAUSE")
        status.label(text="帧 {} · 错误 {}".format(_PACKETS, _INVALID))

        box = layout.box()
        box.label(text="驱动物体")
        box.template_list("HO_UL_HoFaceTargets", "", scene, "ho_face_targets",
                          scene, "ho_face_target_index", rows=4)
        row = box.row(align=True)
        row.operator(HO_OT_HoFaceAddSelected.bl_idname, text="添加选中", icon="ADD")
        row.operator(HO_OT_HoFaceRemoveTarget.bl_idname, text="", icon="REMOVE")
        row.operator(HO_OT_HoFaceClearTargets.bl_idname, text="", icon="TRASH")

        box = layout.box()
        box.label(text="制作清理")
        box.operator(HO_OT_HoFaceClearKeys.bl_idname, icon="X")
        box.prop(scene, "ho_face_base_check", text="基型检查")
        box.prop(scene, "ho_face_pinning_check", text="钉固检查")
        if not scene.ho_face_base_check and not scene.ho_face_pinning_check:
            box.label(text="预检查已关闭，不阻挡实时预览。", icon="INFO")


CLASSES = (
    PG_HoFaceTarget, HO_UL_HoFaceTargets, HO_OT_HoFaceStart,
    HO_OT_HoFaceStop, HO_OT_HoFaceAddSelected, HO_OT_HoFaceRemoveTarget,
    HO_OT_HoFaceClearTargets, HO_OT_HoFaceClearKeys, HO_PT_HoFace,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ho_face_targets = CollectionProperty(type=PG_HoFaceTarget)
    bpy.types.Scene.ho_face_target_index = IntProperty(default=0)
    bpy.types.Scene.ho_face_port = IntProperty(name="HoFace 端口", default=21414, min=1, max=65535)
    bpy.types.Scene.ho_face_base_check = BoolProperty(name="基型检查", default=False)
    bpy.types.Scene.ho_face_pinning_check = BoolProperty(name="钉固检查", default=False)


def unregister():
    _stop()
    for name in ("ho_face_pinning_check", "ho_face_base_check", "ho_face_port",
                 "ho_face_target_index", "ho_face_targets"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
