from .base import Widget

class Button(Widget):
    def __init__(self, id, rect, text, on_click=None):
        super().__init__(id, rect)
        self.text = text
        self.on_click = on_click

    def on_draw(self, ctx, renderer):
        color = (0.24, 0.28, 0.36, 1.0)

        if self.hovered:
            color = (0.3, 0.6, 0.9, 1.0)
        if self.pressed:
            color = (0.1, 0.3, 0.6, 1.0)

        renderer.draw_rect(self.rect, color, ctx)
        renderer.draw_text(self.text, self.rect, ctx)

    def on_event(self, ctx, event):
        hit = self.hit_test(ctx)

        if hit:
            ctx.hovered_id = self.id

            if event.type == 'LEFTMOUSE':
                if event.value == 'PRESS':
                    ctx.pressed_id = self.id
                    if self.on_click:
                        self.on_click()
                    return True
                elif event.value == 'RELEASE':
                    if ctx.pressed_id == self.id:
                        ctx.pressed_id = None
                    return True

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE' and ctx.pressed_id == self.id:
            ctx.pressed_id = None
            return True

        return False