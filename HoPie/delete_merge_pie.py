import bmesh
import bpy


def _mesh_operator(pie, operator_id, text, icon, **properties):
    operator = pie.operator(operator_id, text=text, icon=icon)
    for name, value in properties.items():
        setattr(operator, name, value)
    return operator


def _merge_to_selection_end(context, use_last):
    active = context.active_object
    if not active or active.type != 'MESH' or context.mode != 'EDIT_MESH':
        return {'CANCELLED'}

    bm = bmesh.from_edit_mesh(active.data)
    selected = [vert for vert in bm.verts if vert.select]
    if len(selected) < 2:
        return {'CANCELLED'}

    history = [
        element
        for element in bm.select_history
        if isinstance(element, bmesh.types.BMVert) and element.select
    ]
    if history:
        target = history[-1] if use_last else history[0]
    else:
        target = selected[-1] if use_last else selected[0]
    bmesh.ops.pointmerge(bm, verts=selected, merge_co=target.co.copy())
    bmesh.update_edit_mesh(active.data, loop_triangles=False, destructive=True)
    return {'FINISHED'}


class OP_MergeToFirst(bpy.types.Operator):
    bl_idname = 'ho.merge_to_first'
    bl_label = '合到首'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == 'EDIT_MESH'
            and bool(context.active_object)
            and context.active_object.type == 'MESH'
        )

    def execute(self, context):
        return _merge_to_selection_end(context, use_last=False)


class OP_MergeToLast(bpy.types.Operator):
    bl_idname = 'ho.merge_to_last'
    bl_label = '合到尾'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == 'EDIT_MESH'
            and bool(context.active_object)
            and context.active_object.type == 'MESH'
        )

    def execute(self, context):
        return _merge_to_selection_end(context, use_last=True)


class HO_MT_delete_merge_pie(bpy.types.Menu):
    bl_idname = 'HO_MT_delete_merge_pie'
    bl_label = '饼:删除与合并'

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        pie = self.layout.menu_pie()
        _mesh_operator(
            pie,
            'mesh.delete',
            '删面',
            'AREA_DOCK',
            type='FACE',
        )
        _mesh_operator(
            pie,
            'mesh.merge',
            '合到中',
            'UV_SYNC_SELECT',
            type='CENTER',
        )
        pie.separator()
        _mesh_operator(pie, 'mesh.dissolve_edges', '融并边', 'EDGESEL')
        _mesh_operator(pie, 'mesh.dissolve_verts', '融并顶点', 'FACE_CORNER')
        _mesh_operator(pie, OP_MergeToFirst.bl_idname, '合到首', 'BACK')
        _mesh_operator(
            pie,
            'mesh.delete',
            '删点',
            'LAYER_ACTIVE',
            type='VERT',
        )
        _mesh_operator(pie, OP_MergeToLast.bl_idname, '合到尾', 'FORWARD')
        # PME reserves slots 8 and 9 for the center column below the pie.
        pie.separator()
        pie.separator()
        center = pie.column(align=True)
        center.separator()
        row = center.row(align=True)
        row.scale_y = 1.5
        row.operator(
            'wm.call_menu',
            text='删除',
        ).name = 'VIEW3D_MT_edit_mesh_delete'
        row.operator(
            'wm.call_menu',
            text='合并',
        ).name = 'VIEW3D_MT_edit_mesh_merge'


DELETE_MERGE_PIE_CLASSES = (
    OP_MergeToFirst,
    OP_MergeToLast,
    HO_MT_delete_merge_pie,
)
