"""Run with Blender --background --factory-startup --python this_file.

Core operations work without ARP. When a local ARP installation is available,
also exercise its real human preset and Match to Rig operator.
"""

import importlib.util
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from BoneTools import arpAssembly as assembly, boneHumanoid, boneProperty, hoAux
from BoneTools.humanoid_auto_mapping import TARGET_LAYOUT


hoAux.register()
boneProperty.register()
boneHumanoid.register()
assert not hasattr(bpy.types.Scene, "bone_constraint_resting_armature")
assert not hasattr(bpy.types.Scene, "bone_humanoid_deform_tag_preset")
assert "deformMappingTag" not in boneProperty.PG_Hotools_BoneProps.bl_rna.properties
assert not assembly.arp_status()[0]


class LayoutRecorder:
    """Verify the visible fallback without requiring a GPU/UI screenshot."""
    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.enabled = True
        self.alert = False

    def box(self):
        return LayoutRecorder(self.events)

    def row(self, **_kwargs):
        return LayoutRecorder(self.events)

    def column(self, **_kwargs):
        return LayoutRecorder(self.events)

    def label(self, **kwargs):
        self.events.append(("label", kwargs["text"], self.alert))

    def operator(self, operator, **_kwargs):
        self.events.append(("operator", operator, self.enabled))

    def prop(self, *_args, **_kwargs):
        pass

    def separator(self):
        pass


def create_armature(name, specs):
    active = bpy.context.view_layer.objects.active
    if active and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    data = bpy.data.armatures.new(name + "Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for bone_name, head, tail in specs:
        bone = data.edit_bones.new(bone_name)
        bone.head, bone.tail = head, tail
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


scene = bpy.context.scene
main = create_armature("SnapMain", [
    ("hips", (0, 0, 0), (0, 0, 1)),
    ("hair", (0, 0, 1), (0, 0, 2)),
])
follower = create_armature("SnapFollower", [
    ("hips", (0, 0, 0), (0, 0, 1)),
    ("hair", (0, 0, 1), (0, 0, 2)),
    ("unmatched", (1, 0, 0), (1, 0, 1)),
])
scene.ho_arp_main_armature = main
scene.ho_arp_follower_armature = follower
layout = LayoutRecorder()
assembly.draw_panel(layout, bpy.context)
assert ("label", "未安装或未启用 Auto-Rig Pro", True) in layout.events
assert ("operator", "ho.generate_arp_controller", False) in layout.events
assert ("operator", "ho.snap_to_main_armature", True) in layout.events
assert ("operator", "ho.clear_humanoid_constraints", True) in layout.events
main.matrix_world = Matrix.Translation((3.0, -2.0, 1.0))
follower.matrix_world = Matrix.Translation((-4.0, 2.0, 0.0))
assert bpy.ops.ho.snap_to_main_armature() == {"FINISHED"}
assert bpy.ops.ho.snap_to_main_armature() == {"FINISHED"}
for name in ("hips", "hair"):
    constraints = follower.pose.bones[name].constraints
    assert len(constraints) == 2
    assert all(c.target == main and c.subtarget == name for c in constraints)
assert not follower.pose.bones["unmatched"].constraints
bpy.context.view_layer.update()
for name in ("hips", "hair"):
    actual = follower.matrix_world @ follower.pose.bones[name].head
    expected = main.matrix_world @ main.pose.bones[name].head
    assert (actual - expected).length < 1e-5, (name, actual, expected)
assert assembly.would_create_cycle(main, follower)

# Clearing includes manually authored constraints, but only on semantic bones.
main.data.bones["hips"].hotools_boneprops.humanoidMapping = "hips"
main.pose.bones["hips"].constraints.new("LIMIT_ROTATION")
main.pose.bones["hips"].constraints.new("LIMIT_LOCATION")
main.pose.bones["hair"].constraints.new("LIMIT_ROTATION")
assert bpy.ops.ho.clear_humanoid_constraints() == {"FINISHED"}
assert not main.pose.bones["hips"].constraints
assert len(main.pose.bones["hair"].constraints) == 1

# Save/restore the edit context, including flushing an edited bone position.
bpy.context.view_layer.objects.active = main
bpy.ops.object.select_all(action="DESELECT")
main.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
main.data.edit_bones["hips"].head.x = 0.25
assert bpy.ops.ho.snap_to_main_armature() == {"FINISHED"}
assert bpy.context.object == main and main.mode == "EDIT"
bpy.ops.object.mode_set(mode="OBJECT")
assert abs(main.data.bones["hips"].head_local.x - 0.25) < 1e-6
# Validate every pair before changing any constraints.
prior = [(c, c.target, c.influence) for c in follower.pose.bones["hips"].constraints]
try:
    assembly.bind_pairs(follower, main, [
        ("hips", "hips", ""), ("hair", "missing_target", "")],
        assembly.SNAP_PREFIX)
    raise AssertionError("Expected a missing-target error")
except ValueError:
    pass
assert all(c.target == target and c.influence == influence
           for c, target, influence in prior)
# Exercise rollback after a runtime error, including an updated existing binding.
saved_configure = assembly._configure_constraint
def fail_configure(constraint, *args):
    saved_configure(constraint, *args)
    constraint.influence = 0.25
    if constraint.type == "COPY_ROTATION":
        raise ValueError("injected constraint failure")
assembly._configure_constraint = fail_configure
try:
    assembly.bind_pairs(
        follower, main, [("hips", "hips", "")], assembly.SNAP_PREFIX)
    raise AssertionError("Expected the injected constraint failure")
except ValueError as error:
    assert str(error) == "injected constraint failure"
finally:
    assembly._configure_constraint = saved_configure
assert len(follower.pose.bones["hips"].constraints) == 2
assert all(c.target == target and c.influence == influence
           for c, target, influence in prior)
# Twist compatibility remains rotation-only.
twist = create_armature("TwistFollower", [("twist", (0, 0, 0), (0, 0, 1))])
assembly.bind_pairs(
    twist, main, [("twist", "hips", "arm_twist.L")], assembly.ASSEMBLY_PREFIX)
assert len(twist.pose.bones["twist"].constraints) == 1
rotation = twist.pose.bones["twist"].constraints[0]
assert rotation.type == "COPY_ROTATION"
assert rotation.owner_space == "LOCAL_WITH_PARENT"
assert rotation.target_space == "LOCAL_OWNER_ORIENT"
print("ARP_ASSEMBLY_CORE_OK")


arp_spec = importlib.util.find_spec("auto_rig_pro")
if arp_spec:
    bpy.ops.preferences.addon_enable(module="auto_rig_pro")
    assert assembly.arp_status() == (True, "")
    preset = Path(arp_spec.origin).parent / "armature_presets" / "human.blend"
    with bpy.data.libraries.load(str(preset), link=False) as (source, target):
        target.objects = source.objects
    template = next(obj for obj in target.objects if obj and obj.type == "ARMATURE")
    specs = []
    for slot, reference_name in assembly.REFERENCE_BONES.items():
        bone = template.data.bones[reference_name]
        # Fit a moved, resized character, not a duplicate at the preset origin.
        offset = Vector((0.45, 0.2, 0.35))
        head = bone.head_local * 1.6 + offset
        tail = bone.tail_local * 1.6 + offset
        # Wrist bone lengths are often arbitrary in imported character rigs.
        # Palm placement must use finger roots rather than that short length.
        if slot.startswith("hand."):
            tail = head + (tail - head) * 0.2
        specs.append((slot, head, tail))
    source = create_armature("Character", specs)
    bpy.ops.object.mode_set(mode="EDIT")
    parents = {slot: parent for slot, parent, _, _ in TARGET_LAYOUT}
    for slot, reference_name in assembly.REFERENCE_BONES.items():
        bone = source.data.edit_bones[slot]
        # ARP's legacy toe reference has the opposite roll to its deform bone.
        # A character's rest axes follow its actual deform bones.
        roll_name = assembly.DEFORM_BONES[slot] if slot.startswith("toes.") else reference_name
        bone.align_roll(template.data.bones[roll_name].matrix_local.to_3x3().col[2])
        # An imported ankle's roll must not turn the ground pivots upright or
        # change the foot controller footprint. Use different rolls per side.
        if slot.startswith("foot."):
            bone.roll += 1.2 if slot.endswith(".L") else -0.85
        parent = source.data.edit_bones.get(parents.get(slot, ""))
        if parent:
            bone.parent = parent
            bone.use_connect = (bone.head - parent.tail).length < 1e-5
    bpy.ops.object.mode_set(mode="OBJECT")
    source.matrix_world = (
        Matrix.Translation((2.0, 3.0, 0.5))
        @ Matrix.Rotation(0.35, 4, "Z")
        @ Matrix.Scale(1.25, 4)
    )
    for slot, reference_name in assembly.REFERENCE_BONES.items():
        source.data.bones[slot].hotools_boneprops.humanoidMapping = slot
    # No source metacarpals: all eight ARP palms must be reconstructed.
    scene.ho_arp_main_armature = source
    original_rest = {
        bone.name: (bone.head_local.copy(), bone.tail_local.copy(),
                    bone.matrix_local.copy())
        for bone in source.data.bones
    }
    original_hierarchy = {
        bone.name: (bone.parent.name if bone.parent else None, bone.use_connect)
        for bone in source.data.bones
    }
    bpy.context.scene.cursor.location = (8.0, -4.0, 2.0)
    count_before = len([obj for obj in bpy.data.objects if obj.type == "ARMATURE"])
    assert bpy.ops.ho.generate_arp_controller() == {"FINISHED"}
    rig = source.ho_arp_controller
    assert rig and rig.data.get("has_match_to_rig", False)
    assert len([obj for obj in bpy.data.objects if obj.type == "ARMATURE"]) == count_before + 1
    footprint_scale = 1.6 * 1.25
    for side in ("l", "r"):
        offsets = []
        for base in assembly.FOOT_HELPER_BASES:
            name = f"{base}.{side}"
            bone = rig.data.bones[name]
            saved = template.data.bones[name]
            direction = (bone.tail_local - bone.head_local).normalized()
            saved_direction = (saved.tail_local - saved.head_local).normalized()
            assert direction.dot(saved_direction) > 0.99999, name
            assert abs(direction.z) < 1e-5 and direction.y < -0.99999, name
            assert bone.matrix_local.to_3x3().col[2].dot(
                saved.matrix_local.to_3x3().col[2]) > 0.99999, name
            assert abs(bone.length - saved.length * footprint_scale) < 1e-5, name
            offsets.extend((
                bone.head_local - saved.head_local * footprint_scale,
                bone.tail_local - saved.tail_local * footprint_scale,
            ))
        assert all((offset - offsets[0]).length < 1e-5 for offset in offsets)
        heel = rig.data.bones[f"foot_heel_ref.{side}"]
        saved_heel = template.data.bones[f"foot_heel_ref.{side}"]
        foot = rig.data.bones[f"foot_ref.{side}"]
        toes = rig.data.bones[f"toes_ref.{side}"]
        saved_foot = template.data.bones[f"foot_ref.{side}"]
        saved_toes = template.data.bones[f"toes_ref.{side}"]
        low_z = min(p.z for p in (
            foot.head_local, foot.tail_local, toes.head_local, toes.tail_local))
        saved_low_z = min(p.z for p in (
            saved_foot.head_local, saved_foot.tail_local,
            saved_toes.head_local, saved_toes.tail_local))
        assert abs((low_z - heel.head_local.z)
                   - (saved_low_z - saved_heel.head_local.z) * footprint_scale) < 1e-5
        # ARP sizes/orients the final controller using the heel-to-toe extent.
        # Verify the generated output as well as the three reference bones.
        control = rig.data.bones[f"c_foot_ik.{side}"]
        control_direction = (control.tail_local - control.head_local).normalized()
        assert abs(control_direction.z) < 1e-5
        assert control_direction.y < -0.99999
        assert abs(control.length - (heel.head_local - toes.tail_local).length / 3) < 1e-5
        assert abs(control.length - template.data.bones[
            f"c_foot_ik.{side}"].length * footprint_scale) < 1e-5
    print("ARP_ASSEMBLY_GROUNDED_FOOT_CONTROLS_OK")
    for side in ("l", "r"):
        for finger in ("index", "middle", "ring", "pinky"):
            palm = rig.data.bones[f"{finger}1_base_ref.{side}"]
            proximal = rig.data.bones[f"{finger}1_ref.{side}"]
            assert palm.length > 1e-5
            assert (palm.tail_local - proximal.head_local).length < 1e-5
            assert not palm.use_connect
            assert palm.parent.name == f"hand_ref.{side}"
            wrist = rig.data.bones[f"hand_ref.{side}"].head_local
            assert 0 < (palm.head_local - wrist).length < (
                proximal.head_local - wrist).length
    for slot in assembly.REFERENCE_BONES:
        target_name = assembly.DEFORM_BONES[slot]
        constraints = source.pose.bones[slot].constraints
        assert len(constraints) == 2, (slot, len(constraints))
        assert all(c.target == rig and c.subtarget == target_name for c in constraints)
    for name, (head, tail, matrix) in original_rest.items():
        bone = source.data.bones[name]
        assert (bone.head_local - head).length < 1e-6
        assert (bone.tail_local - tail).length < 1e-6
        assert all(abs(bone.matrix_local[r][c] - matrix[r][c]) < 1e-6
                   for r in range(4) for c in range(4))
        assert (bone.parent.name if bone.parent else None, bone.use_connect) == (
            original_hierarchy[name])
    bpy.context.view_layer.update()
    evaluated = source.evaluated_get(bpy.context.evaluated_depsgraph_get())
    for name, (head, tail, _) in original_rest.items():
        bone = evaluated.pose.bones[name]
        assert (evaluated.matrix_world @ bone.head
                - source.matrix_world @ head).length < 5e-5, name
        assert (evaluated.matrix_world @ bone.tail
                - source.matrix_world @ tail).length < 5e-5, name
        expected_rotation = (source.matrix_world @ original_rest[name][2]).to_quaternion()
        actual_rotation = (evaluated.matrix_world @ bone.matrix).to_quaternion()
        assert abs(expected_rotation.dot(actual_rotation)) > 0.99999, name
    assert bpy.ops.ho.generate_arp_controller() == {"FINISHED"}
    assert source.ho_arp_controller == rig
    assert len([obj for obj in bpy.data.objects if obj.type == "ARMATURE"]) == count_before + 1
    assert all(len(b.constraints) == 2 for b in source.pose.bones)
    # A distal control drives its own source segment, not the proximal bone.
    rig.pose.bones["c_index2.l"].rotation_euler.x = 0.3
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    driven = source.evaluated_get(depsgraph).pose.bones["index_intermediate.L"]
    driver = rig.evaluated_get(depsgraph).pose.bones["c_index2.l"]
    driven_world = source.matrix_world @ driven.matrix
    driver_world = rig.matrix_world @ driver.matrix
    assert (driven_world.translation - driver_world.translation).length < 1e-5
    assert driven_world.to_quaternion().rotation_difference(
        driver_world.to_quaternion()).angle < 1e-4
    # A controller in an excluded collection still exists. Recover only that
    # object, preserving the collection exclusion and the controller's pose.
    excluded = bpy.data.collections.new("ExcludedArpController")
    scene.collection.children.link(excluded)
    excluded.objects.link(rig)
    for collection in tuple(rig.users_collection):
        if collection != excluded:
            collection.objects.unlink(rig)
    excluded_layer = bpy.context.view_layer.layer_collection.children[excluded.name]
    excluded_layer.exclude = True
    bpy.context.view_layer.update()
    assert scene.objects.get(rig.name) == rig
    assert bpy.context.view_layer.objects.get(rig.name) is None
    before_objects = set(bpy.data.objects)
    saved_bind = assembly.bind_pairs
    def fail_bind(*_args):
        raise ValueError("injected rebind failure")
    assembly.bind_pairs = fail_bind
    try:
        assembly.generate_controller(bpy.context, source)
        raise AssertionError("Expected the injected rebind failure")
    except ValueError as error:
        assert str(error) == "injected rebind failure"
    finally:
        assembly.bind_pairs = saved_bind
    assert scene.collection.objects.get(rig.name) is None
    assert bpy.context.view_layer.objects.get(rig.name) is None
    assert source.ho_arp_controller == rig
    assert excluded_layer.exclude
    assert bpy.ops.ho.generate_arp_controller() == {"FINISHED"}
    assert source.ho_arp_controller == rig
    assert bpy.context.view_layer.objects.get(rig.name) == rig
    assert excluded_layer.exclude
    assert set(bpy.data.objects) == before_objects
    assert abs(rig.pose.bones["c_index2.l"].rotation_euler.x - 0.3) < 1e-6

    # Unlinking/deleting the controller's collection can leave a non-None
    # pointer to an orphan object. It must not prevent generating a new rig.
    for collection in tuple(rig.users_collection):
        collection.objects.unlink(rig)
    bpy.context.view_layer.update()
    assert scene.objects.get(rig.name) is None
    assert source.ho_arp_controller == rig
    before_objects = set(bpy.data.objects)
    saved_align = assembly.align_reference_bones
    def fail_orphan_replacement(*_args):
        raise ValueError("injected orphan replacement failure")
    assembly.align_reference_bones = fail_orphan_replacement
    try:
        assembly.generate_controller(bpy.context, source)
        raise AssertionError("Expected the injected replacement failure")
    except ValueError as error:
        assert str(error) == "injected orphan replacement failure"
    finally:
        assembly.align_reference_bones = saved_align
    assert set(bpy.data.objects) == before_objects
    assert source.ho_arp_controller == rig
    assert all(c.target == rig for bone in source.pose.bones for c in bone.constraints)
    assert bpy.ops.ho.generate_arp_controller() == {"FINISHED"}
    replacement = source.ho_arp_controller
    assert replacement != rig
    assert scene.objects.get(replacement.name) == replacement
    assert bpy.context.view_layer.objects.get(replacement.name) == replacement
    assert scene.objects.get(rig.name) is None
    assert bpy.data.objects.get(rig.name) == rig
    assert all(c.target == replacement for bone in source.pose.bones for c in bone.constraints)
    assert all(len(bone.constraints) == 2 for bone in source.pose.bones)
    print("ARP_ASSEMBLY_CONTROLLER_RECOVERY_OK")
    # An error after creating a new rig must not leave orphan assemblies.
    failed_source = create_armature("FailedCharacter", specs)
    for slot in assembly.REFERENCE_BONES:
        failed_source.data.bones[slot].hotools_boneprops.humanoidMapping = slot
    objects_before = set(bpy.data.objects)
    collections_before = set(bpy.data.collections)
    original_align = assembly.align_reference_bones
    def fail_alignment(*_args):
        raise ValueError("injected alignment failure")
    assembly.align_reference_bones = fail_alignment
    try:
        assembly.generate_controller(bpy.context, failed_source)
        raise AssertionError("Expected the injected failure")
    except ValueError as error:
        assert str(error) == "injected alignment failure"
    finally:
        assembly.align_reference_bones = original_align
    assert set(bpy.data.objects) == objects_before
    assert set(bpy.data.collections) == collections_before
    assert not failed_source.ho_arp_controller
    assert all(not bone.constraints for bone in failed_source.pose.bones)
    print("ARP_ASSEMBLY_REAL_GENERATION_OK")
else:
    print("ARP_ASSEMBLY_REAL_GENERATION_SKIPPED: ARP is not installed")

boneHumanoid.unregister()
boneProperty.unregister()
hoAux.unregister()
assert not hasattr(bpy.types.Scene, "ho_arp_main_armature")
assert not hasattr(bpy.types.Object, "ho_arp_controller")
print("ARP_ASSEMBLY_ALL_OK")
