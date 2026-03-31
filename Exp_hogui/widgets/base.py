class Widget:
    def __init__(self, id, rect):
        self.id = id
        self.rect = rect  # (x, y, w, h)
        self.children = []
        self.hovered = False
        self.pressed = False
        self.enabled = True

    def refresh_state(self, ctx):
        self.hovered = getattr(ctx, 'hovered_id', None) == self.id
        self.pressed = getattr(ctx, 'pressed_id', None) == self.id

    def draw(self, ctx, renderer):
        self.refresh_state(ctx)

        x, y, w, h = self.rect

        old_x = ctx.offset_x
        old_y = ctx.offset_y

        ctx.offset_x += x
        ctx.offset_y += y

        self.on_draw(ctx, renderer)

        for child in self.children:
            child.draw(ctx, renderer)

        ctx.offset_x = old_x
        ctx.offset_y = old_y

    def on_draw(self, ctx, renderer):
        pass

    def hit_test(self, ctx):
        if not self.enabled:
            return False

        x, y, w, h = self.rect

        gx = ctx.offset_x
        gy = ctx.offset_y

        return (gx <= ctx.mouse_x <= gx + w and
                gy <= ctx.mouse_y <= gy + h)

    def on_event(self, ctx, event):
        hit = self.hit_test(ctx)
        if hit:
            ctx.hovered_id = self.id

        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS' and hit:
                ctx.pressed_id = self.id
            elif event.value == 'RELEASE' and ctx.pressed_id == self.id:
                ctx.pressed_id = None

        return False

    def add(self, widget):
        self.children.append(widget)