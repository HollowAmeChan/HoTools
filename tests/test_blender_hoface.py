"""Blender-level contract for the thin HoFace receiver."""

import json
import socket
import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR.parent) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR.parent))

result = bpy.ops.preferences.addon_enable(module="HoTools")
assert result == {"FINISHED"}, result
assert hasattr(bpy.types.Scene, "ho_face_targets")
assert not hasattr(bpy.types.Scene, "ho_ShapekeyToolsPanel_Mod") or all(
    item[0] != "PANEL_SHAPEKEYTOOLS_BLENDMATRIX"
    for item in bpy.types.Scene.ho_ShapekeyToolsPanel_Mod.keywords.get("items", [])
)
assert hasattr(bpy.types, "HO_PT_HoFace") or hasattr(bpy.types, "HO_PT_hoface")

mesh = bpy.data.meshes.new("HoFaceTestMesh")
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
obj = bpy.data.objects.new("Face", mesh)
bpy.context.scene.collection.objects.link(obj)
obj.shape_key_add(name="Basis", from_mix=False)
obj.shape_key_add(name="JawOpen", from_mix=False)

scene = bpy.context.scene
target = scene.ho_face_targets.add()
target.object = obj
target.enabled = True

assert bpy.ops.ho.hoface_start() == {"FINISHED"}
packet = {
    "type": "hoface.preview",
    "version": 1,
    "sequence": 1,
    "time": 0.1,
    "tracked": True,
    "weights": {"jaw": 0.65},
    "targets": [{"id": "jaw", "slot": "Face", "shape": "JawOpen"}],
}
sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sender.sendto(json.dumps(packet).encode("utf-8"), ("127.0.0.1", scene.ho_face_port))
sender.close()

from HoTools import HoFace as hoface  # noqa: E402
hoface._poll_timer()
assert abs(obj.data.shape_keys.key_blocks["JawOpen"].value - 0.65) < 1e-6

obj.select_set(True)
bpy.context.view_layer.objects.active = obj
assert bpy.ops.ho.hoface_clear_keys() == {"FINISHED"}
assert obj.data.shape_keys.key_blocks["JawOpen"].value == 0.0

bpy.ops.ho.hoface_stop()
print("HO_FACE_BLENDER PASS")
