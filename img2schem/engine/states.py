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


TURN_CW: dict[Direction, Direction] = {"north": "east", "east": "south", "south": "west", "west": "north"}
MIRROR: dict[str, dict[Direction, Direction]] = {
    "x": {"east": "west", "west": "east", "north": "north", "south": "south"},
    "z": {"north": "south", "south": "north", "east": "east", "west": "west"},
}


def _turn(d: Direction, turns: int, mirror: str | None) -> Direction:
    if mirror:
        d = MIRROR[mirror][d]
    for _ in range(turns % 4):
        d = TURN_CW[d]
    return d


def transform_meta(shape: str, meta: int, turns: int, mirror: str | None = None) -> int:
    """Metadata of an oriented block after mirroring across ``mirror`` (x: east <-> west, z: north <-> south)
    and then turning ``turns`` quarter turns clockwise seen from above (RE.5). Other blocks keep their meta."""
    if shape == "stairs":
        d = next(k for k, v in STAIRS_ASCEND.items() if v == meta & 3)
        return (meta & ~3) | STAIRS_ASCEND[_turn(d, turns, mirror)]
    if shape == "door":
        if meta & 8:  # upper half: the hinge side flips in a mirror image
            return meta ^ 1 if mirror else meta
        d = next(k for k, v in DOOR_FACING.items() if v == meta & 3)
        return (meta & ~3) | DOOR_FACING[_turn(d, turns, mirror)]
    if shape == "log" and turns % 2 and meta & 12 in (4, 8):
        return meta ^ 12  # x axis <-> z axis
    return meta
