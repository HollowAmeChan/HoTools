"""Module preview controllers built on the shared HoAux viewport renderer."""

from .modules import shoulder_volume
from .preview_draw import PreviewScene, ROLE_LINE_STYLES, ViewportPreview


class ShoulderVolumePreview:
    OWNER_KEY = "SHOULDER_VOLUME"

    @classmethod
    def is_visible(cls):
        return ViewportPreview.is_visible(cls.OWNER_KEY)

    @classmethod
    def show(cls, context):
        obj = context.object
        settings = context.scene.hoaux_settings
        parameters = shoulder_volume.parameters_from_settings(settings)
        plans = shoulder_volume.build_plan(
            obj,
            settings.shoulderBone,
            settings.upperArmBone,
            settings.side,
            parameters,
        )
        upper_arm = obj.data.bones[settings.upperArmBone]
        direction_tail = upper_arm.head_local + (
            upper_arm.tail_local - upper_arm.head_local
        ).normalized() * upper_arm.length * parameters.dir_length_ratio

        scene = PreviewScene(obj.name)
        scene.add_planned_bones(plans)
        scene.add_segment(
            upper_arm.head_local,
            direction_tail,
            ROLE_LINE_STYLES["DIR"],
        )
        scene.add_point(upper_arm.head_local)
        ViewportPreview.show(cls.OWNER_KEY, scene)

    @classmethod
    def refresh(cls, context):
        if not cls.is_visible():
            return
        try:
            cls.show(context)
        except (KeyError, TypeError, ValueError, ReferenceError):
            cls.clear()

    @classmethod
    def clear(cls):
        ViewportPreview.clear(cls.OWNER_KEY)

    @staticmethod
    def shutdown():
        ViewportPreview.clear()
