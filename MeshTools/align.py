import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from mathutils import Matrix, Vector, Euler, Quaternion
from math import radians
from Utils.hud import begin_hud, draw_hud_rows, end_hud
from Utils.viewport_draw import draw_mesh_wire


obj_align_mode_items = [
    ('ORIGIN', '原点', ''),
    ('CURSOR', '游标', ''),
    ('ACTIVE', '活动项', ''),
    ('FLOOR', '地面', ''),
]

green = (0.25, 1.0, 0.25)
blue = (0.2, 0.6, 1.0)


def get_loc_matrix(location):
    return Matrix.Translation(location)


def get_rot_matrix(rotation):
    return rotation.to_matrix().to_4x4()


def get_sca_matrix(scale):
    matrix = Matrix.Identity(4)
    for index in range(3):
        matrix[index][index] = scale[index]
    return matrix


def average_locations(locations):
    locations = list(locations)
    return sum(locations, Vector()) / len(locations) if locations else Vector()


def compensate_children(obj, old_matrix, new_matrix):
    delta_matrix = new_matrix.inverted_safe() @ old_matrix
    for child in list(obj.children):
        child.matrix_parent_inverse = delta_matrix @ child.matrix_parent_inverse


def parent(obj, parent_obj):
    if obj.parent:
        unparent(obj)
    obj.parent = parent_obj
    obj.matrix_parent_inverse = parent_obj.matrix_world.inverted_safe()


def unparent(obj):
    if obj.parent:
        matrix = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = matrix


def get_coords(mesh, matrix, indices=False):
    coords = [matrix @ vertex.co for vertex in mesh.vertices]
    if indices:
        return coords, [tuple(edge.vertices) for edge in mesh.edges]
    return coords


def printd(data, name='data'):
    print(name)
    print(data)


def _m3_flag(obj, name):
    props = getattr(obj, "M3", None)
    return bool(getattr(props, name, False)) if props else False

class Align(bpy.types.Operator):
    bl_idname = 'ho.align'
    bl_label = '对象对齐'
    bl_description = '按轴对齐对象的位置、旋转和缩放，或将对象放置到两目标之间'
    bl_options = {'REGISTER', 'UNDO'}

    inbetween: BoolProperty(name="对齐到两者之间", default=False)
    is_inbetween: BoolProperty(name="显示两者之间选项", default=True)
    inbetween_flip: BoolProperty(name="翻转", default=False)
    mode: EnumProperty(name='模式', items=obj_align_mode_items, default='FLOOR')
    location: BoolProperty(name='对齐位置', default=True)
    rotation: BoolProperty(name='对齐旋转', default=True)
    scale: BoolProperty(name='对齐缩放', default=False)
    loc_x: BoolProperty(name='X', default=True)
    loc_y: BoolProperty(name='Y', default=True)
    loc_z: BoolProperty(name='Z', default=True)
    rot_x: BoolProperty(name='X', default=True)
    rot_y: BoolProperty(name='Y', default=True)
    rot_z: BoolProperty(name='Z', default=True)
    sca_x: BoolProperty(name='X', default=True)
    sca_y: BoolProperty(name='Y', default=True)
    sca_z: BoolProperty(name='Z', default=True)
    parent_to_bone: BoolProperty(name='父级到骨骼', default=True)
    align_z_to_y: BoolProperty(name='Z 轴对齐 Y 轴', default=True)
    roll: BoolProperty(name='滚转', default=False)
    roll_amount: FloatProperty(name='滚转角度', default=90)
    def draw(self, context):
        layout = self.layout

        column = layout.column()

        if not self.inbetween or not self.is_inbetween:
            row = column.split(factor=0.3)
            row.label(text='对齐到', icon='BONE_DATA' if self.mode == 'ACTIVE' and context.active_bone else 'BLANK1')
            r = row.row()
            r.prop(self, 'mode', expand=True)

            if self.mode == 'ACTIVE' and context.active_bone:
                row = column.split(factor=0.3)
                row.label(text='父级到骨骼')
                row.prop(self, 'parent_to_bone', text='是' if self.parent_to_bone else '否', toggle=True)

                row = column.split(factor=0.3)
                row.label(text='Z 轴对齐 Y 轴')
                row.prop(self, 'align_z_to_y', text='是' if self.align_z_to_y else '否', toggle=True)

                row = column.split(factor=0.3)
                row.prop(self, 'roll', text='滚转')

                r = row.row(align=True)
                r.active = self.roll
                r.prop(self, 'roll_amount', text='')

            else:
                if self.mode in ['ORIGIN', 'CURSOR', 'ACTIVE']:
                    row = column.split(factor=0.3)
                    row.prop(self, 'location', text='位置')

                    r = row.row(align=True)
                    r.active = self.location
                    r.prop(self, 'loc_x', toggle=True)
                    r.prop(self, 'loc_y', toggle=True)
                    r.prop(self, 'loc_z', toggle=True)

                if self.mode in ['CURSOR', 'ACTIVE']:
                    row = column.split(factor=0.3)
                    row.prop(self, 'rotation', text='旋转')

                    r = row.row(align=True)
                    r.active = self.rotation
                    r.prop(self, 'rot_x', toggle=True)
                    r.prop(self, 'rot_y', toggle=True)
                    r.prop(self, 'rot_z', toggle=True)

                if self.mode == 'ACTIVE':
                    row = column.split(factor=0.3)
                    row.prop(self, 'scale', text='缩放')

                    r = row.row(align=True)
                    r.active = self.scale
                    r.prop(self, 'sca_x', toggle=True)
                    r.prop(self, 'sca_y', toggle=True)
                    r.prop(self, 'sca_z', toggle=True)

        if self.is_inbetween:
            row = column.split(factor=0.3)
            row.label(text='对齐到两者之间')
            r = row.row(align=True)
            r.prop(self, 'inbetween', toggle=True)

            if self.inbetween:
                r.prop(self, 'inbetween_flip', toggle=True)

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects and context.mode in ['OBJECT', 'POSE'])

    def execute(self, context):
        active = context.active_object
        sel = context.selected_objects

        if bpy.app.version >= (4, 2, 0):
            context.evaluated_depsgraph_get()

        self.is_inbetween = len(sel) == 3 and active and active in sel

        if self.is_inbetween and self.inbetween:
            self.align_in_between(context, active, [obj for obj in context.selected_objects if obj != active])
            return {'FINISHED'}

        if self.mode in ['ORIGIN', 'CURSOR', 'FLOOR']:

            if active and _m3_flag(active, 'is_group_empty') and active.children:
                sel = [active]

        elif self.mode == 'ACTIVE':
            all_empties = [
                obj
                for obj in sel
                if _m3_flag(obj, 'is_group_empty') and obj != active
            ]
            top_level = [obj for obj in all_empties if obj.parent not in all_empties]

            if top_level:
                sel = top_level

        if self.mode == 'ORIGIN':
            self.align_to_origin(context, sel)

        elif self.mode == 'CURSOR':
            self.align_to_cursor(context, sel)

        elif self.mode == 'ACTIVE':
            if context.active_bone:
                self.align_to_active_bone(active, context.active_bone.name, [obj for obj in sel if obj != active])

            else:
                self.align_to_active_object(context, active, [obj for obj in sel if obj != active])

        elif self.mode == 'FLOOR':
            context.evaluated_depsgraph_get()
            self.drop_to_floor(context, sel)

        return {'FINISHED'}

    def align_to_origin(self, context, sel):
        for obj in sel:
            omx = obj.matrix_world
            oloc, orot, osca = omx.decompose()

            olocx, olocy, olocz = oloc
            orotx, oroty, orotz = orot.to_euler('XYZ')
            oscax, oscay, oscaz = osca

            if self.location:
                locx = 0 if self.loc_x else olocx
                locy = 0 if self.loc_y else olocy
                locz = 0 if self.loc_z else olocz

                loc = get_loc_matrix(Vector((locx, locy, locz)))

            else:
                loc = get_loc_matrix(oloc)

            rot = orot.to_matrix().to_4x4()

            sca = get_sca_matrix(osca)

            if obj.children and context.scene.tool_settings.use_transform_skip_children:
                compensate_children(obj, omx, loc @ rot @ sca)

            obj.matrix_world = loc @ rot @ sca

    def align_to_cursor(self, context, sel):
        cursor = context.scene.cursor
        cursor.rotation_mode = 'XYZ'

        for obj in sel:
            omx = obj.matrix_world
            oloc, orot, osca = omx.decompose()

            olocx, olocy, olocz = oloc
            orotx, oroty, orotz = orot.to_euler('XYZ')
            oscax, oscay, oscaz = osca

            if self.location:
                locx = cursor.location.x if self.loc_x else olocx
                locy = cursor.location.y if self.loc_y else olocy
                locz = cursor.location.z if self.loc_z else olocz

                loc = get_loc_matrix(Vector((locx, locy, locz)))

            else:
                loc = get_loc_matrix(oloc)

            if self.rotation:
                rotx = cursor.rotation_euler.x if self.rot_x else orotx
                roty = cursor.rotation_euler.y if self.rot_y else oroty
                rotz = cursor.rotation_euler.z if self.rot_z else orotz

                rot = get_rot_matrix(Euler((rotx, roty, rotz), 'XYZ'))

            else:
                rot = get_rot_matrix(orot)

            sca = get_sca_matrix(osca)

            if obj.children and context.scene.tool_settings.use_transform_skip_children:
                compensate_children(obj, omx, loc @ rot @ sca)

            obj.matrix_world = loc @ rot @ sca

    def align_to_active_object(self, context, active, sel):
        amx = active.matrix_world
        aloc, arot, asca = amx.decompose()

        alocx, alocy, alocz = aloc
        arotx, aroty, arotz = arot.to_euler('XYZ')
        ascax, ascay, ascaz = asca

        for obj in sel:
            omx = obj.matrix_world
            oloc, orot, osca = omx.decompose()

            olocx, olocy, olocz = oloc
            orotx, oroty, orotz = orot.to_euler('XYZ')
            oscax, oscay, oscaz = osca

            if self.location:
                locx = alocx if self.loc_x else olocx
                locy = alocy if self.loc_y else olocy
                locz = alocz if self.loc_z else olocz

                loc = get_loc_matrix(Vector((locx, locy, locz)))

            else:
                loc = get_loc_matrix(oloc)

            if self.rotation:
                rotx = arotx if self.rot_x else orotx
                roty = aroty if self.rot_y else oroty
                rotz = arotz if self.rot_z else orotz

                rot = get_rot_matrix(Euler((rotx, roty, rotz), 'XYZ'))

            else:
                rot = get_rot_matrix(orot)

            if self.scale:
                scax = ascax if self.sca_x else oscax
                scay = ascay if self.sca_y else oscay
                scaz = ascaz if self.sca_z else oscaz

                sca = get_sca_matrix(Vector((scax, scay, scaz)))

            else:
                sca = get_sca_matrix(osca)

            if obj.children and context.scene.tool_settings.use_transform_skip_children:
                compensate_children(obj, omx, loc @ rot @ sca)

            obj.matrix_world = loc @ rot @ sca

    def align_to_active_bone(self, armature, bonename, sel):
        bone = armature.pose.bones[bonename]

        for obj in sel:
            if self.parent_to_bone:
                obj.parent = armature
                obj.parent_type = 'BONE'
                obj.parent_bone = bonename

            if self.align_z_to_y:
                obj.matrix_world = armature.matrix_world @ bone.matrix @ Matrix.Rotation(radians(-90), 4, 'X') @ Matrix.Rotation(radians(self.roll_amount if self.roll else 0), 4, 'Z')
            else:
                obj.matrix_world = armature.matrix_world @ bone.matrix @ Matrix.Rotation(radians(self.roll_amount if self.roll else 0), 4, 'Y')

    def drop_to_floor(self, context, selection):
        for obj in selection:
            mx = obj.matrix_world
            oldmx = mx.copy()

            if obj.type == 'MESH':
                minz = min((mx @ v.co)[2] for v in obj.data.vertices)
                mx.translation.z -= minz

            elif obj.type == 'EMPTY':
                mx.translation.z -= obj.location.z

            if obj.children and context.scene.tool_settings.use_transform_skip_children:
                compensate_children(obj, oldmx, mx)

    def align_in_between(self, context, active, sel):
        oldmx = active.matrix_world.copy()

        _, rot, sca = oldmx.decompose()
        locations = [obj.matrix_world.to_translation() for obj in sel]

        active_up = rot @ Vector((0, 0, 1))
        sel_up = locations[0] - locations[1]
        mx = get_loc_matrix(average_locations(locations)) @ get_rot_matrix(active_up.rotation_difference(sel_up) @ rot @ Quaternion((1, 0, 0), radians(180 if self.inbetween_flip else 0))) @ get_sca_matrix(sca)

        active.matrix_world = mx

        if active.children and context.scene.tool_settings.use_transform_skip_children:
            compensate_children(active, oldmx, mx)

class AlignRelative(bpy.types.Operator):
    bl_idname = "ho.align_relative"
    bl_label = "相对对齐复制"
    bl_description = "把所选对象的相对布局复制或实例化到新的目标对象"
    bl_options = {'REGISTER', 'UNDO'}

    instance: BoolProperty(name="Instance", default=False)
    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT':
            active = context.active_object
            return bool(active and [obj for obj in context.selected_objects if obj != active])
        return False

    def draw_HUD(self):
        font_id = begin_hud(size=14)
        draw_hud_rows(
            font_id,
            self.HUD_x,
            self.HUD_y,
            [
                (0, "状态: ", "实例" if self.instance else "复制", green if self.instance else blue),
                (22, "空格: ", "确认"),
                (44, "右键/Esc: ", "取消"),
                (66, "左键: ", "选择目标"),
                (88, "Shift+左键: ", "选择多个目标"),
                (110, "滚轮: ", "切换复制 / 实例"),
            ],
        )
        end_hud(font_id)

    def draw_VIEW3D(self):
        for obj in self.targets:
            for batch in self.batches[obj]:
                draw_mesh_wire(batch, color=green if self.instance else blue, alpha=0.5)

    def modal(self, context, event):
        context.area.tag_redraw()

        self.targets = [obj for obj in context.selected_objects if obj not in self.orig_sel]

        for obj in self.targets:
            if obj not in self.batches:
                if self.debug:
                    print("new target:", obj.name)

                self.batches[obj] = [
                    get_coords(
                        aligner.data,
                        obj.matrix_world @ self.deltamx[aligner],
                        indices=True,
                    )
                    for aligner in self.aligners
                    if aligner.type == 'MESH' and aligner.data
                ]

        events = ['MOUSEMOVE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE']

        if event.type in events:

            if event.type == 'MOUSEMOVE':
                self.mousepos = Vector((event.mouse_region_x, event.mouse_region_y))
                self.HUD_x = event.mouse_region_x + 10
                self.HUD_y = event.mouse_region_y + 10

            elif event.type in ['WHEELUPMOUSE', 'WHEELDOWNMOUSE']:
                self.instance = not self.instance
                context.active_object.select_set(True)

        if event.type == 'LEFTMOUSE':
            return {'PASS_THROUGH'}

        elif event.type == 'MIDDLEMOUSE':
            return {'PASS_THROUGH'}

        if event.type == 'SPACE':
            self.finish()

            for target in self.targets:
                self.target_map[target] = {'dups': [],
                                           'map': {}}

                for aligner in self.aligners:
                    dup = aligner.copy()

                    self.target_map[target]['dups'].append(dup)
                    self.target_map[target]['map'][aligner] = dup

                    if aligner.data:
                        dup.data = aligner.data if self.instance else aligner.data.copy()

                    dup.matrix_world = target.matrix_world @ self.deltamx[aligner]

                    for col in aligner.users_collection:
                        col.objects.link(dup)

            if self.debug:
                printd(self.target_map, name='target map')

            for target, dup_data in self.target_map.items():
                if self.debug:
                    print(target.name)

                for dup in dup_data['dups']:
                    if self.debug:
                        print("", dup.name, " > ", dup_data['map'][dup].name)

                    self.reparent(dup_data, target, dup, debug=self.debug)

                    self.remirror(dup_data, target, dup, debug=self.debug)

                    self.regroup(dup_data, target, dup, debug=self.debug)

            bpy.ops.object.select_all(action='DESELECT')

            for target, dup_data in self.target_map.items():
                for dup in dup_data['dups']:
                    dup.select_set(True)
                    context.view_layer.objects.active = dup

            return {'FINISHED'}

        elif event.type in ['RIGHTMOUSE', 'ESC']:
            self.finish()

            bpy.ops.object.select_all(action='DESELECT')

            for obj in self.orig_sel:
                obj.select_set(True)

                if obj == self.active:
                    context.view_layer.objects.active = obj

            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def finish(self):
        view = getattr(self, 'VIEW3D', None)
        hud = getattr(self, 'HUD', None)
        if view is not None:
            bpy.types.SpaceView3D.draw_handler_remove(view, 'WINDOW')
            self.VIEW3D = None
        if hud is not None:
            bpy.types.SpaceView3D.draw_handler_remove(hud, 'WINDOW')
            self.HUD = None
        if getattr(self, 'area', None):
            self.area.tag_redraw()

    def invoke(self, context, event):
        self.debug = True
        self.debug = False

        self.active = context.active_object
        self.aligners = [obj for obj in context.selected_objects if obj != self.active]

        if self.debug:
            print("reference:", self.active.name)
            print(" aligners:", [obj.name for obj in self.aligners])

        self.orig_sel = [self.active] + self.aligners
        self.targets = []
        self.batches = {}
        self.target_map = {}

        self.deltamx = {obj: self.active.matrix_world.inverted_safe() @ obj.matrix_world for obj in self.aligners}
        self.area = context.area
        self.HUD_x = event.mouse_region_x + 10
        self.HUD_y = event.mouse_region_y + 10
        self.active.select_set(True)

        self.HUD = bpy.types.SpaceView3D.draw_handler_add(self.draw_HUD, (), 'WINDOW', 'POST_PIXEL')
        self.VIEW3D = bpy.types.SpaceView3D.draw_handler_add(self.draw_VIEW3D, (), 'WINDOW', 'POST_VIEW')

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def reparent(self, dup_data, target, dup, debug=False):
        if dup.parent and dup.parent in self.orig_sel:
            if dup.parent == self.active:
                pobj = target

                if debug:
                    print("  duplicate is parented to reference", dup.parent.name)

            else:
                pobj = dup_data['map'][dup.parent]
                if debug:
                    print("  duplicate is parented to another aligner", dup.parent.name)

            unparent(dup)
            parent(dup, pobj)

    def remirror(self, dup_data, target, dup, debug=False):
        mirrors = [mod for mod in dup.modifiers if mod.type == 'MIRROR' and mod.mirror_object in self.orig_sel]

        for mod in mirrors:
            if mod.mirror_object == self.active:
                mobj = target
                if debug:
                    print("  duplicate is mirrored accross reference", mod.mirror_object.name)

            else:
                mobj = dup_data['map'][mod.mirror_object]
                if debug:
                    print("  duplicate is mirrored accross another aligner", mod.mirror_object.name)

            mod.mirror_object = mobj

    def regroup(self, dup_data, target, dup, debug=False):
        if _m3_flag(target, 'is_group_object') and target.parent and _m3_flag(target.parent, 'is_group_empty'):
            if (_m3_flag(dup, 'is_group_object') and _m3_flag(self.active, 'is_group_object')) and (dup.parent and self.active.parent) and (_m3_flag(dup.parent, 'is_group_empty') and _m3_flag(self.active.parent, 'is_group_empty')) and (dup.parent == self.active.parent):
                if debug:
                    print("  regrouping to", target.name)

                unparent(dup)
                parent(dup, target.parent)
