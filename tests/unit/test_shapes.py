import math

import numpy as np
import pytest
from scipy import ndimage

from img2schem.engine.compiler import compile_ops
from img2schem.engine.ops import LoftKey, OpsDoc
from img2schem.engine.shapes import key_at

CIRCLE = {"outer": {"shape": "ellipse", "rx": 8, "rz": 8}}


def build(*ops):
    return compile_ops(OpsDoc.model_validate({"style": {"a": "minecraft:stone", "b": "minecraft:quartz_block"},
                                              "ops": list(ops)}))  # fmt: skip


def layers(c):
    """{design y: set of (x, z)} of non-air cells."""
    ox, oy, oz = c.origin
    out = {}
    for x, y, z in np.argwhere(c.grid.idx != 0):
        out.setdefault(int(y) - oy, set()).add((int(x) - ox, int(z) - oz))
    return out


def test_solid_extrusion_area_and_symmetry():
    c = build({"op": "loft", "id": "l", "profile": CIRCLE, "keys": [{"y": 0}, {"y": 3}], "mat": "$a"})
    ls = layers(c)
    assert sorted(ls) == [0, 1, 2, 3]
    cells = ls[0]
    assert abs(len(cells) - math.pi * 64) / (math.pi * 64) < 0.05
    assert all(ls[y] == cells for y in ls)  # straight extrusion
    assert cells == {(-1 - x, z) for x, z in cells} == {(x, -1 - z) for x, z in cells}  # symmetric about center


def test_shell_is_watertight_with_floors_and_caps():
    c = build({"op": "loft", "id": "l", "profile": CIRCLE, "keys": [{"y": 0}, {"y": 12}], "fill": "shell",
               "mat": "$a", "floor_every": 4, "floor_mat": "$b"})  # fmt: skip
    ls = layers(c)
    ox, oy, oz = c.origin
    for y in range(13):
        blocks = {c.grid.palette[c.grid.idx[x + ox, y + oy, z + oz]] for x, z in ls[y]}
        if y % 4 == 0:
            assert blocks == {"minecraft:quartz_block"} and len(ls[y]) > 150  # full floor
        else:
            assert blocks == {"minecraft:stone"} and len(ls[y]) < 70  # a ring
            ring = np.zeros((20, 20), bool)
            for x, z in ls[y]:
                ring[x + 10, z + 10] = True
            _, n = ndimage.label(~ring)  # 4-connected: the inside must not leak to the outside
            assert n == 2


def test_taper_lean_and_twist():
    square = {"outer": {"shape": "polygon", "points": [[-6, -6], [6, -6], [6, 6], [-6, 6]]}}
    c = build({"op": "loft", "id": "l", "profile": square, "interp": "linear", "mat": "$a",
               "keys": [{"y": 0}, {"y": 10, "scale": 0.5, "dx": 10, "rotate": 45}]})  # fmt: skip
    ls = layers(c)
    assert len(ls[0]) == 144 and abs(len(ls[10]) - 36) <= 6  # area scales by 0.5 squared
    cx = np.mean([x for x, _ in ls[10]]) + 0.5
    assert abs(cx - 10) < 0.6  # moved 10 east
    xs = [x for x, _ in ls[10]]
    assert max(xs) - min(xs) + 1 >= 8  # a 6-wide square turned 45 degrees is ~8.5 wide


def test_crescent_profile_and_keys():
    crescent = {"outer": {"shape": "ellipse", "rx": 9, "rz": 6},
                "minus": [{"shape": "ellipse", "center": [4, 0], "rx": 9, "rz": 7}]}  # fmt: skip
    ls = layers(build({"op": "loft", "id": "l", "profile": crescent, "keys": [{"y": 0}], "mat": "$a"}))
    assert all(x < 0 for x, _ in ls[0])  # only the western band remains
    with pytest.raises(ValueError, match="increasing"):
        OpsDoc.model_validate({"ops": [{"op": "loft", "id": "l", "profile": CIRCLE, "mat": "a:b",
                                        "keys": [{"y": 5}, {"y": 2}]}]})  # fmt: skip


def test_key_interpolation():
    keys = [LoftKey(y=0), LoftKey(y=10, dx=10), LoftKey(y=20, dx=0)]
    assert key_at(keys, 5, smooth=False)["dx"] == 5
    assert key_at(keys, 10, smooth=True)["dx"] == 10  # passes through the keys
    assert key_at(keys, 30, smooth=True)["dx"] == 0  # clamped above the last key


def test_sweep_tube():
    pts = [[0, 0, 0], [10, 5, 0], [20, 0, 0]]
    c = build({"op": "sweep", "id": "s", "points": pts, "radius": 1.5, "interp": "linear", "mat": "$a"})
    ox, oy, oz = c.origin
    cells = [(x - ox, y - oy, z - oz) for x, y, z in np.argwhere(c.grid.idx != 0)]
    assert (0, 0, 0) in cells and (19, 0, 0) in cells or (20, 0, 0) in cells
    seg = np.array([[0, 0, 0], [10, 5, 0]], float), np.array([[10, 5, 0], [20, 0, 0]], float)

    def dist(p):
        best = 99.0
        for a, b in (seg[0], seg[1]):
            t = np.clip(np.dot(p - a, b - a) / np.dot(b - a, b - a), 0, 1)
            best = min(best, float(np.linalg.norm(p - (a + t * (b - a)))))
        return best

    assert all(dist(np.array(cell) + 0.5) <= 1.5 + 1e-9 for cell in cells)
    length = 2 * math.hypot(10, 5)
    assert 0.7 < len(cells) / (math.pi * 1.5**2 * length) < 1.4


def build_with(style, *ops):
    return compile_ops(OpsDoc.model_validate({"style": style, "ops": list(ops)}))


def cells_of(c):
    """{design (x, y, z): block}."""
    ox, oy, oz = c.origin
    return {(int(x) - ox, int(y) - oy, int(z) - oz): c.grid.palette[c.grid.idx[x, y, z]]
            for x, y, z in np.argwhere(c.grid.idx != 0)}  # fmt: skip


STEP = {"east": (1, 0), "west": (-1, 0), "south": (0, 1), "north": (0, -1)}
ASCEND = {0: "east", 1: "west", 2: "south", 3: "north"}
COBBLE = {"a": "minecraft:cobblestone", "a.stairs": "minecraft:stone_stairs"}


@pytest.mark.parametrize("invert", [False, True])
def test_smooth_puts_stairs_on_the_steps(invert):
    keys = [{"y": 0}, {"y": 8, "scale": 0.3}] if not invert else [{"y": 0, "scale": 0.3}, {"y": 8}]
    cells = cells_of(build_with(COBBLE, {"op": "loft", "id": "cone", "profile": CIRCLE, "keys": keys,
                                         "interp": "linear", "mat": "$a", "smooth": True}))  # fmt: skip
    stairs = {p: b for p, b in cells.items() if "stairs" in b}
    assert len(stairs) > 40
    for (x, y, z), b in stairs.items():
        meta = int(b.split("@")[1]) if "@" in b else 0
        dx, dz = STEP[ASCEND[meta & 3]]
        dy = -1 if invert else 1
        assert bool(meta & 4) is invert  # upside-down under an overhang
        assert (x, y + dy, z) not in cells  # the open face...
        assert (x + dx, y + dy, z + dz) in cells  # ...and the stair rises toward where the surface continues
    top = max(y for _, y, _ in cells) if not invert else 0
    assert not any("stairs" in b for (_, y, _), b in cells.items() if y == top)  # flat top/bottom stays full


def test_smooth_needs_stairs():
    from img2schem.engine.compiler import CompileError

    cone = {"op": "loft", "id": "l", "profile": CIRCLE, "keys": [{"y": 0}, {"y": 6, "scale": 0.5}], "smooth": True}
    with pytest.raises(CompileError, match="set style"):
        build_with({"a": "minecraft:glass"}, {**cone, "mat": "$a"})  # no palette family, no override
    with pytest.raises(CompileError, match="slot"):
        build_with({}, {**cone, "mat": "minecraft:glass"})
    with pytest.raises(CompileError, match="stairs are needed"):
        build_with({"a": "minecraft:glass", "a.stairs": "minecraft:stone_slab"}, {**cone, "mat": "$a"})


def test_mullions_and_lights():
    style = {"a": "minecraft:glass", "b": "minecraft:quartz_block", "m": "minecraft:iron_block",
             "l": "minecraft:glowstone"}  # fmt: skip
    cells = cells_of(build_with(style, {"op": "loft", "id": "l", "profile": CIRCLE, "keys": [{"y": 0}, {"y": 8}],
                                        "fill": "shell", "mat": "$a", "floor_every": 4, "floor_mat": "$b",
                                        "mullions": {"count": 4, "mat": "$m"},
                                        "lights": {"every": 4, "mat": "$l"}}))  # fmt: skip
    ribs = {(x, z) for (x, y, z), b in cells.items() if b == "minecraft:iron_block" and y == 2}
    assert ribs == {(7, -1), (7, 0), (-8, -1), (-8, 0), (-1, 7), (0, 7), (-1, -8), (0, -8)}  # E, W, S, N
    assert not any(b == "minecraft:iron_block" for (_, y, _), b in cells.items() if y % 4 == 0)  # not in floors
    lights = {(x, y, z) for (x, y, z), b in cells.items() if b == "minecraft:glowstone"}
    assert {y for _, y, _ in lights} == {0, 4, 8}
    assert all(x % 4 == 0 and z % 4 == 0 and abs(x + 0.5) < 7 and abs(z + 0.5) < 7 for x, _, z in lights)
    assert len(lights) == 3 * 9  # x, z in {-4, 0, 4}


def test_mullions_turn_with_the_keys():
    style = {"a": "minecraft:glass", "m": "minecraft:iron_block"}
    cells = cells_of(build_with(style, {"op": "loft", "id": "l", "profile": CIRCLE, "fill": "shell", "mat": "$a",
                                        "keys": [{"y": 0}, {"y": 10, "rotate": 45}], "interp": "linear",
                                        "mullions": {"count": 4, "mat": "$m"}}))  # fmt: skip
    top = [(x + 0.5, z + 0.5) for (x, y, z), b in cells.items() if b == "minecraft:iron_block" and y == 10]
    assert top and all(abs(abs(math.degrees(math.atan2(z, x))) % 90 - 45) < 10 for x, z in top)  # diagonals


@pytest.mark.parametrize(("radius", "turn"), [(1, "ccw"), (2, "cw")])
def test_spiral_stair_is_walkable_and_opens_the_floors(radius, turn):
    style = {"f": "minecraft:planks", "f.stairs": "minecraft:oak_stairs", "c": "minecraft:log"}
    cells = cells_of(build_with(style,
                                {"op": "floors", "id": "fl", "footprint": {"x0": -5, "z0": -5, "x1": 5, "z1": 5},
                                 "ys": [0, 4, 8, 12], "mat": "$f"},
                                {"op": "spiral_stair", "id": "s", "center": [0, 0], "y0": 1, "y1": 12,
                                 "radius": radius, "turn": turn, "mat": "$f.stairs", "column": "$c"}))  # fmt: skip
    steps = sorted(((y, x, z), b) for (x, y, z), b in cells.items() if "stairs" in b)
    assert [y for (y, _, _), _ in steps] == list(range(1, 13))  # one stair per level
    for ((y, x, z), b), ((_, nx, nz), _) in zip(steps, steps[1:], strict=False):
        meta = int(b.split("@")[1]) if "@" in b else 0
        assert (nx - x, nz - z) == STEP[ASCEND[meta]]  # each stair rises toward the next one
        assert (x, y + 1, z) not in cells and (x, y + 2, z) not in cells  # headroom
    ring = {(x, z) for (_, x, z), _ in steps}
    for fy in (4, 8, 12):
        opened = [(x, z) for x, z in ring if (x, fy, z) in cells and "stairs" not in cells[(x, fy, z)]]
        assert opened == []  # the floor is cleared around the stair
    (y0, x0, z0), _ = steps[0]
    (_, x1, z1), _ = steps[1]
    cross = (x0 * z1 - z0 * x1)  # z points south, so a clockwise turn seen from above is positive
    assert (cross > 0) is (turn == "cw")
    assert cells[(0, 5, 0)] == "minecraft:log"  # the central column
