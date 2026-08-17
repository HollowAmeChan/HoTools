import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector


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
