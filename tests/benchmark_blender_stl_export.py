"""Real Blender STL timings; not a test with machine-dependent time assertions.

blender --background --factory-startup --python benchmark_blender_stl_export.py
    -- --baseline <saved StlExporter.py> --repeat 3

Native uses merged export because its batch output does not group GN instances
by Blender object. All implementations must write the same total facet count.
"""

import argparse
import importlib.util
import json
import statistics
import struct
import sys
import tempfile
import time
from pathlib import Path

import bpy


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Exporter import StlExporter


def build_scene(grid_size, instances):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if grid_size:
        bpy.ops.mesh.primitive_grid_add(x_subdivisions=grid_size,
                                       y_subdivisions=grid_size, size=1)
    else:
        bpy.ops.mesh.primitive_cube_add(size=1)
    source = bpy.context.object
    if not instances:
        bpy.context.view_layer.update()
        return
    collection = bpy.data.collections.new('Sources')
    collection.objects.link(source)
    bpy.context.scene.collection.objects.unlink(source)
    group = bpy.data.node_groups.new('Benchmark GN', 'GeometryNodeTree')
    group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    output = group.nodes.new('NodeGroupOutput')
    points = group.nodes.new('GeometryNodeMeshLine')
    points.inputs['Count'].default_value = instances
    points.inputs['Offset'].default_value = (2, 0, 0)
    info = group.nodes.new('GeometryNodeCollectionInfo')
    info.inputs['Collection'].default_value = collection
    instance = group.nodes.new('GeometryNodeInstanceOnPoints')
    group.links.new(info.outputs['Instances'], instance.inputs['Instance'])
    group.links.new(points.outputs['Mesh'], instance.inputs['Points'])
    group.links.new(instance.outputs['Instances'], output.inputs['Geometry'])
    for i in range(2):
        obj = bpy.data.objects.new(f'Owner_{i}', bpy.data.meshes.new(f'OwnerMesh_{i}'))
        bpy.context.scene.collection.objects.link(obj)
        obj.location.y = i * 10
        obj.modifiers.new('GN', 'NODES').node_group = group
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    bpy.context.view_layer.update()


def facet_count(paths, ascii_format):
    count = 0
    for path in paths:
        with open(path, 'rb') as stream:
            if ascii_format:
                count += sum(line.lstrip().startswith(b'facet normal') for line in stream)
            else:
                stream.seek(80)
                count += struct.unpack('<I', stream.read(4))[0]
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline')
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--ascii', action='store_true')
    parser.add_argument('--case', choices=('dense', 'gn_dense', 'gn_small'))
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    exporters = {'optimized': StlExporter}
    if args.baseline:
        spec = importlib.util.spec_from_file_location('hostl_baseline', args.baseline)
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        exporters = {'baseline': baseline, **exporters}
    report = {'blender': bpy.app.version_string, 'ascii': args.ascii, 'cases': {}}
    with tempfile.TemporaryDirectory(prefix='hostl_bench_') as temporary:
        root = Path(temporary)
        for name, grid_size, instances in (('dense', 512, 0), ('gn_dense', 128, 8),
                                            ('gn_small', 0, 2000)):
            if args.case and name != args.case:
                continue
            build_scene(grid_size, instances)
            result = {}
            counts = set()
            for label in (*exporters, 'native'):
                samples = []
                output = root / label
                output.mkdir(exist_ok=True)
                paths = []
                # Warm up dependency-graph and triangulation caches separately.
                for trial in range(args.repeat + 1):
                    started = time.perf_counter()
                    if label == 'native':
                        path = output / 'native.stl'
                        bpy.ops.wm.stl_export(filepath=str(path), export_selected_objects=True,
                                              ascii_format=args.ascii,
                                              global_scale=1, use_scene_unit=False, use_batch=False)
                        paths = [path]
                    else:
                        paths, _ = exporters[label].export_stl(
                            bpy.context, str(output / 'export.stl'), convert_units=False,
                            ascii_format=args.ascii,
                            use_batch=bool(instances))
                    elapsed = time.perf_counter() - started
                    if trial:
                        samples.append(elapsed)
                count = facet_count(paths, args.ascii)
                counts.add(count)
                result[label] = {'seconds': round(statistics.median(samples), 6),
                                 'triangles': count, 'files': len(paths)}
            assert len(counts) == 1, result
            report['cases'][name] = result
            print('BENCH_CASE ' + json.dumps({name: result}), flush=True)
    print('BENCH_RESULT ' + json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
