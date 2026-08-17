"""Rigid-only scope expansion for explicit fracture assets."""

from .authoring import FractureAssetError, validate_fracture_manifest


FRACTURE_SCOPE_SIGNATURE_RESOURCE_KEY = "rigid.fracture.scope_signature"
FRACTURE_SLOT_INDEX_RESOURCE_KEY = "rigid.fracture.slot_index"


def _flatten_objects(values) -> list:
    result = []
    stack = list(reversed(values)) if isinstance(values, (list, tuple)) else [values]
    while stack:
        value = stack.pop()
        if isinstance(value, (list, tuple)):
            stack.extend(reversed(value))
        elif value is not None:
            result.append(value)
    return result


def _has_committed_fracture_products(props) -> bool:
    """Return whether the linked collection contains any managed product."""
    collection = getattr(props, "product_collection", None)
    if collection is None:
        return False
    for obj in collection.all_objects:
        piece = getattr(obj, "hotools_rigid_fracture_piece", None)
        if piece is not None and bool(getattr(piece, "managed", False)):
            return True
    return False


def resolve_fracture_scope_objects(objects) -> tuple[tuple, dict[int, dict], tuple]:
    """Return the rigid-only object view, piece metadata, and manifest signature."""
    original = _flatten_objects(objects)
    sources = []
    owner_sources = {}
    for obj in original:
        props = getattr(obj, "hotools_rigid_fracture", None)
        if props is None or not bool(getattr(props, "enabled", False)):
            continue
        if not _has_committed_fracture_products(props):
            # Authoring state and stale manifest metadata are not physical
            # products. Keep the source usable until managed pieces exist.
            continue
        asset_id = str(getattr(props, "asset_id", "") or "").strip()
        if asset_id and asset_id in owner_sources:
            other = owner_sources[asset_id]
            raise FractureAssetError(
                f"破碎 asset_id 重复: {other.name_full} / {obj.name_full}"
            )
        # A committed collection remains a usable simulation asset while its
        # preview is OUTDATED.  Refreshing is still explicit in the authoring
        # UI; runtime must not silently drop the entire world in the meantime.
        pieces = validate_fracture_manifest(obj, allow_outdated=True)
        owner_sources[asset_id] = obj
        sources.append((obj, props, pieces))

    if not sources:
        seen = set()
        deduped = []
        for obj in original:
            try:
                pointer = int(obj.as_pointer())
            except Exception:
                continue
            if pointer and pointer not in seen:
                seen.add(pointer)
                deduped.append(obj)
        return tuple(deduped), {}, ()

    active_owner_ids = set(owner_sources)
    expansion_by_pointer = {int(source.as_pointer()): pieces for source, _props, pieces in sources}
    result = []
    metadata_by_pointer = {}
    seen = set()

    def append_object(obj, metadata=None):
        try:
            pointer = int(obj.as_pointer())
        except Exception:
            return
        if not pointer or pointer in seen:
            return
        seen.add(pointer)
        result.append(obj)
        if metadata is not None:
            metadata_by_pointer[pointer] = metadata

    for obj in original:
        pointer = int(obj.as_pointer())
        pieces = expansion_by_pointer.get(pointer)
        if pieces is not None:
            source_props = obj.hotools_rigid_fracture
            for piece_obj in pieces:
                piece = piece_obj.hotools_rigid_fracture_piece
                append_object(piece_obj, {
                    "source": obj,
                    "asset_id": str(source_props.asset_id),
                    "piece_id": str(piece.piece_id),
                    "product_revision": int(piece.product_revision),
                    "breakable": bool(piece.breakable),
                })
            continue

        piece = getattr(obj, "hotools_rigid_fracture_piece", None)
        if (
            piece is not None
            and bool(getattr(piece, "managed", False))
            and str(getattr(piece, "owner_asset_id", "") or "") in active_owner_ids
        ):
            continue
        append_object(obj)

    signature = []
    for source, props, pieces in sources:
        collection = props.product_collection
        piece_entries = []
        for piece_obj in pieces:
            data = getattr(piece_obj, "data", None)
            piece_entries.append((
                str(piece_obj.hotools_rigid_fracture_piece.piece_id),
                int(piece_obj.as_pointer()),
                int(data.as_pointer()) if data is not None else 0,
            ))
        signature.append((
            int(source.as_pointer()),
            str(props.asset_id),
            int(props.product_revision),
            int(collection.as_pointer()),
            tuple(piece_entries),
        ))
    return tuple(result), metadata_by_pointer, tuple(signature)


__all__ = [
    "FRACTURE_SCOPE_SIGNATURE_RESOURCE_KEY",
    "FRACTURE_SLOT_INDEX_RESOURCE_KEY",
    "resolve_fracture_scope_objects",
]
