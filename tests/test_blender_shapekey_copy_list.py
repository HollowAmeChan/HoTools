import importlib
import sys
import types
from pathlib import Path

import bpy
import numpy as np


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))
package = types.ModuleType("HoTools")
package.__path__ = [str(ADDON_DIR)]
sys.modules.setdefault("HoTools", package)
shapekey_package = types.ModuleType("HoTools.ShapekeyTools")
shapekey_package.__path__ = [str(ADDON_DIR / "ShapekeyTools")]
sys.modules.setdefault("HoTools.ShapekeyTools", shapekey_package)
module = importlib.import_module("HoTools.ShapekeyTools.operators")


def make_object(name):
    mesh = bpy.data.meshes.new(f"{name}Data")
    mesh.from_pydata(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [], []
    )
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


source = make_object("CopyListSource")
source.shape_key_add(name="Basis", from_mix=False)
source.shape_key_add(name="Smile", from_mix=False)
source.shape_key_add(name="Blink", from_mix=False)

target = make_object("CopyListTarget")
basis = target.shape_key_add(name="Basis", from_mix=False)
basis.data[0].co.z = 2.0
basis.data[1].co.z = 3.0
basis.data[2].co.z = 4.0
existing = target.shape_key_add(name="Existing", from_mix=False)
existing.data[0].co.z += 10.0
existing.value = 1.0

# Exercise the relative/absolute toggle path that used to expose from_mix=True.
target.data.shape_keys.use_relative = False
target.data.shape_keys.use_relative = True
target.active_shape_key_index = target.data.shape_keys.key_blocks.find("Existing")

for obj in bpy.context.selected_objects:
    obj.select_set(False)
source.select_set(True)
target.select_set(True)
bpy.context.view_layer.objects.active = source

operator_class = module.OP_ShapekeyTools_CopyList2selectedObjects
bpy.utils.register_class(operator_class)
try:
    assert bpy.ops.ho.shapekeytools_copylist2selectedobjects(
        "EXEC_DEFAULT") == {'FINISHED'}
finally:
    bpy.utils.unregister_class(operator_class)

target_keys = target.data.shape_keys.key_blocks
assert [key.name for key in target_keys] == [
    "Basis", "Smile", "Blink", "Existing"
]
basis_positions = np.array([point.co[:] for point in basis.data])
for name in ("Smile", "Blink"):
    positions = np.array([point.co[:] for point in target_keys[name].data])
    assert np.allclose(positions, basis_positions, atol=1e-6)

for obj in (source, target):
    bpy.data.objects.remove(obj, do_unlink=True)
print("SHAPEKEY_COPY_LIST_OK", bpy.app.version_string)
