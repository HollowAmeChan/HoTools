import importlib.util
import sys
import unittest
from pathlib import Path

import bmesh
import bpy


ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

PACKAGE_NAME = 'hotools_hopie_new_pies_test'


def load_hopie():
    if PACKAGE_NAME in sys.modules:
        return sys.modules[PACKAGE_NAME]
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        ADDON_ROOT / 'HoPie' / '__init__.py',
        submodule_search_locations=[str(ADDON_ROOT / 'HoPie')],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


class NewPieRegistrationTests(unittest.TestCase):
    def test_registration_and_keymaps(self):
        hopie = load_hopie()
        hopie.register()
        try:
            hopie.set_selection_mode_pie_enabled(True)
            hopie.set_delete_merge_pie_enabled(True)
            ids = {item.bl_idname for item in hopie.selection_mode_pie.SELECTION_MODE_PIE_CLASSES}
            self.assertEqual(ids, {'HO_MT_selection_mode_pie'})
            ids = {item.bl_idname for item in hopie.delete_merge_pie.DELETE_MERGE_PIE_CLASSES}
            self.assertEqual(ids, {
                'ho.merge_to_first',
                'ho.merge_to_last',
                'HO_MT_delete_merge_pie',
            })

            self.assertEqual(len(hopie.selection_mode_pie_keymaps), 1)
            selection_keymap, selection_item = hopie.selection_mode_pie_keymaps[0]
            self.assertEqual(selection_keymap.name, 'Window')
            self.assertEqual(selection_item.type, 'W')
            self.assertEqual(selection_item.properties.name, 'HO_MT_selection_mode_pie')

            self.assertEqual(len(hopie.delete_merge_pie_keymaps), 1)
            delete_keymap, delete_item = hopie.delete_merge_pie_keymaps[0]
            self.assertEqual(delete_keymap.name, 'Window')
            self.assertEqual(delete_item.type, 'X')
            self.assertEqual(delete_item.properties.name, 'HO_MT_delete_merge_pie')
        finally:
            hopie.unregister()

        self.assertEqual(hopie.preference_keymaps(), [])

    def test_merge_to_selection_ends(self):
        hopie = load_hopie()
        hopie.register()
        try:
            hopie.set_delete_merge_pie_enabled(True)
            for operator_id, expected_x in (
                ('ho.merge_to_first', 1.0),
                ('ho.merge_to_last', 3.0),
            ):
                mesh = bpy.data.meshes.new(f'{operator_id}_mesh')
                mesh.from_pydata([(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)], [], [])
                obj = bpy.data.objects.new(f'{operator_id}_object', mesh)
                bpy.context.collection.objects.link(obj)
                bpy.context.view_layer.objects.active = obj
                obj.select_set(True)
                bpy.ops.object.mode_set(mode='EDIT')
                bm = bmesh.from_edit_mesh(mesh)
                selected = list(bm.verts)
                for vert in selected:
                    vert.select = True
                bm.select_history.clear()
                bm.select_history.add(selected[0])
                bm.select_history.add(selected[1])
                bm.select_history.add(selected[2])
                bmesh.update_edit_mesh(mesh)

                self.assertEqual(getattr(bpy.ops.ho, operator_id.rsplit('.', 1)[1])(), {'FINISHED'})
                bpy.ops.object.mode_set(mode='OBJECT')
                self.assertEqual(len(mesh.vertices), 1)
                self.assertAlmostEqual(mesh.vertices[0].co.x, expected_x)
                bpy.data.objects.remove(obj, do_unlink=True)
        finally:
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            hopie.unregister()


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NewPieRegistrationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
