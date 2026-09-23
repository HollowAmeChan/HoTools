"""Edit-mode cleanup for spike vertices and collapsed (near-coincident) vertices.

Unlike the corrective-smooth operator this one needs **no reference state**: the
problems are self-evident from the local neighbourhood.

Two independent detectors, deliberately kept apart because their natural
thresholds live on different scales:

* **Spike / outlier vertex** -- a vertex that sticks far out of its own 1-ring and
  makes the silhouette read as a needle.  Measured *scale free* as
  ``|v - ring_centroid|`` compared with the same quantity of the neighbours,
  using a leave-one-out centroid so a spike cannot hide behind its own
  neighbours.  The correction is a clamp along the umbrella direction: only the
  excess over the threshold is removed, so smooth geometry is left untouched.
* **Collapsed / near-coincident vertex** -- an edge far shorter than the mesh's
  own average edge length.  The correction is an edge-length equalisation push
  projected into the tangent plane, so the silhouette does not move.

Spike repair acts along the umbrella (mostly normal) direction and collapse
repair acts in the tangent plane, so the two motions are orthogonal and do not
fight each other even though they react to the same neighbourhood.
"""

import bmesh
import bpy
import numpy as np
from bpy.props import BoolProperty, FloatProperty, IntProperty

from Utils.hud import draw_mouse_hud_rows


_ZERO_EPS = 1.0e-30

# Wheel steps and ranges for the modal interaction.
_SPIKE_STEP = 0.1
_SHORT_STEP = 0.002
_STRENGTH_STEP = 0.05
_SPIKE_RANGE = (1.0, 20.0)
_SHORT_RANGE = (0.001, 0.5)
_STRENGTH_RANGE = (0.0, 1.0)
_ITERATION_RANGE = (1, 50)

_DEFAULTS = {
    "spike_threshold": 2.0,
    "short_threshold": 0.08,
    "strength": 1.0,
    "iterations": 3,
    "fix_spikes": True,
    "fix_short_edges": True,
    "anchor_selection": True,
}


# A cancelled modal or a module reload can leak the HUD draw handler; track the
# handles globally like `offset_edges_modal` does so a later run can clean up.
_HUD_NAMESPACE_KEY = "hotools_singularity_smooth_hud_handles"
_ACTIVE_HUD_HANDLES = bpy.app.driver_namespace.setdefault(
    _HUD_NAMESPACE_KEY,
    set(),
)


def cleanup_singularity_smooth_huds():
    """Remove HUD draw handlers left behind by a reload or a hard cancel."""
    for handle in list(_ACTIVE_HUD_HANDLES):
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except (AttributeError, RuntimeError, TypeError, ReferenceError):
            pass
        _ACTIVE_HUD_HANDLES.discard(handle)


def _read_coords(vertices, count):
    buffer = np.empty(count * 3, dtype=np.float32)
    try:
        vertices.foreach_get("co", buffer)
    except (AttributeError, TypeError, RuntimeError):
        for index, vert in enumerate(vertices):
            buffer[index * 3:index * 3 + 3] = vert.co[:]
    return buffer.reshape(count, 3).astype(np.float64)


def _write_coords(vertices, coords):
    buffer = np.ascontiguousarray(coords, dtype=np.float32).ravel()
    try:
        vertices.foreach_set("co", buffer)
    except (AttributeError, TypeError, RuntimeError):
        for index, vert in enumerate(vertices):
            coords_list = coords[index].tolist()
            vertices[index].co = coords_list


def _normalize_inplace(vectors):
    lengths = np.linalg.norm(vectors, axis=1)
    np.divide(
        vectors, lengths[:, None], out=vectors,
        where=lengths[:, None] > _ZERO_EPS,
    )


def _loop_tables(mesh):
    """Per-corner vertex, next-vertex and owning-face index arrays."""
    loop_count = len(mesh.loops)
    corner_verts = np.empty(loop_count, dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", corner_verts)
    corner_verts = corner_verts.astype(np.int64)

    face_count = len(mesh.polygons)
    starts = np.empty(face_count, dtype=np.int32)
    totals = np.empty(face_count, dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", starts)
    mesh.polygons.foreach_get("loop_total", totals)
    starts = starts.astype(np.int64)
    totals = totals.astype(np.int64)

    indices = np.arange(loop_count, dtype=np.int64)
    first = np.repeat(starts, totals)
    size = np.repeat(totals, totals)
    following = np.where(indices - first == size - 1, first, indices + 1)
    loop_face = np.repeat(np.arange(face_count, dtype=np.int64), totals)
    return corner_verts, corner_verts[following], loop_face


class _DefectSolver:
    """Caches the topology and per-iteration neighbourhoods."""

    def __init__(self, obj):
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.verts.ensure_lookup_table()
        self.obj = obj
        self.vert_count = len(bm.verts)
        if len(mesh.vertices) != self.vert_count:
            raise RuntimeError("网格数据与编辑网格的顶点数不一致，无法计算")

        self.original = _read_coords(bm.verts, self.vert_count)
        self.selected = np.fromiter(
            (bool(vert.select) and not vert.hide for vert in bm.verts),
            dtype=bool, count=self.vert_count,
        )
        self.movable = bool(self.selected.any())

        edge_count = len(mesh.edges)
        if edge_count:
            edges = np.empty(edge_count * 2, dtype=np.int32)
            mesh.edges.foreach_get("vertices", edges)
            edges = edges.reshape(edge_count, 2).astype(np.int64)
        else:
            edges = np.empty((0, 2), dtype=np.int64)
        self.edges = edges

        self.corner_verts, self.next_verts, self.loop_face = _loop_tables(mesh)
        self.face_count = len(mesh.polygons)

        # Global edge-length scale, frozen so the collapse threshold never
        # drifts while the operator is running.
        if edge_count:
            lengths = np.linalg.norm(
                self.original[edges[:, 1]] - self.original[edges[:, 0]], axis=1)
            self.mean_edge = float(lengths.mean())
        else:
            self.mean_edge = 0.0

        self._key = None
        self._state = None
        self._stats = (0, 0)

    # -- neighbourhoods ----------------------------------------------------

    def _neighbours(self, coords):
        """Ring centroid, spike-proof local scale, normals and edge data.

        ``ring_scale[v]`` is the average, over v's neighbours, of that
        neighbour's mean edge length *measured without the edge to v*.  Using
        the vertex's own edges would defeat the spike test: a spike stretches
        its own incident edges, so ``|v - centroid| / own_edge_length`` is
        bounded by 1 no matter how long the spike is.  Leaving the offending
        edge out keeps the reference at the mesh's normal edge length, while
        still adapting to locally finer or coarser regions.
        """
        first, second = self.edges[:, 0], self.edges[:, 1]
        edge_vec = coords[second] - coords[first]
        edge_len = np.linalg.norm(edge_vec, axis=1)
        edge_count = len(self.edges)

        count = (
            np.bincount(first, minlength=self.vert_count)
            + np.bincount(second, minlength=self.vert_count)).astype(np.float64)

        total = np.zeros((self.vert_count, 3))
        for axis in range(3):
            total[:, axis] = (
                np.bincount(first, weights=coords[second][:, axis],
                            minlength=self.vert_count)
                + np.bincount(second, weights=coords[first][:, axis],
                              minlength=self.vert_count))
        length_sum = np.zeros(self.vert_count)
        np.add.at(length_sum, first, edge_len)
        np.add.at(length_sum, second, edge_len)

        safe = np.where(count > 0.0, count, 1.0)
        centroid = total / safe[:, None]

        if edge_count:
            leave_one_out = np.empty(edge_count * 2)
            for step, (a, b) in enumerate(((first, second), (second, first))):
                divisor = np.maximum(count[a] - 1.0, 1.0)
                leave_one_out[step * edge_count:(step + 1) * edge_count] = (
                    (length_sum[a] - edge_len) / divisor)
            scale_sum = np.bincount(
                np.concatenate((second, first)), weights=leave_one_out,
                minlength=self.vert_count)
            ring_scale = scale_sum / safe
        else:
            ring_scale = np.zeros(self.vert_count)

        # Area-weighted vertex normals from the edit cage itself (the mesh
        # datablock normals would describe the Basis, not the cage).
        crosses = np.cross(coords[self.corner_verts], coords[self.next_verts])
        face_normal = np.empty((self.face_count, 3))
        for axis in range(3):
            face_normal[:, axis] = np.bincount(
                self.loop_face, weights=crosses[:, axis],
                minlength=self.face_count)
        vertex_normal = np.empty((self.vert_count, 3))
        for axis in range(3):
            vertex_normal[:, axis] = np.bincount(
                self.corner_verts, weights=face_normal[self.loop_face, axis],
                minlength=self.vert_count)
        _normalize_inplace(vertex_normal)
        return centroid, ring_scale, vertex_normal, edge_len

    def _spike_excess(self, coords, centroid, ring_scale, threshold):
        """Clamp ``|v - ring_centroid|`` to ``threshold * ring_scale``.

        The metric is scale free (a 1 mm model and a 1 m model behave
        identically), predictable ("a spike taller than N local edges is clamped
        back to N local edges") and idempotent, so the converged result does not
        drift with the iteration count.
        """
        deviation = np.linalg.norm(coords - centroid, axis=1)
        limit = threshold * ring_scale
        active = (deviation > limit) & (limit > 0.0)
        delta = np.zeros_like(coords)
        usable = active & (deviation > _ZERO_EPS)
        scale = np.zeros(self.vert_count)
        scale[usable] = 1.0 - limit[usable] / deviation[usable]
        delta[usable] = (centroid[usable] - coords[usable]) * scale[usable, None]
        return delta, int(active.sum())

    def _collapse_delta(self, coords, normal, edge_len, limit):
        """Push the endpoints of too-short edges apart, tangentially."""
        first, second = self.edges[:, 0], self.edges[:, 1]
        short = edge_len < limit
        if not short.any():
            return np.zeros_like(coords), 0

        index = np.nonzero(short)[0]
        a, b = first[index], second[index]
        length = np.maximum(edge_len[index], _ZERO_EPS)
        direction = (coords[b] - coords[a]) / length[:, None]
        push = 0.5 * (limit - edge_len[index])[:, None] * direction

        total = np.zeros_like(coords)
        count = np.zeros(self.vert_count)
        for target, amount in ((a, -push), (b, push)):
            for axis in range(3):
                total[:, axis] += np.bincount(
                    target, weights=amount[:, axis], minlength=self.vert_count)
            count += np.bincount(target, minlength=self.vert_count)
        safe = np.where(count > 0.0, count, 1.0)
        total /= safe[:, None]

        # Keep the motion in the tangent plane so the silhouette is preserved.
        total -= normal * np.einsum('ij,ij->i', total, normal)[:, None]
        reached = np.unique(np.concatenate((a, b)))
        return total, int(reached.size)

    # -- evaluation --------------------------------------------------------

    def _refresh(self, spike_threshold, short_threshold, iterations,
                 fix_spikes, fix_short_edges, anchor_selection):
        coords = self.original.copy()
        anchored = self.selected if anchor_selection else np.ones(
            self.vert_count, dtype=bool)
        limit = short_threshold * self.mean_edge
        spikes = collapapsed = 0
        for _ in range(iterations):
            centroid, ring_scale, normal, edge_len = self._neighbours(coords)
            move = np.zeros_like(coords)
            if fix_spikes:
                delta, spikes = self._spike_excess(
                    coords, centroid, ring_scale, spike_threshold)
                move += delta
            if fix_short_edges and limit > 0.0:
                delta, collapapsed = self._collapse_delta(
                    coords, normal, edge_len, limit)
                move += delta
            coords = coords + move
            coords[~anchored] = self.original[~anchored]
        self._state = coords
        self._stats = (spikes, collapapsed)
        self._key = (float(spike_threshold), float(short_threshold),
                     int(iterations), bool(fix_spikes), bool(fix_short_edges),
                     bool(anchor_selection))

    def stats(self):
        return self._stats

    def short_limit(self, short_threshold):
        return short_threshold * self.mean_edge

    def evaluate(self, spike_threshold, short_threshold, strength, iterations,
                 fix_spikes, fix_short_edges, anchor_selection):
        key = (float(spike_threshold), float(short_threshold), int(iterations),
               bool(fix_spikes), bool(fix_short_edges), bool(anchor_selection))
        if key != self._key:
            self._refresh(spike_threshold, short_threshold, iterations,
                          fix_spikes, fix_short_edges, anchor_selection)
        result = self.original + (self._state - self.original) * strength
        # Never write outside the selection, even when the boundary is not
        # anchored, so the operator always stays local.
        result[~self.selected] = self.original[~self.selected]
        return result


def _clamp(value, limits, digits=4):
    return round(max(limits[0], min(limits[1], value)), digits)


def _adjust_parameters(operator, event):
    """Apply one modal wheel/key event; returns True when something changed."""
    if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
        direction = 1.0 if event.type == 'WHEELUPMOUSE' else -1.0
        if event.shift:
            operator.short_threshold = _clamp(
                operator.short_threshold + direction * _SHORT_STEP,
                _SHORT_RANGE, 4)
        elif event.ctrl:
            operator.strength = _clamp(
                operator.strength + direction * _STRENGTH_STEP,
                _STRENGTH_RANGE)
        else:
            operator.spike_threshold = _clamp(
                operator.spike_threshold + direction * _SPIKE_STEP,
                _SPIKE_RANGE)
        return True

    if event.value != 'PRESS':
        return False

    if event.type in {'LEFT_BRACKET', 'RIGHT_BRACKET'}:
        step = -1 if event.type == 'LEFT_BRACKET' else 1
        operator.iterations = int(_clamp(
            operator.iterations + step, _ITERATION_RANGE, 0))
        return True
    if event.type == 'T':
        operator.fix_spikes = not operator.fix_spikes
        return True
    if event.type == 'B':
        operator.fix_short_edges = not operator.fix_short_edges
        return True
    if event.type == 'V':
        operator.anchor_selection = not operator.anchor_selection
        return True
    if event.type == 'R':
        for name, value in _DEFAULTS.items():
            setattr(operator, name, value)
        return True
    return False


class HO_OT_MeshSingularitySmooth(bpy.types.Operator):
    """Pull spike vertices back onto the surface and separate collapsed points."""

    bl_idname = "ho.mesh_singularity_smooth"
    bl_label = "奇异点平滑"
    bl_description = (
        "修整两类网格瑕疵：突出成尖刺的顶点，以及过近叠在一起的点。"
        "阈值按局部尺度自适应，未超阈值的地方完全不动"
    )
    bl_options = {'REGISTER', 'UNDO'}

    spike_threshold: FloatProperty(
        name="突刺阈值", default=_DEFAULTS["spike_threshold"],
        min=1.0, max=20.0, soft_max=6.0, precision=2,
        description="顶点偏离 1 环中心超过「局部边长 × 此值」就算突刺，"
                    "并被夹回该距离；越大越保守（平滑球面约 0.1，直角折边约 0.7）",
    )  # type: ignore
    short_threshold: FloatProperty(
        name="叠点阈值", default=_DEFAULTS["short_threshold"],
        min=0.001, max=0.5, soft_max=0.3, precision=4,
        description="短于「网格平均边长 × 此值」的边视为叠点；阈值与突刺完全独立",
    )  # type: ignore
    strength: FloatProperty(
        name="强度", default=_DEFAULTS["strength"],
        min=0.0, max=1.0, subtype='FACTOR',
    )  # type: ignore
    iterations: IntProperty(
        name="迭代", default=_DEFAULTS["iterations"],
        min=1, max=50, soft_max=20,
    )  # type: ignore
    fix_spikes: BoolProperty(
        name="修突刺", default=_DEFAULTS["fix_spikes"])  # type: ignore
    fix_short_edges: BoolProperty(
        name="修叠点", default=_DEFAULTS["fix_short_edges"])  # type: ignore
    anchor_selection: BoolProperty(
        name="固定选区边界", default=_DEFAULTS["anchor_selection"],
        description="开启时选区之外完全不动，只作为邻域参考",
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "active_object", None)
        return (
            obj is not None and obj.type == 'MESH'
            and getattr(context, "mode", None) == 'EDIT_MESH'
        )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "fix_spikes")
        layout.prop(self, "spike_threshold")
        layout.prop(self, "fix_short_edges")
        layout.prop(self, "short_threshold")
        layout.prop(self, "strength")
        layout.prop(self, "iterations")
        layout.prop(self, "anchor_selection")
        layout.label(text="两个阈值互相独立：突刺按相对偏离，叠点按边长")

    # -- HUD ---------------------------------------------------------------

    def _hud_rows(self):
        spikes, collapsed = self._stats
        limit = self._solver.short_limit(self.short_threshold)
        rows = [
            (0, "奇异点平滑", "突刺 {} 点 · 叠点 {} 点".format(spikes, collapsed)),
            (24, "滚轮：", f"突刺阈值 {self.spike_threshold:.2f}×"),
            (48, "Shift+滚轮：",
             f"叠点阈值 {self.short_threshold:.4f}×均边 = {limit:.5f}"),
            (72, "Ctrl+滚轮：", f"强度 {self.strength:.2f}"),
            (96, "[ / ]：", f"迭代 {self.iterations}"),
            (120, "T：", "修突刺 {}".format("开" if self.fix_spikes else "关")),
            (144, "B：", "修叠点 {}".format(
                "开" if self.fix_short_edges else "关")),
            (168, "V：", "固定选区边界 {}".format(
                "开" if self.anchor_selection else "关")),
            (192, "R：", "重置参数"),
            (216, "左键 / 回车：", "确认"),
            (240, "右键 / Esc：", "取消"),
        ]
        return rows

    def draw_text(self):
        try:
            draw_mouse_hud_rows(
                (self._mouse_x, self._mouse_y), self._hud_rows(),
                offset=24, size=15)
        except (AttributeError, RuntimeError, TypeError, ValueError,
                ReferenceError):
            pass

    def _tag_redraw(self, context):
        area = getattr(context, "area", None)
        if area is not None:
            try:
                area.tag_redraw()
            except (AttributeError, ReferenceError, RuntimeError):
                pass

    def _install_hud(self):
        if self._handle_text is not None:
            return
        cleanup_singularity_smooth_huds()
        try:
            self._handle_text = bpy.types.SpaceView3D.draw_handler_add(
                self.draw_text, (), "WINDOW", "POST_PIXEL")
            _ACTIVE_HUD_HANDLES.add(self._handle_text)
        except (AttributeError, RuntimeError, TypeError, ReferenceError):
            self._handle_text = None

    def _remove_hud(self):
        handle = self._handle_text
        self._handle_text = None
        if handle is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
            except (AttributeError, RuntimeError, TypeError, ReferenceError):
                pass
            _ACTIVE_HUD_HANDLES.discard(handle)

    # -- internals ---------------------------------------------------------

    def _build_solver(self, context):
        active = context.active_object
        bm = bmesh.from_edit_mesh(active.data)
        bm.verts.ensure_lookup_table()
        try:
            solver = _DefectSolver(active)
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return None, None
        if not solver.movable:
            self.report({'WARNING'}, "请先选择要修整的顶点")
            return None, None
        return bm, solver

    def _write(self, context, target):
        # The edit BMesh can be recreated behind our back (mode switch, undo,
        # another operator, F9 repeat); cached element references then point at
        # removed data, so re-acquire it every time.  Edit mode preserves vertex
        # order, so index based writes and the cached arrays stay valid.
        obj = self._obj
        if obj is None:
            raise RuntimeError("对象已失效")
        if getattr(obj, "mode", None) != 'EDIT':
            raise RuntimeError("对象已不在编辑模式")
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        if len(bm.verts) != len(target):
            raise RuntimeError(
                "网格顶点数已变化（%d -> %d），无法写回" % (len(target), len(bm.verts)))
        _write_coords(bm.verts, target)
        bm.normal_update()
        bmesh.update_edit_mesh(
            obj.data, loop_triangles=False, destructive=False)
        self._bm = bm
        self._tag_redraw(context)

    def _apply(self, context):
        try:
            target = self._solver.evaluate(
                self.spike_threshold, self.short_threshold, self.strength,
                self.iterations, self.fix_spikes, self.fix_short_edges,
                self.anchor_selection)
            self._write(context, target)
        except (AttributeError, RuntimeError, TypeError, ValueError,
                ReferenceError) as error:
            self.report({'WARNING'}, f"奇异点平滑失败: {error}")
            return False
        return True

    def _cancel(self, context):
        try:
            self._write(context, self._solver.original)
        except (AttributeError, RuntimeError, TypeError, ValueError,
                ReferenceError) as error:
            # Never fail mute: the preview may still be applied.
            self.report({'WARNING'}, f"取消时未能还原网格: {error}")
        self._remove_hud()
        self._tag_redraw(context)
        return {'CANCELLED'}

    def _finish(self, context):
        self._remove_hud()
        self._tag_redraw(context)
        return {'FINISHED'}

    # -- operator ----------------------------------------------------------

    def _start(self, context):
        bm, solver = self._build_solver(context)
        if solver is None:
            return False
        self._obj = context.active_object
        self._source_object = self._obj
        self._bm = bm
        self._solver = solver
        self._handle_text = None
        self._stats = (0, 0)
        return True

    def invoke(self, context, event):
        if not self._start(context):
            return {'CANCELLED'}
        self._mouse_x = event.mouse_region_x
        self._mouse_y = event.mouse_region_y
        if not self._apply(context):
            return self._cancel(context)
        self._install_hud()
        context.window_manager.modal_handler_add(self)
        self._tag_redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if context.active_object is not self._source_object:
            return self._cancel(context)
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            return self._cancel(context)
        if event.type in {'RET', 'NUMPAD_ENTER', 'LEFTMOUSE', 'SPACE'} \
                and event.value == 'PRESS':
            return self._finish(context)

        if event.type == 'MOUSEMOVE':
            # The HUD follows the cursor; the mouse never edits a value.
            self._mouse_x = event.mouse_region_x
            self._mouse_y = event.mouse_region_y
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if _adjust_parameters(self, event):
            if not self._apply(context):
                return self._cancel(context)
            self._tag_redraw(context)

        if event.type in {'MIDDLEMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM',
                          'NDOF_MOTION'} or event.type.startswith('NDOF'):
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self._start(context):
            return {'CANCELLED'}
        if not self._apply(context):
            return {'CANCELLED'}
        return {'FINISHED'}


HO_SINGULARITY_CLASSES = (HO_OT_MeshSingularitySmooth,)


__all__ = [
    "HO_OT_MeshSingularitySmooth",
    "HO_SINGULARITY_CLASSES",
    "cleanup_singularity_smooth_huds",
]
