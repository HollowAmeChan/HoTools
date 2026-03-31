from .base import Widget

class Table(Widget):
    def __init__(self, id, rect, headers, rows, selected_row=0, on_select=None):
        super().__init__(id, rect)
        self.headers = headers
        self.rows = rows
        self.selected_row = selected_row
        self.on_select = on_select

    def row_height(self):
        return 24

    def total_height(self):
        return self.row_height() * (1 + len(self.rows))

    def on_draw(self, ctx, renderer):
        col_count = len(self.headers)
        if col_count == 0:
            return

        cell_w = self.rect[2] / col_count
        header_rect = (0, 0, self.rect[2], self.row_height())
        renderer.draw_rect(header_rect, (0.16, 0.18, 0.22, 1.0), ctx)
        renderer.draw_rect_outline(header_rect, (0.5, 0.5, 0.5, 1.0), ctx)

        for idx, header in enumerate(self.headers):
            cell_rect = (idx * cell_w, 0, cell_w, self.row_height())
            renderer.draw_text(str(header), cell_rect, ctx, size=12)

        for row_idx, row in enumerate(self.rows):
            y = self.row_height() * (row_idx + 1)
            row_rect = (0, y, self.rect[2], self.row_height())
            bg_color = (0.10, 0.12, 0.16, 1.0)
            if row_idx == self.selected_row:
                bg_color = (0.20, 0.30, 0.55, 1.0)
            elif row_idx % 2 == 0:
                bg_color = (0.12, 0.14, 0.18, 1.0)
            renderer.draw_rect(row_rect, bg_color, ctx)
            renderer.draw_rect_outline(row_rect, (0.35, 0.35, 0.35, 1.0), ctx)

            for col_idx, value in enumerate(row):
                cell_rect = (col_idx * cell_w, y, cell_w, self.row_height())
                renderer.draw_text(str(value), cell_rect, ctx, size=12)

    def on_event(self, ctx, event):
        if event.type != 'LEFTMOUSE' or event.value != 'PRESS':
            return False

        if not self.hit_test(ctx):
            return False

        gx = ctx.offset_x
        gy = ctx.offset_y
        local_x = ctx.mouse_x - gx
        local_y = ctx.mouse_y - gy

        if local_y < self.row_height():
            return False

        row_idx = int((local_y - self.row_height()) / self.row_height())
        if 0 <= row_idx < len(self.rows):
            self.selected_row = row_idx
            if self.on_select:
                self.on_select(self.rows[row_idx], row_idx)
            return True

        return False
