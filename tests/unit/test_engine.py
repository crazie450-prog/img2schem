import numpy as np
import pytest
from fixtures.jars.make import nei_dumps

from img2schem.engine.compiler import CompileError, compile_ops
from img2schem.engine.materials import MaterialError, Resolver
from img2schem.engine.ops import OpsDoc
from img2schem.engine.states import door_metas, log_meta, slab_meta, stairs_meta
from img2schem.models import AIR
from img2schem.palette.nei import import_nei
from img2schem.palette.query import PaletteIndex
from img2schem.stages.export_schem import write_schematic

STYLE = {
    "wall": "minecraft:brick_block",
    "floor": "minecraft:planks",
    "roof": "minecraft:planks@1",
    "roof.stairs": "minecraft:spruce_stairs",
    "roof.slab": "minecraft:wooden_slab@1",
    "glass": "minecraft:glass_pane",
    "door": "minecraft:wooden_door",
    "trim": "minecraft:quartz_block",
}
FP = {"x0": 0, "z0": 0, "x1": 6, "z1": 4}  # 7 wide, 5 deep


def build(*ops, style=None, index=None):
    return compile_ops(OpsDoc.model_validate({"style": style or STYLE, "ops": list(ops)}), index)


def at(c, x, y, z):
    """Block at design coordinates."""
    ox, oy, oz = c.origin
    return c.grid.palette[c.grid.idx[x + ox, y + oy, z + oz]]


def blocks(c):
    """{design (x, y, z): block} of all non-air cells."""
    ox, oy, oz = c.origin
    return {
        (int(x) - ox, int(y) - oy, int(z) - oz): c.grid.palette[c.grid.idx[x, y, z]]
        for x, y, z in np.argwhere(c.grid.idx != 0)
    }


def test_state_tables():
    assert stairs_meta(0, "south") == 2 and stairs_meta(8, "north", upside_down=True) == 15
    assert door_metas("north") == (3, 8) and door_metas("east", hinge_right=True) == (0, 9)
    assert log_meta(1, "x") == 5 and log_meta(2, "z") == 10 and log_meta(3, "y") == 3
    assert slab_meta(5, top=True, has_top_block=False) == 13 and slab_meta(9, top=True, has_top_block=True) == 9


def test_resolver_slots_overrides_and_errors():
    res = Resolver(STYLE)
    assert res("$wall").block == "minecraft:brick_block"
    assert res("$roof.stairs").block == "minecraft:spruce_stairs" and res("$roof.stairs").shape == "stairs"
    assert res("chisel:marble@3").block == "chisel:marble@3"
    with pytest.raises(MaterialError, match="no slot"):
        res("$nope")
    with pytest.raises(MaterialError, match="no palette"):
        res("$wall.stairs")
    with pytest.raises(MaterialError, match="family member"):
        res("$wall.pillar")


@pytest.fixture
def index(tmp_path):
    return PaletteIndex(import_nei(nei_dumps(tmp_path / "dumps")))


def test_resolver_families_from_palette(index):
    res = Resolver({"roof": "minecraft:stonebrick"}, index)
    assert res("$roof.stairs").block == "minecraft:stone_brick_stairs"
    assert res("$roof.slab").block == "minecraft:stone_slab@5"
    with pytest.raises(MaterialError, match="no matching wall"):
        res("$roof.wall")
    with pytest.raises(MaterialError, match="not in the palette"):
        res("create:casing")


def test_walls_floors_and_keep():
    c = build(
        {"op": "walls", "id": "w", "footprint": FP, "y0": 0, "height": 3},
        {"op": "floors", "id": "f", "footprint": FP, "ys": [0], "mode": "keep"},
    )
    cells = blocks(c)
    ring = 2 * 7 + 2 * 3
    assert sum(b == "minecraft:brick_block" for b in cells.values()) == ring * 3
    assert sum(b == "minecraft:planks" for b in cells.values()) == 5 * 3  # keep: only the interior of layer 0
    assert c.summaries[1].cells == 15 and c.summaries[1].overwritten == 0


def test_door_and_openings():
    c = build(
        {"op": "walls", "id": "w", "footprint": FP, "y0": 0, "height": 4},
        {"op": "openings", "id": "o", "footprint": FP, "face": "front", "sills": [1], "w": 1, "h": 2, "count": 2,
         "spacing": 3},
        {"op": "door", "id": "d", "pos": [3, 0, 0], "facing": "north"},
    )  # fmt: skip
    assert at(c, 3, 0, 0) == "minecraft:wooden_door@3" and at(c, 3, 1, 0) == "minecraft:wooden_door@8"
    windows = sorted(p for p, b in blocks(c).items() if b == "minecraft:glass_pane")
    assert windows == [(1, 1, 0), (1, 2, 0), (5, 1, 0), (5, 2, 0)]  # centered: 2 windows, 3 apart
    with pytest.raises(CompileError, match="don't fit"):
        build({"op": "openings", "id": "o", "footprint": FP, "face": "left", "sills": [1], "w": 3, "count": 2})


def test_gable_1_1_rows_ridge_and_gable_fill():
    c = build({"op": "roof", "id": "r", "footprint": FP, "y0": 5, "overhang": 1})
    # Depth 5 + 2 overhang = 7 rows: 3 per side rising toward the middle, a full-block ridge in row z = 2.
    for x in range(-1, 8):
        assert at(c, x, 5, -1) == "minecraft:spruce_stairs@2"  # north slope ascends south
        assert at(c, x, 6, 0) == "minecraft:spruce_stairs@2"
        assert at(c, x, 5, 5) == "minecraft:spruce_stairs@3"  # south slope ascends north
        assert at(c, x, 7, 2) == "minecraft:planks@1"  # ridge cap, flush with the top stairs
    fill = {p for p, b in blocks(c).items() if b == "minecraft:brick_block"}
    assert {p[0] for p in fill} == {0, 6}  # only the two gable-end walls
    assert max(p[1] for p in fill) == 6 and (0, 7, 2) not in fill  # never above the roof


def test_gable_along_z_hip_shed_flat():
    ew = blocks(build({"op": "roof", "id": "r", "footprint": FP, "y0": 0, "ridge": "z", "overhang": 0}))
    assert ew[(0, 0, 2)] == "minecraft:spruce_stairs" and ew[(6, 0, 2)] == "minecraft:spruce_stairs@1"

    hip = blocks(build({"op": "roof", "id": "r", "footprint": FP, "y0": 0, "type": "hip", "overhang": 0}))
    assert hip[(3, 0, 0)] == "minecraft:spruce_stairs@2" and hip[(0, 0, 2)] == "minecraft:spruce_stairs"
    assert hip[(5, 1, 2)] == "minecraft:spruce_stairs@1"  # layer 1: the ring shrank by one
    assert [p for p, b in hip.items() if b == "minecraft:planks@1"] == [(2, 1, 2), (3, 1, 2), (4, 1, 2)]  # ridge

    shed = blocks(build({"op": "roof", "id": "r", "footprint": FP, "y0": 0, "type": "shed", "rise": "south",
                         "overhang": 1}))  # fmt: skip
    assert shed[(0, 0, -1)] == "minecraft:spruce_stairs@2" and shed[(0, 5, 4)] == "minecraft:spruce_stairs@2"
    assert shed[(0, 5, 5)] == "minecraft:spruce_stairs@2"  # overhang beyond the high wall stays level
    assert all(p[1] < 5 for p, b in shed.items() if b == "minecraft:brick_block" and p[2] == 4)  # high wall

    flat = blocks(build({"op": "roof", "id": "r", "footprint": FP, "y0": 3, "type": "flat", "overhang": 0,
                         "parapet": True}))  # fmt: skip
    assert len([p for p in flat if p[1] == 3]) == 35 and len([p for p in flat if p[1] == 4]) == 20


def test_slab_pitch_and_steep_pitch():
    low = blocks(build({"op": "roof", "id": "r", "footprint": FP, "y0": 0, "pitch": "1:2", "overhang": 0}))
    assert low[(0, 0, 0)] == "minecraft:wooden_slab@1" and low[(0, 0, 1)] == "minecraft:wooden_slab@9"
    assert low[(0, 1, 2)] == "minecraft:wooden_slab@1"  # ridge: bottom slab one block up
    steep = blocks(build({"op": "roof", "id": "r", "footprint": FP, "y0": 0, "pitch": "2:1", "overhang": 0}))
    assert steep[(0, 0, 0)] == "minecraft:planks@1" and steep[(0, 1, 0)] == "minecraft:spruce_stairs@2"
    assert steep[(0, 3, 1)] == "minecraft:spruce_stairs@2"


def test_chisel_top_slab_block_used_for_top_halves(index):
    style = {"roof": "minecraft:stonebrick", "roof.slab": "chisel:marble_slab@9", "wall": "minecraft:stonebrick"}
    low = blocks(build({"op": "roof", "id": "r", "footprint": FP, "y0": 0, "pitch": "1:2", "overhang": 0},
                       style=style, index=index))  # fmt: skip
    assert low[(0, 0, 0)] == "chisel:marble_slab@9" and low[(0, 0, 1)] == "chisel:marble_slab_top@9"


def test_logs_get_their_axis():
    c = build(
        {"op": "column", "id": "c", "pos": [0, 0], "height": 2, "mat": "minecraft:log@1"},
        {"op": "beam", "id": "b", "from": [0, 3, 0], "to": [4, 3, 0], "mat": "minecraft:log@1"},
        {"op": "beam", "id": "b2", "from": [0, 4, 0], "to": [0, 4, 3], "mat": "minecraft:log@1"},
    )
    assert at(c, 0, 1, 0) == "minecraft:log@1" and at(c, 2, 3, 0) == "minecraft:log@5"
    assert at(c, 0, 4, 2) == "minecraft:log@9"


def test_carve_trim_normalization_and_set_limits():
    c = build(
        {"op": "box", "id": "b", "from": [-2, 0, -3], "to": [2, 2, 1], "mat": "$wall"},
        {"op": "carve", "id": "c", "from": [-1, 1, -2], "to": [1, 1, 0]},
        {"op": "trim_band", "id": "t", "footprint": {"x0": -2, "z0": -3, "x1": 2, "z1": 1}, "y": 3, "outset": 1},
    )
    assert c.origin == (3, 0, 4) and c.grid.shape == (7, 4, 7)
    assert at(c, 0, 1, -1) == AIR and at(c, 0, 0, -1) == "minecraft:brick_block"
    assert at(c, -3, 3, -4) == "minecraft:quartz_block" and at(c, 0, 3, 0) == AIR
    with pytest.raises(ValueError, match="limit is 256"):
        OpsDoc.model_validate({"ops": [{"op": "set", "id": f"s{i}", "cells": [[i, 0, j] for j in range(64)],
                                        "block": "minecraft:stone"} for i in range(5)]})  # fmt: skip
    with pytest.raises(ValueError, match="unique"):
        OpsDoc.model_validate({"ops": [{"op": "carve", "id": "a", "from": [0, 0, 0], "to": [0, 0, 0]}] * 2})


def test_deterministic_bytes(tmp_path):
    from pathlib import Path

    doc = OpsDoc.model_validate_json(Path("examples/house.ops.json").read_text())
    a = write_schematic(tmp_path / "a.schematic", compile_ops(doc).grid).read_bytes()
    b = write_schematic(tmp_path / "b.schematic", compile_ops(doc).grid).read_bytes()
    assert a == b
