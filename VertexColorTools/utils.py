import bpy


def linear_channel_to_srgb(channel):
    if channel <= 0.0031308:
        return 12.92 * channel
    return 1.055 * pow(channel, 1.0 / 2.4) - 0.055


def linear_to_srgb(color):
    return [linear_channel_to_srgb(channel) for channel in color]


def get_active_corner_color_attribute(mesh, create_if_missing=True):
    color_attributes = mesh.color_attributes
    if len(color_attributes) == 0:
        if not create_if_missing:
            return None

        color_attribute = color_attributes.new(
            name="Col",
            type="BYTE_COLOR",
            domain="CORNER",
        )
        color_attributes.active_color_index = len(color_attributes) - 1
        return color_attribute

    color_attribute = color_attributes[color_attributes.active_color_index]
    if color_attribute.domain != "CORNER":
        raise RuntimeError("当前激活的顶点色层不是 Face Corner 类型")
    return color_attribute


def get_active_corner_color_data(mesh, create_if_missing=True):
    color_attribute = get_active_corner_color_attribute(mesh, create_if_missing)
    if color_attribute is None:
        return None
    return color_attribute.data


def get_color_data_value(color_data):
    if hasattr(color_data, "color_srgb"):
        return color_data.color_srgb
    return color_data.color


def write_color_data(color_data, color):
    if hasattr(color_data, "color_srgb"):
        color_data.color_srgb = color
    else:
        color_data.color = color
