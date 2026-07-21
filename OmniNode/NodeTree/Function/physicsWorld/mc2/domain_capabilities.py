"""Pure E0 capability gate for MC2 unified-domain backend programs."""

from __future__ import annotations

from dataclasses import dataclass

from .domain_ir import MC2CompiledDomainProgramV1


_SETUP_TYPES = frozenset(("mesh_cloth", "bone_cloth", "bone_spring"))


def _text(value: object, name: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{name} cannot be empty")
    return result


def _sorted_unique_text(values, name: str) -> tuple[str, ...]:
    result = tuple(_text(value, name) for value in values)
    if result != tuple(sorted(set(result))):
        raise ValueError(f"{name} must be sorted and unique")
    return result


def _sorted_unique_versions(values) -> tuple[int, ...]:
    source = tuple(values)
    if any(type(value) is not int or value <= 0 for value in source):
        raise ValueError("schema_versions must contain positive integers")
    result = source
    if result != tuple(sorted(set(result))):
        raise ValueError("schema_versions must be sorted and unique")
    return result


@dataclass(frozen=True)
class MC2BackendCapabilitiesV1:
    """A resource-free backend declaration checked before allocation."""

    backend_id: str
    schema_versions: tuple[int, ...]
    setup_types: tuple[str, ...]
    capabilities: tuple[str, ...]
    max_particles: int
    index_width_bits: int = 32
    supports_physical_reorder: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "schema_versions", _sorted_unique_versions(self.schema_versions)
        )
        setup_types = _sorted_unique_text(self.setup_types, "setup_types")
        if any(value not in _SETUP_TYPES for value in setup_types):
            raise ValueError("setup_types contains an unknown MC2 setup")
        object.__setattr__(self, "setup_types", setup_types)
        object.__setattr__(
            self,
            "capabilities",
            _sorted_unique_text(self.capabilities, "capabilities"),
        )
        if type(self.max_particles) is not int or self.max_particles <= 0:
            raise ValueError("max_particles must be a positive integer")
        if (
            type(self.index_width_bits) is not int
            or self.index_width_bits not in (32, 64)
        ):
            raise ValueError("index_width_bits must be 32 or 64")
        if type(self.supports_physical_reorder) is not bool:
            raise TypeError("supports_physical_reorder must be bool")

    def debug_dict(self) -> dict:
        return {
            "backend_id": self.backend_id,
            "schema_versions": list(self.schema_versions),
            "setup_types": list(self.setup_types),
            "capabilities": list(self.capabilities),
            "max_particles": self.max_particles,
            "index_width_bits": self.index_width_bits,
            "supports_physical_reorder": self.supports_physical_reorder,
        }


@dataclass(frozen=True)
class MC2BackendCompatibilityReportV1:
    backend_id: str
    domain_signature: str
    compatible: bool
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "domain_signature", _text(self.domain_signature, "domain_signature")
        )
        if type(self.compatible) is not bool:
            raise TypeError("compatible must be bool")
        if not isinstance(self.blockers, tuple) or any(
            not isinstance(value, str) or not value for value in self.blockers
        ):
            raise TypeError("blockers must be a tuple of non-empty strings")
        if self.blockers != tuple(sorted(set(self.blockers))):
            raise ValueError("blockers must be sorted and unique")
        if self.compatible == bool(self.blockers):
            raise ValueError("compatible must be true exactly when blockers are empty")

    def debug_dict(self) -> dict:
        return {
            "backend_id": self.backend_id,
            "domain_signature": self.domain_signature,
            "compatible": self.compatible,
            "blockers": list(self.blockers),
        }


def evaluate_mc2_backend_capabilities(
    program: MC2CompiledDomainProgramV1,
    capabilities: MC2BackendCapabilitiesV1,
) -> MC2BackendCompatibilityReportV1:
    """Check a logical program without loading or allocating a backend."""

    if not isinstance(program, MC2CompiledDomainProgramV1):
        raise TypeError("program must be MC2CompiledDomainProgramV1")
    if not isinstance(capabilities, MC2BackendCapabilitiesV1):
        raise TypeError("capabilities must be MC2BackendCapabilitiesV1")
    blockers = []
    if program.schema_version not in capabilities.schema_versions:
        blockers.append(f"schema:{program.schema_version}")
    if program.setup_type not in capabilities.setup_types:
        blockers.append(f"setup:{program.setup_type}")
    missing = sorted(
        set(program.required_capabilities) - set(capabilities.capabilities)
    )
    blockers.extend(f"capability:{value}" for value in missing)
    if program.particle_count > capabilities.max_particles:
        blockers.append(
            f"particle_limit:{program.particle_count}>{capabilities.max_particles}"
        )
    if program.particle_count >= (1 << capabilities.index_width_bits):
        blockers.append(f"index_width:{capabilities.index_width_bits}")
    result = tuple(sorted(blockers))
    return MC2BackendCompatibilityReportV1(
        backend_id=capabilities.backend_id,
        domain_signature=program.domain_signature,
        compatible=not result,
        blockers=result,
    )


__all__ = [
    "MC2BackendCapabilitiesV1",
    "MC2BackendCompatibilityReportV1",
    "evaluate_mc2_backend_capabilities",
]
