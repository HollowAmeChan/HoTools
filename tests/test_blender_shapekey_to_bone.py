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
modtools_package = types.ModuleType("HoTools.ModTools")
modtools_package.__path__ = [str(ADDON_DIR / "ModTools")]
sys.modules.setdefault("HoTools.ModTools", modtools_package)

module = importlib.import_module("HoTools.ModTools.shapekey_to_bone")
from HoTools.Utils.bone_selection import select_bones


def make_armature():
    data = bpy.data.armatures.new("ShapeKeyToBoneRigData")
    armature = bpy.data.objects.new("ShapeKeyToBoneRig", data)
    bpy.context.scene.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    head = data.edit_bones.new("Head")
    head.head = (0.0, -0.5, 0.0)
    head.tail = (0.0, 0.0, 0.0)
    upper = data.edit_bones.new("UpperLid")
    upper.head = (0.0, 0.0, 1.0)
    upper.tail = (0.0, 0.2, 1.0)
    upper.parent = head
    lower = data.edit_bones.new("LowerLid")
    lower.head = (0.0, 0.0, -1.0)
    lower.tail = (0.0, 0.2, -1.0)
    lower.parent = head

    bpy.ops.object.mode_set(mode='POSE')
    select_bones(armature, ["UpperLid", "LowerLid"])
    bpy.ops.object.mode_set(mode='OBJECT')
    return armature


def make_mesh(armature):
    data = bpy.data.meshes.new("ShapeKeyToBoneMeshData")
    data.from_pydata(
        [
            (-1.0, 0.0, 1.0),
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 1.0),
            (-1.0, 0.0, -1.0),
            (0.0, 0.0, -1.0),
            (1.0, 0.0, -1.0),
            (-0.2, 0.0, 1.5),
            (0.2, 0.0, 1.5),
            (0.0, 0.0, 1.8),
        ],
        [
            (0, 1), (1, 2),
            (3, 4), (4, 5),
            (0, 3), (1, 4), (2, 5),
            (6, 7),
        ],
        [],
    )
    mesh = bpy.data.objects.new("ShapeKeyToBoneMesh", data)
    bpy.context.scene.collection.objects.link(mesh)
    modifier = mesh.modifiers.new(name="Armature", type='ARMATURE')
    modifier.object = armature

    basis = mesh.shape_key_add(name="Basis", from_mix=False)
    blink = mesh.shape_key_add(name="Blink", from_mix=False)
    for index in (0, 2):
        blink.data[index].co.z -= 0.2
    blink.data[1].co.z -= 0.4
    for index in (3, 5):
        blink.data[index].co.z += 0.2
    blink.data[4].co.z += 0.4
    blink.data[6].co.z -= 0.3
    blink.data[7].co.z -= 0.3
    blink.data[8].co.z -= 0.25
    mesh.active_shape_key_index = 1

    head_group = mesh.vertex_groups.new(name="Head")
    head_group.add(list(range(9)), 1.0, 'REPLACE')
    return mesh, basis, blink


armature = make_armature()
mesh, basis, blink = make_mesh(armature)

module.register()
try:
    settings = bpy.context.scene.ho_mod_shapekey_to_bone
    settings.armature_object = armature
    settings.mesh_object = mesh
    settings.only_selected_bones = True
    settings.shape_key_scope = 'ACTIVE'
    settings.smooth_iterations = 0
    settings.max_influences = 2

    plan = module.ShapeKeyWeightSolver.build_plan(bpy.context, settings)
    assert plan.shape_key_names == ("Blink",)
    assert set(plan.target_bone_names) == {"UpperLid", "LowerLid"}
    assert plan.donor_names == ("Head",)
    assert plan.affected_indices == (0, 1, 2, 3, 4, 5, 6, 7, 8)

    module.WeightTransferTransaction(plan).commit()

    def weight(group_name, index):
        group_index = mesh.vertex_groups[group_name].index
        return next(
            (
                membership.weight
                for membership in mesh.data.vertices[index].groups
                if membership.group == group_index
            ),
            0.0,
        )

    first_result = {}
    for index in range(9):
        head_weight = weight("Head", index)
        upper_weight = weight("UpperLid", index)
        lower_weight = weight("LowerLid", index)
        assert abs(head_weight + upper_weight + lower_weight - 1.0) < 1e-6
        first_result[index] = (head_weight, upper_weight, lower_weight)

    assert weight("UpperLid", 0) > weight("LowerLid", 0)
    assert weight("UpperLid", 1) > weight("LowerLid", 1)
    assert weight("UpperLid", 2) > weight("LowerLid", 2)
    assert weight("LowerLid", 3) > weight("UpperLid", 3)
    assert weight("LowerLid", 4) > weight("UpperLid", 4)
    assert weight("LowerLid", 5) > weight("UpperLid", 5)
    assert weight("UpperLid", 6) > weight("LowerLid", 6)
    assert weight("UpperLid", 7) > weight("LowerLid", 7)
    assert weight("UpperLid", 6) + weight("LowerLid", 6) > 0.0
    assert weight("UpperLid", 8) > weight("LowerLid", 8)
    assert weight("UpperLid", 8) + weight("LowerLid", 8) > 0.0

    # Rebuilding from donor + target pools must be deterministic and idempotent.
    second_plan = module.ShapeKeyWeightSolver.build_plan(bpy.context, settings)
    module.WeightTransferTransaction(second_plan).commit()
    for index, expected in first_result.items():
        actual = (
            weight("Head", index),
            weight("UpperLid", index),
            weight("LowerLid", index),
        )
        assert all(abs(a - b) < 1e-6 for a, b in zip(actual, expected))

    # Strength increases the transferred target-bone budget without changing totals.
    head_before_strength = weight("Head", 0)
    settings.transfer_strength = 2.0
    strong_plan = module.ShapeKeyWeightSolver.build_plan(bpy.context, settings)
    module.WeightTransferTransaction(strong_plan).commit()
    assert weight("Head", 0) < head_before_strength
    assert abs(
        weight("Head", 0)
        + weight("UpperLid", 0)
        + weight("LowerLid", 0)
        - 1.0
    ) < 1e-6
    settings.transfer_strength = 1.0

    # A relative shape key must be measured against its own relative key, not Basis.
    relative = mesh.shape_key_add(name="Relative", from_mix=False)
    relative.relative_key = blink
    for index in range(9):
        relative.data[index].co = blink.data[index].co.copy()
    relative.data[0].co.x += 0.25
    mesh.active_shape_key_index = mesh.data.shape_keys.key_blocks.find("Relative")
    settings.motion_threshold_ratio = 0.001
    relative_plan = module.ShapeKeyWeightSolver.build_plan(bpy.context, settings)
    assert relative_plan.max_motion < 0.26
    assert relative_plan.max_motion > 0.24

    modifier = next(modifier for modifier in mesh.modifiers if modifier.type == 'ARMATURE')
    mesh.modifiers.remove(modifier)
    unbound_plan = module.ShapeKeyWeightSolver.build_plan(bpy.context, settings)
    assert any("尚未" in warning for warning in unbound_plan.warnings)
    assert len(mesh.modifiers) == 0
finally:
    module.unregister()

# Exercise the real ModTools package registration order without importing unrelated
# viewport GPU modules from the add-on root package.
sys.modules.pop("HoTools.ModTools", None)
modtools = importlib.import_module("HoTools.ModTools")
modtools.register()
try:
    assert hasattr(bpy.types.Scene, "ho_mod_shapekey_to_bone")
    assert hasattr(bpy.types.Scene, "ho_ModToolsPanel_Mod")
finally:
    modtools.unregister()

print("SHAPEKEY_TO_BONE_OK", bpy.app.version_string)
