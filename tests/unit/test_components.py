import numpy as np
import pytest

from img2schem.engine.compiler import CompileError, compile_ops
from img2schem.engine.ops import OpsDoc
from img2schem.engine.states import transform_meta

STYLE = {"w": "minecraft:planks", "s": "minecraft:oak_stairs", "log": "minecraft:log", "door": "minecraft:wooden_door",
         "alt": "minecraft:cobblestone", "f": "minecraft:fence"}  # fmt: skip
PART = [  # an L of planks, an east-ascending stair, a north door, an x-axis log
    {"op": "box", "id": "l", "from": [0, 0, 0], "to": [2, 0, 0], "mat": "$w"},
    {"op": "box", "id": "l2", "from": [0, 0, 1], "to": [0, 0, 1], "mat": "$w"},
    {"op": "set", "id": "st", "cells": [[1, 1, 0]], "block": "minecraft:oak_stairs"},
    {"op": "door", "id": "dr", "pos": [2, 1, 0], "facing": "north"},
    {"op": "set", "id": "lg", "cells": [[0, 1, 0]], "block": "minecraft:log@4"},
]


def cells_of(*ops, style=STYLE):
    c = compile_ops(OpsDoc.model_validate({"style": style, "ops": list(ops)}))
    ox, oy, oz = c.origin
    return {(int(x) - ox, int(y) - oy, int(z) - oz): c.grid.palette[c.grid.idx[x, y, z]]
            for x, y, z in np.argwhere(c.grid.idx != 0)}  # fmt: skip


def test_place_rotates_positions_and_states():
    base = cells_of({"op": "define", "id": "def", "name": "p", "ops": PART}, {"op": "place", "id": "a", "name": "p"})
    turned = cells_of({"op": "define", "id": "def", "name": "p", "ops": PART},
                      {"op": "place", "id": "a", "name": "p", "pos": [10, 0, 0], "rotate": 90})  # fmt: skip
    assert base[(1, 1, 0)] == "minecraft:oak_stairs"  # ascending east (meta 0)
    # a quarter turn clockwise seen from above: (x, z) -> (-z, x); east -> south, north -> east, x axis -> z axis
    assert turned[(10, 1, 1)] == "minecraft:oak_stairs@2"
    assert turned[(10, 1, 2)] == "minecraft:wooden_door" and turned[(10, 2, 2)] == "minecraft:wooden_door@8"
    assert turned[(10, 1, 0)] == "minecraft:log@8"
    assert {(10 - z, y, x) for x, y, z in base} == set(turned)


def test_array_and_mirror_of_a_place():
    got = cells_of({"op": "define", "id": "def", "name": "p", "ops": PART},
                   {"op": "array", "id": "a", "name": "p", "count": 3, "step": [0, 0, 4], "mirror": "x"})  # fmt: skip
    assert {z for _, _, z in got} == {0, 1, 4, 5, 8, 9}
    assert got[(-1, 1, 4)] == "minecraft:oak_stairs@1"  # mirrored east -> west
    assert got[(-2, 2, 8)] == "minecraft:wooden_door@9"  # the mirror image has its hinge on the other side


@pytest.mark.parametrize(("shape", "meta"), [(s, m) for s in ("stairs", "door", "log") for m in range(16)])
def test_state_transforms_compose(shape, meta):
    for turns in range(4):
        assert transform_meta(shape, transform_meta(shape, meta, turns), (4 - turns) % 4) == meta
    for mirror in ("x", "z"):
        assert transform_meta(shape, transform_meta(shape, meta, 0, mirror), 0, mirror) == meta
    assert transform_meta(shape, meta, 2, "x") == transform_meta(shape, meta, 0, "z")  # x-mirror + 180 = z-mirror


def test_mirror_op_makes_a_symmetric_build():
    half = [{"op": "box", "id": "wall", "group": "west", "from": [0, 0, 0], "to": [2, 3, 0], "mat": "$w"},
            {"op": "set", "id": "eave", "group": "west", "cells": [[0, 4, 0]], "block": "minecraft:oak_stairs@0"},
            {"op": "mirror", "id": "m", "ops": ["west"], "axis": "x", "plane": 3.5}]  # fmt: skip
    got = cells_of(*half)
    assert {x for x, _, _ in got} == {0, 1, 2, 4, 5, 6}  # block 3 is the mirror line, left empty
    assert got[(6, 4, 0)] == "minecraft:oak_stairs@1"  # east-ascending becomes west-ascending
    assert all(got.get((6 - x, y, z)) is not None for x, y, z in got)
    with pytest.raises(CompileError, match="no earlier op"):
        cells_of({"op": "mirror", "id": "m", "ops": ["nothing"], "axis": "z", "plane": 0})


def test_vary_is_seeded_and_touches_only_the_targets_own_blocks():
    ops = [{"op": "box", "id": "wall", "from": [0, 0, 0], "to": [29, 9, 0], "mat": "$w"},
           {"op": "set", "id": "st", "cells": [[0, 10, 0]], "block": "minecraft:oak_stairs"},
           {"op": "box", "id": "other", "from": [0, 0, 2], "to": [9, 0, 2], "mat": "$w"}]  # fmt: skip
    a = cells_of(*ops, {"op": "vary", "id": "v", "target": "wall", "mat": "$alt", "ratio": 0.2, "seed": 1})
    b = cells_of(*ops, {"op": "vary", "id": "v", "target": "wall", "mat": "$alt", "ratio": 0.2, "seed": 1})
    c = cells_of(*ops, {"op": "vary", "id": "v", "target": "wall", "mat": "$alt", "ratio": 0.2, "seed": 2})
    varied = {p for p, blk in a.items() if blk == "minecraft:cobblestone"}
    assert a == b and a != c
    assert 0.12 < len(varied) / 300 < 0.28
    assert all(z == 0 and y < 10 for _, y, z in varied)  # not the stair, not the other op


def test_railing_is_face_connected_and_closes():
    got = cells_of({"op": "railing", "id": "r", "path": [[0, 0], [4, 2], [4, 5]], "y": 1, "mat": "$f",
                    "closed": True})  # fmt: skip
    pts = sorted((x, z) for x, _, z in got)
    assert (0, 0) in pts and (4, 2) in pts and (4, 5) in pts
    for p in pts:  # every block touches another on a face
        assert any((p[0] + dx, p[1] + dz) in pts for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)))


def test_component_errors_and_carves_stay_inside():
    with pytest.raises(CompileError, match="no component"):
        cells_of({"op": "place", "id": "p", "name": "missing"})
    with pytest.raises(ValueError, match="another define"):
        inner = {"op": "define", "id": "b", "name": "b", "ops": [{"op": "carve", "id": "c", "from": [0, 0, 0],
                                                                 "to": [0, 0, 0]}]}  # fmt: skip
        OpsDoc.model_validate({"ops": [{"op": "define", "id": "a", "name": "a", "ops": [inner]}]})
    got = cells_of({"op": "box", "id": "floor", "from": [0, 0, 0], "to": [4, 0, 4], "mat": "$w"},
                   {"op": "define", "id": "d", "name": "hole", "ops": [
                       {"op": "box", "id": "b", "from": [0, 1, 0], "to": [0, 1, 0], "mat": "$alt"},
                       {"op": "carve", "id": "c", "from": [0, -1, 0], "to": [2, 0, 2]}]},
                   {"op": "place", "id": "p", "name": "hole", "pos": [1, 0, 1]})  # fmt: skip
    assert len([p for p in got if p[1] == 0]) == 25 and got[(1, 1, 1)] == "minecraft:cobblestone"


def test_set_limit_counts_sets_inside_components():
    sets = [{"op": "set", "id": f"s{i}", "cells": [[i, j, 0] for j in range(64)], "block": "a:b"} for i in range(5)]
    with pytest.raises(ValueError, match="limit"):
        OpsDoc.model_validate({"ops": [{"op": "define", "id": "d", "name": "d", "ops": sets}]})


