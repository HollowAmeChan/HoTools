from .ui_context import UIContext
from ..rendering.renderer import UIRenderer

class UIManager:
    def __init__(self):
        self.ctx = UIContext()
        self.renderer = UIRenderer()
        self.root = None

    def set_root(self, root_widget):
        self.root = root_widget

    def draw(self, context):
        if not self.root:
            return

        self.ctx.offset_x = 0
        self.ctx.offset_y = 0
        self.ctx.region_x = getattr(context.region, 'x', 0)
        self.ctx.region_y = getattr(context.region, 'y', 0)

        self.root.draw(self.ctx, self.renderer)

    def handle_event(self, event):
        self.ctx.hovered_id = None
        self.ctx.offset_x = 0
        self.ctx.offset_y = 0
        self.ctx.begin_frame(event)
        consumed = self._dispatch(self.root, event)
        self.ctx.end_frame()
        return consumed
    
    def _dispatch(self, widget, event):
        if not widget:
            return False

        x, y, w, h = widget.rect
        old_x = self.ctx.offset_x
        old_y = self.ctx.offset_y

        self.ctx.offset_x += x
        self.ctx.offset_y += y

        consumed = bool(widget.on_event(self.ctx, event))

        if not consumed:
            for child in widget.children:
                if self._dispatch(child, event):
                    consumed = True
                    break

        self.ctx.offset_x = old_x
        self.ctx.offset_y = old_y
        return consumed