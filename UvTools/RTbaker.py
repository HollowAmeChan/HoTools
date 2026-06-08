import bpy
import os
import sys
import numpy as np
from bpy.types import Operator, PropertyGroup, UIList
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

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
}


def poll_mesh_object(self, obj):
    return obj is not None and obj.type == 'MESH'


class PG_UVTools_RTBakeTargetItem(PropertyGroup):
    object: PointerProperty(
        name="物体",
        type=bpy.types.Object,
        poll=poll_mesh_object
    )  # type: ignore


class PG_UVTools_RTBakeTargetGroup(PropertyGroup):
    name: StringProperty(name="名称", default="MeshGroup")  # type: ignore
    objects: CollectionProperty(
        name="物体",
        type=PG_UVTools_RTBakeTargetItem
    )  # type: ignore
    active_object_index: IntProperty(default=0)  # type: ignore


class HO_UL_RTBakeGroupList(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row_name = row.row(align=True)
            row_name.prop(item, "name", text="", emboss=False, icon='OUTLINER_COLLECTION')
            row_label = row.row(align=True)
            row_label.alignment = 'RIGHT'
            row_label.label(text=str(len(item.objects)))
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='OUTLINER_COLLECTION')


class HO_UL_RTBakeGroupObjectList(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.prop(
                item,
                "object",
                text="",
                icon='MESH_DATA' if item.object else 'OBJECT_DATA',
                emboss=False
            )
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='MESH_DATA')


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

    def is_non_color_output(self):
        return self.bake_type in NON_COLOR_BAKE_TYPES

    def use_active_camera_view(self, context):
        return self.bake_type not in BAKE_TYPES_WITHOUT_VIEW_FROM

    def use_group_isolation(self, context, bake_context):
        return True

    def prepare(self, context, operator, bake_context):
        return {'FINISHED'}, None

    def restore(self, context, prepare_state, bake_context):
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
        mode_state = self._switch_to_object_mode(context)
        temp_targets = []
        try:
            scene = context.scene
            scene.cycles.bake_type = self.bake_type
            apply_rt_bake_view_from(context, self)

            bake_contexts = get_bake_target_group_contexts(context)
            if not bake_contexts:
                operator.report({'ERROR'}, "请先在MeshGroup中添加至少一个网格物体")
                return {'CANCELLED'}

            temp_targets = ensure_active_image_targets(context, self)
            try:
                for bake_context in bake_contexts:
                    result = self._execute_group(context, operator, bake_context)
                    if result != {'FINISHED'}:
                        return result
                save_baked_images(temp_targets, context, self, operator)
                return {'FINISHED'}
            finally:
                restore_active_image_targets(temp_targets)
        finally:
            self._restore_mode(context, mode_state)

    def _execute_group(self, context, operator, bake_context):
        selection_state = None
        visibility_state = None
        prepare_state = None
        is_prepared = False
        try:
            selection_state = self._select_bake_target_objects(context, bake_context["objects"])
            visibility_state = self._isolate_bake_group_render_objects(context, bake_context)

            prepare_result, prepare_state = self.prepare(context, operator, bake_context)
            if prepare_result != {'FINISHED'}:
                return prepare_result
            is_prepared = True

            return bpy.ops.object.bake(**get_rt_bake_operator_args(context, self))
        finally:
            if is_prepared:
                self.restore(context, prepare_state, bake_context)
            self._restore_render_visibility(visibility_state)
            self._restore_selection(context, selection_state)

    def _switch_to_object_mode(self, context):
        active_obj = context.view_layer.objects.active
        mode = active_obj.mode if active_obj is not None else 'OBJECT'
        state = {
            "active_object": active_obj,
            "mode": mode,
        }

        if mode == 'OBJECT':
            return state

        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            state["mode"] = 'OBJECT'
        return state

    def _restore_mode(self, context, state):
        if state is None:
            return

        active_obj = state.get("active_object")
        if active_obj is not None and active_obj.name in bpy.data.objects:
            try:
                context.view_layer.objects.active = active_obj
            except (TypeError, RuntimeError):
                pass

        mode = state.get("mode", 'OBJECT')
        if mode == 'OBJECT':
            return

        active_obj = context.view_layer.objects.active
        if active_obj is None or active_obj.name not in bpy.data.objects:
            return

        try:
            bpy.ops.object.mode_set(mode=mode)
        except (TypeError, RuntimeError):
            pass

    def _select_bake_target_objects(self, context, target_objects):
        view_layer = context.view_layer
        state = {
            "active_object": view_layer.objects.active,
            "selected_objects": list(context.selected_objects),
        }

        for obj in list(context.selected_objects):
            try:
                obj.select_set(False)
            except (ReferenceError, RuntimeError):
                pass

        active_obj = None
        for obj in target_objects:
            if obj.name not in bpy.data.objects:
                continue
            try:
                obj.select_set(True)
            except (ReferenceError, RuntimeError):
                continue
            if active_obj is None:
                active_obj = obj

        if active_obj is not None:
            try:
                view_layer.objects.active = active_obj
            except (TypeError, RuntimeError):
                pass

        return state

    def _restore_selection(self, context, state):
        if state is None:
            return

        for obj in list(context.selected_objects):
            try:
                obj.select_set(False)
            except (ReferenceError, RuntimeError):
                pass

        for obj in state.get("selected_objects", []):
            if obj is None or obj.name not in bpy.data.objects:
                continue
            try:
                obj.select_set(True)
            except (ReferenceError, RuntimeError):
                pass

        active_obj = state.get("active_object")
        if active_obj is not None and active_obj.name in bpy.data.objects:
            try:
                context.view_layer.objects.active = active_obj
            except (TypeError, RuntimeError):
                pass

    def _isolate_bake_group_render_objects(self, context, bake_context):
        if not self.use_group_isolation(context, bake_context):
            return []

        enabled_objects = set(bake_context["objects"])
        state = []
        for obj in context.scene.objects:
            if obj.type == 'LIGHT':
                continue
            state.append((obj, obj.hide_render))
            obj.hide_render = obj not in enabled_objects
        return state

    def _restore_render_visibility(self, state):
        if state is None:
            return
        for obj, hide_render in state:
            if obj is None or obj.name not in bpy.data.objects:
                continue
            obj.hide_render = hide_render

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
                    material_index = poly.material_index
                    if material_index < 0 or material_index >= len(obj.material_slots):
                        continue
                    slot = obj.material_slots[material_index]
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

    def prepare(self, context, operator, bake_context):
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        lights = self.get_lights(context, rt_settings.shadowcast_light)
        if not lights:
            operator.report({'ERROR'}, "没有可用于 ShadowCast 的灯光")
            return {'CANCELLED'}, None

        selected_objs = bake_context["objects"]
        if not selected_objs:
            operator.report({'ERROR'}, "当前MeshGroup中没有网格物体")
            return {'CANCELLED'}, None

        light_state = self.isolate_lights(context, lights)
        world_state = self.override_world_with_white_background(context.scene)
        material_state = self.override_objects_with_diffuse_bsdf(selected_objs)
        return {'FINISHED'}, {
            "lights": light_state,
            "world": world_state,
            "materials": material_state,
        }

    def restore(self, context, prepare_state, bake_context):
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

    def find_shader_normal_source(self, node, visited=None):
        if node is None:
            return None
        if visited is None:
            visited = set()
        if node.name in visited:
            return None
        visited.add(node.name)

        normal_input = node.inputs.get("Normal")
        if normal_input is not None and normal_input.is_linked:
            return normal_input.links[0].from_socket

        for input_socket in node.inputs:
            if getattr(input_socket, "type", None) != 'SHADER' or not input_socket.is_linked:
                continue
            for link in input_socket.links:
                normal_source = self.find_shader_normal_source(link.from_node, visited)
                if normal_source is not None:
                    return normal_source
        return None

    def find_output_surface_normal_source(self, surface_input):
        if surface_input is None:
            return None
        for link in surface_input.links:
            normal_source = self.find_shader_normal_source(link.from_node)
            if normal_source is not None:
                return normal_source
        return None

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
            normal_source = self.find_output_surface_normal_source(surface_input)
            for link in list(surface_input.links):
                links.remove(link)

            diffuse = nodes.new(type='ShaderNodeBsdfDiffuse')
            diffuse.name = "HoRTBake_ShadowCast_Diffuse"
            diffuse.label = "HoRTBake ShadowCast Diffuse"
            diffuse.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            diffuse.inputs["Roughness"].default_value = 0.5
            temp_link = links.new(diffuse.outputs["BSDF"], surface_input)
            temp_normal_link = None
            if normal_source is not None:
                normal_input = diffuse.inputs.get("Normal")
                if normal_input is not None:
                    try:
                        temp_normal_link = links.new(normal_source, normal_input)
                    except RuntimeError:
                        temp_normal_link = None

            states.append({
                "material": mat,
                "original_use_nodes": original_use_nodes,
                "created_output": created_output,
                "output": output,
                "diffuse": diffuse,
                "temp_link": temp_link,
                "temp_normal_link": temp_normal_link,
                "original_links": original_links,
                "original_active": original_active,
                "selected_nodes": selected_nodes,
            })

        return states

    def override_normal_source_strength(self, normal_source, links, strength):
        if normal_source is None:
            return None
        node = getattr(normal_source, "node", None)
        if node is None:
            return None
        strength_input = node.inputs.get("Strength")
        if strength_input is None:
            return None

        original_links = [
            (link.from_socket, link.to_socket)
            for link in strength_input.links
        ]
        for link in list(strength_input.links):
            links.remove(link)

        original_default = strength_input.default_value
        strength_input.default_value = strength
        return {
            "input": strength_input,
            "original_default": original_default,
            "original_links": original_links,
        }

    def override_objects_with_ao_emission(
            self,
            objects,
            samples=32,
            distance=4.0,
            normal_strength=1.0,
            use_normal_map=True
    ):
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
            normal_source = self.find_output_surface_normal_source(surface_input) if use_normal_map else None
            normal_strength_state = None
            if use_normal_map:
                normal_strength_state = self.override_normal_source_strength(
                    normal_source,
                    links,
                    normal_strength
                )
            for link in list(surface_input.links):
                links.remove(link)

            ao = nodes.new(type='ShaderNodeAmbientOcclusion')
            ao.name = "HoRTBake_AO_Node"
            ao.label = "HoRTBake AO"
            if hasattr(ao, "samples"):
                ao.samples = max(1, int(samples))
            if hasattr(ao, "inside"):
                ao.inside = False
            if hasattr(ao, "only_local"):
                ao.only_local = False
            color_input = ao.inputs.get("Color")
            if color_input is not None:
                color_input.default_value = (1.0, 1.0, 1.0, 1.0)
            distance_input = ao.inputs.get("Distance")
            if distance_input is not None:
                distance_input.default_value = distance

            emission = nodes.new(type='ShaderNodeEmission')
            emission.name = "HoRTBake_AO_Emission"
            emission.label = "HoRTBake AO Emission"
            emission.inputs["Strength"].default_value = 1.0

            temp_links = []
            ao_output = ao.outputs.get("AO") or ao.outputs.get("Color")
            if ao_output is not None:
                temp_links.append(links.new(ao_output, emission.inputs["Color"]))
            emission_output = emission.outputs.get("Emission") or emission.outputs[0]
            temp_links.append(links.new(emission_output, surface_input))

            if normal_source is not None:
                normal_input = ao.inputs.get("Normal")
                if normal_input is not None:
                    try:
                        temp_links.append(links.new(normal_source, normal_input))
                    except RuntimeError:
                        pass

            states.append({
                "material": mat,
                "original_use_nodes": original_use_nodes,
                "created_output": created_output,
                "output": output,
                "temp_nodes": [ao, emission],
                "temp_links": temp_links,
                "normal_strength": normal_strength_state,
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
            temp_links = state.get("temp_links")
            if temp_links is None:
                temp_links = [state.get("temp_link"), state.get("temp_normal_link")]
            for temp_link in temp_links:
                if temp_link is None:
                    continue
                try:
                    links.remove(temp_link)
                except (ReferenceError, RuntimeError):
                    pass

            temp_nodes = state.get("temp_nodes")
            if temp_nodes is None:
                temp_nodes = [state.get("diffuse")]
            for temp_node in temp_nodes:
                if temp_node is not None and temp_node.name in nodes:
                    nodes.remove(temp_node)

            normal_strength_state = state.get("normal_strength")
            if normal_strength_state is not None:
                strength_input = normal_strength_state["input"]
                strength_input.default_value = normal_strength_state["original_default"]
                for from_socket, to_socket in normal_strength_state["original_links"]:
                    try:
                        links.new(from_socket, to_socket)
                    except RuntimeError:
                        pass

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


class RTAOChannel(RTShadowCastChannel):
    def __init__(self):
        RTBakeChannel.__init__(
            self,
            "ao",
            "环境光遮蔽 (AO)",
            'COMBINED',
            "AO",
            pass_filter={'DIRECT', 'INDIRECT', 'DIFFUSE', 'GLOSSY', 'TRANSMISSION', 'EMIT'}
        )

    def draw_settings(self, layout:bpy.types.UILayout, context):
        RTBakeChannel.draw_settings(self, layout, context)
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(rt_settings, "ao_search_normal_map")
        strength_col = col.column(align=True)
        strength_col.enabled = rt_settings.ao_search_normal_map
        strength_col.prop(rt_settings, "ao_normal_strength")

    def is_non_color_output(self):
        return True

    def use_active_camera_view(self, context):
        return False

    def prepare(self, context, operator, bake_context):
        selected_objs = bake_context["objects"]
        if not selected_objs:
            operator.report({'ERROR'}, "当前MeshGroup中没有网格物体")
            return {'CANCELLED'}, None

        world_state = self.override_world_with_white_background(context.scene)
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        material_state = self.override_objects_with_ao_emission(
            selected_objs,
            normal_strength=rt_settings.ao_normal_strength,
            use_normal_map=rt_settings.ao_search_normal_map
        )
        return {'FINISHED'}, {
            "world": world_state,
            "materials": material_state,
        }

    def restore(self, context, prepare_state, bake_context):
        if prepare_state is None:
            return
        self.restore_material_overrides(prepare_state.get("materials", []))
        self.restore_world(prepare_state.get("world"))

RT_BAKE_CHANNELS = [
    RTDirectChannel(),
    RTAOChannel(),
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
    target_groups: CollectionProperty(
        name="MeshGroup",
        type=PG_UVTools_RTBakeTargetGroup
    )  # type: ignore
    target_group_index: IntProperty(default=0)  # type: ignore

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
    ao_search_normal_map: BoolProperty(name="搜寻法线贴图", default=True)  # type: ignore
    ao_normal_strength: FloatProperty(
        name="法线强度",
        default=1.0,
        min=0.0,
        precision=3
    )  # type: ignore
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


TARGET_MOVE_ITEMS = [
    ('UP', "上移", ""),
    ('DOWN', "下移", ""),
]


def make_unique_target_group_name(target_groups):
    base_name = "MeshGroup"
    names = {group.name for group in target_groups}
    if base_name not in names:
        return base_name

    index = 1
    while True:
        name = f"{base_name}.{index:03d}"
        if name not in names:
            return name
        index += 1


def clamp_target_group_index(rt_settings):
    if len(rt_settings.target_groups) == 0:
        rt_settings.target_group_index = 0
        return None

    rt_settings.target_group_index = min(
        max(0, rt_settings.target_group_index),
        len(rt_settings.target_groups) - 1
    )
    return rt_settings.target_groups[rt_settings.target_group_index]


def get_or_create_active_target_group(rt_settings):
    group = clamp_target_group_index(rt_settings)
    if group is not None:
        return group

    group_name = make_unique_target_group_name(rt_settings.target_groups)
    group = rt_settings.target_groups.add()
    group.name = group_name
    rt_settings.target_group_index = len(rt_settings.target_groups) - 1
    return group


class OT_UVTools_RTBakeGroupAdd(Operator):
    """添加MeshGroup"""
    bl_idname = "ho.uvtools_rt_bake_group_add"
    bl_label = "添加MeshGroup"
    bl_description = "添加一个MeshGroup"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        group_name = make_unique_target_group_name(rt_settings.target_groups)
        group = rt_settings.target_groups.add()
        group.name = group_name
        rt_settings.target_group_index = len(rt_settings.target_groups) - 1
        return {'FINISHED'}


class OT_UVTools_RTBakeGroupRemove(Operator):
    """删除活动MeshGroup"""
    bl_idname = "ho.uvtools_rt_bake_group_remove"
    bl_label = "删除MeshGroup"
    bl_description = "删除活动MeshGroup"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        index = rt_settings.target_group_index
        if 0 <= index < len(rt_settings.target_groups):
            rt_settings.target_groups.remove(index)
            rt_settings.target_group_index = min(index, len(rt_settings.target_groups) - 1)
            rt_settings.target_group_index = max(0, rt_settings.target_group_index)
        return {'FINISHED'}


class OT_UVTools_RTBakeGroupMove(Operator):
    """移动活动MeshGroup"""
    bl_idname = "ho.uvtools_rt_bake_group_move"
    bl_label = "移动MeshGroup"
    bl_description = "移动活动MeshGroup"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=TARGET_MOVE_ITEMS, default='UP')  # type: ignore

    def execute(self, context):
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        index = rt_settings.target_group_index
        target_index = index - 1 if self.direction == 'UP' else index + 1
        if 0 <= index < len(rt_settings.target_groups) and 0 <= target_index < len(rt_settings.target_groups):
            rt_settings.target_groups.move(index, target_index)
            rt_settings.target_group_index = target_index
        return {'FINISHED'}


class OT_UVTools_RTBakeTargetAddSelected(Operator):
    """添加当前选中的网格物体"""
    bl_idname = "ho.uvtools_rt_bake_target_add_selected"
    bl_label = "添加选中物体"
    bl_description = "添加当前选中的网格物体到活动MeshGroup"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        group = get_or_create_active_target_group(rt_settings)
        existing = {
            item.object.name
            for item in group.objects
            if item.object is not None
        }

        added = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH' or obj.name in existing:
                continue
            item = group.objects.add()
            item.object = obj
            existing.add(obj.name)
            group.active_object_index = len(group.objects) - 1
            added += 1

        if added == 0:
            self.report({'INFO'}, "没有可添加的选中网格物体")
        return {'FINISHED'}


class OT_UVTools_RTBakeTargetRemove(Operator):
    """删除活动目标物体"""
    bl_idname = "ho.uvtools_rt_bake_target_remove"
    bl_label = "删除目标物体"
    bl_description = "删除活动MeshGroup中的活动目标物体"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        group = clamp_target_group_index(rt_settings)
        if group is None:
            return {'FINISHED'}

        index = group.active_object_index
        if 0 <= index < len(group.objects):
            group.objects.remove(index)
            group.active_object_index = min(index, len(group.objects) - 1)
            group.active_object_index = max(0, group.active_object_index)
        return {'FINISHED'}


class OT_UVTools_RTBakeTargetMove(Operator):
    """移动活动目标物体"""
    bl_idname = "ho.uvtools_rt_bake_target_move"
    bl_label = "移动目标物体"
    bl_description = "移动活动MeshGroup中的活动目标物体"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=TARGET_MOVE_ITEMS, default='UP')  # type: ignore

    def execute(self, context):
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        group = clamp_target_group_index(rt_settings)
        if group is None:
            return {'FINISHED'}

        index = group.active_object_index
        target_index = index - 1 if self.direction == 'UP' else index + 1
        if 0 <= index < len(group.objects) and 0 <= target_index < len(group.objects):
            group.objects.move(index, target_index)
            group.active_object_index = target_index
        return {'FINISHED'}


class OT_UVTools_RTBakeTargetClear(Operator):
    """清空MeshGroup"""
    bl_idname = "ho.uvtools_rt_bake_target_clear"
    bl_label = "清空MeshGroup"
    bl_description = "清空所有MeshGroup"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        rt_settings.target_groups.clear()
        rt_settings.target_group_index = 0
        return {'FINISHED'}


class OT_UVTools_RTBakeTargetClearGroup(Operator):
    """清空活动MeshGroup中的物体"""
    bl_idname = "ho.uvtools_rt_bake_target_clear_group"
    bl_label = "清空组内物体"
    bl_description = "清空活动MeshGroup中的所有物体"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rt_settings = context.scene.ho_uvtools_rt_bake_settings
        group = clamp_target_group_index(rt_settings)
        if group is not None:
            group.objects.clear()
            group.active_object_index = 0
        return {'FINISHED'}


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
        target_objects = get_bake_target_objects(context)

        filepath = bpy.path.abspath(bake_settings.filepath)
        if not filepath:
            self.report({'ERROR'}, "请先设置外部输出路径")
            return {'CANCELLED'}

        if not target_objects:
            self.report({'ERROR'}, "请先在MeshGroup中添加至少一个网格物体")
            return {'CANCELLED'}

        if not bake_channels:
            self.report({'ERROR'}, "请至少启用一个烘焙通道")
            return {'CANCELLED'}

        original_bake_type = scene.cycles.bake_type
        original_cycles_sampling = capture_rt_cycles_sampling(scene)
        original_view_from = bake_settings.view_from

        try:
            apply_rt_bake_defaults(context)
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


def apply_rt_bake_view_from(context, bake_target):
    scene = context.scene
    bake_settings = scene.render.bake
    if hasattr(bake_target, "bake_type"):
        channel = bake_target
        if not channel.use_active_camera_view(context):
            bake_settings.view_from = 'ABOVE_SURFACE'
            return
        bake_type = channel.bake_type
    else:
        bake_type = bake_target

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
    objects = []
    seen = set()
    for bake_context in get_bake_target_group_contexts(context):
        for obj in bake_context["objects"]:
            if obj.name in seen:
                continue
            objects.append(obj)
            seen.add(obj.name)
    return objects


def get_bake_target_group_contexts(context):
    scene = context.scene
    rt_settings = getattr(scene, "ho_uvtools_rt_bake_settings", None)
    if rt_settings is None:
        return []

    all_objects = []
    global_seen = set()
    contexts = []
    for group_index, group in enumerate(rt_settings.target_groups):
        group_objects = []
        group_seen = set()
        for item in group.objects:
            obj = item.object
            if obj is None or obj.type != 'MESH':
                continue
            if obj.name in group_seen or obj.name in global_seen:
                continue
            group_objects.append(obj)
            group_seen.add(obj.name)
            global_seen.add(obj.name)
            all_objects.append(obj)

        if not group_objects:
            continue

        contexts.append({
            "group": group,
            "group_index": group_index,
            "group_name": group.name,
            "objects": group_objects,
        })

    for bake_context in contexts:
        bake_context["all_objects"] = all_objects

    return contexts


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


def set_image_color_space(image, channel):
    if not channel.is_non_color_output():
        return
    try:
        image.colorspace_settings.name = 'Non-Color'
    except TypeError:
        pass


def ensure_active_image_targets(context, channel):
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
                    set_image_color_space(image, channel)
                    image_by_material[image_key] = image
            else:
                if shared_image is None:
                    shared_image = bpy.data.images.new(
                        "HoRTBake_Merged",
                        bake_settings.width,
                        bake_settings.height,
                        alpha=True
                    )
                    set_image_color_space(shared_image, channel)
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


def draw_rt_bake_targets(layout: bpy.types.UILayout, context):
    scene = context.scene
    rt_settings = scene.ho_uvtools_rt_bake_settings

    box = layout.box()
    active_group = None
    if len(rt_settings.target_groups) > 0:
        group_index = min(max(0, rt_settings.target_group_index), len(rt_settings.target_groups) - 1)
        active_group = rt_settings.target_groups[group_index]

    target_rows = 4
    split = box.split(factor=0.5, align=True)

    group_root = split.column()
    group_row = group_root.row(align=True)
    group_col = group_row.column()
    group_col.template_list(
        HO_UL_RTBakeGroupList.__name__,
        "",
        rt_settings,
        "target_groups",
        rt_settings,
        "target_group_index",
        rows=target_rows
    )

    group_buttons = group_row.column(align=True)
    group_buttons.operator(OT_UVTools_RTBakeGroupAdd.bl_idname, text="", icon="ADD")
    group_buttons.operator(OT_UVTools_RTBakeGroupRemove.bl_idname, text="", icon="REMOVE")
    group_buttons.separator()
    group_up = group_buttons.operator(OT_UVTools_RTBakeGroupMove.bl_idname, text="", icon="TRIA_UP")
    group_up.direction = 'UP'
    group_down = group_buttons.operator(OT_UVTools_RTBakeGroupMove.bl_idname, text="", icon="TRIA_DOWN")
    group_down.direction = 'DOWN'
    group_buttons.separator()
    group_buttons.operator(OT_UVTools_RTBakeTargetClear.bl_idname, text="", icon="X")

    object_root = split.column()
    object_row = object_root.row(align=True)
    object_col = object_row.column()
    if active_group is None:
        object_col.label(text="没有MeshGroup", icon="INFO")
    else:
        object_col.template_list(
            HO_UL_RTBakeGroupObjectList.__name__,
            "",
            active_group,
            "objects",
            active_group,
            "active_object_index",
            rows=target_rows
        )

    object_buttons = object_row.column(align=True)
    object_buttons.operator(OT_UVTools_RTBakeTargetAddSelected.bl_idname, text="", icon="RESTRICT_SELECT_OFF")
    object_buttons.operator(OT_UVTools_RTBakeTargetRemove.bl_idname, text="", icon="REMOVE")
    object_buttons.separator()
    move_up = object_buttons.operator(OT_UVTools_RTBakeTargetMove.bl_idname, text="", icon="TRIA_UP")
    move_up.direction = 'UP'
    move_down = object_buttons.operator(OT_UVTools_RTBakeTargetMove.bl_idname, text="", icon="TRIA_DOWN")
    move_down.direction = 'DOWN'
    object_buttons.separator()
    object_buttons.operator(OT_UVTools_RTBakeTargetClearGroup.bl_idname, text="", icon="X")


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

    draw_rt_bake_targets(root, context)
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
    PG_UVTools_RTBakeTargetItem,
    PG_UVTools_RTBakeTargetGroup,
    PG_UVTools_RTBakeSettings,
    HO_UL_RTBakeGroupList,
    HO_UL_RTBakeGroupObjectList,
    OT_UVTools_RTBakeGroupAdd,
    OT_UVTools_RTBakeGroupRemove,
    OT_UVTools_RTBakeGroupMove,
    OT_UVTools_RTBakeTargetAddSelected,
    OT_UVTools_RTBakeTargetRemove,
    OT_UVTools_RTBakeTargetMove,
    OT_UVTools_RTBakeTargetClear,
    OT_UVTools_RTBakeTargetClearGroup,
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
