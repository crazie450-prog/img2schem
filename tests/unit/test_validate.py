import numpy as np

from img2schem.config import Budgets
from img2schem.instance.discover import discover_vanilla
from img2schem.models import BlockGrid
from img2schem.palette.build import extract
from img2schem.stages.validate import failed, validate_grid


def _palette(launchers):
    inst = next(i for i in discover_vanilla(launchers["vanilla"][0]) if i.loader == "fabric")
    return extract(inst)[0]


def test_clean_grid_passes(launchers):
    g = BlockGrid.empty(3, 3, 3)
    g.fill((0, 0, 0), (2, 0, 2), "minecraft:bricks")
    g.set(1, 1, 0, "fabdeco:slate_shingle_stairs[facing=north,half=bottom,shape=straight]")
    assert validate_grid(g, Budgets(), _palette(launchers)) == []


def test_unknown_block_and_bad_state(launchers):
    g = BlockGrid.empty(2, 1, 1)
    g.set(0, 0, 0, "create:andesite_casing")
    g.set(1, 0, 0, "minecraft:oak_stairs[facing=up]")
    issues = validate_grid(g, Budgets(), _palette(launchers))
    assert [i.rule for i in issues] == ["R10.1b", "R10.1b"] and failed(issues)


def test_malformed_state_without_palette():
    g = BlockGrid(np.array([[[1]]]), ["minecraft:air", "Stone"])
    (issue,) = validate_grid(g, Budgets())
    assert issue.rule == "R10.1" and issue.severity == "error"


def test_flagged_block(launchers):
    g = BlockGrid.empty(1, 1, 1)
    g.set(0, 0, 0, "minecraft:chest[facing=north]")
    (issue,) = validate_grid(g, Budgets(), _palette(launchers))
    assert "code_rendered" in issue.message


def test_budgets():
    g = BlockGrid.empty(10, 2, 2)
    g.fill((0, 0, 0), (9, 1, 1), "minecraft:stone")
    issues = validate_grid(g, Budgets(max_dim=8, max_nonair=10, hard_max_total=20))
    assert sorted(i.severity for i in issues) == ["error", "warning", "warning"]
    assert not failed(validate_grid(g, Budgets(max_dim=8), allow_large=True))
    assert failed(validate_grid(g, Budgets(max_dim=8)), strict=True)
