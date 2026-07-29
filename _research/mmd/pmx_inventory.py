"""MMD 物理规划用的只读 PMX 资源盘点探针。

探针直接加载本机 mmd_tools 的 PMX 二进制解析器，只记录汇总物理元数据；
不会启动 Blender，也不会修改模型文件。
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import math
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path


PMX_2_0_VERSION = 2.0
PMX_2_0_VERSION_BITS = struct.unpack("<I", struct.pack("<f", PMX_2_0_VERSION))[0]


def load_parser(addon_root: Path):
    # 直接加载解析器模块。完整导入插件会执行 Blender 注册代码并要求 ``bpy``；
    # PMX 二进制解析器本身不依赖宿主。
    parser_path = addon_root / "core" / "pmx" / "__init__.py"
    spec = importlib.util.spec_from_file_location("mmd_tools_pmx_probe", parser_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load PMX parser: {parser_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bit_count(value: int) -> int:
    return int(value & 0xFFFF).bit_count()


def read_pmx_header(path: Path) -> dict:
    """读取并严格分类 PMX magic 与版本，不把近似值格式化成 2.0。"""
    with path.open("rb") as stream:
        header = stream.read(17)
    if len(header) != 17 or header[:4] != b"PMX ":
        raise ValueError("invalid PMX header")
    version_bytes = header[4:8]
    version = float(struct.unpack("<f", version_bytes)[0])
    if not math.isfinite(version):
        raise ValueError("non-finite PMX version")
    version_bits = int(struct.unpack("<I", version_bytes)[0])
    header_data_size = int(header[8])
    encoding = int(header[9])
    additional_uv_count = int(header[10])
    index_sizes = tuple(int(value) for value in header[11:17])
    if header_data_size != 8:
        raise ValueError(f"invalid PMX 2.0 header data size: {header_data_size}")
    if encoding not in {0, 1}:
        raise ValueError(f"invalid PMX text encoding: {encoding}")
    if additional_uv_count not in range(5):
        raise ValueError(f"invalid PMX additional UV count: {additional_uv_count}")
    if any(size not in {1, 2, 4} for size in index_sizes):
        raise ValueError(f"invalid PMX index sizes: {index_sizes!r}")
    return {
        "version": version,
        "version_bits": f"0x{version_bits:08x}",
        "version_bytes_le": version_bytes.hex(),
        "supported_exact": version_bits == PMX_2_0_VERSION_BITS,
        "header_data_size": header_data_size,
        "encoding": encoding,
        "additional_uv_count": additional_uv_count,
        "index_sizes": index_sizes,
    }


def version_identity(header: dict) -> str:
    return f"{header['version']!r}@{header['version_bits']}"


def load_model_strict(pmx_module, path: Path):
    """调用底层 Model.load，让截断异常传播并要求恰好消费到 EOF。"""
    with pmx_module.FileReadStream(str(path)) as stream:
        header = pmx_module.Header()
        header.load(stream)
        stream.setHeader(header)
        model = pmx_module.Model()
        # mmd_tools 会把最后一个被截断的 Joint 补零后返回。盘点必须拒绝这种
        # 半条记录，因此只在本次加载期间改用 Joint._load 的严格行为。
        tolerant_joint_load = pmx_module.Joint.load
        pmx_module.Joint.load = pmx_module.Joint._load
        try:
            model.load(stream)
        finally:
            pmx_module.Joint.load = tolerant_joint_load
        file_obj = getattr(stream, "_FileReadStream__fin")
        bytes_consumed = int(file_obj.tell())

    file_size = int(path.stat().st_size)
    if bytes_consumed != file_size:
        raise ValueError(
            f"PMX payload was not consumed exactly: {bytes_consumed}/{file_size} bytes"
        )
    return model, bytes_consumed, file_size


def require_finite_vector(owner: str, field: str, value, length: int) -> None:
    if not isinstance(value, (tuple, list)) or len(value) != length:
        raise ValueError(f"{owner}.{field} must contain {length} values")
    if any(not math.isfinite(float(item)) for item in value):
        raise ValueError(f"{owner}.{field} contains a non-finite value")


def require_finite_scalar(owner: str, field: str, value) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{owner}.{field} contains a non-finite value")


def validate_pmx20_model(model) -> None:
    """校验物理记录的 PMX 2.0 枚举、引用范围和有限数值。"""
    bones = list(getattr(model, "bones", ()) or ())
    rigids = list(getattr(model, "rigids", ()) or ())
    joints = list(getattr(model, "joints", ()) or ())

    for index, rigid in enumerate(rigids):
        owner = f"rigid[{index}]"
        bone = getattr(rigid, "bone", None)
        if bone is not None and not 0 <= int(bone) < len(bones):
            raise ValueError(f"{owner}.bone is out of range: {bone}")
        group = int(getattr(rigid, "collision_group_number", -1))
        if group not in range(16):
            raise ValueError(f"{owner}.collision_group_number is invalid: {group}")
        shape = int(getattr(rigid, "type", -1))
        if shape not in {0, 1, 2}:
            raise ValueError(f"{owner}.type is invalid: {shape}")
        mode = int(getattr(rigid, "mode", -1))
        if mode not in {0, 1, 2}:
            raise ValueError(f"{owner}.mode is invalid: {mode}")
        for field in ("size", "location", "rotation"):
            require_finite_vector(owner, field, getattr(rigid, field, None), 3)
        for field in (
            "mass",
            "velocity_attenuation",
            "rotation_attenuation",
            "bounce",
            "friction",
        ):
            require_finite_scalar(owner, field, getattr(rigid, field, None))

    for index, joint in enumerate(joints):
        owner = f"joint[{index}]"
        mode = int(getattr(joint, "mode", -1))
        if mode != 0:
            raise ValueError(f"{owner}.mode is invalid for PMX 2.0: {mode}")
        for field in ("src_rigid", "dest_rigid"):
            endpoint = getattr(joint, field, None)
            if endpoint is not None and not 0 <= int(endpoint) < len(rigids):
                raise ValueError(f"{owner}.{field} is out of range: {endpoint}")
        for field in (
            "location",
            "rotation",
            "minimum_location",
            "maximum_location",
            "minimum_rotation",
            "maximum_rotation",
            "spring_constant",
            "spring_rotation_constant",
        ):
            require_finite_vector(owner, field, getattr(joint, field, None), 3)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_model(pmx_module, path: Path, pmx_header: dict) -> dict:
    if not bool(pmx_header.get("supported_exact", False)):
        raise ValueError(
            "unsupported PMX version "
            f"{pmx_header.get('version')!r} ({pmx_header.get('version_bits')})"
        )

    model, bytes_consumed, file_size = load_model_strict(pmx_module, path)
    validate_pmx20_model(model)
    rigids = list(getattr(model, "rigids", ()) or ())
    joints = list(getattr(model, "joints", ()) or ())

    shape_counts = collections.Counter(int(getattr(item, "type", -1)) for item in rigids)
    mode_counts = collections.Counter(int(getattr(item, "mode", -1)) for item in rigids)
    group_counts = collections.Counter(int(getattr(item, "collision_group_number", -1)) for item in rigids)
    ignored_group_counts = collections.Counter()
    mask_histogram = collections.Counter()
    for item in rigids:
        mask = int(getattr(item, "collision_group_mask", 0))
        mask_histogram[f"0x{mask & 0xFFFF:04x}"] += 1
        ignored_group_counts[bit_count(mask)] += 1

    joint_mode_counts = collections.Counter(int(getattr(item, "mode", -1)) for item in joints)
    unbound_rigids = sum(
        1
        for item in rigids
        if getattr(item, "bone", None) is None
    )
    unbound_joint_endpoint_counts = collections.Counter()
    for item in joints:
        missing = int(getattr(item, "src_rigid", None) is None)
        missing += int(getattr(item, "dest_rigid", None) is None)
        unbound_joint_endpoint_counts[missing] += 1

    return {
        "path": str(path),
        "pmx_version": pmx_header["version"],
        "pmx_version_bits": pmx_header["version_bits"],
        "complete_parse": True,
        "bytes_consumed": bytes_consumed,
        "file_size": file_size,
        "rigid_count": len(rigids),
        "joint_count": len(joints),
        "shape_counts": dict(sorted(shape_counts.items())),
        "mode_counts": dict(sorted(mode_counts.items())),
        "collision_group_counts": dict(sorted(group_counts.items())),
        "ignored_group_count_histogram": dict(sorted(ignored_group_counts.items())),
        "mask_histogram": dict(sorted(mask_histogram.items())),
        "joint_mode_counts": dict(sorted(joint_mode_counts.items())),
        "unbound_rigid_count": unbound_rigids,
        "unbound_joint_endpoint_counts": dict(sorted(unbound_joint_endpoint_counts.items())),
    }


def merge(rows: list[dict]) -> dict:
    totals = {
        "model_count": len(rows),
        "rigid_count": sum(row["rigid_count"] for row in rows),
        "joint_count": sum(row["joint_count"] for row in rows),
        "complete_parse_count": sum(bool(row["complete_parse"]) for row in rows),
        "unbound_rigid_count": sum(row["unbound_rigid_count"] for row in rows),
    }
    totals["parsed_version_counts"] = dict(sorted(collections.Counter(
        f"{row['pmx_version']!r}@{row['pmx_version_bits']}" for row in rows
    ).items()))
    endpoint_counter = collections.Counter()
    for row in rows:
        endpoint_counter.update(row["unbound_joint_endpoint_counts"])
    totals["unbound_joint_endpoint_counts"] = dict(sorted(endpoint_counter.items()))
    for field in (
        "shape_counts",
        "mode_counts",
        "collision_group_counts",
        "ignored_group_count_histogram",
        "mask_histogram",
        "joint_mode_counts",
    ):
        counter = collections.Counter()
        for row in rows:
            counter.update(row[field])
        totals[field] = dict(sorted(counter.items(), key=lambda item: str(item[0])))
    return totals


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--mmd-tools", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true", help="存在解析失败时返回非零")
    args = parser.parse_args()

    pmx_module = load_parser(args.mmd_tools)
    rows = []
    failures = []
    header_failures = []
    header_version_counts = collections.Counter()
    supported_exact_header_count = 0
    paths = sorted(args.models.rglob("*.pmx"))
    for path in paths:
        try:
            pmx_header = read_pmx_header(path)
            header_version_counts[version_identity(pmx_header)] += 1
            supported_exact_header_count += int(pmx_header["supported_exact"])
        except Exception as exc:
            header_failures.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            pmx_header = None

        try:
            if pmx_header is None:
                raise ValueError("cannot parse a file without a valid PMX header")
            rows.append(inspect_model(pmx_module, path, pmx_header))
        except Exception as exc:  # 坏资源记录在结果中，不中断整个批处理
            failure = {"path": str(path), "error": f"{type(exc).__name__}: {exc}"}
            if pmx_header is not None:
                failure["pmx_version"] = pmx_header["version"]
                failure["pmx_version_bits"] = pmx_header["version_bits"]
            failures.append(failure)

    summary = merge(rows)
    summary["file_count"] = len(paths)
    summary["valid_header_count"] = sum(header_version_counts.values())
    summary["header_version_counts"] = dict(sorted(header_version_counts.items()))
    summary["supported_exact_header_count"] = supported_exact_header_count
    summary["unsupported_version_header_count"] = (
        summary["valid_header_count"] - supported_exact_header_count
    )

    parser_path = args.mmd_tools / "core" / "pmx" / "__init__.py"
    parser_supported_version = float(getattr(pmx_module.Header, "VERSION", 0.0))
    parser_supported_bits = struct.unpack(
        "<I", struct.pack("<f", parser_supported_version)
    )[0]

    payload = {
        "schema": 3,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "strict_failure_exit": bool(args.strict),
        "source": str(args.models),
        "parser": str(args.mmd_tools),
        "probe_sha256": sha256_file(Path(__file__)),
        "parser_sha256": sha256_file(parser_path),
        "parser_supported_version": parser_supported_version,
        "parser_supported_version_bits": f"0x{parser_supported_bits:08x}",
        "summary": summary,
        "header_failures": header_failures,
        "failures": failures,
        "models": rows,
    }
    rendered = json.dumps(payload, ensure_ascii=True, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    # 真实目录可能含有 macOS 侧车文件或其它坏文件；失败详情已经写入
    # failures。默认盘点仍成功，CI 可用 --strict 将失败转换为非零返回码。
    return 2 if args.strict and failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
