"""Backend-neutral domain output mapping and Mesh writeback commands.

This module owns only logical-particle to target conversion.  It does not
import Blender or mutate an object; the Physics World result transaction may
consume the returned commands after validating all targets together.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .domain_ir import MC2CompiledDomainProgramV1
from .domain_ir import MC2DomainFrameOutputV1
from .domain_ir import MC2DomainFramePacketV1


@dataclass(frozen=True)
class MC2MeshWritebackCommandV1:
    """One target's world result converted to object-local vertex offsets."""

    target_id: str
    partition_index: int
    frame: int
    generation: int
    source_elements: np.ndarray
    logical_particle_indices: np.ndarray
    world_positions: np.ndarray
    object_local_offsets: np.ndarray
    space_kind: str = "mesh_object_local_offset"

    def __post_init__(self) -> None:
        source = np.asarray(self.source_elements, dtype=np.uint32)
        logical = np.asarray(self.logical_particle_indices, dtype=np.uint32)
        world = np.asarray(self.world_positions, dtype=np.float32)
        offsets = np.asarray(self.object_local_offsets, dtype=np.float32)
        count = len(source)
        if source.shape != (count,) or logical.shape != (count,):
            raise ValueError("writeback command index arrays must be one-dimensional")
        if world.shape != (count, 3) or offsets.shape != (count, 3):
            raise ValueError("writeback command positions must have shape [N,3]")
        if count and not np.array_equal(source, np.arange(count, dtype=np.uint32)):
            raise ValueError("writeback source elements must be target ordered")
        if not np.isfinite(world).all() or not np.isfinite(offsets).all():
            raise ValueError("writeback command positions must be finite")
        if int(self.partition_index) < 0:
            raise ValueError("writeback partition_index must be non-negative")
        if int(self.frame) < 0 or int(self.generation) < 0:
            raise ValueError("writeback frame/generation must be non-negative")
        if self.space_kind != "mesh_object_local_offset":
            raise ValueError("unsupported Mesh writeback space_kind")
        for value in (source, logical, world, offsets):
            value.setflags(write=False)
        object.__setattr__(self, "source_elements", source)
        object.__setattr__(self, "logical_particle_indices", logical)
        object.__setattr__(self, "world_positions", world)
        object.__setattr__(self, "object_local_offsets", offsets)


def make_mc2_mesh_writeback_commands(
    program: MC2CompiledDomainProgramV1,
    frame_packet: MC2DomainFramePacketV1,
    frame_output: MC2DomainFrameOutputV1,
) -> tuple[MC2MeshWritebackCommandV1, ...]:
    """Split one logical domain output into explicit target-local commands."""
    if not isinstance(program, MC2CompiledDomainProgramV1):
        raise TypeError("program must be MC2CompiledDomainProgramV1")
    if not isinstance(frame_packet, MC2DomainFramePacketV1):
        raise TypeError("frame_packet must be MC2DomainFramePacketV1")
    if not isinstance(frame_output, MC2DomainFrameOutputV1):
        raise TypeError("frame_output must be MC2DomainFrameOutputV1")
    if frame_packet.domain_signature != program.domain_signature:
        raise ValueError("frame packet domain signature does not match program")
    if frame_output.domain_signature != program.domain_signature:
        raise ValueError("frame output domain signature does not match program")
    if frame_output.layout_signature != program.layout_signature:
        raise ValueError("frame output layout signature does not match program")
    if (frame_output.frame, frame_output.generation) != (
        frame_packet.frame, frame_packet.generation
    ):
        raise ValueError("frame output identity does not match frame packet")
    if frame_output.index_order != "logical":
        raise ValueError("writeback mapping requires logical frame output")

    commands = []
    for target_index, target in enumerate(program.output_targets):
        logical_indices = np.flatnonzero(
            program.output_target_index == np.uint32(target_index)
        ).astype(np.uint32)
        source_elements = program.output_source_element[logical_indices]
        order = np.argsort(source_elements, kind="stable")
        logical_indices = logical_indices[order]
        source_elements = source_elements[order]
        if len(source_elements) != target.element_count:
            raise ValueError("output target element count does not match output map")
        world_positions = np.asarray(
            frame_output.world_positions[logical_indices], dtype=np.float32
        )
        base_positions = np.asarray(
            frame_packet.animated_base_world_positions[logical_indices], dtype=np.float32
        )
        linear = np.asarray(
            frame_packet.partition_world_linear[target.partition_index],
            dtype=np.float64,
        )
        try:
            inverse_linear = np.linalg.inv(linear)
        except np.linalg.LinAlgError as exc:
            raise ValueError("partition world linear is not invertible") from exc
        world_delta = world_positions - base_positions
        object_local_offsets = np.asarray(
            world_delta @ inverse_linear.astype(np.float32).T,
            dtype=np.float32,
        )
        commands.append(MC2MeshWritebackCommandV1(
            target_id=target.target_id,
            partition_index=target.partition_index,
            frame=frame_packet.frame,
            generation=frame_packet.generation,
            source_elements=source_elements,
            logical_particle_indices=logical_indices,
            world_positions=world_positions,
            object_local_offsets=object_local_offsets,
            space_kind=target.space_kind,
        ))
    return tuple(commands)


__all__ = [
    "MC2MeshWritebackCommandV1",
    "make_mc2_mesh_writeback_commands",
]
