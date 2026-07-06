"""VRM SpringBone 新物理世界重写使用的稳定规格。"""

from __future__ import annotations

from ..names import SPRING_VRM_SLOT_KIND
from ..utils.ids import as_pointer, data_pointer, make_typed_slot_id, stable_short_hash
from ..utils.values import float3


def _simulated_bones(bones: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(bones[1:]) if len(bones) > 1 else ()


def _spec_hash(chains: tuple["SpringVRMChainSpec", ...], backend: str, substeps: int) -> str:
    payload = [
        str(backend),
        str(int(substeps)),
    ]
    for chain in chains:
        payload.extend((
            chain.root_bone,
            ",".join(chain.bones),
            "1" if chain.enabled else "0",
            f"{chain.stiffness_force:.8g}",
            f"{chain.drag_force:.8g}",
            ",".join(f"{item:.8g}" for item in chain.gravity_dir),
            f"{chain.gravity_power:.8g}",
        ))
    return stable_short_hash(payload, 12)


def make_spring_vrm_slot_id(armature_ptr: int, armature_data_ptr: int, spec_hash: str) -> str:
    return make_typed_slot_id(SPRING_VRM_SLOT_KIND, int(armature_ptr), int(armature_data_ptr), str(spec_hash))


class SpringVRMChainSpec:
    __slots__ = (
        "armature",
        "armature_ptr",
        "armature_data_ptr",
        "root_bone",
        "bones",
        "simulated_bones",
        "enabled",
        "stiffness_force",
        "drag_force",
        "gravity_dir",
        "gravity_power",
    )

    def __init__(
        self,
        armature,
        root_bone: str,
        bones,
        enabled: bool = True,
        stiffness_force: float = 1.0,
        drag_force: float = 0.4,
        gravity_dir=(0.0, 0.0, -1.0),
        gravity_power: float = 0.0,
    ) -> None:
        bone_names = tuple(str(name or "") for name in (bones or ()) if str(name or ""))
        self.armature = armature
        self.armature_ptr = as_pointer(armature)
        self.armature_data_ptr = data_pointer(armature)
        self.root_bone = str(root_bone or "")
        self.bones = bone_names
        self.simulated_bones = _simulated_bones(bone_names)
        self.enabled = bool(enabled)
        self.stiffness_force = max(float(stiffness_force), 0.0)
        self.drag_force = max(0.0, min(1.0, float(drag_force)))
        self.gravity_dir = float3(gravity_dir, fallback=(0.0, 0.0, -1.0))
        self.gravity_power = max(float(gravity_power), 0.0)

    def debug_dict(self) -> dict:
        return {
            "armature_ptr": self.armature_ptr,
            "armature_data_ptr": self.armature_data_ptr,
            "armature_name": str(getattr(self.armature, "name_full", "") or getattr(self.armature, "name", "")),
            "root_bone": self.root_bone,
            "bones": self.bones,
            "simulated_bones": self.simulated_bones,
            "enabled": self.enabled,
            "stiffness_force": self.stiffness_force,
            "drag_force": self.drag_force,
            "gravity_dir": self.gravity_dir,
            "gravity_power": self.gravity_power,
        }


class SpringVRMSolverSpec:
    __slots__ = (
        "armature",
        "armature_ptr",
        "armature_data_ptr",
        "slot_id",
        "spec_hash",
        "chains",
        "backend",
        "substeps",
        "chain_count",
        "simulated_bone_count",
    )

    def __init__(
        self,
        armature,
        chains,
        backend: str = "cpp",
        substeps: int = 1,
    ) -> None:
        chain_specs = tuple(chains or ())
        armature_ptr = as_pointer(armature)
        armature_data_ptr = data_pointer(armature)
        spec_hash = _spec_hash(chain_specs, backend, substeps)
        self.armature = armature
        self.armature_ptr = armature_ptr
        self.armature_data_ptr = armature_data_ptr
        self.slot_id = make_spring_vrm_slot_id(armature_ptr, armature_data_ptr, spec_hash)
        self.spec_hash = spec_hash
        self.chains = chain_specs
        self.backend = str(backend or "cpp").lower()
        self.substeps = max(1, min(16, int(substeps)))
        self.chain_count = len(chain_specs)
        self.simulated_bone_count = sum(len(chain.simulated_bones) for chain in chain_specs)

    def debug_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "spec_hash": self.spec_hash,
            "armature_ptr": self.armature_ptr,
            "armature_data_ptr": self.armature_data_ptr,
            "armature_name": str(getattr(self.armature, "name_full", "") or getattr(self.armature, "name", "")),
            "backend": self.backend,
            "substeps": self.substeps,
            "chain_count": self.chain_count,
            "simulated_bone_count": self.simulated_bone_count,
            "chains": [chain.debug_dict() for chain in self.chains],
        }


def normalize_spring_vrm_chain_properties(values) -> list[dict]:
    result = []
    stack = list(values) if isinstance(values, (list, tuple)) else ([values] if values is not None else [])
    while stack:
        item = stack.pop(0)
        if isinstance(item, (list, tuple)):
            stack[0:0] = list(item)
            continue
        if not isinstance(item, dict):
            continue
        armature = item.get("armature")
        root_bone = str(item.get("root_bone") or "")
        bones = item.get("bones")
        if armature is None or not root_bone or not isinstance(bones, list) or not bones:
            continue
        result.append(item)
    return result


def build_spring_vrm_solver_specs(
    vrm_chain_properties,
    backend: str = "cpp",
    substeps: int = 1,
) -> list[SpringVRMSolverSpec]:
    flat_properties = normalize_spring_vrm_chain_properties(vrm_chain_properties)
    armature_order: list[int] = []
    grouped: dict[int, tuple[object, list[SpringVRMChainSpec]]] = {}

    for chain_property in flat_properties:
        armature = chain_property.get("armature")
        key = as_pointer(armature)
        if key <= 0:
            continue
        if key not in grouped:
            grouped[key] = (armature, [])
            armature_order.append(key)
        grouped[key][1].append(SpringVRMChainSpec(
            armature=armature,
            root_bone=str(chain_property.get("root_bone") or ""),
            bones=list(chain_property.get("bones") or []),
            enabled=bool(chain_property.get("enabled", True)),
            stiffness_force=float(chain_property.get("stiffness_force", 1.0)),
            drag_force=float(chain_property.get("drag_force", 0.4)),
            gravity_dir=chain_property.get("gravity_dir", (0.0, 0.0, -1.0)),
            gravity_power=float(chain_property.get("gravity_power", 0.0)),
        ))

    specs = []
    for key in armature_order:
        armature, chains = grouped[key]
        chains = _validate_chain_group(chains)
        if chains:
            specs.append(SpringVRMSolverSpec(armature, chains, backend=backend, substeps=substeps))
    return specs


def _validate_chain_group(chains: list[SpringVRMChainSpec]) -> tuple[SpringVRMChainSpec, ...]:
    roots = set()
    simulated = set()
    valid = []
    for chain in sorted(chains, key=lambda item: item.root_bone):
        if not chain.root_bone:
            raise ValueError("SpringVRMChainSpec root_bone 不能为空")
        if chain.root_bone in roots:
            raise ValueError(f"SpringVRM root bone 重复: {chain.root_bone}")
        roots.add(chain.root_bone)
        for bone_name in chain.simulated_bones:
            if bone_name in simulated:
                raise ValueError(f"SpringVRM 模拟骨重复: {bone_name}")
        simulated.update(chain.simulated_bones)
        valid.append(chain)
    return tuple(valid)
