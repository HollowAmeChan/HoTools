"""MeshCloth setup adapter registration."""

from ....names import GN_ATTRIBUTE_CHANNEL
from ...names import MC2_SETUP_MESH_CLOTH
from ...topology import build_mc2_mesh_source_topology
from ..contracts import MC2SetupAdapterContract


MC2_MESH_CLOTH_SETUP_ADAPTER = MC2SetupAdapterContract(
    setup_type=MC2_SETUP_MESH_CLOTH,
    source_kind="mesh_object",
    writeback_channel=GN_ATTRIBUTE_CHANNEL,
    topology_builder=build_mc2_mesh_source_topology,
)


__all__ = ["MC2_MESH_CLOTH_SETUP_ADAPTER"]
