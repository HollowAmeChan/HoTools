from .base import Widget

class Label(Widget):
    def __init__(self, id, rect, text, color=(1.0, 1.0, 1.0, 1.0), size=16):
        super().__init__(id, rect)
        self.text = text
        self.color = color
        self.size = size

    def on_draw(self, ctx, renderer):
        renderer.draw_text(self.text, self.rect, ctx, color=self.color, size=self.size)

    def on_event(self, ctx, event):
        return False
