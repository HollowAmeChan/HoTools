"""Exercise production cleanup on a captured FBX without touching its source.

Blender -b --factory-startup --python-exit-code 1 --python THIS_FILE -- INPUT OUTPUT
Writes a JSON evidence file beside OUTPUT. The installed parser is test-only.
"""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from Exporter.FbxExporter._vendor import encode_bin
from Exporter.FbxExporter.cleanup import optimize_fbx_tree
from io_scene_fbx import parse_fbx


METHODS = dict(zip("BCYIFDLRSfdlibcZ", (
    "add_bool", "add_char", "add_int16", "add_int32", "add_float32", "add_float64",
    "add_int64", "add_bytes", "add_string", "add_float32_array", "add_float64_array",
    "add_int64_array", "add_int32_array", "add_bool_array", "add_byte_array", "add_int8",
)))
SCALARS = {"B": "?", "C": "c", "Z": "b", "Y": "h", "I": "i", "F": "f", "D": "d", "L": "q"}


def encode(node):
    result = encode_bin.FBXElem(node.id)
    for kind, value in zip(node.props_type, node.props):
        getattr(result, METHODS[chr(kind)])(bool(value) if kind == ord("B") else value)
    result.elems.extend(encode(c) for c in node.elems)
    return result


def digest(node):
    hasher = hashlib.sha256()
    def visit(n):
        hasher.update(struct.pack("<I", len(n.id)))
        hasher.update(n.id)
        hasher.update(bytes(n.props_type))
        for kind, value in zip(n.props_type, n.props):
            k = chr(kind)
            if k in SCALARS:
                value = struct.pack("<" + SCALARS[k], value)
            elif k not in "RS":
                value = value.tobytes()
            hasher.update(struct.pack("<I", len(value)))
            hasher.update(value)
        hasher.update(struct.pack("<I", len(n.elems)))
        for c in n.elems:
            visit(c)
    visit(node)
    return hasher.hexdigest()


def evidence(root):
    objects = next(c for c in root.elems if c.id == b"Objects")
    relations = next(c for c in root.elems if c.id == b"Connections")
    return {
        "objects": {obj.props[0]: (obj.id, obj.props[2], digest(obj)) for obj in objects.elems},
        "poses": {digest(n) for obj in objects.elems if obj.id == b"Pose"
                  for n in obj.elems if n.id == b"PoseNode"},
        "relations": [(c.props[1], c.props[2], digest(c)) for c in relations.elems],
    }


def run(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output:
        raise ValueError("Snapshot verification must not overwrite its source")
    decoded, version = parse_fbx.parse(str(source))
    before = evidence(decoded)
    with encode_bin.FBXElem.enable_multithreading_cm():
        tree = encode(decoded)
    del decoded
    stats = optimize_fbx_tree(tree)
    encode_bin.write(str(output), tree, version)
    del tree
    decoded, _ = parse_fbx.parse(str(output))
    after = evidence(decoded)
    removed = before["objects"].keys() - after["objects"].keys()
    assert not after["objects"].keys() - before["objects"].keys()
    assert all(before["objects"][uid][:2] in {(b"Pose", b"BindPose"), (b"Deformer", b"Cluster")} for uid in removed)
    assert all(obj == before["objects"][uid] for uid, obj in after["objects"].items() if obj[0] != b"Pose")
    assert before["poses"] == after["poses"]
    assert [c for c in before["relations"] if c[0] not in removed and c[1] not in removed] == after["relations"]
    result = {"source": str(source), "output": str(output), "source_bytes": source.stat().st_size,
              "output_bytes": output.stat().st_size, "cleanup": asdict(stats),
              "retained_object_payloads_identical": True, "bind_pose_matrices_preserved": True,
              "connections_preserved": True, "file_version": version}
    output.with_suffix(".verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    source, output = sys.argv[sys.argv.index("--") + 1:]
    run(source, output)
