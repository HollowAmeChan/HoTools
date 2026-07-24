"""Bent-joint reference frame derived from joint convexity and bone roll."""

from dataclasses import dataclass
from math import atan2, degrees, radians

from mathutils import Quaternion, Vector


@dataclass(frozen=True)
class JointFrame:
    origin: Vector
    x_axis: Vector
    y_axis: Vector
    z_axis: Vector
    bend_angle_degrees: float
    roll_angle_degrees: float
    uses_bend_plane: bool

    def transform_direction(self, local_direction: Vector) -> Vector:
        result = (
            self.x_axis * local_direction.x
            + self.y_axis * local_direction.y
            + self.z_axis * local_direction.z
        )
        return result.normalized()


def _projected_axis(axis, normal):
    projected = axis - normal * axis.dot(normal)
    return projected.normalized() if projected.length > 1e-8 else None


def build_joint_frame(
    parent_bone,
    child_bone,
    *,
    convex_axis="X",
    roll_follow=1.0,
    twist_offset_degrees=0.0,
    straight_threshold_degrees=5.0,
):
    incoming = (parent_bone.tail_local - parent_bone.head_local).normalized()
    outgoing = (child_bone.tail_local - child_bone.head_local).normalized()
    child_basis = child_bone.matrix_local.to_3x3()
    local_x = child_basis @ Vector((1.0, 0.0, 0.0))
    local_z = child_basis @ Vector((0.0, 0.0, 1.0))
    bend_angle = incoming.angle(outgoing)
    bend_normal = incoming.cross(outgoing)
    use_bend = (
        bend_normal.length > 1e-8
        and bend_angle >= radians(straight_threshold_degrees)
    )

    roll_angle = 0.0
    if use_bend:
        bend_normal.normalize()
        convex = outgoing.cross(bend_normal).normalized()
        preferred = local_x if convex_axis == "X" else local_z
        preferred = _projected_axis(preferred, outgoing)
        if preferred is not None and convex.dot(preferred) < 0.0:
            preferred.negate()
        if convex_axis == "X":
            x_axis = convex
            z_axis = x_axis.cross(outgoing).normalized()
            baseline = x_axis
        else:
            z_axis = convex
            x_axis = outgoing.cross(z_axis).normalized()
            baseline = z_axis

        if preferred is not None:
            roll_angle = atan2(
                outgoing.dot(baseline.cross(preferred)),
                baseline.dot(preferred),
            )
            roll_rotation = Quaternion(outgoing, roll_angle * roll_follow)
            x_axis = (roll_rotation @ x_axis).normalized()
            z_axis = (roll_rotation @ z_axis).normalized()
    else:
        x_axis = _projected_axis(local_x, outgoing)
        if x_axis is None:
            x_axis = outgoing.cross(local_z).normalized()
        z_axis = x_axis.cross(outgoing).normalized()
        if z_axis.dot(local_z) < 0.0:
            x_axis.negate()
            z_axis.negate()

    if abs(twist_offset_degrees) > 1e-8:
        rotation = Quaternion(outgoing, radians(twist_offset_degrees))
        x_axis = (rotation @ x_axis).normalized()
        z_axis = (rotation @ z_axis).normalized()

    return JointFrame(
        origin=child_bone.head_local.copy(),
        x_axis=x_axis,
        y_axis=outgoing,
        z_axis=z_axis,
        bend_angle_degrees=degrees(bend_angle),
        roll_angle_degrees=degrees(roll_angle),
        uses_bend_plane=use_bend,
    )
