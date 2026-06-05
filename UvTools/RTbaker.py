import bpy
import os
from bpy.types import Operator, PropertyGroup
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty


BAKE_TYPES_WITHOUT_VIEW_FROM = {
    'AO',
    'ENVIRONMENT',
}


RT_BAKE_CHANNELS = [
    {
        "id": "combined",
        "label": "合并结果",
        "type": 'COMBINED',
        "suffix": "Combined",
        "pass_filter": {'DIRECT', 'INDIRECT', 'DIFFUSE', 'GLOSSY', 'TRANSMISSION', 'EMIT'},
    },
    {
        "id": "ao",
        "label": "环境光遮蔽 (AO)",
        "type": 'AO', 
        "suffix": "AO"
    },
    {
        "id": "shadow", 
        "label": "阴影", 
        "type": 'SHADOW', 
        "suffix": "Shadow"
    },
    {
        "id": "environment", 
        "label": "环境", 
        "type": 'ENVIRONMENT', 
        "suffix": "Environment"
    },
    {
        "id": "diffuse",
        "label": "漫射",
        "type": 'DIFFUSE',
        "suffix": "Diffuse",
        "pass_filter": {'DIRECT', 'INDIRECT', 'COLOR'},
    },
    {
        "id": "glossy",
        "label": "光泽",
        "type": 'GLOSSY',
        "suffix": "Glossy",
        "pass_filter": {'DIRECT', 'INDIRECT', 'COLOR'},
    },
    {
        "id": "transmission",
        "label": "透射",
        "type": 'TRANSMISSION',
        "suffix": "Transmission",
        "pass_filter": {'DIRECT', 'INDIRECT', 'COLOR'},
    },
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

    use_combined: BoolProperty(name="合并结果", default=False)  # type: ignore
    suffix_combined: StringProperty(name="合并结果后缀", default="Combined")  # type: ignore
    use_ao: BoolProperty(name="环境光遮蔽 (AO)", default=True)  # type: ignore
    suffix_ao: StringProperty(name="环境光遮蔽后缀", default="AO")  # type: ignore
    use_shadow: BoolProperty(name="阴影", default=True)  # type: ignore
    suffix_shadow: StringProperty(name="阴影后缀", default="Shadow")  # type: ignore
    use_environment: BoolProperty(name="环境", default=True)  # type: ignore
    suffix_environment: StringProperty(name="环境后缀", default="Environment")  # type: ignore
    use_diffuse: BoolProperty(name="漫射", default=True)  # type: ignore
    suffix_diffuse: StringProperty(name="漫射后缀", default="Diffuse")  # type: ignore
    use_glossy: BoolProperty(name="光泽", default=True)  # type: ignore
    suffix_glossy: StringProperty(name="光泽后缀", default="Glossy")  # type: ignore
    use_transmission: BoolProperty(name="透射", default=True)  # type: ignore
    suffix_transmission: StringProperty(name="透射后缀", default="Transmission")  # type: ignore


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
                scene.cycles.bake_type = channel["type"]
                apply_rt_bake_view_from(context, channel["type"])

                temp_targets = ensure_active_image_targets(context, channel["type"])
                try:
                    result = bpy.ops.object.bake(**get_rt_bake_operator_args(context, channel))
                    if result != {'FINISHED'}:
                        return result
                    save_baked_images(temp_targets, context, channel)
                finally:
                    restore_active_image_targets(temp_targets)
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
        for attr in RT_CYCLES_SAMPLING_SETTINGS
        if hasattr(cycles, attr)
    }


def apply_rt_cycles_sampling(scene):
    cycles = scene.cycles
    rt_settings = scene.ho_uvtools_rt_bake_settings
    cycles.samples = rt_settings.samples
    cycles.use_adaptive_sampling = rt_settings.use_adaptive_sampling
    cycles.adaptive_threshold = rt_settings.adaptive_threshold
    cycles.adaptive_min_samples = rt_settings.adaptive_min_samples


def restore_rt_cycles_sampling(scene, original_values):
    cycles = scene.cycles
    for attr, value in original_values.items():
        setattr(cycles, attr, value)


def get_enabled_rt_bake_channels(scene):
    rt_settings = scene.ho_uvtools_rt_bake_settings
    bake_channels = []

    for channel in RT_BAKE_CHANNELS:
        channel_id = channel["id"]
        if not getattr(rt_settings, f"use_{channel_id}"):
            continue

        bake_channel = dict(channel)
        suffix = getattr(rt_settings, f"suffix_{channel_id}").strip()
        bake_channel["suffix"] = suffix if suffix else channel["suffix"]
        bake_channels.append(bake_channel)

    return bake_channels


def get_rt_bake_operator_args(context, channel):
    bake_settings = context.scene.render.bake
    args = {
        "type": channel["type"],
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

    pass_filter = channel.get("pass_filter")
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

    suffix_parts = [clean_filename_part(channel["suffix"])]
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
        channel_id = channel["id"]
        row = col.row(align=True)
        row.prop(rt_settings, f"use_{channel_id}", text=channel["label"], toggle=True)

        suffix_row = row.row(align=True)
        suffix_row.enabled = getattr(rt_settings, f"use_{channel_id}")
        suffix_row.prop(rt_settings, f"suffix_{channel_id}", text="")


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
