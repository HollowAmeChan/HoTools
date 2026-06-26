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

_CHIRALITY_NORMAL_COLOR = (1.0, 1.0, 1.0, 1.0)
_CHIRALITY_MIRROR_COLOR = (0.0, 0.0, 0.0, 1.0)
_CHIRALITY_UNDEFINED_COLOR = (0.50, 0.50, 0.50, 1.0)

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


class CheckerOverlayCommon:
    """
    叠加层预览的公共基础设施。

    负责管理 3D 视图绘制 handler、实时刷新 handler、批次缓存、贴图缓存、
    可见 Mesh 收集、临时 evaluated mesh 获取、通用 shader 顶点代码等共用逻辑。
    具体检查模式只负责生成自己的绘制数据和 shader，避免把刷新与绘制生命周期散在各个模式里。
    """

    DRAW_HANDLE = None
    OVERLAY_BATCH_CACHE = None
    OVERLAY_CACHE_DIRTY = True
    OVERLAY_TEXTURE_CACHE = {}

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
        scene = CheckerOverlayCommon.get_scene(context)
        return bool(scene and getattr(scene, "ho_checker_overlay_show", False))

    @staticmethod
    def clear_overlay_cache():
        CheckerOverlayCommon.OVERLAY_BATCH_CACHE = None
        CheckerOverlayCommon.OVERLAY_CACHE_DIRTY = True

    @staticmethod
    def set_overlay_cache_clean():
        CheckerOverlayCommon.OVERLAY_CACHE_DIRTY = False

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
        for entry in CheckerOverlayCommon.OVERLAY_TEXTURE_CACHE.values():
            texture = entry.get("texture") if isinstance(entry, dict) else None
            image = entry.get("image") if isinstance(entry, dict) else None
            CheckerOverlayCommon.free_texture(texture)
            CheckerOverlayCommon.free_image(image)
        CheckerOverlayCommon.OVERLAY_TEXTURE_CACHE.clear()

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
            buffer = CheckerOverlayCommon.texture_buffer_from_pixels(width, height, pixels)
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
            CheckerOverlayCommon.free_image(image)
            return None, None

    @staticmethod
    def texture_from_file(path):
        try:
            resolved = Path(path).expanduser().resolve()
            stat = resolved.stat()
        except Exception:
            return None

        cache_key = str(resolved)
        stamp = (stat.st_mtime_ns, stat.st_size)
        cache_entry = CheckerOverlayCommon.OVERLAY_TEXTURE_CACHE.get(cache_key)
        if cache_entry is not None and cache_entry.get("stamp") == stamp:
            return cache_entry.get("texture")

        if cache_entry is not None:
            CheckerOverlayCommon.free_texture(cache_entry.get("texture"))
            CheckerOverlayCommon.free_image(cache_entry.get("image"))
            CheckerOverlayCommon.OVERLAY_TEXTURE_CACHE.pop(cache_key, None)

        try:
            texture, image = CheckerOverlayCommon.texture_from_pil_image(resolved)
        except Exception:
            texture, image = None, None

        if texture is None:
            texture, image = CheckerOverlayCommon.texture_from_blender_image(resolved)
        if texture is None:
            print(f"[HoTools CheckerOverlay] Failed to load overlay texture: {resolved}")
            return None

        CheckerOverlayCommon.OVERLAY_TEXTURE_CACHE[cache_key] = {
            "stamp": stamp,
            "texture": texture,
            "image": image,
        }
        return texture

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
    def evaluated_mesh(obj, depsgraph):
        evaluated_obj = obj.evaluated_get(depsgraph)
        try:
            return evaluated_obj, evaluated_obj.to_mesh(depsgraph=depsgraph)
        except TypeError:
            return evaluated_obj, evaluated_obj.to_mesh()

    @staticmethod
    def alpha(scene):
        return min(max(float(getattr(scene, "ho_checker_overlay_uv_grid_alpha", _DEFAULT_ALPHA)), 0.0), 1.0)

    @staticmethod
    def overlay_vertex_source(varying_assignment):
        return f"""
void main()
{{
    vec4 clip = view_projection * vec4(position, 1.0);
    clip.z -= abs(clip.w) * depth_bias;
    gl_Position = clip;
    {varying_assignment}
}}
"""

    @staticmethod
    def ensure_draw_handler():
        if CheckerOverlayCommon.DRAW_HANDLE is None:
            CheckerOverlayCommon.DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
                _draw_overlay_handler,
                (),
                "WINDOW",
                "POST_VIEW",
            )

    @staticmethod
    def remove_draw_handler():
        if CheckerOverlayCommon.DRAW_HANDLE is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(CheckerOverlayCommon.DRAW_HANDLE, "WINDOW")
            except Exception:
                pass
            CheckerOverlayCommon.DRAW_HANDLE = None

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
        scene = CheckerOverlayCommon.get_scene(context)
        if scene is None or not bool(getattr(scene, "ho_checker_overlay_show", False)):
            CheckerOverlayCommon.remove_draw_handler()
            CheckerOverlayCommon.remove_realtime_handler()
            CheckerOverlayCommon.clear_overlay_cache()
            return False

        CheckerOverlayCommon.ensure_draw_handler()
        if bool(getattr(scene, "ho_checker_overlay_realtime_refresh", False)):
            CheckerOverlayCommon.ensure_realtime_handler()
        else:
            CheckerOverlayCommon.remove_realtime_handler()
        return True

    @staticmethod
    def refresh_draw(context):
        context = context or bpy.context
        scene = CheckerOverlayCommon.get_scene(context)
        if scene is None or not bool(getattr(scene, "ho_checker_overlay_show", False)):
            return

        CheckerOverlayCommon.sync_runtime_handlers(context)
        refresh_fn = CheckerOverlayPreview.current_mode_refresh(scene)
        refresh_fn(context)
        CheckerOverlayCommon.tag_view3d_redraw()

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
        CheckerOverlayCommon.tag_view3d_redraw()

    @staticmethod
    def overlay_load_handler(_dummy):
        context = bpy.context
        if CheckerOverlayCommon.overlay_show_enabled(context):
            CheckerOverlayCommon.sync_runtime_handlers(context)
            CheckerOverlayCommon.refresh_draw(context)
        else:
            CheckerOverlayCommon.sync_runtime_handlers(context)

    @staticmethod
    def draw_overlay_handler():
        context = bpy.context
        scene = CheckerOverlayCommon.get_scene(context)
        if scene is None or not bool(getattr(scene, "ho_checker_overlay_show", False)):
            return

        region_data = getattr(context, "region_data", None)
        if region_data is None:
            return

        mode_draw = CheckerOverlayPreview.current_mode_draw(scene)
        mode_draw(context)


class UVGridOverlayPreview:
    """
    UV 栅格检查模式。

    负责把所有可见 Mesh 的世界坐标三角面和 UV 坐标打包成 GPU batch，
    并按用户选择的外部 UV Grid、Color Grid、Checker 或自定义图片进行采样绘制。
    当外部资源缺失时会退回到程序化棋盘格 shader，保证预览功能仍然可用。
    """

    CHECKER_SHADER = None
    IMAGE_SHADER = None

    @staticmethod
    def grid_resolution(scene):
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
    def resolve_texture(scene):
        mode = getattr(scene, "ho_checker_overlay_visual_mode", _DEFAULT_VISUAL_MODE)
        if mode == "CUSTOM_IMAGE":
            custom_path = getattr(scene, "ho_checker_overlay_custom_image_path", "")
            if custom_path:
                texture = CheckerOverlayCommon.texture_from_file(bpy.path.abspath(custom_path))
                if texture is not None:
                    return "IMAGE", texture
            mode = "COLOR_GRID"

        resolution = UVGridOverlayPreview.grid_resolution(scene)
        texture = CheckerOverlayCommon.texture_from_file(
            UVGridOverlayPreview.asset_file_for_mode(mode, resolution)
        )
        if texture is not None:
            return "IMAGE", texture

        return "CHECKER", None

    @staticmethod
    def append_mesh_triangles(obj, depsgraph, positions_out, uvs_out):
        evaluated_obj, evaluated_mesh = CheckerOverlayCommon.evaluated_mesh(obj, depsgraph)
        try:
            if evaluated_mesh is None:
                return

            uv_layer = CheckerOverlayCommon.mesh_uv_layer(evaluated_mesh)
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
    def rebuild_cache(context):
        scene = CheckerOverlayCommon.get_scene(context)
        if scene is None or not bool(getattr(scene, "ho_checker_overlay_show", False)):
            CheckerOverlayCommon.OVERLAY_BATCH_CACHE = None
            CheckerOverlayCommon.set_overlay_cache_clean()
            return

        depsgraph = context.evaluated_depsgraph_get()
        positions = []
        uvs = []

        for obj in CheckerOverlayCommon.visible_mesh_objects(context):
            UVGridOverlayPreview.append_mesh_triangles(obj, depsgraph, positions, uvs)

        if not positions:
            CheckerOverlayCommon.OVERLAY_BATCH_CACHE = None
            CheckerOverlayCommon.set_overlay_cache_clean()
            return

        batch_shader = UVGridOverlayPreview.get_image_shader()
        if batch_shader is None:
            batch_shader = UVGridOverlayPreview.get_checker_shader()
        if batch_shader is None:
            CheckerOverlayCommon.OVERLAY_BATCH_CACHE = None
            CheckerOverlayCommon.set_overlay_cache_clean()
            return

        CheckerOverlayCommon.OVERLAY_BATCH_CACHE = batch_for_shader(
            batch_shader,
            "TRIS",
            {
                "position": positions,
                "uv": uvs,
            },
        )
        CheckerOverlayCommon.set_overlay_cache_clean()

    @staticmethod
    def get_checker_shader():
        if UVGridOverlayPreview.CHECKER_SHADER is not None:
            return UVGridOverlayPreview.CHECKER_SHADER

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
        shader_info.vertex_source(CheckerOverlayCommon.overlay_vertex_source("v_uv = uv;"))
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
            UVGridOverlayPreview.CHECKER_SHADER = gpu.shader.create_from_info(shader_info)
        except Exception:
            UVGridOverlayPreview.CHECKER_SHADER = None
        return UVGridOverlayPreview.CHECKER_SHADER

    @staticmethod
    def get_image_shader():
        if UVGridOverlayPreview.IMAGE_SHADER is not None:
            return UVGridOverlayPreview.IMAGE_SHADER

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
        shader_info.vertex_source(CheckerOverlayCommon.overlay_vertex_source("v_uv = uv;"))
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
            UVGridOverlayPreview.IMAGE_SHADER = gpu.shader.create_from_info(shader_info)
        except Exception:
            UVGridOverlayPreview.IMAGE_SHADER = None
        return UVGridOverlayPreview.IMAGE_SHADER

    @staticmethod
    def draw(context=None):
        context = context or bpy.context
        scene = CheckerOverlayCommon.get_scene(context)
        if scene is None or not bool(getattr(scene, "ho_checker_overlay_show", False)):
            return

        region_data = getattr(context, "region_data", None)
        if region_data is None:
            return

        if CheckerOverlayCommon.OVERLAY_BATCH_CACHE is None:
            if CheckerOverlayCommon.OVERLAY_CACHE_DIRTY:
                CheckerOverlayCommon.refresh_draw(context)
            if CheckerOverlayCommon.OVERLAY_BATCH_CACHE is None:
                return

        shader_kind, image_texture = UVGridOverlayPreview.resolve_texture(scene)
        if shader_kind == "IMAGE":
            shader = UVGridOverlayPreview.get_image_shader()
        else:
            shader = UVGridOverlayPreview.get_checker_shader()
        if shader is None:
            return

        alpha = CheckerOverlayCommon.alpha(scene)
        grid_scale = max(float(UVGridOverlayPreview.grid_resolution(scene)) / 512.0, 1.0)

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

            CheckerOverlayCommon.OVERLAY_BATCH_CACHE.draw(shader)
        finally:
            gpu.state.depth_mask_set(True)
            gpu.state.depth_test_set("NONE")
            gpu.state.blend_set("NONE")

    @staticmethod
    def draw_panel(layout, context):
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


class UVChiralityOverlayPreview:
    """
    UV 手性检查模式。

    负责按 UV 连通关系划分 UV 岛，并参考 bake 逻辑通过 tangent、bitangent、normal
    的方向关系判断每个 UV 岛是正常、镜像还是未定义。
    绘制时使用纯色叠加：白色表示正常，黑色表示镜像，灰色表示未定义。
    """

    SOLID_COLOR_SHADER = None

    @staticmethod
    def mesh_face_edge_uv_pair(mesh, uv_layer, polygon_index, edge_index):
        loop_indices = list(mesh.polygons[polygon_index].loop_indices)
        for offset, loop_index in enumerate(loop_indices):
            if mesh.loops[loop_index].edge_index != edge_index:
                continue
            next_loop_index = loop_indices[(offset + 1) % len(loop_indices)]
            return (
                uv_layer.data[loop_index].uv.copy(),
                uv_layer.data[next_loop_index].uv.copy(),
            )
        return None

    @staticmethod
    def mesh_uv_edge_connected(mesh, uv_layer, polygon_index, linked_polygon_index, edge_index, epsilon=1e-5):
        pair_a = UVChiralityOverlayPreview.mesh_face_edge_uv_pair(mesh, uv_layer, polygon_index, edge_index)
        pair_b = UVChiralityOverlayPreview.mesh_face_edge_uv_pair(mesh, uv_layer, linked_polygon_index, edge_index)
        if pair_a is None or pair_b is None:
            return False

        a0, a1 = pair_a
        b0, b1 = pair_b
        same_dir = (a0 - b0).length < epsilon and (a1 - b1).length < epsilon
        flip_dir = (a0 - b1).length < epsilon and (a1 - b0).length < epsilon
        return same_dir or flip_dir

    @staticmethod
    def find_mesh_uv_islands(mesh, uv_layer):
        edge_faces = {}
        poly_edges = {}
        for poly in mesh.polygons:
            edges = [mesh.loops[loop_index].edge_index for loop_index in poly.loop_indices]
            poly_edges[poly.index] = edges
            for edge_index in edges:
                edge_faces.setdefault(edge_index, []).append(poly.index)

        islands = []
        visited = set()
        for poly in mesh.polygons:
            if poly.index in visited:
                continue

            island = set()
            stack = [poly.index]
            while stack:
                polygon_index = stack.pop()
                if polygon_index in island:
                    continue

                island.add(polygon_index)
                visited.add(polygon_index)

                for edge_index in poly_edges.get(polygon_index, []):
                    for linked_polygon_index in edge_faces.get(edge_index, []):
                        if (
                            linked_polygon_index == polygon_index
                            or linked_polygon_index in island
                            or linked_polygon_index in visited
                        ):
                            continue
                        if UVChiralityOverlayPreview.mesh_uv_edge_connected(
                            mesh, uv_layer, polygon_index, linked_polygon_index, edge_index
                        ):
                            stack.append(linked_polygon_index)

            islands.append(island)

        return islands

    @staticmethod
    def calc_uv_chirality_triangle(mesh, uv_layer, polygon, tri_loop_indices):
        p0 = mesh.vertices[mesh.loops[tri_loop_indices[0]].vertex_index].co
        p1 = mesh.vertices[mesh.loops[tri_loop_indices[1]].vertex_index].co
        p2 = mesh.vertices[mesh.loops[tri_loop_indices[2]].vertex_index].co
        uv0 = uv_layer.data[tri_loop_indices[0]].uv
        uv1 = uv_layer.data[tri_loop_indices[1]].uv
        uv2 = uv_layer.data[tri_loop_indices[2]].uv

        q1 = p1 - p0
        q2 = p2 - p0
        du1 = uv1.x - uv0.x
        dv1 = uv1.y - uv0.y
        du2 = uv2.x - uv0.x
        dv2 = uv2.y - uv0.y
        det = du1 * dv2 - dv1 * du2
        if abs(det) <= 1e-12:
            return None

        tangent = (q1 * dv2 - q2 * dv1) / det
        bitangent = (q2 * du1 - q1 * du2) / det
        normal = polygon.normal.copy()
        if normal.length <= 1e-8:
            normal = q1.cross(q2)
        if tangent.length <= 1e-8 or bitangent.length <= 1e-8 or normal.length <= 1e-8:
            return None

        area = q1.cross(q2).length
        tangent.normalize()
        bitangent.normalize()
        normal.normalize()
        handedness = tangent.cross(bitangent).dot(normal)
        if abs(handedness) <= 1e-8:
            return None

        uv_area = abs(det)
        weight = area if area > 1e-8 else uv_area
        return (1 if handedness >= 0.0 else -1), weight

    @staticmethod
    def chirality_color(sign):
        if sign > 0:
            return _CHIRALITY_NORMAL_COLOR
        if sign < 0:
            return _CHIRALITY_MIRROR_COLOR
        return _CHIRALITY_UNDEFINED_COLOR

    @staticmethod
    def append_mesh_triangles(obj, depsgraph, positions_out, colors_out):
        evaluated_obj, evaluated_mesh = CheckerOverlayCommon.evaluated_mesh(obj, depsgraph)
        try:
            if evaluated_mesh is None:
                return

            uv_layer = CheckerOverlayCommon.mesh_uv_layer(evaluated_mesh)
            if uv_layer is None or len(evaluated_mesh.vertices) == 0:
                return

            evaluated_mesh.calc_loop_triangles()
            tri_by_polygon = {}
            for tri in evaluated_mesh.loop_triangles:
                tri_by_polygon.setdefault(tri.polygon_index, []).append(tri)

            vertex_world_positions = []
            for vertex in evaluated_mesh.vertices:
                world_pos = evaluated_obj.matrix_world @ vertex.co
                vertex_world_positions.append((world_pos.x, world_pos.y, world_pos.z))

            for island_polygon_indices in UVChiralityOverlayPreview.find_mesh_uv_islands(evaluated_mesh, uv_layer):
                island_score = 0.0
                island_defined = 0
                island_tris = []

                for polygon_index in island_polygon_indices:
                    polygon = evaluated_mesh.polygons[polygon_index]
                    for tri in tri_by_polygon.get(polygon_index, []):
                        tri_loop_indices = list(tri.loops)
                        chirality = UVChiralityOverlayPreview.calc_uv_chirality_triangle(
                            evaluated_mesh, uv_layer, polygon, tri_loop_indices
                        )
                        sign = 0
                        if chirality is not None:
                            sign, weight = chirality
                            island_score += sign * weight
                            island_defined += 1
                        island_tris.append((tri, sign))

                if not island_tris:
                    continue

                island_sign = 0
                if island_defined > 0:
                    island_sign = 1 if island_score >= 0.0 else -1
                color = UVChiralityOverlayPreview.chirality_color(island_sign)

                for tri, _tri_sign in island_tris:
                    for vertex_index in tri.vertices:
                        positions_out.append(vertex_world_positions[vertex_index])
                        colors_out.append(color)
        finally:
            if evaluated_mesh is not None:
                evaluated_obj.to_mesh_clear()

    @staticmethod
    def rebuild_cache(context):
        scene = CheckerOverlayCommon.get_scene(context)
        if scene is None or not bool(getattr(scene, "ho_checker_overlay_show", False)):
            CheckerOverlayCommon.OVERLAY_BATCH_CACHE = None
            CheckerOverlayCommon.set_overlay_cache_clean()
            return

        depsgraph = context.evaluated_depsgraph_get()
        positions = []
        colors = []

        for obj in CheckerOverlayCommon.visible_mesh_objects(context):
            UVChiralityOverlayPreview.append_mesh_triangles(obj, depsgraph, positions, colors)

        if not positions:
            CheckerOverlayCommon.OVERLAY_BATCH_CACHE = None
            CheckerOverlayCommon.set_overlay_cache_clean()
            return

        shader = UVChiralityOverlayPreview.get_solid_color_shader()
        if shader is None:
            CheckerOverlayCommon.OVERLAY_BATCH_CACHE = None
            CheckerOverlayCommon.set_overlay_cache_clean()
            return

        CheckerOverlayCommon.OVERLAY_BATCH_CACHE = batch_for_shader(
            shader,
            "TRIS",
            {
                "position": positions,
                "color": colors,
            },
        )
        CheckerOverlayCommon.set_overlay_cache_clean()

    @staticmethod
    def get_solid_color_shader():
        if UVChiralityOverlayPreview.SOLID_COLOR_SHADER is not None:
            return UVChiralityOverlayPreview.SOLID_COLOR_SHADER

        shader_info = gpu.types.GPUShaderCreateInfo()
        shader_info.vertex_in(0, "VEC3", "position")
        shader_info.vertex_in(1, "VEC4", "color")

        stage_interface = gpu.types.GPUStageInterfaceInfo("CheckerOverlayColor")
        stage_interface.smooth("VEC4", "v_color")
        shader_info.vertex_out(stage_interface)

        shader_info.push_constant("MAT4", "view_projection")
        shader_info.push_constant("FLOAT", "alpha")
        shader_info.push_constant("FLOAT", "depth_bias")
        shader_info.fragment_out(0, "VEC4", "FragColor")
        shader_info.vertex_source(CheckerOverlayCommon.overlay_vertex_source("v_color = color;"))
        shader_info.fragment_source(
            """
void main()
{
    FragColor = vec4(v_color.rgb, v_color.a * alpha);
}
"""
        )

        try:
            UVChiralityOverlayPreview.SOLID_COLOR_SHADER = gpu.shader.create_from_info(shader_info)
        except Exception:
            UVChiralityOverlayPreview.SOLID_COLOR_SHADER = None
        return UVChiralityOverlayPreview.SOLID_COLOR_SHADER

    @staticmethod
    def draw(context=None):
        context = context or bpy.context
        scene = CheckerOverlayCommon.get_scene(context)
        if scene is None or not bool(getattr(scene, "ho_checker_overlay_show", False)):
            return

        region_data = getattr(context, "region_data", None)
        if region_data is None:
            return

        if CheckerOverlayCommon.OVERLAY_BATCH_CACHE is None:
            if CheckerOverlayCommon.OVERLAY_CACHE_DIRTY:
                CheckerOverlayCommon.refresh_draw(context)
            if CheckerOverlayCommon.OVERLAY_BATCH_CACHE is None:
                return

        shader = UVChiralityOverlayPreview.get_solid_color_shader()
        if shader is None:
            return

        alpha = CheckerOverlayCommon.alpha(scene)

        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(False)
        try:
            shader.bind()
            shader.uniform_float("view_projection", region_data.perspective_matrix)
            shader.uniform_float("alpha", alpha)
            shader.uniform_float("depth_bias", _DEPTH_BIAS)
            CheckerOverlayCommon.OVERLAY_BATCH_CACHE.draw(shader)
        finally:
            gpu.state.depth_mask_set(True)
            gpu.state.depth_test_set("NONE")
            gpu.state.blend_set("NONE")

    @staticmethod
    def draw_panel(layout, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return

        active_mode = CheckerOverlayPreview.current_mode_spec(scene)
        if active_mode is not None:
            layout.label(text=f"当前模式：{active_mode['label']}")

        layout.label(text="白色：正常")
        layout.label(text="黑色：镜像")
        layout.label(text="灰色：未定义")
        layout.prop(scene, "ho_checker_overlay_uv_grid_alpha", text="不透明度", slider=True)


class CheckerOverlayPreview:
    """
    检查预览的模式注册表与 UI 外壳。

    负责维护当前支持的检查模式、注册 Scene 属性、响应属性 update 回调，
    并把顶部叠加层弹窗里的通用控件转发给当前模式自己的面板绘制函数。
    新增检查模式时优先在这里注册模式规格，而不是把模式逻辑混进这个管理层。
    """

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
    def current_mode_refresh(scene):
        spec = CheckerOverlayPreview.current_mode_spec(scene)
        refresh_fn = spec.get("refresh") if spec is not None else None
        return refresh_fn or UVGridOverlayPreview.rebuild_cache

    @staticmethod
    def current_mode_draw(scene):
        spec = CheckerOverlayPreview.current_mode_spec(scene)
        draw_fn = spec.get("draw") if spec is not None else None
        return draw_fn or UVGridOverlayPreview.draw

    @staticmethod
    def on_show_update(self, context):
        if bool(getattr(self, "ho_checker_overlay_show", False)):
            CheckerOverlayCommon.sync_runtime_handlers(context)
            CheckerOverlayCommon.refresh_draw(context)
        else:
            CheckerOverlayCommon.sync_runtime_handlers(context)
            CheckerOverlayCommon.tag_view3d_redraw()

    @staticmethod
    def on_realtime_update(self, context):
        if not bool(getattr(self, "ho_checker_overlay_show", False)):
            CheckerOverlayCommon.remove_realtime_handler()
            return

        CheckerOverlayCommon.sync_runtime_handlers(context)
        if bool(getattr(self, "ho_checker_overlay_realtime_refresh", False)):
            CheckerOverlayCommon.refresh_draw(context)
        else:
            CheckerOverlayCommon.tag_view3d_redraw()

    @staticmethod
    def on_visual_update(self, context):
        del self
        CheckerOverlayCommon.clear_texture_cache()
        if CheckerOverlayCommon.overlay_show_enabled(context):
            CheckerOverlayCommon.refresh_draw(context)
        else:
            CheckerOverlayCommon.tag_view3d_redraw()

    @staticmethod
    def on_alpha_update(self, context):
        del self, context
        CheckerOverlayCommon.tag_view3d_redraw()

    @staticmethod
    def on_mode_update(self, context):
        del self
        CheckerOverlayCommon.clear_overlay_cache()
        if CheckerOverlayCommon.overlay_show_enabled(context):
            CheckerOverlayCommon.refresh_draw(context)
        else:
            CheckerOverlayCommon.tag_view3d_redraw()

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
            description="依赖对象更新时自动重建缓存，复杂模型可能变卡；通常建议手动刷新",
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
            description="选择 512 / 1024 / 2048 / 4096 / 8192 像素密度",
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
            panel_fn = active_mode.get("draw_panel") or UVGridOverlayPreview.draw_panel
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


class OP_Hotools_CheckerOverlayRefresh(Operator):
    """
    检查预览的手动刷新操作。

    只在叠加层预览开启时可用，用于在实时刷新关闭的情况下主动重建当前模式的 GPU batch。
    具体刷新逻辑不放在 Operator 内部，而是转交给模块桥接层，保证按钮、加载回调和注册逻辑走同一条刷新路径。
    """

    bl_idname = "ho.checker_overlay_refresh"
    bl_label = "刷新检查预览"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        return bool(scene and getattr(scene, "ho_checker_overlay_show", False))

    def execute(self, context):
        CheckerOverlayModule.refresh_draw(context)
        return {"FINISHED"}


class PT_Hotools_CheckerOverlayPopover(Panel):
    """
    3D 视图顶部叠加层弹窗。

    只承载 Checker 预览相关的开关、刷新按钮和当前模式参数。
    入口放在 3D View header 的 overlay 区域，不再额外绘制侧边栏面板。
    """

    bl_idname = "VIEW3D_PT_Hotools_CheckerOverlayPopover"
    bl_label = "HoTools 检查预览"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 14

    def draw(self, context):
        drawCheckerOverlayPanel(self.layout, context)


class CheckerOverlayModule:
    """
    overlayPreview 模块的注册桥接层。

    负责集中维护模式注册、外部 draw handler 回调、depsgraph 实时刷新回调、
    blend 文件加载回调和 header 注入移除逻辑。
    模块底部保留的裸函数只作为 addon register/unregister 与旧调用点的公开入口。
    """

    @staticmethod
    def ensure_overlay_modes():
        CheckerOverlayPreview.MODE_SPECS.clear()
        CheckerOverlayPreview.register_mode(
            "UV_GRID",
            label="UV 栅格检查",
            description="绘制所有可见 Mesh 的 UV 栅格预览",
            refresh=UVGridOverlayPreview.rebuild_cache,
            draw=UVGridOverlayPreview.draw,
            draw_panel=UVGridOverlayPreview.draw_panel,
        )
        CheckerOverlayPreview.register_mode(
            "UV_CHIRALITY",
            label="UV 手性检查",
            description="按 UV 岛显示正常、镜像、未定义手性",
            refresh=UVChiralityOverlayPreview.rebuild_cache,
            draw=UVChiralityOverlayPreview.draw,
            draw_panel=UVChiralityOverlayPreview.draw_panel,
        )

    @staticmethod
    def refresh_draw(context):
        CheckerOverlayCommon.refresh_draw(context)

    @staticmethod
    def draw_overlay_handler():
        CheckerOverlayCommon.draw_overlay_handler()

    @staticmethod
    def overlay_realtime_listener(scene, depsgraph=None):
        CheckerOverlayCommon.overlay_realtime_listener(scene, depsgraph)

    @staticmethod
    def overlay_load_handler(_dummy):
        CheckerOverlayCommon.overlay_load_handler(_dummy)

    @staticmethod
    def remove_header():
        try:
            bpy.types.VIEW3D_HT_header.remove(draw_checker_overlay_header)
        except Exception:
            pass


CheckerOverlayModule.ensure_overlay_modes()


_draw_overlay_handler = CheckerOverlayModule.draw_overlay_handler
_overlay_realtime_listener = CheckerOverlayModule.overlay_realtime_listener
_overlay_load_handler = persistent(CheckerOverlayModule.overlay_load_handler)


def reg_props():
    CheckerOverlayModule.ensure_overlay_modes()
    CheckerOverlayPreview.register_props()


def ureg_props():
    CheckerOverlayPreview.unregister_props()
    CheckerOverlayCommon.clear_texture_cache()


def drawCheckerOverlayPanel(layout, context):
    CheckerOverlayPreview.draw_panel(layout, context)


def draw_checker_overlay_header(self, context):
    CheckerOverlayPreview.draw_header(self, context)


cls = [
    OP_Hotools_CheckerOverlayRefresh,
    PT_Hotools_CheckerOverlayPopover,
]


def register():
    CheckerOverlayModule.ensure_overlay_modes()

    for cls_item in cls:
        bpy.utils.register_class(cls_item)

    reg_props()

    CheckerOverlayModule.remove_header()
    bpy.types.VIEW3D_HT_header.append(draw_checker_overlay_header)

    if _overlay_load_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_overlay_load_handler)

    context = bpy.context
    if CheckerOverlayCommon.overlay_show_enabled(context):
        CheckerOverlayCommon.sync_runtime_handlers(context)
        CheckerOverlayModule.refresh_draw(context)


def unregister():
    CheckerOverlayModule.remove_header()
    CheckerOverlayCommon.remove_draw_handler()
    CheckerOverlayCommon.remove_realtime_handler()
    CheckerOverlayCommon.clear_overlay_cache()
    CheckerOverlayCommon.clear_texture_cache()

    if _overlay_load_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_overlay_load_handler)

    ureg_props()

    for cls_item in reversed(cls):
        bpy.utils.unregister_class(cls_item)
