"""Actual Blender Copy Rotation samples plus raw/MCH FBX; no user file needed.

blender --background --factory-startup --disable-autoexec --python-exit-code 1
        --python tests/export_copyr_v4_fixture.py -- ABSOLUTE_OUTPUT_DIRECTORY
"""

import json
import math
from pathlib import Path
import random
import sys

import bpy
from bpy.props import BoolProperty, CollectionProperty, PointerProperty
from bpy.types import PropertyGroup
from mathutils import Euler, Matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from BoneTools.boneProperty import PG_Hotools_AuxBoneInfo, PG_Hotools_BoneRef
from BoneTools.auxBone.copyRotation import CopyRotationCore
from Exporter.FbxExporter import FBXExporter
from Exporter.FbxExporter import OP_FinalFBXExport
from Exporter.ConstraintIRExporter import ConstraintIRExporter
from RigConstraints import codec
from RigConstraints.binding import build_export_document
from RigConstraints.blender.properties import PROPERTY_CLASSES, PG_RigConstraintGroup
from RigConstraints.source.reader import capture_armature
from RigConstraints.semantics.translate import translate
from RigConstraints.registry import implementations_for


class FixtureBoneProps(PropertyGroup):
    generateMCH: BoolProperty(default=False)
    auxBone: PointerProperty(type=PG_Hotools_AuxBoneInfo)
    constraintGroups: CollectionProperty(type=PG_RigConstraintGroup)


for cls in (PG_Hotools_BoneRef, PG_Hotools_AuxBoneInfo, *PROPERTY_CLASSES, FixtureBoneProps):
    bpy.utils.register_class(cls)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=FixtureBoneProps)
out = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
out.mkdir(parents=True, exist_ok=True)
operator_mode = "--operator-object-transform" in sys.argv


def flat(matrix):
    return [float(value) for row in matrix for value in row]


def save(name, value):
    (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def build():
    rig = bpy.data.objects.new("CopyRLocal", bpy.data.armatures.new("CopyRLocalData"))
    bpy.context.scene.collection.objects.link(rig)
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")

    def bone(name, head, direction, parent=None, roll=0):
        b = rig.data.edit_bones.new(name)
        b.head = head
        b.tail = tuple(a + d for a, d in zip(head, direction))
        b.roll = roll
        if parent:
            b.parent = rig.data.edit_bones[parent]

    bone("Root", (0, 0, 0), (0, 0, .3), roll=.2)
    inputs = ["Root"]
    operations = []
    for side, sign in (("L", 1), ("R", -1)):
        bone("OwnerParent_"+side, (sign*.3, -.1, .85), (sign*.1, .2, .25), "Root", sign*.4)
        bone("TargetParent_"+side, (sign*.5, .25, .9), (-sign*.1, .1, .3), "Root", -sign*.6)
        bone("TargetA_"+side, (sign*.48, .3, .95), (sign*.12, .05, -.55), "TargetParent_"+side, sign*.7)
        bone("TargetB_"+side, (sign*.52, .4, .9), (-sign*.25, -.13, -.35), "TargetParent_"+side, -sign*.5)
        # Top-level measurement source isolates the existing rigid MCH binding
        # from Blender Child Of's dynamic pre-state parent composition. Raw
        # TargetA/B cases above cover independent animated target parents.
        bone("MchInput_"+side, (sign*.9, .15, 1.05), (-sign*.18, .1, -.4), roll=sign*.8)
        inputs += [name+"_"+side for name in ("OwnerParent", "TargetParent", "TargetA", "TargetB")]
        inputs.append("MchInput_"+side)
        for mode, target_space, owner_space in (("Plain", "LOCAL", "LOCAL"), ("Oriented", "LOCAL_OWNER_ORIENT", "LOCAL"), ("World", "WORLD", "WORLD")):
            for index, influence in enumerate((0, .3, .5, 1)):
                name = "{}_{}_{}".format(mode, side, index)
                bone(name, (sign*(.28+.025*index), -.2, .8), (sign*.3, .18, -.45), "OwnerParent_"+side, -sign*1.1)
                operations.append((name, [("TargetA_"+side, target_space, owner_space, influence)]))
        for label, specs in (
            ("LocalStack", [("TargetA_"+side, "LOCAL", "LOCAL", .3), ("TargetB_"+side, "LOCAL_OWNER_ORIENT", "LOCAL", .5)]),
            ("MixedStack", [("TargetA_"+side, "WORLD", "WORLD", .3), ("TargetB_"+side, "LOCAL", "LOCAL", .5)]),
            ("ReverseStack", [("TargetA_"+side, "LOCAL_OWNER_ORIENT", "LOCAL", .5), ("TargetB_"+side, "LOCAL", "LOCAL", .3)]),
        ):
            bone(label+"_"+side, (sign*.4, -.15, .8), (-sign*.15, .27, -.4), "OwnerParent_"+side, sign*.9)
            operations.append((label+"_"+side, specs))
        bone("DrivenParent_"+side, (sign*.7, -.1, .85), (sign*.15, -.2, -.3), "OwnerParent_"+side, -sign*.2)
        operations.append(("DrivenParent_"+side, [("TargetA_"+side, "LOCAL_OWNER_ORIENT", "LOCAL", .5)]))
        bone("ChildInput_"+side, (sign*.82, -.2, .55), (sign*.13, .15, -.2), "DrivenParent_"+side, sign*.3)
        inputs.append("ChildInput_"+side)
        bone("ReadsDrivenChild_"+side, (sign*.2, -.3, .6), (sign*.2, -.1, -.35), "OwnerParent_"+side, sign*.8)
        operations.append(("ReadsDrivenChild_"+side, [("ChildInput_"+side, "LOCAL", "LOCAL", 1)]))
        for mode, target_space in (("PlainMch", "LOCAL"), ("OrientedMch", "LOCAL_OWNER_ORIENT")):
            bone(mode+"_"+side, (sign*.6, -.25, .75), (sign*.2, .12, -.5), "OwnerParent_"+side, -sign*.9)
            operations.append((mode+"_"+side, [("MchInput_"+side, target_space, "LOCAL", .3)]))
    bpy.ops.object.mode_set(mode="OBJECT")
    for owner_name, specs in operations:
        target, target_space, owner_space, influence = specs[0]
        CopyRotationCore.configure(rig, [owner_name], target, influence=influence, target_space=target_space, owner_space=owner_space)
        owner = rig.pose.bones[owner_name]
        for stage, (target, target_space, owner_space, influence) in enumerate(specs[1:], 1):
            c = owner.constraints.new("COPY_ROTATION")
            c.name = "HoTools_COPY_R_Stack_"+str(len(owner.constraints)-1)
            c.target, c.subtarget = rig, target
            c.target_space, c.owner_space, c.mix_mode = target_space, owner_space, "REPLACE"
            c.influence = influence
            owner.bone.hotools_boneprops.auxBone.constraintNames.add().name = c.name
    return rig, inputs, [name for name, _ in operations]


rig, inputs, owners = build()
if operator_mode:
    rig.location = (.7, -.3, .2)
    rig.rotation_euler = (.3, -.4, .7)
    rig.scale = (1.3, 1.3, 1.3)
    bpy.context.view_layer.update()
author_rest_world = {bone.name: rig.matrix_world @ bone.matrix_local for bone in rig.data.bones}
rng = random.Random(20261121)
samples = [("rest", {})]
for index in range(32):
    motions = {}
    for name in inputs:
        amplitude = .35 if name == "Root" else 1.8 if name.startswith("TargetA") else .9
        angles = tuple(rng.uniform(-amplitude, amplitude) for _ in range(3))
        motions[name] = angles
    samples.append(("pose_{:02d}".format(index), motions))


def apply(motions, rest_basis=None):
    for bone in rig.pose.bones:
        bone.matrix_basis = Matrix.Identity(4)
    # Ancestors must be assigned before descendants; input world matrices of a
    # ChildInput whose parent is constrained are read from Blender's actual depsgraph.
    for name in inputs:
        rotation = Euler(motions.get(name, (0, 0, 0)), "XYZ").to_matrix().to_4x4()
        if rest_basis is None or name not in rest_basis:
            rig.pose.bones[name].matrix_basis = rotation
        else:
            old_local, new_local = rest_basis[name]
            rig.pose.bones[name].matrix_basis = new_local.inverted() @ old_local @ rotation @ old_local.inverted() @ new_local
    bpy.context.view_layer.update()


def pose_matrix(name):
    return rig.matrix_world @ rig.pose.bones[name].matrix if operator_mode else rig.pose.bones[name].matrix


def sample_current():
    return [{"name": bone.name, "matrix": flat(pose_matrix(bone.name))} for bone in rig.pose.bones]


authoring = capture_armature(rig)


def explicit_test_stacks(document):
    """Author extra atomic v4 semantics for runtime stack tests, explicitly.

    The current copyR UI owns one instance per owner. Its first-stage record and
    all 32 non-stack owners pass through production capture/translate/binding.
    Extra Blender stack constraints are sampled as real facts, then this fixture
    authors their semantic records; this is not presented as multi-copyR UI.
    """
    added = []
    for source in document["sources"]:
        if not source["constraint"]["name"].startswith("HoTools_COPY_R_Stack_"):
            continue
        source_id = source["sourceId"]
        semantic_id = "fixture_stack_"+source_id
        document["semantics"].append({"semanticId": semantic_id, "semanticType": "COPY_ROTATION", "semanticVersion": 1,
            "ownerBone": source["ownerBone"], "sourceIds": [source_id], "ruleId": "group.copy_r", "ruleVersion": 1,
            "evidence": "EXPLICIT", "parameters": {"auxType": "COPY_R", "generatorId": "hotools.aux.copy_r", "ownsBone": False,
                "testOnlyExplicitStack": True}})
        for implementation in implementations_for("COPY_ROTATION"):
            document["implementationBindings"].append({"semanticId": semantic_id, "backendId": implementation["backendId"],
                "implementationId": implementation["id"], "contractVersion": implementation["contractVersion"],
                "selection": "CANDIDATE", "fallbackPolicy": "EXACT_ONLY"})
        added.append(source_id)
    document["diagnostics"] = [row for row in document["diagnostics"] if not (row["status"] == "UNKNOWN" and set(row.get("sourceIds", ())).issubset(added))]
    document["fixtureAuthorship"] = {"singleCopyR": "Production configure/capture/translate/binding path",
        "extraStackStages": "Explicit test-authored v4 atomic semantic records; not a multi-instance copyR UI feature",
        "explicitStackSourceIds": added}
    assert not document["diagnostics"], document["diagnostics"]
    return document


translated = explicit_test_stacks(translate(authoring))
(out / "authoring_v4.json").write_text(codec.dumps(translated), encoding="utf-8")
before = []
for label, motions in samples:
    apply(motions)
    before.append({"name": label, "inputs": [{"name": name, "matrix": flat(pose_matrix(name))} for name in inputs], "expected": sample_current()})


def export_operator_variants():
    """Export both FBXs through the actual production HoFBX operator.

    Only static final bind matrices are observed at getParams immediately before
    the FBX writer. Dynamic expected poses always come from the earlier actual
    Blender constraint evaluation, never the Unity algorithm or fit transform.
    """
    captured = {}
    original_get_params = OP_FinalFBXExport.getParams

    def observe_final(self, context, report_errors=True):
        current = next(obj for obj in context.selected_objects if obj.type == "ARMATURE")
        captured[Path(self.filepath).stem] = {
            "bones": {bone.name: current.matrix_world @ bone.matrix_local for bone in current.data.bones},
            "context": ConstraintIRExporter._binding_context(current, list(current.data.bones)),
        }
        return original_get_params(self, context, report_errors)

    OP_FinalFBXExport.getParams = observe_final
    bpy.utils.register_class(OP_FinalFBXExport)
    try:
        for label, mch in (("Raw", False), ("Mch", True)):
            current = bpy.data.objects["CopyRLocal"]
            for bone in current.pose.bones:
                bone.matrix_basis = Matrix.Identity(4)
            for name in ("MchInput_L", "MchInput_R"):
                current.data.bones[name].hotools_boneprops.generateMCH = mch
            bpy.context.view_layer.objects.active = current
            bpy.ops.object.select_all(action="DESELECT")
            current.select_set(True)
            bpy.context.view_layer.update()
            target = out / (label+".fbx")
            assert bpy.ops.ho.final_fbx_export("EXEC_DEFAULT", filepath=str(target),
                rigConstraintIRVersion="4", exportUnityMetadata=False, exportBoneConstraint=True,
                exportBoneCollection=False, exportHumanoidMapping=False, exportBsCorrective=False,
                addLeafBones=False, generateMCHBones=mch, applyArmaturePose=False,
                fixObjectTransform=True, applyExportConstraints=False) == {"FINISHED"}
            sidecar = next((out/"HoFBX").glob(label+"_*_constraint.json"))
            exported = codec.loads(sidecar.read_text(encoding="utf-8"))
            exported = explicit_test_stacks(exported)
            (out/(label+"_v4.json")).write_text(codec.dumps(exported),encoding="utf-8")
            final = captured[label]
            actual_context = final["context"]
            serialized_context = exported["bindings"]["bindingContext"]
            assert actual_context["objectMatrix"]==serialized_context["objectMatrix"], "final object matrix sampled before last correction"
            actual_bones={row["boneName"]:row for row in actual_context["bones"]}
            for row in serialized_context["bones"]:
                assert row["restMatrix"]==actual_bones[row["boneName"]]["restMatrix"], "final rest sampled before last correction"
                assert row["inheritRotation"]==actual_bones[row["boneName"]]["inheritRotation"] is True
            rest_rows = [{"name":name,"matrix":flat(matrix)} for name,matrix in final["bones"].items()]
            actual_samples=[]
            final_map = {row["exportBone"]:row["sourceBone"] for row in exported["bindings"]["boneMap"]}
            for sample in before:
                source_pose = {row["name"]:Matrix([row["matrix"][i:i+4] for i in range(0,16,4)]) for row in sample["expected"]}
                expected={}
                for name, bind in final["bones"].items():
                    source_name = name if name in author_rest_world else final_map[name]
                    expected[name]=source_pose[source_name] @ author_rest_world[source_name].inverted() @ bind
                actual_samples.append({"name":sample["name"],"inputs":[{"name":name,"matrix":flat(expected[name])} for name in inputs],
                    "expected":[{"name":name,"matrix":flat(matrix)} for name,matrix in expected.items()]})
            save(label+"_samples.json", {"variant":label,"blenderVersion":bpy.app.version_string,"bones":rest_rows,
                "ownerNames":owners,"inputNames":inputs,"samples":actual_samples,"authoringPreprocessMaxMatrixError":0,
                "exportRoute":"ACTUAL_HOFBX_OPERATOR_NONIDENTITY_OBJECT","sampleSpace":"BLENDER_WORLD",
                "originalObjectMatrix":authoring["sourceContext"]["objectMatrix"]})
            print("COPYR_OPERATOR_FINAL_BINDING_OK",label,len(exported["semantics"]))
    finally:
        bpy.utils.unregister_class(OP_FinalFBXExport)
        OP_FinalFBXExport.getParams=original_get_params


def export_variant(label, rest_basis=None, *, mch_map=None):
    apply({}, rest_basis)
    # The unmodified authoring facts plus final binding overlay are available
    # for the real v4 planner once its PLANNED local contracts are released.
    final_v4=explicit_test_stacks(build_export_document(authoring,rig,mch_map=mch_map))
    (out/(label+"_v4.json")).write_text(codec.dumps(final_v4),encoding="utf-8")
    ir = ConstraintIRExporter.export_to_dict(rig)
    ir["bindingContext"]["fbxBoneAxes"] = "Y_X"
    # The numerical fixture targets the production direct evaluator. Keep raw
    # Copy Rotation records direct even when legacy Aux ownership claimed them.
    ir["knownConstraints"] = [record for record in ir["knownConstraints"] if record["relationType"] == "MCH_BINDING"]
    for owner_name in owners:
        owner = rig.pose.bones[owner_name]
        for index, constraint in enumerate(owner.constraints):
            ir["knownConstraints"].append({"ownerBone": owner_name, "relationType": "DIRECT_CONSTRAINT", "constraint": ConstraintIRExporter._raw_constraint(constraint, rig, index).to_dict()})
    ir["auxBones"] = [row for row in ir["auxBones"] if row["auxType"] == "MCH"]
    ir["unknownConstraints"] = []
    ir["aimBindings"] = []
    save(label+"_runtime_ir.json", ir)
    rests = [{"name": bone.name, "matrix": flat(bone.matrix_local)} for bone in rig.data.bones]
    actual_samples = []
    max_authoring_error = 0
    for index, (name, motions) in enumerate(samples):
        apply(motions, rest_basis)
        actual = sample_current()
        expected_by_name = {row["name"]: row["matrix"] for row in before[index]["expected"]}
        for row in actual:
            if row["name"] in owners:
                max_authoring_error = max(max_authoring_error, max(abs(a-b) for a,b in zip(row["matrix"], expected_by_name[row["name"]])))
        actual_samples.append({"name": name, "inputs": [{"name": bone_name, "matrix": flat(rig.pose.bones[bone_name].matrix)} for bone_name in inputs], "expected": actual})
    save(label+"_samples.json", {"variant": label, "blenderVersion": bpy.app.version_string, "bones": rests, "ownerNames": owners, "inputNames": inputs, "samples": actual_samples, "authoringPreprocessMaxMatrixError": max_authoring_error})
    assert max_authoring_error < 2e-5, (label, max_authoring_error)
    apply({}, rest_basis)
    # Temporarily mute (rather than delete) constraints to export the final raw
    # rest skeleton, exactly as the JSON-carried HoFBX constraint contract needs.
    muted = [(constraint, constraint.mute) for bone in rig.pose.bones for constraint in bone.constraints]
    for constraint, _mute in muted:
        constraint.mute = True
    bpy.context.view_layer.update()
    bpy.ops.export_scene.fbx(filepath=str(out/(label+".fbx")), use_selection=True, object_types={"ARMATURE"},
        global_scale=1, apply_unit_scale=True, apply_scale_options="FBX_SCALE_ALL", use_space_transform=True,
        bake_space_transform=False, add_leaf_bones=False, primary_bone_axis="Y", secondary_bone_axis="X",
        use_armature_deform_only=False, armature_nodetype="NULL", bake_anim=False, axis_forward="-Z", axis_up="Y")
    for constraint, mute in muted:
        constraint.mute = mute
    bpy.context.view_layer.update()


if operator_mode:
    export_operator_variants()
    print("COPY_R_V4_OPERATOR_FIXTURE_OK",len(owners),len(samples))
else:
    export_variant("Raw")
    apply({})
    for name in ("MchInput_L", "MchInput_R"):
        rig.data.bones[name].hotools_boneprops.generateMCH = True
    old_locals = {name: rig.data.bones[name].matrix_local.copy() for name in ("MchInput_L", "MchInput_R")}
    mch_map = FBXExporter.clear_armatures_bone_rotation([rig], [rig], rig)[rig.name]
    rest_basis = {name: (old_locals[name], rig.data.bones[name].matrix_local.copy()) for name in mch_map}
    export_variant("Mch", rest_basis, mch_map=mch_map)
    print("COPY_R_V4_FIXTURE_OK", len(owners), len(samples), json.dumps(mch_map))
