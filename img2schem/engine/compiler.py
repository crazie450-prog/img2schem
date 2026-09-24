"""S4: compile an OpsDoc into a BlockGrid (SOW §6.5 RE.2, RE.6, RE.7, RE.9).

Ops are applied in order; later ops overwrite earlier ones unless ``mode: keep``. The result is normalized so
all indices are >= 0; ``origin`` is the grid index of design coordinate (0, 0, 0).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from img2schem.engine.materials import MaterialError, Resolver
from img2schem.engine.ops import (
    Beam,
    Box,
    Carve,
    Column,
    Door,
    Floors,
    Loft,
    Op,
    Openings,
    OpsDoc,
    Roof,
    SetBlock,
    Sweep,
    TrimBand,
    Walls,
    Window,
)
from img2schem.engine.roof import roof_cells
from img2schem.engine.shapes import loft_cells, sweep_cells
from img2schem.engine.states import door_metas, log_meta
from img2schem.models import AIR, BlockGrid
from img2schem.palette.query import PaletteIndex
from img2schem.util.block import format_block

Cell = tuple[int, int, int, str, int]  # x, y, z, block, label
# Semantic labels (SOW §5.3).
AIR_L, WALL, WINDOW, DOOR, ROOF, TRIM, FLOOR, BASE, OTHER = range(9)


class CompileError(ValueError):
    def __init__(self, op_id: str, message: str):
        super().__init__(f"op {op_id!r}: {message}")
        self.op_id = op_id


@dataclass
class OpSummary:
    """RE.9: what one op did, for the designer's tool results."""

    id: str
    label: str
    cells: int = 0
    overwritten: int = 0
    bounds: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None
    blocks: dict[str, int] = field(default_factory=dict)


@dataclass
class Compiled:
    grid: BlockGrid
    labels: np.ndarray  # uint8 [X, Y, Z]
    op_index: np.ndarray  # int16 [X, Y, Z], -1 = no op
    origin: tuple[int, int, int]
    summaries: list[OpSummary]


def _box(a: tuple[int, int, int], b: tuple[int, int, int]):  # type: ignore[no-untyped-def]
    lo = [min(p, q) for p, q in zip(a, b, strict=True)]
    hi = [max(p, q) for p, q in zip(a, b, strict=True)]
    return (
        (x, y, z) for x in range(lo[0], hi[0] + 1) for y in range(lo[1], hi[1] + 1) for z in range(lo[2], hi[2] + 1)
    )


def _oriented(res: Resolver, mat: str, axis: str) -> str:
    m = res(mat)
    return format_block(m.name, log_meta(m.meta, axis)) if m.shape == "log" else m.block  # type: ignore[arg-type]


def _openings(op: Openings, res: Resolver) -> list[Cell]:
    fp = op.footprint
    horizontal = op.face in ("front", "back")  # windows run along x
    lo, hi = (fp.x0, fp.x1) if horizontal else (fp.z0, fp.z1)
    plane = {"front": fp.z0, "back": fp.z1, "left": fp.x0, "right": fp.x1}[op.face]
    usable = (hi - lo + 1) - 2 * op.margin
    count = op.count or max(0, (usable + op.spacing) // (op.w + op.spacing))
    span = count * op.w + (count - 1) * op.spacing
    if count and span > hi - lo + 1:
        raise ValueError(f"{count} windows of width {op.w} don't fit on the {op.face} face")
    start = lo + (hi - lo + 1 - span) // 2
    glass = res(op.mat).block
    cells: list[Cell] = []
    for i in range(count):
        a = start + i * (op.w + op.spacing)
        for s in range(a, a + op.w):
            for y0 in op.sills:
                for y in range(y0, y0 + op.h):
                    x, z = (s, plane) if horizontal else (plane, s)
                    cells.append((x, y, z, glass, WINDOW))
    return cells


def _window(op: Window, res: Resolver) -> list[Cell]:
    fp = op.footprint
    glass = res(op.mat).block
    # (axis of the plane, plane coordinate, inward step)
    plane, inward = {"front": (fp.z0, 1), "back": (fp.z1, -1), "left": (fp.x0, 1), "right": (fp.x1, -1)}[op.face]
    cells: list[Cell] = []
    for u in range(op.u0, op.u1 + 1):
        for y in range(op.y0, op.y1 + 1):
            for depth in range(op.recess + 1):
                w = plane + depth * inward
                x, z = (u, w) if op.face in ("front", "back") else (w, u)
                cells.append((x, y, z, glass if depth == op.recess else AIR, WINDOW))
    return cells


def rasterize(op: Op, res: Resolver) -> list[Cell]:
    if isinstance(op, Box):
        b = res(op.mat).block
        lo, hi = op.from_, op.to
        return [
            (x, y, z, b, OTHER)
            for x, y, z in _box(lo, hi)
            if not op.hollow or x in (lo[0], hi[0]) or y in (lo[1], hi[1]) or z in (lo[2], hi[2])
        ]
    if isinstance(op, Walls):
        b, fp, t = res(op.mat).block, op.footprint, op.thickness
        return [
            (x, y, z, b, WALL)
            for x, y, z in _box((fp.x0, op.y0, fp.z0), (fp.x1, op.y0 + op.height - 1, fp.z1))
            if x < fp.x0 + t or x > fp.x1 - t or z < fp.z0 + t or z > fp.z1 - t
        ]
    if isinstance(op, Floors):
        b, fp = res(op.mat).block, op.footprint
        return [(x, y, z, b, FLOOR) for y in op.ys for x, _, z in _box((fp.x0, y, fp.z0), (fp.x1, y, fp.z1))]
    if isinstance(op, Door):
        m = res(op.mat)
        lower, upper = door_metas(op.facing, op.hinge == "right")
        x, y, z = op.pos
        return [(x, y, z, format_block(m.name, lower), DOOR), (x, y + 1, z, format_block(m.name, upper), DOOR)]
    if isinstance(op, Openings):
        return _openings(op, res)
    if isinstance(op, Window):
        return _window(op, res)
    if isinstance(op, Roof):
        return roof_cells(op, res)
    if isinstance(op, Column):
        b = _oriented(res, op.mat, "y")
        x, z = op.pos
        return [(x, y, z, b, TRIM) for y in range(op.y0, op.y0 + op.height)]
    if isinstance(op, Beam):
        axis = next((a for a, p, q in zip("xyz", op.from_, op.to, strict=True) if p != q), "y")
        b = _oriented(res, op.mat, axis)
        return [(x, y, z, b, TRIM) for x, y, z in _box(op.from_, op.to)]
    if isinstance(op, TrimBand):
        b, fp, o = res(op.mat).block, op.footprint, op.outset
        x0, x1, z0, z1 = fp.x0 - o, fp.x1 + o, fp.z0 - o, fp.z1 + o
        return [
            (x, op.y, z, b, TRIM) for x, _, z in _box((x0, op.y, z0), (x1, op.y, z1)) if x in (x0, x1) or z in (z0, z1)
        ]
    if isinstance(op, Loft):
        walls, floors = loft_cells(op)
        wall_b = res(op.mat).block
        floor_b = res(op.floor_mat).block if op.floor_mat else wall_b
        return [(x, y, z, wall_b, WALL) for x, y, z in walls] + [(x, y, z, floor_b, FLOOR) for x, y, z in floors]
    if isinstance(op, Sweep):
        b = res(op.mat).block
        return [(x, y, z, b, OTHER) for x, y, z in sweep_cells(op)]
    if isinstance(op, Carve):
        return [(x, y, z, AIR, AIR_L) for x, y, z in _box(op.from_, op.to)]
    if isinstance(op, SetBlock):
        b = res(op.block).block
        return [(x, y, z, b, OTHER) for x, y, z in op.cells]
    raise TypeError(f"unhandled op {type(op).__name__}")


def compile_ops(doc: OpsDoc, index: PaletteIndex | None = None, hard_max_total: int = 2_000_000) -> Compiled:
    res = Resolver(doc.style, index)
    world: dict[tuple[int, int, int], tuple[str, int, int]] = {}  # cell -> (block, label, op index)
    summaries: list[OpSummary] = []
    for i, op in enumerate(doc.ops):
        try:
            cells = rasterize(op, res)
        except (MaterialError, ValueError) as e:
            raise CompileError(op.id, str(e)) from None
        s = OpSummary(op.id, op.label)
        for x, y, z, block, label in cells:
            key = (x, y, z)
            prev = world.get(key)
            if op.mode == "keep" and prev is not None and prev[0] != AIR:
                continue
            if prev is not None and prev[0] != AIR:
                s.overwritten += 1
            world[key] = (block, label, i)
            s.cells += 1
            s.blocks[block] = s.blocks.get(block, 0) + 1
        if cells:
            xs, ys, zs = zip(*((c[0], c[1], c[2]) for c in cells), strict=True)
            s.bounds = ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
        summaries.append(s)

    solid = {k: v for k, v in world.items() if v[0] != AIR}
    if not solid:
        return Compiled(BlockGrid.empty(1, 1, 1), np.zeros((1, 1, 1), np.uint8), np.full((1, 1, 1), -1, np.int16),
                        (0, 0, 0), summaries)  # fmt: skip
    keys = np.array(list(solid))
    lo, hi = keys.min(axis=0), keys.max(axis=0)
    dims = hi - lo + 1
    total = int(np.prod(dims))
    if total > hard_max_total:  # RE.7: check before allocating
        raise CompileError("*", f"bounding box {tuple(int(d) for d in dims)} = {total} cells exceeds {hard_max_total}")
    grid = BlockGrid.empty(*(int(d) for d in dims))
    labels = np.zeros(grid.shape, np.uint8)
    op_index = np.full(grid.shape, -1, np.int16)
    for (x, y, z), (block, label, i) in solid.items():
        gx, gy, gz = x - lo[0], y - lo[1], z - lo[2]
        grid.idx[gx, gy, gz] = grid.index_of(block)
        labels[gx, gy, gz] = label
        op_index[gx, gy, gz] = i
    origin = (int(-lo[0]), int(-lo[1]), int(-lo[2]))
    return Compiled(grid, labels, op_index, origin, summaries)


def paste_offset(c: Compiled) -> tuple[int, int, int]:
    """WEOffset so that //paste puts design (W//2 - origin_x, 0, 0) — the front facade's bottom center — two
    blocks south of the player, with y = 0 replacing the ground block (§4.3, D-015). A roof overhang in front
    (design z < 0) still lands the facade itself two blocks ahead."""
    width = c.grid.shape[0]
    _, oy, oz = c.origin
    return (-(width // 2), -oy - 1, -oz + 2)
