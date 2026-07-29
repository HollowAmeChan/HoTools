import gpu
from gpu_extras.batch import batch_for_shader


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
