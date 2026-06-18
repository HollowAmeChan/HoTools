"""PropertyCurve 通用曲线预览绘制逻辑。"""

from __future__ import annotations

from .sampling import resolve_color_curve, resolve_float_curve


class PropertyCurveDraw:
    """只负责曲线预览几何；实际 GPU/文字绘制由外部 draw_ops 提供。"""

    @staticmethod
    def draw_curve_segment(draw_ops, curve, index, sx, sy, channel=None, color=(1.0, 1.0, 1.0, 1.0), width=1.0):
        points = curve.points
        if index < 0 or index >= len(points) - 1:
            return

        left = points[index]
        right = points[index + 1]
        x0 = float(left["x"])
        x1 = float(right["x"])
        if x1 < x0:
            return

        segment_interpolation = curve.segment_interpolation(index)
        if channel is None:
            y0 = float(left["y"])
            y1 = float(right["y"])
            sample_value = lambda x: curve.sample(x)
        else:
            y0 = float(left["color"][channel])
            y1 = float(right["color"][channel])
            sample_value = lambda x: curve.sample(x)[channel]

        if segment_interpolation == "CONSTANT":
            draw_ops.draw_polyline([(sx(x0), sy(y0)), (sx(x1), sy(y0))], color, width=width)
            draw_ops.draw_polyline([(sx(x1), sy(y0)), (sx(x1), sy(y1))], color, width=1.0)
            return

        if segment_interpolation == "LINEAR" or abs(x1 - x0) < 0.000001:
            draw_ops.draw_polyline([(sx(x0), sy(y0)), (sx(x1), sy(y1))], color, width=width)
            return

        sample_count = 24
        segment_points = []
        for sample_index in range(sample_count):
            factor = sample_index / float(sample_count - 1)
            x = x0 * (1.0 - factor) + x1 * factor
            segment_points.append((sx(x), sy(sample_value(x))))
        draw_ops.draw_polyline(segment_points, color, width=width)

    @staticmethod
    def draw_curve_handles(draw_ops, curve, sx, sy, channel=None, color=(0.75, 0.82, 0.92, 0.72)):
        points = curve.points
        for index in range(max(0, len(points) - 1)):
            if curve.segment_interpolation(index) != "BEZIER":
                continue

            if channel is None:
                left_value = float(points[index]["y"])
                right_value = float(points[index + 1]["y"])
                handles = curve.segment_handles(index)
            else:
                left_value = float(points[index]["color"][channel])
                right_value = float(points[index + 1]["color"][channel])
                handles = curve.segment_handles(index, channel)
            if not handles:
                continue

            left_handle, right_handle = handles
            left_point = (sx(points[index]["x"]), sy(left_value))
            right_point = (sx(points[index + 1]["x"]), sy(right_value))
            left_handle_point = (sx(left_handle["x"]), sy(left_handle["y"]))
            right_handle_point = (sx(right_handle["x"]), sy(right_handle["y"]))

            draw_ops.draw_polyline([left_point, left_handle_point], color, width=1.0)
            draw_ops.draw_polyline([right_point, right_handle_point], color, width=1.0)
            draw_ops.draw_square(left_handle_point[0], left_handle_point[1], 4, color)
            draw_ops.draw_square(right_handle_point[0], right_handle_point[1], 4, color)

    @staticmethod
    def draw_curve_points(draw_ops, curve, sx, sy, channel=None, color=(1.0, 1.0, 1.0, 1.0)):
        for point in curve.points:
            if channel is None:
                value = point["y"]
            else:
                value = point["color"][channel]
            x = sx(point["x"])
            y = sy(value)
            draw_ops.draw_square(x, y, 7, (0.02, 0.025, 0.032, 0.9))
            draw_ops.draw_square(x, y, 5, color)

    @staticmethod
    def format_axis_value(value):
        value = float(value)
        if abs(value) < 0.000001:
            return "0"
        if abs(value - round(value)) < 0.000001 and abs(value) <= 9:
            return str(int(round(value)))
        return f"{value:.2g}"

    @staticmethod
    def curve_from_payload(payload):
        if not isinstance(payload, dict):
            return None, None
        kind = str(payload.get("kind", ""))
        if kind == "float_curve":
            return resolve_float_curve(payload), "float"
        if kind == "color_curve":
            return resolve_color_curve(payload), "color"
        return None, None

    @staticmethod
    def axis_values(minimum, maximum):
        values = [float(minimum), float(maximum)]
        for value in (-1.0, 0.0, 1.0):
            if minimum <= value <= maximum:
                values.append(value)
        result = []
        for value in values:
            if not any(abs(value - item) < 0.0001 for item in result):
                result.append(value)
        return sorted(result)

    @staticmethod
    def y_bounds(curve, curve_type):
        if curve_type == "color":
            return 0.0, 1.0

        sample_count = 96
        xs = [index / float(sample_count - 1) for index in range(sample_count)]
        sample_values = [curve.sample(x) for x in xs]
        point_values = [point["y"] for point in curve.points]
        y_min = min(sample_values + point_values)
        y_max = max(sample_values + point_values)
        if abs(y_max - y_min) < 0.000001:
            padding = max(abs(y_max) * 0.2, 1.0)
            y_min -= padding
            y_max += padding
        else:
            padding = (y_max - y_min) * 0.08
            y_min -= padding
            y_max += padding
        return y_min, y_max

    @staticmethod
    def draw_axes(draw_ops, rect, plot_rect, y_min, y_max):
        left, bottom, right, _top = rect
        plot_left, plot_bottom, plot_right, plot_top = plot_rect

        def sx(value):
            return plot_left + float(value) * (plot_right - plot_left)

        def sy(value):
            if abs(y_max - y_min) < 0.000001:
                return (plot_bottom + plot_top) * 0.5
            return plot_bottom + (float(value) - y_min) / (y_max - y_min) * (plot_top - plot_bottom)

        grid_color = (0.25, 0.31, 0.39, 0.65)
        axis_color = (0.62, 0.68, 0.76, 0.9)
        label_color = (0.72, 0.78, 0.86, 1.0)
        for x_value in (0.0, 1.0):
            x = sx(x_value)
            draw_ops.draw_polyline([(x, plot_bottom), (x, plot_top)], axis_color, width=1.0)
            draw_ops.draw_label(PropertyCurveDraw.format_axis_value(x_value), x, bottom + 7, label_color, size=9)

        for y_value in PropertyCurveDraw.axis_values(y_min, y_max):
            y = sy(y_value)
            color = axis_color if abs(y_value) < 0.000001 else grid_color
            draw_ops.draw_polyline([(plot_left, y), (plot_right, y)], color, width=1.0)
            draw_ops.draw_label(
                PropertyCurveDraw.format_axis_value(y_value),
                plot_left - 5,
                y - 4,
                label_color,
                size=9,
                align="RIGHT",
            )

        return sx, sy

    @staticmethod
    def draw_color_curve(draw_ops, curve, sx, sy, right, top):
        channels = [
            (0, (1.0, 0.25, 0.22, 1.0), "R"),
            (1, (0.3, 0.95, 0.42, 1.0), "G"),
            (2, (0.32, 0.55, 1.0, 1.0), "B"),
        ]
        for channel, color, _label in channels:
            handle_color = (color[0], color[1], color[2], 0.45)
            PropertyCurveDraw.draw_curve_handles(draw_ops, curve, sx, sy, channel=channel, color=handle_color)
            for point_index in range(len(curve.points) - 1):
                PropertyCurveDraw.draw_curve_segment(
                    draw_ops,
                    curve,
                    point_index,
                    sx,
                    sy,
                    channel=channel,
                    color=color,
                    width=1.8,
                )
            PropertyCurveDraw.draw_curve_points(draw_ops, curve, sx, sy, channel=channel, color=color)
        draw_ops.draw_label("R", right - 39, top - 16, (1.0, 0.25, 0.22, 1.0), size=9)
        draw_ops.draw_label("G", right - 26, top - 16, (0.3, 0.95, 0.42, 1.0), size=9)
        draw_ops.draw_label("B", right - 13, top - 16, (0.32, 0.55, 1.0, 1.0), size=9)

    @staticmethod
    def draw_float_curve(draw_ops, curve, sx, sy):
        curve_color = (0.38, 0.86, 1.0, 1.0)
        PropertyCurveDraw.draw_curve_handles(draw_ops, curve, sx, sy, color=(0.68, 0.84, 0.96, 0.72))
        for point_index in range(len(curve.points) - 1):
            PropertyCurveDraw.draw_curve_segment(
                draw_ops,
                curve,
                point_index,
                sx,
                sy,
                color=curve_color,
                width=2.0,
            )
        PropertyCurveDraw.draw_curve_points(draw_ops, curve, sx, sy, color=curve_color)

    @staticmethod
    def draw_preview(draw_ops, payload, rect, title=""):
        curve, curve_type = PropertyCurveDraw.curve_from_payload(payload)
        if curve is None:
            return

        left, bottom, right, top = rect
        if right - left < 12 or top - bottom < 12:
            return

        draw_ops.draw_rect(left, bottom, right, top, (0.045, 0.052, 0.065, 0.88))
        draw_ops.draw_polyline(
            [(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)],
            (0.35, 0.42, 0.52, 0.95),
            width=1.0,
        )

        pad_left = 34
        pad_right = 12
        pad_top = 22
        pad_bottom = 24
        plot_left = left + pad_left
        plot_right = right - pad_right
        plot_top = top - pad_top
        plot_bottom = bottom + pad_bottom
        y_min, y_max = PropertyCurveDraw.y_bounds(curve, curve_type)
        sx, sy = PropertyCurveDraw.draw_axes(
            draw_ops,
            rect,
            (plot_left, plot_bottom, plot_right, plot_top),
            y_min,
            y_max,
        )

        if curve_type == "color":
            PropertyCurveDraw.draw_color_curve(draw_ops, curve, sx, sy, right, top)
        else:
            PropertyCurveDraw.draw_float_curve(draw_ops, curve, sx, sy)

        preview_title = str(title or "曲线")
        draw_ops.draw_label(preview_title, left + 8, top - 15, (0.88, 0.93, 1.0, 1.0), size=10, align="LEFT")
