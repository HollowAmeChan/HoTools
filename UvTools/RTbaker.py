import bpy
import os
import sys
import numpy as np
from bpy.types import Operator, PropertyGroup
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

if sys.version_info >= (3, 13):
    from .._Lib.py313.PIL import Image, ImageDraw
    try:
        from .._Lib.py313 import pyoidn
    except ImportError:
        pyoidn = None
elif sys.version_info >= (3, 11):
    from .._Lib.py311.PIL import Image, ImageDraw
    try:
        from .._Lib.py311 import pyoidn
    except ImportError:
        pyoidn = None
else:
    pyoidn = None


BAKE_TYPES_WITHOUT_VIEW_FROM = {
    'AO',
    'ENVIRONMENT',
}


class RTBakeChannel:
    # 子类主要覆盖下面这一组 hook；其余 `_` 方法是基类内部流程工具。
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

    # Overridable hooks

    def get_suffix(self, rt_settings):
        suffix = getattr(rt_settings, self.suffix_prop).strip()
        return suffix if suffix else self.suffix

    def draw_settings(self, layout, context):
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(rt_settings, self.suffix_prop, text="后缀")

    def get_bake_margin(self, context):
        return context.scene.render.bake.margin

    def prepare(self, context, operator):
        return {'FINISHED'}, None

    def restore(self, context, prepare_state):
        return

    def build_oidn_padding_context(self, context, image_name):
        bake_settings = context.scene.render.bake
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        return {
            "objects": get_bake_target_objects(context),
            "cycles_margin": self.get_bake_margin(context),
            "output_margin": bake_settings.margin,
            "material_name": image_name if bake_settings.use_split_materials else None,
            "debug_output": rt_settings.debug_output,
            "use_oidn_denoise": rt_settings.use_oidn_denoise,
            "oidn_quality": rt_settings.oidn_quality,
            "oidn_hdr": rt_settings.oidn_hdr,
        }

    def postprocess_saved_image(self, filepath, image_name, context, operator):
        return self._postprocess_oidn_denoise(filepath, image_name, context, operator)

    # Execution template

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
                    save_baked_images(temp_targets, context, self, operator)
                return result
            finally:
                restore_active_image_targets(temp_targets)
        finally:
            self.restore(context, prepare_state)

    # Internal postprocess helpers

    def _postprocess_oidn_denoise(self, filepath, image_name, context, operator):
        uv_padding_context = self.build_oidn_padding_context(context, image_name)
        if uv_padding_context["debug_output"]:
            self._save_debug_image(filepath, "BLRaw", filepath)
        oidn_input = self._expand_image_for_oidn(filepath, uv_padding_context)
        if uv_padding_context["debug_output"]:
            self._save_debug_image(filepath, "InfinitePadding", oidn_input["array"])
        if uv_padding_context["use_oidn_denoise"]:
            denoised = self._denoise_image_with_oidn(oidn_input, uv_padding_context, operator)
        else:
            denoised = oidn_input
        return self._crop_image_to_user_margin(denoised, filepath, uv_padding_context)

    def _get_debug_output_path(self, filepath, tag):
        stem, ext = os.path.splitext(filepath)
        if not ext:
            ext = ".png"
        return f"{stem}_{tag}{ext}"

    def _save_debug_image(self, source_filepath, tag, image_data):
        debug_path = self._get_debug_output_path(source_filepath, tag)
        if isinstance(image_data, str):
            Image.open(image_data).convert("RGBA").save(debug_path)
        else:
            self._save_array_image(debug_path, image_data)
        return debug_path

    def _expand_image_for_oidn(self, filepath, uv_padding_context):
        image = Image.open(filepath).convert("RGBA")
        arr = np.array(image, dtype=np.uint8)
        surface_mask = self._build_uv_mask(
            uv_padding_context["objects"],
            arr.shape[1],
            arr.shape[0],
            material_name=uv_padding_context.get("material_name"),
            margin=0,
        )
        seed_mask = self._build_uv_edge_seed_mask(
            surface_mask,
            uv_padding_context["cycles_margin"],
        )
        expanded = self._expand_image_to_mask(arr, seed_mask)
        expanded[surface_mask] = arr[surface_mask]
        return {
            "array": expanded,
            "mask": surface_mask,
            "seed_mask": seed_mask,
        }

    def _denoise_image_with_oidn(self, oidn_input, uv_padding_context, operator):
        if not is_oidn_available():
            operator.report({'WARNING'}, "未找到 pyoidn，已跳过 OIDN 降噪")
            return oidn_input

        input_arr = oidn_input["array"]
        color = np.ascontiguousarray(input_arr[:, :, :3].astype(np.float32) / 255.0)
        output = np.zeros_like(color, dtype=np.float32)

        with pyoidn.Device() as device:
            device.commit()
            with pyoidn.Filter(device, getattr(pyoidn, "OIDN_FILTER_TYPE_RT", "RT")) as flt:
                flt.set_bool("hdr", uv_padding_context["oidn_hdr"])
                flt.set_image(pyoidn.OIDN_IMAGE_COLOR, color, pyoidn.OIDN_FORMAT_FLOAT3)
                flt.set_image(pyoidn.OIDN_IMAGE_OUTPUT, output, pyoidn.OIDN_FORMAT_FLOAT3)
                quality = get_oidn_quality(uv_padding_context["oidn_quality"])
                if quality is not None:
                    flt.set_quality(quality)
                flt.commit()
                flt.execute()

            error = device.get_error()
            if error is not None:
                operator.report({'WARNING'}, f"OIDN降噪失败: {error}")
                return oidn_input

        denoised = input_arr.copy()
        denoised[:, :, :3] = np.clip(output * 255.0 + 0.5, 0, 255).astype(np.uint8)
        return {
            "array": denoised,
            "mask": oidn_input["mask"],
            "seed_mask": oidn_input.get("seed_mask"),
        }

    def _crop_image_to_user_margin(self, denoised, output_path, uv_padding_context):
        denoised_arr = denoised["array"]
        width = denoised_arr.shape[1]
        height = denoised_arr.shape[0]
        output_mask = self._build_uv_mask(
            uv_padding_context["objects"],
            width,
            height,
            material_name=uv_padding_context.get("material_name"),
            margin=uv_padding_context["output_margin"],
        )
        output_arr = np.zeros_like(denoised_arr)
        output_arr[output_mask] = denoised_arr[output_mask]
        output_arr[output_mask, 3] = 255
        self._save_array_image(output_path, output_arr)
        return output_path

    def _save_array_image(self, filepath, arr):
        image = Image.fromarray(arr)
        ext = os.path.splitext(filepath)[1].lower()
        if ext in {".jpg", ".jpeg", ".bmp"}:
            image = image.convert("RGB")
        image.save(filepath)

    # Internal UV padding helpers

    def _build_uv_mask(self, objects, width, height, material_name=None, margin=0):
        mask_img = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask_img)

        for obj in objects:
            mesh = obj.data
            uv_layer = mesh.uv_layers.active
            if uv_layer is None:
                continue

            for poly in mesh.polygons:
                if material_name is not None:
                    slot = obj.material_slots[poly.material_index]
                    mat = slot.material
                    if mat is None or mat.name != material_name:
                        continue

                pts = []
                for loop_index in poly.loop_indices:
                    uv = uv_layer.data[loop_index].uv
                    x = int(round(uv.x * (width - 1)))
                    y = int(round((1.0 - uv.y) * (height - 1)))
                    pts.append((max(0, min(width - 1, x)), max(0, min(height - 1, y))))

                if len(pts) < 3:
                    continue
                for i in range(1, len(pts) - 1):
                    draw.polygon([pts[0], pts[i], pts[i + 1]], fill=255)

        mask = np.array(mask_img, dtype=np.uint8) > 0
        if margin > 0:
            mask = self._dilate_mask(mask, margin)
        return mask

    def _dilate_mask(self, mask, radius):
        if radius <= 0 or not mask.any():
            return mask

        result = mask.copy()
        for _ in range(radius):
            padded = np.pad(result, 1, mode="constant", constant_values=False)
            result = (
                padded[0:-2, 0:-2] | padded[0:-2, 1:-1] | padded[0:-2, 2:] |
                padded[1:-1, 0:-2] | padded[1:-1, 1:-1] | padded[1:-1, 2:] |
                padded[2:, 0:-2] | padded[2:, 1:-1] | padded[2:, 2:]
            )
        return result

    def _build_uv_edge_seed_mask(self, surface_mask, radius):
        if not surface_mask.any():
            return surface_mask

        boundary_radius = max(1, radius)
        outside_reach = self._dilate_mask(~surface_mask, boundary_radius)
        seed_mask = surface_mask & outside_reach
        if seed_mask.any():
            return seed_mask
        return surface_mask

    def _expand_image_to_mask(self, arr, seed_mask):
        valid = seed_mask
        if not valid.any():
            return arr

        height, width = valid.shape
        yy, xx = np.indices((height, width), dtype=np.int32)
        nearest_x = np.where(valid, xx, -1)
        nearest_y = np.where(valid, yy, -1)
        distance = np.where(valid, 0, width * width + height * height).astype(np.int64)

        step = 1
        max_dim = max(width, height)
        while step < max_dim:
            for dy, dx in (
                (-step, -step), (-step, 0), (-step, step),
                (0, -step),                 (0, step),
                (step, -step),  (step, 0),  (step, step),
            ):
                self._relax_nearest_seed(nearest_x, nearest_y, distance, xx, yy, dx, dy)
            step *= 2

        step //= 2
        while step >= 1:
            for dy, dx in (
                (-step, -step), (-step, 0), (-step, step),
                (0, -step),                 (0, step),
                (step, -step),  (step, 0),  (step, step),
            ):
                self._relax_nearest_seed(nearest_x, nearest_y, distance, xx, yy, dx, dy)
            step //= 2

        expanded = arr.copy()
        has_seed = nearest_x >= 0
        expanded[has_seed] = arr[nearest_y[has_seed], nearest_x[has_seed]]
        expanded[:, :, 3] = 255
        return expanded

    def _relax_nearest_seed(self, nearest_x, nearest_y, distance, xx, yy, dx, dy):
        height, width = nearest_x.shape
        src_y0 = max(0, -dy)
        src_y1 = min(height, height - dy)
        src_x0 = max(0, -dx)
        src_x1 = min(width, width - dx)
        if src_y0 >= src_y1 or src_x0 >= src_x1:
            return

        dst_y0 = src_y0 + dy
        dst_y1 = src_y1 + dy
        dst_x0 = src_x0 + dx
        dst_x1 = src_x1 + dx

        cand_x = nearest_x[src_y0:src_y1, src_x0:src_x1]
        cand_y = nearest_y[src_y0:src_y1, src_x0:src_x1]
        valid = cand_x >= 0
        if not valid.any():
            return

        target_x = xx[dst_y0:dst_y1, dst_x0:dst_x1]
        target_y = yy[dst_y0:dst_y1, dst_x0:dst_x1]
        cand_dist = (cand_x - target_x) ** 2 + (cand_y - target_y) ** 2
        target_dist = distance[dst_y0:dst_y1, dst_x0:dst_x1]
        update = valid & (cand_dist < target_dist)
        if not update.any():
            return

        target_nearest_x = nearest_x[dst_y0:dst_y1, dst_x0:dst_x1]
        target_nearest_y = nearest_y[dst_y0:dst_y1, dst_x0:dst_x1]
        target_nearest_x[update] = cand_x[update]
        target_nearest_y[update] = cand_y[update]
        target_dist[update] = cand_dist[update]


class RTShadowCastChannel(RTBakeChannel):
    """
    ShadowCast 走 Cycles bake，临时把选中物体材质改成白色 Diffuse、
    世界改成纯白，并用可选灯光隔离得到可控直射阴影结果。
    它使用隐藏小 margin 给 Blender 烘焙，后续统一走基类的 UV 无限
    padding + OIDN + UI 边距裁回流程；结束后恢复灯光、世界和材质状态。
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

    def get_bake_margin(self, context):
        resolution = context.scene.ho_uvtools_rt_bake_settings.resolution
        return max(1, int(round(resolution / SHADOWCAST_BLENDER_MARGIN_DIVISOR)))

    def build_oidn_padding_context(self, context, image_name):
        bake_settings = context.scene.render.bake
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        return {
            "objects": get_bake_target_objects(context),
            "resolution": rt_settings.resolution,
            "cycles_margin": self.get_bake_margin(context),
            "output_margin": bake_settings.margin,
            "material_name": image_name if bake_settings.use_split_materials else None,
            "debug_output": rt_settings.debug_output,
            "use_oidn_denoise": rt_settings.use_oidn_denoise,
            "oidn_quality": rt_settings.oidn_quality,
            "oidn_hdr": rt_settings.oidn_hdr,
        }

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

OIDN_QUALITY_ITEMS = [
    ('FAST', "快速", "更快，细节稳定性较低"),
    ('BALANCED', "均衡", "速度和质量折中"),
    ('HIGH', "高质量", "质量最高，速度较慢"),
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

SHADOWCAST_BLENDER_MARGIN_DIVISOR = 512


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


def get_oidn_quality(quality):
    if not is_oidn_available():
        return None
    return {
        'FAST': getattr(pyoidn, "OIDN_QUALITY_FAST", None),
        'BALANCED': getattr(pyoidn, "OIDN_QUALITY_BALANCED", None),
        'HIGH': getattr(pyoidn, "OIDN_QUALITY_HIGH", None),
    }.get(quality)


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
    debug_output: BoolProperty(name="输出调试贴图", default=False)  # type: ignore
    use_oidn_denoise: BoolProperty(name="OIDN降噪", default=True)  # type: ignore
    oidn_quality: EnumProperty(
        name="OIDN质量",
        items=OIDN_QUALITY_ITEMS,
        default='HIGH'
    )  # type: ignore
    oidn_hdr: BoolProperty(name="HDR", default=False)  # type: ignore

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
        "margin": channel.get_bake_margin(context),
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


def get_oidn_module():
    return pyoidn


def is_oidn_available():
    return get_oidn_module() is not None


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


def save_baked_images(targets, context, channel, operator):
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
        channel.postprocess_saved_image(filepath, image_name, context, operator)


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
    col.prop(rt_settings, "debug_output")

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

    oidn_col = box.column(align=True)
    oidn_col.prop(rt_settings, "use_oidn_denoise")
    oidn_settings_col = oidn_col.column(align=True)
    oidn_settings_col.enabled = rt_settings.use_oidn_denoise
    oidn_settings_col.prop(rt_settings, "oidn_quality")
    oidn_settings_col.prop(rt_settings, "oidn_hdr")


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
