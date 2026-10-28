"""Run with Blender --background --factory-startup --python-exit-code 1 --python."""

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
operator = module.OP_ShapekeyTools_GenerateHideShapeKey


def positions(key):
    return np.array([point.co[:] for point in key.data])


def activate(obj):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def fixture(label, existing=True, *, basis_name="Basis"):
    arm_data = bpy.data.armatures.new(label + "RigData")
    arm = bpy.data.objects.new(label + "Rig", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    activate(arm)
    bpy.ops.object.mode_set(mode='EDIT')
    bone = arm_data.edit_bones.new("Bone")
    bone.head, bone.tail = (0, 0, 0), (0, 2, 0)
    bpy.ops.object.mode_set(mode='OBJECT')

    mesh = bpy.data.meshes.new(label + "Mesh")
    mesh.from_pydata([(-1, 0.25, 0), (2, 1.5, 0), (3, 0.75, 0), (4, 1, 0)], [], [])
    obj = bpy.data.objects.new(label, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = arm
    activate(obj)
    vg = obj.vertex_groups.new(name="Bone")
    for index, weight in enumerate((0.8, 0.4, 0.9, 0.0)):
        vg.add([index], weight, 'REPLACE')
    obj.shape_key_add(name=basis_name, from_mix=False)
    if existing:
        target = obj.shape_key_add(name="Hide_Bone", from_mix=False)
        for point in target.data:
            point.co.z = 99
        target.slider_min, target.slider_max, target.value = -1, 2, 0.37
    return obj


def run_hide(**kwargs):
    assert bpy.ops.ho.shapekeytools_generate_hide_shapekey(
        'EXEC_DEFAULT', **kwargs) == {'FINISHED'}


def assert_weight_projection(key):
    assert np.allclose(positions(key), [(0, 0.25, 0), (2, 1.5, 0), (0, 0.75, 0), (4, 1, 0)])


def dialog_operator(**kwargs):
    state = types.SimpleNamespace(
        mode='WEIGHT', threshold=0.5, slide_smooth=False, slide_factor=0.5,
        overwrite=True, report=lambda *args: None, poll=operator.poll,
        bl_idname=operator.bl_idname, _copy_property_names=operator._copy_property_names,
    )
    for method in ("_existing_target_names", "_invoke_overwrite_dialog", "_generate", "execute"):
        setattr(state, method, types.MethodType(getattr(operator, method), state))
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


class DialogCapture:
    def __init__(self):
        self.calls = []

    def invoke_props_dialog(self, state, **kwargs):
        self.calls.append((state, kwargs))
        return {'RUNNING_MODAL'}


bpy.utils.register_class(operator)
try:
    # Explicit execution retains the previous default of replacing the existing key.
    prop = bpy.ops.ho.shapekeytools_generate_hide_shapekey.get_rna_type().properties['overwrite']
    assert prop.default is True
    obj = fixture("HideOverwrite")
    keys = obj.data.shape_keys.key_blocks
    old = keys['Hide_Bone']
    old.mute, old.lock_shape = True, True
    follower = obj.shape_key_add(name="Follower", from_mix=False)
    follower.relative_key = old
    before_order = list(keys.keys())
    identity = old.as_pointer()
    run_hide(mode='WEIGHT', threshold=0.5, slide_smooth=False)
    assert list(keys.keys()) == before_order
    assert old.as_pointer() == identity
    assert follower.relative_key == old
    assert old.mute and old.lock_shape
    assert (old.slider_min, old.slider_max, old.value) == (-1, 2, 0)
    assert obj.active_shape_key == old
    assert_weight_projection(old)

    # Copy mode preserves the old key and selects the actual numbered result.
    obj = fixture("HideCopy")
    keys = obj.data.shape_keys.key_blocks
    before = positions(keys['Hide_Bone'])
    old_value = keys['Hide_Bone'].value
    run_hide(mode='WEIGHT', threshold=0.5, slide_smooth=False, overwrite=False)
    assert list(keys.keys()) == ['Basis', 'Hide_Bone', 'Hide_Bone.001']
    assert np.array_equal(positions(keys['Hide_Bone']), before)
    assert keys['Hide_Bone'].value == old_value
    assert obj.active_shape_key.name == 'Hide_Bone.001'
    assert_weight_projection(keys['Hide_Bone.001'])

    # No collision keeps the original parameter dialog, whose cancel does nothing.
    obj = fixture("HideFreshDialog", existing=False)
    state, dialog = dialog_operator(), DialogCapture()
    context = types.SimpleNamespace(active_object=obj, window_manager=dialog)
    assert operator.invoke(state, context, None) == {'RUNNING_MODAL'}
    assert not state._create_copy_on_cancel and len(dialog.calls) == 1
    operator.cancel(state, context)
    assert list(obj.data.shape_keys.key_blocks.keys()) == ['Basis']
    assert operator.execute(state, context) == {'FINISHED'}
    assert_weight_projection(obj.data.shape_keys.key_blocks['Hide_Bone'])

    # Conflicts only request a decision; confirming uses the configured parameters.
    obj = fixture("HideConfirmDialog")
    keys = obj.data.shape_keys.key_blocks
    before = positions(keys['Hide_Bone'])
    state, dialog = dialog_operator(), DialogCapture()
    context = types.SimpleNamespace(active_object=obj, window_manager=dialog)
    assert operator.invoke(state, context, None) == {'RUNNING_MODAL'}
    assert state._create_copy_on_cancel and state.overwrite
    assert state._existing_target_names(obj) == ('Hide_Bone',)
    assert np.array_equal(positions(keys['Hide_Bone']), before)
    assert dialog.calls[0][1]['confirm_text'] == '确定（覆盖）'
    assert operator.execute(state, context) == {'FINISHED'}
    assert not state._create_copy_on_cancel and len(keys) == 2
    assert_weight_projection(keys['Hide_Bone'])

    # Cancel forwards selection and slide parameters to the copy operation in edit mode.
    obj = fixture("HideCancelDialog")
    keys = obj.data.shape_keys.key_blocks
    old = positions(keys['Hide_Bone'])
    for vertex in obj.data.vertices:
        vertex.select = vertex.index in (1, 3)
    bpy.ops.object.mode_set(mode='EDIT')
    state = dialog_operator(mode='SELECT', threshold=0.9, slide_smooth=True, slide_factor=0.5)
    context = types.SimpleNamespace(active_object=obj, window_manager=DialogCapture())
    assert operator.invoke(state, context, None) == {'RUNNING_MODAL'}
    operator.cancel(state, context)
    assert obj.mode == 'EDIT'
    bpy.ops.object.mode_set(mode='OBJECT')
    assert not state._create_copy_on_cancel
    assert obj.active_shape_key.name == 'Hide_Bone.001'
    assert np.array_equal(positions(keys['Hide_Bone']), old)
    assert np.allclose(positions(keys['Hide_Bone.001']),
                       [(-1, 0.25, 0), (0, 1.75, 0), (3, 0.75, 0), (0, 0.5, 0)])
    operator.cancel(state, context)
    assert len(keys) == 3

    # A Basis named like the output must never be overwritten.
    obj = fixture("HideBasisProtection", existing=False, basis_name='Hide_Bone')
    keys = obj.data.shape_keys.key_blocks
    before = positions(keys[0])
    state = dialog_operator()
    assert state._existing_target_names(obj) == ()
    run_hide(mode='WEIGHT', threshold=0.5, slide_smooth=False, overwrite=True)
    assert np.array_equal(positions(keys[0]), before)
    assert obj.active_shape_key.name == 'Hide_Bone.001'
    assert_weight_projection(keys['Hide_Bone.001'])
finally:
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.utils.unregister_class(operator)

print("SHAPEKEY_HIDE_OVERWRITE_OK", bpy.app.version_string)
