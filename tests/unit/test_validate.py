import numpy as np

from img2schem.config import Budgets
from img2schem.models import BlockGrid, WorldPalette
from img2schem.stages.validate import autofix, contrast_issues, failed, shape_lookup, validate_grid

PAL = WorldPalette(world="w", level_dat="-", blocks={"minecraft:stone": 1, "chisel:marble_stairs.0": 2052})
SHAPE = shape_lookup(None)
DOOR_LO, DOOR_HI = "minecraft:wooden_door@3", "minecraft:wooden_door@8"


def rules(issues, severity=None):
    return sorted(i.rule for i in issues if severity is None or i.severity == severity)


def house(w=5, h=4, length=4):
    """A ground slab with a wall and a door in it."""
    g = BlockGrid.empty(w, h, length)
    g.fill((0, 0, 0), (w - 1, 0, length - 1), "minecraft:stone")
    g.fill((0, 1, 0), (w - 1, h - 1, 0), "minecraft:stone")
    g.set(2, 1, 0, DOOR_LO)
    g.set(2, 2, 0, DOOR_HI)
    return g


def test_clean_house_passes():
    g = house()
    g.set(1, 1, 1, "chisel:marble_stairs.0@6")
    issues = validate_grid(g, Budgets(), None, shape_of=SHAPE)
    assert rules(issues) == ["R10.10"] and not failed(issues, strict=True)  # info: chisel is required


def test_unknown_block_and_malformed():
    g = BlockGrid.empty(1, 1, 1)
    g.set(0, 0, 0, "gregtech:nothing@2")
    assert rules(validate_grid(g, Budgets(), PAL), "error") == ["R10.1b"]
    bad = BlockGrid(np.array([[[1]]]), ["minecraft:air", "stone@3"])
    assert rules(validate_grid(bad, Budgets()), "error") == ["R10.1"]


def test_budgets():
    g = BlockGrid.empty(10, 2, 2)
    g.fill((0, 0, 0), (9, 1, 1), "minecraft:stone")
    issues = [i for i in validate_grid(g, Budgets(max_dim=8, max_nonair=10, hard_max_total=20)) if i.rule == "R10.2"]
    assert sorted(i.severity for i in issues) == ["error", "warning", "warning"]
    assert not failed(validate_grid(g, Budgets(max_dim=8), allow_large=True))


def test_door_pair_and_support_rules_and_fixes():
    g = house()
    g.idx[2, 2, 0] = 0  # lower half alone, air above
    assert rules(validate_grid(g, Budgets(), shape_of=SHAPE), "error") == ["R10.5"]
    fixed = autofix(g, SHAPE)
    assert [i.rule for i in fixed] == ["R10.5"] and "added the missing upper half" in fixed[0].message
    assert g.palette[g.idx[2, 2, 0]] == "minecraft:wooden_door@8"
    assert autofix(g, SHAPE) == []  # idempotent

    g = house()
    g.set(2, 2, 0, "minecraft:glass_pane")  # a window replaced the upper half (the owner's bug)
    fixed = autofix(g, SHAPE)
    assert "orphan lower half" in fixed[0].message and g.idx[2, 1, 0] == 0

    g = house()
    g.idx[2, 0, 0] = 0  # nothing under the door
    assert "R10.6" in rules(validate_grid(g, Budgets(), shape_of=SHAPE), "error")
    fixed = autofix(g, SHAPE)
    assert [i.rule for i in fixed] == ["R10.6"] and g.idx[2, 1, 0] == 0 and g.idx[2, 2, 0] == 0


def test_missing_ground_door():
    g = house()
    g.idx[2, 1, 0] = g.idx[2, 2, 0] = 0
    assert rules(validate_grid(g, Budgets(), shape_of=SHAPE)) == ["R10.3b"]


def test_small_fragments_removed_large_kept():
    g = house()
    g.set(4, 3, 3, "minecraft:stone")  # 1 block, floating
    g.fill((0, 3, 2), (1, 3, 3), "minecraft:stone")  # 4 blocks, floating
    fixed = autofix(g, SHAPE)
    assert [i.message for i in fixed] == ["removed a floating fragment of 1 blocks"]
    assert g.idx[4, 3, 3] == 0 and g.idx[0, 3, 2] != 0
    assert rules(validate_grid(g, Budgets(), shape_of=SHAPE), "warning") == ["R10.3"]


def test_window_under_roof_and_roof_hole_need_labels():
    g = house()
    labels = np.zeros(g.shape, np.uint8)
    labels[1, 2, 0] = 2  # window...
    labels[1, 3, 0] = 4  # ...right under a roof cell
    labels[0, 3, 1] = labels[2, 3, 1] = 4  # roof on both sides of an air cell
    issues = validate_grid(g, Budgets(), shape_of=SHAPE, labels=labels)
    assert rules(issues, "warning") == ["R10.3b", "R10.8"]


def test_contrast_guard():
    labs = {"minecraft:quartz_block": (70.0, 0.0, 2.0), "minecraft:stone": (40.0, 0.0, 0.0),
            "minecraft:sandstone": (68.0, 1.0, 5.0)}  # fmt: skip
    assert contrast_issues({"wall": "minecraft:stone", "trim": "minecraft:quartz_block"}, labs.get) == []
    (issue,) = contrast_issues({"wall": "minecraft:sandstone", "trim": "minecraft:quartz_block"}, labs.get)
    assert issue.rule == "R10.9"
