"""Stable modal wrapper around the bundled OffsetEdges topology algorithm."""

from __future__ import annotations

import bmesh
import bpy
from bpy.props import BoolProperty, FloatProperty
from bpy.types import Operator
from math import cos, radians, sin
from mathutils import Vector

from Utils.hud import draw_mouse_hud_rows


X_UP = Vector((1.0, 0.0, 0.0))
Y_UP = Vector((0.0, 1.0, 0.0))
Z_UP = Vector((0.0, 0.0, 1.0))
ZERO_VEC = Vector((0.0, 0.0, 0.0))


def calc_loop_normal(verts, fallback=Z_UP):
    normal = ZERO_VEC.copy()
    if verts[0] is verts[-1]:
        indices = range(1, len(verts))
    else:
        indices = range(len(verts))
    for index in indices:
        first = verts[index - 1].co
        second = verts[index].co
        normal.x += (first.y - second.y) * (first.z + second.z)
        normal.y += (first.z - second.z) * (first.x + second.x)
        normal.z += (first.x - second.x) * (first.y + second.y)
    if normal != ZERO_VEC:
        normal.normalize()
    else:
        normal = fallback.copy()
    return normal


def collect_edges(bm):
    edges = set()
    for edge in bm.edges:
        if not edge.select:
            continue
        selected_faces = sum(1 for face in edge.link_faces if face.select)
        if selected_faces < 2:
            edges.add(edge)
    return edges or None


def collect_loops(edges):
    remaining = set(edges)
    loops = []
    while remaining:
        start = remaining.pop()
        left, right = start.verts
        loop = [left, start, right]
        reversed_once = False
        while True:
            next_edge = None
            for edge in right.link_edges:
                if edge in remaining:
                    if next_edge is not None:
                        return None
                    next_edge = edge
            if next_edge is not None:
                remaining.remove(next_edge)
                right = next_edge.other_vert(right)
                loop.extend((next_edge, right))
                continue
            if right is left:
                loops.append(loop)
                break
            if not reversed_once:
                loop.reverse()
                right, left = left, right
                reversed_once = True
                continue
            loops.append(loop)
            break
    return loops


def get_adj_faces(edges):
    result = []
    for edge in edges:
        adjacent = None
        count = 0
        for face in edge.link_faces:
            if face.hide or face.normal == ZERO_VEC:
                continue
            adjacent = face
            count += 1
            if face.select:
                break
        result.append(adjacent if count == 1 or adjacent and adjacent.select else None)
    return result


def get_edge_rail(vert, selected_edges):
    unselected_count = 0
    selected_count = 0
    rail = None
    for edge in vert.link_edges:
        if edge in selected_edges or edge.hide:
            continue
        other = edge.other_vert(vert)
        vector = other.co - vert.co
        if vector == ZERO_VEC:
            continue
        rail = vector
        unselected_count += 1
    if unselected_count == 1 and rail is not None:
        rail.normalize()
        return rail
    for edge in vert.link_edges:
        if edge not in selected_edges or edge.hide:
            continue
        vector = edge.other_vert(vert).co - vert.co
        if vector == ZERO_VEC:
            continue
        selected_count += 1
        rail = vector
        if selected_count == 2:
            return None
    if selected_count == 1 and rail is not None:
        rail.normalize()
        return rail
    return None


def get_cross_rail(tangent, edge_right, edge_left, normal_right, normal_left):
    cross = normal_right.cross(normal_left)
    if cross.dot(tangent) < 0.0:
        cross *= -1.0
    minimum = min(tangent.dot(edge_right), tangent.dot(-edge_left))
    if tangent.dot(cross) >= minimum and cross.length > 1.0e-8:
        cross.normalize()
        return cross
    return None


def reorder_loop(verts, edges, loop_normal, adjacent_faces):
    for index, face in enumerate(adjacent_faces):
        if face is None:
            continue
        first, second = verts[index], verts[index + 1]
        face_verts = tuple(face.verts)
        if face_verts[face_verts.index(first) - 1] is second:
            verts.reverse()
            edges.reverse()
            adjacent_faces.reverse()
        if loop_normal.dot(face.normal) < 0.0:
            loop_normal *= -1.0
        break
    else:
        for vert in verts:
            if vert.normal != ZERO_VEC:
                if loop_normal.dot(vert.normal) < 0.0:
                    verts.reverse()
                    edges.reverse()
                    loop_normal *= -1.0
                break
    return verts, edges, loop_normal, adjacent_faces


def get_directions(loop, upward, normal_fallback, _mirror_pairs, **options):
    follow_face = options["follow_face"]
    edge_rail = options["edge_rail"]
    edge_rail_only_end = options["edge_rail_only_end"]
    threshold = options["threshold"]
    verts, edges = loop[::2], loop[1::2]
    selected_edges = set(edges)
    loop_normal = calc_loop_normal(verts, fallback=normal_fallback)
    if loop_normal.dot(upward) < 0.0:
        verts.reverse()
        edges.reverse()
        loop_normal *= -1.0
    if follow_face:
        adjacent_faces = get_adj_faces(edges)
        verts, edges, loop_normal, adjacent_faces = reorder_loop(
            verts, edges, loop_normal, adjacent_faces
        )
    else:
        adjacent_faces = (None,) * len(edges)
    edge_vectors = tuple(
        (edge.other_vert(vert).co - vert.co).normalized()
        for vert, edge in zip(verts, edges)
    )
    half_loop = not (verts[0] is verts[-1])
    if not half_loop:
        verts.pop()
    directions = []
    for index, vert in enumerate(verts):
        right_index, left_index = index, index - 1
        endpoint = False
        if half_loop:
            if index == 0:
                left_index = right_index
                endpoint = True
            elif index == len(verts) - 1:
                right_index = left_index
                endpoint = True
        edge_right = edge_vectors[right_index]
        edge_left = edge_vectors[left_index]
        face_right = adjacent_faces[right_index]
        face_left = adjacent_faces[left_index]
        normal_right = face_right.normal if face_right else loop_normal
        normal_left = face_left.normal if face_left else loop_normal
        two_normals = normal_right.angle(normal_left) > threshold
        tangent_right = edge_right.cross(normal_right).normalized()
        tangent_left = edge_left.cross(normal_left).normalized()
        tangent = (tangent_right + tangent_left).normalized()
        normal = (normal_right + normal_left).normalized()
        rail = None
        if two_normals or edge_rail:
            if two_normals or not edge_rail_only_end or endpoint:
                rail = get_edge_rail(vert, selected_edges)
        if rail is None and two_normals:
            rail = get_cross_rail(
                tangent, edge_right, edge_left, normal_right, normal_left
            )
        if rail is not None:
            dot = tangent.dot(rail)
            if dot > 0.0:
                tangent = rail
            elif dot < 0.0:
                tangent = -rail
        plane = normal.cross(tangent)
        dot_right = edge_right.dot(plane)
        dot_left = edge_left.dot(plane)
        if dot_right or dot_left:
            edge_vector, edge_dot = (
                (edge_right, dot_right)
                if dot_right > dot_left
                else (edge_left, dot_left)
            )
            tangent_projected = (tangent - tangent.project(edge_vector)).normalized()
            upward_vector = tangent_projected.cross(edge_vector)
            width_vector = tangent_projected - (
                tangent_projected.dot(plane) / edge_dot
            ) * edge_vector
            depth_vector = upward_vector - (
                upward_vector.dot(plane) / edge_dot
            ) * edge_vector
        else:
            width_vector = tangent
            depth_vector = normal
        directions.append((width_vector, depth_vector))
    return verts, directions


def move_verts(width, depth, verts, directions, geom_ex):
    if geom_ex:
        side_edges = geom_ex["side"]
        extruded_verts = []
        for vert in verts:
            side = next(
                (edge for edge in vert.link_edges if edge in side_edges),
                None,
            )
            if side is not None:
                extruded_verts.append(side.other_vert(vert))
        verts = extruded_verts
    for vert, (width_vector, depth_vector) in zip(verts, directions):
        vert.co += width * width_vector + depth * depth_vector


def extrude_edges(bm, edges_orig):
    extruded = bmesh.ops.extrude_edge_only(bm, edges=edges_orig)["geom"]
    edge_count = face_count = len(edges_orig)
    vert_count = len(extruded) - edge_count - face_count
    verts = set(extruded[:vert_count])
    edges = set(extruded[vert_count:vert_count + edge_count])
    faces = set(extruded[vert_count + edge_count:])
    side = {edge for vert in verts for edge in vert.link_edges if edge not in edges}
    return {"verts": verts, "edges": edges, "faces": faces, "side": side}


def clean(bm, mode, edges_orig, geom_ex=None):
    for face in bm.faces:
        face.select_set(False)
    if geom_ex:
        for edge in geom_ex["edges"]:
            edge.select_set(True)
        if mode == "offset":
            bmesh.ops.delete(
                bm,
                geom=list(geom_ex["side"]) + list(geom_ex["faces"]),
                context="EDGES",
            )
    else:
        for edge in edges_orig:
            edge.select_set(True)


_HUD_NAMESPACE_KEY = "hotools_offset_edges_hud_handles"
_ACTIVE_HUD_HANDLES = bpy.app.driver_namespace.setdefault(
    _HUD_NAMESPACE_KEY,
    set(),
)


def cleanup_offset_edges_huds():
    """Remove any HUD handlers left by a reload or addon unregister."""
    for handle in list(_ACTIVE_HUD_HANDLES):
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except (AttributeError, RuntimeError, TypeError, ReferenceError):
            pass
        _ACTIVE_HUD_HANDLES.discard(handle)


def _ensure_edit_mode(context):
    active = getattr(context, "active_object", None)
    if active is None or active.type != "MESH":
        return None
    mode = getattr(context, "mode", None) or getattr(active, "mode", None)
    if mode not in {"EDIT_MESH", "EDIT"}:
        return None
    return active


def _mesh_snapshot(active):
    """Copy the live edit BMesh, including unflushed edit-mode changes."""
    bmesh.update_edit_mesh(
        active.data,
        loop_triangles=False,
        destructive=False,
    )
    edit_bm = bmesh.from_edit_mesh(active.data)
    edit_bm.verts.ensure_lookup_table()
    edit_bm.edges.ensure_lookup_table()
    edit_bm.faces.ensure_lookup_table()
    edit_bm.verts.index_update()
    edit_bm.edges.index_update()
    edit_bm.faces.index_update()
    snapshot = active.data.copy()
    edit_bm.to_mesh(snapshot)
    snapshot.update()
    return snapshot


def _selected_edge_keys(active):
    bm = bmesh.from_edit_mesh(active.data)
    bm.edges.ensure_lookup_table()
    bm.edges.index_update()
    return {_edge_key(edge) for edge in bm.edges if edge.select}


def _restore_snapshot_bmesh(active, snapshot, selected_edge_keys=None):
    """Restore without rebuilding through mesh.from_pydata."""
    bpy.ops.object.mode_set(mode="OBJECT")
    bm = bmesh.new()
    try:
        bm.from_mesh(snapshot)
        if selected_edge_keys is not None:
            bm.edges.ensure_lookup_table()
            for vertex in bm.verts:
                vertex.select_set(False)
            for face in bm.faces:
                face.select_set(False)
            for edge in bm.edges:
                edge.select_set(_edge_key(edge) in selected_edge_keys)
        bm.to_mesh(active.data)
    finally:
        bm.free()
    bpy.ops.object.mode_set(mode="EDIT")


def _build_offset_infos(
    snapshot,
    active,
    selected_edge_keys,
    follow_face,
    edge_rail,
    edge_rail_only_end,
    threshold,
):
    bm = bmesh.new()
    try:
        bm.from_mesh(snapshot)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.verts.index_update()
        bm.edges.index_update()
        bm.faces.index_update()
        for face in bm.faces:
            face.select_set(False)
        for vertex in bm.verts:
            vertex.select_set(False)
        for edge in bm.edges:
            edge.select_set(_edge_key(edge) in selected_edge_keys)
        edges_orig = collect_edges(bm)
        if not edges_orig:
            raise ValueError("select at least one edge")
        loops = collect_loops(edges_orig)
        if loops is None:
            raise ValueError("selected edges contain overlapping loops")
        vec_upward = (
            X_UP
            + Y_UP
            + Z_UP
        ).normalized()
        mirror_pairs = None
        offset_infos = []
        for loop in loops:
            verts, directions = get_directions(
                loop,
                vec_upward,
                Z_UP,
                mirror_pairs,
                follow_face=follow_face,
                edge_rail=edge_rail,
                edge_rail_only_end=edge_rail_only_end,
                threshold=threshold,
            )
            if verts:
                offset_infos.append(
                    (
                        tuple(vertex.index for vertex in verts),
                        tuple(
                            (width.copy(), depth.copy())
                            for width, depth in directions
                        ),
                    )
                )
        if not offset_infos:
            raise ValueError("could not calculate an offset direction")
        return (
            offset_infos,
            tuple(edge.index for edge in edges_orig),
        )
    finally:
        bm.free()


def _apply_offset(active, snapshot, offset_infos, edge_indices, width, depth):
    bpy.ops.object.mode_set(mode="OBJECT")
    bm = bmesh.new()
    try:
        bm.from_mesh(snapshot)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        edges_orig = [bm.edges[index] for index in edge_indices]
        geom_ex = extrude_edges(bm, edges_orig)
        # extrude_edge_only invalidates sequence lookup tables.  The bundled
        # implementation keeps BMVert references; our cached preview keeps
        # indices, so refresh before resolving them.
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.verts.index_update()
        bm.edges.index_update()
        for vertex_indices, directions in offset_infos:
            verts = [bm.verts[index] for index in vertex_indices]
            move_verts(width, depth, verts, directions, geom_ex)
        clean(bm, "extrude", edges_orig, geom_ex)
        bm.normal_update()
        bm.to_mesh(active.data)
        active.data.update()
    finally:
        bm.free()
        bpy.ops.object.mode_set(mode="EDIT")


class OP_OffsetEdgesExtrude(Operator):
    bl_idname = "ho.offset_edges_extrude"
    bl_label = "外扩边环"
    bl_description = "沿选中边环向外生成一圈新面，滚轮调节凹翘程度"
    bl_options = {"REGISTER", "UNDO"}

    width: FloatProperty(
        name="外扩宽度",
        default=0.2,
        precision=4,
        description="Ctrl + 滚轮调节外扩宽度",
    )  # type: ignore
    warp_angle: FloatProperty(
        name="翘凹角度",
        default=0.0,
        soft_min=-1.570796,
        soft_max=1.570796,
        precision=3,
        subtype="ANGLE",
        description="Shift + 滚轮调节正负翘凹角度",
    )  # type: ignore
    follow_face: BoolProperty(
        name="跟随面方向",
        default=True,
    )  # type: ignore
    edge_rail: BoolProperty(
        name="边轨约束",
        default=False,
    )  # type: ignore
    edge_rail_only_end: BoolProperty(
        name="仅端点边轨",
        default=False,
    )  # type: ignore

    _source_object = None
    _snapshot = None
    _selected_edge_keys = None
    _offset_infos = None
    _edge_indices = None
    _step = 0.0
    _handle_text = None
    _mouse_x = 0.0
    _mouse_y = 0.0

    @classmethod
    def poll(cls, context):
        return _ensure_edit_mode(context) is not None

    def draw(self, context):
        self.layout.prop(self, "width")
        self.layout.prop(self, "warp_angle")
        self.layout.prop(self, "follow_face")
        self.layout.prop(self, "edge_rail")
        if self.edge_rail:
            self.layout.prop(self, "edge_rail_only_end")

    def _tag_redraw(self, context):
        area = getattr(context, "area", None)
        if area is not None:
            try:
                area.tag_redraw()
            except (AttributeError, ReferenceError, RuntimeError):
                pass

    def _draw_hud(self):
        try:
            rows = [
                (0, "宽度：", f"{self.width:+.4f}"),
                (24, "翘凹角度：", f"{self.warp_angle * 57.2957795:+.1f}°"),
                (48, "Ctrl+滚轮：", "调节宽度"),
                (72, "Shift+滚轮：", "调节翘凹"),
                (96, "左键：", "确认"),
                (120, "右键 / Esc：", "取消"),
            ]
            draw_mouse_hud_rows(
                (self._mouse_x, self._mouse_y),
                rows,
                offset=24,
                size=15,
            )
        except (AttributeError, RuntimeError, TypeError, ValueError, ReferenceError):
            pass

    def _install_hud(self):
        if self._handle_text is not None:
            return
        cleanup_offset_edges_huds()
        try:
            self._handle_text = bpy.types.SpaceView3D.draw_handler_add(
                self._draw_hud,
                (),
                "WINDOW",
                "POST_PIXEL",
            )
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

    def _cleanup_snapshot(self):
        self._remove_hud()
        snapshot = self._snapshot
        self._snapshot = None
        self._source_object = None
        self._selected_edge_keys = None
        self._offset_infos = None
        self._edge_indices = None
        if snapshot is not None:
            try:
                if snapshot.users == 0:
                    bpy.data.meshes.remove(snapshot)
            except (AttributeError, ReferenceError, RuntimeError):
                pass

    def _cancel(self, context):
        if self._source_object is not None and self._snapshot is not None:
            try:
                _restore_snapshot_bmesh(
                    self._source_object,
                    self._snapshot,
                    self._selected_edge_keys,
                )
            except (AttributeError, RuntimeError, TypeError, ValueError, ReferenceError):
                pass
        self._cleanup_snapshot()
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()
        return {"CANCELLED"}

    def _finish(self, context):
        self._cleanup_snapshot()
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()
        return {"FINISHED"}

    def _rebuild(self):
        _apply_offset(
            self._source_object,
            self._snapshot,
            self._offset_infos,
            self._edge_indices,
            self.width * cos(self.warp_angle),
            self.width * sin(self.warp_angle),
        )

    def modal(self, context, event):
        if context.active_object is not self._source_object:
            return self._cancel(context)
        if event.type in {"ESC", "RIGHTMOUSE"}:
            return self._cancel(context)
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            return self._finish(context)

        if event.type == "MOUSEMOVE":
            self._mouse_x = event.mouse_region_x
            self._mouse_y = event.mouse_region_y
            self._tag_redraw(context)
            return {"RUNNING_MODAL"}

        changed = False
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            if not event.shift and not event.ctrl:
                return {"PASS_THROUGH"}
            direction = 1.0 if event.type == "WHEELUPMOUSE" else -1.0
            if event.shift:
                self.warp_angle = max(
                    -1.570796,
                    min(1.570796, self.warp_angle + direction * radians(5.0)),
                )
            elif event.ctrl:
                self.width += direction * self._step * 4.0
            changed = True

        if changed:
            try:
                self._rebuild()
            except (AttributeError, RuntimeError, TypeError, ValueError, IndexError, ReferenceError) as error:
                self.report({"WARNING"}, f"外扩预览失败: {error}")
                return self._cancel(context)
            self._tag_redraw(context)
        if event.type in {
            "MIDDLEMOUSE",
            "TRACKPADPAN",
            "TRACKPADZOOM",
            "NDOF_MOTION",
        }:
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        active = _ensure_edit_mode(context)
        if active is None:
            return {"CANCELLED"}
        self._mouse_x = event.mouse_region_x
        self._mouse_y = event.mouse_region_y
        snapshot = None
        try:
            snapshot = _mesh_snapshot(active)
            selected_edge_keys = _selected_edge_keys(active)
            offset_infos, edge_indices = _build_offset_infos(
                snapshot,
                active,
                selected_edge_keys,
                self.follow_face,
                self.edge_rail,
                self.edge_rail_only_end,
                radians(0.05),
            )
            self._source_object = active
            self._snapshot = snapshot
            self._selected_edge_keys = selected_edge_keys
            self._offset_infos = offset_infos
            self._edge_indices = edge_indices
            self._step = max(1.0e-4, self._estimate_step(snapshot, edge_indices))
            self.width = self._step * 24.0
            self.warp_angle = 0.0
            self._rebuild()
            self._install_hud()
            context.window_manager.modal_handler_add(self)
            self._tag_redraw(context)
            return {"RUNNING_MODAL"}
        except (AttributeError, RuntimeError, TypeError, ValueError, IndexError, ReferenceError) as error:
            if snapshot is not None:
                self._snapshot = snapshot
            self.report({"WARNING"}, f"无法开始外扩: {error}")
            return self._cancel(context)

    def execute(self, context):
        active = _ensure_edit_mode(context)
        if active is None:
            return {"CANCELLED"}
        snapshot = None
        try:
            snapshot = _mesh_snapshot(active)
            selected_edge_keys = _selected_edge_keys(active)
            offset_infos, edge_indices = _build_offset_infos(
                snapshot,
                active,
                selected_edge_keys,
                self.follow_face,
                self.edge_rail,
                self.edge_rail_only_end,
                radians(0.05),
            )
            self._source_object = active
            self._snapshot = snapshot
            self._selected_edge_keys = selected_edge_keys
            self._offset_infos = offset_infos
            self._edge_indices = edge_indices
            self._step = max(1.0e-4, self._estimate_step(snapshot, edge_indices))
            self._rebuild()
            self._cleanup_snapshot()
            return {"FINISHED"}
        except (AttributeError, RuntimeError, TypeError, ValueError, IndexError, ReferenceError) as error:
            if snapshot is not None:
                self._snapshot = snapshot
            self.report({"WARNING"}, f"外扩失败: {error}")
            return self._cancel(context)

    @staticmethod
    def _estimate_step(snapshot, edge_indices):
        bm = bmesh.new()
        try:
            bm.from_mesh(snapshot)
            bm.edges.ensure_lookup_table()
            lengths = [bm.edges[index].calc_length() for index in edge_indices]
            return sum(lengths) / max(1, len(lengths)) / 120.0
        finally:
            bm.free()


def _edge_key(edge):
    first, second = edge.verts
    return tuple(sorted((first.index, second.index)))


def _ensure_tables(bm):
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()


def _find_edge(bm, key):
    return next(
        (edge for edge in bm.edges if edge.is_valid and _edge_key(edge) == key),
        None,
    )


def _collect_inner_specs(bm, selected_keys):
    specs = []
    for face in sorted(bm.faces, key=lambda item: item.index):
        if not face.is_valid or len(face.verts) not in {3, 4}:
            continue
        selected = [edge for edge in face.edges if _edge_key(edge) in selected_keys]
        if len(selected) != 1:
            continue
        anchor = selected[0]
        if len(face.verts) == 3:
            # A triangle has no opposite edge. Splitting both remaining edges
            # and connecting their points creates the missing support edge.
            cross = [edge for edge in face.edges if edge is not anchor]
        else:
            opposite = next(
                (
                    edge for edge in face.edges
                    if edge is not anchor
                    and not any(vertex in anchor.verts for vertex in edge.verts)
                ),
                None,
            )
            if opposite is None:
                continue
            cross = [edge for edge in face.edges if edge not in {anchor, opposite}]
        if len(cross) != 2:
            continue
        cross_specs = []
        valid = True
        for edge in cross:
            endpoint = next(
                (vertex for vertex in edge.verts if vertex in anchor.verts),
                None,
            )
            if endpoint is None:
                valid = False
                break
            cross_specs.append((_edge_key(edge), endpoint.index))
        if valid:
            specs.append(
                {
                    "face_ids": tuple(vertex.index for vertex in face.verts),
                    "cross": tuple(cross_specs),
                }
            )
    return specs


def _find_split_face(bm, point_a, point_b, face_ids):
    wanted = set(face_ids)
    return next(
        (
            face for face in bm.faces
            if face.is_valid
            and point_a in face.verts
            and point_b in face.verts
            and wanted.issubset(vertex.index for vertex in face.verts)
        ),
        None,
    )


def _apply_inner_cut(active, snapshot, specs, factor):
    # Keep the original isolated BMesh transaction here.  The modal operator
    # must not clear Blender's live edit BMesh while it is being displayed.
    bpy.ops.object.mode_set(mode="OBJECT")
    bm = bmesh.new()
    try:
        bm.from_mesh(snapshot)
        _ensure_tables(bm)
        points = {}
        for spec in specs:
            for edge_key, anchor_id in spec["cross"]:
                if edge_key in points:
                    continue
                edge = _find_edge(bm, edge_key)
                if edge is None:
                    raise RuntimeError("transverse edge disappeared")
                start = next(
                    (vertex for vertex in edge.verts if vertex.index == anchor_id),
                    None,
                )
                if start is None:
                    raise RuntimeError("transverse edge anchor disappeared")
                _unused, point = bmesh.utils.edge_split(edge, start, factor)
                points[edge_key] = point
                _ensure_tables(bm)

        generated = []
        for spec in specs:
            point_a = points[spec["cross"][0][0]]
            point_b = points[spec["cross"][1][0]]
            face = _find_split_face(bm, point_a, point_b, spec["face_ids"])
            if face is None:
                raise RuntimeError("target face disappeared")
            bmesh.utils.face_split(face, point_a, point_b)
            edge = next(
                (
                    item for item in point_a.link_edges
                    if item.is_valid and point_b in item.verts
                ),
                None,
            )
            if edge is not None:
                generated.append(edge)

        if not generated:
            raise RuntimeError("no inner loop was created")
        for vertex in bm.verts:
            vertex.select_set(False)
        for face in bm.faces:
            face.select_set(False)
        for edge in bm.edges:
            edge.select_set(False)
        for edge in generated:
            edge.select_set(edge.is_valid)
        bm.normal_update()
        bm.to_mesh(active.data)
        active.data.update()
    finally:
        bm.free()
        bpy.ops.object.mode_set(mode="EDIT")


class OP_InnerLoopCutSlide(Operator):
    bl_idname = "ho.inner_loop_cut_slide"
    bl_label = "内环切滑移"
    bl_description = "在选中边环旁插入内部切线，右键或 Esc 会完整撤销"
    bl_options = {"REGISTER", "UNDO"}

    follow_selected_side: BoolProperty(
        name="跟随选中边方向",
        default=True,
        options={"HIDDEN"},
    )  # type: ignore

    _source_object = None
    _snapshot = None
    _specs = None
    _selected_edge_keys = None
    _handle_text = None
    _mouse_x = 0.0
    _mouse_y = 0.0
    slide_factor: FloatProperty(
        name="滑移位置",
        description="切线在横向边上的位置，0.05 靠近选中边，0.95 靠近对侧",
        default=0.5,
        soft_min=0.05,
        soft_max=0.95,
        precision=3,
        subtype="FACTOR",
    )  # type: ignore
    _start_mouse_x = 0.0
    _step = 0.001

    @classmethod
    def poll(cls, context):
        return _ensure_edit_mode(context) is not None

    def _tag_redraw(self, context):
        area = getattr(context, "area", None)
        if area is not None:
            try:
                area.tag_redraw()
            except (AttributeError, ReferenceError, RuntimeError):
                pass

    def _draw_hud(self):
        try:
            rows = [
                (0, "\u6ed1\u79fb\u4f4d\u7f6e:", f"{self.slide_factor:.3f}"),
                (24, "\u9f20\u6807\u79fb\u52a8:", "\u8c03\u6574\u6ed1\u79fb"),
                (48, "\u5de6\u952e:", "\u786e\u8ba4"),
                (72, "\u53f3\u952e / Esc:", "\u53d6\u6d88"),
            ]
            draw_mouse_hud_rows(
                (self._mouse_x, self._mouse_y),
                rows,
                offset=24,
                size=15,
            )
        except (AttributeError, RuntimeError, TypeError, ValueError, ReferenceError):
            pass

    def _install_hud(self):
        if self._handle_text is not None:
            return
        cleanup_offset_edges_huds()
        try:
            self._handle_text = bpy.types.SpaceView3D.draw_handler_add(
                self._draw_hud,
                (),
                "WINDOW",
                "POST_PIXEL",
            )
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

    def _cleanup(self):
        self._remove_hud()
        snapshot = self._snapshot
        self._snapshot = None
        self._source_object = None
        self._specs = None
        self._selected_edge_keys = None
        if snapshot is not None:
            try:
                if snapshot.users == 0:
                    bpy.data.meshes.remove(snapshot)
            except (AttributeError, ReferenceError, RuntimeError):
                pass

    def _cancel(self, context):
        if self._source_object is not None and self._snapshot is not None:
            try:
                _restore_snapshot_bmesh(
                    self._source_object,
                    self._snapshot,
                    self._selected_edge_keys,
                )
            except (AttributeError, RuntimeError, TypeError, ValueError, ReferenceError):
                pass
        self._cleanup()
        self._tag_redraw(context)
        return {"CANCELLED"}

    def _finish(self, context):
        self._cleanup()
        self._tag_redraw(context)
        return {"FINISHED"}

    def _rebuild(self):
        _apply_inner_cut(
            self._source_object,
            self._snapshot,
            self._specs,
            self.slide_factor,
        )

    def modal(self, context, event):
        if context.active_object is not self._source_object:
            return self._cancel(context)
        if event.type in {"ESC", "RIGHTMOUSE"}:
            return self._cancel(context)
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            return self._finish(context)
        if event.type == "MOUSEMOVE":
            self._mouse_x = event.mouse_region_x
            self._mouse_y = event.mouse_region_y
            delta = event.mouse_region_x - self._start_mouse_x
            slide_factor = max(
                0.05,
                min(0.95, 0.5 + delta * self._step),
            )
            if slide_factor == self.slide_factor:
                self._tag_redraw(context)
                return {"RUNNING_MODAL"}
            self.slide_factor = slide_factor
            try:
                self._rebuild()
            except (AttributeError, RuntimeError, TypeError, ValueError, IndexError, ReferenceError) as error:
                self.report({"WARNING"}, f"内环切预览失败: {error}")
                return self._cancel(context)
            self._tag_redraw(context)
            return {"RUNNING_MODAL"}
        if event.type in {
            "MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE",
            "TRACKPADPAN", "TRACKPADZOOM", "NDOF_MOTION",
        }:
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        active = _ensure_edit_mode(context)
        if active is None:
            return {"CANCELLED"}
        self._mouse_x = event.mouse_region_x
        self._mouse_y = event.mouse_region_y
        snapshot = None
        try:
            snapshot = _mesh_snapshot(active)
            selected_edge_keys = _selected_edge_keys(active)
            bm = bmesh.new()
            try:
                bm.from_mesh(snapshot)
                _ensure_tables(bm)
                self._specs = _collect_inner_specs(bm, selected_edge_keys)
                lengths = [
                    bm.edges[index].calc_length()
                    for index in range(len(bm.edges))
                    if _edge_key(bm.edges[index]) in selected_edge_keys
                ]
            finally:
                bm.free()
            if not self._specs:
                raise ValueError("select a continuous edge loop beside quad faces")
            self._source_object = active
            self._snapshot = snapshot
            self._selected_edge_keys = selected_edge_keys
            self._start_mouse_x = event.mouse_region_x
            self._step = max(1.0e-4, sum(lengths) / max(1, len(lengths)) / 120.0)
            self.slide_factor = 0.5
            self._rebuild()
            self._install_hud()
            context.window_manager.modal_handler_add(self)
            self._tag_redraw(context)
            return {"RUNNING_MODAL"}
        except (AttributeError, RuntimeError, TypeError, ValueError, IndexError, ReferenceError) as error:
            if snapshot is not None:
                self._snapshot = snapshot
            self.report({"WARNING"}, f"无法开始内环切: {error}")
            return self._cancel(context)

    def execute(self, context):
        active = _ensure_edit_mode(context)
        if active is None:
            return {"CANCELLED"}
        snapshot = None
        try:
            snapshot = _mesh_snapshot(active)
            selected_edge_keys = _selected_edge_keys(active)
            bm = bmesh.new()
            try:
                bm.from_mesh(snapshot)
                _ensure_tables(bm)
                self._specs = _collect_inner_specs(bm, selected_edge_keys)
            finally:
                bm.free()
            if not self._specs:
                raise ValueError("select a continuous edge loop beside quad faces")
            self._source_object = active
            self._snapshot = snapshot
            self._selected_edge_keys = selected_edge_keys
            self._rebuild()
            self._cleanup()
            return {"FINISHED"}
        except (AttributeError, RuntimeError, TypeError, ValueError, IndexError, ReferenceError) as error:
            if snapshot is not None:
                self._snapshot = snapshot
            self.report({"WARNING"}, f"内环切失败: {error}")
            return self._cancel(context)


__all__ = [
    "OP_OffsetEdgesExtrude",
    "OP_InnerLoopCutSlide",
    "cleanup_offset_edges_huds",
]
