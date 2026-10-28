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
        _copy_property_names=operator._copy_property_names,
    )
    for cls in reversed(operator.__mro__):
        for name, value in vars(cls).items():
            if isinstance(value, types.FunctionType):
                setattr(state, name, types.MethodType(value, state))
    return state


class DialogCapture:
    def __init__(self):
        self.calls = []

    def invoke_props_dialog(self, state, **kwargs):
        self.calls.append((state, kwargs))
        return {'RUNNING_MODAL'}


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

    # The collision dialog itself leaves all shape coordinates and order intact.
    obj, source = fixture("MirrorInvokeCollision", existing=True)
    keys = obj.data.shape_keys.key_blocks
    before_order = names(obj)
    before = {key.name: positions(key) for key in keys}
    state = dialog_operator()
    context = callback_context(obj)
    assert operator.invoke(state, context, None) == {'RUNNING_MODAL'}
    assert state.overwrite and state._create_copy_on_cancel
    assert len(context.window_manager.calls) == 1
    assert names(obj) == before_order
    for key in keys:
        assert np.array_equal(positions(key), before[key.name])

    # Cancel creates a copy through the registered operator, retaining old data.
    operator.cancel(state, context)
    assert not state._create_copy_on_cancel
    assert len(names(obj)) == len(before_order) + 1
    assert np.array_equal(positions(keys["SmileRight"]), before["SmileRight"])
    assert_mirror(keys["SmileRight.001"])
    after_cancel = names(obj)
    operator.cancel(state, context)
    assert names(obj) == after_cancel

    # RNA instances expose HO_OT_... names; cancel must dispatch the Python id.
    obj, source = fixture("MirrorRnaCancel", existing=True)
    keys = obj.data.shape_keys.key_blocks
    old_shape = positions(keys["SmileRight"])
    callback_ids = []
    original_execute = operator.execute

    def cancel_rna_execution(self, context):
        callback_ids.append(self.bl_idname)
        assert self.bl_idname == "HO_OT_generate_mirrored_shapekey"
        # Background Blender skips invoke callbacks, so trigger cancel from exec.
        # Restore the real implementation before cancel dispatches the copy op.
        operator.execute = original_execute
        self.overwrite = True
        self._create_copy_on_cancel = True
        self.cancel(context)
        return {'CANCELLED'}

    operator.execute = cancel_rna_execution
    try:
        result = bpy.ops.ho.generate_mirrored_shapekey(
            'EXEC_DEFAULT', auto_rename=True)
        assert result == {'CANCELLED'}, result
    finally:
        operator.execute = original_execute
    assert callback_ids == ["HO_OT_generate_mirrored_shapekey"]
    assert len(names(obj)) == 5
    assert np.array_equal(positions(keys["SmileRight"]), old_shape)
    assert_mirror(keys["SmileRight.001"])

    # Confirm reuses the colliding target.
    obj, source = fixture("MirrorConfirm", existing=True)
    state = dialog_operator()
    context = callback_context(obj)
    assert operator.invoke(state, context, None) == {'RUNNING_MODAL'}
    assert operator.execute(state, context) == {'FINISHED'}
    assert len(names(obj)) == 4
    assert_mirror(obj.data.shape_keys.key_blocks["SmileRight"])

    # With automatic renaming disabled, the source itself is a collision.
    obj, source = fixture("MirrorSelfConfirm")
    state = dialog_operator(auto_rename=False)
    context = callback_context(obj)
    assert operator.invoke(state, context, None) == {'RUNNING_MODAL'}
    assert operator.execute(state, context) == {'FINISHED'}
    assert len(names(obj)) == 3
    assert_mirror(source)

    obj, source = fixture("MirrorSelfCancel")
    source_before = positions(source)
    state = dialog_operator(auto_rename=False)
    context = callback_context(obj)
    assert operator.invoke(state, context, None) == {'RUNNING_MODAL'}
    operator.cancel(state, context)
    assert np.array_equal(positions(source), source_before)
    assert_mirror(obj.data.shape_keys.key_blocks["SmileLeft.001"])

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
