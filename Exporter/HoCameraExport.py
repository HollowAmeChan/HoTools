"""Export a Blender camera as a versioned HoCamera JSON asset.

The exporter samples evaluated dependency-graph transforms so parent objects,
constraints, drivers, and NLA evaluation are baked into the camera track. The
file stores Unity-space values because the Unity importer is intentionally a
small data importer rather than a Blender compatibility layer.
"""

import json
import math
import traceback

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper
from mathutils import Matrix


_AXIS_CONVERSION = Matrix((
    (1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0),
    (0.0, 1.0, 0.0),
))
# Blender cameras use local -Z as forward; HoCamera stores the corresponding
# Unity camera basis after the explicit axis conversion below.
_BLENDER_CAMERA_BASIS = Matrix.Diagonal((-1.0, 1.0, -1.0))


def _vector(value):
    return {"x": float(value.x), "y": float(value.y), "z": float(value.z)}


def _quaternion(value):
    # Unity's JSON reader accepts the same x/y/z/w quaternion field names.
    return {"x": float(value.x), "y": float(value.y), "z": float(value.z), "w": float(value.w)}


def _unity_transform(matrix):
    """Convert Blender's Z-up camera transform to Unity's Y-up basis.

    The position changes with ``C*p``. Camera local bases differ as well:
    Blender uses right/up/back while Unity uses right/up/forward, so the
    rotation is ``C*R*B`` where ``B`` converts Blender's camera-local basis
    to the basis used by the Unity component.
    """
    position = _AXIS_CONVERSION @ matrix.to_translation()
    rotation = (_AXIS_CONVERSION @ matrix.to_3x3() @ _BLENDER_CAMERA_BASIS).to_quaternion()
    return position, rotation


def _unit_scale(scene):
    value = getattr(getattr(scene, "unit_settings", None), "scale_length", 0.0)
    return float(value) if value and value > 0.0 else 1.0


def _render_aspect(scene):
    render = scene.render
    width = max(1.0, float(render.resolution_x) * float(render.pixel_aspect_x))
    height = max(1.0, float(render.resolution_y) * float(render.pixel_aspect_y))
    return width, height


def _frame_sample(scene, camera, depsgraph, frame, unit_scale):
    scene.frame_set(frame)
    depsgraph.update()
    evaluated = camera.evaluated_get(depsgraph)
    matrix = evaluated.matrix_world.copy()
    position, rotation = _unity_transform(matrix)
    position *= unit_scale
    data = evaluated.data
    orthographic = data.type == "ORTHO"
    width, height = _render_aspect(scene)
    # Camera.angle_y is Blender's vertical camera angle and maps directly to
    # Unity Camera.fieldOfView, which is also vertical.
    fov_y = math.degrees(float(data.angle_y))
    return {
        "frame": int(frame),
        "position": _vector(position),
        "rotation": _quaternion(rotation),
        "orthographic": bool(orthographic),
        "fieldOfView": fov_y,
        "fovY": fov_y,
        "focalLength": float(data.lens),
        # Blender's ortho_scale is the horizontal frame span; Unity's
        # orthographicSize is the vertical half-span.
        "orthographicSize": float(data.ortho_scale) * unit_scale * height / width * 0.5,
        "nearClipPlane": float(data.clip_start) * unit_scale,
        "farClipPlane": float(data.clip_end) * unit_scale,
        "lensShift": {"x": float(data.shift_x), "y": float(data.shift_y)},
    }


def build_hocamera(scene, camera, depsgraph=None):
    if camera is None or camera.type != "CAMERA":
        raise ValueError("HoCamera 需要一个摄像机对象")
    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    first = int(scene.frame_start)
    last = int(scene.frame_end)
    unit_scale = _unit_scale(scene)
    render = scene.render
    fps_base = float(render.fps_base) if render.fps_base else 1.0
    fps = float(render.fps) / fps_base
    width, height = _render_aspect(scene)
    samples = []
    original_frame = scene.frame_current
    try:
        for frame in range(first, last + 1):
            samples.append(_frame_sample(scene, camera, depsgraph, frame, unit_scale))
    finally:
        scene.frame_set(original_frame)
        depsgraph.update()
    if not samples:
        raise ValueError("场景没有可导出的帧范围")
    return {
        "schema": "HoCamera",
        "version": "1.0",
    "coordinateSystem": "unity-x-right-y-up-z-forward",
        "unit": "meter",
        "sourceCamera": camera.name,
        "projection": "orthographic" if camera.data.type == "ORTHO" else "perspective",
        "frameRate": fps,
        "startFrame": first,
        "endFrame": last,
        "resolution": {
            "width": int(render.resolution_x),
            "height": int(render.resolution_y),
            "pixelAspect": float(render.pixel_aspect_x) / max(1e-9, float(render.pixel_aspect_y)),
        },
        "camera": samples[0],
        "frames": samples,
    }


class OP_HoCameraExport(Operator, ExportHelper):
    bl_idname = "ho.camera_export"
    bl_label = "HoCamera(.hocamera)"
    bl_description = "按场景帧范围烘焙当前场景摄像机并导出 HoCamera JSON"
    bl_options = {"PRESET"}

    filename_ext = ".hocamera"
    filter_glob: StringProperty(default="*.hocamera", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.scene.camera is not None

    def execute(self, context):
        camera = context.scene.camera
        try:
            payload = build_hocamera(context.scene, camera, context.evaluated_depsgraph_get())
            with open(self.filepath, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, f"HoCamera 导出失败：{exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"HoCamera 已导出 {len(payload['frames'])} 帧")
        return {"FINISHED"}


def menu_export(self, context):
    self.layout.operator_context = "INVOKE_DEFAULT"
    self.layout.operator(OP_HoCameraExport.bl_idname, text="HoCamera(.hocamera)")


def register():
    bpy.utils.register_class(OP_HoCameraExport)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    bpy.utils.unregister_class(OP_HoCameraExport)
