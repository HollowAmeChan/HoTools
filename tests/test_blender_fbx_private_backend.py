"""Compare private and installed official exporters on disposable Blender scenes.

Run with Blender --background --factory-startup --python-exit-code 1 --python ...
An optional directory after -- retains both FBX files for Unity verification.
"""

from collections import Counter
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import bpy
from mathutils import Euler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from Exporter.FbxExporter.backend import export_fbx
from Exporter.FbxExporter import OP_FinalFBXExport
from io_scene_fbx import parse_fbx


class Reporter:
    def report(self, kinds, message):
        if "ERROR" in kinds:
            raise AssertionError(message)
        print(kinds, message)


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for rig_index in range(2):
        data = bpy.data.armatures.new("RigData%d" % rig_index)
        rig = bpy.data.objects.new("Rig%d" % rig_index, data)
        bpy.context.collection.objects.link(rig)
        bpy.context.view_layer.objects.active = rig
        rig.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        for i in range(14):
            bone = data.edit_bones.new("Bone%02d" % i)
            bone.head, bone.tail = (0, 0, i * .2), (0, 0, (i + 1) * .2)
            if i:
                bone.parent = data.edit_bones["Bone%02d" % (i - 1)]
        bpy.ops.object.mode_set(mode="OBJECT")
        data.bones[-1].use_deform = False
        rig.location = (rig_index * 3.1, .3, -.2)
        rig.rotation_euler = Euler((.1, .2, -.1))
        rig.scale = (1.1, .9, 1.2)
        rig.pose.bones["Bone00"].rotation_mode = "XYZ"
        rig.pose.bones["Bone00"].rotation_euler.x = .25
        for mesh_index in range(2):
            mesh = bpy.data.meshes.new("Mesh%d_%dData" % (rig_index, mesh_index))
            mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)], [], [(0, 1, 2), (0, 2, 3)])
            mesh.update()
            obj = bpy.data.objects.new("Mesh%d_%d" % (rig_index, mesh_index), mesh)
            bpy.context.collection.objects.link(obj)
            obj.parent = rig
            obj.location = (.15 * mesh_index, .2, .1)
            obj.rotation_euler = (.1, 0, .05)
            uv = mesh.uv_layers.new(name="UVMap")
            for loop in mesh.loops:
                co = mesh.vertices[loop.vertex_index].co
                uv.data[loop.index].uv = (co.x, co.z)
            color = mesh.color_attributes.new(name="Color", type="FLOAT_COLOR", domain="CORNER")
            for value in color.data:
                value.color = (.2, .4, .8, 1)
            for name, indices in (("Bone00", [0, 1]), ("Bone02", [2, 3])):
                obj.vertex_groups.new(name=name).add(indices, 1.0, "REPLACE")
            modifier = obj.modifiers.new("Skin", "ARMATURE")
            modifier.object = rig
            obj.shape_key_add(name="Basis")
            smile = obj.shape_key_add(name="Smile")
            smile.data[2].co.z += .17
    bpy.context.view_layer.update()
    for obj in bpy.context.scene.objects:
        obj.select_set(True)


def canonical(node):
    def value(prop):
        if hasattr(prop, "tolist"):
            return tuple(prop.tolist())
        return prop
    return node.id, bytes(node.props_type), tuple(value(p) for p in node.props), tuple(canonical(c) for c in node.elems)


def section(root, name):
    return next(c for c in root.elems if c.id == name)


def compare(before_path, after_path):
    before, v1 = parse_fbx.parse(str(before_path))
    after, v2 = parse_fbx.parse(str(after_path))
    assert v1 == v2 == 7400
    old = {o.props[0]: o for o in section(before, b"Objects").elems}
    new = {o.props[0]: o for o in section(after, b"Objects").elems}
    removed = old.keys() - new.keys()
    assert removed
    assert not new.keys() - old.keys()
    for uid in removed:
        obj = old[uid]
        assert (obj.id, obj.props[2]) in {(b"Pose", b"BindPose"), (b"Deformer", b"Cluster")}
    for uid, obj in new.items():
        if obj.id != b"Pose":
            assert canonical(obj) == canonical(old[uid]), (uid, obj.id, obj.props[1])
    old_connections = [canonical(c) for c in section(before, b"Connections").elems
                       if c.props[1] not in removed and c.props[2] not in removed]
    assert old_connections == [canonical(c) for c in section(after, b"Connections").elems]
    def poses(root):
        result = set()
        for obj in section(root, b"Objects").elems:
            if obj.id != b"Pose":
                continue
            nodes = [n for n in obj.elems if n.id == b"PoseNode"]
            assert section(obj, b"NbPoseNodes").props[0] == len(nodes)
            result.update(canonical(n) for n in nodes)
        return result
    assert poses(before) == poses(after)
    counts = Counter(o.id for o in new.values())
    for entry in section(after, b"Definitions").elems:
        if entry.id == b"ObjectType" and entry.props[0] in (b"Pose", b"Deformer"):
            assert section(entry, b"Count").props[0] == counts[entry.props[0]]
    assert section(section(after, b"Definitions"), b"Count").props[0] == len(new) + 1
    models = [o for o in new.values() if o.id == b"Model"]
    assert sum(o.props[2] == b"LimbNode" for o in models) == 28
    assert sum(o.id == b"Geometry" and o.props[2] == b"Shape" for o in new.values()) == 4
    print("PRIVATE_BACKEND_EQUIVALENT", after_path.name, "removed", len(removed), "objects", flush=True)


def run(directory):
    build_scene()
    common = OP_FinalFBXExport.getParams(SimpleNamespace(filepath=""), bpy.context)
    common.pop("filepath")
    common["use_mesh_modifiers"] = False
    for label, changes in (("axes", {}), ("no_axis_conversion", {"use_space_transform": False}),
                           ("centimeters", {"global_scale": .01, "apply_scale_options": "FBX_SCALE_ALL"})):
        parameters = dict(common, **changes)
        original, optimized = directory / (label + "_official.fbx"), directory / (label + "_private.fbx")
        assert bpy.ops.export_scene.fbx(filepath=str(original), **parameters) == {"FINISHED"}
        assert export_fbx(Reporter(), bpy.context, filepath=str(optimized), **parameters) == {"FINISHED"}
        compare(original, optimized)
    print("FBX_PRIVATE_BACKEND_OK", bpy.app.version_string, flush=True)


if __name__ == "__main__":
    if "--" in sys.argv:
        directory = Path(sys.argv[sys.argv.index("--") + 1])
        directory.mkdir(parents=True, exist_ok=True)
        run(directory)
    else:
        with TemporaryDirectory(prefix="hotools_private_fbx_") as directory:
            run(Path(directory))
