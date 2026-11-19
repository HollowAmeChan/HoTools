"""Blender regression tests for Unity muscle coordinates on a parented rig."""
from math import acos, atan, degrees, radians, sin, cos
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from BoneTools import boneProperty, hoAux
from BoneTools.HumanoidDebug import muscles, rig
from BoneTools.HumanoidDebug.anim_parser import HumanoidClip
from Exporter.HumanoidMappingExporter import HumanoidMappingExporter


def create_rig():
    specs = [
        ("hips", None, (0, 0, 1), (0, 0, 1.1)),
        ("spine", "hips", (0, 0, 1.1), (0, 0, 1.3)),
        ("chest", "spine", (0, 0, 1.3), (0, 0, 1.55)),
        ("neck", "chest", (0, 0, 1.55), (0, 0, 1.65)),
        ("head", "neck", (0, 0, 1.65), (0, 0, 1.85)),
    ]
    for side, sign in (("L", 1), ("R", -1)):
        def add(slot, parent, head, tail):
            specs.append((f"{slot}.{side}", f"{parent}.{side}" if parent not in {"chest", "hips"} else parent,
                          (head[0] * sign, *head[1:]), (tail[0] * sign, *tail[1:])))
        add("shoulder", "chest", (0.1, 0, 1.5), (0.2, 0, 1.5))
        add("upper_arm", "shoulder", (0.2, 0, 1.5), (0.5, 0, 1.5))
        add("lower_arm", "upper_arm", (0.5, 0, 1.5), (0.8, 0, 1.5))
        add("hand", "lower_arm", (0.8, 0, 1.5), (0.86, 0, 1.5))
        add("index_proximal", "hand", (0.87, -0.02, 1.5), (0.92, -0.02, 1.5))
        add("index_intermediate", "index_proximal", (0.92, -0.02, 1.5), (0.96, -0.02, 1.5))
        add("index_distal", "index_intermediate", (0.96, -0.02, 1.5), (1, -0.02, 1.5))
        add("upper_leg", "hips", (0.12, 0, 0.95), (0.12, 0, 0.5))
        add("lower_leg", "upper_leg", (0.12, 0, 0.5), (0.12, 0, 0.05))
        add("foot", "lower_leg", (0.12, 0, 0.05), (0.12, -0.12, 0.02))
        add("toes", "foot", (0.12, -0.12, 0.02), (0.12, -0.2, 0.02))
    data = bpy.data.armatures.new("MuscleRegressionRig")
    obj = bpy.data.objects.new("MuscleRegressionRig", data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for index, (slot, parent, head, tail) in enumerate(specs):
        bone = data.edit_bones.new(slot)
        bone.head, bone.tail = head, tail
        bone.roll = (index % 5 - 2) * 0.37
        if parent:
            bone.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    for slot, _parent, _head, _tail in specs:
        props = data.bones[slot].hotools_boneprops
        # Standard Unity labels, including spaced finger names, must work.
        props.humanoidMapping = HumanoidMappingExporter.to_unity_human_name(slot)
        props.humanoidTPoseCached = True
        props.humanoidTPoseMatrixBasis = tuple(v for row in Matrix.Identity(4) for v in row)
    return obj


def reference_sample():
    sample = {channel: 0.0 for channel in muscles.CHANNELS}
    for side in ("Left", "Right"):
        sample.update({
            f"{side} Arm Down-Up": 0.4,
            f"{side} Arm Front-Back": 0.3,
            f"{side} Forearm Stretch": 1.0,
            f"{side} Upper Leg Front-Back": 0.6,
            f"{side} Lower Leg Stretch": 1.0,
            f"{side}Hand.Index.1 Stretched": degrees(2 * atan(0.3)) / 50,
            f"{side}Hand.Index.Spread": -degrees(2 * atan(0.08)) / 20,
            f"{side}Hand.Index.2 Stretched": degrees(2 * atan(0.33)) / 45,
            f"{side}Hand.Index.3 Stretched": degrees(2 * atan(0.33)) / 45,
        })
    sample.update({"RootT.x": 0, "RootT.y": 1, "RootT.z": 0,
                   "RootQ.x": 0, "RootQ.y": 0, "RootQ.z": 0, "RootQ.w": 1})
    return sample


hoAux.register()
boneProperty.register()
obj = create_rig()
assert rig.clip_readiness(obj)[0]
assert rig.humanoid_mapping(obj)["upper_arm.L"] == "upper_arm.L"
assert rig.humanoid_mapping(obj)["index_intermediate.R"] == "index_intermediate.R"
obj.data.bones["head"].hotools_boneprops.humanoidTPoseCached = False
assert not rig.clip_readiness(obj)[0]
obj.data.bones["head"].hotools_boneprops.humanoidTPoseCached = True
state = rig.build_reference_state(obj, HumanoidClip(None, {}))
sample = reference_sample()
rig.apply_sample(obj, state, sample)
for bone in obj.pose.bones:
    expected = state["references"][bone.name]
    assert max(abs(bone.matrix[i][j] - expected[i][j]) for i in range(4) for j in range(4)) < 2e-5, bone.name

# A muscle value of 1 opens the elbow/knee; zero bends it about 80 degrees.
bent = {**sample, "Left Forearm Stretch": 0, "Left Lower Leg Stretch": 0}
rig.apply_sample(obj, state, bent)
for upper, lower in (("upper_arm.L", "lower_arm.L"), ("upper_leg.L", "lower_leg.L")):
    a = (obj.pose.bones[upper].tail - obj.pose.bones[upper].head).normalized()
    b = (obj.pose.bones[lower].tail - obj.pose.bones[lower].head).normalized()
    assert abs(degrees(acos(max(-1, min(1, a.dot(b))))) - 80) < 0.01
assert obj.pose.bones["hand.L"].head.y < obj.pose.bones["lower_arm.L"].head.y
assert obj.pose.bones["foot.L"].head.y > obj.pose.bones["lower_leg.L"].head.y

# The root uses a left-handed source frame and a body-centre height of 1.
# Forward motion moves along the model's forward, with no extra upward step.
rig.apply_sample(obj, state, {**sample, "RootT.z": 0.2})
for bone in obj.pose.bones:
    delta = bone.head - state["references"][bone.name].translation
    assert (delta - Vector((0, -state["rig_scale"] * 0.2, 0))).length < 2e-5
rotation = Quaternion((cos(radians(45)), 0, sin(radians(45)), 0))
turned = {**sample, **{f"RootQ.{axis}": value for axis, value in zip("wxyz", rotation)}}
rig.apply_sample(obj, state, turned)
conversion = Matrix(((-1, 0, 0), (0, 0, 1), (0, -1, 0)))
expected_turn = conversion.transposed() @ rotation.to_matrix() @ conversion
for bone in obj.pose.bones:
    relative = bone.head - obj.pose.bones["hips"].head
    reference = state["references"][bone.name].translation - state["references"]["hips"].translation
    assert (relative - expected_turn @ reference).length < 3e-5, bone.name

# Optional UpperChest curves fold into Chest. They must not disappear.
rig.apply_sample(obj, state, {**sample, "Chest Front-Back": 0.25, "UpperChest Front-Back": 0.5})
combined = obj.pose.bones["chest"].matrix_basis.copy()
rig.apply_sample(obj, state, {**sample, "Chest Front-Back": 0.5})
assert max(abs(combined[i][j] - obj.pose.bones["chest"].matrix_basis[i][j])
           for i in range(4) for j in range(4)) < 1e-5

# A multi-axis result captured from Unity HumanPoseHandler, not computed
# with this implementation: catches rotation-order and swing errors.
native_sample = {
    "Spine Front-Back": -0.15160387754440308,
    "Spine Left-Right": -0.9231911897659302,
    "Spine Twist Left-Right": 0.6084752082824707,
}
actual = muscles.swing_twist(muscles.angles_for_sample(muscles.BY_SLOT["spine"], native_sample))
expected = Quaternion((0.9260407374, 0.1997012011, -0.3197768936, 0.0176272895))
assert min((actual - expected).magnitude, (actual + expected).magnitude) < 2e-6
assert muscles.angles_for_sample(muscles.BY_SLOT["upper_leg.L"],
                                {"Left Upper Leg Front-Back": -1})[2] == -90
assert muscles.angles_for_sample(muscles.BY_SLOT["upper_leg.L"],
                                {"Left Upper Leg Front-Back": 1})[2] == 50

rig.apply_sample(obj, state, bent, muscle_scale=0)
for bone in obj.pose.bones:
    assert bone.matrix_basis.to_quaternion().angle < 1e-4, bone.name
print("HUMANOID_MUSCLES_OK", bpy.app.version_string, len(obj.pose.bones))
bpy.data.objects.remove(obj, do_unlink=True)
boneProperty.unregister()
hoAux.unregister()
