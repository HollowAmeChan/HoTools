from .base import Widget

class Frame(Widget):
    def __init__(self, id, rect, title=None):
        super().__init__(id, rect)
        self.title = title

    def on_draw(self, ctx, renderer):
        renderer.draw_rect(self.rect, (0.08, 0.10, 0.14, 0.95), ctx)
        renderer.draw_rect_outline(self.rect, (0.46, 0.52, 0.62, 1.0), ctx)
        if self.title:
            renderer.draw_text(self.title, (10, 10, self.rect[2] - 20, 24), ctx, size=14)
