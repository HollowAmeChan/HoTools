"""Armature-local symmetry domains for ordinary auxiliary weight transfers."""

EPSILON = 1e-6


def _points(bone):
    if hasattr(bone, "head_local"):
        return bone.head_local, bone.tail_local
    return bone.head, bone.tail


def _sign(value):
    return 1 if value > EPSILON else -1 if value < -EPSILON else 0


def bone_side(bone):
    """Geometric side, independent of names and object/world transforms."""
    head, tail = _points(bone)
    return _sign((head.x + tail.x) * 0.5)


def frame_side(frame):
    side = _sign(frame["joint"].x)
    # A limb may start on the mirror plane; a genuinely central spine stays 0.
    return side or bone_side(frame["child_bone"])


def local_x_coordinates(obj, armature):
    mesh_to_armature = armature.matrix_world.inverted() @ obj.matrix_world
    return [(mesh_to_armature @ vertex.co).x for vertex in obj.data.vertices]


def side_mask(coordinates, side, include_midplane=False):
    if side == 0:
        return [True] * len(coordinates)
    if include_midplane:
        return [side * x >= -EPSILON for x in coordinates]
    # Independent transfers leave center vertices in their original source.
    return [side * x > EPSILON for x in coordinates]


def restrict_adjacency(adjacency, mask):
    return [[neighbor for neighbor in row if mask[neighbor]] if mask[index] else []
            for index, row in enumerate(adjacency)]


def blur_buffers(buffers, sides, coordinates, adjacency, region, iterations,
                 strength, include_midplane=False):
    """Blur each buffer inside its own domain, including neighbor sampling.

    Buffers are independent, so updating one full buffer at a time retains the
    simultaneous Laplacian result without letting a center vertex bridge sides.
    Source buffers spanning both sides use side 0; fan buffers use their site.
    """
    domains = {}
    for side in set(sides):
        mask = side_mask(coordinates, side, include_midplane)
        domains[side] = (mask, adjacency if side == 0 else restrict_adjacency(adjacency, mask))
    for buffer, side in zip(buffers, sides):
        mask, neighbors = domains[side]
        active = [i for i in region if mask[i] and neighbors[i]]
        for _ in range(iterations):
            updates = []
            for i in active:
                row = neighbors[i]
                average = 0.0
                for neighbor in row:
                    average += buffer[neighbor]
                average *= 1.0 / len(row)
                updates.append((i, buffer[i] + strength * (average - buffer[i])))
            for i, value in updates:
                buffer[i] = value
