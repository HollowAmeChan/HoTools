"""RT direct modifier meshes, real Cycles output and scene restoration.

Run with Blender --background --factory-startup --python-exit-code 1 --python.
"""

import importlib
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import bpy
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
package = ModuleType("hotools_rt_bake_tests")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
uv_package = ModuleType(package.__name__ + ".UvTools")
uv_package.__path__ = [str(ROOT / "UvTools")]
sys.modules[uv_package.__name__] = uv_package
rt = importlib.import_module(uv_package.__name__ + ".RTbaker")


def modifier_flags(obj):
    return [(mod.name, mod.show_viewport, mod.show_render) for mod in obj.modifiers]


class RTBakeModifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rt.register()

    @classmethod
    def tearDownClass(cls):
        rt.unregister()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        self.settings = scene.ho_uvtools_rt_bake_settings
        self.settings.resolution = 32
        self.settings.samples = 1
        self.settings.use_adaptive_sampling = False
        self.settings.use_oidn_denoise = False
        self.settings.direct_non_color = True
        scene.render.bake.margin = 0
        scene.render.bake.image_settings.file_format = 'PNG'
        scene.render.bake.use_split_materials = False
        self.directory = tempfile.TemporaryDirectory(prefix="hotools_rt_modifiers_")
        self.addCleanup(self.directory.cleanup)
        self.obj = self.make_plane("Target")
        self.channel = rt.RTDirectChannel()
        self.operator = SimpleNamespace(report=Mock())

    def tearDown(self):
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

    def make_plane(self, name):
        mesh = bpy.data.meshes.new(name + "Mesh")
        mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)],
                         [], [(0, 1, 2, 3)])
        uv = mesh.uv_layers.new(name="UVMap")
        for loop, co in zip(uv.data, [(.1, .1), (.4, .1), (.4, .9), (.1, .9)]):
            loop.uv = co
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        obj.data.materials.append(self.make_material(name + "Material"))
        group = self.settings.target_groups.add()
        group.objects.add().object = obj
        return obj

    def make_material(self, name, color=(.5, .5, 1, 1)):
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        material.node_tree.nodes.clear()
        emission = material.node_tree.nodes.new('ShaderNodeEmission')
        emission.inputs['Color'].default_value = color
        output = material.node_tree.nodes.new('ShaderNodeOutputMaterial')
        material.node_tree.links.new(emission.outputs['Emission'], output.inputs['Surface'])
        return material

    def add_array(self):
        modifier = self.obj.modifiers.new("ArrayWithUVOffset", 'ARRAY')
        modifier.count = 2
        modifier.use_relative_offset = False
        modifier.use_constant_offset = True
        modifier.constant_offset_displace = (3, 0, 0)
        modifier.offset_u = .5
        return modifier

    def add_geometry_nodes(self, node_type):
        group = bpy.data.node_groups.new("BakeGeometry", 'GeometryNodeTree')
        group.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        group.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        source = group.nodes.new('NodeGroupInput')
        output = group.nodes.new('NodeGroupOutput')
        node = group.nodes.new(node_type)
        group.links.new(source.outputs['Geometry'], node.inputs['Geometry'])
        group.links.new(node.outputs['Geometry'], output.inputs['Geometry'])
        modifier = self.obj.modifiers.new("BakeGeometry", 'NODES')
        modifier.node_group = group
        return node, modifier

    def bake(self, name):
        bpy.context.scene.render.bake.filepath = str(Path(self.directory.name) / (name + ".png"))
        self.assertEqual(bpy.ops.ho.uvtools_rt_bake(), {'FINISHED'})
        with rt.Image.open(Path(self.directory.name) / (name + "_Direct.png")) as image:
            return np.array(image.convert("RGBA"))

    def test_switch_is_registered_and_drawn_with_direct_settings(self):
        self.assertFalse(self.settings.direct_use_modifiers)
        layout = Mock()
        self.channel.draw_settings(layout, bpy.context)
        properties = [call.args[1] for call in layout.column.return_value.prop.call_args_list]
        self.assertIn("direct_use_modifiers", properties)
        self.assertIn("direct_non_color", properties)

    def test_array_output_matches_manually_applied_mesh_including_uv_padding(self):
        modifier = self.add_array()
        mesh = self.obj.data
        flags = modifier_flags(self.obj)
        mesh_names = set(bpy.data.meshes.keys())
        off = self.bake("disabled")
        self.settings.direct_use_modifiers = True
        on = self.bake("enabled")
        self.assertIs(self.obj.data, mesh)
        self.assertEqual(modifier_flags(self.obj), flags)
        self.assertEqual(set(bpy.data.meshes.keys()), mesh_names)
        self.assertEqual(len(mesh.vertices), 4)
        self.assertEqual(int(off[16, 24, 3]), 0)
        self.assertEqual(tuple(on[16, 24]), (128, 128, 255, 255))
        self.assertEqual(tuple(on[16, 8]), (128, 128, 255, 255))
        self.assertEqual(int(on[16, 16, 3]), 0)
        self.settings.direct_use_modifiers = False
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        expected = self.bake("applied")
        np.testing.assert_array_equal(on, expected)

    def test_uses_viewport_enabled_stack_without_applying_render_only_modifiers(self):
        modifier = self.add_array()
        modifier.show_viewport = False
        modifier.show_render = True
        self.settings.direct_use_modifiers = True
        image = self.bake("viewport")
        self.assertEqual(int(image[16, 24, 3]), 0)
        self.assertEqual(modifier_flags(self.obj), [(modifier.name, False, True)])

    def test_bakes_geometry_nodes_attributes_and_respects_ignore_switch(self):
        node, modifier = self.add_geometry_nodes('GeometryNodeStoreNamedAttribute')
        node.data_type = 'FLOAT_COLOR'
        node.domain = 'POINT'
        node.inputs['Name'].default_value = "ModifierColor"
        node.inputs['Value'].default_value = (.25, .5, .75, 1)
        tree = self.obj.active_material.node_tree
        attribute = tree.nodes.new('ShaderNodeAttribute')
        attribute.attribute_name = "ModifierColor"
        emission = next(node for node in tree.nodes if node.type == 'EMISSION')
        tree.links.new(attribute.outputs['Color'], emission.inputs['Color'])
        self.settings.direct_use_modifiers = True
        mesh = self.obj.data
        flags = modifier_flags(self.obj)
        self.settings.ignore_geometry_nodes = True
        ignored = self.bake("ignore_nodes")
        self.settings.ignore_geometry_nodes = False
        included = self.bake("include_nodes")
        self.assertEqual(tuple(ignored[16, 8]), (0, 0, 0, 255))
        self.assertEqual(tuple(included[16, 8]), (64, 128, 191, 255))
        self.assertIs(self.obj.data, mesh)
        self.assertIsNone(mesh.attributes.get("ModifierColor"))
        self.assertEqual(modifier_flags(self.obj), flags)

    def test_bakes_material_generated_by_geometry_nodes_and_restores_slots(self):
        node, _ = self.add_geometry_nodes('GeometryNodeSetMaterial')
        material = self.make_material("NodeMaterial", (.25, .5, .75, 1))
        node.inputs['Material'].default_value = material
        self.settings.direct_use_modifiers = True
        self.settings.ignore_geometry_nodes = False
        slots = [(slot.link, slot.material) for slot in self.obj.material_slots]
        image = self.bake("node_material")
        self.assertEqual(tuple(image[16, 8]), (64, 128, 191, 255))
        self.assertEqual([(slot.link, slot.material) for slot in self.obj.material_slots], slots)

    def test_restores_edit_mode_shape_keys_material_slots_and_selection(self):
        self.add_array()
        basis = self.obj.shape_key_add(name="Basis")
        shape = self.obj.shape_key_add(name="Shape")
        shape.data[0].co.z = .5
        shape.value = .25
        override = self.make_material("ObjectMaterial", (.25, .5, .75, 1))
        self.obj.material_slots[0].link = 'OBJECT'
        self.obj.material_slots[0].material = override
        mesh = self.obj.data
        nodes = override.node_tree.nodes
        active = nodes.active
        selected = [node.name for node in nodes if node.select]
        mesh_names = set(bpy.data.meshes.keys())
        image_names = set(bpy.data.images.keys())
        self.settings.direct_use_modifiers = True
        bpy.ops.object.mode_set(mode='EDIT')
        self.bake("edit_mode")
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertIs(self.obj.data, mesh)
        self.assertEqual([key.name for key in mesh.shape_keys.key_blocks], [basis.name, shape.name])
        self.assertAlmostEqual(shape.value, .25)
        self.assertEqual(self.obj.material_slots[0].link, 'OBJECT')
        self.assertIs(self.obj.material_slots[0].material, override)
        self.assertEqual(nodes.active, active)
        self.assertEqual([node.name for node in nodes if node.select], selected)
        self.assertEqual(set(bpy.data.meshes.keys()), mesh_names)
        self.assertEqual(set(bpy.data.images.keys()), image_names)
        self.assertEqual(list(bpy.context.selected_objects), [self.obj])

    def test_restores_meshes_and_modifier_flags_when_bake_raises(self):
        self.add_array()
        self.settings.direct_use_modifiers = True
        mesh = self.obj.data
        flags = modifier_flags(self.obj)
        mesh_names = set(bpy.data.meshes.keys())
        image_names = set(bpy.data.images.keys())
        bpy.ops.object.mode_set(mode='EDIT')
        with patch.object(rt.RTBakeChannel, "_execute_group", side_effect=RuntimeError("test bake error")):
            with self.assertRaisesRegex(RuntimeError, "test bake error"):
                self.channel.execute(bpy.context, self.operator)
        self.assertIs(self.obj.data, mesh)
        self.assertEqual(modifier_flags(self.obj), flags)
        self.assertEqual(set(bpy.data.meshes.keys()), mesh_names)
        self.assertEqual(set(bpy.data.images.keys()), image_names)
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')

    def test_restores_all_targets_if_preparation_fails(self):
        self.add_array()
        other = self.make_plane("Other")
        originals = {obj.name: obj.data for obj in (self.obj, other)}
        flags = {obj.name: modifier_flags(obj) for obj in (self.obj, other)}
        mesh_names = set(bpy.data.meshes.keys())
        self.settings.direct_use_modifiers = True
        prepare = self.channel._prepare_modifier_meshes

        def prepare_and_fail(context, states):
            prepare(context, states)
            raise RuntimeError("test prepare error")

        with patch.object(self.channel, "_prepare_modifier_meshes", side_effect=prepare_and_fail):
            with self.assertRaisesRegex(RuntimeError, "test prepare error"):
                self.channel.execute(bpy.context, self.operator)
        self.assertEqual({obj.name: obj.data for obj in (self.obj, other)}, originals)
        self.assertEqual({obj.name: modifier_flags(obj) for obj in (self.obj, other)}, flags)
        self.assertEqual(set(bpy.data.meshes.keys()), mesh_names)

    def test_prepares_all_targets_before_swapping_shared_meshes(self):
        self.add_array()
        other = self.make_plane("Other")
        other.data = self.obj.data
        modifier = other.modifiers.new("OtherArray", 'ARRAY')
        modifier.count = 3
        original = self.obj.data
        flags = {obj.name: modifier_flags(obj) for obj in (self.obj, other)}
        states = []
        try:
            self.channel._prepare_modifier_meshes(bpy.context, states)
            self.assertEqual([len(obj.data.vertices) for obj in (self.obj, other)], [8, 12])
            self.assertIsNot(self.obj.data, other.data)
            self.assertTrue(all(not mod.show_viewport and not mod.show_render
                                for obj in (self.obj, other) for mod in obj.modifiers))
        finally:
            self.channel._restore_modifier_meshes(bpy.context, states)
        self.assertIs(self.obj.data, original)
        self.assertIs(other.data, original)
        self.assertEqual({obj.name: modifier_flags(obj) for obj in (self.obj, other)}, flags)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
