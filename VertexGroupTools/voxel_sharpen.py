"""NumPy-only voxel sharpening for selected vertex-group values.

The module deliberately has no Blender dependency.  It is intended to be the
numerical core used by the vertex-group operators, while keeping the operator
responsible for reading and writing Blender's deform layers.

Only selected vertices participate in the calculation.  In particular, the
positions and weights of unselected vertices are never indexed or inspected.
Edges are filtered to selected endpoints and become the only links between
occupied voxels.  This gives the voxel field a topology-aware sparse graph
without allowing an unselected vertex to become a source or a destination.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping, Sequence

import numpy as np


ArrayLike = Any


@dataclass(frozen=True)
class VoxelSharpenResult:
    """Result of :func:`sharpen_weights`.

    ``selected_indices`` has the same order as the caller's selected index
    sequence (a boolean mask is converted to ascending indices).  ``weights``
    is one-dimensional for a single group and ``(M, G)`` for multiple groups,
    where ``M`` is the number of selected vertices.  ``diagnostics`` contains
    grid and sampling details useful for an operator report or debug panel.
    """

    selected_indices: np.ndarray
    weights: np.ndarray
    diagnostics: Mapping[str, Any]

    @property
    def weight_map(self) -> dict[int, np.ndarray | float]:
        """Return a global vertex-index -> weight mapping."""

        result: dict[int, np.ndarray | float] = {}
        if self.weights.ndim == 1:
            for index, value in zip(self.selected_indices, self.weights):
                result[int(index)] = float(value)
        else:
            for row, index in zip(self.weights, self.selected_indices):
                result[int(index)] = np.asarray(row).copy()
        return result

    @property
    def weights_by_index(self) -> dict[int, np.ndarray | float]:
        """Compatibility alias for :attr:`weight_map`."""

        return self.weight_map

    def __iter__(self) -> Iterator[Any]:
        """Allow ``indices, weights, diagnostics = result`` unpacking."""

        yield self.selected_indices
        yield self.weights
        yield self.diagnostics


class VoxelSharpenError(ValueError):
    """Raised when voxel-sharpen inputs cannot be interpreted safely."""


def _as_float_array(value: ArrayLike, name: str) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise VoxelSharpenError(f"{name} must be a numeric array") from exc
    if array.ndim == 0:
        raise VoxelSharpenError(f"{name} must be an array")
    return array


def _selected_indices(selected: ArrayLike, count: int) -> np.ndarray:
    """Normalize a mask/index input without touching vertex data."""

    if selected is None:
        raise VoxelSharpenError("selected mask or indices are required")

    raw = np.asarray(selected)
    if raw.ndim != 1:
        raise VoxelSharpenError("selected must be a one-dimensional mask or index array")

    if raw.dtype == np.bool_:
        if raw.size != count:
            raise VoxelSharpenError("selected mask length must match positions")
        indices = np.flatnonzero(raw)
    else:
        # Integer-valued floats are accepted because Blender-side lists often
        # arrive through generic numeric properties.  Fractional values are not.
        try:
            numeric = np.asarray(raw, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise VoxelSharpenError("selected indices must be integers") from exc
        if numeric.size and (not np.all(np.isfinite(numeric)) or not np.all(numeric == np.floor(numeric))):
            raise VoxelSharpenError("selected indices must be finite integers")
        indices = numeric.astype(np.int64, copy=False)
        if np.any(indices < 0) or np.any(indices >= count):
            raise VoxelSharpenError("selected index is outside the positions array")
        if np.unique(indices).size != indices.size:
            raise VoxelSharpenError("selected indices must not contain duplicates")

    if indices.size == 0:
        raise VoxelSharpenError("at least one vertex must be selected")
    return np.asarray(indices, dtype=np.int64)


def _validate_edges(edges: ArrayLike, count: int, selected_set: set[int]) -> np.ndarray:
    if edges is None:
        return np.empty((0, 2), dtype=np.int64)
    raw = np.asarray(edges)
    if raw.size == 0:
        return np.empty((0, 2), dtype=np.int64)
    if raw.ndim != 2 or raw.shape[1] != 2:
        raise VoxelSharpenError("edges must have shape (E, 2)")
    try:
        numeric = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise VoxelSharpenError("edges must contain integer vertex indices") from exc
    if not np.all(np.isfinite(numeric)) or not np.all(numeric == np.floor(numeric)):
        raise VoxelSharpenError("edges must contain finite integer vertex indices")
    integer = numeric.astype(np.int64, copy=False)
    if np.any(integer < 0) or np.any(integer >= count):
        raise VoxelSharpenError("edge endpoint is outside the positions array")

    # Filtering happens before any positions or weights are indexed.  Thus an
    # edge touching an unselected vertex cannot pull that vertex into the field.
    keep = np.fromiter(
        (int(a) in selected_set and int(b) in selected_set and int(a) != int(b)
         for a, b in integer),
        dtype=bool,
        count=integer.shape[0],
    )
    filtered = integer[keep]
    if filtered.size == 0:
        return np.empty((0, 2), dtype=np.int64)

    # Duplicate/reversed edges only add redundant samples and make coverage
    # depend on input ordering, so canonicalize them.
    canonical = np.sort(filtered, axis=1)
    return np.unique(canonical, axis=0)


def _voxel_index(coord: np.ndarray, shape: tuple[int, int, int]) -> tuple[int, int, int]:
    index = np.rint(coord).astype(np.int64)
    index = np.clip(index, 0, np.asarray(shape, dtype=np.int64) - 1)
    return int(index[0]), int(index[1]), int(index[2])


def _topology_blur(
    field: np.ndarray,
    support: np.ndarray,
    links: Mapping[int, set[int]] | np.ndarray,
    radius: int,
) -> np.ndarray:
    """Blur only across voxel links rasterized from selected mesh edges.

    A regular 3-D convolution is deliberately avoided here.  It would allow
    two selected surfaces that happen to be close in space to exchange weight
    even when the mesh has no edge between them.  ``links`` is the voxelized
    selected-topology graph, so the spatial field remains topology bounded.
    """

    if radius <= 0 or not links:
        return field.copy()

    flat_field = field.reshape((-1, field.shape[-1]))
    flat_support = support.reshape(-1)
    result = np.zeros_like(flat_field)
    result[flat_support] = flat_field[flat_support]
    radius = int(radius)

    # Convert the selected-topology voxel graph to a compact edge list once.
    # The old implementation ran a Python BFS from every support voxel.  A
    # Jacobi diffusion pass has the same topology hard-gate, while reducing
    # the work to O(radius * links * groups) and letting NumPy do the inner
    # accumulation.  The self term and exponential edge weight approximate
    # the old graph-distance kernel without ever crossing an unlinked voxel.
    if isinstance(links, np.ndarray):
        link_array = np.asarray(links, dtype=np.int64)
        if link_array.size == 0:
            return result.reshape(field.shape)
        link_array = link_array.reshape((-1, 2))
    else:
        pairs = [
            (int(source), int(destination))
            for source, neighbors in links.items()
            if flat_support[int(source)]
            for destination in neighbors
            if int(destination) != int(source) and flat_support[int(destination)]
        ]
        if not pairs:
            return result.reshape(field.shape)
        link_array = np.asarray(pairs, dtype=np.int64)

    in_bounds = (
        (link_array[:, 0] >= 0)
        & (link_array[:, 0] < flat_support.size)
        & (link_array[:, 1] >= 0)
        & (link_array[:, 1] < flat_support.size)
    )
    link_array = link_array[in_bounds]
    if link_array.size:
        valid = (
            flat_support[link_array[:, 0]]
            & flat_support[link_array[:, 1]]
            & (link_array[:, 0] != link_array[:, 1])
        )
        link_array = link_array[valid]
    if link_array.size == 0:
        return result.reshape(field.shape)
    # Duplicate links would bias a voxel by the number of rasterized edges
    # passing through it.  Canonicalization is cheap compared with the old
    # per-voxel BFS and keeps the blur independent of mesh edge ordering.
    link_array = np.unique(np.sort(link_array, axis=1), axis=0)
    source = np.concatenate((link_array[:, 0], link_array[:, 1]))
    destination = np.concatenate((link_array[:, 1], link_array[:, 0]))
    neighbor_weight = float(np.exp(-1.0 / max(float(radius), 1.0)))

    for _ in range(radius):
        accumulated = result.copy()
        np.add.at(accumulated, source, result[destination] * neighbor_weight)
        denominator = np.ones(flat_support.size, dtype=np.float64)
        np.add.at(denominator, source, neighbor_weight)
        result[flat_support] = accumulated[flat_support] / denominator[flat_support, None]
        result[~flat_support] = 0.0

    return result.reshape(field.shape)


def _resolution_tuple(
    resolution: int | Sequence[int],
    extents: np.ndarray,
    max_voxels: int,
    padding: int = 1,
) -> tuple[tuple[int, int, int], np.ndarray, np.ndarray]:
    """Return ``(grid_shape, spacing, base_resolution)`` with a bounded cell count."""

    if isinstance(resolution, (int, np.integer)):
        requested = (int(resolution),) * 3
    else:
        try:
            requested = tuple(int(v) for v in resolution)
        except (TypeError, ValueError) as exc:
            raise VoxelSharpenError("resolution must be an integer or a 3-item sequence") from exc
        if len(requested) != 3:
            raise VoxelSharpenError("resolution must be an integer or a 3-item sequence")
    if any(v < 2 for v in requested):
        raise VoxelSharpenError("each resolution dimension must be at least 2")
    if not isinstance(max_voxels, (int, np.integer)) or int(max_voxels) < 27:
        raise VoxelSharpenError("max_voxels must be an integer >= 27")
    max_voxels = int(max_voxels)

    # A common isotropic spacing is preferable for line rasterization.  A
    # degenerate axis still receives a small, explicit three-cell slab.
    finite_extents = np.maximum(np.asarray(extents, dtype=np.float64), 0.0)
    longest = float(np.max(finite_extents))
    if longest <= np.finfo(np.float64).eps:
        base = np.array([2, 2, 2], dtype=np.int64)
        spacing = np.full(3, 1.0, dtype=np.float64)
    else:
        base = np.maximum(
            2,
            np.rint(np.asarray(requested, dtype=np.float64) * finite_extents / longest).astype(np.int64),
        )

    base_product = int(np.prod(base + 2 * padding, dtype=np.int64))
    if base_product > max_voxels:
        scale = (float(max_voxels) / float(base_product)) ** (1.0 / 3.0)
        base = np.maximum(2, np.floor(base * scale).astype(np.int64))
        while int(np.prod(base + 2 * padding, dtype=np.int64)) > max_voxels:
            axis = int(np.argmax(base))
            if base[axis] <= 2:
                break
            base[axis] -= 1

    shape = tuple(int(v + 2 * padding) for v in base)
    if int(np.prod(shape, dtype=np.int64)) > max_voxels:
        raise VoxelSharpenError("requested resolution cannot fit max_voxels")

    # Keep one padding cell around selected points.  For a zero extent axis,
    # use the common spacing so all points land in the center slab.
    if longest > np.finfo(np.float64).eps:
        spacing = np.full(3, longest / max(int(np.max(base)) - 1, 1), dtype=np.float64)
    spacing = np.where(spacing > np.finfo(np.float64).eps, spacing, 1.0)
    return shape, spacing, base


def _grid_coordinates(points: np.ndarray, origin: np.ndarray, spacing: np.ndarray, shape: tuple[int, int, int]) -> np.ndarray:
    coords = (points - origin[None, :]) / spacing[None, :]
    return np.clip(coords, 0.0, np.asarray(shape, dtype=np.float64)[None, :] - 1.0)


def _sparse_resolution_tuple(
    resolution: int | Sequence[int],
    extents: np.ndarray,
) -> tuple[tuple[int, int, int], np.ndarray, np.ndarray]:
    """Resolve a grid transform without allocating or bounding a dense grid."""

    if isinstance(resolution, (int, np.integer)):
        requested = (int(resolution),) * 3
    else:
        try:
            requested = tuple(int(value) for value in resolution)
        except (TypeError, ValueError) as exc:
            raise VoxelSharpenError(
                "resolution must be an integer or a 3-item sequence"
            ) from exc
        if len(requested) != 3:
            raise VoxelSharpenError(
                "resolution must be an integer or a 3-item sequence"
            )
    if any(value < 2 for value in requested):
        raise VoxelSharpenError("each resolution dimension must be at least 2")

    finite_extents = np.maximum(np.asarray(extents, dtype=np.float64), 0.0)
    longest = float(np.max(finite_extents))
    if longest <= np.finfo(np.float64).eps:
        base = np.array([2, 2, 2], dtype=np.int64)
        spacing = np.ones(3, dtype=np.float64)
    else:
        base = np.maximum(
            2,
            np.rint(
                np.asarray(requested, dtype=np.float64)
                * finite_extents
                / longest
            ).astype(np.int64),
        )
        spacing = np.full(
            3,
            longest / max(int(np.max(base)) - 1, 1),
            dtype=np.float64,
        )
    shape = tuple(int(value + 2) for value in base)
    return shape, spacing, base


def _splat_point(
    coord: np.ndarray,
    value: np.ndarray,
    field_sum: np.ndarray,
    coverage: np.ndarray,
) -> None:
    """Trilinearly splat one scalar/vector sample into the voxel field."""
    _splat_points(
        np.asarray(coord, dtype=np.float64).reshape(1, 3),
        np.asarray(value, dtype=np.float64).reshape(1, -1),
        field_sum,
        coverage,
    )


def _splat_points(
    coordinates: np.ndarray,
    values: np.ndarray,
    field_sum: np.ndarray,
    coverage: np.ndarray,
) -> None:
    """Batch trilinear splatting with duplicate-safe NumPy accumulation."""

    coordinates = np.asarray(coordinates, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    if coordinates.size == 0:
        return
    if coordinates.ndim != 2 or coordinates.shape[1] != 3:
        raise VoxelSharpenError("splat coordinates must have shape (M, 3)")
    if values.ndim != 2 or values.shape[0] != coordinates.shape[0]:
        raise VoxelSharpenError("splat values must have shape (M, G)")
    if field_sum.ndim != 4 or field_sum.shape[:3] != coverage.shape:
        raise VoxelSharpenError("splat field shape does not match coverage")

    shape = np.asarray(coverage.shape, dtype=np.int64)
    lower = np.floor(coordinates).astype(np.int64)
    fraction = coordinates - lower
    flat_coverage = coverage.reshape(-1)
    flat_field = field_sum.reshape((-1, field_sum.shape[-1]))
    offsets = np.asarray(
        [(bits & 1, (bits >> 1) & 1, (bits >> 2) & 1) for bits in range(8)],
        dtype=np.float64,
    )
    for offset in offsets:
        indices = lower + offset.astype(np.int64)[None, :]
        valid = np.all((indices >= 0) & (indices < shape[None, :]), axis=1)
        if not np.any(valid):
            continue
        kernels = np.prod(
            np.where(offset[None, :], fraction, 1.0 - fraction), axis=1
        )
        valid &= kernels > 0.0
        if not np.any(valid):
            continue
        flat_indices = np.ravel_multi_index(indices[valid].T, tuple(shape))
        kernel_values = kernels[valid]
        np.add.at(flat_coverage, flat_indices, kernel_values)
        np.add.at(flat_field, flat_indices, kernel_values[:, None] * values[valid])


def _sample_segment_count(a: np.ndarray, b: np.ndarray, spacing: np.ndarray) -> int:
    distance = float(np.linalg.norm(b - a))
    step = max(float(np.min(spacing)), np.finfo(np.float64).eps)
    return max(2, int(np.ceil(distance / step)) + 1)


def _shifted_view(array: np.ndarray, offset: tuple[int, int, int], radius: int) -> np.ndarray:
    """Return an out-of-bounds-zero shifted view with no wraparound."""

    pad_width = ((radius, radius), (radius, radius), (radius, radius))
    if array.ndim == 4:
        pad_width += ((0, 0),)
    padded = np.pad(array, pad_width, mode="constant", constant_values=0.0)
    slices = []
    for axis, delta in enumerate(offset):
        start = radius + delta
        slices.append(slice(start, start + array.shape[axis]))
    if array.ndim == 4:
        slices.append(slice(None))
    return padded[tuple(slices)]


def _local_blur(field: np.ndarray, support: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return field.copy()
    result = np.zeros_like(field)
    denominator = np.zeros(support.shape, dtype=np.float64)

    offsets: list[tuple[int, int, int, float]] = []
    sigma = max(float(radius), 0.5)
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                distance2 = float(dx * dx + dy * dy + dz * dz)
                if distance2 > float(radius * radius):
                    continue
                offsets.append((dx, dy, dz, float(np.exp(-distance2 / (2.0 * sigma * sigma)))))

    for dx, dy, dz, kernel in offsets:
        source_support = _shifted_view(support.astype(np.float64), (dx, dy, dz), radius) > 0.0
        source = _shifted_view(field, (dx, dy, dz), radius)
        result += source * (source_support[..., None] * kernel)
        denominator += source_support * kernel

    valid = denominator > np.finfo(np.float64).eps
    if field.ndim == 4:
        result[valid] /= denominator[valid, None]
        result[~valid] = 0.0
    else:
        result[valid] /= denominator[valid]
        result[~valid] = 0.0
    return result


def _sample_field(
    field: np.ndarray,
    support: np.ndarray,
    points: np.ndarray,
    origin: np.ndarray,
    spacing: np.ndarray,
) -> np.ndarray:
    coords = _grid_coordinates(points, origin, spacing, support.shape)
    channels = 1 if field.ndim == 3 else int(field.shape[-1])
    result = np.zeros((points.shape[0], channels), dtype=np.float64)
    support_sum = np.zeros(points.shape[0], dtype=np.float64)
    shape = np.asarray(support.shape, dtype=np.int64)
    lower = np.floor(coords).astype(np.int64)
    fraction = coords - lower
    flat_support = support.reshape(-1)
    flat_field = field.reshape((-1, channels))
    offsets = np.asarray(
        [(bits & 1, (bits >> 1) & 1, (bits >> 2) & 1) for bits in range(8)],
        dtype=np.float64,
    )

    # Coordinates are clipped before indexing, matching the previous
    # boundary behavior while evaluating all selected samples in NumPy.
    for offset in offsets:
        indices = np.clip(
            lower + offset.astype(np.int64)[None, :], 0, shape[None, :] - 1
        )
        kernels = np.prod(
            np.where(offset[None, :], fraction, 1.0 - fraction), axis=1
        )
        flat_indices = np.ravel_multi_index(indices.T, tuple(shape))
        valid = flat_support[flat_indices] & (kernels > 0.0)
        if not np.any(valid):
            continue
        result[valid] += flat_field[flat_indices[valid]] * kernels[valid, None]
        support_sum[valid] += kernels[valid]

    if field.ndim == 3:
        return result[:, 0], support_sum
    return result, support_sum


def _normalize_rows(values: np.ndarray, target: np.ndarray) -> np.ndarray:
    clipped = np.maximum(values, 0.0)
    sums = np.sum(clipped, axis=1)
    result = np.zeros_like(clipped)
    valid = (sums > np.finfo(np.float64).eps) & (target > np.finfo(np.float64).eps)
    result[valid] = clipped[valid] * (target[valid, None] / sums[valid, None])
    return result


def _connected_components(count: int, edges: np.ndarray) -> list[np.ndarray]:
    """Return local vertex-index components induced by selected edges."""

    adjacency: list[list[int]] = [[] for _ in range(count)]
    for first, second in edges:
        a, b = int(first), int(second)
        adjacency[a].append(b)
        adjacency[b].append(a)

    visited = np.zeros(count, dtype=bool)
    components: list[np.ndarray] = []
    for start in range(count):
        if visited[start]:
            continue
        stack = [start]
        visited[start] = True
        members: list[int] = []
        while stack:
            current = stack.pop()
            members.append(current)
            for neighbor in adjacency[current]:
                if not visited[neighbor]:
                    visited[neighbor] = True
                    stack.append(neighbor)
        components.append(np.asarray(sorted(members), dtype=np.int64))
    return components


def _legacy_sharpen_weights(
    positions: ArrayLike,
    weights: ArrayLike,
    selected: ArrayLike,
    edges: ArrayLike = None,
    *,
    resolution: int | Sequence[int] = 32,
    strength: float = 1.0,
    blur_radius: int = 1,
    iterations: int = 1,
    topology_hops: int | None = 2,
    max_voxels: int = 250_000,
    normalize: bool = True,
    normalization_target: str | float | ArrayLike = "input_sum",
    clamp: bool = True,
) -> VoxelSharpenResult:
    """Sharpen selected vertex weights through a local voxel scalar field.

    Parameters
    ----------
    positions:
        ``(N, 3)`` vertex coordinates.
    weights:
        ``(N,)`` for one group or ``(N, G)`` for multiple groups.
    selected:
        Boolean ``(N,)`` mask or a sequence of global vertex indices.  Only
        these vertices are ever indexed for numerical processing.
    edges:
        Optional ``(E, 2)`` global edge indices.  Only edges whose two
        endpoints are selected are rasterized.
    resolution:
        Maximum grid resolution.  An integer preserves aspect ratio; a
        three-item sequence specifies per-axis base resolutions.
    strength:
        Unsharp amount. Zero returns a copy of the selected input weights.
    blur_radius / iterations:
        Radius and number of local Gaussian blur passes used by unsharp mask.
    topology_hops:
        Reserved topology budget for the local filter.  Connected components
        are always processed independently (the hard gate).  A finite value
        also caps the voxel blur radius, preventing a large spatial kernel
        from reaching farther than the requested local topology budget.
        ``None`` disables that additional cap.
    max_voxels:
        Hard upper bound for the allocated voxel support grid.
    normalize:
        For multi-group values, preserve each selected vertex's input row sum.
    normalization_target:
        ``"input_sum"`` (default), ``"one"``, a scalar, or one target per
        selected vertex.

    Returns
    -------
    VoxelSharpenResult
        Selected indices, sharpened values, and diagnostics.  The result can
        also be unpacked as ``indices, values, diagnostics``.
    """

    try:
        positions_array = np.asarray(positions)
    except (TypeError, ValueError) as exc:
        raise VoxelSharpenError("positions must be an array-like value") from exc
    if positions_array.ndim != 2 or positions_array.shape[1] != 3:
        raise VoxelSharpenError("positions must have shape (N, 3)")
    count = int(positions_array.shape[0])

    try:
        weights_array = np.asarray(weights)
    except (TypeError, ValueError) as exc:
        raise VoxelSharpenError("weights must be an array-like value") from exc
    if weights_array.ndim not in (1, 2) or weights_array.shape[0] != count:
        raise VoxelSharpenError("weights must have shape (N,) or (N, G)")
    group_count = 1 if weights_array.ndim == 1 else int(weights_array.shape[1])
    if group_count < 1:
        raise VoxelSharpenError("weights must contain at least one group")

    selected_indices = _selected_indices(selected, count)
    selected_set = set(int(index) for index in selected_indices)
    try:
        # Numeric conversion is intentionally delayed until after indexing.
        # Unselected rows are never parsed, copied, or checked for finiteness.
        selected_positions = np.asarray(positions_array[selected_indices], dtype=np.float64).copy()
        selected_weights = np.asarray(weights_array[selected_indices], dtype=np.float64).copy()
    except (TypeError, ValueError) as exc:
        raise VoxelSharpenError("selected positions and weights must be numeric") from exc

    # Crucially, finite checks are performed only after selecting rows.  NaN,
    # infinity, or arbitrary sentinels in unselected rows are never consumed.
    if not np.all(np.isfinite(selected_positions)):
        raise VoxelSharpenError("selected positions must be finite")
    if not np.all(np.isfinite(selected_weights)):
        raise VoxelSharpenError("selected weights must be finite")

    edge_array_global = _validate_edges(edges, count, selected_set)
    # Internally use the compact selected-row domain.  This matters when the
    # caller passes global vertex indices with a sparse selection: component
    # extraction must never allocate or index by an unselected vertex id.
    selected_local_index = {
        int(global_index): local_index
        for local_index, global_index in enumerate(selected_indices)
    }
    if edge_array_global.size:
        edge_array = np.asarray(
            [
                (selected_local_index[int(first)], selected_local_index[int(second)])
                for first, second in edge_array_global
            ],
            dtype=np.int64,
        )
    else:
        edge_array = np.empty((0, 2), dtype=np.int64)
    requested_strength = float(strength)
    if not np.isfinite(requested_strength):
        raise VoxelSharpenError("strength must be finite")
    if not isinstance(blur_radius, (int, np.integer)) or int(blur_radius) < 0:
        raise VoxelSharpenError("blur_radius must be an integer >= 0")
    if not isinstance(iterations, (int, np.integer)) or int(iterations) < 1:
        raise VoxelSharpenError("iterations must be an integer >= 1")
    if topology_hops is not None and (
        not isinstance(topology_hops, (int, np.integer)) or int(topology_hops) < 0
    ):
        raise VoxelSharpenError("topology_hops must be None or an integer >= 0")

    original_shape = selected_weights.shape
    field_values = selected_weights[:, None] if selected_weights.ndim == 1 else selected_weights
    if requested_strength == 0.0:
        output = selected_weights.copy()
        diagnostics = {
            "selected_count": int(selected_indices.size),
            "group_count": group_count,
            "edge_count": int(edge_array.shape[0]),
            "grid_shape": (0, 0, 0),
            "voxel_count": 0,
            "support_voxels": 0,
            "coverage_nonzero": 0,
            "resolution_requested": resolution,
            "max_voxels": int(max_voxels),
            "strength": requested_strength,
            "blur_radius": int(blur_radius),
            "iterations": int(iterations),
            "topology_hops": None if topology_hops is None else int(topology_hops),
            "component_count": int(selected_indices.size),
            "normalization": "none (zero strength)",
        }
        return VoxelSharpenResult(selected_indices.copy(), output, diagnostics)

    mins = np.min(selected_positions, axis=0)
    maxs = np.max(selected_positions, axis=0)
    extents = maxs - mins
    grid_shape, spacing, base_resolution = _resolution_tuple(resolution, extents, max_voxels)
    origin = mins - spacing

    components = _connected_components(int(selected_indices.size), edge_array)

    # Process each topology component in its own local grid.  This is the hard
    # topology gate: two nearby but disconnected surfaces never share a blur
    # denominator, even when their world-space voxels overlap.
    output_values = field_values.copy()
    sample_support = np.zeros(selected_indices.size, dtype=np.float64)
    edge_sample_count = 0
    support_voxels_total = 0
    coverage_values: list[np.ndarray] = []
    effective_blur_radius = int(blur_radius)
    if topology_hops is not None:
        effective_blur_radius = min(effective_blur_radius, int(topology_hops))

    global_local_index = {int(index): local for local, index in enumerate(selected_indices)}
    for members in components:
        component_positions = selected_positions[members]
        component_values = field_values[members]
        component_mins = np.min(component_positions, axis=0)
        component_extents = np.max(component_positions, axis=0) - component_mins
        # Allocate each topology component from its own extent. A distant
        # selected island must not make a small island's voxel spacing coarse.
        component_shape, component_spacing, _component_resolution = _resolution_tuple(
            resolution, component_extents, max_voxels
        )
        component_origin = component_mins - component_spacing
        component_coords = _grid_coordinates(
            component_positions, component_origin, component_spacing, component_shape
        )
        component_field_sum = np.zeros(component_shape + (group_count,), dtype=np.float64)
        component_coverage = np.zeros(component_shape, dtype=np.float64)
        # All selected points are splatted in one duplicate-safe NumPy call.
        # This replaces eight Python updates per vertex.
        _splat_points(
            component_coords,
            component_values,
            component_field_sum,
            component_coverage,
        )

        member_set = set(int(member) for member in members)
        component_edges = edge_array[
            np.asarray(
                [int(first) in member_set and int(second) in member_set
                 for first, second in edge_array],
                dtype=bool,
            )
        ]
        member_to_component = {int(member): row for row, member in enumerate(members)}
        topology_link_chunks: list[np.ndarray] = []
        edge_coord_chunks: list[np.ndarray] = []
        edge_value_chunks: list[np.ndarray] = []
        buffered_samples = 0

        def flush_edge_samples() -> None:
            nonlocal buffered_samples
            if not edge_coord_chunks:
                return
            _splat_points(
                np.concatenate(edge_coord_chunks, axis=0),
                np.concatenate(edge_value_chunks, axis=0),
                component_field_sum,
                component_coverage,
            )
            edge_coord_chunks.clear()
            edge_value_chunks.clear()
            buffered_samples = 0

        for local_a, local_b in component_edges:
            a = member_to_component[int(local_a)]
            b = member_to_component[int(local_b)]
            count_samples = _sample_segment_count(
                component_coords[a], component_coords[b], component_spacing
            )
            edge_sample_count += count_samples
            t = np.linspace(0.0, 1.0, count_samples, dtype=np.float64)
            segment_coords = (
                component_coords[a][None, :] * (1.0 - t[:, None])
                + component_coords[b][None, :] * t[:, None]
            )
            segment_values = (
                component_values[a][None, :] * (1.0 - t[:, None])
                + component_values[b][None, :] * t[:, None]
            )
            edge_coord_chunks.append(segment_coords)
            edge_value_chunks.append(segment_values)
            buffered_samples += count_samples

            # Keep topology links as a compact edge list.  Consecutive voxel
            # samples are the only allowed blur connections.
            voxels = np.rint(segment_coords).astype(np.int64)
            voxels = np.clip(voxels, 0, np.asarray(component_shape) - 1)
            flats = np.ravel_multi_index(voxels.T, component_shape)
            changes = flats[1:] != flats[:-1]
            if np.any(changes):
                topology_link_chunks.append(
                    np.column_stack((flats[:-1][changes], flats[1:][changes]))
                )
            if buffered_samples >= 8192:
                flush_edge_samples()
        flush_edge_samples()
        if topology_link_chunks:
            topology_links = np.unique(
                np.sort(np.concatenate(topology_link_chunks, axis=0), axis=1),
                axis=0,
            )
        else:
            topology_links = np.empty((0, 2), dtype=np.int64)

        support = component_coverage > np.finfo(np.float64).eps
        component_field = np.zeros_like(component_field_sum)
        component_field[support] = (
            component_field_sum[support] / component_coverage[support, None]
        )
        baseline_sample, baseline_support = _sample_field(
            component_field,
            support,
            component_positions,
            component_origin,
            spacing,
        )
        sharpened_field = component_field
        for _ in range(int(iterations)):
            blurred = _topology_blur(
                sharpened_field,
                support,
                topology_links,
                effective_blur_radius,
            )
            sharpened_field = sharpened_field + requested_strength * (sharpened_field - blurred)
            if clamp:
                sharpened_field = np.clip(sharpened_field, 0.0, 1.0)
        sharpened_sample, sharpened_support = _sample_field(
            sharpened_field,
            support,
            component_positions,
            component_origin,
            spacing,
        )
        component_support = np.maximum(baseline_support, sharpened_support)
        fallback = component_support <= np.finfo(np.float64).eps
        if np.any(fallback):
            baseline_sample[fallback] = component_values[fallback]
            sharpened_sample[fallback] = component_values[fallback]
        # Apply only the filter's delta.  Rasterization/interpolation itself
        # must not silently alter a selected vertex's authored weight.
        delta = sharpened_sample - baseline_sample
        output_values[members] = component_values + delta
        sample_support[members] = component_support
        support_voxels_total += int(np.count_nonzero(support))
        coverage_values.append(component_coverage[support])

    sampled = output_values
    if clamp:
        sampled = np.clip(sampled, 0.0, 1.0)

    normalization_name = "none"
    # A scalar single-group field must remain sharpenable. ``input_sum`` is a
    # no-op target for one group, so only apply it to multi-group rows; a
    # custom target is still meaningful for the all-bone/locked-group case.
    should_normalize = normalize and (
        group_count > 1
        or not (isinstance(normalization_target, str)
                and normalization_target == "input_sum")
    )
    if should_normalize:
        if isinstance(normalization_target, str):
            if normalization_target == "input_sum":
                target = np.sum(np.maximum(field_values, 0.0), axis=1)
            elif normalization_target == "one":
                target = np.ones(selected_indices.size, dtype=np.float64)
            else:
                raise VoxelSharpenError("normalization_target must be input_sum, one, scalar, or an array")
        elif np.isscalar(normalization_target):
            target = np.full(selected_indices.size, float(normalization_target), dtype=np.float64)
        else:
            target = np.asarray(normalization_target, dtype=np.float64)
            if target.ndim != 1 or target.size != selected_indices.size:
                raise VoxelSharpenError("normalization target array must match selected vertex count")
        if not np.all(np.isfinite(target)) or np.any(target < 0.0):
            raise VoxelSharpenError("normalization targets must be finite and non-negative")
        sampled = _normalize_rows(sampled, target)
        normalization_name = "row sum: " + (normalization_target if isinstance(normalization_target, str) else "custom")

    if selected_weights.ndim == 1:
        sampled = sampled[:, 0]
    sampled = np.asarray(sampled, dtype=np.float64)
    assert sampled.shape == original_shape

    diagnostics = {
        "selected_count": int(selected_indices.size),
        "group_count": group_count,
        "edge_count": int(edge_array.shape[0]),
        "edge_sample_count": int(edge_sample_count),
        "component_count": int(len(components)),
        "grid_shape": tuple(int(v) for v in grid_shape),
        "voxel_count": int(np.prod(grid_shape, dtype=np.int64)),
        "support_voxels": int(support_voxels_total),
        "coverage_nonzero": int(sum(values.size for values in coverage_values)),
        "coverage_min": float(min((np.min(values) for values in coverage_values), default=0.0)),
        "coverage_max": float(max((np.max(values) for values in coverage_values), default=0.0)),
        "coverage_mean": float(
            np.mean(np.concatenate(coverage_values)) if coverage_values else 0.0
        ),
        "sample_support_min": float(np.min(sample_support)),
        "sample_support_max": float(np.max(sample_support)),
        "origin": tuple(float(v) for v in origin),
        "spacing": tuple(float(v) for v in spacing),
        "base_resolution": tuple(int(v) for v in base_resolution),
        "resolution_requested": resolution,
        "max_voxels": int(max_voxels),
        "strength": requested_strength,
        "blur_radius": int(blur_radius),
        "effective_blur_radius": int(effective_blur_radius),
        "iterations": int(iterations),
        "topology_hops": None if topology_hops is None else int(topology_hops),
        "normalization": normalization_name,
    }
    return VoxelSharpenResult(selected_indices.copy(), sampled, diagnostics)


def _voxel_graph_diffuse(
    values: np.ndarray,
    edges: np.ndarray,
    passes: int,
) -> np.ndarray:
    """Diffuse a voxel field across a sparse selected-topology graph.

    The previous implementation ran a Python breadth-first search from every
    support voxel.  This is mathematically equivalent to repeated one-hop
    normalized diffusion for the small radii used by the operator, but the
    vectorized edge accumulation is linear in the number of graph edges and
    does not allocate a dictionary per voxel.
    """

    result = np.asarray(values, dtype=np.float64).copy()
    if result.ndim != 2:
        raise VoxelSharpenError("voxel values must have shape (K, G)")
    if passes <= 0 or edges.size == 0 or result.shape[0] < 2:
        return result

    edge_array = np.asarray(edges, dtype=np.int64)
    if edge_array.ndim != 2 or edge_array.shape[1] != 2:
        raise VoxelSharpenError("voxel edges must have shape (E, 2)")
    if np.any(edge_array < 0) or np.any(edge_array >= result.shape[0]):
        raise VoxelSharpenError("voxel edge endpoint is outside the field")

    # An edge is an undirected topology constraint. Canonicalizing once keeps
    # duplicate mesh edges from changing the filter strength.
    edge_array = np.unique(np.sort(edge_array, axis=1), axis=0)
    edge_array = edge_array[edge_array[:, 0] != edge_array[:, 1]]
    if edge_array.size == 0:
        return result

    first = edge_array[:, 0]
    second = edge_array[:, 1]
    for _ in range(int(passes)):
        sums = result.copy()
        denominator = np.ones(result.shape[0], dtype=np.float64)
        np.add.at(sums, first, result[second])
        np.add.at(sums, second, result[first])
        np.add.at(denominator, first, 1.0)
        np.add.at(denominator, second, 1.0)
        result = sums / denominator[:, None]
    return result


def _contrast_sharpen_field(values: np.ndarray, strength: float) -> np.ndarray:
    """Increase influence contrast without moving hard 0/1 boundaries."""

    if strength <= 0.0:
        return values.copy()
    factor = 1.0 + min(0.75, 0.5 * float(strength))
    clipped = np.clip(values, 0.0, 1.0)
    if clipped.shape[1] == 1:
        # Use the selected component's authored range as the pivot. A fixed
        # 0.5 pivot would erase a perfectly valid local bone group whose
        # weights all live around 0.01..0.10.
        scalar = clipped[:, 0]
        low, high = np.percentile(scalar, (5.0, 95.0))
        if high - low <= np.finfo(np.float64).eps:
            return clipped.copy()
        center = 0.5 * (float(low) + float(high))
        contrasted = center + (scalar - center) * factor
        return np.clip(contrasted, 0.0, 1.0)[:, None]

    # For all-bone sharpening, strengthen ratios and preserve the voxel row
    # sum. The final vertex-level normalization still accounts for locked
    # groups and the caller's selected-vertex target.
    target = np.sum(clipped, axis=1)
    powered = np.power(clipped, factor)
    denominator = np.sum(powered, axis=1)
    result = np.zeros_like(powered)
    valid = denominator > np.finfo(np.float64).eps
    result[valid] = powered[valid] * (
        target[valid, None] / denominator[valid, None]
    )
    return result


def sharpen_weights(
    positions: ArrayLike,
    weights: ArrayLike,
    selected: ArrayLike,
    edges: ArrayLike = None,
    *,
    resolution: int | Sequence[int] = 32,
    strength: float = 1.0,
    blur_radius: int = 1,
    iterations: int = 1,
    topology_hops: int | None = 2,
    max_voxels: int = 250_000,
    normalize: bool = True,
    normalization_target: str | float | ArrayLike = "input_sum",
    clamp: bool = True,
) -> VoxelSharpenResult:
    """Fast topology-gated voxel unsharp mask for selected vertex weights.

    Vertices are aggregated into local voxels, while voxel-to-voxel links are
    created only from selected mesh edges.  The field is diffused with a
    vectorized sparse graph operation, sharpened, then only the resulting voxel
    delta is added back to the authored selected-vertex values.  This avoids
    the blocky value replacement and the per-voxel Python BFS used previously.
    """

    try:
        positions_array = np.asarray(positions)
        weights_array = np.asarray(weights)
    except (TypeError, ValueError) as exc:
        raise VoxelSharpenError("positions and weights must be array-like") from exc
    if positions_array.ndim != 2 or positions_array.shape[1] != 3:
        raise VoxelSharpenError("positions must have shape (N, 3)")
    if weights_array.ndim not in (1, 2) or weights_array.shape[0] != positions_array.shape[0]:
        raise VoxelSharpenError("weights must have shape (N,) or (N, G)")
    group_count = 1 if weights_array.ndim == 1 else int(weights_array.shape[1])
    if group_count < 1:
        raise VoxelSharpenError("weights must contain at least one group")

    selected_indices = _selected_indices(selected, int(positions_array.shape[0]))
    selected_set = set(int(index) for index in selected_indices)
    try:
        # Conversion deliberately happens after selecting rows. Unselected
        # positions and weights are never parsed or used as field samples.
        selected_positions = np.asarray(
            positions_array[selected_indices], dtype=np.float64
        ).copy()
        selected_weights = np.asarray(
            weights_array[selected_indices], dtype=np.float64
        ).copy()
    except (TypeError, ValueError) as exc:
        raise VoxelSharpenError("selected positions and weights must be numeric") from exc
    if not np.all(np.isfinite(selected_positions)):
        raise VoxelSharpenError("selected positions must be finite")
    if not np.all(np.isfinite(selected_weights)):
        raise VoxelSharpenError("selected weights must be finite")

    edge_array = _validate_edges(edges, int(positions_array.shape[0]), selected_set)
    local_by_global = {
        int(global_index): local_index
        for local_index, global_index in enumerate(selected_indices)
    }
    local_edges = np.asarray(
        [
            (local_by_global[int(first)], local_by_global[int(second)])
            for first, second in edge_array
        ],
        dtype=np.int64,
    )
    if local_edges.size == 0:
        local_edges = np.empty((0, 2), dtype=np.int64)

    try:
        requested_strength = float(strength)
    except (TypeError, ValueError) as exc:
        raise VoxelSharpenError("strength must be finite") from exc
    if not np.isfinite(requested_strength):
        raise VoxelSharpenError("strength must be finite")
    # Keep accidental stale scene values from producing an all-or-nothing
    # field. The UI exposes 0..2; this also protects callers using old files.
    requested_strength = float(np.clip(requested_strength, 0.0, 2.0))
    if not isinstance(blur_radius, (int, np.integer)) or int(blur_radius) < 0:
        raise VoxelSharpenError("blur_radius must be an integer >= 0")
    if not isinstance(iterations, (int, np.integer)) or int(iterations) < 1:
        raise VoxelSharpenError("iterations must be an integer >= 1")
    if topology_hops is not None and (
        not isinstance(topology_hops, (int, np.integer)) or int(topology_hops) < 0
    ):
        raise VoxelSharpenError("topology_hops must be None or an integer >= 0")

    original_shape = selected_weights.shape
    field_values = (
        selected_weights[:, None]
        if selected_weights.ndim == 1
        else selected_weights.copy()
    )
    if requested_strength == 0.0 or selected_indices.size == 1:
        return VoxelSharpenResult(
            selected_indices.copy(),
            selected_weights.copy(),
            {
                "selected_count": int(selected_indices.size),
                "group_count": group_count,
                "edge_count": int(local_edges.shape[0]),
                "edge_sample_count": 0,
                "component_count": int(selected_indices.size),
                "grid_shape": (0, 0, 0),
                "voxel_count": 0,
                "support_voxels": 0,
                "coverage_nonzero": 0,
                "resolution_requested": resolution,
                "max_voxels": int(max_voxels),
                "strength": requested_strength,
                "blur_radius": int(blur_radius),
                "effective_blur_radius": 0,
                "iterations": int(iterations),
                "topology_hops": None if topology_hops is None else int(topology_hops),
                "normalization": "none (no-op)",
            },
        )

    components = _connected_components(int(selected_indices.size), local_edges)
    component_ids = np.full(selected_indices.size, -1, dtype=np.int64)
    component_positions_in_order = np.full(selected_indices.size, -1, dtype=np.int64)
    for component_id, members in enumerate(components):
        component_ids[members] = component_id
        component_positions_in_order[members] = np.arange(members.size)

    effective_blur_radius = int(blur_radius)
    if topology_hops is not None:
        effective_blur_radius = min(effective_blur_radius, int(topology_hops))

    output_values = field_values.copy()
    voxel_count_total = 0
    support_voxels_total = 0
    total_edge_sample_count = 0
    coverage_values: list[np.ndarray] = []
    component_budgets = max(27, int(max_voxels) // max(len(components), 1))
    global_mins = np.min(selected_positions, axis=0)
    global_extents = np.max(selected_positions, axis=0) - global_mins
    global_shape, _global_spacing, global_base = _sparse_resolution_tuple(
        resolution, global_extents
    )

    for members in components:
        component_positions = selected_positions[members]
        component_values = field_values[members]
        mins = np.min(component_positions, axis=0)
        extents = np.max(component_positions, axis=0) - mins
        shape, spacing, _base_resolution = _sparse_resolution_tuple(
            resolution, extents
        )
        origin = mins - spacing
        coordinates = _grid_coordinates(
            component_positions, origin, spacing, shape
        )
        integer_coordinates = np.rint(coordinates).astype(np.int64)
        integer_coordinates = np.clip(
            integer_coordinates, 0, np.asarray(shape, dtype=np.int64) - 1
        )
        flat_coordinates = np.ravel_multi_index(
            integer_coordinates.T, shape
        )

        # Map selected mesh edges to local vertex rows. Edges are filtered by
        # topology first; no proximity-only voxel links are ever introduced.
        component_edge_mask = (
            component_ids[local_edges[:, 0]] == component_ids[members[0]]
            if local_edges.size
            else np.zeros(0, dtype=bool)
        )
        component_edges = local_edges[component_edge_mask]
        if component_edges.size:
            component_edges = component_positions_in_order[component_edges]
        else:
            component_edges = np.empty((0, 2), dtype=np.int64)

        # Add a short DDA path for every selected edge. This keeps long mesh
        # edges connected through the voxel field instead of jumping directly
        # between endpoint voxels, while remaining linear in edge samples.
        path_flat_parts: list[np.ndarray] = []
        path_value_parts: list[np.ndarray] = []
        path_edge_parts: list[np.ndarray] = []
        if component_edges.size:
            edge_distances = np.linalg.norm(
                coordinates[component_edges[:, 0]]
                - coordinates[component_edges[:, 1]],
                axis=1,
            )
            short_edge_mask = edge_distances <= 1.000001
            short_edges = component_edges[short_edge_mask]
            long_edges = component_edges[~short_edge_mask]
        else:
            short_edges = np.empty((0, 2), dtype=np.int64)
            long_edges = np.empty((0, 2), dtype=np.int64)
        edge_sample_count = int(short_edges.shape[0] * 2)
        for first, second in long_edges:
            distance = float(
                np.linalg.norm(coordinates[int(first)] - coordinates[int(second)])
            )
            sample_count = max(2, min(128, int(np.ceil(distance)) + 1))
            parameter = np.linspace(0.0, 1.0, sample_count)
            path_coordinates = (
                coordinates[int(first)][None, :] * (1.0 - parameter[:, None])
                + coordinates[int(second)][None, :] * parameter[:, None]
            )
            path_coordinates = np.rint(path_coordinates).astype(np.int64)
            path_coordinates = np.clip(
                path_coordinates, 0, np.asarray(shape, dtype=np.int64) - 1
            )
            path_flat = np.ravel_multi_index(path_coordinates.T, shape)
            path_values = (
                component_values[int(first)][None, :] * (1.0 - parameter[:, None])
                + component_values[int(second)][None, :] * parameter[:, None]
            )
            # Endpoint values are already supplied by the selected vertices;
            # only interior samples contribute to voxel averages, preventing
            # high-valence vertices from being counted once per incident edge.
            if path_flat.size > 2:
                path_flat_parts.append(path_flat[1:-1])
                path_value_parts.append(path_values[1:-1])
            path_edge_parts.append(path_flat)
            edge_sample_count += sample_count

        if path_flat_parts:
            all_flat = np.concatenate([flat_coordinates, *path_flat_parts])
            all_values = np.concatenate([component_values, *path_value_parts], axis=0)
        else:
            all_flat = flat_coordinates
            all_values = component_values
        unique_voxels, all_voxel_ids = np.unique(all_flat, return_inverse=True)
        vertex_voxel_ids = all_voxel_ids[: members.size]
        voxel_count = int(unique_voxels.size)
        if voxel_count > component_budgets:
            raise VoxelSharpenError(
                "occupied voxel budget exceeded; lower resolution or select a smaller region"
            )
        voxel_count_total += voxel_count
        voxel_values = np.zeros((voxel_count, group_count), dtype=np.float64)
        np.add.at(voxel_values, all_voxel_ids, all_values)
        voxel_counts = np.bincount(all_voxel_ids, minlength=voxel_count)
        voxel_values /= voxel_counts[:, None]

        voxel_edge_parts: list[np.ndarray] = []
        if short_edges.size:
            voxel_edge_parts.append(
                np.column_stack(
                    (
                        vertex_voxel_ids[short_edges[:, 0]],
                        vertex_voxel_ids[short_edges[:, 1]],
                    )
                )
            )
        if path_edge_parts:
            for path in path_edge_parts:
                path_ids = np.searchsorted(unique_voxels, path)
                voxel_edge_parts.append(
                    np.column_stack((path_ids[:-1], path_ids[1:]))
                )
        if voxel_edge_parts:
            voxel_edges = np.concatenate(voxel_edge_parts, axis=0)
            voxel_edges = np.unique(np.sort(voxel_edges, axis=1), axis=0)
            voxel_edges = voxel_edges[voxel_edges[:, 0] != voxel_edges[:, 1]]
        else:
            voxel_edges = np.empty((0, 2), dtype=np.int64)

        sharpened = voxel_values
        for _ in range(int(iterations)):
            blurred = _voxel_graph_diffuse(
                sharpened, voxel_edges, effective_blur_radius
            )
            sharpened = sharpened + requested_strength * (sharpened - blurred)
            if clamp:
                sharpened = np.clip(sharpened, 0.0, 1.0)

        sharpened = _contrast_sharpen_field(sharpened, requested_strength)
        if clamp:
            sharpened = np.clip(sharpened, 0.0, 1.0)

        # Preserve each authored selected vertex and add only the voxel-field
        # detail. This avoids blocky replacement when several vertices share a
        # voxel while still sharpening their shared topology neighborhood.
        output_values[members] = component_values + (
            sharpened - voxel_values
        )[vertex_voxel_ids]
        support_voxels_total += voxel_count
        coverage_values.append(voxel_counts.astype(np.float64))
        total_edge_sample_count += edge_sample_count

    sampled = np.clip(output_values, 0.0, 1.0) if clamp else output_values
    normalization_name = "none"
    should_normalize = normalize and (
        group_count > 1
        or not (
            isinstance(normalization_target, str)
            and normalization_target == "input_sum"
        )
    )
    if should_normalize:
        if isinstance(normalization_target, str):
            if normalization_target == "input_sum":
                target = np.sum(np.maximum(field_values, 0.0), axis=1)
            elif normalization_target == "one":
                target = np.ones(selected_indices.size, dtype=np.float64)
            else:
                raise VoxelSharpenError(
                    "normalization_target must be input_sum, one, scalar, or an array"
                )
        elif np.isscalar(normalization_target):
            target = np.full(
                selected_indices.size, float(normalization_target), dtype=np.float64
            )
        else:
            target = np.asarray(normalization_target, dtype=np.float64)
            if target.ndim != 1 or target.size != selected_indices.size:
                raise VoxelSharpenError(
                    "normalization target array must match selected vertex count"
                )
        if not np.all(np.isfinite(target)) or np.any(target < 0.0):
            raise VoxelSharpenError(
                "normalization targets must be finite and non-negative"
            )
        sampled = _normalize_rows(sampled, target)
        normalization_name = (
            "row sum: "
            + (
                normalization_target
                if isinstance(normalization_target, str)
                else "custom"
            )
        )

    if selected_weights.ndim == 1:
        sampled = sampled[:, 0]
    sampled = np.asarray(sampled, dtype=np.float64)
    assert sampled.shape == original_shape
    diagnostics = {
        "selected_count": int(selected_indices.size),
        "group_count": group_count,
        "edge_count": int(local_edges.shape[0]),
        "edge_sample_count": int(total_edge_sample_count),
        "component_count": int(len(components)),
        "grid_shape": tuple(int(v) for v in global_shape),
        "voxel_count": int(voxel_count_total),
        "support_voxels": int(support_voxels_total),
        "coverage_nonzero": int(sum(values.size for values in coverage_values)),
        "coverage_min": float(
            min((np.min(values) for values in coverage_values), default=0.0)
        ),
        "coverage_max": float(
            max((np.max(values) for values in coverage_values), default=0.0)
        ),
        "coverage_mean": float(
            np.mean(np.concatenate(coverage_values))
            if coverage_values
            else 0.0
        ),
        "sample_support_min": 1.0,
        "sample_support_max": 1.0,
        "origin": tuple(float(v) for v in global_mins),
        "spacing": tuple(float(v) for v in _global_spacing),
        "base_resolution": tuple(int(v) for v in global_base),
        "resolution_requested": resolution,
        "max_voxels": int(max_voxels),
        "strength": requested_strength,
        "blur_radius": int(blur_radius),
        "effective_blur_radius": int(effective_blur_radius),
        "iterations": int(iterations),
        "topology_hops": None if topology_hops is None else int(topology_hops),
        "normalization": normalization_name,
        "algorithm": "sparse topology voxel diffusion",
    }
    return VoxelSharpenResult(selected_indices.copy(), sampled, diagnostics)


def sharpen_weight_field(*args: Any, **kwargs: Any) -> VoxelSharpenResult:
    """Descriptive alias for :func:`sharpen_weights`."""

    return sharpen_weights(*args, **kwargs)


def voxel_sharpen(*args: Any, **kwargs: Any) -> VoxelSharpenResult:
    """Short alias for :func:`sharpen_weights`."""

    return sharpen_weights(*args, **kwargs)


__all__ = [
    "VoxelSharpenError",
    "VoxelSharpenResult",
    "sharpen_weights",
    "sharpen_weight_field",
    "voxel_sharpen",
]
