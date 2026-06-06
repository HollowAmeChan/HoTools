import bpy
import os
from bpy.types import Operator, PropertyGroup
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty


BAKE_TYPES_WITHOUT_VIEW_FROM = {
    'AO',
    'ENVIRONMENT',
}


class RTBakeChannel:
    def __init__(
        self,
        channel_id,
        label,
        bake_type,
        suffix,
        default_enabled=False,
        pass_filter=None
    ):
        self.id = channel_id
        self.label = label
        self.bake_type = bake_type
        self.suffix = suffix
        self.default_enabled = default_enabled
        self.pass_filter = pass_filter
        self.enabled_prop = f"use_{channel_id}"
        self.suffix_prop = f"suffix_{channel_id}"
        self.expand_prop = f"show_{channel_id}_settings"

    def get_suffix(self, rt_settings):
        suffix = getattr(rt_settings, self.suffix_prop).strip()
        return suffix if suffix else self.suffix

    def draw_settings(self, layout, context):
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(rt_settings, self.suffix_prop, text="后缀")

    def prepare(self, context, operator):
        return {'FINISHED'}, None

    def restore(self, context, prepare_state):
        return

    def execute(self, context, operator):
        prepare_result, prepare_state = self.prepare(context, operator)
        if prepare_result != {'FINISHED'}:
            return prepare_result

        scene = context.scene
        try:
            scene.cycles.bake_type = self.bake_type
            apply_rt_bake_view_from(context, self.bake_type)

            temp_targets = ensure_active_image_targets(context, self.bake_type)
            try:
                result = bpy.ops.object.bake(**get_rt_bake_operator_args(context, self))
                if result == {'FINISHED'}:
                    save_baked_images(temp_targets, context, self)
                return result
            finally:
                restore_active_image_targets(temp_targets)
        finally:
            self.restore(context, prepare_state)


class RTShadowCastChannel(RTBakeChannel):
    """
    ShadowCast 仍然走 Cycles 的 bpy.ops.object.bake，不使用 CPU ray_cast。

    工作流程：
    1. bake_type 使用 COMBINED，并把 pass_filter 限制为 DIRECT + DIFFUSE。
       这样只取直接漫射光，避免原材质里的复杂 BSDF、发光、光泽、透射等影响结果。
    2. 如果指定了单独光源，就临时关闭其它 Light 的 render 可见性。
       如果光源为空，就保留当前所有可渲染、可见的 Light。
    3. 烘焙前只把当前选中网格的材质 Surface 临时改成
       白色 Diffuse BSDF -> Material Output，保证 ShadowCast 只受灯光和几何遮挡影响。
    4. 烘焙前把当前 Scene World 临时改成纯白 Background，Strength=1。
    5. Cycles bake 结束后，无论成功或失败，都会恢复灯光 hide_render、
       World、原 Surface 链接、临时节点、节点 active/selection 状态和 material.use_nodes。

    后续如果要做按物体/集合隔离、多次烘焙再合成，应继续放在这个类的
    prepare/execute/restore 流程里，不要塞回主 operator。
    """

    def __init__(self):
        super().__init__(
            "shadowcast",
            "ShadowCast",
            'COMBINED',
            "ShadowCast",
            default_enabled=False,
            pass_filter={'DIRECT', 'DIFFUSE'}
        )

    def draw_settings(self, layout, context):
        super().draw_settings(layout, context)
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(rt_settings, "shadowcast_light", text="光源")

    def prepare(self, context, operator):
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        lights = self.get_lights(context, rt_settings.shadowcast_light)
        if not lights:
            operator.report({'ERROR'}, "没有可用于 ShadowCast 的灯光")
            return {'CANCELLED'}, None

        selected_objs = get_bake_target_objects(context)
        if not selected_objs:
            operator.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}, None

        light_state = self.isolate_lights(context, lights)
        world_state = self.override_world_with_white_background(context.scene)
        material_state = self.override_objects_with_diffuse_bsdf(selected_objs)
        return {'FINISHED'}, {
            "lights": light_state,
            "world": world_state,
            "materials": material_state,
        }

    def restore(self, context, prepare_state):
        if prepare_state is None:
            return
        self.restore_material_overrides(prepare_state.get("materials", []))
        self.restore_world(prepare_state.get("world"))
        self.restore_render_visibility(prepare_state.get("lights", []))

    def get_lights(self, context, specified_light):
        if specified_light is not None and specified_light.type == 'LIGHT':
            return [specified_light]

        lights = []
        for obj in context.scene.objects:
            if obj.type != 'LIGHT' or obj.hide_render:
                continue
            try:
                if obj.hide_get(view_layer=context.view_layer):
                    continue
            except TypeError:
                if obj.hide_get():
                    continue
            lights.append(obj)
        return lights

    def isolate_lights(self, context, enabled_lights):
        enabled_lights = set(enabled_lights)
        state = []
        for obj in context.scene.objects:
            if obj.type != 'LIGHT':
                continue
            state.append((obj, obj.hide_render))
            obj.hide_render = obj not in enabled_lights
        return state

    def restore_render_visibility(self, state):
        for obj, hide_render in state:
            obj.hide_render = hide_render

    def override_world_with_white_background(self, scene):
        world = scene.world
        original_world = world
        if world is None:
            world = bpy.data.worlds.new("HoRTBake_ShadowCast_World")
            scene.world = world

        original_use_nodes = world.use_nodes
        original_color = world.color[:]
        world.use_nodes = True

        node_tree = world.node_tree
        nodes = node_tree.nodes
        links = node_tree.links
        original_active = nodes.active
        selected_nodes = [node for node in nodes if node.select]

        output = None
        for node in nodes:
            if node.bl_idname == 'ShaderNodeOutputWorld' and getattr(node, "is_active_output", False):
                output = node
                break
        if output is None:
            for node in nodes:
                if node.bl_idname == 'ShaderNodeOutputWorld':
                    output = node
                    break

        created_output = False
        if output is None:
            output = nodes.new(type='ShaderNodeOutputWorld')
            created_output = True

        surface_input = output.inputs.get("Surface")
        original_links = []
        if surface_input is not None:
            original_links = [
                (link.from_socket, link.to_socket)
                for link in surface_input.links
            ]
            for link in list(surface_input.links):
                links.remove(link)

        background = nodes.new(type='ShaderNodeBackground')
        background.name = "HoRTBake_ShadowCast_World"
        background.label = "HoRTBake ShadowCast World"
        background.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        background.inputs["Strength"].default_value = 1.0
        temp_link = None
        if surface_input is not None:
            temp_link = links.new(background.outputs["Background"], surface_input)

        return {
            "scene": scene,
            "world": world,
            "original_world": original_world,
            "created_world": original_world is None,
            "original_use_nodes": original_use_nodes,
            "original_color": original_color,
            "created_output": created_output,
            "output": output,
            "background": background,
            "temp_link": temp_link,
            "original_links": original_links,
            "original_active": original_active,
            "selected_nodes": selected_nodes,
        }

    def restore_world(self, state):
        if state is None:
            return

        world = state["world"]
        node_tree = world.node_tree
        if node_tree is not None:
            nodes = node_tree.nodes
            links = node_tree.links
            temp_link = state["temp_link"]
            if temp_link is not None:
                try:
                    links.remove(temp_link)
                except (ReferenceError, RuntimeError):
                    pass

            background = state["background"]
            if background.name in nodes:
                nodes.remove(background)

            output = state["output"]
            if state["created_output"]:
                if output.name in nodes:
                    nodes.remove(output)
            else:
                for from_socket, to_socket in state["original_links"]:
                    try:
                        links.new(from_socket, to_socket)
                    except RuntimeError:
                        pass

                for node in nodes:
                    node.select = False
                for node in state["selected_nodes"]:
                    if node.name in nodes:
                        node.select = True

                original_active = state["original_active"]
                if original_active is not None and original_active.name in nodes:
                    nodes.active = original_active

        world.use_nodes = state["original_use_nodes"]
        world.color = state["original_color"]

        if state["created_world"]:
            state["scene"].world = None
            if world.users == 0:
                bpy.data.worlds.remove(world)

    def get_active_material_output(self, nodes):
        for node in nodes:
            if node.bl_idname == 'ShaderNodeOutputMaterial' and getattr(node, "is_active_output", False):
                return node
        for node in nodes:
            if node.bl_idname == 'ShaderNodeOutputMaterial':
                return node
        return None

    def get_unique_materials_from_objects(self, objects):
        materials = []
        seen = set()
        for obj in objects:
            for slot in obj.material_slots:
                mat = slot.material
                if mat is None or mat.name in seen:
                    continue
                seen.add(mat.name)
                materials.append(mat)
        return materials

    def override_objects_with_diffuse_bsdf(self, objects):
        states = []
        for mat in self.get_unique_materials_from_objects(objects):
            original_use_nodes = mat.use_nodes
            mat.use_nodes = True
            node_tree = mat.node_tree
            nodes = node_tree.nodes
            links = node_tree.links
            original_active = nodes.active
            selected_nodes = [node for node in nodes if node.select]

            output = self.get_active_material_output(nodes)
            created_output = False
            if output is None:
                output = nodes.new(type='ShaderNodeOutputMaterial')
                created_output = True

            surface_input = output.inputs.get("Surface")
            if surface_input is None:
                continue

            original_links = [
                (link.from_socket, link.to_socket)
                for link in surface_input.links
            ]
            for link in list(surface_input.links):
                links.remove(link)

            diffuse = nodes.new(type='ShaderNodeBsdfDiffuse')
            diffuse.name = "HoRTBake_ShadowCast_Diffuse"
            diffuse.label = "HoRTBake ShadowCast Diffuse"
            diffuse.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            diffuse.inputs["Roughness"].default_value = 0.5
            temp_link = links.new(diffuse.outputs["BSDF"], surface_input)

            states.append({
                "material": mat,
                "original_use_nodes": original_use_nodes,
                "created_output": created_output,
                "output": output,
                "diffuse": diffuse,
                "temp_link": temp_link,
                "original_links": original_links,
                "original_active": original_active,
                "selected_nodes": selected_nodes,
            })

        return states

    def restore_material_overrides(self, states):
        for state in reversed(states):
            mat = state["material"]
            node_tree = mat.node_tree
            if node_tree is None:
                mat.use_nodes = state["original_use_nodes"]
                continue

            nodes = node_tree.nodes
            links = node_tree.links
            temp_link = state["temp_link"]
            try:
                links.remove(temp_link)
            except (ReferenceError, RuntimeError):
                pass

            diffuse = state["diffuse"]
            if diffuse.name in nodes:
                nodes.remove(diffuse)

            output = state["output"]
            if state["created_output"]:
                if output.name in nodes:
                    nodes.remove(output)
            else:
                for from_socket, to_socket in state["original_links"]:
                    try:
                        links.new(from_socket, to_socket)
                    except RuntimeError:
                        pass

            for node in nodes:
                node.select = False
            for node in state["selected_nodes"]:
                if node.name in nodes:
                    node.select = True

            original_active = state["original_active"]
            if original_active is not None and original_active.name in nodes:
                nodes.active = original_active

            mat.use_nodes = state["original_use_nodes"]


class RTDirectChannel(RTBakeChannel):
    def __init__(self):
        super().__init__(
            "direct",
            "直出",
            'COMBINED',
            "Direct",
            default_enabled=True,
            pass_filter={'DIRECT', 'INDIRECT', 'DIFFUSE', 'GLOSSY', 'TRANSMISSION', 'EMIT'}
        )


class RTAOChannel(RTBakeChannel):
    def __init__(self):
        super().__init__("ao", "环境光遮蔽 (AO)", 'AO', "AO")


class RTShadowChannel(RTBakeChannel):
    def __init__(self):
        super().__init__("shadow", "阴影", 'SHADOW', "Shadow")


class RTEnvironmentChannel(RTBakeChannel):
    def __init__(self):
        super().__init__("environment", "环境", 'ENVIRONMENT', "Environment")


RT_BAKE_CHANNELS = [
    RTDirectChannel(),
    RTAOChannel(),
    RTShadowChannel(),
    RTEnvironmentChannel(),
    RTShadowCastChannel(),
]


MARGIN_SPACE_ITEMS = [
    ('ADJACENT_FACES', "3D空间相邻", "按模型表面相邻关系拓展边距"),
    ('EXTEND', "UV空间相邻", "按UV图像空间向外拓展边距"),
]


NON_COLOR_BAKE_TYPES = {
    'AO',
    'SHADOW',
}


RT_CYCLES_SAMPLING_SETTINGS = (
    'samples',
    'use_adaptive_sampling',
    'adaptive_threshold',
    'adaptive_min_samples',
)

RT_CYCLES_DENOISING_SWITCHES = (
    'use_denoising',
    'use_preview_denoising',
)


def update_margin_space(self, context):
    try:
        context.scene.render.bake.margin_type = self.margin_space
    except AttributeError:
        pass


def update_resolution(self, context):
    try:
        context.scene.render.bake.width = self.resolution
        context.scene.render.bake.height = self.resolution
    except AttributeError:
        pass


def poll_light_object(self, obj):
    return obj is not None and obj.type == 'LIGHT'


class PG_UVTools_RTBakeSettings(PropertyGroup):
    margin_space: EnumProperty(
        name="拓展",
        items=MARGIN_SPACE_ITEMS,
        default='EXTEND',
        update=update_margin_space
    )  # type: ignore
    resolution: IntProperty(
        name="分辨率",
        default=2048,
        min=1,
        update=update_resolution
    )  # type: ignore
    samples: IntProperty(
        name="采样率",
        default=128,
        min=1
    )  # type: ignore
    use_adaptive_sampling: BoolProperty(
        name="自适应采样",
        default=True
    )  # type: ignore
    adaptive_threshold: FloatProperty(
        name="噪声阈值",
        default=0.01,
        min=0.0,
        precision=4
    )  # type: ignore
    adaptive_min_samples: IntProperty(
        name="最小采样",
        default=0,
        min=0
    )  # type: ignore

    use_direct: BoolProperty(name="直出", default=True)  # type: ignore
    suffix_direct: StringProperty(name="直出后缀", default="Direct")  # type: ignore
    show_direct_settings: BoolProperty(name="直出设置", default=False)  # type: ignore
    use_ao: BoolProperty(name="环境光遮蔽 (AO)", default=False)  # type: ignore
    suffix_ao: StringProperty(name="环境光遮蔽后缀", default="AO")  # type: ignore
    show_ao_settings: BoolProperty(name="环境光遮蔽设置", default=False)  # type: ignore
    use_shadow: BoolProperty(name="阴影", default=False)  # type: ignore
    suffix_shadow: StringProperty(name="阴影后缀", default="Shadow")  # type: ignore
    show_shadow_settings: BoolProperty(name="阴影设置", default=False)  # type: ignore
    use_environment: BoolProperty(name="环境", default=False)  # type: ignore
    suffix_environment: StringProperty(name="环境后缀", default="Environment")  # type: ignore
    show_environment_settings: BoolProperty(name="环境设置", default=False)  # type: ignore
    use_shadowcast: BoolProperty(name="ShadowCast", default=False)  # type: ignore
    suffix_shadowcast: StringProperty(name="ShadowCast后缀", default="ShadowCast")  # type: ignore
    show_shadowcast_settings: BoolProperty(name="ShadowCast设置", default=False)  # type: ignore
    shadowcast_light: PointerProperty(
        name="光源",
        type=bpy.types.Object,
        poll=poll_light_object,
        description="指定单独Light;留空时使用所有启用的灯光"
    )  # type: ignore


def reg_props():
    bpy.types.Scene.ho_uvtools_rt_bake_settings = PointerProperty(
        type=PG_UVTools_RTBakeSettings
    )
    return


def ureg_props():
    if hasattr(bpy.types.Scene, "ho_uvtools_rt_bake_settings"):
        del bpy.types.Scene.ho_uvtools_rt_bake_settings
    return


class OT_UVTools_RTBake(Operator):
    """按当前Cycles烘焙设置执行RT烘焙"""
    bl_idname = "ho.uvtools_rt_bake"
    bl_label = "RT烘焙"
    bl_description = "按当前Cycles烘焙设置执行RT烘焙"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            context.scene is not None and
            hasattr(context.scene, "cycles") and
            context.scene.render.engine == 'CYCLES'
        )

    def execute(self, context):
        scene = context.scene
        bake_settings = scene.render.bake
        bake_channels = get_enabled_rt_bake_channels(scene)

        apply_rt_bake_defaults(context)

        filepath = bpy.path.abspath(bake_settings.filepath)
        if not filepath:
            self.report({'ERROR'}, "请先设置外部输出路径")
            return {'CANCELLED'}

        if not bake_channels:
            self.report({'ERROR'}, "请至少启用一个烘焙通道")
            return {'CANCELLED'}

        original_bake_type = scene.cycles.bake_type
        original_cycles_sampling = capture_rt_cycles_sampling(scene)
        original_view_from = bake_settings.view_from

        try:
            apply_rt_cycles_sampling(scene)

            for channel in bake_channels:
                result = channel.execute(context, self)
                if result != {'FINISHED'}:
                    return result
        finally:
            scene.cycles.bake_type = original_bake_type
            restore_rt_cycles_sampling(scene, original_cycles_sampling)
            bake_settings.view_from = original_view_from

        self.report({'INFO'}, f"已导出 {len(bake_channels)} 个RT烘焙通道")
        return {'FINISHED'}


def apply_rt_bake_defaults(context):
    scene = context.scene
    bake_settings = scene.render.bake
    rt_settings = scene.ho_uvtools_rt_bake_settings
    bake_settings.target = 'IMAGE_TEXTURES'
    bake_settings.save_mode = 'EXTERNAL'
    bake_settings.width = rt_settings.resolution
    bake_settings.height = rt_settings.resolution
    bake_settings.margin_type = rt_settings.margin_space
    apply_rt_bake_view_from(context, scene.cycles.bake_type)


def apply_rt_bake_view_from(context, bake_type):
    scene = context.scene
    bake_settings = scene.render.bake
    if scene.camera is not None and bake_type not in BAKE_TYPES_WITHOUT_VIEW_FROM:
        bake_settings.view_from = 'ACTIVE_CAMERA'


def capture_rt_cycles_sampling(scene):
    cycles = scene.cycles
    return {
        attr: getattr(cycles, attr)
        for attr in RT_CYCLES_SAMPLING_SETTINGS + RT_CYCLES_DENOISING_SWITCHES
        if hasattr(cycles, attr)
    }


def apply_rt_cycles_sampling(scene):
    cycles = scene.cycles
    rt_settings = scene.ho_uvtools_rt_bake_settings
    cycles.samples = rt_settings.samples
    cycles.use_adaptive_sampling = rt_settings.use_adaptive_sampling
    cycles.adaptive_threshold = rt_settings.adaptive_threshold
    cycles.adaptive_min_samples = rt_settings.adaptive_min_samples
    for attr in RT_CYCLES_DENOISING_SWITCHES:
        if hasattr(cycles, attr):
            setattr(cycles, attr, False)


def restore_rt_cycles_sampling(scene, original_values):
    cycles = scene.cycles
    for attr, value in original_values.items():
        setattr(cycles, attr, value)


def get_enabled_rt_bake_channels(scene):
    rt_settings = scene.ho_uvtools_rt_bake_settings
    bake_channels = []

    for channel in RT_BAKE_CHANNELS:
        if not getattr(rt_settings, channel.enabled_prop):
            continue

        bake_channels.append(channel)

    return bake_channels


def get_rt_bake_operator_args(context, channel):
    bake_settings = context.scene.render.bake
    args = {
        "type": channel.bake_type,
        "filepath": bpy.path.abspath(bake_settings.filepath),
        "width": bake_settings.width,
        "height": bake_settings.height,
        "margin": bake_settings.margin,
        "margin_type": bake_settings.margin_type,
        "use_selected_to_active": False,
        "target": 'IMAGE_TEXTURES',
        "save_mode": 'EXTERNAL',
        "use_clear": False,
        "use_cage": False,
        "use_split_materials": bake_settings.use_split_materials,
        "use_automatic_name": False,
    }

    pass_filter = channel.pass_filter
    if pass_filter is not None:
        args["pass_filter"] = set(pass_filter)

    return args


def get_bake_target_objects(context):
    return [
        obj for obj in context.selected_objects
        if obj.type == 'MESH'
    ]


def clean_filename_part(name):
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)


def get_image_format_extension(file_format):
    return {
        'BMP': ".bmp",
        'IRIS': ".rgb",
        'PNG': ".png",
        'JPEG': ".jpg",
        'JPEG2000': ".jp2",
        'TARGA': ".tga",
        'TARGA_RAW': ".tga",
        'CINEON': ".cin",
        'DPX': ".dpx",
        'OPEN_EXR_MULTILAYER': ".exr",
        'OPEN_EXR': ".exr",
        'HDR': ".hdr",
        'TIFF': ".tif",
        'WEBP': ".webp",
    }.get(file_format, ".png")


def make_temp_image_name(obj, mat, slot_index, split_materials):
    if split_materials and mat is not None:
        return f"HoRTBake_{mat.name}"
    return f"HoRTBake_{obj.name}_{slot_index}"


def set_image_color_space(image, bake_type):
    if bake_type not in NON_COLOR_BAKE_TYPES:
        return
    try:
        image.colorspace_settings.name = 'Non-Color'
    except TypeError:
        pass


def ensure_active_image_targets(context, bake_type):
    scene = context.scene
    bake_settings = scene.render.bake
    shared_image = None
    shared_name = "Bake"
    image_by_material = {}
    targets = []

    for obj in get_bake_target_objects(context):
        if not obj.material_slots:
            continue

        for slot_index, slot in enumerate(obj.material_slots):
            mat = slot.material
            if mat is None:
                continue

            original_use_nodes = mat.use_nodes
            mat.use_nodes = True
            node_tree = mat.node_tree
            nodes = node_tree.nodes
            original_active = nodes.active
            selected_nodes = [node for node in nodes if node.select]

            if bake_settings.use_split_materials:
                image_key = mat.name
                image = image_by_material.get(image_key)
                if image is None:
                    image = bpy.data.images.new(
                        make_temp_image_name(obj, mat, slot_index, True),
                        bake_settings.width,
                        bake_settings.height,
                        alpha=True
                    )
                    set_image_color_space(image, bake_type)
                    image_by_material[image_key] = image
            else:
                if shared_image is None:
                    shared_image = bpy.data.images.new(
                        "HoRTBake_Merged",
                        bake_settings.width,
                        bake_settings.height,
                        alpha=True
                    )
                    set_image_color_space(shared_image, bake_type)
                image = shared_image

            node = nodes.new(type='ShaderNodeTexImage')
            node.name = "HoRTBake_Target"
            node.label = "HoRTBake Target"
            node.image = image

            for selected_node in selected_nodes:
                selected_node.select = False
            node.select = True
            nodes.active = node

            targets.append({
                "material": mat,
                "original_use_nodes": original_use_nodes,
                "original_active": original_active,
                "selected_nodes": selected_nodes,
                "node": node,
                "image": image,
                "image_name": mat.name if bake_settings.use_split_materials else shared_name,
            })

    return targets


def get_unique_bake_images(targets):
    unique_images = []
    seen = set()
    for target in targets:
        image = target["image"]
        if image.name in seen:
            continue
        seen.add(image.name)
        unique_images.append((image, target["image_name"]))
    return unique_images


def get_bake_output_path(base_filepath, image_name, context, channel):
    bake_settings = context.scene.render.bake
    image_settings = bake_settings.image_settings
    filepath = bpy.path.abspath(base_filepath)
    directory, filename = os.path.split(filepath)
    stem, ext = os.path.splitext(filename)
    if not ext:
        ext = get_image_format_extension(image_settings.file_format)
    if not stem:
        stem = "Bake"

    suffix_parts = [
        clean_filename_part(
            channel.get_suffix(context.scene.ho_uvtools_rt_bake_settings)
        )
    ]
    if bake_settings.use_split_materials:
        suffix_parts.append(clean_filename_part(image_name))

    if suffix_parts:
        stem = stem + "_" + "_".join(suffix_parts)

    return os.path.join(directory, stem + ext)


def save_baked_images(targets, context, channel):
    bake_settings = context.scene.render.bake
    image_settings = bake_settings.image_settings

    for image, image_name in get_unique_bake_images(targets):
        filepath = get_bake_output_path(bake_settings.filepath, image_name, context, channel)
        directory = os.path.dirname(filepath)
        if directory:
            os.makedirs(directory, exist_ok=True)

        image.filepath_raw = filepath
        image.file_format = image_settings.file_format
        image.save()


def restore_active_image_targets(targets):
    images = []
    for target in reversed(targets):
        mat = target["material"]
        node_tree = mat.node_tree
        if node_tree is None:
            continue

        nodes = node_tree.nodes
        node = target["node"]
        if node.name in nodes:
            nodes.remove(node)

        for selected_node in target["selected_nodes"]:
            if selected_node.name in nodes:
                selected_node.select = True

        original_active = target["original_active"]
        if original_active is not None and original_active.name in nodes:
            nodes.active = original_active

        mat.use_nodes = target["original_use_nodes"]

        image = target["image"]
        if image not in images:
            images.append(image)

    for image in images:
        if image.name in bpy.data.images and image.users == 0:
            bpy.data.images.remove(image)


def draw_rt_bake_output(layout: bpy.types.UILayout, context):
    bake_settings = context.scene.render.bake
    rt_settings = context.scene.ho_uvtools_rt_bake_settings

    box = layout.box()
    box.label(text="输出")

    col = box.column(align=True)
    col.prop(bake_settings, "filepath", text="路径")
    col.prop(rt_settings, "resolution")
    col.prop(bake_settings.image_settings, "file_format", text="格式")
    col.prop(bake_settings, "use_split_materials", text="按材质分离")

    margin_col = box.column(align=True)
    margin_col.prop(rt_settings, "margin_space")
    margin_col.prop(bake_settings, "margin", text="边距")


def draw_rt_bake_sampling(layout: bpy.types.UILayout, context):
    rt_settings = context.scene.ho_uvtools_rt_bake_settings

    box = layout.box()
    box.label(text="采样")

    col = box.column(align=True)
    col.prop(rt_settings, "samples")
    col.prop(rt_settings, "use_adaptive_sampling")

    adaptive_col = col.column(align=True)
    adaptive_col.enabled = rt_settings.use_adaptive_sampling
    adaptive_col.prop(rt_settings, "adaptive_threshold")
    adaptive_col.prop(rt_settings, "adaptive_min_samples")


def draw_rt_bake_channels(layout: bpy.types.UILayout, context):
    rt_settings = context.scene.ho_uvtools_rt_bake_settings

    box = layout.box()
    box.label(text="通道")

    col = box.column(align=True)
    col.use_property_split = False
    col.use_property_decorate = False

    for channel in RT_BAKE_CHANNELS:
        is_expanded = getattr(rt_settings, channel.expand_prop)
        row = col.row(align=True)
        row.prop(
            rt_settings,
            channel.expand_prop,
            text="",
            icon='TRIA_DOWN' if is_expanded else 'TRIA_RIGHT',
            emboss=False
        )
        row.prop(rt_settings, channel.enabled_prop, text=channel.label, toggle=True)

        if is_expanded:
            settings_box = col.box()
            settings_box.enabled = getattr(rt_settings, channel.enabled_prop)
            channel.draw_settings(settings_box, context)


def draw_rt_bake_settings(layout: bpy.types.UILayout, context, use_box=True):
    scene = context.scene
    bake_settings = scene.render.bake

    root = layout.box() if use_box else layout
    root.use_property_split = True
    root.use_property_decorate = False

    col = root.column(align=True)
    row = col.row()
    row.prop(bake_settings, "view_from", text="观察方位")
    row.active = scene.camera is not None

    draw_rt_bake_sampling(root, context)
    draw_rt_bake_channels(root, context)
    draw_rt_bake_output(root, context)


def drawRTBakePanel(layout: bpy.types.UILayout, context):
    box = layout.box()
    box.operator(OT_UVTools_RTBake.bl_idname, text="烘焙", icon="RENDER_STILL")

    if context.scene.render.engine != 'CYCLES':
        box.label(text="请先切换到Cycles渲染器", icon="ERROR")
        return

    draw_rt_bake_settings(layout, context)
    return


cls = [
    PG_UVTools_RTBakeSettings,
    OT_UVTools_RTBake,
]


def register():
    for i in cls:
        bpy.utils.register_class(i)

    reg_props()


def unregister():
    ureg_props()

    for i in reversed(cls):
        bpy.utils.unregister_class(i)
