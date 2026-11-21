"""Binding normalization contracts using the actual private FBX encoder."""

import importlib
import importlib.util
from pathlib import Path
import struct
import sys
import unittest


PACKAGE = Path(__file__).resolve().parents[1] / "Exporter" / "FbxExporter"


def load(name, path, package=False):
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(path.parent)] if package else None,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


load("hofbx_test_vendor", PACKAGE / "_vendor" / "__init__.py", True)
encoder = importlib.import_module("hofbx_test_vendor.encode_bin")
cleanup = load("hofbx_test_cleanup", PACKAGE / "cleanup.py")


def element(name, *properties, children=()):
    result = encoder.FBXElem(name)
    methods = {"L": "add_int64", "I": "add_int32", "S": "add_string",
               "d": "add_float64_array", "i": "add_int32_array"}
    for kind, value in properties:
        getattr(result, methods[kind])(value)
    result.elems.extend(children)
    return result


def child(parent, name):
    return next(c for c in parent.elems if c.id == name)


def matrix(offset=0.0):
    return [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0, float(offset), 0.0, 0.0, 1.0]


def pose_node(uid, offset=None):
    return element(b"PoseNode", children=[
        element(b"Node", ("L", uid)),
        element(b"Matrix", ("d", matrix(uid if offset is None else offset))),
    ])


def pose(uid, node_ids):
    return element(b"Pose", ("L", uid), ("S", b"pose"), ("S", b"BindPose"), children=[
        element(b"Type", ("S", b"BindPose")), element(b"Version", ("I", 100)),
        element(b"NbPoseNodes", ("I", len(node_ids))),
        *(pose_node(n) for n in node_ids),
    ])


def connect(source, target, kind=b"OO"):
    return element(b"C", ("S", kind), ("L", source), ("L", target))


def cluster(uid, bone_id, weights=None):
    children = [element(b"Version", ("I", 100)), element(b"UserData", ("S", b""), ("S", b""))]
    if weights is not None:
        children.extend([element(b"Indexes", ("i", list(range(len(weights))))),
                         element(b"Weights", ("d", weights))])
    children.extend([element(b"Transform", ("d", matrix())),
                     element(b"TransformLink", ("d", matrix(bone_id))),
                     element(b"TransformAssociateModel", ("d", matrix()))])
    return element(b"Deformer", ("L", uid), ("S", b"cluster"), ("S", b"Cluster"), children=children)


def scene():
    objects = element(b"Objects", children=[
        *(element(b"Model", ("L", uid), ("S", b"SameBoneName"), ("S", b"LimbNode")) for uid in (1, 2)),
        *(element(b"Model", ("L", uid), ("S", b"mesh"), ("S", b"Mesh")) for uid in (10, 11)),
        element(b"Geometry", ("L", 50), ("S", b"geometry"), ("S", b"Mesh")),
        element(b"Deformer", ("L", 20), ("S", b"skin"), ("S", b"Skin")),
        cluster(30, 1, [1.0]), cluster(31, 2),
        pose(100, [1, 2, 10]), pose(101, [1, 2, 11]),
    ])
    counts = {kind: sum(o.id == kind for o in objects.elems) for kind in {o.id for o in objects.elems}}
    definitions = element(b"Definitions", children=[element(b"Count", ("I", len(objects.elems) + 1)),
        *(element(b"ObjectType", ("S", kind), children=[element(b"Count", ("I", count))])
          for kind, count in counts.items())])
    connections = element(b"Connections", children=[connect(1, 30), connect(30, 20),
                       connect(2, 31), connect(31, 20), connect(20, 50), connect(50, 10)])
    return element(b"", children=[definitions, objects, connections])


def objects(root, kind):
    return [o for o in child(root, b"Objects").elems if o.id == kind]


def fingerprint(root):
    return root.id, tuple(root.props_type), tuple(root.props), tuple(fingerprint(c) for c in root.elems)


class BindingCleanupTests(unittest.TestCase):
    def test_compatible_poses_union_meshes_preserving_every_bone(self):
        root = scene()
        stats = cleanup.optimize_fbx_tree(root)
        self.assertEqual((stats.poses_merged, stats.pose_nodes_removed, stats.empty_clusters_removed), (1, 2, 1))
        poses = objects(root, b"Pose")
        self.assertEqual(len(poses), 1)
        self.assertEqual(struct.unpack("<i", child(poses[0], b"NbPoseNodes").props[0])[0], 4)
        self.assertEqual(len(objects(root, b"Model")), 4)
        self.assertEqual(len(child(root, b"Connections").elems), 4)
        defs = child(root, b"Definitions")
        self.assertEqual(struct.unpack("<i", child(defs, b"Count").props[0])[0], 9)
        counts = {e.props[0][4:]: struct.unpack("<i", child(e, b"Count").props[0])[0]
                  for e in defs.elems if e.id == b"ObjectType"}
        self.assertEqual(counts[b"Pose"], 1)
        self.assertEqual(counts[b"Deformer"], 2)

    def test_second_pass_is_identical(self):
        root = scene()
        cleanup.optimize_fbx_tree(root)
        before = fingerprint(root)
        self.assertEqual(cleanup.optimize_fbx_tree(root), cleanup.CleanupStats())
        self.assertEqual(fingerprint(root), before)

    def test_preexisting_upstream_binding_count_underestimates_are_corrected(self):
        root = scene()
        definitions = child(root, b"Definitions")
        for entry in definitions.elems:
            if entry.id == b"ObjectType" and entry.props[0][4:] == b"Pose":
                child(entry, b"Count").props[0] = struct.pack("<i", 1)
        child(definitions, b"Count").props[0] = struct.pack("<i", 10)
        cleanup.optimize_fbx_tree(root)
        self.assertEqual(struct.unpack("<i", child(definitions, b"Count").props[0])[0], 9)

    def test_extra_pose_node_reference_metadata_is_preserved(self):
        root = scene()
        second = objects(root, b"Pose")[1]
        child(second.elems[-3], b"Node").elems.append(element(b"Custom", ("I", 1)))
        cleanup.optimize_fbx_tree(root)
        self.assertEqual(len(objects(root, b"Pose")), 2)

    def test_conflicting_bind_matrices_survive(self):
        root = scene()
        second = objects(root, b"Pose")[1]
        second.elems[-3] = pose_node(1, 123.0)
        cleanup.optimize_fbx_tree(root)
        self.assertEqual(len(objects(root, b"Pose")), 2)

    def test_distinct_skeleton_ids_with_equal_names_are_not_merged(self):
        root = scene()
        second = objects(root, b"Pose")[1]
        second.elems[:] = pose(101, [2, 11]).elems
        cleanup.optimize_fbx_tree(root)
        self.assertEqual(len(objects(root, b"Pose")), 2)

    def test_shape_only_poses_are_preserved(self):
        root = scene()
        second = objects(root, b"Pose")[1]
        second.elems[:] = pose(101, [11]).elems
        cleanup.optimize_fbx_tree(root)
        self.assertEqual(len(objects(root, b"Pose")), 2)

    def test_external_pose_reference_is_preserved(self):
        root = scene()
        child(root, b"Connections").elems.append(connect(101, 10))
        cleanup.optimize_fbx_tree(root)
        self.assertEqual(len(objects(root, b"Pose")), 2)

    def test_pose_with_unknown_metadata_is_preserved(self):
        root = scene()
        objects(root, b"Pose")[1].elems.append(element(b"CustomPoseData", ("S", b"important")))
        cleanup.optimize_fbx_tree(root)
        self.assertEqual(len(objects(root, b"Pose")), 2)

    def test_nonfinite_pose_matrix_is_not_merged(self):
        root = scene()
        objects(root, b"Pose")[1].elems[-3] = pose_node(1, float("nan"))
        cleanup.optimize_fbx_tree(root)
        self.assertEqual(len(objects(root, b"Pose")), 2)

    def test_invalid_definitions_abort_without_partial_changes(self):
        root = scene()
        child(child(root, b"Definitions"), b"Count").props[0] = struct.pack("<i", 0)
        before = fingerprint(root)
        cleanup.optimize_fbx_tree(root)
        self.assertEqual(fingerprint(root), before)

    def test_wholly_unweighted_skin_keeps_its_clusters(self):
        root = scene()
        weighted = objects(root, b"Deformer")[1]
        weighted.elems[:] = cluster(30, 1).elems
        stats = cleanup.optimize_fbx_tree(root)
        self.assertEqual(stats.empty_clusters_removed, 0)

    def test_missing_rest_pose_retains_empty_cluster(self):
        root = scene()
        for p in objects(root, b"Pose"):
            p.elems[:] = pose(100, [1, 10]).elems
        self.assertEqual(cleanup.optimize_fbx_tree(root).empty_clusters_removed, 0)

    def test_nonstandard_cluster_connection_is_preserved(self):
        root = scene()
        child(root, b"Connections").elems.append(connect(31, 11, b"OP"))
        self.assertEqual(cleanup.optimize_fbx_tree(root).empty_clusters_removed, 0)

    def test_compressed_zero_weights_can_be_removed(self):
        root = scene()
        empty = objects(root, b"Deformer")[2]
        empty.elems[:] = cluster(31, 2, [0.0] * 64).elems
        self.assertEqual(cleanup.optimize_fbx_tree(root).empty_clusters_removed, 1)

    def test_even_tiny_nonzero_weight_is_preserved(self):
        root = scene()
        empty = objects(root, b"Deformer")[2]
        empty.elems[:] = cluster(31, 2, [1e-300]).elems
        self.assertEqual(cleanup.optimize_fbx_tree(root).empty_clusters_removed, 0)

    def test_cluster_userdata_is_not_discarded(self):
        root = scene()
        empty = objects(root, b"Deformer")[2]
        user = child(empty, b"UserData")
        user.props[:] = element(b"UserData", ("S", b"custom"), ("S", b"data")).props
        self.assertEqual(cleanup.optimize_fbx_tree(root).empty_clusters_removed, 0)

    def test_mismatched_weight_index_arrays_are_preserved(self):
        root = scene()
        empty = objects(root, b"Deformer")[2]
        empty.elems[:] = cluster(31, 2, [0.0]).elems
        empty.elems.remove(child(empty, b"Indexes"))
        self.assertEqual(cleanup.optimize_fbx_tree(root).empty_clusters_removed, 0)

    def test_nonstandard_cluster_fields_are_preserved(self):
        root = scene()
        objects(root, b"Deformer")[2].elems.append(element(b"Mode", ("S", b"Additive")))
        self.assertEqual(cleanup.optimize_fbx_tree(root).empty_clusters_removed, 0)

    def test_missing_binding_sections_is_a_noop(self):
        root = element(b"", children=[element(b"GlobalSettings")])
        before = fingerprint(root)
        self.assertEqual(cleanup.optimize_fbx_tree(root), cleanup.CleanupStats())
        self.assertEqual(fingerprint(root), before)


if __name__ == "__main__":
    unittest.main()
