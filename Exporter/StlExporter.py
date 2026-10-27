"""Selection-only STL export, grouped by the original instancing object.

Read evaluated geometry without applying operators or modifying authored data.
In particular, never use Blender's STL batch mode: it batches dependency-graph
instances, rather than the selected Blender objects that own those instances.
"""

import os
import re
import struct
import tempfile
import traceback
from collections import OrderedDict
from contextlib import ExitStack, contextmanager
from itertools import chain

import bpy
import numpy as np
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper
from mathutils import Matrix


MESH_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}
_STL_DTYPE = np.dtype([
    ('normal', '<f4', (3,)), ('vertices', '<f4', (3, 3)), ('attribute', '<u2'),
])
_CHUNK_TRIANGLES = 65_536
_GEOMETRY_CACHE_BYTES = 128 * 1024 * 1024
_ASCII_FACET = ('  facet normal %.9g %.9g %.9g\n    outer loop\n'
                '      vertex %.9g %.9g %.9g\n      vertex %.9g %.9g %.9g\n'
                '      vertex %.9g %.9g %.9g\n    endloop\n  endfacet')


def _base_geometry(obj, matrix, ancestors=frozenset()):
    """Unmodified geometry, including ordinary collection instances, without GN."""
    if obj.type in MESH_TYPES:
        yield obj, matrix
    collection = obj.instance_collection if obj.instance_type == 'COLLECTION' else None
    if collection is None or collection.as_pointer() in ancestors:
        return
    ancestors = ancestors | {collection.as_pointer()}
    transform = matrix @ Matrix.Translation(-collection.instance_offset)
    for child in collection.all_objects:
        if not child.hide_viewport:
            yield from _base_geometry(child, transform @ child.matrix_world, ancestors)


def iter_geometry(context, selection, apply_modifiers):
    """Consume each object before advancing the iterator.

    GN's instance.object can itself be a temporary evaluated object. Keeping that
    reference for later silently loses instance geometry/modifiers in Blender 4.5.
    """
    owners = {obj.as_pointer() for obj in selection}
    depsgraph = context.evaluated_depsgraph_get()
    if not apply_modifiers:
        for obj in selection:
            for source, matrix in _base_geometry(
                    obj, obj.evaluated_get(depsgraph).matrix_world.copy()):
                yield obj.as_pointer(), source, matrix
        return

    for instance in depsgraph.object_instances:
        owner = instance.parent if instance.is_instance else instance.object
        if owner is None:
            continue
        key = owner.original.as_pointer()
        if key not in owners or not instance.show_self:
            continue
        obj = instance.object
        if obj.type in MESH_TYPES:
            yield key, obj, instance.matrix_world.copy()


def _mesh_corners(mesh):
    """Copy numeric data immediately, never retain a GN runtime object or Mesh."""
    mesh.calc_loop_triangles()
    coordinates = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    indices = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.vertices.foreach_get('co', coordinates)
    mesh.loop_triangles.foreach_get('vertices', indices)
    return coordinates.reshape(-1, 3)[indices].reshape(-1, 3, 3)


class _GeometryBatch:
    def __init__(self, corners, name):
        self.corners = corners
        self.name = name
        self.pending = {}
        self.batch_size = max(1, _CHUNK_TRIANGLES // max(1, len(corners)))

    def add(self, writer, matrix, scale):
        if not len(self.corners):
            return
        matrices = self.pending.setdefault(writer, [])
        matrices.append(matrix)
        if len(matrices) >= self.batch_size:
            writer.write_batch(self.corners, matrices, scale, self.name)
            matrices.clear()

    def flush(self, scale):
        for writer, matrices in self.pending.items():
            if matrices:
                writer.write_batch(self.corners, matrices, scale, self.name)
        self.pending.clear()


class GeometryCache:
    """Export-local bounded LRU of numeric snapshots, shared by all output files.

    A GN iterator reuses temporary Object wrappers, but its shared Mesh IDs have
    stable identity during this dependency-graph traversal. Include session_uid
    so even an allocator-reused address cannot alias an unrelated snapshot.
    Eviction writes pending instance batches before dropping their geometry.
    """

    def __init__(self, scale):
        self.scale = scale
        self.entries = OrderedDict()
        self.bytes = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        # On write failures pending batches hold writers which reference this
        # cache. Break that cycle and release large arrays immediately.
        self.entries.clear()
        self.bytes = 0

    def write_geometry(self, writer, obj, matrix):
        if obj.type != 'MESH':
            mesh = obj.to_mesh()
            try:
                if mesh is None:
                    return
                batch = _GeometryBatch(_mesh_corners(mesh), obj.name)
            finally:
                obj.to_mesh_clear()
            batch.add(writer, matrix, self.scale)
            batch.flush(self.scale)
            return
        mesh = obj.data
        key = (mesh.as_pointer(), mesh.session_uid)
        batch = self.entries.get(key)
        if batch is None:
            batch = _GeometryBatch(_mesh_corners(mesh), obj.name)
            # A single very large mesh may exceed the budget; keep that one
            # entry so repeated instances still reuse it, and evict the others.
            while self.entries and self.bytes + batch.corners.nbytes > _GEOMETRY_CACHE_BYTES:
                _old_key, old = self.entries.popitem(last=False)
                old.flush(self.scale)
                self.bytes -= old.corners.nbytes
            self.entries[key] = batch
            self.bytes += batch.corners.nbytes
        else:
            self.entries.move_to_end(key)
        batch.add(writer, matrix, self.scale)

    def flush(self):
        for batch in self.entries.values():
            batch.flush(self.scale)


class STLWriter:
    """Stream facets without retaining GN iterator objects or merging Mesh data."""

    def __init__(self, stream, ascii_format, cache):
        self.stream = stream
        self.ascii_format = ascii_format
        self.count = 0
        self.cache = cache
        if ascii_format:
            stream.write(b'solid HoSTL\n')
        else:
            stream.write(b'HoTools STL'.ljust(80, b'\0'))
            stream.write(struct.pack('<I', 0))

    def write_geometry(self, obj, matrix):
        self.cache.write_geometry(self, obj, matrix)

    def write_batch(self, corners, matrices, scale, name):
        # Matrix has no array buffer: np.asarray recursively inspects its row
        # Vectors and dominates small-instance exports. Iterate scalar values
        # once instead (about 8x faster for thousands of Blender matrices).
        transforms = np.fromiter(
            chain.from_iterable(chain.from_iterable(matrices)),
            dtype=np.float32, count=len(matrices) * 16,
        ).reshape(-1, 4, 4)
        mirrored = np.linalg.det(transforms[:, :3, :3]) < 0
        for start in range(0, len(corners), _CHUNK_TRIANGLES):
            local = corners[start:start + _CHUNK_TRIANGLES]
            # Shape: (instances, triangles, vertices, xyz). All facet work runs
            # in NumPy; Python never visits individual binary-STL triangles.
            with np.errstate(over='ignore', invalid='ignore'):
                vertices = (local.reshape(1, -1, 3) @ transforms[:, :3, :3].swapaxes(1, 2))
                vertices = vertices.reshape(len(matrices), len(local), 3, 3)
                vertices += transforms[:, None, None, :3, 3]
                vertices *= scale
                if mirrored.any():
                    vertices[mirrored] = vertices[mirrored, :, ::-1, :]
                normals = np.cross(vertices[:, :, 1] - vertices[:, :, 0],
                                   vertices[:, :, 2] - vertices[:, :, 0])
                lengths = np.sqrt(np.einsum('mti,mti->mt', normals, normals))
                np.divide(normals, lengths[:, :, None], out=normals,
                          where=lengths[:, :, None] != 0)
            if not np.isfinite(vertices).all():
                raise ValueError(f'物体“{name}”包含无效的顶点坐标')
            if not np.isfinite(normals).all():
                raise ValueError(f'物体“{name}”包含无效的三角面法线')
            count = vertices.shape[0] * vertices.shape[1]
            if self.ascii_format:
                values = np.concatenate((normals.reshape(-1, 3), vertices.reshape(-1, 9)), axis=1)
                np.savetxt(self.stream, values, fmt=_ASCII_FACET)
            else:
                records = np.empty(count, dtype=_STL_DTYPE)
                records['normal'] = normals.reshape(-1, 3)
                records['vertices'] = vertices.reshape(-1, 3, 3)
                records['attribute'] = 0
                self.stream.write(memoryview(records).cast('B'))
            self.count += count

    def finish(self):
        if self.ascii_format:
            self.stream.write(b'endsolid HoSTL\n')
        else:
            self.stream.seek(80)
            self.stream.write(struct.pack('<I', self.count))


def batch_paths(directory, selection):
    """Keep filenames safe and distinct on Windows, even after sanitization."""
    used = set()
    for obj in selection:
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', obj.name).strip(' .') or 'Object'
        if re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]', name.split('.')[0], re.I):
            name = '_' + name
        # Leave room for the extension and disambiguation suffix.
        name = name[:180].rstrip(' .')
        candidate = name
        suffix = 1
        while candidate.casefold() in used:
            candidate = f'{name}_{suffix:03d}'
            suffix += 1
        used.add(candidate.casefold())
        yield os.path.join(directory, candidate + '.stl')


@contextmanager
def staged_files():
    """Finish every file before replacing destinations; always remove leftovers."""
    pending = []
    try:
        yield pending
        for temporary, destination in pending:
            os.replace(temporary, destination)
    finally:
        for temporary, _destination in pending:
            if os.path.exists(temporary):
                os.unlink(temporary)


def export_stl(context, filepath, *, ascii_format=False, use_batch=False,
               convert_units=True, apply_modifiers=True):
    selection = sorted(context.selected_objects, key=lambda obj: obj.name)
    if not selection:
        raise ValueError('请先选中需要导出的物体')
    if context.mode != 'OBJECT':
        raise ValueError('请在物体模式下导出 STL')
    if not filepath or not os.path.basename(filepath):
        raise ValueError('请选择 STL 文件路径')
    filepath = bpy.path.ensure_ext(os.path.abspath(bpy.path.abspath(filepath)), '.stl')
    directory = os.path.dirname(filepath)
    if use_batch:
        destinations = dict(zip((obj.as_pointer() for obj in selection),
                                batch_paths(directory, selection)))
    else:
        destinations = {obj.as_pointer(): filepath for obj in selection}
    written = []
    skipped = []
    with staged_files() as pending:
        writers = {}
        with GeometryCache(100.0 if convert_units else 1.0) as cache, ExitStack() as streams:
            for owner, obj, matrix in iter_geometry(context, selection, apply_modifiers):
                destination = destinations[owner]
                if destination not in writers:
                    descriptor, temporary = tempfile.mkstemp(
                        prefix='.hostl_', suffix='.tmp', dir=directory)
                    pending.append((temporary, destination))
                    stream = streams.enter_context(os.fdopen(descriptor, 'wb'))
                    writers[destination] = STLWriter(stream, ascii_format, cache)
                writers[destination].write_geometry(obj, matrix)
            cache.flush()
            for writer in writers.values():
                writer.finish()
        for temporary, destination in pending[:]:
            if not writers[destination].count:
                os.unlink(temporary)
                pending.remove((temporary, destination))
            else:
                written.append(destination)
        if use_batch:
            skipped = [obj.name for obj in selection if destinations[obj.as_pointer()] not in written]
        if not written:
            raise ValueError('选中的物体没有可导出的三角面；关闭应用修改器时不会导出 GN 生成的实例')
    return written, skipped


class OP_HoSTLExport(Operator, ExportHelper):
    bl_idname = 'ho.stl_export'
    bl_label = 'HoSTL导出'
    bl_description = '只导出选中物体，GN 实例按所属 Blender 物体合并'
    bl_options = {'PRESET'}

    filename_ext = '.stl'
    filter_glob: StringProperty(default='*.stl', options={'HIDDEN'})
    ascii_format: BoolProperty(name='ASCII格式', default=False)
    use_batch: BoolProperty(
        name='按物体分批', default=False,
        description='关闭：合并为一个 STL；开启：在所选目录按物体名导出，每个物体的全部 GN 实例写入同一文件',
    )
    convert_units: BoolProperty(
        name='单位转化', default=True,
        description='导出坐标乘以 100（包含世界位置），不额外乘场景单位比例',
    )
    apply_modifiers: BoolProperty(
        name='应用修改器', default=True,
        description='对所有导出物体读取视口启用的完整修改器栈（包括 GN 与实例源物体），不修改原场景；关闭则导出基础几何',
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        for prop in ('ascii_format', 'use_batch', 'convert_units', 'apply_modifiers'):
            layout.prop(self, prop)
        layout.label(text='仅导出选中物体')
        if self.use_batch:
            layout.label(text='文件名：物体名.stl')

    def execute(self, context):
        try:
            written, skipped = export_stl(
                context, self.filepath, ascii_format=self.ascii_format,
                use_batch=self.use_batch, convert_units=self.convert_units,
                apply_modifiers=self.apply_modifiers,
            )
        except Exception as exc:
            traceback.print_exc()
            self.report({'ERROR'}, f'HoSTL 导出失败：{exc}')
            return {'CANCELLED'}
        if skipped:
            self.report({'WARNING'}, '跳过没有三角面的物体：' + '、'.join(skipped))
        self.report({'INFO'}, f'HoSTL 已导出 {len(written)} 个文件')
        return {'FINISHED'}


def menu_export(self, context):
    self.layout.operator_context = 'INVOKE_DEFAULT'
    self.layout.operator(OP_HoSTLExport.bl_idname, text='HoSTL (.stl)')


def register():
    bpy.utils.register_class(OP_HoSTLExport)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    bpy.utils.unregister_class(OP_HoSTLExport)
