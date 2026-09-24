"""Metadata for oriented 1.7.10 blocks (SOW_GTNH: the engine only writes metadata; the game computes
pane/fence/wall connections and stair corner shapes itself).

Tables verified in game on GTNH (docs/TEST_BED.md, D-014): vanilla and Chisel stairs, wooden doors.
Directions are compass names: north = -Z, south = +Z, west = -X, east = +X (SOW §4.3).
"""

from __future__ import annotations

from typing import Literal

Direction = Literal["north", "south", "east", "west"]

# Stairs: the direction the stair ascends toward (its tall back side). +4 = upside-down.
STAIRS_ASCEND: dict[Direction, int] = {"east": 0, "west": 1, "south": 2, "north": 3}
# Wooden door, lower half: the direction the player faced when placing it (the door's outward side is behind
# them). Upper half: 8, +1 for a right-hand hinge.
DOOR_FACING: dict[Direction, int] = {"east": 0, "south": 1, "west": 2, "north": 3}
# Logs (vanilla BlockLog and subclasses): material in bits 0-1, axis in bits 2-3.
LOG_AXIS = {"y": 0, "x": 4, "z": 8}

OPPOSITE: dict[Direction, Direction] = {"north": "south", "south": "north", "east": "west", "west": "east"}


def stairs_meta(material: int, ascend: Direction, upside_down: bool = False) -> int:
    """``material`` is the stairs variant's own meta (0, or 8 for Chisel's second texture)."""
    return (material & 8) | STAIRS_ASCEND[ascend] | (4 if upside_down else 0)


def slab_meta(material: int, top: bool, has_top_block: bool) -> int:
    """Vanilla-style slabs keep the top half in bit 3; slabs with a separate top block don't."""
    if has_top_block:
        return material
    return (material & 7) | (8 if top else 0)


def door_metas(facing: Direction, hinge_right: bool = False) -> tuple[int, int]:
    """(lower, upper) metadata of a two-block door."""
    return DOOR_FACING[facing], 8 | (1 if hinge_right else 0)


def log_meta(material: int, axis: Literal["x", "y", "z"]) -> int:
    return (material & 3) | LOG_AXIS[axis]
