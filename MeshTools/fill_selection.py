"""Select the connected mesh region under the cursor."""

import bpy


class OP_FillSelection(bpy.types.Operator):
    bl_idname = 'ho.fill_selection'
    bl_label = '填充选择'
    bl_description = '选择鼠标位置所在的连续网格区域'
    bl_options = {'REGISTER', 'UNDO'}

    event: bpy.types.Event  # type: ignore
    location: tuple[int, int]  # type: ignore

    @classmethod
    def poll(cls, context):
        return (
            context.active_object is not None
            and context.active_object.type == 'MESH'
            and context.mode == 'EDIT_MESH'
        )

    def execute(self, context):
        bpy.ops.mesh.hide()
        bpy.ops.view3d.select(location=self.location)
        bpy.ops.mesh.select_linked()
        bpy.ops.mesh.reveal()
        return {'FINISHED'}

    def invoke(self, context, event):
        self.event = event
        self.location = (event.mouse_region_x, event.mouse_region_y)
        return self.execute(context)
