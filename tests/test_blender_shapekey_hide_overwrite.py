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
        bl_idname=operator.bl_idname,
    )
    for cls in reversed(operator.__mro__):
        for name, value in vars(cls).items():
            if isinstance(value, types.FunctionType):
                setattr(state, name, types.MethodType(value, state))
    for key, value in kwargs.items():
        setattr(state, key, value)
    state.properties = types.SimpleNamespace(
        is_property_set=lambda name: name == 'overwrite_mode' and hasattr(state, name))
    return state


class DialogCapture:
    def __init__(self):
        self.calls = []

    def invoke_props_dialog(self, state, **kwargs):
        self.calls.append((state, kwargs))
        return {'RUNNING_MODAL'}


class LayoutCapture:
    def __init__(self):
        self.labels = []
        self.props = []

    def label(self, **kwargs):
        self.labels.append(kwargs['text'])

    def prop(self, state, property_name, **kwargs):
        self.props.append((property_name, kwargs))


registered = (operator,)
for cls in registered:
    bpy.utils.register_class(cls)
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

    # No collision keeps the original parameter dialog and generates on confirmation.
    obj = fixture("HideFreshDialog", existing=False)
    state, dialog = dialog_operator(), DialogCapture()
    context = types.SimpleNamespace(active_object=obj, window_manager=dialog)
    assert operator.invoke(state, context, None) == {'RUNNING_MODAL'}
    assert len(dialog.calls) == 1
    assert list(obj.data.shape_keys.key_blocks.keys()) == ['Basis']
    assert operator.execute(state, context) == {'FINISHED'}
    assert_weight_projection(obj.data.shape_keys.key_blocks['Hide_Bone'])

    # Parameters and the overwrite/new enum share one native confirmation dialog.
    obj = fixture("HideConfirmDialog")
    keys = obj.data.shape_keys.key_blocks
    before = positions(keys['Hide_Bone'])
    state, dialog = dialog_operator(), DialogCapture()
    context = types.SimpleNamespace(active_object=obj, window_manager=dialog)
    assert operator.invoke(state, context, None) == {'RUNNING_MODAL'}
    assert len(dialog.calls) == 1 and state.overwrite_mode == 'OVERWRITE'
    assert state._existing_target_names(obj) == ('Hide_Bone',)
    state.layout = LayoutCapture()
    operator.draw(state, context)
    assert [name for name, kwargs in state.layout.props] == [
        'mode', 'threshold', 'slide_smooth', 'overwrite_mode']
    # Keep enum item labels visible in Blender's expanded toggle buttons.
    assert state.layout.props[-1][1] == {'expand': True}
    assert "Hide_Bone" in state.layout.labels
    assert not any("副本" in text for text in state.layout.labels)
    assert np.array_equal(positions(keys['Hide_Bone']), before)

    # Confirming the default choice directly replaces the existing shape.
    assert operator.execute(state, context) == {'FINISHED'}
    assert len(keys) == 2
    assert_weight_projection(keys['Hide_Bone'])

    # Explicit enum values control registered execution and retain legacy bool support.
    mode_prop = bpy.ops.ho.shapekeytools_generate_hide_shapekey.get_rna_type().properties['overwrite_mode']
    assert mode_prop.default == 'OVERWRITE'
    assert [(item.identifier, item.name) for item in mode_prop.enum_items] == [
        ('OVERWRITE', "覆盖"), ('NEW', "新建")]
    for mode in ('OVERWRITE', 'NEW'):
        obj = fixture("HideEnum" + mode)
        keys = obj.data.shape_keys.key_blocks
        old_shape = positions(keys['Hide_Bone'])
        run_hide(mode='WEIGHT', threshold=0.5, slide_smooth=False,
                 overwrite_mode=mode, overwrite=(mode == 'NEW'))
        if mode == 'OVERWRITE':
            assert len(keys) == 2
            assert_weight_projection(keys['Hide_Bone'])
        else:
            assert len(keys) == 3
            assert np.array_equal(positions(keys['Hide_Bone']), old_shape)
            assert_weight_projection(keys['Hide_Bone.001'])

    # Opening and changing the enum in edit mode do not modify data or active state.
    obj = fixture("HideEditDialog")
    keys = obj.data.shape_keys.key_blocks
    old = positions(keys['Hide_Bone'])
    active_index = obj.active_shape_key_index
    for vertex in obj.data.vertices:
        vertex.select = vertex.index in (1, 3)
    bpy.ops.object.mode_set(mode='EDIT')
    state = dialog_operator(mode='SELECT', threshold=0.9, slide_smooth=True, slide_factor=0.5)
    context = types.SimpleNamespace(active_object=obj, window_manager=DialogCapture())
    assert operator.invoke(state, context, None) == {'RUNNING_MODAL'}
    state.overwrite_mode = 'NEW'
    assert obj.mode == 'EDIT'
    assert list(keys.keys()) == ['Basis', 'Hide_Bone']
    assert obj.active_shape_key_index == active_index
    assert np.array_equal(positions(keys['Hide_Bone']), old)

    # Confirming NEW honors selection/slide parameters and restores edit mode.
    assert operator.execute(state, context) == {'FINISHED'}
    assert obj.mode == 'EDIT'
    bpy.ops.object.mode_set(mode='OBJECT')
    assert obj.active_shape_key.name == 'Hide_Bone.001'
    assert np.array_equal(positions(keys['Hide_Bone']), old)
    assert np.allclose(positions(keys['Hide_Bone.001']),
                       [(-1, 0.25, 0), (0, 1.75, 0), (3, 0.75, 0), (0, 0.5, 0)])
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
    for cls in reversed(registered):
        bpy.utils.unregister_class(cls)

print("SHAPEKEY_HIDE_OVERWRITE_OK", bpy.app.version_string)
