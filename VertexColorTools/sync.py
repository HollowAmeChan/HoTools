import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty


VC_LISTENER_CACHE = {
    "active_color": None,
    "render_color": None,
}


def get_active_color_name(color_attributes):
    if len(color_attributes) == 0:
        return None

    active_name = getattr(color_attributes, "active_color_name", "")
    if active_name:
        return active_name

    active_index = color_attributes.active_color_index
    if 0 <= active_index < len(color_attributes):
        return color_attributes[active_index].name
    return None


def get_render_color_name(color_attributes):
    if len(color_attributes) == 0:
        return None

    render_name = getattr(color_attributes, "default_color_name", "")
    if render_name:
        return render_name

    render_index = getattr(color_attributes, "render_color_index", -1)
    if 0 <= render_index < len(color_attributes):
        return color_attributes[render_index].name
    return None


def find_color_attribute_index(color_attributes, target_name):
    if not target_name:
        return -1

    for index, attribute in enumerate(color_attributes):
        if attribute.name == target_name:
            return index
    return -1


def vertex_color_listener(scene):
    del scene

    context = bpy.context
    active_obj = context.object
    if active_obj is None or active_obj.type != "MESH":
        return

    selected_meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
    if len(selected_meshes) < 2:
        return

    active_attributes = active_obj.data.color_attributes
    if len(active_attributes) == 0:
        return

    active_color_name = get_active_color_name(active_attributes)
    render_color_name = get_render_color_name(active_attributes)

    if (
        VC_LISTENER_CACHE["active_color"] == active_color_name
        and VC_LISTENER_CACHE["render_color"] == render_color_name
    ):
        return

    VC_LISTENER_CACHE["active_color"] = active_color_name
    VC_LISTENER_CACHE["render_color"] = render_color_name

    for obj in selected_meshes:
        if obj == active_obj:
            continue

        color_attributes = obj.data.color_attributes
        if len(color_attributes) == 0:
            continue

        active_index = find_color_attribute_index(color_attributes, active_color_name)
        if active_index != -1:
            color_attributes.active_color_index = active_index

        render_index = find_color_attribute_index(color_attributes, render_color_name)
        if render_index != -1 and hasattr(color_attributes, "render_color_index"):
            color_attributes.render_color_index = render_index


def update_color_listener_switch(self, context):
    enabled = context.scene.hoVertexColorTools_control_color_attribute_listener
    if enabled:
        if vertex_color_listener not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(vertex_color_listener)
    else:
        if vertex_color_listener in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(vertex_color_listener)


@persistent
def vertex_color_load_handler(dummy):
    for scene in bpy.data.scenes:
        if (
            hasattr(scene, "hoVertexColorTools_control_color_attribute_listener")
            and scene.hoVertexColorTools_control_color_attribute_listener
        ):
            if vertex_color_listener not in bpy.app.handlers.depsgraph_update_post:
                bpy.app.handlers.depsgraph_update_post.append(vertex_color_listener)
            break


def register():
    bpy.types.Scene.hoVertexColorTools_control_color_attribute_listener = BoolProperty(
        name="启用顶点色多物体同步",
        description="同步活动顶点色层和渲染顶点色层",
        default=False,
        update=update_color_listener_switch,
    )
    if vertex_color_load_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(vertex_color_load_handler)


def unregister():
    if vertex_color_listener in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(vertex_color_listener)
    if hasattr(bpy.types.Scene, "hoVertexColorTools_control_color_attribute_listener"):
        del bpy.types.Scene.hoVertexColorTools_control_color_attribute_listener
    if vertex_color_load_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(vertex_color_load_handler)
