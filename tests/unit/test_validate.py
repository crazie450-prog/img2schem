import numpy as np

from img2schem.config import Budgets
from img2schem.models import BlockGrid, WorldPalette
from img2schem.stages.validate import failed, validate_grid

PAL = WorldPalette(world="w", level_dat="-", blocks={"minecraft:stone": 1, "chisel:marble_stairs.0": 2052})


def test_clean_grid_passes():
    g = BlockGrid.empty(3, 3, 3)
    g.fill((0, 0, 0), (2, 0, 2), "minecraft:stone")
    g.set(1, 1, 0, "chisel:marble_stairs.0@6")
    assert validate_grid(g, Budgets(), PAL) == []


def test_unknown_block():
    g = BlockGrid.empty(1, 1, 1)
    g.set(0, 0, 0, "gregtech:nothing@2")
    (issue,) = validate_grid(g, Budgets(), PAL)
    assert issue.rule == "R10.1b" and failed([issue])


def test_malformed_without_palette():
    g = BlockGrid(np.array([[[1]]]), ["minecraft:air", "stone@3"])
    (issue,) = validate_grid(g, Budgets())
    assert issue.rule == "R10.1" and issue.severity == "error"


def test_budgets():
    g = BlockGrid.empty(10, 2, 2)
    g.fill((0, 0, 0), (9, 1, 1), "minecraft:stone")
    issues = validate_grid(g, Budgets(max_dim=8, max_nonair=10, hard_max_total=20))
    assert sorted(i.severity for i in issues) == ["error", "warning", "warning"]
    assert not failed(validate_grid(g, Budgets(max_dim=8), allow_large=True))
    assert failed(validate_grid(g, Budgets(max_dim=8)), strict=True)
