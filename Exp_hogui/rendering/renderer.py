import gpu
from gpu_extras.batch import batch_for_shader
import blf

class UIRenderer:
    def __init__(self):
        self.shader = gpu.shader.from_builtin('UNIFORM_COLOR')

    def draw_rect(self, rect, color, ctx):
        x, y, w, h = rect

        x += ctx.offset_x
        y += ctx.offset_y

        verts = [(x, y), (x+w, y), (x+w, y+h), (x, y+h)]

        batch = batch_for_shader(self.shader, 'TRI_FAN', {"pos": verts})

        self.shader.bind()
        self.shader.uniform_float("color", color)
        batch.draw(self.shader)


    def draw_text(self, text, rect, ctx, color=(1.0, 1.0, 1.0, 1.0), size=16):
        x, y, w, h = rect

        x += ctx.offset_x
        y += ctx.offset_y

        blf.size(0, size)
        blf.color(0, *color)
        blf.position(0, x + 10, y + 10, 0)
        blf.draw(0, text)

    def draw_text_abs(self, text, x, y, color=(1.0, 1.0, 1.0, 1.0)):
        blf.size(0, 14)
        blf.color(0, *color)
        blf.position(0, x, y, 0)
        blf.draw(0, text)

    def draw_crosshair(self, pos, color=(1.0, 0.3, 0.1, 1.0), size=6):
        x, y = pos
        verts = [
            (x - size, y),
            (x + size, y),
            (x, y),
            (x, y - size),
            (x, y + size),
        ]
        batch = batch_for_shader(self.shader, 'LINE_STRIP', {"pos": verts})
        self.shader.bind()
        self.shader.uniform_float("color", color)
        batch.draw(self.shader)

    def draw_rect_outline(self, rect, color, ctx, thickness=1):
        x, y, w, h = rect
        x += ctx.offset_x
        y += ctx.offset_y
        verts = [
            (x, y),
            (x + w, y),
            (x + w, y + h),
            (x, y + h),
            (x, y),
        ]
        batch = batch_for_shader(self.shader, 'LINE_STRIP', {"pos": verts})
        self.shader.bind()
        self.shader.uniform_float("color", color)
        batch.draw(self.shader)

    def draw_background(self, region, color=(0.08, 0.09, 0.11, 1.0)):
        verts = [
            (0, 0),
            (region.width, 0),
            (region.width, region.height),
            (0, region.height)
        ]

        batch = batch_for_shader(self.shader, 'TRI_FAN', {"pos": verts})

        self.shader.bind()
        self.shader.uniform_float("color", color)
        batch.draw(self.shader)