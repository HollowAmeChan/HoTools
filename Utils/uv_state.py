"""Restore temporary unwrap selection, pins, seams and UV coordinates by keys.

Never retain loop wrappers across bpy.ops calls: their Python BMesh owner and
CustomData storage may be refreshed. Topology must remain unchanged throughout.
"""

import bmesh


class UVSceneState:
    def __init__(self, context):
        self.context = context
        settings = context.scene.tool_settings
        self.settings = {name: getattr(settings, name) for name in (
            'use_uv_select_sync', 'mesh_select_mode', 'uv_select_mode', 'uv_sticky_select_mode',
        )}
        self.settings['mesh_select_mode'] = tuple(self.settings['mesh_select_mode'])
        if hasattr(settings, 'use_uv_select_island'):
            self.settings['use_uv_select_island'] = settings.use_uv_select_island
        self.meshes = []
        for obj in context.objects_in_mode_unique_data:
            if obj.type != 'MESH':
                continue
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.index_update()
            bm.edges.index_update()
            bm.faces.index_update()
            uv = bm.loops.layers.uv.active
            modern = hasattr(bm, 'uv_select_sync_valid')
            self.meshes.append({
                'obj': obj, 'bm': bm, 'uv_name': uv.name if uv else None,
                'uv_names': tuple(bm.loops.layers.uv.keys()),
                'verts': tuple((v.select, v.hide) for v in bm.verts),
                'edges': tuple((e.select, e.hide, e.seam) for e in bm.edges),
                'faces': tuple((f.select, f.hide, f.uv_select if modern else None) for f in bm.faces),
                'corners': tuple(tuple((tuple(l[uv].uv), l[uv].pin_uv,
                                       l.uv_select_vert if modern else l[uv].select,
                                       l.uv_select_edge if modern else l[uv].select_edge)
                                      for l in f.loops) for f in bm.faces) if uv else None,
                'valid': bm.uv_select_sync_valid if modern else None,
                'active': bm.faces.active.index if bm.faces.active is not None else None,
                'history': tuple((type(item).__name__, item.index) for item in bm.select_history),
            })

    def restore(self):
        settings = self.context.scene.tool_settings
        # Restore settings BEFORE raw selections: callbacks may flush selections.
        for name in ('use_uv_select_sync', 'mesh_select_mode', 'uv_select_mode',
                     'uv_sticky_select_mode', 'use_uv_select_island'):
            if name in self.settings and getattr(settings, name) != self.settings[name]:
                setattr(settings, name, self.settings[name])
        for saved in self.meshes:
            obj = saved['obj']
            bm = bmesh.from_edit_mesh(obj.data)
            if (len(bm.verts), len(bm.edges), len(bm.faces)) != (
                    len(saved['verts']), len(saved['edges']), len(saved['faces'])):
                raise RuntimeError('展开过程中网格拓扑改变，无法恢复 UV 状态')
            for name in list(bm.loops.layers.uv.keys()):
                if name not in saved['uv_names']:
                    bm.loops.layers.uv.remove(bm.loops.layers.uv.get(name))
            modern = saved['valid'] is not None
            if modern and saved['corners'] is not None and not bm.uv_select_sync_valid:
                bm.uv_select_sync_from_mesh()
            # Setters propagate to children: faces -> edges -> vertices restores
            # partial edge selections exactly. The reverse order deselects them.
            for f, (select, hide, uv_select) in zip(bm.faces, saved['faces']):
                f.select, f.hide = select, hide
            for e, (select, hide, seam) in zip(bm.edges, saved['edges']):
                e.select, e.hide, e.seam = select, hide, seam
            for v, (select, hide) in zip(bm.verts, saved['verts']):
                v.select, v.hide = select, hide
            uv = bm.loops.layers.uv.get(saved['uv_name']) if saved['uv_name'] else None
            if saved['corners'] is not None:
                if uv is None:
                    raise RuntimeError('展开过程中活动 UV 层丢失')
                for face, face_state, corners in zip(bm.faces, saved['faces'], saved['corners']):
                    if len(face.loops) != len(corners):
                        raise RuntimeError('展开过程中面角点数量改变')
                    if modern:
                        face.uv_select_set(face_state[2])
                    for loop, (coordinate, pin, vert_select, edge_select) in zip(face.loops, corners):
                        loop[uv].uv = coordinate
                        loop[uv].pin_uv = pin
                        if modern:
                            loop.uv_select_edge_set(edge_select)
                        else:
                            loop[uv].select, loop[uv].select_edge = vert_select, edge_select
                if modern:
                    # Edge/face UV setters also propagate to UV vertices. Set
                    # vertex flags only after ALL faces and edges are restored.
                    for face, corners in zip(bm.faces, saved['corners']):
                        for loop, (_, _, vert_select, _) in zip(face.loops, corners):
                            loop.uv_select_vert_set(vert_select)
            if modern:
                bm.uv_select_sync_valid = saved['valid']
            bm.faces.ensure_lookup_table()
            bm.faces.active = bm.faces[saved['active']] if saved['active'] is not None else None
            bm.select_history.clear()
            sequences = {'BMVert': bm.verts, 'BMEdge': bm.edges, 'BMFace': bm.faces}
            for sequence in sequences.values():
                sequence.ensure_lookup_table()
            for kind, index in saved['history']:
                bm.select_history.add(sequences[kind][index])
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
