"""Run with Blender --background --factory-startup --python-exit-code 1 --python <file>."""

import unittest
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


ASSET_PATH = Path(__file__).resolve().parents[1] / "HoAssets" / "GN.blend"
QUAD = [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)]


def make_mesh(name, collection=None, vertices=QUAD):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, [], [tuple(range(len(vertices)))])
    obj = bpy.data.objects.new(name, mesh)
    (collection or bpy.context.scene.collection).objects.link(obj)
    return obj


class CopyMeshTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        with bpy.data.libraries.load(str(ASSET_PATH), assets_only=True) as (_, data):
            data.node_groups = ["CopyMesh"]
        self.group = data.node_groups[0]
        self.assertIsNotNone(self.group, "CopyMesh must be saved as an asset")
        self.inputs = {
            item.name: item
            for item in self.group.interface.items_tree
            if item.item_type == "SOCKET" and item.in_out == "INPUT"
        }
        self.host = make_mesh(
            "Host", vertices=[(50, 0, 0), (51, 0, 0), (50, 1, 0)]
        )
        self.modifier = self.host.modifiers.new("CopyMesh", "NODES")
        self.modifier.node_group = self.group

    def configure(self, **values):
        for name, value in values.items():
            self.modifier[self.inputs[name].identifier] = value
        self.host.update_tag()
        bpy.context.view_layer.update()

    def evaluated_mesh(self):
        depsgraph = bpy.context.evaluated_depsgraph_get()
        return self.host.evaluated_get(depsgraph).data

    def instances(self):
        depsgraph = bpy.context.evaluated_depsgraph_get()
        return [
            (instance.object.original.name, instance.matrix_world.copy())
            for instance in depsgraph.object_instances
            if instance.is_instance
            and instance.parent
            and instance.parent.original == self.host
        ]

    def assert_vertices(self, mesh, expected):
        actual = sorted(tuple(round(c, 5) for c in vertex.co) for vertex in mesh.vertices)
        expected = sorted(tuple(round(c, 5) for c in vertex) for vertex in expected)
        self.assertEqual(actual, expected)

    def test_asset_is_in_hogn_and_defaults_to_instances(self):
        self.assertTrue(self.group.is_modifier)
        self.assertEqual(
            self.group.asset_data.catalog_id, "b48222de-168c-4553-b6ff-032d3f992197"
        )
        self.assertFalse(self.inputs["非实例"].default_value)
        self.assertFalse(self.modifier[self.inputs["非实例"].identifier])
        self.assertFalse(self.inputs["集合模式"].default_value)

    def test_no_source_replaces_original_geometry_with_empty_geometry(self):
        for collection_mode in (False, True):
            for realize in (False, True):
                with self.subTest(collection_mode=collection_mode, realize=realize):
                    self.configure(**{"集合模式": collection_mode, "非实例": realize})
                    self.assertEqual(len(self.evaluated_mesh().vertices), 0)
                    self.assertEqual(self.instances(), [])
        self.assertEqual(len(self.host.data.vertices), 3)

    def test_object_is_an_instance_by_default(self):
        source = make_mesh("Source")
        self.configure(**{"物体": source})
        self.assertEqual(len(self.evaluated_mesh().vertices), 0)
        self.assertEqual([name for name, _ in self.instances()], ["Source"])
        self.assertEqual(len(self.host.data.vertices), 3)

    def test_realized_object_copies_local_mesh_and_preserves_host_transform(self):
        source = make_mesh("Source")
        source.location = (13, -7, 9)
        source.rotation_euler = (0.2, 0.4, 0.8)
        source.scale = (2, 3, 4)
        self.host.location = (-4, 3, 2)
        self.host.rotation_euler = (0.3, -0.5, 0.7)
        self.host.scale = (1.5, 0.75, 2)
        bpy.context.view_layer.update()
        before = self.host.matrix_world.copy()
        self.configure(**{"物体": source, "非实例": True})
        self.assert_vertices(self.evaluated_mesh(), QUAD)
        self.assertEqual(len(self.evaluated_mesh().polygons), 1)
        self.assertEqual(self.instances(), [])
        self.assertEqual(self.host.matrix_world, before)
        self.assertEqual(len(self.host.data.vertices), 3)
        self.assert_vertices(source.data, QUAD)

    def test_source_modifiers_and_mesh_changes_update_the_copy(self):
        source = make_mesh("Source")
        subdivide = source.modifiers.new("Source Subdivision", "SUBSURF")
        subdivide.subdivision_type = "SIMPLE"
        subdivide.levels = 1
        self.configure(**{"物体": source, "非实例": True})
        self.assertEqual(len(self.evaluated_mesh().vertices), 9)
        self.assertEqual(len(self.evaluated_mesh().polygons), 4)
        for vertex in source.data.vertices:
            vertex.co.z = 3
        source.data.update()
        self.configure()
        self.assertTrue(all(abs(v.co.z - 3) < 1e-5 for v in self.evaluated_mesh().vertices))

    def test_materials_uvs_and_named_attributes_are_preserved(self):
        source = make_mesh("Source")
        material = bpy.data.materials.new("Source Material")
        source.data.materials.append(material)
        uv = source.data.uv_layers.new(name="CopyUV")
        uv_values = [(0, 0), (1, 0), (1, 1), (0, 1)]
        for loop, value in zip(uv.data, uv_values):
            loop.uv = value
        attribute = source.data.attributes.new("CopyWeight", "FLOAT", "POINT")
        for index, value in enumerate(attribute.data):
            value.value = index / 4
        self.configure(**{"物体": source, "非实例": True})
        mesh = self.evaluated_mesh()
        self.assertEqual([item.original for item in mesh.materials], [material])
        self.assertEqual([tuple(loop.uv) for loop in mesh.uv_layers["CopyUV"].data], uv_values)
        self.assertEqual(
            [value.value for value in mesh.attributes["CopyWeight"].data],
            [0, 0.25, 0.5, 0.75],
        )

    def test_collection_retains_child_transforms_and_realizes_nested_instances(self):
        collection = bpy.data.collections.new("Sources")
        bpy.context.scene.collection.children.link(collection)
        first = make_mesh("First", collection)
        first.location = (4, 0, 0)
        nested = bpy.data.collections.new("Nested")
        collection.children.link(nested)
        second = make_mesh("Second", nested)
        second.location = (0, 5, 1)
        nested.instance_offset = (1, 0, 0)
        instance_collection = bpy.data.collections.new("Instanced Sources")
        instanced_source = make_mesh("Instanced Source", instance_collection)
        instance = bpy.data.objects.new("Nested Instance", None)
        instance.instance_type = "COLLECTION"
        instance.instance_collection = instance_collection
        instance.location = (-4, 0, 2)
        collection.objects.link(instance)
        collection.instance_offset = (1, 2, 0)
        self.host.location = (30, 40, 50)
        bpy.context.view_layer.update()
        expected = []
        offset = Matrix.Translation(-collection.instance_offset)
        for obj in (first, second):
            expected.extend(offset @ obj.matrix_world @ Vector(v) for v in QUAD)
        expected.extend(offset @ instance.matrix_world @ Vector(v) for v in QUAD)
        self.configure(**{"集合": collection, "集合模式": True})
        self.assertEqual(len(self.evaluated_mesh().vertices), 0)
        self.assertEqual(
            sorted(name for name, _ in self.instances()),
            ["First", "Instanced Source", "Nested Instance", "Second"],
        )
        self.configure(**{"非实例": True})
        self.assert_vertices(self.evaluated_mesh(), expected)
        self.assertEqual(len(self.evaluated_mesh().polygons), 3)
        self.assertEqual(self.instances(), [])
        self.assertEqual(len(instanced_source.data.vertices), 4)

    def test_mode_switch_selects_object_or_collection(self):
        source = make_mesh("Object Source")
        collection = bpy.data.collections.new("Collection Source")
        bpy.context.scene.collection.children.link(collection)
        other = make_mesh("Collection Child", collection)
        other.location = (10, 0, 0)
        self.configure(**{"物体": source, "集合": collection, "非实例": True})
        self.assert_vertices(self.evaluated_mesh(), QUAD)
        self.configure(**{"集合模式": True})
        self.assert_vertices(self.evaluated_mesh(), [Vector(v) + other.location for v in QUAD])
        self.configure(**{"集合模式": False})
        self.assert_vertices(self.evaluated_mesh(), QUAD)

    def test_selected_source_is_used_even_when_empty(self):
        empty = bpy.data.objects.new("Empty Source", bpy.data.meshes.new("Empty Mesh"))
        bpy.context.scene.collection.objects.link(empty)
        collection = bpy.data.collections.new("Collection Source")
        bpy.context.scene.collection.children.link(collection)
        make_mesh("Collection Child", collection)
        self.configure(**{"物体": empty, "集合": collection, "非实例": True})
        self.assertEqual(len(self.evaluated_mesh().vertices), 0)
        self.configure(**{"集合模式": True})
        self.assert_vertices(self.evaluated_mesh(), QUAD)
        self.configure(**{"集合": None})
        self.assertEqual(len(self.evaluated_mesh().vertices), 0)
        self.configure(**{"集合": collection, "集合模式": False, "物体": None})
        self.assertEqual(len(self.evaluated_mesh().vertices), 0)

    def test_realized_output_supports_a_following_mesh_modifier(self):
        source = make_mesh("Source")
        self.configure(**{"物体": source, "非实例": True})
        solidify = self.host.modifiers.new("Following Solidify", "SOLIDIFY")
        solidify.thickness = 0.5
        self.configure()
        mesh = self.evaluated_mesh()
        self.assertEqual(len(mesh.vertices), 8)
        self.assertEqual(len(mesh.polygons), 6)

    def test_realized_output_supports_a_following_geometry_nodes_modifier(self):
        source = make_mesh("Source")
        following = bpy.data.node_groups.new("Following GN", "GeometryNodeTree")
        following.interface.new_socket(
            name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
        )
        following.interface.new_socket(
            name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
        )
        input_node = following.nodes.new("NodeGroupInput")
        set_position = following.nodes.new("GeometryNodeSetPosition")
        set_position.inputs["Offset"].default_value = (0, 0, 5)
        output_node = following.nodes.new("NodeGroupOutput")
        following.links.new(input_node.outputs["Geometry"], set_position.inputs["Geometry"])
        following.links.new(set_position.outputs["Geometry"], output_node.inputs["Geometry"])
        modifier = self.host.modifiers.new("Following GN", "NODES")
        modifier.node_group = following
        self.configure(**{"物体": source, "非实例": True})
        self.assert_vertices(self.evaluated_mesh(), [(x, y, z + 5) for x, y, z in QUAD])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CopyMeshTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
