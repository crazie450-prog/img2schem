"""Roof rasterization: flat, gable, hip and shed roofs at pitches 1:1 (stairs), 1:2 (slabs) and 2:1 (stairs over
full blocks). Stairs always ascend toward the ridge; the game forms the corner shapes itself in 1.7.10.
"""

from __future__ import annotations

from collections.abc import Callable

from img2schem.engine.materials import Material, Resolver
from img2schem.engine.ops import Roof
from img2schem.engine.states import OPPOSITE, Direction, slab_meta, stairs_meta
from img2schem.util.block import format_block

Cell = tuple[int, int, int, str, int]  # x, y, z, block, label
ROOF, WALL = 4, 1


class _Blocks:
    def __init__(self, op: Roof, res: Resolver):
        self.base = res(op.mat).block
        self.stairs = res(f"{op.mat}.stairs") if op.type != "flat" and op.pitch != "1:2" else None
        self.slab = res(f"{op.mat}.slab") if op.type != "flat" and op.pitch == "1:2" else None
        self.fill = res(op.gable_fill).block

    def stair(self, ascend: Direction) -> str:
        st = self.stairs
        assert st is not None
        return format_block(st.name, stairs_meta(st.meta, ascend))

    def half(self, top: bool) -> str:
        sl: Material | None = self.slab
        assert sl is not None
        if top and sl.top_block:
            return format_block(sl.top_block, sl.meta)
        return format_block(sl.name, slab_meta(sl.meta, top, sl.top_block is not None))


def _course(op: Roof, b: _Blocks, k: int, ascend: Direction) -> list[tuple[int, str]]:
    """(dy, block) placed at step k of a slope, bottom to top."""
    if op.pitch == "1:1":
        return [(k, b.stair(ascend))]
    if op.pitch == "2:1":
        return [(2 * k, b.base), (2 * k + 1, b.stair(ascend))]
    return [(k // 2, b.half(top=k % 2 == 1))]


def _cap(op: Roof, b: _Blocks, k: int) -> list[tuple[int, str]]:
    """(dy, block) for a ridge cell whose neighbors on both sides are at step k - 1."""
    k = max(k, 1)  # a 1-wide roof has no slope below its ridge
    if op.pitch == "1:1":
        return [(k - 1, b.base)]
    if op.pitch == "2:1":
        return [(2 * k - 2, b.base), (2 * k - 1, b.base)]
    return [(k // 2, b.half(top=k % 2 == 1))]


def roof_cells(op: Roof, res: Resolver) -> list[Cell]:
    b = _Blocks(op, res)
    fp, o = op.footprint, op.overhang
    fx0, fx1, fz0, fz1 = fp.x0 - o, fp.x1 + o, fp.z0 - o, fp.z1 + o
    cells: list[Cell] = []

    if op.type == "flat":
        cells += [(x, op.y0, z, b.base, ROOF) for x in range(fx0, fx1 + 1) for z in range(fz0, fz1 + 1)]
        if op.parapet:
            cells += [
                (x, op.y0 + 1, z, b.base, ROOF)
                for x in range(fx0, fx1 + 1)
                for z in range(fz0, fz1 + 1)
                if x in (fx0, fx1) or z in (fz0, fz1)
            ]
        return cells

    if op.type == "hip":
        return _hip(op, b, fx0, fx1, fz0, fz1)

    # Gable and shed roofs work in (u, v): u runs across the slope(s), v along the ridge.
    if op.type == "gable":
        along_x = op.ridge == "x"
    else:
        along_x = op.rise in ("north", "south")  # a shed rising south has its courses running along x
    if along_x:  # u = z
        u0, u1, v0, v1, wall_u0, wall_u1 = fz0, fz1, fx0, fx1, fp.z0, fp.z1
        up_from_low: Direction = "south"

        def put(u: int, v: int, dy: int, block: str, label: int) -> None:
            cells.append((v, op.y0 + dy, u, block, label))

    else:  # u = x
        u0, u1, v0, v1, wall_u0, wall_u1 = fx0, fx1, fz0, fz1, fp.x0, fp.x1
        up_from_low = "east"

        def put(u: int, v: int, dy: int, block: str, label: int) -> None:
            cells.append((u, op.y0 + dy, v, block, label))

    step_at: Callable[[int], tuple[int, Direction | None]]  # u -> (k, ascend); ascend None = ridge cap
    depth = u1 - u0 + 1
    if op.type == "gable":
        n = depth // 2

        def step_at(u: int) -> tuple[int, Direction | None]:
            a, c = u - u0, u1 - u
            if a == c:
                return n, None
            return (a, up_from_low) if a < c else (c, OPPOSITE[up_from_low])

    else:
        rising_to_high_u = op.rise in ("south", "east")

        def step_at(u: int) -> tuple[int, Direction | None]:
            # The overhang beyond the high wall stays level with the top course instead of climbing on.
            if rising_to_high_u:
                return min(u, wall_u1) - u0, up_from_low
            return u1 - max(u, wall_u0), OPPOSITE[up_from_low]

    for u in range(u0, u1 + 1):
        k, ascend = step_at(u)
        placements = _cap(op, b, k) if ascend is None else _course(op, b, k, ascend)
        for v in range(v0, v1 + 1):
            for dy, block in placements:
                put(u, v, dy, block, ROOF)
    return _seal(op, b, cells)


def _seal(op: Roof, b: _Blocks, cells: list[Cell]) -> list[Cell]:
    """Close the roof onto the walls: every column on the footprint's wall line is filled with ``gable_fill``
    from ``y0`` up to just below its lowest roof block. This makes the gable triangles and a shed's tall wall,
    and with an overhang it closes the slot between the wall top and the first course over the wall."""
    if not op.seal:
        return cells
    fp = op.footprint
    lowest: dict[tuple[int, int], int] = {}
    for x, y, z, _, _ in cells:
        if (x in (fp.x0, fp.x1) and fp.z0 <= z <= fp.z1) or (z in (fp.z0, fp.z1) and fp.x0 <= x <= fp.x1):
            lowest[(x, z)] = min(y, lowest.get((x, z), y))
    fill = [(x, y, z, b.fill, WALL) for (x, z), top in sorted(lowest.items()) for y in range(op.y0, top)]
    return cells + fill


def _hip(op: Roof, b: _Blocks, x0: int, x1: int, z0: int, z1: int) -> list[Cell]:
    cells: list[Cell] = []
    k = 0
    while x0 <= x1 and z0 <= z1:
        if x0 == x1 or z0 == z1:  # a 1-wide ridge line (or a single peak cell)
            for x in range(x0, x1 + 1):
                for z in range(z0, z1 + 1):
                    cells += [(x, op.y0 + dy, z, block, ROOF) for dy, block in _cap(op, b, k)]
            break
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                if x not in (x0, x1) and z not in (z0, z1):
                    continue
                ascend: Direction = "south" if z == z0 else "north" if z == z1 else "east" if x == x0 else "west"
                cells += [(x, op.y0 + dy, z, block, ROOF) for dy, block in _course(op, b, k, ascend)]
        x0, x1, z0, z1, k = x0 + 1, x1 - 1, z0 + 1, z1 - 1, k + 1
    return _seal(op, b, cells)
