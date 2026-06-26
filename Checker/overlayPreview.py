from array import array
from pathlib import Path

import bpy
import gpu
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy.types import Operator, Panel
from gpu_extras.batch import batch_for_shader

try:
    from .._Lib.py311.PIL import Image as PILImage
except Exception:
    try:
        from .._Lib.py313.PIL import Image as PILImage
    except Exception:
        from PIL import Image as PILImage


_ASSET_ROOT = Path(__file__).resolve().with_name("assets")
_DEPTH_BIAS = 1.0e-5

_DEFAULT_CHECK_MODE = "UV_GRID"
_DEFAULT_GRID_RESOLUTION = "PX_1024"
_DEFAULT_VISUAL_MODE = "COLOR_GRID"
_DEFAULT_ALPHA = 0.72
_DEFAULT_FILL_A = (0.16, 0.16, 0.16, 1.0)
_DEFAULT_FILL_B = (0.90, 0.90, 0.90, 1.0)

_GRID_RESOLUTION_VALUES = {
    "PX_512": 512,
    "PX_1024": 1024,
    "PX_2048": 2048,
    "PX_4096": 4096,
    "PX_8192": 8192,
}

_GRID_RESOLUTION_ITEMS = tuple(
    (resolution_id, str(resolution), f"{resolution} 像素")
    for resolution_id, resolution in _GRID_RESOLUTION_VALUES.items()
)

_VISUAL_MODE_ITEMS = (
    ("UV_GRID", "UV Grid", "外部 UV Grid 图片"),
    ("COLOR_GRID", "Color Grid", "外部 Color Grid 图片"),
    ("CHECKER", "Checker", "外部 Checker 图片"),
    ("CUSTOM_IMAGE", "Custom Image", "用户指定外部图片"),
)


class CheckerOverlayPreview:
    # Shared runtime state for all overlay modes.
    DRAW_HANDLE = None
    CHECKER_SHADER = None
    IMAGE_SHADER = None
    OVERLAY_BATCH_CACHE = None
    OVERLAY_CACHE_DIRTY = True
    OVERLAY_TEXTURE_CACHE = {}
    MODE_SPECS = {}

    @staticmethod
    def register_mode(mode_id, label, description="", *, refresh=None, draw=None, draw_panel=None):
        CheckerOverlayPreview.MODE_SPECS[mode_id] = {
            "label": label,
            "description": description,
            "refresh": refresh,
            "draw": draw,
            "draw_panel": draw_panel,
        }

    @staticmethod
    def mode_items(_self=None, _context=None):
        if CheckerOverlayPreview.MODE_SPECS:
            return tuple(
                (mode_id, spec["label"], spec["description"])
                for mode_id, spec in CheckerOverlayPreview.MODE_SPECS.items()
            )
        return (("UV_GRID", "UV 栅格检查", "绘制所有可见 Mesh 的 UV 栅格预览"),)

    @staticmethod
    def default_mode_id():
        if _DEFAULT_CHECK_MODE in CheckerOverlayPreview.MODE_SPECS:
            return _DEFAULT_CHECK_MODE
        return next(iter(CheckerOverlayPreview.MODE_SPECS), _DEFAULT_CHECK_MODE)

    @staticmethod
    def get_scene(context):
        if context is not None:
            scene = getattr(context, "scene", None)
            if scene is not None:
                return scene
        return getattr(bpy.context, "scene", None)

    @staticmethod
    def tag_view3d_redraw():
        wm = getattr(bpy.context, "window_manager", None)
        if wm is None:
            return

        for window in wm.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

    @staticmethod
    def overlay_show_enabled(context=None):
        scene = CheckerOverlayPreview.get_scene(context)
        return bool(scene and getattr(scene, "ho_checker_overlay_show", False))

    @staticmethod
    def current_mode_id(scene):
        mode_id = getattr(
            scene,
            "ho_checker_overlay_check_mode",
            CheckerOverlayPreview.default_mode_id(),
        )
        if mode_id not in CheckerOverlayPreview.MODE_SPECS:
            return CheckerOverlayPreview.default_mode_id()
        return mode_id

    @staticmethod
    def current_mode_spec(scene):
        return CheckerOverlayPreview.MODE_SPECS.get(CheckerOverlayPreview.current_mode_id(scene))

    @staticmethod
    def current_mode_label(scene):
        spec = CheckerOverlayPreview.current_mode_spec(scene)
        if spec is not None:
            return spec["label"]
        return "UV 栅格检查"

    @staticmethod
    def current_mode_refresh(scene):
        spec = CheckerOverlayPreview.current_mode_spec(scene)
        refresh_fn = spec.get("refresh") if spec is not None else None
        return refresh_fn or CheckerOverlayPreview.rebuild_overlay_cache

    @staticmethod
    def current_mode_draw(scene):
        spec = CheckerOverlayPreview.current_mode_spec(scene)
        draw_fn = spec.get("draw") if spec is not None else None
        return draw_fn or CheckerOverlayPreview.draw_overlay_batch

    @staticmethod
    def current_mode_panel(scene):
        spec = CheckerOverlayPreview.current_mode_spec(scene)
        panel_fn = spec.get("draw_panel") if spec is not None else None
        return panel_fn or CheckerOverlayPreview.draw_uv_grid_panel

    @staticmethod
    def clear_overlay_cache():
        CheckerOverlayPreview.OVERLAY_BATCH_CACHE = None
        CheckerOverlayPreview.OVERLAY_CACHE_DIRTY = True

    @staticmethod
    def set_overlay_cache_clean():
        CheckerOverlayPreview.OVERLAY_CACHE_DIRTY = False

    @staticmethod
    def free_texture(texture):
        if texture is None:
            return

        free_fn = getattr(texture, "free", None)
        if callable(free_fn):
            try:
                free_fn()
            except Exception:
                pass

    @staticmethod
    def free_image(image):
        if image is None:
            return

        try:
            if image.name in bpy.data.images:
                bpy.data.images.remove(image)
        except Exception:
            pass

    @staticmethod
    def clear_texture_cache():
        for entry in CheckerOverlayPreview.OVERLAY_TEXTURE_CACHE.values():
            texture = entry.get("texture") if isinstance(entry, dict) else None
            image = entry.get("image") if isinstance(entry, dict) else None
            CheckerOverlayPreview.free_texture(texture)
            CheckerOverlayPreview.free_image(image)
        CheckerOverlayPreview.OVERLAY_TEXTURE_CACHE.clear()

    @staticmethod
    def texture_buffer_from_pixels(width, height, pixels):
        dimensions_options = (
            width * height * 4,
            (width * height * 4,),
            (height, width, 4),
        )
        for dimensions in dimensions_options:
            try:
                return gpu.types.Buffer("UBYTE", dimensions, pixels)
            except Exception:
                pass
        return None

    @staticmethod
    def texture_from_pil_image(path):
        with PILImage.open(str(path)) as src:
            rgba = src.convert("RGBA")
            width, height = rgba.size
            pixels = array("B", rgba.tobytes())
            buffer = CheckerOverlayPreview.texture_buffer_from_pixels(width, height, pixels)
            if buffer is None:
                return None, None
            return gpu.types.GPUTexture((width, height), format="RGBA8", data=buffer), None

    @staticmethod
    def texture_from_blender_image(path):
        image = None
        try:
            image = bpy.data.images.load(filepath=str(path), check_existing=False)
            image.name = f"__HoToolsCheckerOverlay_{path.stem}"
            image.use_fake_user = False
            texture = gpu.texture.from_image(image)
            return texture, image
        except Exception:
            CheckerOverlayPreview.free_image(image)
            return None, None

    @staticmethod
    def overlay_grid_resolution(scene):
        resolution_id = getattr(
            scene,
            "ho_checker_overlay_uv_grid_resolution",
            _DEFAULT_GRID_RESOLUTION,
        )
        resolution = _GRID_RESOLUTION_VALUES.get(resolution_id)
        if resolution is not None:
            return resolution

        legacy_value = getattr(scene, "ho_checker_overlay_uv_grid_scale", 1024.0)
        try:
            return max(int(float(legacy_value)), 1)
        except (TypeError, ValueError):
            return 1024

    @staticmethod
    def asset_file_for_mode(mode, resolution):
        folder = {
            "UV_GRID": "uv_grid",
            "COLOR_GRID": "color_grid",
            "CHECKER": "checker",
        }.get(mode, "color_grid")
        candidates = [resolution]
        for value in sorted(_GRID_RESOLUTION_VALUES.values(), reverse=True):
            if value < resolution:
                candidates.append(value)

        for size in candidates:
            asset_path = _ASSET_ROOT / folder / f"{size}.png"
            if asset_path.exists():
                return asset_path
        return _ASSET_ROOT / folder / f"{resolution}.png"

    @staticmethod
    def texture_from_file(path):
        try:
            resolved = Path(path).expanduser().resolve()
            stat = resolved.stat()
        except Exception:
            return None

        cache_key = str(resolved)
        stamp = (stat.st_mtime_ns, stat.st_size)
        cache_entry = CheckerOverlayPreview.OVERLAY_TEXTURE_CACHE.get(cache_key)
        if cache_entry is not None and cache_entry.get("stamp") == stamp:
            return cache_entry.get("texture")

        if cache_entry is not None:
            CheckerOverlayPreview.free_texture(cache_entry.get("texture"))
            CheckerOverlayPreview.free_image(cache_entry.get("image"))
            CheckerOverlayPreview.OVERLAY_TEXTURE_CACHE.pop(cache_key, None)

        try:
            texture, image = CheckerOverlayPreview.texture_from_pil_image(resolved)
        except Exception:
            texture, image = None, None

        if texture is None:
            texture, image = CheckerOverlayPreview.texture_from_blender_image(resolved)
        if texture is None:
            print(f"[HoTools CheckerOverlay] Failed to load overlay texture: {resolved}")
            return None

        CheckerOverlayPreview.OVERLAY_TEXTURE_CACHE[cache_key] = {
            "stamp": stamp,
            "texture": texture,
            "image": image,
        }
        return texture

    @staticmethod
    def resolve_overlay_texture(scene):
        mode = getattr(scene, "ho_checker_overlay_visual_mode", _DEFAULT_VISUAL_MODE)
        if mode == "CUSTOM_IMAGE":
            custom_path = getattr(scene, "ho_checker_overlay_custom_image_path", "")
            if custom_path:
                texture = CheckerOverlayPreview.texture_from_file(bpy.path.abspath(custom_path))
                if texture is not None:
                    return "IMAGE", texture
            mode = "COLOR_GRID"

        resolution = CheckerOverlayPreview.overlay_grid_resolution(scene)
        texture = CheckerOverlayPreview.texture_from_file(
            CheckerOverlayPreview.asset_file_for_mode(mode, resolution)
        )
        if texture is not None:
            return "IMAGE", texture

        return "CHECKER", None

    @staticmethod
    def ensure_draw_handler():
        if CheckerOverlayPreview.DRAW_HANDLE is None:
            CheckerOverlayPreview.DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
                _draw_overlay_handler,
                (),
                "WINDOW",
                "POST_VIEW",
            )

    @staticmethod
    def remove_draw_handler():
        if CheckerOverlayPreview.DRAW_HANDLE is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(CheckerOverlayPreview.DRAW_HANDLE, "WINDOW")
            except Exception:
                pass
            CheckerOverlayPreview.DRAW_HANDLE = None

    @staticmethod
    def ensure_realtime_handler():
        if _overlay_realtime_listener not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(_overlay_realtime_listener)

    @staticmethod
    def remove_realtime_handler():
        if _overlay_realtime_listener in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(_overlay_realtime_listener)

    @staticmethod
    def sync_runtime_handlers(context=None):
        scene = CheckerOverlayPreview.get_scene(context)
        if scene is None or not bool(getattr(scene, "ho_checker_overlay_show", False)):
            CheckerOverlayPreview.remove_draw_handler()
            CheckerOverlayPreview.remove_realtime_handler()
            CheckerOverlayPreview.clear_overlay_cache()
            return False

        CheckerOverlayPreview.ensure_draw_handler()
        if bool(getattr(scene, "ho_checker_overlay_realtime_refresh", False)):
            CheckerOverlayPreview.ensure_realtime_handler()
        else:
            CheckerOverlayPreview.remove_realtime_handler()
        return True

    @staticmethod
    def on_show_update(self, context):
        if bool(getattr(self, "ho_checker_overlay_show", False)):
            CheckerOverlayPreview.sync_runtime_handlers(context)
            CheckerOverlayPreview.refresh_draw(context)
        else:
            CheckerOverlayPreview.sync_runtime_handlers(context)
            CheckerOverlayPreview.tag_view3d_redraw()

    @staticmethod
    def on_realtime_update(self, context):
        if not bool(getattr(self, "ho_checker_overlay_show", False)):
            CheckerOverlayPreview.remove_realtime_handler()
            return

        CheckerOverlayPreview.sync_runtime_handlers(context)
        if bool(getattr(self, "ho_checker_overlay_realtime_refresh", False)):
            CheckerOverlayPreview.refresh_draw(context)
        else:
            CheckerOverlayPreview.tag_view3d_redraw()

    @staticmethod
    def on_visual_update(self, context):
        del self
        CheckerOverlayPreview.clear_texture_cache()
        if CheckerOverlayPreview.overlay_show_enabled(context):
            CheckerOverlayPreview.refresh_draw(context)
        else:
            CheckerOverlayPreview.tag_view3d_redraw()

    @staticmethod
    def on_alpha_update(self, context):
        del self, context
        CheckerOverlayPreview.tag_view3d_redraw()

    @staticmethod
    def on_mode_update(self, context):
        del self
        if CheckerOverlayPreview.overlay_show_enabled(context):
            CheckerOverlayPreview.refresh_draw(context)
        else:
            CheckerOverlayPreview.tag_view3d_redraw()

    @staticmethod
    def refresh_draw(context):
        context = context or bpy.context
        scene = CheckerOverlayPreview.get_scene(context)
        if scene is None or not bool(getattr(scene, "ho_checker_overlay_show", False)):
            return

        CheckerOverlayPreview.sync_runtime_handlers(context)
        refresh_fn = CheckerOverlayPreview.current_mode_refresh(scene)
        refresh_fn(context)
        CheckerOverlayPreview.tag_view3d_redraw()

    @staticmethod
    def visible_mesh_objects(context):
        visible_objects = getattr(context, "visible_objects", None)
        if visible_objects is None:
            visible_objects = context.view_layer.objects

        result = []
        for obj in visible_objects:
            if obj.type != "MESH":
                continue
            if not obj.visible_get():
                continue
            result.append(obj)
        return result

    @staticmethod
    def mesh_uv_layer(mesh):
        uv_layers = getattr(mesh, "uv_layers", None)
        if uv_layers is None or len(uv_layers) == 0:
            return None

        uv_layer = uv_layers.active
        if uv_layer is None:
            uv_layer = uv_layers[0]
        return uv_layer

    @staticmethod
    def append_mesh_triangles(obj, depsgraph, positions_out, uvs_out):
        evaluated_obj = obj.evaluated_get(depsgraph)
        evaluated_mesh = None
        try:
            try:
                evaluated_mesh = evaluated_obj.to_mesh(depsgraph=depsgraph)
            except TypeError:
                evaluated_mesh = evaluated_obj.to_mesh()

            if evaluated_mesh is None:
                return

            uv_layer = CheckerOverlayPreview.mesh_uv_layer(evaluated_mesh)
            if uv_layer is None or len(evaluated_mesh.vertices) == 0:
                return

            evaluated_mesh.calc_loop_triangles()

            vertex_world_positions = []
            for vertex in evaluated_mesh.vertices:
                world_pos = evaluated_obj.matrix_world @ vertex.co
                vertex_world_positions.append((world_pos.x, world_pos.y, world_pos.z))

            uv_data = [tuple(loop_uv.uv) for loop_uv in uv_layer.data]
            for tri in evaluated_mesh.loop_triangles:
                for loop_index, vertex_index in zip(tri.loops, tri.vertices):
                    positions_out.append(vertex_world_positions[vertex_index])
                    uvs_out.append(uv_data[loop_index])
        finally:
            if evaluated_mesh is not None:
                evaluated_obj.to_mesh_clear()

    @staticmethod
    def rebuild_overlay_cache(context):
        scene = CheckerOverlayPreview.get_scene(context)
        if scene is None or not bool(getattr(scene, "ho_checker_overlay_show", False)):
            CheckerOverlayPreview.OVERLAY_BATCH_CACHE = None
            CheckerOverlayPreview.set_overlay_cache_clean()
            return

        depsgraph = context.evaluated_depsgraph_get()
        positions = []
        uvs = []

        for obj in CheckerOverlayPreview.visible_mesh_objects(context):
            CheckerOverlayPreview.append_mesh_triangles(obj, depsgraph, positions, uvs)

        if not positions:
            CheckerOverlayPreview.OVERLAY_BATCH_CACHE = None
            CheckerOverlayPreview.set_overlay_cache_clean()
            return

        batch_shader = CheckerOverlayPreview.get_image_shader()
        if batch_shader is None:
            batch_shader = CheckerOverlayPreview.get_checker_shader()
        if batch_shader is None:
            CheckerOverlayPreview.OVERLAY_BATCH_CACHE = None
            CheckerOverlayPreview.set_overlay_cache_clean()
            return

        CheckerOverlayPreview.OVERLAY_BATCH_CACHE = batch_for_shader(
            batch_shader,
            "TRIS",
            {
                "position": positions,
                "uv": uvs,
            },
        )
        CheckerOverlayPreview.set_overlay_cache_clean()

    @staticmethod
    def overlay_vertex_source():
        return """
void main()
{
    vec4 clip = view_projection * vec4(position, 1.0);
    clip.z -= abs(clip.w) * depth_bias;
    gl_Position = clip;
    v_uv = uv;
}
"""

    @staticmethod
    def get_checker_shader():
        if CheckerOverlayPreview.CHECKER_SHADER is not None:
            return CheckerOverlayPreview.CHECKER_SHADER

        shader_info = gpu.types.GPUShaderCreateInfo()
        shader_info.vertex_in(0, "VEC3", "position")
        shader_info.vertex_in(1, "VEC2", "uv")

        stage_interface = gpu.types.GPUStageInterfaceInfo("CheckerOverlay")
        stage_interface.smooth("VEC2", "v_uv")
        shader_info.vertex_out(stage_interface)

        shader_info.push_constant("MAT4", "view_projection")
        shader_info.push_constant("FLOAT", "grid_scale")
        shader_info.push_constant("FLOAT", "alpha")
        shader_info.push_constant("FLOAT", "depth_bias")
        shader_info.push_constant("VEC4", "fill_a")
        shader_info.push_constant("VEC4", "fill_b")
        shader_info.fragment_out(0, "VEC4", "FragColor")
        shader_info.vertex_source(CheckerOverlayPreview.overlay_vertex_source())
        shader_info.fragment_source(
            """
void main()
{
    vec2 scaled_uv = v_uv * max(grid_scale, 0.001);
    float checker = mod(floor(scaled_uv.x) + floor(scaled_uv.y), 2.0);
    vec4 fill_color = mix(fill_a, fill_b, checker);
    FragColor = vec4(fill_color.rgb, fill_color.a * alpha);
}
"""
        )

        try:
            CheckerOverlayPreview.CHECKER_SHADER = gpu.shader.create_from_info(shader_info)
        except Exception:
            CheckerOverlayPreview.CHECKER_SHADER = None
        return CheckerOverlayPreview.CHECKER_SHADER

    @staticmethod
    def get_image_shader():
        if CheckerOverlayPreview.IMAGE_SHADER is not None:
            return CheckerOverlayPreview.IMAGE_SHADER

        shader_info = gpu.types.GPUShaderCreateInfo()
        shader_info.vertex_in(0, "VEC3", "position")
        shader_info.vertex_in(1, "VEC2", "uv")

        stage_interface = gpu.types.GPUStageInterfaceInfo("CheckerOverlayImage")
        stage_interface.smooth("VEC2", "v_uv")
        shader_info.vertex_out(stage_interface)

        shader_info.sampler(0, "FLOAT_2D", "image_tex")
        shader_info.push_constant("MAT4", "view_projection")
        shader_info.push_constant("FLOAT", "alpha")
        shader_info.push_constant("FLOAT", "depth_bias")
        shader_info.fragment_out(0, "VEC4", "FragColor")
        shader_info.vertex_source(CheckerOverlayPreview.overlay_vertex_source())
        shader_info.fragment_source(
            """
void main()
{
    vec2 uv = fract(v_uv);
    vec4 tex_color = texture(image_tex, uv);
    FragColor = vec4(tex_color.rgb, tex_color.a * alpha);
}
"""
        )

        try:
            CheckerOverlayPreview.IMAGE_SHADER = gpu.shader.create_from_info(shader_info)
        except Exception:
            CheckerOverlayPreview.IMAGE_SHADER = None
        return CheckerOverlayPreview.IMAGE_SHADER

    @staticmethod
    def draw_overlay_batch(context=None):
        context = context or bpy.context
        scene = CheckerOverlayPreview.get_scene(context)
        if scene is None or not bool(getattr(scene, "ho_checker_overlay_show", False)):
            return

        region_data = getattr(context, "region_data", None)
        if region_data is None:
            return

        if CheckerOverlayPreview.OVERLAY_BATCH_CACHE is None:
            if CheckerOverlayPreview.OVERLAY_CACHE_DIRTY:
                CheckerOverlayPreview.refresh_draw(context)
            if CheckerOverlayPreview.OVERLAY_BATCH_CACHE is None:
                return

        shader_kind, image_texture = CheckerOverlayPreview.resolve_overlay_texture(scene)
        if shader_kind == "IMAGE":
            shader = CheckerOverlayPreview.get_image_shader()
        else:
            shader = CheckerOverlayPreview.get_checker_shader()
        if shader is None or CheckerOverlayPreview.OVERLAY_BATCH_CACHE is None:
            return

        alpha = min(max(float(getattr(scene, "ho_checker_overlay_uv_grid_alpha", _DEFAULT_ALPHA)), 0.0), 1.0)
        grid_scale = max(float(CheckerOverlayPreview.overlay_grid_resolution(scene)) / 512.0, 1.0)

        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(False)
        try:
            shader.bind()
            shader.uniform_float("view_projection", region_data.perspective_matrix)
            shader.uniform_float("alpha", alpha)
            shader.uniform_float("depth_bias", _DEPTH_BIAS)

            if shader_kind == "IMAGE":
                shader.uniform_sampler("image_tex", image_texture)
            else:
                shader.uniform_float("grid_scale", grid_scale)
                shader.uniform_float("fill_a", _DEFAULT_FILL_A)
                shader.uniform_float("fill_b", _DEFAULT_FILL_B)

            CheckerOverlayPreview.OVERLAY_BATCH_CACHE.draw(shader)
        finally:
            gpu.state.depth_mask_set(True)
            gpu.state.depth_test_set("NONE")
            gpu.state.blend_set("NONE")

    @staticmethod
    def draw_active_preview(context=None):
        context = context or bpy.context
        scene = CheckerOverlayPreview.get_scene(context)
        if scene is None or not bool(getattr(scene, "ho_checker_overlay_show", False)):
            return

        region_data = getattr(context, "region_data", None)
        if region_data is None:
            return

        draw_fn = CheckerOverlayPreview.current_mode_draw(scene)
        draw_fn(context)

    @staticmethod
    def overlay_realtime_listener(scene, depsgraph=None):
        if scene is None:
            return
        if not bool(getattr(scene, "ho_checker_overlay_show", False)):
            return
        if not bool(getattr(scene, "ho_checker_overlay_realtime_refresh", False)):
            return

        if depsgraph is not None:
            try:
                if not (
                    bool(depsgraph.id_type_updated("MESH"))
                    or bool(depsgraph.id_type_updated("OBJECT"))
                    or bool(depsgraph.id_type_updated("ARMATURE"))
                ):
                    return
            except Exception:
                updates = getattr(depsgraph, "updates", None)
                if updates:
                    relevant = False
                    for update in updates:
                        id_data = getattr(update, "id", None)
                        if id_data is None:
                            continue
                        if getattr(id_data, "type", None) in {"MESH", "OBJECT", "ARMATURE"}:
                            relevant = True
                            break
                        if id_data.__class__.__name__ in {"Mesh", "Object", "Armature"}:
                            relevant = True
                            break
                    if not relevant:
                        return

        CheckerOverlayPreview.current_mode_refresh(scene)(bpy.context)
        CheckerOverlayPreview.tag_view3d_redraw()

    @staticmethod
    def overlay_load_handler(_dummy):
        context = bpy.context
        if CheckerOverlayPreview.overlay_show_enabled(context):
            CheckerOverlayPreview.sync_runtime_handlers(context)
            CheckerOverlayPreview.refresh_draw(context)
        else:
            CheckerOverlayPreview.sync_runtime_handlers(context)

    @staticmethod
    def draw_overlay_handler():
        context = bpy.context
        scene = CheckerOverlayPreview.get_scene(context)
        if scene is None or not bool(getattr(scene, "ho_checker_overlay_show", False)):
            return

        region_data = getattr(context, "region_data", None)
        if region_data is None:
            return

        mode_draw = CheckerOverlayPreview.current_mode_draw(scene)
        mode_draw(context)

    @staticmethod
    def register_props():
        bpy.types.Scene.ho_checker_overlay_show = BoolProperty(
            name="检查预览",
            description="在 3D 视图中绘制检查预览叠加层",
            default=False,
            update=CheckerOverlayPreview.on_show_update,
        )
        bpy.types.Scene.ho_checker_overlay_realtime_refresh = BoolProperty(
            name="实时刷新",
            description="在依赖对象更新时自动重建缓存",
            default=False,
            update=CheckerOverlayPreview.on_realtime_update,
        )
        bpy.types.Scene.ho_checker_overlay_check_mode = EnumProperty(
            name="检查模式",
            description="选择检查预览模式",
            items=CheckerOverlayPreview.mode_items(),
            default=CheckerOverlayPreview.default_mode_id(),
            update=CheckerOverlayPreview.on_mode_update,
        )
        bpy.types.Scene.ho_checker_overlay_visual_mode = EnumProperty(
            name="显示样式",
            description="选择外部图片显示样式",
            items=_VISUAL_MODE_ITEMS,
            default=_DEFAULT_VISUAL_MODE,
            update=CheckerOverlayPreview.on_visual_update,
        )
        bpy.types.Scene.ho_checker_overlay_custom_image_path = StringProperty(
            name="外部图片",
            description="自定义图片模式下使用的外部图片路径",
            subtype="FILE_PATH",
            default="",
            update=CheckerOverlayPreview.on_visual_update,
        )
        bpy.types.Scene.ho_checker_overlay_uv_grid_resolution = EnumProperty(
            name="像素密度",
            description="选择 512 / 1024 / 2048 / 4096 像素密度",
            items=_GRID_RESOLUTION_ITEMS,
            default=_DEFAULT_GRID_RESOLUTION,
            update=CheckerOverlayPreview.on_visual_update,
        )
        bpy.types.Scene.ho_checker_overlay_uv_grid_alpha = FloatProperty(
            name="不透明度",
            default=_DEFAULT_ALPHA,
            min=0.0,
            max=1.0,
            update=CheckerOverlayPreview.on_alpha_update,
        )

    @staticmethod
    def unregister_props():
        for prop_name in (
            "ho_checker_overlay_uv_grid_alpha",
            "ho_checker_overlay_uv_grid_resolution",
            "ho_checker_overlay_custom_image_path",
            "ho_checker_overlay_visual_mode",
            "ho_checker_overlay_check_mode",
            "ho_checker_overlay_realtime_refresh",
            "ho_checker_overlay_show",
        ):
            if hasattr(bpy.types.Scene, prop_name):
                delattr(bpy.types.Scene, prop_name)

    @staticmethod
    def draw_uv_grid_panel(layout, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return

        active_mode = CheckerOverlayPreview.current_mode_spec(scene)
        if active_mode is not None:
            layout.label(text=f"当前模式：{active_mode['label']}")

        if scene.ho_checker_overlay_visual_mode == "CUSTOM_IMAGE":
            layout.label(text="显示样式")
            layout.prop(scene, "ho_checker_overlay_visual_mode", text="")
            layout.prop(scene, "ho_checker_overlay_custom_image_path", text="图片路径")
        else:
            layout.label(text="显示样式")
            layout.prop(scene, "ho_checker_overlay_visual_mode", text="")
            layout.prop(scene, "ho_checker_overlay_uv_grid_resolution", text="像素密度")
        layout.prop(scene, "ho_checker_overlay_uv_grid_alpha", text="不透明度", slider=True)

    @staticmethod
    def draw_panel(layout, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return

        row = layout.row(align=True)
        row.prop(scene, "ho_checker_overlay_show", text="检查预览", toggle=True, icon="OVERLAY")
        row.prop(scene, "ho_checker_overlay_realtime_refresh", text="", toggle=True, icon="TIME")
        refresh_row = row.row(align=True)
        refresh_row.enabled = bool(scene.ho_checker_overlay_show)
        refresh_row.operator(OP_Hotools_CheckerOverlayRefresh.bl_idname, text="", icon="FILE_REFRESH")

        col = layout.column(align=True)
        col.enabled = bool(scene.ho_checker_overlay_show)

        mode_items = CheckerOverlayPreview.mode_items()
        if len(mode_items) > 1:
            col.prop(scene, "ho_checker_overlay_check_mode", text="检查模式")

        active_mode = CheckerOverlayPreview.current_mode_spec(scene)
        if active_mode is not None:
            panel_fn = active_mode.get("draw_panel") or CheckerOverlayPreview.draw_uv_grid_panel
            panel_fn(col, context)

    @staticmethod
    def draw_header(self, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return

        row = self.layout.row(align=True)
        row.prop(
            scene,
            "ho_checker_overlay_show",
            text="",
            icon="OVERLAY",
            toggle=True,
        )
        row.popover(
            panel=PT_Hotools_CheckerOverlayPopover.bl_idname,
            text="",
        )


def _ensure_overlay_modes():
    CheckerOverlayPreview.register_mode(
        "UV_GRID",
        label="UV 栅格检查",
        description="绘制所有可见 Mesh 的 UV 栅格预览",
        refresh=CheckerOverlayPreview.rebuild_overlay_cache,
        draw=CheckerOverlayPreview.draw_overlay_batch,
        draw_panel=CheckerOverlayPreview.draw_uv_grid_panel,
    )


_ensure_overlay_modes()


def _tag_view3d_redraw():
    CheckerOverlayPreview.tag_view3d_redraw()


def _get_scene(context):
    return CheckerOverlayPreview.get_scene(context)


def _overlay_show_enabled(context=None):
    return CheckerOverlayPreview.overlay_show_enabled(context)


def _clear_overlay_cache():
    CheckerOverlayPreview.clear_overlay_cache()


def _set_overlay_cache_clean():
    CheckerOverlayPreview.set_overlay_cache_clean()


def _overlay_grid_resolution(scene):
    return CheckerOverlayPreview.overlay_grid_resolution(scene)


def _asset_file_for_mode(mode, resolution):
    return CheckerOverlayPreview.asset_file_for_mode(mode, resolution)


def _texture_from_file(path):
    return CheckerOverlayPreview.texture_from_file(path)


def _resolve_overlay_texture(scene):
    return CheckerOverlayPreview.resolve_overlay_texture(scene)


def _ensure_draw_handler():
    CheckerOverlayPreview.ensure_draw_handler()


def _remove_draw_handler():
    CheckerOverlayPreview.remove_draw_handler()


def _ensure_realtime_handler():
    CheckerOverlayPreview.ensure_realtime_handler()


def _remove_realtime_handler():
    CheckerOverlayPreview.remove_realtime_handler()


def _sync_runtime_handlers(context=None):
    return CheckerOverlayPreview.sync_runtime_handlers(context)


def _overlay_show_update(self, context):
    CheckerOverlayPreview.on_show_update(self, context)


def _overlay_realtime_update(self, context):
    CheckerOverlayPreview.on_realtime_update(self, context)


def _overlay_visual_update(self, context):
    CheckerOverlayPreview.on_visual_update(self, context)


def _overlay_mode_update(self, context):
    CheckerOverlayPreview.on_mode_update(self, context)


def refresh_draw(context):
    CheckerOverlayPreview.refresh_draw(context)


def _visible_mesh_objects(context):
    return CheckerOverlayPreview.visible_mesh_objects(context)


def _mesh_uv_layer(mesh):
    return CheckerOverlayPreview.mesh_uv_layer(mesh)


def _append_mesh_triangles(obj, depsgraph, positions_out, uvs_out):
    CheckerOverlayPreview.append_mesh_triangles(obj, depsgraph, positions_out, uvs_out)


def _rebuild_overlay_cache(context):
    CheckerOverlayPreview.rebuild_overlay_cache(context)


def _get_checker_shader():
    return CheckerOverlayPreview.get_checker_shader()


def _get_image_shader():
    return CheckerOverlayPreview.get_image_shader()


def _draw_uv_grid_overlay():
    CheckerOverlayPreview.draw_active_preview()


def _draw_overlay_handler():
    CheckerOverlayPreview.draw_overlay_handler()


def _overlay_realtime_listener(scene, depsgraph=None):
    CheckerOverlayPreview.overlay_realtime_listener(scene, depsgraph)


@persistent
def _overlay_load_handler(_dummy):
    CheckerOverlayPreview.overlay_load_handler(_dummy)


def reg_props():
    _ensure_overlay_modes()
    CheckerOverlayPreview.register_props()


def ureg_props():
    CheckerOverlayPreview.unregister_props()
    CheckerOverlayPreview.clear_texture_cache()


class OP_Hotools_CheckerOverlayRefresh(Operator):
    bl_idname = "ho.checker_overlay_refresh"
    bl_label = "刷新检查预览"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        return bool(scene and getattr(scene, "ho_checker_overlay_show", False))

    def execute(self, context):
        refresh_draw(context)
        return {"FINISHED"}


class PT_Hotools_CheckerOverlayPopover(Panel):
    bl_idname = "VIEW3D_PT_Hotools_CheckerOverlayPopover"
    bl_label = "HoTools 检查预览"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 14

    def draw(self, context):
        drawCheckerOverlayPanel(self.layout, context)


def drawCheckerOverlayPanel(layout, context):
    CheckerOverlayPreview.draw_panel(layout, context)


def draw_checker_overlay_header(self, context):
    CheckerOverlayPreview.draw_header(self, context)


cls = [
    OP_Hotools_CheckerOverlayRefresh,
    PT_Hotools_CheckerOverlayPopover,
]


def register():
    _ensure_overlay_modes()

    for cls_item in cls:
        bpy.utils.register_class(cls_item)

    reg_props()

    _remove_header()
    bpy.types.VIEW3D_HT_header.append(draw_checker_overlay_header)

    if _overlay_load_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_overlay_load_handler)

    context = bpy.context
    if _overlay_show_enabled(context):
        _sync_runtime_handlers(context)
        refresh_draw(context)


def _remove_header():
    try:
        bpy.types.VIEW3D_HT_header.remove(draw_checker_overlay_header)
    except Exception:
        pass


def unregister():
    _remove_header()
    _remove_draw_handler()
    _remove_realtime_handler()
    _clear_overlay_cache()
    CheckerOverlayPreview.clear_texture_cache()

    if _overlay_load_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_overlay_load_handler)

    ureg_props()

    for cls_item in reversed(cls):
        bpy.utils.unregister_class(cls_item)
