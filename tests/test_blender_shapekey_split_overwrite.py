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
operator = module.OP_SplitShapekey


def positions(key):
    return np.array([point.co[:] for point in key.data])


def names(obj):
    return [key.name for key in obj.data.shape_keys.key_blocks]


def fixture(label, existing=()):
    mesh = bpy.data.meshes.new(label + "Data")
    mesh.from_pydata([(-1, 0, 0), (0, 0, 0), (1, 0, 0)], [], [])
    obj = bpy.data.objects.new(label, mesh)
    bpy.context.scene.collection.objects.link(obj)
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    obj.shape_key_add(name="Basis", from_mix=False)
    source = obj.shape_key_add(name="Wide", from_mix=False)
    for index, delta in enumerate((2, 4, 6)):
        source.data[index].co.z += delta
    obj.shape_key_add(name="Tail", from_mix=False)
    for suffix in existing:
        target = obj.shape_key_add(name="Wide" + suffix, from_mix=False)
        for point in target.data:
            point.co.z = 99
    obj.active_shape_key_index = 1
    return obj, source


def assert_split(obj, left_name="WideLeft", right_name="WideRight"):
    keys = obj.data.shape_keys.key_blocks
    assert np.allclose(positions(keys[left_name]), [(-1, 0, 2), (0, 0, 2), (1, 0, 0)])
    assert np.allclose(positions(keys[right_name]), [(-1, 0, 0), (0, 0, 2), (1, 0, 6)])


def run_split(**kwargs):
    assert bpy.ops.ho.split_shapekey(
        'EXEC_DEFAULT', suffix_viewLeft="Left", suffix_viewRight="Right",
        **kwargs) == {'FINISHED'}


def dialog_operator():
    """Exercise the real Python callbacks without opening UI in background mode."""
    state = types.SimpleNamespace(
        suffix_viewLeft="Left", suffix_viewRight="Right", overwrite=True,
        report=lambda *args: None, poll=operator.poll,
        bl_idname=operator.bl_idname,
    )
    # Include the shared confirmation mixin's callbacks on the lightweight state.
    for cls in reversed(operator.__mro__):
        for name, value in vars(cls).items():
            if isinstance(value, types.FunctionType):
                setattr(state, name, types.MethodType(value, state))
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
    # No collision retains the existing insertion order and center-line split.
    obj, source = fixture("FreshSplit")
    run_split()
    assert names(obj) == ["Basis", "Wide", "WideLeft", "WideRight", "Tail"]
    assert_split(obj)

    # Overwriting updates the actual keys while retaining settings and references.
    obj, source = fixture("OverwriteBoth", ("Left", "Right"))
    keys = obj.data.shape_keys.key_blocks
    left, right = keys["WideLeft"], keys["WideRight"]
    left.slider_min, left.slider_max, left.value = -2, 3, 0.25
    left.mute = True
    left.lock_shape = True
    left.relative_key = keys["Tail"]
    follower = obj.shape_key_add(name="Follower", from_mix=False)
    follower.relative_key = left
    curve = right.driver_add("value")
    curve.driver.expression = "0.33"
    identity = (left.as_pointer(), right.as_pointer(), curve.as_pointer())
    before_order = names(obj)
    source_before = positions(source)
    run_split(overwrite=True)
    assert names(obj) == before_order
    assert (left.as_pointer(), right.as_pointer(), curve.as_pointer()) == identity
    assert (left.slider_min, left.slider_max, left.value) == (-2, 3, 0.25)
    assert left.mute and left.lock_shape and left.relative_key == keys["Tail"]
    assert follower.relative_key == left and curve.driver.expression == "0.33"
    assert np.array_equal(positions(source), source_before)
    assert_split(obj)

    # A missing side is added; its existing counterpart is reused in place.
    for existing_suffix in ("Left", "Right"):
        obj, source = fixture("Overwrite" + existing_suffix, (existing_suffix,))
        existing_key = obj.data.shape_keys.key_blocks["Wide" + existing_suffix]
        pointer = existing_key.as_pointer()
        run_split(overwrite=True)
        assert len(names(obj)) == 5
        assert existing_key.as_pointer() == pointer
        assert_split(obj)

    # Explicit copy mode keeps the old shapes and adds Blender's numbered keys.
    obj, source = fixture("CopyBoth", ("Left", "Right"))
    keys = obj.data.shape_keys.key_blocks
    before = {name: positions(keys[name]) for name in ("WideLeft", "WideRight")}
    run_split(overwrite=False)
    assert len(names(obj)) == 7
    assert_split(obj, "WideLeft.001", "WideRight.001")
    for name, coords in before.items():
        assert np.array_equal(positions(keys[name]), coords)

    # Invoke resets a previous overwrite decision and runs immediately if clear.
    obj, source = fixture("InvokeClear")
    state = dialog_operator()
    dialog = DialogCapture()
    context = types.SimpleNamespace(active_object=obj, window_manager=dialog)
    assert operator.invoke(state, context, None) == {'FINISHED'}
    assert not state.overwrite and not dialog.calls
    assert_split(obj)

    # The native dialog lists conflicts and exposes the overwrite/new enum.
    obj, source = fixture("InvokeCollision", ("Right",))
    keys = obj.data.shape_keys.key_blocks
    before_order = names(obj)
    before = {key.name: positions(key) for key in keys}
    state = dialog_operator()
    dialog = DialogCapture()
    context = types.SimpleNamespace(active_object=obj, window_manager=dialog)
    assert operator.invoke(state, context, None) == {'RUNNING_MODAL'}
    assert len(dialog.calls) == 1 and state.overwrite_mode == 'OVERWRITE'
    assert state._existing_target_names(obj) == ("WideRight",)
    state.layout = LayoutCapture()
    operator.draw(state, context)
    # Keep enum item labels visible in Blender's expanded toggle buttons.
    assert state.layout.props == [('overwrite_mode', {'expand': True})]
    assert "WideRight" in state.layout.labels
    assert not any("副本" in text for text in state.layout.labels)

    # Opening, drawing and changing the selection do not execute the operation.
    state.overwrite_mode = 'NEW'
    assert names(obj) == before_order
    for key in keys:
        assert np.array_equal(positions(key), before[key.name])

    # Confirming NEW retains the conflicting key and generates numbered results.
    assert operator.execute(state, context) == {'FINISHED'}
    assert names(obj) == ["Basis", "Wide", "WideLeft", "WideRight.001", "Tail", "WideRight"]
    assert_split(obj, "WideLeft", "WideRight.001")
    assert np.array_equal(positions(keys["WideRight"]), before["WideRight"])

    # Both registered enum choices override legacy bool arguments consistently.
    mode_prop = bpy.ops.ho.split_shapekey.get_rna_type().properties['overwrite_mode']
    assert mode_prop.default == 'OVERWRITE'
    assert [(item.identifier, item.name) for item in mode_prop.enum_items] == [
        ('OVERWRITE', "覆盖"), ('NEW', "新建")]
    for mode in ('OVERWRITE', 'NEW'):
        obj, source = fixture("SplitEnum" + mode, ("Left", "Right"))
        keys = obj.data.shape_keys.key_blocks
        old = {name: positions(keys[name]) for name in ("WideLeft", "WideRight")}
        run_split(overwrite_mode=mode, overwrite=(mode == 'NEW'))
        if mode == 'OVERWRITE':
            assert len(names(obj)) == 5
            assert_split(obj)
        else:
            assert len(names(obj)) == 7
            assert_split(obj, "WideLeft.001", "WideRight.001")
            for name, coords in old.items():
                assert np.array_equal(positions(keys[name]), coords)

    # Empty/equal suffixes must never overwrite the source or alias both sides.
    obj, source = fixture("EmptySuffix")
    source_before = positions(source)
    assert bpy.ops.ho.split_shapekey(
        'EXEC_DEFAULT', suffix_viewLeft="", suffix_viewRight="", overwrite=True,
    ) == {'FINISHED'}
    assert np.array_equal(positions(source), source_before)
    assert_split(obj, "Wide.001", "Wide.002")

    obj, source = fixture("EqualSuffix", ("Side",))
    assert bpy.ops.ho.split_shapekey(
        'EXEC_DEFAULT', suffix_viewLeft="Side", suffix_viewRight="Side", overwrite=True,
    ) == {'FINISHED'}
    assert_split(obj, "WideSide", "WideSide.001")
finally:
    for cls in reversed(registered):
        bpy.utils.unregister_class(cls)

print("SHAPEKEY_SPLIT_OVERWRITE_OK", bpy.app.version_string)
