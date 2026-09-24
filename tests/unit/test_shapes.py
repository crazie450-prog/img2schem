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
