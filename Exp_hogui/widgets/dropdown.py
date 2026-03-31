from .base import Widget

class Dropdown(Widget):
    def __init__(self, id, rect, label, options, selected_index=0, on_select=None):
        super().__init__(id, rect)
        self.label = label
        self.options = options
        self.selected_index = selected_index
        self.on_select = on_select
        self.open = False

    def option_height(self):
        return 26

    def total_height(self):
        if self.open:
            return self.rect[3] + len(self.options) * self.option_height()
        return self.rect[3]

    def hit_test(self, ctx):
        if not self.enabled:
            return False
        x, y, w, h = self.rect
        h = self.total_height()
        gx = ctx.offset_x
        gy = ctx.offset_y
        return (gx <= ctx.mouse_x <= gx + w and
                gy <= ctx.mouse_y <= gy + h)

    def on_draw(self, ctx, renderer):
        renderer.draw_text(self.label, (0, 0, self.rect[2], 18), ctx, size=14)
        base_rect = (0, 22, self.rect[2], 30)
        renderer.draw_rect(base_rect, (0.16, 0.18, 0.22, 1.0), ctx)
        renderer.draw_rect_outline(base_rect, (0.6, 0.6, 0.6, 1.0), ctx)

        selected_text = self.options[self.selected_index]
        renderer.draw_text(selected_text, base_rect, ctx, size=12)
        renderer.draw_text("▼", (self.rect[2] - 22, 24, 20, 20), ctx)

        if self.open:
            for idx, option in enumerate(self.options):
                option_rect = (0, 22 + (idx + 1) * self.option_height(), self.rect[2], self.option_height())
                fill = (0.12, 0.14, 0.18, 1.0)
                if idx == self.selected_index:
                    fill = (0.20, 0.24, 0.30, 1.0)
                renderer.draw_rect(option_rect, fill, ctx)
                renderer.draw_rect_outline(option_rect, (0.4, 0.4, 0.4, 1.0), ctx)
                renderer.draw_text(option, option_rect, ctx, size=12)

    def on_event(self, ctx, event):
        if event.type != 'LEFTMOUSE' or event.value != 'PRESS':
            return False

        gx = ctx.offset_x
        gy = ctx.offset_y
        local_x = ctx.mouse_x - gx
        local_y = ctx.mouse_y - gy

        box = (0, 22, self.rect[2], 30)
        if (box[0] <= local_x <= box[0] + box[2] and
                box[1] <= local_y <= box[1] + box[3]):
            self.open = not self.open
            return True

        if self.open:
            for idx in range(len(self.options)):
                option_rect = (0, 22 + (idx + 1) * self.option_height(), self.rect[2], self.option_height())
                if (option_rect[0] <= local_x <= option_rect[0] + option_rect[2] and
                        option_rect[1] <= local_y <= option_rect[1] + option_rect[3]):
                    self.selected_index = idx
                    self.open = False
                    if self.on_select:
                        self.on_select(self.options[idx])
                    return True

        return False
