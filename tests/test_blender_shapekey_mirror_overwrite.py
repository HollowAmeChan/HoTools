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
operator = module.OP_GenerateMirroredShapekey


def positions(key):
    return np.array([point.co[:] for point in key.data])


def names(obj):
    return [key.name for key in obj.data.shape_keys.key_blocks]


def fixture(label, *, existing=False, basis_name="Basis"):
    mesh = bpy.data.meshes.new(label + "Data")
    mesh.from_pydata([(-1, 0, 0), (0, 0, 0), (1, 0, 0)], [], [])
    obj = bpy.data.objects.new(label, mesh)
    bpy.context.scene.collection.objects.link(obj)
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    obj.shape_key_add(name=basis_name, from_mix=False)
    source = obj.shape_key_add(name="SmileLeft", from_mix=False)
    source.data[0].co = (-1.25, 0.5, 2)
    source.data[1].co.z = 1
    obj.shape_key_add(name="Tail", from_mix=False)
    if existing:
        target = obj.shape_key_add(name="SmileRight", from_mix=False)
        for point in target.data:
            point.co.z = 99
    obj.active_shape_key_index = 1
    return obj, source


def assert_mirror(key):
    assert np.allclose(positions(key), [(-1, 0, 0), (0, 0, 1), (1.25, 0.5, 2)], atol=1e-6)


def run_mirror(**kwargs):
    assert bpy.ops.ho.generate_mirrored_shapekey('EXEC_DEFAULT', **kwargs) == {'FINISHED'}


def dialog_operator(*, auto_rename=True):
    """Bind real callbacks without opening a popup in background mode."""
    state = types.SimpleNamespace(
        auto_rename=auto_rename, overwrite=True,
        report=lambda *args: None, poll=operator.poll,
        bl_idname=operator.bl_idname,
    )
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


def callback_context(obj):
    return types.SimpleNamespace(
        active_object=obj, mode='OBJECT', scene=bpy.context.scene,
        window_manager=DialogCapture(),
    )


registered = (module.OP_balanceShapekey, operator)
for cls in registered:
    bpy.utils.register_class(cls)
props_registered = False
try:
    module.reg_props()
    props_registered = True

    # The clear path still inserts a renamed mirror immediately after its source.
    obj, source = fixture("MirrorFresh")
    source_before = positions(source)
    run_mirror(auto_rename=True, overwrite=False)
    assert names(obj) == ["Basis", "SmileLeft", "SmileRight", "Tail"]
    assert_mirror(obj.data.shape_keys.key_blocks["SmileRight"])
    assert np.array_equal(positions(source), source_before)

    # Reuse the actual target, retaining its driver, nonzero value and references.
    obj, source = fixture("MirrorOverwrite", existing=True)
    keys = obj.data.shape_keys.key_blocks
    target = keys["SmileRight"]
    target.slider_min, target.slider_max = -2, 3
    target.value = 0.6
    curve = target.driver_add("value")
    curve.driver.expression = "0.6"
    follower = obj.shape_key_add(name="Follower", from_mix=False)
    follower.relative_key = target
    before_order = names(obj)
    identity = target.as_pointer()
    source_before = positions(source)
    run_mirror(auto_rename=True, overwrite=True)
    assert names(obj) == before_order
    assert keys["SmileRight"].as_pointer() == identity
    assert follower.relative_key == target
    assert curve.driver.expression == "0.6"
    assert abs(target.value - 0.6) < 1e-6
    assert (target.slider_min, target.slider_max) == (-2, 3)
    assert np.array_equal(positions(source), source_before)
    assert_mirror(target)

    # Copy mode preserves the existing target and adds the numbered mirror.
    obj, source = fixture("MirrorCopy", existing=True)
    keys = obj.data.shape_keys.key_blocks
    old_shape = positions(keys["SmileRight"])
    run_mirror(auto_rename=True, overwrite=False)
    assert names(obj) == ["Basis", "SmileLeft", "SmileRight.001", "Tail", "SmileRight"]
    assert np.array_equal(positions(keys["SmileRight"]), old_shape)
    assert_mirror(keys["SmileRight.001"])

    # Invoking without a collision resets any previous overwrite decision.
    obj, source = fixture("MirrorInvokeClear")
    state = dialog_operator()
    context = callback_context(obj)
    assert operator.invoke(state, context, None) == {'FINISHED'}
    assert not state.overwrite and not context.window_manager.calls
    assert_mirror(obj.data.shape_keys.key_blocks["SmileRight"])

    # The native dialog exposes one enum and leaves all shapes unchanged.
    obj, source = fixture("MirrorInvokeCollision", existing=True)
    keys = obj.data.shape_keys.key_blocks
    before_order = names(obj)
    before = {key.name: positions(key) for key in keys}
    state = dialog_operator()
    context = callback_context(obj)
    assert operator.invoke(state, context, None) == {'RUNNING_MODAL'}
    assert len(context.window_manager.calls) == 1
    assert state.overwrite_mode == 'OVERWRITE'
    state.layout = LayoutCapture()
    operator.draw(state, context)
    # Keep enum item labels visible in Blender's expanded toggle buttons.
    assert state.layout.props == [('overwrite_mode', {'expand': True})]
    assert "SmileRight" in state.layout.labels
    assert not any("副本" in text for text in state.layout.labels)
    state.overwrite_mode = 'NEW'
    assert names(obj) == before_order
    for key in keys:
        assert np.array_equal(positions(key), before[key.name])

    # Confirming NEW retains the existing target and creates the numbered mirror.
    assert operator.execute(state, context) == {'FINISHED'}
    assert len(names(obj)) == len(before_order) + 1
    assert np.array_equal(positions(keys["SmileRight"]), before["SmileRight"])
    assert_mirror(keys["SmileRight.001"])

    # The enum choices work through the real registered RNA execution path.
    mode_prop = bpy.ops.ho.generate_mirrored_shapekey.get_rna_type().properties['overwrite_mode']
    assert mode_prop.default == 'OVERWRITE'
    assert [(item.identifier, item.name) for item in mode_prop.enum_items] == [
        ('OVERWRITE', "覆盖"), ('NEW', "新建")]
    for mode in ('OVERWRITE', 'NEW'):
        obj, source = fixture("MirrorEnum" + mode, existing=True)
        keys = obj.data.shape_keys.key_blocks
        old_shape = positions(keys["SmileRight"])
        run_mirror(auto_rename=True, overwrite_mode=mode, overwrite=(mode == 'NEW'))
        if mode == 'OVERWRITE':
            assert len(names(obj)) == 4
            assert_mirror(keys["SmileRight"])
        else:
            assert len(names(obj)) == 5
            assert np.array_equal(positions(keys["SmileRight"]), old_shape)
            assert_mirror(keys["SmileRight.001"])

    # Disabling automatic renaming still warns before changing the source itself.
    obj, source = fixture("MirrorSelfConfirm")
    state = dialog_operator(auto_rename=False)
    context = callback_context(obj)
    assert operator.invoke(state, context, None) == {'RUNNING_MODAL'}
    assert operator.execute(state, context) == {'FINISHED'}
    assert len(names(obj)) == 3
    assert_mirror(source)

    # A renamed target matching Basis must produce a safe numbered copy.
    obj, source = fixture("MirrorBasisProtection", basis_name="SmileRight")
    basis = obj.data.shape_keys.reference_key
    basis_before = positions(basis)
    run_mirror(auto_rename=True, overwrite=True)
    assert np.array_equal(positions(basis), basis_before)
    assert_mirror(obj.data.shape_keys.key_blocks["SmileRight.001"])
finally:
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    if props_registered:
        module.ureg_props()
    for cls in reversed(registered):
        bpy.utils.unregister_class(cls)

print("SHAPEKEY_MIRROR_OVERWRITE_OK", bpy.app.version_string)
