import math
import os
import sys
from array import array
from dataclasses import dataclass

import bpy
import numpy as np
try:
    from .._Lib.py313.PIL import Image as PILImage
except (ImportError, ValueError):
    try:
        from .._Lib.py311.PIL import Image as PILImage
    except (ImportError, ValueError):
        lib_variant = 'py313' if sys.version_info[:2] == (3, 13) else 'py311'
        lib_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            '_Lib',
            lib_variant,
        )
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)
        from PIL import Image as PILImage
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator, PropertyGroup, UIList


@dataclass
class MaterialTextures:
    material: bpy.types.Material
    base_node_name: str
    base_image: bpy.types.Image
    normal_node_name: str | None
    normal_image: bpy.types.Image | None
    cell_index: int = 0


@dataclass
class AtlasScan:
    objects: list
    materials: list[MaterialTextures]
    source_size: tuple[int, int]
    grid_size: int
    output_dir: str
    clean_name: str
    base_path: str
    normal_path: str
    has_normal: bool


def _walk_upstream_nodes(socket):
    """Return all nodes feeding a socket, including nodes behind reroutes."""
    result = []
    visited = set()

    def visit_node(node):
        if node.as_pointer() in visited:
            return
        visited.add(node.as_pointer())
        result.append(node)
        for node_input in node.inputs:
            for link in node_input.links:
                if link.is_valid:
                    visit_node(link.from_node)

    for link in socket.links:
        if link.is_valid:
            visit_node(link.from_node)
    return result


def _get_material_surface(material):
    if not material.use_nodes or not material.node_tree:
        raise ValueError(f'材质“{material.name}”未启用节点')

    outputs = [
        node for node in material.node_tree.nodes
        if node.type == 'OUTPUT_MATERIAL' and node.is_active_output
    ]
    if not outputs:
        raise ValueError(f'材质“{material.name}”没有活动的材质输出节点')

    surface = outputs[0].inputs.get('Surface')
    if surface is None:
        raise ValueError(f'材质“{material.name}”的活动输出没有表面输入')
    return surface


def _find_principled(material, surface):
    principled = [
        node for node in _walk_upstream_nodes(surface)
        if node.type == 'BSDF_PRINCIPLED'
    ]
    if len(principled) > 1:
        raise ValueError(
            f'材质“{material.name}”连接到输出的原理化 BSDF 最多只能有一个'
        )
    return principled[0] if principled else None


def _unique_image_nodes(nodes):
    image_nodes = [
        node for node in nodes
        if node.type == 'TEX_IMAGE' and node.image is not None
    ]
    return list({node.as_pointer(): node for node in image_nodes}.values())


def _require_single_base_image(material, image_nodes, source_name):
    if len(image_nodes) != 1:
        raise ValueError(
            f'材质“{material.name}”的{source_name}必须有且只有一张图像纹理'
        )
    return image_nodes[0], image_nodes[0].image


_BASE_COLOR_INPUT_NAMES = (
    'basecolor',
    'basecolour',
    'maincolor',
    'maincolour',
    'albedo',
    'diffusecolor',
    'diffusecolour',
    'diffuse',
    'basetexture',
    'maintexture',
    'basetex',
    'maintex',
    '主色',
    '主颜色',
    '基础色',
    '基础颜色',
    '底色',
    '主贴图',
    '主纹理',
    'color',
    'colour',
    '颜色',
)
_GENERIC_COLOR_INPUT_NAMES = {'color', 'colour', '颜色'}


def _base_color_input_priority(socket):
    normalized = ''.join(
        character.lower() for character in socket.name
        if character.isalnum()
    )
    for priority, name in enumerate(_BASE_COLOR_INPUT_NAMES):
        if normalized == name:
            return priority
    for priority, name in enumerate(_BASE_COLOR_INPUT_NAMES):
        if name not in _GENERIC_COLOR_INPUT_NAMES and name in normalized:
            return len(_BASE_COLOR_INPUT_NAMES) + priority
    return None


def _find_fallback_base_image(material, surface):
    direct_images = _unique_image_nodes(
        link.from_node for link in surface.links if link.is_valid
    )
    if direct_images:
        return _require_single_base_image(
            material,
            direct_images,
            '材质输出直连输入',
        )

    shader_nodes = []
    for link in surface.links:
        if not link.is_valid or link.from_socket.type != 'SHADER':
            continue
        shader_nodes.append(link.from_node)

    image_inputs = []
    preferred_inputs = []
    for shader_index, shader_node in enumerate(shader_nodes):
        for input_index, node_input in enumerate(shader_node.inputs):
            image_nodes = _unique_image_nodes(_walk_upstream_nodes(node_input))
            if not image_nodes:
                continue
            candidate = (
                shader_index,
                input_index,
                shader_node,
                node_input,
                image_nodes,
            )
            image_inputs.append(candidate)
            priority = _base_color_input_priority(node_input)
            if priority is not None:
                preferred_inputs.append((priority, *candidate))

    if preferred_inputs:
        _, _, _, shader_node, node_input, image_nodes = min(
            preferred_inputs,
            key=lambda candidate: candidate[:3],
        )
    elif image_inputs:
        _, _, shader_node, node_input, image_nodes = image_inputs[0]
    else:
        shader_node = None
        node_input = None
        image_nodes = []

    source_name = '着色器节点输入'
    if shader_node is not None:
        source_name = (
            f'着色器节点“{shader_node.name}”的“{node_input.name}”输入'
        )
    return _require_single_base_image(
        material,
        image_nodes,
        source_name,
    )


def _find_single_image(material, socket, channel_name, required):
    image_nodes = _unique_image_nodes(_walk_upstream_nodes(socket))

    if not image_nodes and not required:
        return None, None
    if len(image_nodes) != 1:
        requirement = '需要一张' if required else '最多只能有一张'
        raise ValueError(
            f'材质“{material.name}”的{channel_name}输入{requirement}图像纹理'
        )
    return image_nodes[0], image_nodes[0].image


def _collect_materials(objects):
    materials = []
    seen = set()

    for obj in objects:
        for polygon in obj.data.polygons:
            if polygon.material_index >= len(obj.material_slots):
                raise ValueError(f'物体“{obj.name}”存在无效的材质索引')
            material = obj.material_slots[polygon.material_index].material
            if material is None:
                raise ValueError(f'物体“{obj.name}”存在未指定材质的面')
            pointer = material.as_pointer()
            if pointer in seen:
                continue

            surface = _get_material_surface(material)
            principled = _find_principled(material, surface)
            if principled:
                base_socket = principled.inputs.get('Base Color')
                normal_socket = principled.inputs.get('Normal')
                base_node, base_image = _find_single_image(
                    material, base_socket, '主色', required=True
                )
                normal_node, normal_image = _find_single_image(
                    material, normal_socket, '法线', required=False
                )
            else:
                base_node, base_image = _find_fallback_base_image(
                    material,
                    surface,
                )
                normal_node, normal_image = None, None
            materials.append(MaterialTextures(
                material=material,
                base_node_name=base_node.name,
                base_image=base_image,
                normal_node_name=normal_node.name if normal_node else None,
                normal_image=normal_image,
            ))
            seen.add(pointer)

    if not materials:
        raise ValueError('所选物体没有实际使用的材质')

    for index, item in enumerate(materials):
        item.cell_index = index
    return materials


def _validate_images(materials, force_alignment=False, target_resolution=2048):
    image_roles = {}
    dimensions = set()

    for item in materials:
        for role, image in (('主色', item.base_image), ('法线', item.normal_image)):
            if image is None:
                continue
            if image.source == 'TILED':
                raise ValueError(f'暂不支持 UDIM 图像“{image.name}”')
            width, height = image.size
            if width <= 0 or height <= 0:
                raise ValueError(f'无法读取图像“{image.name}”的尺寸')
            dimensions.add((width, height))

            pointer = image.as_pointer()
            previous_role = image_roles.get(pointer)
            if previous_role and previous_role != role:
                raise ValueError(f'图像“{image.name}”不能同时作为主色和法线使用')
            image_roles[pointer] = role

    if force_alignment:
        if target_resolution <= 0:
            raise ValueError('统一分辨率必须大于 0')
        return target_resolution, target_resolution

    if len(dimensions) != 1:
        sizes = ', '.join(f'{width}x{height}' for width, height in sorted(dimensions))
        raise ValueError(f'所有主色和法线贴图必须尺寸一致；当前尺寸：{sizes}')
    return dimensions.pop()


def _validate_uvs(objects):
    tolerance = 1.0e-6
    for obj in objects:
        uv_layer = obj.data.uv_layers.active
        if uv_layer is None:
            raise ValueError(f'物体“{obj.name}”没有活动 UV 层')
        for uv_loop in uv_layer.data:
            u, v = uv_loop.uv
            if u < -tolerance or u > 1.0 + tolerance or v < -tolerance or v > 1.0 + tolerance:
                raise ValueError(f'物体“{obj.name}”的活动 UV 必须全部位于 0–1 范围')


def _scan_context(context, create_output_dir=False):
    objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
    materials = _collect_materials(objects)
    scene = context.scene
    source_size = _validate_images(
        materials,
        force_alignment=scene.ho_texpacker_force_alignment,
        target_resolution=scene.ho_texpacker_resolution,
    )
    _validate_uvs(objects)

    output_dir = bpy.path.abspath(scene.ho_texpacker_output_dir)
    if not output_dir:
        raise ValueError('请选择输出目录')
    if create_output_dir:
        os.makedirs(output_dir, exist_ok=True)

    clean_name = bpy.path.clean_name(scene.ho_texpacker_atlas_name.strip())
    if not clean_name:
        raise ValueError('图集名称不能为空')

    base_path = os.path.join(output_dir, f'{clean_name}_BaseColor.png')
    has_normal = any(item.normal_image is not None for item in materials)
    normal_path = os.path.join(output_dir, f'{clean_name}_Normal.png')
    output_paths = [base_path] + ([normal_path] if has_normal else [])
    existing = [path for path in output_paths if os.path.exists(path)]
    if existing and not scene.ho_texpacker_overwrite:
        raise ValueError('输出文件已存在；请启用“覆盖同名文件”或修改图集名称')

    return AtlasScan(
        objects=objects,
        materials=materials,
        source_size=source_size,
        grid_size=math.ceil(math.sqrt(len(materials))),
        output_dir=output_dir,
        clean_name=clean_name,
        base_path=base_path,
        normal_path=normal_path,
        has_normal=has_normal,
    )


def _read_pixels(image, pixel_count):
    pixels = array('f', [0.0]) * pixel_count
    image.pixels.foreach_get(pixels)
    return pixels


def _read_image_pixels(image, target_size):
    source_width, source_height = image.size
    target_width, target_height = target_size
    if (source_width, source_height) == target_size:
        return _read_pixels(image, target_width * target_height * 4)

    source_pixels = np.empty(
        (source_height, source_width, 4),
        dtype=np.float32,
    )
    image.pixels.foreach_get(source_pixels.reshape(-1))

    # Filter premultiplied RGB so transparent edges do not bleed their color.
    alpha = source_pixels[..., 3:4]
    source_pixels[..., :3] *= alpha
    resized_channels = []
    for channel in range(4):
        channel_image = PILImage.fromarray(source_pixels[..., channel], mode='F')
        resized = channel_image.resize(
            (target_width, target_height),
            resample=PILImage.Resampling.LANCZOS,
        )
        resized_channels.append(np.asarray(resized, dtype=np.float32))

    resized_pixels = np.stack(resized_channels, axis=-1)
    resized_alpha = resized_pixels[..., 3:4]
    np.divide(
        resized_pixels[..., :3],
        np.maximum(resized_alpha, 1.0e-8),
        out=resized_pixels[..., :3],
        where=resized_alpha > 1.0e-8,
    )
    resized_pixels[..., :3] = np.where(
        resized_alpha > 1.0e-8,
        resized_pixels[..., :3],
        0.0,
    )
    return array('f', resized_pixels.reshape(-1))


def _prepare_image_preview(image, max_size=96):
    source_width, source_height = image.size
    scale = min(1.0, max_size / max(source_width, source_height))
    preview_width = max(1, round(source_width * scale))
    preview_height = max(1, round(source_height * scale))
    source_pixels = image.pixels
    preview_pixels = []

    for preview_y in range(preview_height):
        source_y = min(
            source_height - 1,
            int((preview_y + 0.5) * source_height / preview_height),
        )
        for preview_x in range(preview_width):
            source_x = min(
                source_width - 1,
                int((preview_x + 0.5) * source_width / preview_width),
            )
            source_index = (source_y * source_width + source_x) * 4
            preview_pixels.extend(source_pixels[source_index:source_index + 4])

    preview = image.preview_ensure()
    preview.image_size = (preview_width, preview_height)
    preview.image_pixels_float[:] = preview_pixels
    return preview


def _save_atlas(path, name, width, height, pixels, colorspace):
    generated = bpy.data.images.new(
        name=f'{name}_Generating',
        width=width,
        height=height,
        alpha=True,
        float_buffer=False,
    )
    try:
        generated.colorspace_settings.name = colorspace
        generated.pixels.foreach_set(pixels)
        generated.update()
        generated.filepath_raw = path
        generated.file_format = 'PNG'
        generated.save()
        atlas = bpy.data.images.load(path, check_existing=False)
        atlas.name = name
        atlas.colorspace_settings.name = colorspace
        return atlas
    finally:
        bpy.data.images.remove(generated)


def _build_atlas(materials, image_attr, output_path, atlas_name, source_size,
                 grid_size, colorspace, fill_pixel):
    source_width, source_height = source_size
    atlas_width = source_width * grid_size
    atlas_height = source_height * grid_size
    atlas_pixels = array('f', fill_pixel) * (atlas_width * atlas_height)
    row_length = source_width * 4

    for item in materials:
        image = getattr(item, image_attr)
        if image is None:
            continue
        source_pixels = _read_image_pixels(image, source_size)
        column = item.cell_index % grid_size
        row = item.cell_index // grid_size
        destination_x = column * source_width
        destination_y = row * source_height

        for source_y in range(source_height):
            source_start = source_y * row_length
            destination_start = (
                (destination_y + source_y) * atlas_width + destination_x
            ) * 4
            atlas_pixels[destination_start:destination_start + row_length] = (
                source_pixels[source_start:source_start + row_length]
            )

    return _save_atlas(
        output_path,
        atlas_name,
        atlas_width,
        atlas_height,
        atlas_pixels,
        colorspace,
    )


def _transform_uvs_and_materials(objects, materials, grid_size, source_size,
                                 base_atlas, normal_atlas):
    by_material = {item.material.as_pointer(): item for item in materials}
    material_copies = {}
    source_width, source_height = source_size
    atlas_width = source_width * grid_size
    atlas_height = source_height * grid_size

    for item in materials:
        copied = item.material.copy()
        copied.name = f'{item.material.name}_Atlas'
        copied.node_tree.nodes[item.base_node_name].image = base_atlas
        if item.normal_node_name:
            copied.node_tree.nodes[item.normal_node_name].image = normal_atlas
        material_copies[item.material.as_pointer()] = copied

    for obj in objects:
        if obj.data.users > 1:
            obj.data = obj.data.copy()

        uv_data = obj.data.uv_layers.active.data
        for polygon in obj.data.polygons:
            source_material = obj.material_slots[polygon.material_index].material
            item = by_material[source_material.as_pointer()]
            column = item.cell_index % grid_size
            row = item.cell_index // grid_size

            # Inset the transformed 0 and 1 boundaries to pixel centers. This
            # prevents bilinear filtering from sampling a neighboring cell.
            for loop_index in polygon.loop_indices:
                uv = uv_data[loop_index].uv
                u = min(1.0, max(0.0, uv.x))
                v = min(1.0, max(0.0, uv.y))
                uv.x = (column * source_width + 0.5 + u * (source_width - 1.0)) / atlas_width
                uv.y = (row * source_height + 0.5 + v * (source_height - 1.0)) / atlas_height

        for slot in obj.material_slots:
            if slot.material is None:
                continue
            copied = material_copies.get(slot.material.as_pointer())
            if copied:
                slot.material = copied


class HO_PG_texture_atlas_image(PropertyGroup):
    role: StringProperty()
    image_name: StringProperty()
    resolution: StringProperty()
    colorspace: StringProperty()
    source_info: StringProperty()
    material_name: StringProperty()
    cell_index: IntProperty()
    preview_ready: BoolProperty(options={'HIDDEN'})


class HO_PG_texture_atlas_object(PropertyGroup):
    object_name: StringProperty()
    uv_name: StringProperty()
    polygon_count: IntProperty()
    material_count: IntProperty()


class HO_UL_texture_atlas_images(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index):
        if self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text='', icon='IMAGE_DATA')
            return

        row = layout.row(align=True)
        role = row.row(align=True)
        role.ui_units_x = 5
        role.label(text=item.role, icon='IMAGE_DATA')
        image_name = row.row(align=True)
        image_name.ui_units_x = 12
        image_name.label(text=item.image_name)
        resolution = row.row(align=True)
        resolution.ui_units_x = 7
        resolution.label(text=item.resolution)
        colorspace = row.row(align=True)
        colorspace.ui_units_x = 8
        colorspace.label(text=item.colorspace)
        source = row.row(align=True)
        source.ui_units_x = 14
        source.label(text=item.source_info)
        row.label(text=item.material_name, icon='MATERIAL')


class HO_UL_texture_atlas_objects(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index):
        if self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text='', icon='MESH_DATA')
            return

        row = layout.row(align=True)
        object_name = row.row(align=True)
        object_name.ui_units_x = 16
        object_name.label(text=item.object_name, icon='OBJECT_DATA')
        uv_name = row.row(align=True)
        uv_name.ui_units_x = 14
        uv_name.label(text=item.uv_name, icon='GROUP_UVS')
        faces = row.row(align=True)
        faces.ui_units_x = 8
        faces.label(text=f'{item.polygon_count} 面')
        row.label(text=f'{item.material_count} 材质', icon='MATERIAL')


def _update_base_preview(self, context):
    if self.show_base_preview:
        self._prepare_atlas_previews('主色')


def _update_normal_preview(self, context):
    if self.show_normal_preview:
        self._prepare_atlas_previews('法线')


def _image_source_info(image):
    if image.packed_file:
        return '已打包到 Blend'
    if image.source == 'GENERATED':
        return 'Blender 生成图像'
    if image.filepath:
        return bpy.path.abspath(image.filepath)
    return image.source


class HO_OT_pack_texture_atlas(Operator):
    bl_idname = 'ho.pack_texture_atlas'
    bl_label = '打包主色与法线贴图'
    bl_description = '将所选物体使用的材质贴图和活动 UV 合并到同一个图集'
    bl_options = {'REGISTER', 'UNDO'}

    scan_images: CollectionProperty(type=HO_PG_texture_atlas_image)
    scan_image_index: IntProperty(options={'HIDDEN'})
    scan_objects: CollectionProperty(type=HO_PG_texture_atlas_object)
    scan_object_index: IntProperty(options={'HIDDEN'})
    expected_summary: StringProperty(options={'HIDDEN'})
    expected_base_path: StringProperty(options={'HIDDEN'})
    expected_normal_path: StringProperty(options={'HIDDEN'})
    expected_has_normal: BoolProperty(options={'HIDDEN'})
    expected_grid_size: IntProperty(options={'HIDDEN'})
    show_base_preview: BoolProperty(
        name='主色图集预览',
        default=False,
        options={'SKIP_SAVE'},
        update=_update_base_preview,
    )
    show_normal_preview: BoolProperty(
        name='法线图集预览',
        default=False,
        options={'SKIP_SAVE'},
        update=_update_normal_preview,
    )

    @classmethod
    def poll(cls, context):
        return (
            context.mode == 'OBJECT'
            and any(obj.type == 'MESH' for obj in context.selected_objects)
        )

    def _populate_scan_items(self, scan):
        self.scan_images.clear()
        for material_info in scan.materials:
            for role, image in (
                ('主色', material_info.base_image),
                ('法线', material_info.normal_image),
            ):
                if image is None:
                    continue
                item = self.scan_images.add()
                item.role = role
                item.image_name = image.name
                item.resolution = f'{image.size[0]} x {image.size[1]}'
                item.colorspace = image.colorspace_settings.name
                item.source_info = _image_source_info(image)
                item.material_name = material_info.material.name
                item.cell_index = material_info.cell_index
                item.preview_ready = False

        self.scan_objects.clear()
        for obj in scan.objects:
            item = self.scan_objects.add()
            item.object_name = obj.name
            item.uv_name = obj.data.uv_layers.active.name
            item.polygon_count = len(obj.data.polygons)
            item.material_count = len({
                obj.material_slots[polygon.material_index].material.as_pointer()
                for polygon in obj.data.polygons
            })

        atlas_width = scan.source_size[0] * scan.grid_size
        atlas_height = scan.source_size[1] * scan.grid_size
        self.expected_summary = (
            f'{len(scan.materials)} 个材质，{scan.grid_size} x {scan.grid_size} 排列，'
            f'单格 {scan.source_size[0]} x {scan.source_size[1]} px，'
            f'图集 {atlas_width} x {atlas_height} px'
        )
        self.expected_base_path = scan.base_path
        self.expected_normal_path = scan.normal_path
        self.expected_has_normal = scan.has_normal
        self.expected_grid_size = scan.grid_size

    def _prepare_atlas_previews(self, role):
        for item in self.scan_images:
            if item.role != role or item.preview_ready:
                continue
            image = bpy.data.images.get(item.image_name)
            if image is None:
                continue
            _prepare_image_preview(image)
            item.preview_ready = True

    def _draw_atlas_preview(self, layout, role, expanded_property):
        expanded = getattr(self, expanded_property)
        header = layout.row(align=True)
        header.prop(
            self,
            expanded_property,
            text=f'{role}图集预览',
            icon='TRIA_DOWN' if expanded else 'TRIA_RIGHT',
            emboss=False,
        )
        if not expanded:
            return

        grid_size = max(1, self.expected_grid_size)
        cells = [None] * (grid_size * grid_size)
        for item in self.scan_images:
            if item.role == role and 0 <= item.cell_index < len(cells):
                cells[item.cell_index] = item

        grid = layout.box().grid_flow(
            row_major=True,
            columns=grid_size,
            even_columns=True,
            even_rows=True,
            align=True,
        )
        for cell_index, item in enumerate(cells):
            cell = grid.column(align=True)
            image = bpy.data.images.get(item.image_name) if item else None
            if image is not None:
                tile = cell.box()
                tile.template_icon(
                    icon_value=tile.icon(image),
                    scale=5.0,
                )
            else:
                tile = cell.box()
                tile.template_icon(icon_value=0, scale=5.0)
            cell.label(
                text=(
                    f'{cell_index + 1}'
                    if image is not None else f'{cell_index + 1}  空'
                ),
                icon='IMAGE_DATA' if image is not None else 'BLANK1',
            )

    def invoke(self, context, event):
        try:
            scan = _scan_context(context)
            self._populate_scan_items(scan)
            self.show_base_preview = False
            self.show_normal_preview = False
        except (OSError, RuntimeError, ValueError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(
            self,
            width=760,
            title='确认贴图图集打包',
            confirm_text='确认打包',
        )

    def draw(self, context):
        layout = self.layout

        texture_box = layout.box()
        texture_box.label(
            text=f'扫描到的贴图通道（{len(self.scan_images)}）',
            icon='IMAGE_DATA',
        )
        header = texture_box.row(align=True)
        role = header.row()
        role.ui_units_x = 5
        role.label(text='通道')
        image_name = header.row()
        image_name.ui_units_x = 12
        image_name.label(text='图像')
        resolution = header.row()
        resolution.ui_units_x = 7
        resolution.label(text='尺寸')
        colorspace = header.row()
        colorspace.ui_units_x = 8
        colorspace.label(text='色彩空间')
        source = header.row()
        source.ui_units_x = 14
        source.label(text='来源')
        header.label(text='使用材质')
        texture_box.template_list(
            HO_UL_texture_atlas_images.__name__,
            '',
            self,
            'scan_images',
            self,
            'scan_image_index',
            rows=min(8, max(2, len(self.scan_images))),
        )
        preview_column = texture_box.column(align=True)
        preview_column.separator()
        self._draw_atlas_preview(
            preview_column,
            '主色',
            'show_base_preview',
        )
        if self.expected_has_normal:
            self._draw_atlas_preview(
                preview_column,
                '法线',
                'show_normal_preview',
            )

        output_box = layout.box()
        output_box.label(text='预计输出', icon='FILE_TICK')
        output_box.label(text=self.expected_summary)
        output_box.label(text=f'主色：{self.expected_base_path}', icon='IMAGE_DATA')
        if self.expected_has_normal:
            output_box.label(
                text=f'法线：{self.expected_normal_path}（Non-Color）',
                icon='IMAGE_DATA',
            )
        else:
            output_box.label(text='未扫描到法线贴图，不输出法线图集', icon='INFO')

        object_box = layout.box()
        object_box.label(
            text=f'涉及物体与活动 UV（{len(self.scan_objects)}）',
            icon='OBJECT_DATA',
        )
        header = object_box.row(align=True)
        object_name = header.row()
        object_name.ui_units_x = 16
        object_name.label(text='物体')
        uv_name = header.row()
        uv_name.ui_units_x = 14
        uv_name.label(text='活动 UV')
        faces = header.row()
        faces.ui_units_x = 8
        faces.label(text='面数')
        header.label(text='材质数')
        object_box.template_list(
            HO_UL_texture_atlas_objects.__name__,
            '',
            self,
            'scan_objects',
            self,
            'scan_object_index',
            rows=min(8, max(2, len(self.scan_objects))),
        )

    def execute(self, context):
        try:
            scan = _scan_context(context, create_output_dir=True)
            base_atlas = _build_atlas(
                scan.materials,
                'base_image',
                scan.base_path,
                f'{scan.clean_name}_BaseColor',
                scan.source_size,
                scan.grid_size,
                'sRGB',
                (0.0, 0.0, 0.0, 0.0),
            )

            normal_atlas = None
            if scan.has_normal:
                normal_images = {
                    item.normal_image.as_pointer(): item.normal_image
                    for item in scan.materials if item.normal_image is not None
                }
                old_colorspaces = {
                    pointer: image.colorspace_settings.name
                    for pointer, image in normal_images.items()
                }
                try:
                    for image in normal_images.values():
                        image.colorspace_settings.name = 'Non-Color'
                    normal_atlas = _build_atlas(
                        scan.materials,
                        'normal_image',
                        scan.normal_path,
                        f'{scan.clean_name}_Normal',
                        scan.source_size,
                        scan.grid_size,
                        'Non-Color',
                        (0.5, 0.5, 1.0, 1.0),
                    )
                finally:
                    for pointer, image in normal_images.items():
                        image.colorspace_settings.name = old_colorspaces[pointer]

            _transform_uvs_and_materials(
                scan.objects,
                scan.materials,
                scan.grid_size,
                scan.source_size,
                base_atlas,
                normal_atlas,
            )
        except (OSError, RuntimeError, ValueError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}

        atlas_width = scan.source_size[0] * scan.grid_size
        atlas_height = scan.source_size[1] * scan.grid_size
        self.report({
            'INFO'
        }, f'已打包 {len(scan.materials)} 个材质：{atlas_width}x{atlas_height}')
        return {'FINISHED'}


def drawTexPackerPanel(layout, context):
    scene = context.scene
    column = layout.column(align=True)
    column.prop(scene, 'ho_texpacker_output_dir', text='输出目录')
    column.prop(scene, 'ho_texpacker_atlas_name', text='图集名称')
    column.prop(scene, 'ho_texpacker_overwrite', text='覆盖同名文件')
    column.prop(scene, 'ho_texpacker_force_alignment', text='强制统一分辨率')
    resolution_row = column.row(align=True)
    resolution_row.enabled = scene.ho_texpacker_force_alignment
    resolution_row.prop(scene, 'ho_texpacker_resolution', text='单格分辨率')
    column.separator()
    column.operator(HO_OT_pack_texture_atlas.bl_idname, icon='UV')


classes = (
    HO_PG_texture_atlas_image,
    HO_PG_texture_atlas_object,
    HO_UL_texture_atlas_images,
    HO_UL_texture_atlas_objects,
    HO_OT_pack_texture_atlas,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ho_texpacker_output_dir = StringProperty(
        name='输出目录',
        description='主色与法线图集 PNG 的保存目录',
        subtype='DIR_PATH',
        default='//',
    )
    bpy.types.Scene.ho_texpacker_atlas_name = StringProperty(
        name='图集名称',
        default='TextureAtlas',
    )
    bpy.types.Scene.ho_texpacker_overwrite = BoolProperty(
        name='覆盖同名文件',
        default=False,
    )
    bpy.types.Scene.ho_texpacker_force_alignment = BoolProperty(
        name='强制统一分辨率',
        description='将所有主色与法线贴图抗锯齿缩放到统一的正方形分辨率',
        default=True,
    )
    bpy.types.Scene.ho_texpacker_resolution = IntProperty(
        name='单格分辨率',
        description='图集每个材质单元格的边长（像素）',
        default=2048,
        min=1,
        max=16384,
    )


def unregister():
    del bpy.types.Scene.ho_texpacker_resolution
    del bpy.types.Scene.ho_texpacker_force_alignment
    del bpy.types.Scene.ho_texpacker_overwrite
    del bpy.types.Scene.ho_texpacker_atlas_name
    del bpy.types.Scene.ho_texpacker_output_dir
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
