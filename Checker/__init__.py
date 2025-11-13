import bpy
from bpy.types import Panel,Operator,UIList,PropertyGroup
from bpy.props import BoolProperty,StringProperty,IntProperty,CollectionProperty

from . import check,fix

ICON_MAP_LEVEL = {
            "ERROR": 'CANCEL',
            "WARNING": 'ERROR',
            "INFO": 'DOT',
        }
ICON_MAP_OBJ_TYPE = {
    'MESH': 'MESH_DATA',
    'CURVE': 'CURVE_DATA',
    'ARMATURE': 'ARMATURE_DATA',
    'EMPTY': 'EMPTY_DATA'
}

class PG_Checker_ObjectItem(PropertyGroup):
    name: StringProperty(name="Object Name") # type: ignore

class PG_Checker_ResultItem(PropertyGroup):
    object_name: StringProperty()               # type: ignore # 问题物体名
    message: StringProperty()                   # type: ignore # 问题描述
    level: StringProperty(default="WARNING")    # type: ignore # 可选值: "ERROR", "WARNING","INFO"，对应：高危，警告，一般
    select_operator_id: StringProperty()        # type: ignore # 指向可能的选择操作（选择出问题的区域）
    fix_operator_id: StringProperty()           # type: ignore # 指向可能的修复操作
    cache: StringProperty()                     # type: ignore # 结果缓存


def reg_props():
    bpy.types.Scene.ho_checker_objects = CollectionProperty(type=PG_Checker_ObjectItem)
    bpy.types.Scene.ho_checker_objects_index = IntProperty()
    bpy.types.Scene.ho_checker_results = CollectionProperty(type=PG_Checker_ResultItem)
    return


def ureg_props():
    del bpy.types.Scene.ho_checker_objects
    del bpy.types.Scene.ho_checker_objects_index
    del bpy.types.Scene.ho_checker_results 
    return


class UI_UL_SelectedObjects(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        obj = bpy.data.objects.get(item.name)
        icon = ICON_MAP_OBJ_TYPE.get(obj.type, 'OBJECT_DATA') if obj else 'QUESTION'
        layout.label(text=item.name, icon=icon)


class PL_Checker(Panel):
    bl_idname = "VIEW_PT_Hollow_Checker"
    bl_label = "检查"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        #检查列表
        box = layout.box()
        box.label(text="检查对象")        
        row = box.row(align=True)
        col1 = row.column()
        col1.template_list(
            "UI_UL_SelectedObjects", "",
            scene, "ho_checker_objects",
            scene, "ho_checker_objects_index",
            rows=6
        )
        #运行检查
        r = layout.row(align=True)
        r.scale_y = 2.0
        r.alert = True
        r.operator(OP_Checker_RefreshSelectedObjects.bl_idname, icon="FILE_REFRESH", text="")
        r.alert = False
        r.operator(OP_Checker_Run.bl_idname,text="检查列表物体",icon="INFO")
        #检查结果
        
        box = layout.box()
        results = scene.ho_checker_results
        if not results:
            box.label(text="未发现问题/未执行检查")
            return
        for result in results:
            layout.alert = False
            icon1 = ICON_MAP_LEVEL.get(result.level, 'QUESTION')
            obj = bpy.data.objects.get(result.object_name)
            icon2 = ICON_MAP_OBJ_TYPE.get(obj.type, 'OBJECT_DATA') if obj else 'QUESTION'
            row = box.row(align=True)
            if icon1 == "CANCEL":
                row.alert = True
            r = row.row()
            r.scale_x = 0.6
            r.label(text=result.object_name, icon=icon2)
            row.label(text=result.message, icon=icon1)
            

            #仅选中一个物体，列表只有一个物体，两者相同时绘制
            if not len(scene.ho_checker_objects) == 1:
                continue
            if not context.object:
                continue
            if not context.object.name == scene.ho_checker_objects[0].name:
                continue
            # 重新检查按钮
            if result.select_operator_id:
                op_select = row.operator(result.select_operator_id, text="", icon="RESTRICT_SELECT_OFF")
                op_select.input = result.cache
            # 修复按钮
            if result.fix_operator_id :
                op_fix = row.operator(result.fix_operator_id, text="修复", icon="MODIFIER")

        return



class OP_Checker_RefreshSelectedObjects(Operator):
    bl_idname = "ho.checker_refresh_selected_objects"
    bl_label = "刷新列表"


    def execute(self, context):
        scene = context.scene
        scene.ho_checker_objects.clear()
        scene.ho_checker_results.clear()
        for obj in context.selected_objects:
            item = scene.ho_checker_objects.add()
            item.name = obj.name
        return {'FINISHED'}

class OP_Checker_Run(Operator):
    bl_idname = "ho.checker_run"
    bl_label = "检查列表物体"
    bl_options = {'REGISTER', 'UNDO'}


    @classmethod
    def poll(cls, context):
        scene = context.scene
        return bool(scene.ho_checker_objects and len(scene.ho_checker_objects) > 0)

    def execute(self, context):
        scene = context.scene
        results = scene.ho_checker_results
        results.clear()
        for i in check.CHECK_FUNCTIONS:
            check_func  = i["func"]
            select_func = i["select_operator_id"]
            fix_func = i["fix_operator_id"]
            message = i["message"]
            level = i["level"]
            for j in scene.ho_checker_objects:
                obj_name = j.name
                try:
                    obj = bpy.data.objects[obj_name]
                except:
                    continue
                cache = check_func(obj)
                if cache:
                    r = results.add()
                    r.object_name = obj_name
                    r.message = message
                    r.level= level
                    r.select_operator_id = select_func
                    r.fix_operator_id = fix_func
                    r.cache = str(cache)

        self.report({'INFO'}, "检查完毕")
        return {'FINISHED'}



cls = [
    PL_Checker,PG_Checker_ObjectItem,OP_Checker_RefreshSelectedObjects,UI_UL_SelectedObjects,OP_Checker_Run,
    PG_Checker_ResultItem

       ]


def register():
    fix.register()

    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    fix.unregister()

    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()