"""Read-only investigation of HoTools' current UV alignment and Blender APIs.

Run in an isolated factory-startup Blender process, never in a user's scene:
  blender --background --factory-startup --python-exit-code 1 \
      --python tools/probe_uv_compat.py

This is a diagnostic baseline, NOT acceptance tests for the planned UV tools.
The observations intentionally record existing defects without fixing them.
"""

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

import bmesh
import bpy


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_align():
    # Import only the alignment module; avoid unrelated addon registration.
    name = "hotools_uv_probe"
    package = types.ModuleType(name)
    package.__path__ = [str(ROOT / "HoPie")]
    sys.modules[name] = package
    spec = importlib.util.spec_from_file_location(
        name + ".AlignPie", ROOT / "HoPie" / "AlignPie.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ALIGN = load_align()
REPORT = {"blender": bpy.app.version_string, "observations": {}}


def clear_scene():
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def make_mesh(name, with_uv=True):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
        [], [(0, 1, 2), (0, 2, 3)],
    )
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    if with_uv:
        uv = mesh.uv_layers.new(name="UVMap")
        for item, coordinate in zip(uv.data, [
            (.1, .2), (.8, .2), (.8, .9),
            (2.1, .2), (2.8, .9), (2.1, .9),
        ]):
            item.uv = coordinate
    return obj


def enter_edit(objects, sync=False):
    bpy.context.view_layer.objects.active = objects[0]
    bpy.context.scene.tool_settings.use_uv_select_sync = sync
    bpy.context.scene.tool_settings.mesh_select_mode = (True, False, False)
    bpy.context.scene.tool_settings.uv_select_mode = "VERTEX"
    bpy.ops.object.mode_set(mode="EDIT")
    for obj in objects:
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            face.select_set(True)
        bm.select_flush_mode()
        uv = bm.loops.layers.uv.active
        if uv:
            if hasattr(bm, "uv_select_sync_from_mesh"):
                bm.uv_select_sync_from_mesh()
            else:
                for face in bm.faces:
                    for loop in face.loops:
                        loop[uv].select = True
                        loop[uv].select_edge = True
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)


def coordinates(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    uv = bm.loops.layers.uv.active
    return [tuple(loop[uv].uv) for face in bm.faces for loop in face.loops]


def run_alignment():
    area = bpy.context.screen.areas[0]
    old_type = area.type
    area.type = "IMAGE_EDITOR"
    area.ui_type = "UV"
    try:
        region = next(item for item in area.regions if item.type == "WINDOW")
        with bpy.context.temp_override(area=area, region=region):
            return {"result": sorted(bpy.ops.ho.align_uv(axis="U", type="MIN"))}
    except Exception as exc:
        return {"error": type(exc).__name__, "message": str(exc)}
    finally:
        area.type = old_type


class APIContractTests(unittest.TestCase):
    def setUp(self):
        self.bm = bmesh.new()
        verts = [self.bm.verts.new(co) for co in [(0, 0, 0), (1, 0, 0), (0, 1, 0)]]
        self.face = self.bm.faces.new(verts)
        self.uv = self.bm.loops.layers.uv.new()
        self.loop = self.face.loops[0]

    def tearDown(self):
        self.bm.free()

    def test_selection_api_generation(self):
        modern = bpy.app.version >= (5, 0, 0)
        self.assertEqual(hasattr(self.loop[self.uv], "select"), not modern)
        self.assertEqual(hasattr(self.loop, "uv_select_vert"), modern)

    def test_coordinate_and_pin_contract(self):
        self.loop[self.uv].uv = (1.25, -0.5)
        self.loop[self.uv].pin_uv = True
        self.assertEqual(tuple(self.loop[self.uv].uv), (1.25, -0.5))
        self.assertTrue(self.loop[self.uv].pin_uv)

    def test_selection_round_trip(self):
        if hasattr(self.loop, "uv_select_vert_set"):
            self.bm.uv_select_sync_from_mesh()
            self.loop.uv_select_vert_set(True)
            self.assertTrue(self.loop.uv_select_vert)
            self.loop.uv_select_vert_set(False)
            self.assertFalse(self.loop.uv_select_vert)
        else:
            self.loop[self.uv].select = True
            self.assertTrue(self.loop[self.uv].select)
            self.loop[self.uv].select = False
            self.assertFalse(self.loop[self.uv].select)

    def test_selection_storage_across_uv_layers(self):
        initial_name = self.uv.name
        self.bm.loops.layers.uv.new("OtherUV")
        # Adding custom-data layers can invalidate loop wrappers in both versions.
        self.bm.faces.ensure_lookup_table()
        self.face = self.bm.faces[0]
        self.loop = self.face.loops[0]
        self.uv = self.bm.loops.layers.uv.get(initial_name)
        other = self.bm.loops.layers.uv.get("OtherUV")
        if hasattr(self.loop, "uv_select_vert_set"):
            self.bm.uv_select_sync_from_mesh()
            self.loop.uv_select_vert_set(True)
            self.assertTrue(self.loop.uv_select_vert)
            self.assertFalse(hasattr(self.loop[other], "select"))
        else:
            self.loop[self.uv].select = True
            self.loop[other].select = False
            self.assertTrue(self.loop[self.uv].select)
            self.assertFalse(self.loop[other].select)

    def test_modern_sync_validity(self):
        if not hasattr(self.bm, "uv_select_sync_valid"):
            self.skipTest("4.5 does not store modern UV sync validity")
        self.assertFalse(self.bm.uv_select_sync_valid)
        self.face.select_set(True)
        self.bm.uv_select_sync_from_mesh()
        self.assertTrue(self.bm.uv_select_sync_valid)
        self.assertTrue(all(loop.uv_select_vert for loop in self.face.loops))


def observations():
    data = REPORT["observations"]
    clear_scene()
    first, second = make_mesh("Active"), make_mesh("Other")
    enter_edit([first, second])
    before = [coordinates(first), coordinates(second)]
    data["sync_off_multi_object"] = run_alignment()
    data["sync_off_multi_object"].update(
        active_changed=coordinates(first) != before[0],
        other_changed=coordinates(second) != before[1],
    )

    clear_scene()
    obj = make_mesh("HiddenFace")
    enter_edit([obj], sync=True)
    bm = bmesh.from_edit_mesh(obj.data)
    # Hide the other face, but leave shared vertices selected by the visible face.
    bm.faces[1].hide_set(True)
    bm.faces[0].select_set(True)
    before = coordinates(obj)
    data["sync_on_hidden_face"] = run_alignment()
    data["sync_on_hidden_face"]["hidden_face_changed"] = coordinates(obj)[3:] != before[3:]

    clear_scene()
    obj = make_mesh("NoUV", with_uv=False)
    enter_edit([obj], sync=True)
    data["missing_uv"] = run_alignment()
    data["missing_uv"]["uv_layer_created"] = bool(bmesh.from_edit_mesh(obj.data).loops.layers.uv.active)

    if bpy.app.version >= (5, 0, 0):
        clear_scene()
        obj = make_mesh("SplitUV")
        enter_edit([obj], sync=True)
        bm = bmesh.from_edit_mesh(obj.data)
        loops = [loop for face in bm.faces for loop in face.loops]
        bm.uv_select_foreach_set(False, loop_verts=loops, loop_edges=loops, faces=list(bm.faces))
        bm.faces[0].loops[0].uv_select_vert_set(True)
        bm.faces[0].loops[1].uv_select_vert_set(True)
        bm.uv_select_flush_mode()
        bm.uv_select_sync_to_mesh()
        selected_before = [index for index, loop in enumerate(loops) if loop.uv_select_vert]
        before = coordinates(obj)
        data["sync_on_precise_uv_selection"] = run_alignment()
        data["sync_on_precise_uv_selection"].update(
            sync_valid=bm.uv_select_sync_valid,
            selected_loop_indices=selected_before,
            changed_loop_indices=[index for index, (a, b) in enumerate(zip(before, coordinates(obj))) if a != b],
        )
    clear_scene()


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(APIContractTests)
    )
    REPORT["api_tests"] = {"run": result.testsRun, "skipped": len(result.skipped), "passed": result.wasSuccessful()}
    bpy.utils.register_class(ALIGN.AlignUV)
    try:
        observations()
    finally:
        bpy.utils.unregister_class(ALIGN.AlignUV)
    output = ROOT / "_research" / "uv" / ("probe_" + bpy.app.version_string.split()[0] + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(REPORT, ensure_ascii=False, indent=2))
    if not result.wasSuccessful():
        raise SystemExit(1)
