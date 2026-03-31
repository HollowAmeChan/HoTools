from .base import Widget

class ColorPicker(Widget):
    def __init__(self, id, rect, label, color=(0.35, 0.55, 0.85, 1.0), swatches=None, on_change=None):
        super().__init__(id, rect)
        self.label = label
        self.color = color
        self.on_change = on_change
        self.open = False
        self.swatches = swatches or [
            (0.94, 0.26, 0.21, 1.0),
            (0.20, 0.60, 0.86, 1.0),
            (0.18, 0.80, 0.44, 1.0),
            (0.98, 0.77, 0.18, 1.0),
            (0.60, 0.40, 0.80, 1.0),
            (0.90, 0.30, 0.70, 1.0),
        ]

    def preview_rect(self):
        return (0, 26, 56, 32)

    def swatch_rects(self):
        swatch_w = 32
        swatch_h = 28
        margin = 8
        rects = []
        x = 0
        y = 72
        for idx, _ in enumerate(self.swatches):
            rects.append((x, y, swatch_w, swatch_h))
            x += swatch_w + margin
            if x + swatch_w > self.rect[2]:
                x = 0
                y += swatch_h + margin
        return rects

    def hit_test(self, ctx):
        if not self.enabled:
            return False
        x, y, w, h = self.rect
        extra_height = 0
        if self.open:
            extra_height = 72
        gx = ctx.offset_x
        gy = ctx.offset_y
        return (gx <= ctx.mouse_x <= gx + w and
                gy <= ctx.mouse_y <= gy + h + extra_height)

    def on_draw(self, ctx, renderer):
        renderer.draw_text(self.label, (0, 0, self.rect[2], 20), ctx, size=14)
        renderer.draw_rect(self.preview_rect(), self.color, ctx)
        renderer.draw_rect_outline(self.preview_rect(), (1.0, 1.0, 1.0, 1.0), ctx)
        renderer.draw_text("点击选择颜色", (68, 30, 0, 0), ctx, size=12)

        if self.open:
            renderer.draw_rect((0, 68, self.rect[2], 84), (0.10, 0.12, 0.16, 0.98), ctx)
            renderer.draw_rect_outline((0, 68, self.rect[2], 84), (0.5, 0.5, 0.5, 1.0), ctx)
            for idx, rect in enumerate(self.swatch_rects()):
                renderer.draw_rect(rect, self.swatches[idx], ctx)
                renderer.draw_rect_outline(rect, (1.0, 1.0, 1.0, 0.5), ctx)

    def on_event(self, ctx, event):
        if event.type != 'LEFTMOUSE' or event.value != 'PRESS':
            return False

        gx = ctx.offset_x
        gy = ctx.offset_y
        local_x = ctx.mouse_x - gx
        local_y = ctx.mouse_y - gy

        preview = self.preview_rect()
        if (preview[0] <= local_x <= preview[0] + preview[2] and
                preview[1] <= local_y <= preview[1] + preview[3]):
            self.open = not self.open
            return True

        if self.open:
            for idx, rect in enumerate(self.swatch_rects()):
                if (rect[0] <= local_x <= rect[0] + rect[2] and
                        rect[1] <= local_y <= rect[1] + rect[3]):
                    self.color = self.swatches[idx]
                    self.open = False
                    if self.on_change:
                        self.on_change(self.color)
                    return True

        return False
