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


def keymap_items_for_menu(menu_name):
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    return [
        item
        for keymap in keyconfig.keymaps
        for item in keymap.keymap_items
        if item.idname == 'wm.call_menu_pie'
        and getattr(item.properties, 'name', '') == menu_name
    ]


class NewPieRegistrationTests(unittest.TestCase):
    def test_registration_and_keymaps(self):
        hopie = load_hopie()
        hopie.register()
        try:
            hopie.set_pie_enabled('selection_mode', True)
            hopie.set_pie_enabled('delete_merge', True)
            ids = {item.bl_idname for item in hopie.SelectionModePie.SELECTION_MODE_PIE_CLASSES}
            self.assertEqual(ids, {'HO_MT_selection_mode_pie'})
            ids = {item.bl_idname for item in hopie.DeleteMergePie.DELETE_MERGE_PIE_CLASSES}
            self.assertEqual(ids, {
                'ho.merge_to_first',
                'ho.merge_to_last',
                'HO_MT_delete_merge_pie',
            })

            self.assertEqual(len(hopie.selection_mode_pie_keymaps), 1)
            selection_keymap, selection_item = hopie.selection_mode_pie_keymaps[0]
            self.assertEqual(selection_keymap.name, '3D View Generic')
            self.assertEqual(selection_keymap.space_type, 'VIEW_3D')
            self.assertEqual(selection_item.type, 'W')
            self.assertEqual(selection_item.properties.name, 'HO_MT_selection_mode_pie')
            self.assertEqual(selection_keymap.keymap_items[0].id, selection_item.id)

            self.assertEqual(len(hopie.delete_merge_pie_keymaps), 1)
            delete_keymap, delete_item = hopie.delete_merge_pie_keymaps[0]
            self.assertEqual(delete_keymap.name, 'Mesh')
            self.assertEqual(delete_item.type, 'X')
            self.assertEqual(delete_item.properties.name, 'HO_MT_delete_merge_pie')
            self.assertEqual(delete_keymap.keymap_items[0].id, delete_item.id)
        finally:
            hopie.unregister()

        self.assertEqual(hopie.preference_keymaps(), [])

    def test_merge_skips_without_active_vertex(self):
        hopie = load_hopie()
        hopie.register()
        hopie.set_pie_enabled('delete_merge', True)
        mesh = bpy.data.meshes.new('merge_without_active_mesh')
        mesh.from_pydata([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [(0, 1)], [])
        obj = bpy.data.objects.new('merge_without_active_object', mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(mesh)
            for vert in bm.verts:
                vert.select = True
            bm.select_history.clear()
            bmesh.update_edit_mesh(mesh)
            self.assertEqual(bpy.ops.ho.merge_to_first(), {'CANCELLED'})
        finally:
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(obj, do_unlink=True)
            hopie.unregister()

    def test_disable_purges_untracked_pie_keymaps(self):
        hopie = load_hopie()
        hopie.register()
        try:
            hopie.set_pie_enabled('selection_mode', True)
            hopie.set_pie_enabled('delete_merge', True)
            self.assertEqual(
                len(keymap_items_for_menu('HO_MT_selection_mode_pie')),
                1,
            )
            self.assertEqual(
                len(keymap_items_for_menu('HO_MT_delete_merge_pie')),
                1,
            )

            hopie.selection_mode_pie_keymaps.clear()
            hopie.delete_merge_pie_keymaps.clear()
            hopie.set_pie_enabled('selection_mode', False)
            hopie.set_pie_enabled('delete_merge', False)
            self.assertEqual(
                keymap_items_for_menu('HO_MT_selection_mode_pie'),
                [],
            )
            self.assertEqual(
                keymap_items_for_menu('HO_MT_delete_merge_pie'),
                [],
            )
        finally:
            hopie.unregister()

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NewPieRegistrationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
