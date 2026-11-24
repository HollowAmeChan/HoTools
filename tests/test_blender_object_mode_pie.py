"""Run with Blender --background --factory-startup --python-exit-code 1."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import bpy
import gpu

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))


class RecordingLayout:
    def __init__(self):
        self.operators = []
        self.properties = []

    def __getattr__(self, name):
        if name in {'row', 'column', 'box', 'split', 'menu_pie', 'grid_flow'}:
            return lambda *args, **kwargs: self
        if name in {'separator', 'label'}:
            return lambda *args, **kwargs: None
        raise AttributeError(name)

    def operator(self, idname, **kwargs):
        namespace, name = idname.split('.')
        getattr(getattr(bpy.ops, namespace), name).get_rna_type()
        icon = kwargs.get('icon')
        if icon:
            icons = bpy.types.UILayout.bl_rna.functions['operator'].parameters['icon'].enum_items
            assert icon in icons, icon
        props = SimpleNamespace()
        self.operators.append((idname, props))
        return props

    def prop(self, owner, name, **kwargs):
        assert hasattr(owner, name), name
        self.properties.append((owner, name))


class ObjectModePieTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shader_factory = gpu.shader.from_builtin
        gpu.shader.from_builtin = lambda name: None
        bpy.ops.preferences.addon_enable(module=ROOT.name)
        cls.addon = sys.modules[ROOT.name]
        cls.prefs = bpy.context.preferences.addons[ROOT.name].preferences
        cls.pie = cls.addon.HoPie.ObjectModePie

    @classmethod
    def tearDownClass(cls):
        cls.prefs.hoTools_enableObjectModePie = True
        bpy.ops.preferences.addon_disable(module=ROOT.name)
        gpu.shader.from_builtin = cls.shader_factory
        assert not hasattr(bpy.types, 'HO_MT_object_mode_pie')

    def setUp(self):
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        bpy.ops.mesh.primitive_cube_add()
        self.obj = bpy.context.object
        self.area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')

    def tearDown(self):
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        self.prefs.hoTools_enableObjectModePie = False
        self.prefs.hoTools_enableArmatureModePie = True
        self.prefs.hoTools_enableQuickModifiers = True

    def draw_pie(self):
        layout = RecordingLayout()
        self.pie.HO_MT_object_mode_pie.draw(SimpleNamespace(layout=layout), bpy.context)
        mode_items = bpy.ops.object.mode_set.get_rna_type().properties['mode'].enum_items
        for idname, props in layout.operators:
            if idname == 'object.mode_set':
                self.assertIn(props.mode, mode_items)
        return layout

    def test_defaults_and_repeat_switches_preserve_other_tab_bindings(self):
        self.assertFalse(self.prefs.hoTools_enableObjectModePie)
        self.assertTrue(self.prefs.hoTools_enableQuickModifiers)
        keyconfig = bpy.context.window_manager.keyconfigs.addon
        keymap = keyconfig.keymaps.new(name='Object Non-modal', space_type='EMPTY')
        foreign = keymap.keymap_items.new('wm.call_menu_pie', 'TAB', 'PRESS')
        foreign.properties.name = 'MACHIN3_MT_modes_pie'
        foreign_id = foreign.id
        try:
            for _ in range(3):
                self.prefs.hoTools_enableObjectModePie = True
                items = self.addon.HoPie.object_mode_pie_keymaps
                self.assertEqual([(k.name, i.type) for k, i in items],
                                 [('Object Non-modal', 'TAB'), ('Image', 'TAB')])
                self.assertEqual(len([i for k in keyconfig.keymaps for i in k.keymap_items
                                      if i.idname == 'ho.object_mode_pie']), 2)
                self.assertTrue(all(pair in self.addon._preference_keymaps() for pair in items))
                self.prefs.hoTools_enableObjectModePie = False
                self.assertFalse(self.addon.HoPie.object_mode_pie_keymaps)
                self.assertFalse(hasattr(bpy.types, 'HO_MT_object_mode_pie'))
                self.assertFalse(any(i.idname == 'ho.object_mode_pie'
                                     for k in keyconfig.keymaps for i in k.keymap_items))
                self.assertEqual(foreign.id, foreign_id)
        finally:
            keymap.keymap_items.remove(foreign)

    def test_mesh_edit_selection_modes_and_multi_mode_selection(self):
        self.prefs.hoTools_enableObjectModePie = True
        for mode, expected in [('VERT', (True, False, False)),
                               ('EDGE', (False, True, False)),
                               ('FACE', (False, False, True))]:
            self.assertEqual(bpy.ops.ho.object_mode_mesh_select(mode=mode), {'FINISHED'})
            self.assertEqual(bpy.context.mode, 'EDIT_MESH')
            self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode), expected)
        bpy.ops.ho.object_mode_mesh_select(mode='VERT', use_extend=True)
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode), (True, False, True))
        with bpy.context.temp_override(area=self.area):
            layout = self.draw_pie()
            self.assertIn('use_mesh_automerge', [name for owner, name in layout.properties])
            self.assertIn('show_xray', [name for owner, name in layout.properties])

    def test_armature_pie_keeps_tab_priority_and_other_contexts_fall_through(self):
        self.prefs.hoTools_enableObjectModePie = True
        with bpy.context.temp_override(area=self.area):
            self.assertTrue(bpy.ops.ho.object_mode_pie.poll())
            bpy.ops.object.armature_add()
            self.assertFalse(bpy.ops.ho.object_mode_pie.poll())
            self.assertTrue(bpy.ops.ho.armature_mode_pie.poll())
            self.prefs.hoTools_enableArmatureModePie = False
            self.assertTrue(bpy.ops.ho.object_mode_pie.poll())
            self.draw_pie()
            bpy.ops.object.empty_add()
            self.assertFalse(bpy.ops.ho.object_mode_pie.poll())
            bpy.context.view_layer.objects.active = None
            self.assertFalse(bpy.ops.ho.object_mode_pie.poll())

    def test_image_editor_modes_and_uv_sync(self):
        self.prefs.hoTools_enableObjectModePie = True
        old_type = self.area.type
        self.area.type = 'IMAGE_EDITOR'
        try:
            with bpy.context.temp_override(area=self.area):
                self.assertTrue(bpy.ops.ho.object_mode_pie.poll())
                self.draw_pie()
                self.assertEqual(bpy.ops.ho.object_mode_image(mode='UV'), {'FINISHED'})
                self.assertEqual(bpy.context.mode, 'EDIT_MESH')
                self.assertEqual(len(self.obj.data.uv_layers), 1)
                self.assertEqual(bpy.context.space_data.mode, 'UV')
                settings = bpy.context.tool_settings
                settings.use_uv_select_sync = False
                for mode in ('VERTEX', 'EDGE', 'FACE', 'ISLAND'):
                    bpy.ops.ho.object_mode_uv_select(mode=mode)
                    if mode == 'ISLAND' and hasattr(settings, 'use_uv_select_island'):
                        self.assertTrue(settings.use_uv_select_island)
                    else:
                        self.assertEqual(settings.uv_select_mode, mode)
                self.draw_pie()
                settings.use_uv_select_sync = True
                bpy.ops.ho.object_mode_uv_select(mode='EDGE')
                self.assertEqual(tuple(settings.mesh_select_mode), (False, True, False))
                self.draw_pie()
                bpy.ops.ho.object_mode_image(mode='VIEW')
                self.assertEqual(bpy.context.mode, 'OBJECT')
                for mode in ('PAINT', 'MASK', 'VIEW'):
                    bpy.ops.ho.object_mode_image(mode=mode)
                    self.assertEqual(bpy.context.space_data.mode, mode)
        finally:
            self.area.type = old_type

    def test_draw_mesh_paint_modes_and_non_mesh_objects(self):
        self.prefs.hoTools_enableObjectModePie = True
        with bpy.context.temp_override(area=self.area):
            for mode in ('OBJECT', 'EDIT', 'SCULPT', 'VERTEX_PAINT', 'WEIGHT_PAINT', 'TEXTURE_PAINT'):
                bpy.ops.object.mode_set(mode=mode)
                self.draw_pie()
                bpy.ops.object.mode_set(mode='OBJECT')
            for obj_type in ('CURVE', 'SURFACE', 'META', 'FONT', 'LATTICE'):
                bpy.ops.object.add(type=obj_type)
                self.assertTrue(bpy.ops.ho.object_mode_pie.poll())
                self.draw_pie()
                bpy.ops.object.mode_set(mode='EDIT')
                self.draw_pie()
                bpy.ops.object.mode_set(mode='OBJECT')
            grease_pencils = getattr(bpy.data, 'grease_pencils_v3', bpy.data.grease_pencils)
            for collection in (bpy.data.hair_curves, grease_pencils):
                data = collection.new('mode_pie_data')
                obj = bpy.data.objects.new('mode_pie_obj', data)
                bpy.context.collection.objects.link(obj)
                bpy.context.view_layer.objects.active = obj
                obj.select_set(True)
                self.draw_pie()
                bpy.ops.object.mode_set(mode='EDIT')
                self.draw_pie()
                bpy.ops.object.mode_set(mode='OBJECT')

    def test_quick_modifier_switch_only_hides_the_add_box(self):
        self.obj.modifiers.new('mirror', 'MIRROR')
        for enabled in (True, False, True):
            self.prefs.hoTools_enableQuickModifiers = enabled
            layout = RecordingLayout()
            self.addon.ModifierTools._draw_modifier_tools(layout, bpy.context)
            ids = [idname for idname, props in layout.operators]
            self.assertEqual('ho.modifier_add_quick' in ids, enabled)
            self.assertIn('ho.modifier_apply_all', ids)
            self.assertIn('ho.modifier_delete_all', ids)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ObjectModePieTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
