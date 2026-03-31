from .base import Widget

class MenuList(Widget):
    def __init__(self, id, rect, title, items, on_select=None):
        super().__init__(id, rect)
        self.title = title
        self.items = items
        self.on_select = on_select
        self.selected_index = None

    def item_height(self):
        return 26

    def on_draw(self, ctx, renderer):
        header_rect = (0, 0, self.rect[2], 24)
        renderer.draw_rect(header_rect, (0.16, 0.18, 0.22, 1.0), ctx)
        renderer.draw_rect_outline(header_rect, (0.5, 0.5, 0.5, 1.0), ctx)
        renderer.draw_text(self.title, header_rect, ctx, size=14)

        for idx, item in enumerate(self.items):
            y = 24 + idx * self.item_height()
            item_rect = (0, y, self.rect[2], self.item_height())
            color = (0.10, 0.12, 0.16, 1.0)
            if self.selected_index == idx:
                color = (0.23, 0.40, 0.70, 1.0)
            renderer.draw_rect(item_rect, color, ctx)
            renderer.draw_rect_outline(item_rect, (0.4, 0.4, 0.4, 1.0), ctx)
            renderer.draw_text(item, item_rect, ctx, size=12)

    def on_event(self, ctx, event):
        if event.type != 'LEFTMOUSE' or event.value != 'PRESS':
            return False

        gx = ctx.offset_x
        gy = ctx.offset_y
        local_x = ctx.mouse_x - gx
        local_y = ctx.mouse_y - gy

        if not self.hit_test(ctx):
            return False

        for idx, item in enumerate(self.items):
            y = 24 + idx * self.item_height()
            if 0 <= local_x <= self.rect[2] and y <= local_y <= y + self.item_height():
                self.selected_index = idx
                if self.on_select:
                    self.on_select(item)
                return True

        return False
