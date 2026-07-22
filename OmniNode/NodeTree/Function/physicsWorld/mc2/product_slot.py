"""Physics World slot lifecycle for the fused MeshCloth CPU owner."""

from __future__ import annotations

from dataclasses import dataclass

from ..types import PhysicsSolverSlot
from ..types import PhysicsWorldCache
from .domain_owner import MC2FusedCPUOwnerSyncReportV1
from .domain_owner import MC2MeshFusedCPUOwnerV1
from .product_collect import MC2MeshProductCollectionV1


MC2_FUSED_MESH_SLOT_ID = "mc2.domain.mesh.product.v1"
MC2_FUSED_MESH_SLOT_KIND = "mc2_fused_mesh_cpu_v1"
_MC2_FUSED_MESH_WRITER = "mc2_fused_mesh_cpu"


@dataclass(frozen=True)
class MC2FusedMeshSlotSyncResultV1:
    action: str
    slot_id: str
    world_generation: int
    owner_report: MC2FusedCPUOwnerSyncReportV1

    def __post_init__(self) -> None:
        if self.action not in {"created", "updated", "replaced"}:
            raise ValueError("invalid fused Mesh slot action")
        if self.slot_id != MC2_FUSED_MESH_SLOT_ID:
            raise ValueError("invalid fused Mesh slot id")
        if self.world_generation < 0:
            raise ValueError("world_generation cannot be negative")
        if not isinstance(self.owner_report, MC2FusedCPUOwnerSyncReportV1):
            raise TypeError("owner_report must be MC2FusedCPUOwnerSyncReportV1")

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_fused_mesh_slot_sync_result_v1",
            "action": self.action,
            "slot_id": self.slot_id,
            "world_generation": self.world_generation,
            "owner": self.owner_report.debug_dict(),
        }


def _dispose_slot_owner(slot: PhysicsSolverSlot, _reason: str) -> None:
    owner = slot.data.get("owner")
    if isinstance(owner, MC2MeshFusedCPUOwnerV1):
        owner.dispose()


def _slot_debug_snapshot(slot: PhysicsSolverSlot) -> dict:
    owner = slot.data.get("owner")
    collection = slot.data.get("collection")
    return {
        "slot_id": slot.slot_id,
        "kind": slot.kind,
        "world_generation": slot.world_generation,
        "owner": owner.inspect() if isinstance(owner, MC2MeshFusedCPUOwnerV1) else None,
        "collection": (
            collection.debug_dict()
            if isinstance(collection, MC2MeshProductCollectionV1)
            else None
        ),
    }


def _make_slot(world, owner, collection, report) -> PhysicsSolverSlot:
    slot = PhysicsSolverSlot(
        MC2_FUSED_MESH_SLOT_ID,
        MC2_FUSED_MESH_SLOT_KIND,
        int(world.generation),
    )
    slot.data.update({
        "owner": owner,
        "collection": collection,
        "last_sync": report,
        "product_enabled": False,
        "_dispose": lambda reason, slot=slot: _dispose_slot_owner(slot, reason),
        "_debug_snapshot": lambda slot=slot: _slot_debug_snapshot(slot),
    })
    return slot


def sync_mc2_mesh_fused_slot(
    world: PhysicsWorldCache,
    collection: MC2MeshProductCollectionV1,
    *,
    kernel=None,
) -> MC2FusedMeshSlotSyncResultV1:
    """Stage or update the world owner without enabling the product solve path."""

    if not isinstance(world, PhysicsWorldCache):
        raise TypeError("world must be PhysicsWorldCache")
    if not isinstance(collection, MC2MeshProductCollectionV1):
        raise TypeError("collection must be MC2MeshProductCollectionV1")
    generation = int(world.generation)
    existing = world.solver_slots.get(MC2_FUSED_MESH_SLOT_ID)
    reusable = (
        existing is not None
        and existing.kind == MC2_FUSED_MESH_SLOT_KIND
        and existing.world_generation == generation
        and isinstance(existing.data.get("owner"), MC2MeshFusedCPUOwnerV1)
        and existing.data["owner"].domain is not None
    )

    if reusable:
        world.acquire_write(_MC2_FUSED_MESH_WRITER)
        try:
            report = existing.data["owner"].sync(
                collection.draft,
                collection.static_snapshots,
                world_gravity_directions=collection.world_gravity_directions,
            )
            existing.data["collection"] = collection
            existing.data["last_sync"] = report
        finally:
            world.release_write(_MC2_FUSED_MESH_WRITER)
        return MC2FusedMeshSlotSyncResultV1(
            action="updated",
            slot_id=MC2_FUSED_MESH_SLOT_ID,
            world_generation=generation,
            owner_report=report,
        )

    if kernel is None:
        from .cpu_native_kernel import MC2NativeCPUKernelV1

        kernel = MC2NativeCPUKernelV1()
    staged_owner = MC2MeshFusedCPUOwnerV1(kernel)
    try:
        report = staged_owner.sync(
            collection.draft,
            collection.static_snapshots,
            world_gravity_directions=collection.world_gravity_directions,
        )
        staged_slot = _make_slot(world, staged_owner, collection, report)
    except Exception:
        staged_owner.dispose()
        raise

    world.acquire_write(_MC2_FUSED_MESH_WRITER)
    try:
        old_slot = world.solver_slots.get(MC2_FUSED_MESH_SLOT_ID)
        world.solver_slots[MC2_FUSED_MESH_SLOT_ID] = staged_slot
    finally:
        world.release_write(_MC2_FUSED_MESH_WRITER)
    if old_slot is not None:
        old_slot.dispose("mc2_fused_mesh_staged_replacement")
    return MC2FusedMeshSlotSyncResultV1(
        action="created" if old_slot is None else "replaced",
        slot_id=MC2_FUSED_MESH_SLOT_ID,
        world_generation=generation,
        owner_report=report,
    )


__all__ = [
    "MC2_FUSED_MESH_SLOT_ID",
    "MC2_FUSED_MESH_SLOT_KIND",
    "MC2FusedMeshSlotSyncResultV1",
    "sync_mc2_mesh_fused_slot",
]
