"""Fan weights stay in armature-local half spaces when symmetry is enabled.

Run Blender with --background --factory-startup --python-exit-code 1.
Only synthetic armatures and meshes are created; no user model is read.
"""

import json
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from BoneTools import boneProperty, hoAux
from BoneTools.auxBone import boneFan
from BoneTools.auxBone.boneFan import BoneFanCore
from BoneTools.auxBone.boneFanSingle import BoneFanSingleCore
from BoneTools.auxBone.boneFanSide import BoneFanSideCore
from Utils.bone_selection import select_bones

EPS = 1e-6
TOLERANCE = 2e-6
POINTS = [(.08, 0, 1.03), (.12, .02, .96), (-.08, 0, 1.03), (-.12, .02, .96),
          (0, 0, 1), (.005, -.015, 1.005), (-.005, -.015, 1.005),
          (.08, 0, .5), (-.08, 0, .5)]
# These cross-plane edges deliberately let unmasked blur reach the other leg.
EDGES = [(0, 1), (0, 2), (1, 3), (2, 3), (0, 4), (2, 4), (4, 5), (4, 6),
         (5, 6), (0, 7), (2, 8)]
RESULTS = []


def trs(position, angles, scale):
    return (Matrix.Translation(Vector(position)) @ Euler(angles).to_matrix().to_4x4()
            @ Matrix.Diagonal((*scale, 1)))


TRANSFORMS = {
    "identity": (Matrix.Identity(4), Matrix.Identity(4)),
    "rotated_nonuniform": (trs((1.2, -.7, .3), (.4, -.6, .8), (1.7, .65, 1.2)),
                           trs((-.5, .8, -.2), (-.3, .9, .2), (.8, 1.4, .7))),
    "reflected": (trs((-.6, .9, -.4), (-.7, .3, .5), (-1.3, .8, 1.1)),
                  trs((.7, -.2, .8), (.2, -.8, .6), (1.2, -.9, .6))),
}


def reset():
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def make_rig(label, transform="identity", shared=False, side_joint=False):
    reset()
    data = bpy.data.armatures.new(label + "Data")
    rig = bpy.data.objects.new(label, data)
    bpy.context.scene.collection.objects.link(rig)
    rig.matrix_world = TRANSFORMS[transform][0]
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")

    def add(name, head, tail, parent=""):
        value = data.edit_bones.new(name)
        value.head, value.tail = head, tail
        if parent:
            value.parent = data.edit_bones[parent]
        return value

    pairs = []
    if shared:
        add("Pelvis", (0, 0, 1.5), (0, 0, 1))
        for suffix, sign in ((".L", 1), (".R", -1)):
            joint = (0 if side_joint else sign * .08, 0, 1)
            add("Leg" + suffix, joint, (sign * .14, .12, .5), "Pelvis")
            pairs.append(("Pelvis", "Leg" + suffix))
    else:
        for suffix, sign in ((".L", 1), (".R", -1)):
            add("Thigh" + suffix, (sign * .08, 0, 1.5), (sign * .08, 0, 1))
            add("Shin" + suffix, (sign * .08, 0, 1), (sign * .08, .12, .5), "Thigh" + suffix)
            pairs.append(("Thigh" + suffix, "Shin" + suffix))
    bpy.ops.object.mode_set(mode="OBJECT")
    mesh = bpy.data.meshes.new(label + "Mesh")
    obj = bpy.data.objects.new(label + "Skin", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.matrix_world = TRANSFORMS[transform][1]
    local_to_mesh = obj.matrix_world.inverted() @ rig.matrix_world
    mesh.from_pydata([tuple(local_to_mesh @ Vector(p)) for p in POINTS], EDGES, [])
    modifier = obj.modifiers.new("Skin", "ARMATURE")
    modifier.object = rig
    sources = ["Pelvis", "Leg.L", "Leg.R"] if shared else ["Thigh.L", "Shin.L", "Thigh.R", "Shin.R"]
    for name in sources:
        group = obj.vertex_groups.new(name=name)
        for index, point in enumerate(POINTS):
            if shared:
                weight = .6 if name == "Pelvis" else .2 if point[0] == 0 else (.3999 if (point[0] > 0) == name.endswith(".L") else .0001)
            elif point[0] == 0:
                weight = .3 if name.startswith("Thigh") else .2
            elif (point[0] > 0) == name.endswith(".L"):
                weight = .5999 if name.startswith("Thigh") else .3999
            else:
                weight = .0001
            group.add([index], weight, "REPLACE")
    untouched = obj.vertex_groups.new(name="Unrelated")
    untouched.add(list(range(len(POINTS))), .125, "REPLACE")
    bpy.context.view_layer.update()
    # Mesh coordinates intentionally differ from both world and rig coordinates.
    for vertex, point in zip(mesh.vertices, POINTS):
        recovered = rig.matrix_world.inverted() @ obj.matrix_world @ vertex.co
        assert (recovered - Vector(point)).length < 1e-5
    before = snapshot(obj, sources + ["Unrelated"])
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    return rig, obj, pairs, before


def weight(obj, name, index):
    group = obj.vertex_groups.get(name)
    if group is None:
        return 0
    # Blender 4.5 prints an error before raising for an unassigned vertex.
    return next((entry.weight for entry in obj.data.vertices[index].groups
                 if entry.group == group.index), 0)


def snapshot(obj, names):
    return {name: [weight(obj, name, i) for i in range(len(POINTS))] for name in names}


def fan_sources(rig, fans):
    return {name: rig.data.edit_bones[name].parent.name for name in fans}


def check(label, rig, obj, before, fans_by_side, split=True, center_untouched=False, shared=False):
    fans = [name for names in fans_by_side.values() for name in names]
    source_by_fan = fan_sources(rig, fans)
    max_error, leaked = 0, 0
    for source, original in before.items():
        for index, wanted in enumerate(original):
            actual = weight(obj, source, index) + sum(weight(obj, name, index) for name in fans if source_by_fan[name] == source)
            max_error = max(max_error, abs(actual - wanted))
            assert abs(actual - wanted) < TOLERANCE, (label, "channel conservation", source, index, actual, wanted)
    for side, names in fans_by_side.items():
        for index, point in enumerate(POINTS):
            forbidden = side * point[0] < -EPS or center_untouched and abs(point[0]) <= EPS
            if forbidden:
                value = sum(weight(obj, name, index) for name in names)
                leaked += value
                if split:
                    assert value < TOLERANCE, (label, "wrong half space", side, index, value)
        # This verifies the test did actual redistribution, rather than passing
        # because every generated fan stayed empty.
        signal = sum(weight(obj, name, i) for name in names for i, point in enumerate(POINTS) if side * point[0] > EPS)
        assert signal > .01, (label, "missing same-side transfer", side, signal)
    if center_untouched:
        for source, original in before.items():
            assert abs(weight(obj, source, 4) - original[4]) < TOLERANCE, (label, "center changed", source)
    if shared:
        amounts = [sum(weight(obj, name, 4) for name in fans_by_side[side] if source_by_fan[name] == "Pelvis") for side in (1, -1)]
        assert min(amounts) > .001 and abs(amounts[0] - amounts[1]) < TOLERANCE, (label, "shared center symmetry", amounts)
    RESULTS.append({"case": label, "channelError": max_error, "oppositeWeight": leaked})
    return leaked


def regular_case(transform, blur, radius, split=True, operator=False):
    label = "Fan_{}_blur{}_radius{}_split{}{}".format(transform, blur, radius, split, "_operator" if operator else "")
    rig, obj, pairs, before = make_rig(label, transform)
    fans_by_side = {}
    if operator:
        settings = bpy.context.scene.ho_fan_settings
        settings.process_symmetry = True
        settings.auto_transfer_weights = True
        settings.generate_in, settings.generate_out = False, True
        settings.count_out = 4
        settings.fan_weight_radius, settings.fan_weight_blur = radius, blur
        select_bones(rig, list(pairs[0]))
        assert bpy.ops.ho.fan_generate("EXEC_DEFAULT") == {"FINISHED"}
        for side, suffix in ((1, ".L"), (-1, ".R")):
            fans_by_side[side] = [b.name for b in rig.data.edit_bones if b.name.endswith(suffix) and "_fan_out_" in b.name and "_pin_" not in b.name]
            assert len(fans_by_side[side]) == 4
    else:
        for side, pair in zip((1, -1), pairs):
            fans = BoneFanCore._create_fan_bones(rig, list(pair), "out", 4, .2, .04)
            fans_by_side[side] = fans
            BoneFanCore.apply_fan_weights(bpy.context, rig, list(pair), fans, radius, blur, False, split_sides=split)
    leaked = check(label, rig, obj, before, fans_by_side, split, center_untouched=split)
    if not split:
        assert leaked > 1e-5, (label, "off switch no longer retains old sphere behavior", leaked)


def multi_case(kind, blur, transform):
    label = "{}_shared_{}_blur{}".format(kind, transform, blur)
    side = kind == "FanSide"
    rig, obj, pairs, before = make_rig(label, transform, shared=True, side_joint=side)
    fans_by_side, sites = {}, []
    if side:
        # The two children start on X=0 and branch to opposite sides. This also
        # exercises side inference from child endpoints when joint.x is zero.
        for sign, pair in zip((1, -1), pairs):
            frame, error = BoneFanSideCore._resolve_side_frame(rig, rig.data.edit_bones[pair[0]], rig.data.edit_bones[pair[1]])
            assert error is None
            names = []
            for direction, marker, index in BoneFanSideCore._side_fan_directions(frame, 2, .5):
                parent = BoneFanCore._choose_parent_bone(direction, frame["parent_bone"], frame["parent_dir"], frame["child_bone"], frame["child_dir"])
                name = BoneFanCore._fan_name(parent.name, marker, index, 2, force_suffix=".L" if sign > 0 else ".R")
                value = rig.data.edit_bones.new(name)
                value.head, value.tail = frame["joint"], frame["joint"] + direction * .2
                value.parent = parent
                names.append(name)
            fans_by_side[sign] = names
            sites.append({"parent_name": pair[0], "child_name": pair[1], "fan_names": names})
        BoneFanSideCore.apply_fan_weights_side_multi(bpy.context, rig, sites, .8, blur, False, .02, 0, split_sides=True)
    else:
        virtual = rig.matrix_world.to_3x3() @ Vector((0, 0, 1))
        for sign, pair in zip((1, -1), pairs):
            names = BoneFanSingleCore._create_fan_bones_single(rig, pair[1], pair[0], virtual, "in", 4, .2, .04, force_suffix=".L" if sign > 0 else ".R")
            fans_by_side[sign] = names
            sites.append({"parent_name": pair[0], "main_name": pair[1], "virtual_dir_world": virtual, "fan_names": names})
        BoneFanSingleCore.apply_fan_weights_multi(bpy.context, rig, sites, .8, blur, False, .02, split_sides=True)
    check(label, rig, obj, before, fans_by_side, shared=True)


hoAux.register()  # Required BoneProps dependency; no large HoAux bones are created.
boneProperty.register()
boneFan.register()
try:
    for transform in TRANSFORMS:
        for blur in (0, 1):
            for radius in (.14, .8):
                regular_case(transform, blur, radius)
    for blur in (0, 1):
        regular_case("identity", blur, .8, split=False)
    regular_case("rotated_nonuniform", 1, .8, operator=True)
    for kind in ("FanSingle", "FanSide"):
        for blur in (0, 1):
            for transform in ("identity", "reflected"):
                multi_case(kind, blur, transform)
finally:
    reset()
    boneFan.unregister()
    boneProperty.unregister()
    hoAux.unregister()

print("AUX_WEIGHT_SYMMETRY_RESULTS", json.dumps(RESULTS, sort_keys=True))
print("AUX_WEIGHT_SYMMETRY_OK", bpy.app.version_string, len(RESULTS))
