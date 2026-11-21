"""Twist symmetry keeps opposite-side source weights and uses rig-local X."""

import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from BoneTools.auxBone.boneTwist import TwistBoneCore


def weight(group, index):
    return next((item.weight for item in group.id_data.data.vertices[index].groups
                 if item.group == group.index), 0.0)


def rig(name, center=False):
    data = bpy.data.armatures.new(name + "Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    # Deliberately reverse .L/.R relative to +X/-X. Names cannot select space.
    for bone_name, x in (("Main.L", -1), ("Main.R", 1)):
        bone = data.edit_bones.new(bone_name)
        bone.head, bone.tail = (x, 0, 0), (x, 2, 0)
    middle = data.edit_bones.new("Crossing")
    middle.head, middle.tail = (-1, 0, 0), (1, 2, 0)
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


results = {}


def transfer_case(name, source_name, split, keep, soft, transformed=False):
    armature = rig(name)
    if transformed:
        armature.matrix_world = (Matrix.Translation((2, -3, 4))
            @ Matrix.Rotation(0.7, 4, "Z") @ Matrix.Diagonal((1.5, 0.8, 1.2, 1)))
    positions = [Vector((-1, 1.2, 0)), Vector((1, 1.2, 0)), Vector((0, 1.2, 0)), Vector((0.4, 1.2, 0))]
    mesh = bpy.data.meshes.new(name + "Mesh")
    obj = bpy.data.objects.new(name + "Object", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.matrix_world = (Matrix.Translation((-5, 1, -2)) @ Matrix.Rotation(-0.5, 4, "Y")) if transformed else Matrix.Identity(4)
    inverse = obj.matrix_world.inverted()
    mesh.from_pydata([inverse @ armature.matrix_world @ p for p in positions], [], [])
    source = obj.vertex_groups.new(name=source_name)
    original = [0.3, 0.45, 0.6, 0.75]
    for i, value in enumerate(original):
        source.add([i], value, "REPLACE")
    untouched = obj.vertex_groups.new(name="Other")
    for i in range(4):
        untouched.add([i], 0.125, "REPLACE")
    original = [weight(source, i) for i in range(4)]
    # Cover the complete objs -> obj -> split parameter chain while avoiding
    # unrelated bone creation/ownership setup in this focused weight test.
    create = TwistBoneCore.create_twist_chain
    TwistBoneCore.create_twist_chain = staticmethod(lambda *args, **kwargs: {
        "created_names": [name + "AuxA", name + "AuxB"], "replaced_names": []})
    try:
        TwistBoneCore.objs_bone_twist(source_name, 3, armature, soft, 0.1, keep, [obj], split_sides=split)
    finally:
        TwistBoneCore.create_twist_chain = staticmethod(create)
    groups = [obj.vertex_groups[name + "AuxA"], obj.vertex_groups[name + "AuxB"]]
    for i in range(4):
        assert abs(weight(source, i) + sum(weight(g, i) for g in groups) - original[i]) < 1e-6
        assert abs(weight(untouched, i) - 0.125) < 1e-7
    assert obj.vertex_groups.get("TMP_" + source_name) is None
    values = [sum(weight(g, i) for g in groups) for i in range(4)]
    if split and source_name != "Crossing":
        own = 0 if source_name == "Main.L" else 1
        blocked = (1, 2, 3) if own == 0 else (0, 2)
        assert values[own] > 0
        for i in blocked:
            assert values[i] == 0, (name, i, values)
            assert weight(source, i) == original[i], (name, i)
    else:
        assert values[0] > 0 and values[1] > 0, (name, values)
    results[name] = True


for keep in (True, False):
    for soft in (0.0, 0.5, 1.0):
        suffix = str(int(keep)) + "_" + str(soft)
        transfer_case("negative_" + suffix, "Main.L", True, keep, soft)
        transfer_case("positive_" + suffix, "Main.R", True, keep, soft, True)
transfer_case("symmetry_off", "Main.L", False, True, 0.5, True)
transfer_case("central_crossing_unchanged", "Crossing", True, True, 0.5)

# Existing process_symmetry setting explicitly flows into side-domain splitting.
armature = rig("Forwarding")
mesh_data = bpy.data.meshes.new("ForwardMesh")
mesh = bpy.data.objects.new("ForwardObject", mesh_data)
bpy.context.scene.collection.objects.link(mesh)
for name in ("Main.L", "Main.R"):
    mesh.vertex_groups.new(name=name)
collect, transfer, constraints = (TwistBoneCore._collect_generation_targets,
    TwistBoneCore.objs_bone_twist, TwistBoneCore.add_copy_rotation_to_twist_bones)
try:
    TwistBoneCore._collect_generation_targets = staticmethod(lambda *args: (armature, [mesh], ["Main.L"]))
    TwistBoneCore.add_copy_rotation_to_twist_bones = staticmethod(lambda *args: (0, {}))
    for symmetry in (False, True):
        calls = []
        def record(*args, **kwargs):
            calls.append((args[0], kwargs["split_sides"]))
            return {"created_names": []}
        TwistBoneCore.objs_bone_twist = staticmethod(record)
        TwistBoneCore.generate_twist(bpy.context, armature, 3,
            process_symmetry=symmetry, auto_transfer_weights=True)
        assert calls == ([("Main.L", True), ("Main.R", True)] if symmetry else [("Main.L", False)]), calls
    results["generation_setting_forwarded"] = True
finally:
    TwistBoneCore._collect_generation_targets = staticmethod(collect)
    TwistBoneCore.objs_bone_twist = staticmethod(transfer)
    TwistBoneCore.add_copy_rotation_to_twist_bones = staticmethod(constraints)

print("TWIST_WEIGHT_SIDE_RESULTS", json.dumps(results, sort_keys=True))
print("TWIST_WEIGHT_SIDES_OK", len(results), bpy.app.version_string)
