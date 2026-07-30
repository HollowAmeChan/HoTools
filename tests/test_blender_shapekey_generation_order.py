import importlib
import sys
import types
from pathlib import Path

import bpy


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


def key_names(obj):
    return [key.name for key in obj.data.shape_keys.key_blocks]


def activate_key(obj, key):
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    obj.active_shape_key_index = obj.data.shape_keys.key_blocks.find(key.name)


mesh = bpy.data.meshes.new("ShapeKeyGenerationOrderData")
mesh.from_pydata(
    [(-1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
    [],
    [],
)
obj = bpy.data.objects.new("ShapeKeyGenerationOrder", mesh)
bpy.context.scene.collection.objects.link(obj)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

basis = obj.shape_key_add(name="Basis", from_mix=False)
mirror_source = obj.shape_key_add(name="SmileLeft", from_mix=False)
mirror_source.data[0].co.z += 0.5
mirror_tail = obj.shape_key_add(name="MirrorTail", from_mix=False)

registered = (
    module.OP_balanceShapekey,
    module.OP_GenerateMirroredShapekey,
    module.OP_SplitShapekey,
)
props_registered = False
for operator in registered:
    bpy.utils.register_class(operator)

try:
    module.reg_props()
    props_registered = True

    activate_key(obj, mirror_source)
    assert bpy.ops.ho.generate_mirrored_shapekey(
        "EXEC_DEFAULT", auto_rename=True, overwrite=False) == {'FINISHED'}
    names = key_names(obj)
    source_index = names.index("SmileLeft")
    assert names[source_index:source_index + 3] == [
        "SmileLeft", "SmileRight", "MirrorTail"]

    split_source = obj.shape_key_add(name="Wide", from_mix=False)
    split_source.data[2].co.y += 0.4
    split_tail = obj.shape_key_add(name="SplitTail", from_mix=False)
    activate_key(obj, split_source)
    assert bpy.ops.ho.split_shapekey(
        "EXEC_DEFAULT",
        suffix_viewLeft="Left",
        suffix_viewRight="Right",
    ) == {'FINISHED'}
    names = key_names(obj)
    source_index = names.index("Wide")
    assert names[source_index:source_index + 4] == [
        "Wide", "WideLeft", "WideRight", "SplitTail"]
finally:
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    if props_registered:
        module.ureg_props()
    for operator in reversed(registered):
        bpy.utils.unregister_class(operator)

print("SHAPEKEY_GENERATION_ORDER_OK", bpy.app.version_string)
