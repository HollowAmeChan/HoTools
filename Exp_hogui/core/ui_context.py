class UIContext:
    def __init__(self):
        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_x_abs = 0
        self.mouse_y_abs = 0

        self.region_x = 0
        self.region_y = 0

        self.offset_x = 0
        self.offset_y = 0

        self.hovered_id = None
        self.pressed_id = None

        self.last_event_type = ""
        self.last_event_value = ""

        self.active_widget = None

    def begin_frame(self, event):
        if not event:
            return

        self.last_event_type = getattr(event, 'type', "")
        self.last_event_value = getattr(event, 'value', "")

        if hasattr(event, 'mouse_x') and hasattr(event, 'mouse_y'):
            self.mouse_x_abs = event.mouse_x
            self.mouse_y_abs = event.mouse_y
            self.mouse_x = int(self.mouse_x_abs - self.region_x)
            self.mouse_y = int(self.mouse_y_abs - self.region_y)
        elif hasattr(event, 'mouse_region_x') and hasattr(event, 'mouse_region_y'):
            self.mouse_x = event.mouse_region_x
            self.mouse_y = event.mouse_region_y
            self.mouse_x_abs = self.mouse_x + self.region_x
            self.mouse_y_abs = self.mouse_y + self.region_y

    def end_frame(self):
        pass