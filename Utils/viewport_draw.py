import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector
from math import cos, pi, sin


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


def _rgba(color, alpha):
    return (*color[:3], alpha if len(color) == 3 else color[3] * alpha)


def _draw_uniform_batch(primitive, coords, color, matrix, size=1.0, indices=None):
    if not coords:
        return

    shader_name = 'UNIFORM_COLOR' if primitive == 'POINTS' else 'POLYLINE_UNIFORM_COLOR'
    shader = gpu.shader.from_builtin(shader_name)
    shader.bind()
    shader.uniform_float("color", color)
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    if primitive == 'POINTS':
        gpu.state.point_size_set(size)
    else:
        shader.uniform_float("lineWidth", size)
        shader.uniform_float("viewportSize", gpu.state.scissor_get()[2:])

    batch = batch_for_shader(
        shader,
        primitive,
        {"pos": [matrix @ coord for coord in coords]},
        indices=indices,
    )
    batch.draw(shader)

    gpu.state.point_size_set(1.0)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


def _dispatch_draw(callback, modal, screen=False):
    if modal:
        callback()
        return None
    return bpy.types.SpaceView3D.draw_handler_add(
        callback,
        (),
        'WINDOW',
        'POST_PIXEL' if screen else 'POST_VIEW',
    )


def draw_point(
    co,
    mx=None,
    color=(1.0, 1.0, 1.0),
    size=6,
    alpha=1.0,
    modal=True,
    screen=False,
    **_,
):
    matrix = mx or Matrix.Identity(4)
    return _dispatch_draw(
        lambda: _draw_uniform_batch(
            'POINTS', [co], _rgba(color, alpha), matrix, size=size
        ),
        modal,
        screen,
    )


def draw_points(
    coords,
    mx=None,
    color=(1.0, 1.0, 1.0),
    size=6,
    alpha=1.0,
    modal=True,
    screen=False,
    **_,
):
    matrix = mx or Matrix.Identity(4)
    return _dispatch_draw(
        lambda: _draw_uniform_batch(
            'POINTS', coords, _rgba(color, alpha), matrix, size=size
        ),
        modal,
        screen,
    )


def draw_line(
    coords,
    mx=None,
    color=(1.0, 1.0, 1.0),
    width=1,
    alpha=1.0,
    modal=True,
    screen=False,
    **_,
):
    matrix = mx or Matrix.Identity(4)
    indices = [(index, index + 1) for index in range(len(coords) - 1)]
    return _dispatch_draw(
        lambda: _draw_uniform_batch(
            'LINES', coords, _rgba(color, alpha), matrix, size=width, indices=indices
        ),
        modal,
        screen,
    )


def draw_lines(
    coords,
    mx=None,
    color=(1.0, 1.0, 1.0),
    width=1,
    alpha=1.0,
    modal=True,
    screen=False,
    **_,
):
    matrix = mx or Matrix.Identity(4)
    indices = [(index, index + 1) for index in range(0, len(coords) - 1, 2)]
    return _dispatch_draw(
        lambda: _draw_uniform_batch(
            'LINES', coords, _rgba(color, alpha), matrix, size=width, indices=indices
        ),
        modal,
        screen,
    )


def draw_vector(vector, origin=None, mx=None, **kwargs):
    start = origin or Vector()
    return draw_line([start, start + vector], mx=mx, **kwargs)


def draw_circle(center, radius, color=(1.0, 1.0, 1.0), width=2.0,
                alpha=1.0, segments=64, screen=True, modal=True):
    """Draw a circle in region or world coordinates using the shared line path."""
    center = Vector(center)
    coords = [
        Vector((center.x + cos(2 * pi * index / segments) * radius,
                center.y + sin(2 * pi * index / segments) * radius,
                center.z if len(center) > 2 else 0.0))
        for index in range(segments + 1)
    ]
    return draw_line(
        coords,
        color=color,
        width=width,
        alpha=alpha,
        screen=screen,
        modal=modal,
    )


def draw_mesh_wire(
    batch,
    color=(1.0, 1.0, 1.0),
    width=1.0,
    alpha=1.0,
    modal=True,
):
    """Draw a ``(coordinates, edge_indices)`` mesh preview batch."""
    coords, indices = batch
    if len(coords) == 0 or len(indices) == 0:
        return None
    matrix = Matrix.Identity(4)
    return _dispatch_draw(
        lambda: _draw_uniform_batch(
            'LINES',
            coords,
            _rgba(color, alpha),
            matrix,
            size=width,
            indices=indices,
        ),
        modal,
    )
