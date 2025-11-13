import bpy
from bpy.types import Panel,PropertyGroup,UIList,Armature,Object
from bpy.props import StringProperty,BoolProperty,IntProperty,CollectionProperty,PointerProperty


class PG_VertexGroupExtraInfo(PropertyGroup):
    """缓存内容,新建需要填入link_obj,vgroup_name,vgroup_uuid"""
    vgroup_uuid: IntProperty(default=0) # type: ignore
    vgroup_name: StringProperty() # type: ignore
    link_obj: PointerProperty(type=bpy.types.Object) # type: ignore
    is_bone_group: BoolProperty(default=False) # type: ignore

    @property
    def vertex_group(self):
        """安全获取顶点组，处理删除/改名情况"""
        if not self.link_obj:
            return None
        for vg in self.link_obj.vertex_groups:
            if vg.session_uuid == self.vgroup_uuid:
                self.vgroup_name = vg.name  # 更新名称
                return vg
            if vg.name == self.vgroup_name:  # 通过名称找回
                self.vgroup_uuid = vg.session_uuid
                return vg
        return None

def get_obj_armature(obj)->Armature:
    if obj.type == 'ARMATURE':# 如果物体本身就是骨架，直接返回
        return obj
    # 检查父级骨架
    parent_armature = None
    parent = obj.parent
    while parent:
        if parent.type == 'ARMATURE':
            parent_armature = parent
            break
        parent = parent.parent

    # 检查Armature修改器指向的骨架
    modifier_armature = None
    for modifier in obj.modifiers:
        if modifier.type == 'ARMATURE' and modifier.object:
            modifier_armature = modifier.object
            break  # 只检查第一个有效的Armature修改器

    if parent_armature == modifier_armature:
        return parent_armature  # 两者一致，返回该骨架
    else:
        return None  # 两者不一致，返回None
    
def refresh_vgroup_extra_info(obj):
    """刷新缓存有效性"""
    #清洗链接丢失的数据
    for i in reversed(range(len(obj.ho_vg_advancedlist_extrainfo))):
        obj = obj.ho_vg_advancedlist_extrainfo[i].link_obj
        uuid = obj.ho_vg_advancedlist_extrainfo[i].vgroup_uuid

    #刷新骨权重标记
    arm:Armature = get_obj_armature(obj)
    for i in obj.ho_vg_advancedlist_extrainfo:
        #取得链接的顶点组
        vertex_group = None
        for vg in obj.vertex_groups:
            if vg.session_uuid == i.vgroup_uuid:
                vertex_group = vg

        #判定是否是骨权重
        if not vertex_group:
            continue
        for bone in arm.bones:
            if bone.name == vertex_group.name:
                i.is_bone_group = True
                break


class UL_VertexGroup_AdvancedList(UIList):
    """高级列表,会从外部collection中读取额外信息"""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        obj = data
        vg = item  # VertexGroup
        # # 额外信息
        # extra_info = None
        # if index < len(obj.ho_vg_advancedlist_extrainfo):
        #     extra_info = obj.ho_vg_advancedlist_extrainfo[index]

        row = layout.row(align=True)
        row.label(text=vg.name, icon='GROUP_VERTEX')

        # if extra_info:
        #     if extra_info.is_bone_group:
        #         row.label(text="骨骼", icon='ARMATURE_DATA')
        #     else:
        #         row.label(text="非骨骼", icon='MESH_DATA')
        # else:
        #     row.label(text="(未知)", icon='QUESTION')




def reg_props():
    bpy.types.Object.ho_vg_advancedlist_extrainfo = CollectionProperty(type=PG_VertexGroupExtraInfo)#大缓存
    return 


def ureg_props():
   return 


cls = [PG_VertexGroupExtraInfo,UL_VertexGroup_AdvancedList]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
