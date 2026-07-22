"""三种 MC2 setup 共用的稳定任务规格。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .parameters import (
    MC2ParticleProfileSpec,
    MC2SetupOptionsSpec,
    MC2TaskParametersSpec,
    make_mc2_particle_profile,
    make_mc2_setup_options,
    make_mc2_task_parameters,
)
from .runtime_parameters import make_mc2_runtime_parameters
from .source_identity import (
    mc2_pointer_token,
    mc2_source_token,
    normalize_mc2_setup_type,
)


def _normalize_sources(values) -> tuple[object, ...]:
    if values is None:
        return ()
    if isinstance(values, (list, tuple)):
        return tuple(value for value in values if value is not None)
    return (values,)


def _source_identity(sources: tuple[object, ...]) -> str:
    if not sources:
        raise ValueError("MC2 task 至少需要一个 source")
    tokens = [mc2_source_token(source) for source in sources]
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
    tokens = [mc2_source_token(source) for source in sources]
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
    task_parameters: MC2TaskParametersSpec
    topology_signature: str
    config_signature: str
    parameter_signature: str
    anchor_object: object | None = None
    enabled: bool = True
    implementation_version: int = 3

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
        if self.anchor_object is not None:
            anchor_token = mc2_pointer_token(self.anchor_object)
            if anchor_token is None or not hasattr(self.anchor_object, "matrix_world"):
                raise TypeError("MC2TaskSpec.anchor_object 必须是 Blender Object")
        if not isinstance(self.profile, MC2ParticleProfileSpec):
            raise TypeError("MC2TaskSpec.profile 必须是 MC2ParticleProfileSpec")
        if not isinstance(self.setup_options, MC2SetupOptionsSpec):
            raise TypeError("MC2TaskSpec.setup_options 必须是 MC2SetupOptionsSpec")
        if not isinstance(self.task_parameters, MC2TaskParametersSpec):
            raise TypeError("MC2TaskSpec.task_parameters 必须是 MC2TaskParametersSpec")
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
            self.profile, self.setup_options, self.task_parameters
        ).parameter_signature
        if self.topology_signature != expected_topology:
            raise ValueError("MC2TaskSpec.topology_signature 与拓扑不一致")
        if self.config_signature != expected_config:
            raise ValueError("MC2TaskSpec.config_signature 与 setup options 不一致")
        if self.parameter_signature != expected_parameter:
            raise ValueError("MC2TaskSpec.parameter_signature 与 profile 不一致")
        if self.implementation_version != 3:
            raise ValueError("不支持的 MC2TaskSpec implementation_version")

    def debug_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "source_signature": self.source_signature,
            "setup_type": self.setup_type,
            "source_count": len(self.sources),
            "profile_signature": self.profile.signature,
            "setup_options": self.setup_options.debug_dict(),
            "task_parameters": self.task_parameters.debug_dict(),
            "topology_signature": self.topology_signature,
            "config_signature": self.config_signature,
            "parameter_signature": self.parameter_signature,
            "anchor": (
                mc2_pointer_token(self.anchor_object)
                if self.anchor_object is not None
                else None
            ),
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
    task_parameters: MC2TaskParametersSpec | None = None,
    anchor_object=None,
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
    if task_parameters is None:
        task_parameters = make_mc2_task_parameters()
    if not isinstance(task_parameters, MC2TaskParametersSpec):
        raise TypeError("task_parameters 必须是 MC2TaskParametersSpec")
    topology_signature = _spec_signature({
        "setup_type": normalized_setup,
        "source_signature": source_signature,
        "ordered_source_signature": _ordered_source_identity(normalized_sources),
        "connection_mode": setup_options.connection_mode,
        "connection_model": setup_options.connection_model,
    })
    config_signature = _spec_signature(setup_options.debug_dict())
    parameter_signature = make_mc2_runtime_parameters(
        profile, setup_options, task_parameters
    ).parameter_signature
    return MC2TaskSpec(
        task_id=f"mc2:{normalized_setup}:{source_signature[:24]}",
        source_signature=source_signature,
        setup_type=normalized_setup,
        sources=normalized_sources,
        profile=profile,
        setup_options=setup_options,
        task_parameters=task_parameters,
        topology_signature=topology_signature,
        config_signature=config_signature,
        parameter_signature=parameter_signature,
        anchor_object=anchor_object,
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
