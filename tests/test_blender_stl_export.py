"""Run in Blender: --background --factory-startup --python-exit-code 1 --python <file>.

Check actual STL facets and native import, GN ownership (including nested
collections), selection scope, modifier switches, transforms and failure cleanup.
"""

import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bpy
from mathutils import Matrix, Vector


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Exporter import StlExporter


def make_mesh(name, collection=None):
    mesh = bpy.data.meshes.new(name + 'Mesh')
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    (collection or bpy.context.scene.collection).objects.link(obj)
    return obj


def select(*objects):
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0] if objects else None
    bpy.context.view_layer.update()


def gn_collection(obj, collection, *, join_base=False):
    group = bpy.data.node_groups.new(obj.name + 'GN', 'GeometryNodeTree')
    group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    output = group.nodes.new('NodeGroupOutput')
    info = group.nodes.new('GeometryNodeCollectionInfo')
    info.inputs['Collection'].default_value = collection
    if join_base:
        join = group.nodes.new('GeometryNodeJoinGeometry')
        input_node = group.nodes.new('NodeGroupInput')
        group.links.new(input_node.outputs['Geometry'], join.inputs['Geometry'])
        group.links.new(info.outputs['Instances'], join.inputs['Geometry'])
        group.links.new(join.outputs['Geometry'], output.inputs['Geometry'])
    else:
        group.links.new(info.outputs['Instances'], output.inputs['Geometry'])
    modifier = obj.modifiers.new('Collection GN', 'NODES')
    modifier.node_group = group
    return modifier


def read_stl(path, ascii_format=False):
    data = path.read_bytes()
    if ascii_format:
        vertices = [tuple(float(v) for v in line.split()[1:])
                    for line in data.decode('ascii').splitlines()
                    if line.strip().startswith('vertex ')]
        return [vertices[i:i + 3] for i in range(0, len(vertices), 3)]
    count, = struct.unpack_from('<I', data, 80)
    assert len(data) == 84 + 50 * count
    return [[tuple(record[i:i + 3]) for i in (3, 6, 9)]
            for record in struct.iter_unpack('<12fH', data[84:])]


def bounds(triangles):
    vertices = [vertex for tri in triangles for vertex in tri]
    return tuple(min(v[i] for v in vertices) for i in range(3)), tuple(
        max(v[i] for v in vertices) for i in range(3))


def scene_state():
    return (
        bpy.context.mode,
        bpy.context.view_layer.objects.active.as_pointer()
        if bpy.context.view_layer.objects.active else None,
        tuple(sorted(obj.as_pointer() for obj in bpy.context.selected_objects)),
        tuple((obj.as_pointer(), obj.data.as_pointer() if obj.data else None,
               tuple(value for row in obj.matrix_world for value in row),
               obj.hide_viewport, obj.hide_render, obj.hide_get(),
               tuple((mod.as_pointer(), mod.type, mod.show_viewport, mod.show_render)
                     for mod in obj.modifiers)) for obj in bpy.data.objects),
        tuple((mesh.as_pointer(), tuple(tuple(v.co) for v in mesh.vertices))
              for mesh in bpy.data.meshes),
        tuple(group.as_pointer() for group in bpy.data.node_groups),
        tuple(col.as_pointer() for col in bpy.data.collections),
    )


class HoSTLTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.directory = tempfile.TemporaryDirectory(prefix='hostl_test_')
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def export(self, name='export.stl', **options):
        bpy.context.view_layer.update()
        before = scene_state()
        result = StlExporter.export_stl(bpy.context, str(self.root / name), **options)
        self.assertEqual(scene_state(), before, 'Export changed the authored scene')
        self.assertFalse(list(self.root.glob('.hostl_*')))
        return result

    def build_gn(self):
        # Source meshes are deliberately outside the scene. They must be included
        # through selected instancers, never as additional standalone exports.
        collection = bpy.data.collections.new('Sources')
        source = make_mesh('Source', collection)
        source.location.x = 2
        source.modifiers.new('Solidify source', 'SOLIDIFY').thickness = 0.25
        other = make_mesh('OtherSource', collection)
        other.location.x = 5
        a = make_mesh('GN_A')
        a.location.x = 10
        gn_collection(a, collection, join_base=True)
        b = make_mesh('GN_B')
        b.location.x = 20
        gn_collection(b, collection)
        unselected = make_mesh('Unselected')
        unselected.location.x = 1000
        gn_collection(unselected, collection)
        select(a, b)
        return a, b, source

    def test_gn_instances_grouped_per_selected_object_and_merged(self):
        self.build_gn()
        paths, skipped = self.export(use_batch=True, convert_units=False)
        self.assertFalse(skipped)
        self.assertEqual({Path(path).name for path in paths}, {'GN_A.stl', 'GN_B.stl'})
        a = read_stl(self.root / 'GN_A.stl')
        b = read_stl(self.root / 'GN_B.stl')
        # One solidified triangle (8 facets), one plain triangle, plus A's base.
        self.assertEqual((len(a), len(b)), (10, 9))
        self.assertEqual(bounds(a)[0][0], 10)
        self.assertEqual(bounds(a)[1][0], 16)
        self.assertEqual(bounds(b)[0][0], 22)
        self.assertEqual(bounds(b)[1][0], 26)
        self.export('merged.stl', convert_units=False)
        merged = read_stl(self.root / 'merged.stl')
        self.assertEqual(len(merged), len(a) + len(b))
        self.assertEqual(bounds(merged)[1][0], 26)
        # Verify a real Blender importer accepts the produced binary STL.
        select()
        self.assertEqual(bpy.ops.wm.stl_import(filepath=str(self.root / 'merged.stl')), {'FINISHED'})
        imported = bpy.context.object
        self.assertEqual(len(imported.data.polygons), 19)

    def test_all_switches_and_scene_units(self):
        a, b, source = self.build_gn()
        bpy.context.scene.unit_settings.system = 'METRIC'
        bpy.context.scene.unit_settings.scale_length = 0.001
        for ascii_format in (False, True):
            for use_batch in (False, True):
                for convert_units in (False, True):
                    for apply_modifiers in (False, True):
                        with self.subTest(ascii=ascii_format, batch=use_batch,
                                          units=convert_units, modifiers=apply_modifiers):
                            paths, skipped = self.export(
                                ascii_format=ascii_format, use_batch=use_batch,
                                convert_units=convert_units, apply_modifiers=apply_modifiers)
                            self.assertFalse(skipped)
                            triangles = [tri for path in paths for tri in
                                         read_stl(Path(path), ascii_format)]
                            self.assertEqual(len(triangles), 19 if apply_modifiers else 2)
                            scale = 100 if convert_units else 1
                            self.assertEqual(bounds(triangles)[0][0], 10 * scale)
                            self.assertEqual(bounds(triangles)[1][0],
                                             (26 if apply_modifiers else 21) * scale)

    def test_anonymous_gn_primitive_instances_match_native_export(self):
        obj = make_mesh('Generated')
        obj.location.x = 10
        group = bpy.data.node_groups.new('Primitive Instances', 'GeometryNodeTree')
        group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
        output = group.nodes.new('NodeGroupOutput')
        cube = group.nodes.new('GeometryNodeMeshCube')
        large_cube = group.nodes.new('GeometryNodeMeshCube')
        large_cube.inputs['Size'].default_value = (3, 3, 3)
        to_instances = group.nodes.new('GeometryNodeGeometryToInstance')
        group.links.new(cube.outputs['Mesh'], to_instances.inputs['Geometry'])
        group.links.new(large_cube.outputs['Mesh'], to_instances.inputs['Geometry'])
        points = group.nodes.new('GeometryNodeMeshLine')
        points.inputs['Count'].default_value = 2
        points.inputs['Offset'].default_value = (4, 0, 0)
        instance = group.nodes.new('GeometryNodeInstanceOnPoints')
        group.links.new(to_instances.outputs['Instances'], instance.inputs['Instance'])
        group.links.new(points.outputs['Mesh'], instance.inputs['Points'])
        group.links.new(instance.outputs['Instances'], output.inputs['Geometry'])
        obj.modifiers.new('Primitive GN', 'NODES').node_group = group
        select(obj)
        self.export(convert_units=False)
        ours = read_stl(self.root / 'export.stl')
        self.assertEqual(len(ours), 48)
        bpy.ops.wm.stl_export(filepath=str(self.root / 'native.stl'),
                              export_selected_objects=True, apply_modifiers=True)
        native = read_stl(self.root / 'native.stl')

        def canonical(triangles):
            return sorted(tuple(sorted(tuple(round(value, 5) for value in vertex)
                                       for vertex in tri)) for tri in triangles)

        self.assertEqual(canonical(ours), canonical(native))

    def test_chunk_boundaries_and_cache_eviction_preserve_output(self):
        self.build_gn()
        self.export(use_batch=True, convert_units=False)
        expected = {path.name: sorted(tuple(sorted(tri)) for tri in read_stl(path))
                    for path in self.root.glob('*.stl')}
        # Force both multi-chunk meshes and pending instances evicted between
        # differently sized source meshes and between their destination files.
        with patch.object(StlExporter, '_CHUNK_TRIANGLES', 2), \
                patch.object(StlExporter, '_GEOMETRY_CACHE_BYTES', 1):
            self.export(use_batch=True, convert_units=False)
        actual = {path.name: sorted(tuple(sorted(tri)) for tri in read_stl(path))
                  for path in self.root.glob('*.stl')}
        self.assertEqual(actual, expected)

    def test_shared_instance_geometry_is_read_once_per_export(self):
        self.build_gn()
        original = StlExporter._mesh_corners
        with patch.object(StlExporter, '_mesh_corners', wraps=original) as read:
            self.export(use_batch=True)
            populated = [call.args[0] for call in read.call_args_list
                         if len(call.args[0].polygons)]
            # A's base + the two shared instance sources, regardless of how
            # many selected instancers consume those source meshes.
            self.assertEqual(len(populated), 3)

    def test_zero_scale_and_invalid_coordinates(self):
        obj = make_mesh('Degenerate')
        obj.scale = (0, 1, 1)
        select(obj)
        self.export(convert_units=False)
        destination = self.root / 'export.stl'
        self.assertEqual(struct.unpack_from('<3f', destination.read_bytes(), 84), (0, 0, 0))
        previous = destination.read_bytes()
        obj.data.vertices[0].co.x = float('nan')
        with self.assertRaisesRegex(ValueError, '顶点坐标'):
            self.export(convert_units=False)
        self.assertEqual(destination.read_bytes(), previous)
        self.assertFalse(list(self.root.glob('.hostl_*')))

    def test_cache_does_not_survive_next_export(self):
        obj = make_mesh('Edited')
        select(obj)
        self.export(convert_units=False)
        obj.data.vertices[1].co.x = 7
        self.export(convert_units=False)
        self.assertEqual(bounds(read_stl(self.root / 'export.stl'))[1][0], 7)

    def test_ascii_native_import(self):
        obj = make_mesh('ASCII')
        select(obj)
        self.export(ascii_format=True, convert_units=False)
        select()
        self.assertEqual(bpy.ops.wm.stl_import(filepath=str(self.root / 'export.stl')),
                         {'FINISHED'})
        self.assertEqual(len(bpy.context.object.data.polygons), 1)

    def test_nested_collection_gn_and_collection_offset(self):
        a, b, source = self.build_gn()
        nested = bpy.data.collections.new('Nested')
        # Move B into an unlinked collection and instance it from an empty.
        bpy.context.scene.collection.objects.unlink(b)
        nested.objects.link(b)
        nested.instance_offset.x = 3
        owner = bpy.data.objects.new('NestedOwner', None)
        bpy.context.scene.collection.objects.link(owner)
        owner.instance_type = 'COLLECTION'
        owner.instance_collection = nested
        owner.location.x = 40
        select(owner)
        self.export(convert_units=False)
        result = read_stl(self.root / 'export.stl')
        self.assertEqual(len(result), 9)
        self.assertEqual(bounds(result)[0][0], 59)
        self.export('base.stl', convert_units=False, apply_modifiers=False)
        result = read_stl(self.root / 'base.stl')
        self.assertEqual(len(result), 1)
        self.assertEqual(bounds(result)[0][0], 57)

    def test_world_transforms_normals_and_shared_mesh(self):
        a = make_mesh('Mirrored')
        a.scale = (-2, 3, 1)
        a.rotation_euler.z = math.pi / 2
        parent = bpy.data.objects.new('Parent', None)
        bpy.context.scene.collection.objects.link(parent)
        parent.location = (10, 20, 30)
        a.parent = parent
        b = bpy.data.objects.new('Linked', a.data)
        bpy.context.scene.collection.objects.link(b)
        b.location.x = 1000
        select(a)
        self.export(convert_units=False)
        triangles = read_stl(self.root / 'export.stl')
        self.assertEqual(len(triangles), 1)
        self.assertEqual(tuple(round(v, 4) for v in bounds(triangles)[0]), (7, 18, 30))
        p, q, r = [Vector(v) for v in triangles[0]]
        self.assertGreater((q - p).cross(r - p).z, 0)
        data = (self.root / 'export.stl').read_bytes()
        self.assertEqual(struct.unpack_from('<3f', data, 84), (0, 0, 1))

    def test_sheared_nonuniform_transforms_and_normals_match_native(self):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8)
        a = bpy.context.object
        a.matrix_world = Matrix(((1.2, 0.3, 0.5, 12), (0, 2, 0.2, -4),
                                 (0.1, 0, -0.7, 2), (0, 0, 0, 1)))
        b = bpy.data.objects.new('LinkedSphere', a.data)
        bpy.context.scene.collection.objects.link(b)
        b.location = (2, 4, 8)
        b.rotation_euler = (0.3, 0.7, 2)
        b.scale = (2, -3, 0.1)
        select(a, b)
        self.export(convert_units=False)
        bpy.ops.wm.stl_export(filepath=str(self.root / 'native.stl'),
                              export_selected_objects=True, global_scale=1)

        def facets(path):
            values = struct.iter_unpack('<12fH', path.read_bytes()[84:])
            return {tuple(sorted(tuple(round(value, 4) for value in record[i:i + 3])
                                 for i in (3, 6, 9))): record[:3] for record in values}

        ours = facets(self.root / 'export.stl')
        native = facets(self.root / 'native.stl')
        self.assertEqual(ours.keys(), native.keys())
        for key in ours:
            for value, expected in zip(ours[key], native[key]):
                self.assertAlmostEqual(value, expected, delta=0.0001)

    def test_chunk_write_failure_preserves_destinations_and_clears_cache(self):
        self.build_gn()
        destination = self.root / 'export.stl'
        destination.write_bytes(b'original file')
        before = scene_state()
        real_write = StlExporter.STLWriter.write_batch
        caches = []

        def fail_after_write(writer, *args):
            caches.append(writer.cache)
            real_write(writer, *args)
            raise OSError('simulated full disk during chunk write')

        with patch.object(StlExporter.STLWriter, 'write_batch', fail_after_write):
            with self.assertRaisesRegex(OSError, 'chunk write'):
                self.export()
        self.assertEqual(scene_state(), before)
        self.assertEqual(destination.read_bytes(), b'original file')
        self.assertFalse(list(self.root.glob('.hostl_*')))
        self.assertTrue(caches)
        self.assertTrue(all(not cache.entries and cache.bytes == 0 for cache in caches))

    def test_hidden_modifier_and_selected_source_not_double_counted(self):
        a, b, source = self.build_gn()
        bpy.context.scene.collection.objects.link(source)
        source.modifiers[0].show_viewport = False
        select(a, source)
        self.export(convert_units=False)
        triangles = read_stl(self.root / 'export.stl')
        self.assertEqual(len(triangles), 4)  # A base, two instances, selected source.

    def test_safe_colliding_filenames_and_empty_objects(self):
        a = make_mesh('A:B')
        b = make_mesh('A?B')
        c = make_mesh('a_b')
        d = make_mesh('CON')
        empty = bpy.data.objects.new('Empty', None)
        bpy.context.scene.collection.objects.link(empty)
        select(a, b, c, d, empty)
        paths, skipped = self.export(use_batch=True)
        self.assertEqual({Path(path).name for path in paths},
                         {'A_B.stl', 'A_B_001.stl', 'a_b_002.stl', '_CON.stl'})
        self.assertEqual(skipped, ['Empty'])

    def test_failure_preserves_destinations_and_scene(self):
        self.build_gn()
        destination = self.root / 'GN_A.stl'
        destination.write_bytes(b'original file')
        before = scene_state()
        real_write = StlExporter.STLWriter.write_geometry
        first_writer = []

        def fail_second(writer, *args):
            if not first_writer:
                first_writer.append(writer)
            elif writer is not first_writer[0]:
                raise OSError('simulated full disk')
            return real_write(writer, *args)

        with patch.object(StlExporter.STLWriter, 'write_geometry', fail_second):
            with self.assertRaisesRegex(OSError, 'full disk'):
                self.export(use_batch=True)
        self.assertEqual(scene_state(), before)
        self.assertEqual(destination.read_bytes(), b'original file')
        self.assertEqual({p.name for p in self.root.iterdir()}, {'GN_A.stl'})

    def test_empty_selection_and_no_faces(self):
        with self.assertRaisesRegex(ValueError, '选中'):
            self.export()
        obj = bpy.data.objects.new('Empty', None)
        bpy.context.scene.collection.objects.link(obj)
        select(obj)
        destination = self.root / 'export.stl'
        destination.write_bytes(b'preserve')
        with self.assertRaisesRegex(ValueError, '三角面'):
            self.export()
        self.assertEqual(destination.read_bytes(), b'preserve')
        self.assertFalse(list(self.root.glob('.hostl_*')))

    def test_registration_defaults_and_operator(self):
        StlExporter.register()
        try:
            props = bpy.ops.ho.stl_export.get_rna_type().properties
            for name, expected in (('ascii_format', False), ('use_batch', False),
                                   ('convert_units', True), ('apply_modifiers', True)):
                self.assertEqual(props[name].default, expected)
            obj = make_mesh('Selected')
            select(obj)
            self.assertEqual(bpy.ops.ho.stl_export(filepath=str(self.root / 'operator.stl')),
                             {'FINISHED'})
            self.assertEqual(len(read_stl(self.root / 'operator.stl')), 1)
        finally:
            StlExporter.unregister()


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
