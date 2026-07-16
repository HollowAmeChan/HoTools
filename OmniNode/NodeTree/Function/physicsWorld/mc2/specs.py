"""三种 MC2 setup 共用的稳定任务规格。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .names import MC2_SETUP_TYPES
from .parameters import (
    MC2ParticleProfileSpec,
    MC2SetupOptionsSpec,
    make_mc2_particle_profile,
    make_mc2_setup_options,
)
from .runtime_parameters import make_mc2_runtime_parameters


def normalize_mc2_setup_type(value: object) -> str:
    setup_type = str(value or "").strip().lower()
    if setup_type not in MC2_SETUP_TYPES:
        raise ValueError(f"未知 MC2 setup_type: {value!r}")
    return setup_type


def _normalize_sources(values) -> tuple[object, ...]:
    if values is None:
        return ()
    if isinstance(values, (list, tuple)):
        return tuple(value for value in values if value is not None)
    return (values,)


def _pointer_token(value) -> dict | None:
    pointer = getattr(value, "as_pointer", None)
    if not callable(pointer):
        return None
    try:
        owner_ptr = int(pointer())
    except Exception as exc:
        raise ValueError(f"MC2 source 指针不可读: {value!r}") from exc
    if owner_ptr <= 0:
        raise ValueError(f"MC2 source 指针已失效: {value!r}")
    data = getattr(value, "data", None)
    data_pointer = getattr(data, "as_pointer", None)
    try:
        data_ptr = int(data_pointer()) if callable(data_pointer) else 0
    except Exception:
        data_ptr = 0
    return {
        "kind": "blender_id",
        "owner_ptr": owner_ptr,
        "data_ptr": data_ptr,
        "type": str(getattr(value, "type", type(value).__name__) or type(value).__name__),
        "name": str(getattr(value, "name_full", getattr(value, "name", "")) or ""),
    }


def _source_token(source) -> dict:
    pointer_token = _pointer_token(source)
    if pointer_token is not None:
        return pointer_token

    if isinstance(source, dict):
        stable_id = str(source.get("stable_id") or source.get("source_id") or "").strip()
        if stable_id:
            return {"kind": "stable_id", "value": stable_id}

        armature = source.get("armature")
        armature_token = _pointer_token(armature)
        root_bone = str(source.get("root_bone") or source.get("bone") or "").strip()
        bones = tuple(str(name) for name in (source.get("bones") or ()) if str(name))
        if armature_token is not None and (root_bone or bones):
            return {
                "kind": "bone_source",
                "armature": armature_token,
                "root_bone": root_bone,
                "bones": bones,
            }

        proxy = source.get("proxy_obj")
        if proxy is None:
            proxy = source.get("object")
        proxy_token = _pointer_token(proxy)
        if proxy_token is not None:
            return {"kind": "object_source", "object": proxy_token}

        raise TypeError("MC2 dict source 需要 stable_id/source_id、有效 armature+bone，或 proxy_obj/object")

    if isinstance(source, tuple) and len(source) == 2:
        owner_token = _pointer_token(source[0])
        name = str(source[1] or "").strip()
        if owner_token is not None and name:
            return {"kind": "owner_member", "owner": owner_token, "name": name}

    raise TypeError(f"不支持的 MC2 source: {type(source).__name__}")


def _source_identity(sources: tuple[object, ...]) -> str:
    if not sources:
        raise ValueError("MC2 task 至少需要一个 source")
    tokens = [_source_token(source) for source in sources]
    encoded_tokens = [
        json.dumps(token, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for token in tokens
    ]
    if len(set(encoded_tokens)) != len(encoded_tokens):
        raise ValueError("MC2 task 不能重复包含同一个 source")
    canonical = "[" + ",".join(sorted(encoded_tokens)) + "]"
    signature = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return signature


def _ordered_source_identity(sources: tuple[object, ...]) -> str:
    """拓扑签名保留输入顺序；BoneCloth 的顺序/成环连接依赖 root list 顺序。"""
    tokens = [_source_token(source) for source in sources]
    canonical = json.dumps(tokens, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MC2TaskSpec:
    """MC2 step 的统一输入；setup adapter 只负责生成本规格。"""

    task_id: str
    source_signature: str
    setup_type: str
    sources: tuple[object, ...]
    profile: MC2ParticleProfileSpec
    setup_options: MC2SetupOptionsSpec
    topology_signature: str
    config_signature: str
    parameter_signature: str
    enabled: bool = True
    implementation_version: int = 2

    def __post_init__(self) -> None:
        setup_type = normalize_mc2_setup_type(self.setup_type)
        if setup_type != self.setup_type:
            raise ValueError(f"MC2TaskSpec setup_type 未归一化: {self.setup_type!r}")
        if not isinstance(self.sources, tuple):
            raise TypeError("MC2TaskSpec.sources 必须是 tuple")
        signature = _source_identity(self.sources)
        if self.source_signature != signature:
            raise ValueError("MC2TaskSpec.source_signature 与 sources 不一致")
        expected_task_id = f"mc2:{setup_type}:{signature[:24]}"
        if self.task_id != expected_task_id:
            raise ValueError(f"MC2TaskSpec.task_id 应为 {expected_task_id!r}")
        if type(self.enabled) is not bool:
            raise TypeError("MC2TaskSpec.enabled 必须是 bool")
        if not isinstance(self.profile, MC2ParticleProfileSpec):
            raise TypeError("MC2TaskSpec.profile 必须是 MC2ParticleProfileSpec")
        if not isinstance(self.setup_options, MC2SetupOptionsSpec):
            raise TypeError("MC2TaskSpec.setup_options 必须是 MC2SetupOptionsSpec")
        if self.setup_options.setup_type != setup_type:
            raise ValueError("MC2TaskSpec.setup_options 与 setup_type 不一致")
        expected_topology = _spec_signature({
            "setup_type": setup_type,
            "source_signature": signature,
            "ordered_source_signature": _ordered_source_identity(self.sources),
            "connection_mode": self.setup_options.connection_mode,
            "connection_model": self.setup_options.connection_model,
        })
        expected_config = _spec_signature(self.setup_options.debug_dict())
        # Scheduler settings在 step绑定，不属于 ClothParameters ABI。
        expected_parameter = make_mc2_runtime_parameters(
            self.profile, self.setup_options
        ).parameter_signature
        if self.topology_signature != expected_topology:
            raise ValueError("MC2TaskSpec.topology_signature 与拓扑不一致")
        if self.config_signature != expected_config:
            raise ValueError("MC2TaskSpec.config_signature 与 setup options 不一致")
        if self.parameter_signature != expected_parameter:
            raise ValueError("MC2TaskSpec.parameter_signature 与 profile 不一致")
        if self.implementation_version != 2:
            raise ValueError("不支持的 MC2TaskSpec implementation_version")

    def debug_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "source_signature": self.source_signature,
            "setup_type": self.setup_type,
            "source_count": len(self.sources),
            "profile_signature": self.profile.signature,
            "setup_options": self.setup_options.debug_dict(),
            "topology_signature": self.topology_signature,
            "config_signature": self.config_signature,
            "parameter_signature": self.parameter_signature,
            "enabled": self.enabled,
            "implementation_version": self.implementation_version,
        }


def _spec_signature(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def make_mc2_task_spec(
    setup_type: object,
    sources,
    *,
    profile: MC2ParticleProfileSpec | None = None,
    setup_options: MC2SetupOptionsSpec | None = None,
    enabled: bool = True,
) -> MC2TaskSpec:
    normalized_setup = normalize_mc2_setup_type(setup_type)
    normalized_sources = _normalize_sources(sources)
    source_signature = _source_identity(normalized_sources)
    if profile is None:
        profile = make_mc2_particle_profile()
    if not isinstance(profile, MC2ParticleProfileSpec):
        raise TypeError("profile 必须是 MC2ParticleProfileSpec")
    if setup_options is None:
        setup_options = make_mc2_setup_options(normalized_setup)
    if not isinstance(setup_options, MC2SetupOptionsSpec):
        raise TypeError("setup_options 必须是 MC2SetupOptionsSpec")
    if setup_options.setup_type != normalized_setup:
        raise ValueError("setup_options.setup_type 与 task setup_type 不一致")
    topology_signature = _spec_signature({
        "setup_type": normalized_setup,
        "source_signature": source_signature,
        "ordered_source_signature": _ordered_source_identity(normalized_sources),
        "connection_mode": setup_options.connection_mode,
        "connection_model": setup_options.connection_model,
    })
    config_signature = _spec_signature(setup_options.debug_dict())
    parameter_signature = make_mc2_runtime_parameters(
        profile, setup_options
    ).parameter_signature
    return MC2TaskSpec(
        task_id=f"mc2:{normalized_setup}:{source_signature[:24]}",
        source_signature=source_signature,
        setup_type=normalized_setup,
        sources=normalized_sources,
        profile=profile,
        setup_options=setup_options,
        topology_signature=topology_signature,
        config_signature=config_signature,
        parameter_signature=parameter_signature,
        enabled=bool(enabled),
    )


def build_mc2_task_specs(values) -> tuple[MC2TaskSpec, ...]:
    pending = [values]
    ordered: list[MC2TaskSpec] = []
    by_id: dict[str, MC2TaskSpec] = {}
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
            continue
        if not isinstance(value, MC2TaskSpec):
            raise TypeError(f"MC2 task 列表包含非法值: {type(value).__name__}")
        previous = by_id.get(value.task_id)
        if previous is None:
            by_id[value.task_id] = value
            ordered.append(value)
            continue
        if previous != value:
            raise ValueError(f"MC2 task_id 冲突: {value.task_id}")
    return tuple(ordered)
