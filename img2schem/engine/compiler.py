"""S4: compile an OpsDoc into a BlockGrid (SOW §6.5 RE.2, RE.6, RE.7, RE.9).

Ops are applied in order; later ops overwrite earlier ones unless ``mode: keep``. The result is normalized so
all indices are >= 0; ``origin`` is the grid index of design coordinate (0, 0, 0).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from img2schem.engine.materials import Material, MaterialError, Resolver
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
    SpiralStair,
    Sweep,
    TrimBand,
    Walls,
    Window,
)
from img2schem.engine.roof import roof_cells
from img2schem.engine.shapes import DIRS, loft_cells, sweep_cells
from img2schem.engine.states import Direction, door_metas, log_meta, stairs_meta
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


@dataclass
class Raster:
    """One op's cells as arrays: ``pos`` (N, 3) design coordinates, ``block_ids`` (N,) indexing ``blocks``,
    ``labels`` (N,). Later cells win over earlier ones at the same position."""

    pos: np.ndarray
    blocks: list[str]
    block_ids: np.ndarray
    labels: np.ndarray

    @classmethod
    def uniform(cls, pos: np.ndarray, block: str, label: int) -> Raster:
        pos = np.asarray(pos, np.int64).reshape(-1, 3)
        return cls(pos, [block], np.zeros(len(pos), np.int64), np.full(len(pos), label, np.uint8))

    @classmethod
    def of(cls, cells: list[Cell]) -> Raster:
        if not cells:
            return cls.uniform(np.zeros((0, 3)), AIR, AIR_L)
        blocks = list(dict.fromkeys(c[3] for c in cells))
        ids = {b: i for i, b in enumerate(blocks)}
        return cls(np.array([c[:3] for c in cells], np.int64), blocks, np.array([ids[c[3]] for c in cells], np.int64),
                   np.array([c[4] for c in cells], np.uint8))  # fmt: skip

    @classmethod
    def concat(cls, parts: list[Raster]) -> Raster:
        blocks = list(dict.fromkeys(b for r in parts for b in r.blocks))
        ids = {b: i for i, b in enumerate(blocks)}
        return cls(np.concatenate([r.pos for r in parts]), blocks,
                   np.concatenate([np.array([ids[b] for b in r.blocks], np.int64)[r.block_ids] for r in parts]),
                   np.concatenate([r.labels for r in parts]))  # fmt: skip


def _box_cells(a: tuple[int, int, int], b: tuple[int, int, int]) -> np.ndarray:
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    axes = [np.arange(lo[i], hi[i] + 1) for i in range(3)]
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


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


def _stairs(res: Resolver, mat: str) -> Material:
    m = res(mat)
    if m.shape not in ("stairs", "unknown"):
        raise MaterialError(f"{mat} is {m.block}, a {m.shape}; stairs are needed here")
    return m


def _loft(op: Loft, res: Resolver) -> Raster:
    lc = loft_cells(op)
    wall_b = res(op.mat).block
    floor_b = res(op.floor_mat).block if op.floor_mat else wall_b
    parts = [Raster.uniform(lc.walls, wall_b, WALL), Raster.uniform(lc.floors, floor_b, FLOOR)]
    if op.mullions:
        parts.append(Raster.uniform(lc.mullions, res(op.mullions.mat).block, TRIM))
    if op.lights:
        parts.append(Raster.uniform(lc.lights, res(op.lights.mat).block, OTHER))
    if len(lc.steps):
        if not op.mat.startswith("$"):
            raise MaterialError(f"smooth needs mat to be a slot (e.g. $wall) to find its stairs, not {op.mat}")
        st = _stairs(res, f"{op.mat}.stairs")
        blocks = [format_block(st.name, stairs_meta(st.meta, d, down)) for down in (False, True) for d, _, _ in DIRS]
        ids = lc.step_dir + len(DIRS) * lc.step_down
        parts.append(Raster(lc.steps, blocks, ids, np.full(len(ids), WALL, np.uint8)))
    return Raster.concat(parts)


def _spiral_stair(op: SpiralStair, res: Resolver) -> list[Cell]:
    r, (cx, cz) = op.radius, op.center
    ring = ([(u, -r) for u in range(-r, r)] + [(r, v) for v in range(-r, r)]
            + [(u, r) for u in range(r, -r, -1)] + [(-r, v) for v in range(r, -r, -1)])  # fmt: skip
    if op.turn == "ccw":  # seen from above (north up, east right) the list above runs clockwise
        ring.reverse()
    st = _stairs(res, op.mat)
    col = _oriented(res, op.column, "y")
    names: dict[tuple[int, int], Direction] = {(1, 0): "east", (-1, 0): "west", (0, 1): "south", (0, -1): "north"}
    steps = {}
    for k, y in enumerate(range(op.y0, op.y1 + 1)):
        (u, v), (nu, nv) = ring[k % len(ring)], ring[(k + 1) % len(ring)]
        steps[(cx + u, y, cz + v)] = format_block(st.name, stairs_meta(st.meta, names[(nu - u, nv - v)]))
    cells: list[Cell] = []
    for y in range(op.y0, op.y1 + 3):
        for u, v in ring:
            c = (cx + u, y, cz + v)
            cells.append((*c, steps[c], OTHER) if c in steps else (*c, AIR, AIR_L))
        if y <= op.y1:
            cells += [(cx + u, y, cz + v, col, TRIM) for u in range(1 - r, r) for v in range(1 - r, r)]
    return cells


def rasterize(op: Op, res: Resolver) -> Raster:
    if isinstance(op, Loft):
        return _loft(op, res)
    if isinstance(op, Sweep):
        return Raster.uniform(sweep_cells(op), res(op.mat).block, OTHER)
    cells = _cells(op, res)
    return cells if isinstance(cells, Raster) else Raster.of(cells)


def _cells(op: Op, res: Resolver) -> list[Cell] | Raster:
    if isinstance(op, Box):
        c = _box_cells(op.from_, op.to)
        if op.hollow:
            lo, hi = np.minimum(op.from_, op.to), np.maximum(op.from_, op.to)
            c = c[((c == lo) | (c == hi)).any(axis=1)]
        return Raster.uniform(c, res(op.mat).block, OTHER)
    if isinstance(op, Walls):
        fp, t = op.footprint, op.thickness
        c = _box_cells((fp.x0, op.y0, fp.z0), (fp.x1, op.y0 + op.height - 1, fp.z1))
        cx, cz = c[:, 0], c[:, 2]
        c = c[(cx < fp.x0 + t) | (cx > fp.x1 - t) | (cz < fp.z0 + t) | (cz > fp.z1 - t)]
        return Raster.uniform(c, res(op.mat).block, WALL)
    if isinstance(op, Floors):
        fp = op.footprint
        layers = [_box_cells((fp.x0, fy, fp.z0), (fp.x1, fy, fp.z1)) for fy in op.ys]
        return Raster.uniform(np.concatenate(layers) if layers else np.zeros((0, 3)), res(op.mat).block, FLOOR)
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
    if isinstance(op, SpiralStair):
        return _spiral_stair(op, res)
    if isinstance(op, Carve):
        return Raster.uniform(_box_cells(op.from_, op.to), AIR, AIR_L)
    if isinstance(op, SetBlock):
        b = res(op.block).block
        return [(x, y, z, b, OTHER) for x, y, z in op.cells]
    raise TypeError(f"unhandled op {type(op).__name__}")


def _last(pos: np.ndarray, first: bool) -> np.ndarray:
    """Indices of one cell per distinct position: the last occurrence (the first with ``first``), in order."""
    order = np.arange(len(pos)) if first else np.arange(len(pos))[::-1]
    _, keep = np.unique(pos[order], axis=0, return_index=True)
    return np.sort(order[keep])


def compile_ops(doc: OpsDoc, index: PaletteIndex | None = None, hard_max_total: int = 2_000_000) -> Compiled:
    res = Resolver(doc.style, index)
    rasters: list[Raster] = []
    for op in doc.ops:
        try:
            rasters.append(rasterize(op, res))
        except (MaterialError, ValueError) as e:
            raise CompileError(op.id, str(e)) from None

    palette = [AIR] + list(dict.fromkeys(b for r in rasters for b in r.blocks if b != AIR))
    gid = {b: i for i, b in enumerate(palette)}
    solid = [r.pos[np.array([b != AIR for b in r.blocks], bool)[r.block_ids]] for r in rasters]
    solid = [p for p in solid if len(p)]
    summaries = [OpSummary(op.id, op.label) for op in doc.ops]
    if not solid:
        return Compiled(BlockGrid.empty(1, 1, 1), np.zeros((1, 1, 1), np.uint8), np.full((1, 1, 1), -1, np.int16),
                        (0, 0, 0), summaries)  # fmt: skip
    lo = np.min([p.min(axis=0) for p in solid], axis=0)
    hi = np.max([p.max(axis=0) for p in solid], axis=0)
    dims = hi - lo + 1
    total = int(np.prod(dims))
    if total > hard_max_total:  # RE.7: check before allocating
        raise CompileError("*", f"bounding box {tuple(int(d) for d in dims)} = {total} cells exceeds {hard_max_total}")
    idx = np.zeros(tuple(int(d) for d in dims), np.int32)
    labels = np.zeros(idx.shape, np.uint8)
    op_index = np.full(idx.shape, -1, np.int16)

    for i, (op, r, s) in enumerate(zip(doc.ops, rasters, summaries, strict=True)):
        if not len(r.pos):
            continue
        s.bounds = (tuple(int(v) for v in r.pos.min(axis=0)), tuple(int(v) for v in r.pos.max(axis=0)))  # type: ignore[assignment]
        pick = _last(r.pos, first=op.mode == "keep")
        p = r.pos[pick] - lo
        inside = ((p >= 0) & (p < dims)).all(axis=1)  # only air (carves) can fall outside the solid bounds
        pick, p = pick[inside], p[inside]
        cell = (p[:, 0], p[:, 1], p[:, 2])
        prev = idx[cell]
        if op.mode == "keep":
            pick, cell, prev = pick[prev == 0], tuple(a[prev == 0] for a in cell), prev[prev == 0]
        g = np.array([gid[b] for b in r.blocks], np.int32)[r.block_ids[pick]]
        s.cells, s.overwritten = len(pick), int((prev != 0).sum())
        idx[cell], labels[cell], op_index[cell] = g, r.labels[pick], i
        counts = np.bincount(g, minlength=len(palette))
        s.blocks = {palette[j]: int(n) for j, n in enumerate(counts) if n}

    nz = np.argwhere(idx != 0)
    a, b = nz.min(axis=0), nz.max(axis=0) + 1  # carves can shrink the bounds
    crop = tuple(slice(int(u), int(v)) for u, v in zip(a, b, strict=True))
    grid = BlockGrid(idx[crop].copy(), palette).compact()
    origin = tuple(int(v) for v in -(lo + a))
    return Compiled(grid, labels[crop].copy(), op_index[crop].copy(), origin, summaries)  # type: ignore[arg-type]


def paste_offset(c: Compiled) -> tuple[int, int, int]:
    """WEOffset so that //paste puts design (W//2 - origin_x, 0, 0) — the front facade's bottom center — two
    blocks south of the player, with y = 0 replacing the ground block (§4.3, D-015). A roof overhang in front
    (design z < 0) still lands the facade itself two blocks ahead."""
    width = c.grid.shape[0]
    _, oy, oz = c.origin
    return (-(width // 2), -oy - 1, -oz + 2)
