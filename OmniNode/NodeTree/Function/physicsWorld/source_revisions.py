"""Conservative Blender source revisions shared by Physics World consumers.

The tracker stores pointer-sized identities only.  It never retains Blender ID
objects or solver state, and Blender lifecycle registration stays in this
module's explicit ``register``/``unregister`` boundary.
"""

from __future__ import annotations

from dataclasses import dataclass


_REVISION_STRIDE = 1 << 32


@dataclass(frozen=True)
class GeometryUpdateReservation:
    source_pointer: int
    data_pointer: int
    serial: int


class BlenderSourceRevisionTracker:
    """Turns depsgraph geometry notifications into conservative revisions."""

    def __init__(self) -> None:
        self._epoch = 1
        self._event_serial = 0
        self._reservation_serial = 0
        self._source_revisions: dict[int, int] = {}
        self._data_revisions: dict[int, int] = {}
        self._pending_source: dict[int, list[int]] = {}
        self._pending_data: dict[int, list[int]] = {}

    @property
    def epoch(self) -> int:
        return self._epoch

    def revisions(self, source_pointer: int, data_pointer: int) -> tuple[int, int]:
        source_pointer = self._validated_pointer(source_pointer)
        data_pointer = self._validated_pointer(data_pointer)
        base = self._epoch * _REVISION_STRIDE
        return (
            base + self._source_revisions.get(source_pointer, 0),
            base + self._data_revisions.get(data_pointer, 0),
        )

    def reserve_internal_geometry_update(
        self,
        source_pointer: int,
        data_pointer: int,
    ) -> GeometryUpdateReservation:
        source_pointer = self._validated_pointer(source_pointer)
        data_pointer = self._validated_pointer(data_pointer)
        self._reservation_serial += 1
        serial = self._reservation_serial
        self._pending_source.setdefault(source_pointer, []).append(serial)
        self._pending_data.setdefault(data_pointer, []).append(serial)
        return GeometryUpdateReservation(source_pointer, data_pointer, serial)

    def cancel_reservation(self, reservation: GeometryUpdateReservation) -> None:
        if not isinstance(reservation, GeometryUpdateReservation):
            raise TypeError("reservation must be GeometryUpdateReservation")
        self._remove_pending(
            self._pending_source,
            reservation.source_pointer,
            reservation.serial,
        )
        self._remove_pending(
            self._pending_data,
            reservation.data_pointer,
            reservation.serial,
        )

    def process_geometry_updates(
        self,
        *,
        source_pointers=(),
        data_pointers=(),
    ) -> None:
        """Process one depsgraph batch, then expire all unused reservations."""

        self._event_serial += 1
        for pointer in set(int(value) for value in source_pointers):
            if pointer <= 0:
                continue
            if not self._consume_pending(self._pending_source, pointer):
                self._source_revisions[pointer] = (
                    self._source_revisions.get(pointer, 0) + 1
                )
        for pointer in set(int(value) for value in data_pointers):
            if pointer <= 0:
                continue
            if not self._consume_pending(self._pending_data, pointer):
                self._data_revisions[pointer] = self._data_revisions.get(pointer, 0) + 1
        self.expire_pending()

    def expire_pending(self) -> None:
        self._pending_source.clear()
        self._pending_data.clear()

    def invalidate_all(self) -> None:
        self._epoch += 1
        self._source_revisions.clear()
        self._data_revisions.clear()
        self.expire_pending()

    def inspect(self) -> dict:
        return {
            "schema": "physics_source_revisions_v1",
            "epoch": self._epoch,
            "event_serial": self._event_serial,
            "source_count": len(self._source_revisions),
            "data_count": len(self._data_revisions),
            "pending_source_count": sum(map(len, self._pending_source.values())),
            "pending_data_count": sum(map(len, self._pending_data.values())),
        }

    @staticmethod
    def _validated_pointer(pointer: int) -> int:
        value = int(pointer)
        if value <= 0:
            raise ValueError("Blender ID pointer must be positive")
        return value

    @staticmethod
    def _consume_pending(pending: dict[int, list[int]], pointer: int) -> bool:
        serials = pending.get(pointer)
        if not serials:
            return False
        serials.pop(0)
        if not serials:
            pending.pop(pointer, None)
        return True

    @staticmethod
    def _remove_pending(
        pending: dict[int, list[int]],
        pointer: int,
        serial: int,
    ) -> None:
        serials = pending.get(pointer)
        if not serials:
            return
        try:
            serials.remove(serial)
        except ValueError:
            return
        if not serials:
            pending.pop(pointer, None)


_TRACKER = BlenderSourceRevisionTracker()
_ACTIVE = False


def source_revision_tracker() -> BlenderSourceRevisionTracker:
    return _TRACKER


def source_revision_pair(source) -> tuple[int, int, bool]:
    """Return source/data revisions and whether depsgraph tracking is active."""

    data = getattr(source, "data", None)
    source_pointer = getattr(source, "as_pointer", None)
    data_pointer = getattr(data, "as_pointer", None)
    if not callable(source_pointer) or not callable(data_pointer):
        return 0, 0, False
    try:
        source_value = int(source_pointer())
        data_value = int(data_pointer())
    except Exception:
        return 0, 0, False
    if source_value <= 0 or data_value <= 0 or not _ACTIVE:
        return 0, 0, False
    source_revision, data_revision = _TRACKER.revisions(source_value, data_value)
    return source_revision, data_revision, True


def reserve_internal_geometry_update(source) -> GeometryUpdateReservation | None:
    data = getattr(source, "data", None)
    try:
        return _TRACKER.reserve_internal_geometry_update(
            int(source.as_pointer()),
            int(data.as_pointer()),
        )
    except Exception:
        return None


def cancel_internal_geometry_update(
    reservation: GeometryUpdateReservation | None,
) -> None:
    if reservation is not None:
        _TRACKER.cancel_reservation(reservation)


def _depsgraph_update_post(_scene, depsgraph) -> None:
    try:
        import bpy
    except ImportError:
        return
    source_pointers = []
    data_pointers = []
    for update in getattr(depsgraph, "updates", ()):
        if not bool(getattr(update, "is_updated_geometry", False)):
            continue
        evaluated_item = getattr(update, "id", None)
        item = getattr(evaluated_item, "original", None) or evaluated_item
        pointer = getattr(item, "as_pointer", None)
        if not callable(pointer):
            continue
        try:
            value = int(pointer())
        except Exception:
            continue
        if isinstance(item, bpy.types.Object):
            source_pointers.append(value)
        elif isinstance(item, bpy.types.Mesh):
            data_pointers.append(value)
    _TRACKER.process_geometry_updates(
        source_pointers=source_pointers,
        data_pointers=data_pointers,
    )


def _invalidate_source_revisions(*_args) -> None:
    _TRACKER.invalidate_all()


def register() -> None:
    global _ACTIVE
    if _ACTIVE:
        return
    import bpy
    from bpy.app.handlers import persistent

    persistent(_depsgraph_update_post)
    persistent(_invalidate_source_revisions)
    registrations = (
        (bpy.app.handlers.depsgraph_update_post, _depsgraph_update_post),
        (bpy.app.handlers.undo_post, _invalidate_source_revisions),
        (bpy.app.handlers.redo_post, _invalidate_source_revisions),
        (bpy.app.handlers.load_post, _invalidate_source_revisions),
    )
    for handlers, callback in registrations:
        if callback not in handlers:
            handlers.append(callback)
    _TRACKER.invalidate_all()
    _ACTIVE = True


def unregister() -> None:
    global _ACTIVE
    if not _ACTIVE:
        return
    import bpy

    registrations = (
        (bpy.app.handlers.depsgraph_update_post, _depsgraph_update_post),
        (bpy.app.handlers.undo_post, _invalidate_source_revisions),
        (bpy.app.handlers.redo_post, _invalidate_source_revisions),
        (bpy.app.handlers.load_post, _invalidate_source_revisions),
    )
    for handlers, callback in registrations:
        while callback in handlers:
            handlers.remove(callback)
    _TRACKER.invalidate_all()
    _ACTIVE = False


__all__ = [
    "BlenderSourceRevisionTracker",
    "GeometryUpdateReservation",
    "cancel_internal_geometry_update",
    "register",
    "reserve_internal_geometry_update",
    "source_revision_pair",
    "source_revision_tracker",
    "unregister",
]
