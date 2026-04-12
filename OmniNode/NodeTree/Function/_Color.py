import colorsys
@staticmethod
def hsv2rgb(h, s, v):
    return colorsys.hsv_to_rgb(h, s, v)

colorCat = {
    "GetData": hsv2rgb(0, 0, 0.3),
    "Operator": hsv2rgb(0.05, 0.35, 0.3),
    "Math": hsv2rgb(0.58, 0.35, 0.3),
    "ComplexMath": hsv2rgb(0.55, 0.35, 0.3),
    "Logic": hsv2rgb(0.15, 0.35, 0.3),
}
