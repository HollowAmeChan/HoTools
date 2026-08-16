"""Explicit rigid-fracture asset component consumed by the Jolt rigid solver."""

from __future__ import annotations

from importlib import import_module


COMPONENT_MODULE = {
    "component_id": "rigid_fracture",
    "kind": "core",
    "depends_on": (),
    "blender_properties": ".properties:RIGID_FRACTURE_BLENDER_PROPERTIES",
}


_EXPORTS = {
    "PG_Hotools_RigidFracture": ".properties",
    "PG_Hotools_RigidFracturePiece": ".properties",
    "RIGID_FRACTURE_BLENDER_PROPERTIES": ".properties",
    "FRACTURE_GENERATOR_VERSION": ".geometry_nodes",
    "FRACTURE_PIECE_ID_ATTRIBUTE": ".geometry_nodes",
    "build_grid_fracture_group": ".geometry_nodes",
    "is_managed_fracture_group": ".geometry_nodes",
    "set_grid_modifier_inputs": ".geometry_nodes",
    "FractureAssetError": ".authoring",
    "apply_piece_defaults": ".authoring",
    "ensure_asset_id": ".authoring",
    "ensure_default_fracture_modifier": ".authoring",
    "ensure_product_collection": ".authoring",
    "managed_pieces": ".authoring",
    "refresh_fracture_products": ".authoring",
    "select_managed_pieces": ".authoring",
    "set_fracture_visibility": ".authoring",
    "validate_fracture_manifest": ".authoring",
    "FRACTURE_SCOPE_SIGNATURE_RESOURCE_KEY": ".resolver",
    "FRACTURE_SLOT_INDEX_RESOURCE_KEY": ".resolver",
    "resolve_fracture_scope_objects": ".resolver",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = ["COMPONENT_MODULE", *sorted(_EXPORTS)]
