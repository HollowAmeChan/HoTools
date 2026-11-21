"""Selected Empty groups and required ancestors survive actual HoFBX output."""
import json
import sys
from math import radians
from pathlib import Path
from tempfile import TemporaryDirectory

import bpy
from mathutils import Euler, Matrix, Vector
from io_scene_fbx import parse_fbx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Exporter.FbxExporter import FBXExporter, OP_FinalFBXExport

RESULTS = []
WRITER = {}
ORIGINAL_PARAMS = OP_FinalFBXExport.getParams


def flatten(matrix):
    return [float(x) for row in matrix for x in row]


def snapshot():
    return {o.name: (o.type, o.parent.name if o.parent else None, flatten(o.matrix_world),
                     flatten(o.matrix_parent_inverse), o.hide_get(), o.hide_viewport,
                     o.select_get()) for o in bpy.context.scene.objects}


def observe(self, context, report_errors=True):
    WRITER.clear()
    WRITER.update({o.name: o.matrix_local.copy() for o in context.selected_objects})
    return ORIGINAL_PARAMS(self, context, report_errors)


def setup():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rig = bpy.data.objects.new("Rig", bpy.data.armatures.new("RigData"))
    bpy.context.collection.objects.link(rig)
    rig.select_set(True); bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    bone = rig.data.edit_bones.new("Root"); bone.head = (0, 0, 0); bone.tail = (0, 0, 1)
    bpy.ops.object.mode_set(mode="OBJECT")
    def empty(name, parent=None):
        obj = bpy.data.objects.new(name, None); bpy.context.collection.objects.link(obj); obj.parent = parent
        return obj
    a = empty("_PART_衣服", rig); a.location = (.3, -.2, .4); a.rotation_euler = (.2, -.3, .1); a.scale = (1.2,) * 3
    b = empty("_PART_Details", a); b.location = (-.1, .2, .15); b.rotation_euler = (-.1, .2, -.15)
    mesh = bpy.data.meshes.new("SkinData"); mesh.from_pydata([(0, 0, 0), (.2, 0, 0), (0, .2, .3)], [], [(0, 1, 2)])
    skin = bpy.data.objects.new("Skin", mesh); bpy.context.collection.objects.link(skin); skin.parent = b; skin.location = (.1, .05, .2)
    skin.vertex_groups.new(name="Root").add([0, 1, 2], 1, "REPLACE")
    skin.modifiers.new("Armature", "ARMATURE").object = rig
    skin.shape_key_add(name="Basis"); skin.shape_key_add(name="Shape").data[1].co.z += .1
    empty("UnselectedSibling", a); loose = empty("Loose")
    camera = bpy.data.objects.new("CameraExcluded", bpy.data.cameras.new("CameraData")); bpy.context.collection.objects.link(camera)
    light = bpy.data.objects.new("LightExcluded", bpy.data.lights.new("LightData", "POINT")); bpy.context.collection.objects.link(light)
    bpy.context.view_layer.update()
    return rig, a, b, skin, loose, camera, light


def inspect(path, expected_names, expected_parents):
    root, _ = parse_fbx.parse(str(path))
    objects = next(e for e in root.elems if e.id == b"Objects")
    models = {e.props[1].split(b"\x00\x01")[0].decode("utf-8"): e for e in objects.elems if e.id == b"Model"}
    assert set(models) == set(expected_names), (path.name, set(models), expected_names)
    by_id = {node.props[0]: name for name, node in models.items()}
    connections = next(e for e in root.elems if e.id == b"Connections")
    parents = {by_id[c.props[1]]: by_id.get(c.props[2]) for c in connections.elems
               if c.id == b"C" and c.props[0] == b"OO" and c.props[1] in by_id and (c.props[2] == 0 or c.props[2] in by_id)}
    for child, parent in expected_parents.items():
        assert parents[child] == parent, (path.name, child, parents, parent)
    if "Skin" in models:
        # FBX keeps Mesh->Empty, so this is a LOCAL matrix, never mesh world.
        properties = next(e for e in models["Skin"].elems if e.id == b"Properties70")
        values = {e.props[0]: e.props[4:] for e in properties.elems}
        rotation = Euler(tuple(radians(v) for v in values[b"Lcl Rotation"]), "XYZ").to_quaternion()
        local = Matrix.LocRotScale(Vector(values[b"Lcl Translation"]), rotation, Vector(values[b"Lcl Scaling"]))
        assert max(abs(x-y) for x, y in zip(flatten(local), flatten(WRITER["Skin"]))) < 2e-5, (path.name, "skin local/world mismatch")
        assert sum(e.id == b"Geometry" and e.props[2] == b"Shape" for e in objects.elems) == 1


def run(directory, label, fix=False):
    rig, a, b, skin, loose, camera, light = setup()
    if label == "explicit": selected = [rig, a, b, skin, loose, camera, light]
    elif label == "empty_only": selected = [loose]
    elif label == "rig_only": selected = [rig]
    else: selected = [rig, skin]
    bpy.ops.object.select_all(action="DESELECT")
    for obj in selected: obj.select_set(True)
    bpy.context.view_layer.objects.active = selected[0]
    if label == "hidden_ancestor": a.hide_set(True); b.hide_set(True)
    bpy.context.view_layer.update()
    before, active = snapshot(), bpy.context.view_layer.objects.active.name
    path = directory / (label + ("_fixed" if fix else "") + ".fbx")
    result = bpy.ops.ho.final_fbx_export("EXEC_DEFAULT", filepath=str(path), fixObjectTransform=fix,
        addLeafBones=False, exportUnityMetadata=False, exportBoneConstraint=False,
        exportBoneCollection=False, exportHumanoidMapping=False, exportBsCorrective=False)
    assert result == {"FINISHED"}
    assert snapshot() == before and bpy.context.view_layer.objects.active.name == active, (label, "undo changed source")
    if label == "empty_only": names, parents = {"Loose"}, {"Loose": None}
    elif label == "rig_only": names, parents = {"Rig", "Root"}, {"Rig": None, "Root": "Rig"}
    else:
        names = {"Rig", "Root", "_PART_衣服", "_PART_Details", "Skin"}
        parents = {"_PART_衣服": "Rig", "_PART_Details": "_PART_衣服", "Skin": "_PART_Details"}
        if label == "explicit": names.add("Loose"); parents["Loose"] = None
    inspect(path, names, parents)
    RESULTS.append(path.stem)


bpy.utils.register_class(OP_FinalFBXExport)
OP_FinalFBXExport.getParams = observe
try:
    with TemporaryDirectory(prefix="hotools_empty_hierarchy_") as directory:
        for label in ("explicit", "ancestors", "hidden_ancestor", "empty_only", "rig_only"):
            for fix in (False, True): run(Path(directory), label, fix)
    # Camera selection must not pull its unselected Empty parent into scope.
    rig, a, b, skin, loose, camera, light = setup(); camera.parent = loose
    assert FBXExporter.resolve_export_selection([camera], bpy.context.view_layer) == [camera]
    loose.instance_type = "COLLECTION"
    loose.instance_collection = bpy.data.collections.new("InstancePayload")
    skin.parent = loose
    assert FBXExporter.resolve_export_selection([rig, skin], bpy.context.view_layer) == [rig, skin]
    assert FBXExporter.resolve_export_selection([rig, skin, loose], bpy.context.view_layer) == [rig, skin, loose]
finally:
    OP_FinalFBXExport.getParams = ORIGINAL_PARAMS
    bpy.utils.unregister_class(OP_FinalFBXExport)
print("FBX_EMPTY_HIERARCHY_OK", bpy.app.version_string, json.dumps(RESULTS))
