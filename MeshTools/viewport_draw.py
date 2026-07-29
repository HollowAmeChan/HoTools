import gpu
from gpu_extras.batch import batch_for_shader


_FOREGROUND_COLOR_SHADER = None


def foreground_uniform_color_shader():
    global _FOREGROUND_COLOR_SHADER
    if _FOREGROUND_COLOR_SHADER is not None:
        return _FOREGROUND_COLOR_SHADER

    shader_info = gpu.types.GPUShaderCreateInfo()
    shader_info.vertex_in(0, "VEC3", "pos")
    shader_info.push_constant("MAT4", "view_projection")
    shader_info.push_constant("FLOAT", "depth_scale")
    shader_info.push_constant("VEC4", "color")
    shader_info.fragment_out(0, "VEC4", "FragColor")
    shader_info.vertex_source(
        """
void main()
{
    vec4 clip = view_projection * vec4(pos, 1.0);
    float clip_w = abs(clip.w);
    clip.z = -clip_w + (clip.z + clip_w) * depth_scale;
    gl_Position = clip;
}
"""
    )
    shader_info.fragment_source(
        """
void main()
{
    FragColor = color;
}
"""
    )
    try:
        _FOREGROUND_COLOR_SHADER = gpu.shader.create_from_info(shader_info)
    except Exception:
        return None
    return _FOREGROUND_COLOR_SHADER


def polygon_triangles(polygons):
    coords = []
    for polygon in polygons:
        if len(polygon) < 3:
            continue
        anchor = polygon[0]
        for index in range(1, len(polygon) - 1):
            coords.extend((anchor, polygon[index], polygon[index + 1]))
    return coords


def polygon_lines(polygons):
    coords = []
    for polygon in polygons:
        if len(polygon) < 2:
            continue
        for index, point in enumerate(polygon):
            coords.extend((point, polygon[(index + 1) % len(polygon)]))
    return coords


def draw_segments(shader, coords, color, line_width=1.0):
    if not coords:
        return
    gpu.state.line_width_set(line_width)
    batch = batch_for_shader(shader, 'LINES', {"pos": coords})
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_polygons(
    shader,
    polygons,
    fill_color=None,
    line_color=None,
    line_width=1.0,
):
    if fill_color is not None:
        tri_coords = polygon_triangles(polygons)
        if tri_coords:
            batch = batch_for_shader(shader, 'TRIS', {"pos": tri_coords})
            shader.uniform_float("color", fill_color)
            batch.draw(shader)

    if line_color is not None:
        draw_segments(
            shader,
            polygon_lines(polygons),
            line_color,
            line_width,
        )


def restore_3d_state():
    gpu.state.line_width_set(1.0)
    gpu.state.depth_mask_set(True)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')
