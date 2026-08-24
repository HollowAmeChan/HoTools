"""Object-level lattice creation operator."""

import math

import bpy
from bpy.props import IntVectorProperty
from bpy.types import Operator
from mathutils import Matrix, Vector


class HO_OT_QuickAddLattice(Operator):
    """Add a lattice modifier to the selected objects."""

    bl_idname = "ho.quick_add_lattice"
    bl_label = "快速添加晶格"
    bl_description = "单物体使用本地包围盒，多物体使用全局整体包围盒"
    bl_options = {"REGISTER", "UNDO"}

    resolution: IntVectorProperty(
        name="晶格分辨率",
        description="晶格在 U、V、W 三个方向上的控制点数量",
        size=3,
        default=(2, 2, 2),
        min=2,
        max=64,
        options={"SKIP_SAVE"},
    ) # type: ignore
    _OBJECT_TYPES = {"LATTICE", "MESH", "CURVE", "FONT", "SURFACE", "GREASEPENCIL", "GPENCIL"}
    _GREASE_PENCIL_TYPES = {"GREASEPENCIL", "GPENCIL"}

    @classmethod
    def _selected_objects(cls, context):
        if getattr(context, "mode", None) != "OBJECT":
            return []
        return [obj for obj in getattr(context, "selected_objects", ())
                if getattr(obj, "type", None) in cls._OBJECT_TYPES]

    @staticmethod
    def _object_points(obj):
        bound_box = getattr(obj, "bound_box", ())
        if not bound_box:
            return []
        try:
            points = [obj.matrix_world @ Vector(corner) for corner in bound_box]
        except (AttributeError, TypeError, ValueError):
            return []
        if not all(math.isfinite(float(value)) for point in points for value in point):
            return []
        return points

    @classmethod
    def _bounds(cls, objects, rotation):
        inverse_rotation = rotation.to_matrix().transposed()
        points = [inverse_rotation @ point for obj in objects for point in cls._object_points(obj)]
        if not points:
            return None
        minimum = Vector(tuple(min(point[index] for point in points) for index in range(3)))
        maximum = Vector(tuple(max(point[index] for point in points) for index in range(3)))
        center = (minimum + maximum) * 0.5
        extent = Vector(tuple(value if abs(value) > 1.0e-8 else 0.1
                              for value in (maximum - minimum)))
        return center, extent

    @staticmethod
    def _link_object(context, lattice_object):
        collection = getattr(context, "collection", None)
        if collection is None:
            collection = getattr(getattr(context, "scene", None), "collection", None)
        if collection is None:
            return False
        collection.objects.link(lattice_object)
        return True

    @staticmethod
    def _set_parent(obj, lattice_object):
        world_matrix = obj.matrix_world.copy()
        obj.parent = lattice_object
        obj.matrix_parent_inverse = lattice_object.matrix_world.inverted()
        obj.matrix_world = world_matrix

    @classmethod
    def _add_modifier(cls, obj, lattice_object, name):
        try:
            if getattr(obj, "type", None) in cls._GREASE_PENCIL_TYPES:
                collection = getattr(obj, "grease_pencil_modifiers", None)
                if collection is not None:
                    try:
                        modifier = collection.new(name=name, type="GP_LATTICE")
                    except (RuntimeError, TypeError, ValueError):
                        modifier = obj.modifiers.new(name=name, type="GREASE_PENCIL_LATTICE")
                else:
                    modifier = obj.modifiers.new(name=name, type="GREASE_PENCIL_LATTICE")
            else:
                modifier = obj.modifiers.new(name=name, type="LATTICE")
            modifier.object = lattice_object
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None
        return modifier

    def _create(self, context, objects, rotation, name):
        bounds = self._bounds(objects, rotation)
        if bounds is None:
            return None, 0
        center, extent = bounds
        lattice_data = bpy.data.lattices.new(name=f"{name}_LP")
        lattice_object = bpy.data.objects.new(name=lattice_data.name, object_data=lattice_data)
        if not self._link_object(context, lattice_object):
            bpy.data.objects.remove(lattice_object, do_unlink=True)
            bpy.data.lattices.remove(lattice_data)
            return None, 0
        lattice_object.rotation_mode = "QUATERNION"
        lattice_object.rotation_quaternion = rotation
        lattice_object.location = rotation @ center
        lattice_object.scale = extent
        lattice_data.points_u, lattice_data.points_v, lattice_data.points_w = self.resolution
        lattice_data.interpolation_type_u = "KEY_LINEAR"
        lattice_data.interpolation_type_v = "KEY_LINEAR"
        lattice_data.interpolation_type_w = "KEY_LINEAR"
        if getattr(context, "view_layer", None) is not None:
            context.view_layer.update()
        attached = 0
        for index, obj in enumerate(objects, start=1):
            modifier = self._add_modifier(obj, lattice_object, name=f"Ho Lattice {index}")
            if modifier is None:
                continue
            try:
                self._set_parent(obj, lattice_object)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            attached += 1
        if attached == 0:
            bpy.data.objects.remove(lattice_object, do_unlink=True)
            if lattice_data.users == 0:
                bpy.data.lattices.remove(lattice_data)
            return None, 0
        return lattice_object, attached

    @classmethod
    def poll(cls, context):
        return bool(cls._selected_objects(context))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        objects = self._selected_objects(context)
        if not objects:
            self.report({"ERROR"}, "请在物体模式下选择可添加晶格的物体")
            return {"CANCELLED"}
        rotation = objects[0].matrix_world.to_quaternion() if len(objects) == 1 else Matrix.Identity(3).to_quaternion()
        name = f"HoLattice_{objects[0].name}" if len(objects) == 1 else "HoLattice_Group"
        lattice_object, attached = self._create(context, objects, rotation, name)
        if lattice_object is None:
            self.report({"ERROR"}, "没有物体可以添加晶格修改器")
            return {"CANCELLED"}
        self.report({"INFO"}, f"已添加晶格，影响 {attached} 个物体")
        return {"FINISHED"}

    def draw(self, context):
        self.layout.prop(self, "resolution", text="分辨率")


class HO_MT_HoObjectTools(bpy.types.Menu):
    bl_idname = "HO_MT_HoObjectTools"
    bl_label = "HoObjectTools"

    @classmethod
    def poll(cls, context):
        mode = getattr(context, "mode", None)
        if mode == "OBJECT":
            return True
        active = getattr(context, "active_object", None)
        return mode == "EDIT_MESH" and getattr(active, "type", None) == "MESH"

    def draw(self, context):
        if context.mode == "OBJECT":
            layout = self.layout
            layout.operator_context = "INVOKE_REGION_WIN"
            layout.operator("ho.auto_place_object_bottom", icon="SNAP_FACE")
            layout.operator("ho.auto_snap_face_orthogonal", icon="ORIENTATION_GLOBAL")
            layout.separator()
            layout.operator_context = "INVOKE_DEFAULT"
            layout.operator(
                HO_OT_QuickAddLattice.bl_idname,
                text="快速添加晶格",
                icon="MOD_LATTICE",
            )
            return

        layout = self.layout
        layout.operator_context = "EXEC_DEFAULT"
        layout.operator("ho.placeobjectbottom", icon="TRIA_DOWN")
        layout.operator("ho.snap_selected_face_orthogonal", icon="ORIENTATION_GLOBAL")
