"""Conservative, always-on normalization of the completed FBX element tree.

This operates on encode_bin.FBXElem after compression workers have joined and
before offsets are calculated. It never edits Blender scene data or FBX bytes.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
import math
import struct
import zlib


@dataclass(frozen=True)
class CleanupStats:
    poses_merged: int = 0
    pose_nodes_removed: int = 0
    empty_clusters_removed: int = 0


def _children(element, name):
    return [child for child in element.elems if child.id == name]


def _child(element, name, required=True):
    found = _children(element, name)
    if len(found) != 1:
        if not found and not required:
            return None
        raise ValueError("Missing or ambiguous FBX child %r" % name)
    return found[0]


def _property(element, index, kind):
    if len(element.props_type) <= index or element.props_type[index] != ord(kind):
        raise ValueError("Unexpected FBX property type")
    return bytes(element.props[index])


def _integer(element, index=0, kind="L"):
    return struct.unpack("<" + {"L": "q", "I": "i"}[kind], _property(element, index, kind))[0]


def _string(element, index=0):
    data = _property(element, index, "S")
    if len(data) < 4 or struct.unpack_from("<I", data)[0] != len(data) - 4:
        raise ValueError("Invalid FBX string")
    return data[4:]


def _array(element, kind):
    if len(element.props) != 1:
        raise ValueError("Unexpected FBX array properties")
    data = _property(element, 0, kind)
    count, encoding, size = struct.unpack_from("<III", data)
    if size != len(data) - 12 or encoding not in (0, 1):
        raise ValueError("Invalid FBX array header")
    raw = zlib.decompress(data[12:]) if encoding else data[12:]
    if len(raw) != count * {"d": 8, "i": 4}[kind]:
        raise ValueError("Invalid FBX array size")
    return count, raw


def _matrix(element):
    count, raw = _array(element, "d")
    if count != 16 or not all(math.isfinite(x) for x in struct.unpack("<16d", raw)):
        raise ValueError("Invalid FBX binding matrix")
    return raw


def _kind(element):
    return _string(element, 2) if len(element.props) == 3 else None


def _set_count(element, value):
    if len(element.props) != 1:
        raise ValueError("Unexpected FBX count properties")
    _integer(element, kind="I")
    return element, struct.pack("<i", value)


_READ_ERRORS = (ValueError, IndexError, TypeError, struct.error, zlib.error)


def _pose_record(pose, limb_ids, referenced_ids):
    if _kind(pose) != b"BindPose" or _integer(pose) in referenced_ids:
        return None
    # Only the official global BindPose schema is handled. Preserve other pose
    # formats, local matrices, extra metadata and externally referenced poses.
    if any(child.id not in {b"Type", b"Version", b"NbPoseNodes", b"PoseNode"} for child in pose.elems):
        return None
    if _string(_child(pose, b"Type")) != b"BindPose":
        return None
    version = _integer(_child(pose, b"Version"), kind="I")
    count = _child(pose, b"NbPoseNodes")
    _integer(count, kind="I")
    nodes = {}
    for node in _children(pose, b"PoseNode"):
        if node.props or len(node.elems) != 2:
            return None
        reference = _child(node, b"Node")
        transform = _child(node, b"Matrix")
        if len(reference.props) != 1 or reference.elems or transform.elems:
            return None
        uid = _integer(reference)
        matrix = _matrix(transform)
        if uid in nodes and nodes[uid][1] != matrix:
            return None
        nodes[uid] = (node, matrix)
    # Equal names are not skeleton identity. UUID sets keep separate armatures
    # and partial skeletons apart; shape-only and object poses remain untouched.
    skeleton = frozenset(nodes.keys() & limb_ids)
    if not skeleton:
        return None
    return {"pose": pose, "nodes": nodes, "count": count, "key": (version, skeleton)}


def _plan_poses(objects, by_id, connections):
    referenced = {uid for _, source, target in connections for uid in (source, target)}
    limbs = {uid for uid, obj in by_id.items() if obj.id == b"Model" and _kind(obj) == b"LimbNode"}
    groups = defaultdict(list)
    keepers = []
    removed = set()
    bone_matrices = defaultdict(set)
    original_nodes = 0
    for pose in objects.elems:
        if pose.id != b"Pose":
            continue
        try:
            record = _pose_record(pose, limbs, referenced)
        except _READ_ERRORS:
            continue
        if record is None:
            continue
        original_nodes += len(_children(pose, b"PoseNode"))
        for uid, (_, matrix) in record["nodes"].items():
            bone_matrices[uid].add(matrix)
        for keeper in groups[record["key"]]:
            if all(uid not in keeper["nodes"] or keeper["nodes"][uid][1] == value[1]
                   for uid, value in record["nodes"].items()):
                keeper["nodes"].update(record["nodes"])
                removed.add(_integer(pose))
                break
        else:
            groups[record["key"]].append(record)
            keepers.append(record)
    return keepers, removed, bone_matrices, original_nodes


def _plan_clusters(objects, by_id, connections, bone_matrices):
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for connection in connections:
        kind, source, target = connection
        incoming[target].append(connection)
        outgoing[source].append(connection)
    candidates = defaultdict(set)
    allowed = {b"Version", b"UserData", b"Indexes", b"Weights", b"Transform",
               b"TransformLink", b"TransformAssociateModel"}
    for cluster in objects.elems:
        if cluster.id != b"Deformer":
            continue
        try:
            if _kind(cluster) != b"Cluster" or any(child.id not in allowed for child in cluster.elems):
                continue
            uid = _integer(cluster)
            ins, outs = incoming[uid], outgoing[uid]
            if len(ins) != 1 or len(outs) != 1 or ins[0][0] != b"OO" or outs[0][0] != b"OO":
                continue
            bone_id, skin_id = ins[0][1], outs[0][2]
            skin = by_id.get(skin_id)
            bone = by_id.get(bone_id)
            if (skin is None or skin.id != b"Deformer" or _kind(skin) != b"Skin" or
                    bone is None or bone.id != b"Model" or _kind(bone) != b"LimbNode"):
                continue
            indexes = _child(cluster, b"Indexes", False)
            weights = _child(cluster, b"Weights", False)
            if (indexes is None) != (weights is None):
                continue
            if weights is not None:
                n, raw = _array(weights, "d")
                ni, _ = _array(indexes, "i")
                if ni != n or any(value != 0.0 for (value,) in struct.iter_unpack("<d", raw)):
                    continue
            userdata = _child(cluster, b"UserData")
            if len(userdata.props) != 2 or _string(userdata, 0) or _string(userdata, 1):
                continue
            # Removing a matrix-only cluster must not discard its sole rest-pose
            # source. Conflicting/missing poses and nonstandard clusters survive.
            link = _matrix(_child(cluster, b"TransformLink"))
            _matrix(_child(cluster, b"Transform"))
            _matrix(_child(cluster, b"TransformAssociateModel"))
            if bone_matrices.get(bone_id) != {link}:
                continue
            candidates[skin_id].add(uid)
        except _READ_ERRORS:
            continue
    removed = set()
    for skin_id, empty in candidates.items():
        cluster_ids = {source for kind, source, _ in incoming[skin_id] if kind == b"OO"
                       and source in by_id and by_id[source].id == b"Deformer"
                       and _kind(by_id[source]) == b"Cluster"}
        # Preserve wholly unweighted skins instead of changing renderer type or
        # inventing fallback weights. Every removed cluster has zero influence.
        if cluster_ids - empty:
            removed.update(empty)
    return removed


def _definition_updates(definitions, binding_counts):
    updates = []
    total = _child(definitions, b"Count")
    total_value = _integer(total, kind="I")
    pending = set(binding_counts)
    for entry in _children(definitions, b"ObjectType"):
        kind = _string(entry)
        if kind not in binding_counts:
            continue
        count = _child(entry, b"Count")
        # Upstream counts already omit shape-only poses and can undercount
        # skins in a multi-mesh armature. Count the actual remaining objects.
        value = binding_counts[kind]
        total_value += value - _integer(count, kind="I")
        updates.append(_set_count(count, value))
        pending.discard(kind)
    if pending:
        raise ValueError("Missing FBX ObjectType count")
    if total_value < 0:
        raise ValueError("Invalid FBX Definitions count")
    updates.append(_set_count(total, total_value))
    return updates


def optimize_fbx_tree(root):
    """Normalize supported binding data, leaving ambiguous data unchanged."""
    try:
        objects = _child(root, b"Objects", False)
        if objects is None:
            return CleanupStats()
        relation_root = _child(root, b"Connections")
        by_id = {_integer(obj): obj for obj in objects.elems}
        if len(by_id) != len(objects.elems):
            return CleanupStats()
        relations = []
        for c in relation_root.elems:
            if c.id != b"C" or len(c.props) not in (3, 4):
                return CleanupStats()
            relations.append((_string(c), _integer(c, 1), _integer(c, 2)))
        keepers, poses, matrices, original_nodes = _plan_poses(objects, by_id, relations)
        clusters = _plan_clusters(objects, by_id, relations, matrices)
        removed = poses | clusters
        binding_counts = Counter(obj.id for uid, obj in by_id.items()
                                 if uid not in removed and obj.id in {b"Pose", b"Deformer"})
        updates = _definition_updates(_child(root, b"Definitions"), binding_counts) if removed else []
        # Finish validation before the first mutation, including pose counters.
        for record in keepers:
            updates.append(_set_count(record["count"], len(record["nodes"])))
    except _READ_ERRORS:
        return CleanupStats()

    for record in keepers:
        pose = record["pose"]
        pose.elems[:] = [child for child in pose.elems if child.id != b"PoseNode"]
        pose.elems.extend(node for node, _ in record["nodes"].values())
    if removed:
        objects.elems[:] = [obj for obj in objects.elems if _integer(obj) not in removed]
        relation_root.elems[:] = [c for c, (_, src, dst) in zip(relation_root.elems, relations)
                                 if src not in removed and dst not in removed]
    for element, packed in updates:
        element.props[0] = packed
    stats = CleanupStats(len(poses), original_nodes - sum(len(r["nodes"]) for r in keepers), len(clusters))
    if stats.poses_merged or stats.pose_nodes_removed or stats.empty_clusters_removed:
        print("[HoFBX] BindPose cleanup: merged %d poses, removed %d duplicate pose nodes and %d empty clusters."
              % (stats.poses_merged, stats.pose_nodes_removed, stats.empty_clusters_removed))
    return stats
