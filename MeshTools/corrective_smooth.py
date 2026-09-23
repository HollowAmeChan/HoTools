"""Edit-mode local corrective smooth (delta-mush) for meshes with shape keys.

Reference algorithm: Blender's Corrective Smooth modifier
(`source/blender/modifiers/intern/MOD_correctivesmooth.cc`).  The port here was
verified point-by-point against Blender 4.5.8 and agrees with the modifier to
float32 precision.  Key facts that are easy to get wrong:

* The modifier's RNA ``factor`` **is** the smoothing coefficient ``lambda``; it
  is not a generic modifier influence.
* Per corner the detail is stored in the *rest* tangent frame and restored in
  the *current* tangent frame (``T_rest`` forward, ``T_cur`` inverse).  Swapping
  those two breaks rigid-motion invariance.
* ``Original Coords`` reads the mesh datablock, so with shape keys the natural
  reference is the Basis while the edit cage holds the active shape key.
* delta-mush is exact when rest == deformed, so editing the Basis (or a mesh
  without shape keys) has nothing to correct and the operator refuses to run.

Unlike the modifier this operator is local: only selected vertices are written
and the rest of the mesh acts as a fixed anchor.
"""

import bmesh
import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty

from Utils.hud import draw_mouse_hud_rows


# `normalize_v3` treats an exact zero vector as "leave alone"; this threshold
# only guards against dividing by a denormal.
_ZERO_EPS = 1.0e-30

# Mirrors `FLT_EPSILON * 10.0` as used by `compare_v3v3` in the modifier.
_PARALLEL_EPS = float(np.finfo(np.float32).eps) * 10.0

# Mirrors the `div > FLT_EPSILON * 10.0` guard of the length-weighted smoother.
_LENGTH_DIV_EPS = float(np.finfo(np.float32).eps) * 10.0

# Wheel steps and the ranges they clamp to, matching the RNA property ranges.
_STRENGTH_STEP = 0.05
_SCALE_STEP = 0.05
_ITERATION_STEP = 1
_STRENGTH_RANGE = (0.0, 10.0)
_SCALE_RANGE = (-10.0, 10.0)
_ITERATION_RANGE = (0, 100)

_DEFAULTS = {
    "strength": 0.5,
    "iterations": 5,
    "scale": 1.0,
    "smooth_type": 'SIMPLE',
    "anchor_selection": True,
}

SMOOTH_TYPE_ITEMS = (
    ('SIMPLE', "简单", "邻接顶点均匀平均，对应内置修改器的 Simple"),
    ('LENGTH_WEIGHTED', "长度加权",
     "按边长加权，网格疏密不均时更稳，对应内置修改器的 Length Weight"),
)

SMOOTH_TYPE_LABELS = {
    'SIMPLE': "简单",
    'LENGTH_WEIGHTED': "长度加权",
}


# A modal operator that is cancelled mid-flight (or whose module is reloaded)
# can leak its draw handler; track the handles globally like
# `offset_edges_modal` does so a later run can clean them up.
_HUD_NAMESPACE_KEY = "hotools_corrective_smooth_hud_handles"
_ACTIVE_HUD_HANDLES = bpy.app.driver_namespace.setdefault(
    _HUD_NAMESPACE_KEY,
    set(),
)


def cleanup_corrective_smooth_huds():
    """Remove HUD draw handlers left behind by a reload or a hard cancel."""
    for handle in list(_ACTIVE_HUD_HANDLES):
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except (AttributeError, RuntimeError, TypeError, ReferenceError):
            pass
        _ACTIVE_HUD_HANDLES.discard(handle)


def _normalize_inplace(vectors):
    """Normalize each row, leaving (near) zero rows untouched."""
    lengths = np.linalg.norm(vectors, axis=1)
    np.divide(
        vectors, lengths[:, None], out=vectors,
        where=lengths[:, None] > _ZERO_EPS,
    )


def _read_coords(vertices, count):
    """Read ``count`` vertex coordinates as a float64 (count, 3) array."""
    buffer = np.empty(count * 3, dtype=np.float32)
    try:
        vertices.foreach_get("co", buffer)
    except (AttributeError, TypeError, RuntimeError):
        for index, vert in enumerate(vertices):
            buffer[index * 3:index * 3 + 3] = vert.co[:]
    return buffer.reshape(count, 3).astype(np.float64)


def _write_coords(vertices, coords):
    """Write a float64 (count, 3) array back to bmesh vertices."""
    buffer = np.ascontiguousarray(coords, dtype=np.float32).ravel()
    try:
        vertices.foreach_set("co", buffer)
    except (AttributeError, TypeError, RuntimeError):
        for index, vert in enumerate(vertices):
            vert.co = coords[index].tolist()


def _loop_neighbours(mesh):
    """Return per-corner vertex, previous vertex and next vertex indices.

    ``prev``/``next`` follow the face winding, matching the ``prev_corner`` /
    ``next_corner`` walk of ``calc_tangent_spaces``.  Reading the topology from
    the mesh datablock is safe in edit mode because this operator never changes
    topology, so the corner order matches the bmesh.
    """
    loop_count = len(mesh.loops)
    loop_verts = np.empty(loop_count, dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_verts)
    loop_verts = loop_verts.astype(np.int64)

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
    offset = indices - first
    previous = np.where(offset == 0, first + size - 1, indices - 1)
    following = np.where(offset == size - 1, first, indices + 1)
    return loop_verts, loop_verts[previous], loop_verts[following]


def _smooth(coords, edges, valence, weights, iterations, strength, smooth_type):
    """Port of ``smooth_iter__simple`` / ``smooth_iter__length_weight``."""
    coords = coords.copy()
    if iterations <= 0 or len(edges) == 0:
        return coords

    first = edges[:, 0]
    second = edges[:, 1]

    if smooth_type == 'LENGTH_WEIGHTED':
        # The modifier doubles lambda here to stay comparable with Simple.
        lam = strength * 2.0
        for _ in range(iterations):
            delta = np.zeros_like(coords)
            lengths = np.zeros(len(coords))
            edge = coords[second] - coords[first]
            distance = np.linalg.norm(edge, axis=1)
            weighted = edge * distance[:, None]
            np.add.at(delta, first, weighted)
            np.add.at(delta, second, -weighted)
            np.add.at(lengths, first, distance)
            np.add.at(lengths, second, distance)
            divisor = lengths * valence
            factor = np.zeros(len(coords))
            usable = divisor > _LENGTH_DIV_EPS
            factor[usable] = lam * weights[usable] / divisor[usable]
            coords = coords + factor[:, None] * delta
        return coords

    # A vertex without edges uses lambda * weight directly, mirroring
    # `lambda * (count ? 1/count : 1.0f)`.
    alpha = strength * weights / np.where(valence > 0.0, valence, 1.0)
    for _ in range(iterations):
        delta = np.zeros_like(coords)
        edge = coords[second] - coords[first]
        np.add.at(delta, first, edge)
        np.add.at(delta, second, -edge)
        coords = coords + alpha[:, None] * delta
    return coords


def _tangent_frames(coords, corner_verts, prev_verts, next_verts):
    """Port of ``calc_tangent_spaces``; rows of T are (t0, t1, t2)."""
    v_prev = coords[prev_verts] - coords[corner_verts]
    v_next = coords[corner_verts] - coords[next_verts]
    _normalize_inplace(v_prev)
    _normalize_inplace(v_next)

    # `compare_v3v3(v_dir_prev, v_dir_next, FLT_EPSILON * 10.0f)` in the
    # modifier.  The bisector/normal guards additionally keep the near-180°
    # corner (where Blender itself divides by a denormal) from producing a
    # zero matrix.
    degenerate = np.all(np.abs(v_prev - v_next) <= _PARALLEL_EPS, axis=1)

    normal = np.cross(v_prev, v_next)
    _normalize_inplace(normal)
    bisector = v_prev + v_next
    _normalize_inplace(bisector)
    second = np.cross(normal, bisector)

    degenerate |= (
        (np.linalg.norm(bisector, axis=1) <= _ZERO_EPS)
        | (np.linalg.norm(normal, axis=1) <= _ZERO_EPS)
        | (np.linalg.norm(second, axis=1) <= _ZERO_EPS)
    )

    weight = np.abs(np.arccos(
        np.clip(np.einsum('ij,ij->i', v_next, v_prev), -1.0, 1.0)))
    if degenerate.any():
        bisector[degenerate] = (1.0, 0.0, 0.0)
        second[degenerate] = (0.0, 1.0, 0.0)
        normal[degenerate] = (0.0, 0.0, 1.0)
        weight[degenerate] = 0.0
    return bisector, second, normal, weight


class _DeltaMushSolver:
    """Caches the reference-dependent half of delta-mush for interactive use."""

    def __init__(self, obj):
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.verts.ensure_lookup_table()
        self.obj = obj
        self.vert_count = len(bm.verts)
        if len(mesh.vertices) != self.vert_count:
            raise RuntimeError("网格数据与编辑网格的顶点数不一致，无法计算矫正平滑")

        # Reference state: the mesh datablock, i.e. the Basis when shape keys
        # exist.  This mirrors the modifier's "Original Coords" rest source.
        reference = np.empty(self.vert_count * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", reference)
        self.reference = reference.reshape(self.vert_count, 3).astype(np.float64)

        # Deformed state: the edit cage, i.e. the active shape key.
        self.original = _read_coords(bm.verts, self.vert_count)

        selected = np.fromiter(
            (bool(vert.select) and not vert.hide for vert in bm.verts),
            dtype=bool, count=self.vert_count,
        )
        self.selected = selected
        self.movable = bool(selected.any())

        edge_count = len(mesh.edges)
        if edge_count:
            edges = np.empty(edge_count * 2, dtype=np.int32)
            mesh.edges.foreach_get("vertices", edges)
            edges = edges.reshape(edge_count, 2).astype(np.int64)
            self.valence = np.bincount(
                edges.ravel(), minlength=self.vert_count).astype(np.float64)
        else:
            edges = np.empty((0, 2), dtype=np.int64)
            self.valence = np.zeros(self.vert_count, dtype=np.float64)
        self.edges = edges

        self.corner_verts, self.prev_verts, self.next_verts = _loop_neighbours(mesh)

        self._key = None
        self._state = None

    def reference_delta(self):
        """Largest reference/current discrepancy, used for the degeneracy hint."""
        return float(np.abs(self.reference - self.original).max())

    def _rest_weights(self, anchor_selection):
        # A weight of zero freezes the vertex, which is exactly how the
        # modifier pins a vertex group, so the selection boundary becomes a set
        # of anchors.
        if anchor_selection:
            return self.selected.astype(np.float64)
        return np.ones(self.vert_count, dtype=np.float64)

    def _refresh(self, strength, iterations, smooth_type, anchor_selection):
        weights = self._rest_weights(anchor_selection)
        smoothed_reference = _smooth(
            self.reference, self.edges, self.valence, weights,
            iterations, strength, smooth_type)
        smoothed_current = _smooth(
            self.original, self.edges, self.valence, weights,
            iterations, strength, smooth_type)
        rest = _tangent_frames(
            smoothed_reference, self.corner_verts, self.prev_verts, self.next_verts)
        current = _tangent_frames(
            smoothed_current, self.corner_verts, self.prev_verts, self.next_verts)

        detail = self.reference[self.corner_verts] - smoothed_reference[
            self.corner_verts]
        rest0, rest1, rest2, _rest_weight = rest
        delta = np.empty_like(detail)
        delta[:, 0] = np.einsum('ij,ij->i', rest0, detail)
        delta[:, 1] = np.einsum('ij,ij->i', rest1, detail)
        delta[:, 2] = np.einsum('ij,ij->i', rest2, detail)

        self._state = (smoothed_current, current, delta)
        self._key = (float(strength), int(iterations), str(smooth_type),
                     bool(anchor_selection))

    def evaluate(self, strength, iterations, smooth_type, anchor_selection, scale):
        """Return the deformed coordinates after a local corrective smooth."""
        key = (float(strength), int(iterations), str(smooth_type),
               bool(anchor_selection))
        if key != self._key:
            self._refresh(strength, iterations, smooth_type, anchor_selection)

        smoothed_current, current, delta = self._state
        cur0, cur1, cur2, weight = current

        corner_verts = self.corner_verts
        totals = np.bincount(corner_verts, weights=weight,
                             minlength=self.vert_count)
        per_corner_total = totals[corner_verts]
        share = np.zeros_like(weight)
        usable = per_corner_total > 0.0
        share[usable] = weight[usable] / per_corner_total[usable]

        # `T_cur` is orthonormal, so its inverse is its transpose: row k of
        # ``T_cur^T @ delta`` is ``cur0[k]*delta0 + cur1[k]*delta1 +
        # cur2[k]*delta2``.
        shifted = np.zeros_like(delta)
        if scale != 0.0:
            share = share * scale
            shifted = (
                cur0 * delta[:, 0:1]
                + cur1 * delta[:, 1:2]
                + cur2 * delta[:, 2:3]
            ) * share[:, None]

        correction = np.empty_like(smoothed_current)
        for axis in range(3):
            correction[:, axis] = np.bincount(
                corner_verts, weights=shifted[:, axis],
                minlength=self.vert_count)

        result = self.original.copy()
        result[self.selected] = (smoothed_current + correction)[self.selected]
        return result


def _clamp(value, limits, digits=4):
    return round(max(limits[0], min(limits[1], value)), digits)


def _adjust_parameters(operator, event):
    """Apply one modal wheel/key event to the operator's live parameters.

    Kept free of context so the whole interaction map can be exercised in
    isolation.  Returns True when a parameter changed, so the caller knows it
    has to rebuild the preview.
    """
    changed = False

    if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
        direction = 1.0 if event.type == 'WHEELUPMOUSE' else -1.0
        if event.shift:
            operator.iterations = int(_clamp(
                operator.iterations + direction * _ITERATION_STEP,
                _ITERATION_RANGE, 0))
        elif event.ctrl:
            operator.scale = _clamp(
                operator.scale + direction * _SCALE_STEP, _SCALE_RANGE)
        else:
            operator.strength = _clamp(
                operator.strength + direction * _STRENGTH_STEP,
                _STRENGTH_RANGE)
        return True

    if event.value != 'PRESS':
        return False

    if event.type == 'T':
        operator.smooth_type = (
            'LENGTH_WEIGHTED' if operator.smooth_type == 'SIMPLE' else 'SIMPLE')
        changed = True
    elif event.type == 'B':
        operator.anchor_selection = not operator.anchor_selection
        changed = True
    elif event.type == 'R':
        operator.strength = _DEFAULTS["strength"]
        operator.iterations = _DEFAULTS["iterations"]
        operator.scale = _DEFAULTS["scale"]
        operator.smooth_type = _DEFAULTS["smooth_type"]
        operator.anchor_selection = _DEFAULTS["anchor_selection"]
        changed = True

    return changed


class HO_OT_LocalCorrectiveSmooth(bpy.types.Operator):
    """Locally correct the deformation of the active shape key."""

    bl_idname = "ho.local_corrective_smooth"
    bl_label = "局部矫正平滑"
    bl_description = (
        "以网格基础坐标为参考，对选中顶点做局部矫正平滑（delta-mush）；"
        "形态键细节保留，接缝不动"
    )
    bl_options = {'REGISTER', 'UNDO'}

    strength: FloatProperty(
        name="强度", default=_DEFAULTS["strength"],
        min=0.0, max=10.0, soft_max=2.0, precision=3,
        description="平滑系数，越大越平；等同内置修改器的 Factor",
    )  # type: ignore
    iterations: IntProperty(
        name="迭代", default=_DEFAULTS["iterations"],
        min=0, max=100, soft_max=50,
        description="平滑迭代次数，等同内置修改器的 Iterations",
    )  # type: ignore
    scale: FloatProperty(
        name="细节", default=_DEFAULTS["scale"],
        min=-10.0, max=10.0, soft_min=0.0, precision=3,
        description="基础坐标细节的回填强度，0 表示只平滑不回填",
    )  # type: ignore
    smooth_type: EnumProperty(
        name="平滑类型", items=SMOOTH_TYPE_ITEMS,
        default=_DEFAULTS["smooth_type"],
    )  # type: ignore
    anchor_selection: BoolProperty(
        name="固定选区边界", default=_DEFAULTS["anchor_selection"],
        description="开启时选区之外完全不动；关闭时平滑跨越选区计算，但仍只写回选中顶点",
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
        layout.prop(self, "strength")
        layout.prop(self, "iterations")
        layout.prop(self, "scale")
        layout.prop(self, "smooth_type")
        layout.prop(self, "anchor_selection")
        layout.label(text="参考坐标：网格基础坐标（形态键 Basis）")
        layout.label(text="参考与当前相同时：细节=1 无变化，细节=0 等于局部平滑")

    # -- HUD ---------------------------------------------------------------

    def _hud_rows(self):
        rows = []
        if getattr(self, "_degenerate", False):
            rows.append((0, "注意：", "参考=当前，细节≠1 时才有变化"))
        base = len(rows) * 24
        rows.extend([
            (base + 0, "局部矫正平滑", "参考 Basis"),
            (base + 24, "滚轮：", f"强度 {self.strength:.3f}"),
            (base + 48, "Shift+滚轮：", f"迭代 {self.iterations}"),
            (base + 72, "Ctrl+滚轮：", f"细节 {self.scale:+.3f}"),
            (base + 96, "T：", f"平滑类型 {SMOOTH_TYPE_LABELS[self.smooth_type]}"),
            (base + 120, "B：", "固定选区边界 {}".format(
                "开" if self.anchor_selection else "关")),
            (base + 144, "R：", "重置参数"),
            (base + 168, "左键 / 回车：", "确认"),
            (base + 192, "右键 / Esc：", "取消"),
        ])
        return rows

    def draw_text(self):
        try:
            draw_mouse_hud_rows(
                (self._mouse_x, self._mouse_y),
                self._hud_rows(),
                offset=24,
                size=15,
            )
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
        cleanup_corrective_smooth_huds()
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
        self._degenerate = False
        try:
            solver = _DeltaMushSolver(active)
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return None, None
        if not solver.movable:
            self.report({'WARNING'}, "请先选择要做矫正平滑的顶点")
            return None, None
        if solver.reference_delta() <= 1.0e-9:
            # Matches the modifier, which has no rest==deformed guard: the
            # correction collapses to ``P - S_P``, so ``scale`` still controls
            # the result (1 = identity, 0 = plain smooth, 2 = overshoot).
            # Report a hint instead of refusing to run.
            self._degenerate = True
            self.report(
                {'INFO'},
                "参考坐标与当前坐标相同（没有形态键，或正在编辑 Basis）："
                "细节=1 时结果与原网格一致，细节=0 时相当于局部平滑",
            )
        return bm, solver

    def _write(self, context, target):
        _write_coords(self._bm.verts, target)
        self._bm.normal_update()
        bmesh.update_edit_mesh(
            self._obj.data, loop_triangles=False, destructive=False)
        self._tag_redraw(context)

    def _apply(self, context):
        try:
            target = self._solver.evaluate(
                self.strength, self.iterations, self.smooth_type,
                self.anchor_selection, self.scale,
            )
            self._write(context, target)
        except (AttributeError, RuntimeError, TypeError, ValueError,
                ReferenceError) as error:
            self.report({'WARNING'}, f"矫正平滑失败: {error}")
            return False
        return True

    def _cancel(self, context):
        try:
            self._write(context, self._solver.original)
        except (AttributeError, RuntimeError, TypeError, ValueError,
                ReferenceError):
            pass
        self._remove_hud()
        self._tag_redraw(context)
        return {'CANCELLED'}

    def _finish(self, context):
        self._remove_hud()
        self._tag_redraw(context)
        return {'FINISHED'}

    # -- operator ----------------------------------------------------------

    def invoke(self, context, event):
        bm, solver = self._build_solver(context)
        if solver is None:
            return {'CANCELLED'}

        self._obj = context.active_object
        self._source_object = self._obj
        self._bm = bm
        self._solver = solver
        self._handle_text = None
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
        bm, solver = self._build_solver(context)
        if solver is None:
            return {'CANCELLED'}
        self._obj = context.active_object
        self._source_object = self._obj
        self._bm = bm
        self._solver = solver
        self._handle_text = None
        if not self._apply(context):
            return {'CANCELLED'}
        return {'FINISHED'}


HO_CORRECTIVE_CLASSES = (HO_OT_LocalCorrectiveSmooth,)


__all__ = [
    "HO_OT_LocalCorrectiveSmooth",
    "HO_CORRECTIVE_CLASSES",
    "cleanup_corrective_smooth_huds",
]
