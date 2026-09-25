import json
import os
from pathlib import Path

import numpy as np
import pytest
from fixtures.jars.make import nei_dumps

from img2schem.engine.compiler import compile_ops
from img2schem.models import BuildSpec
from img2schem.palette.nei import import_nei
from img2schem.palette.query import PaletteIndex
from img2schem.stages.plan_template import PlanError, plan_template

EXAMPLE = Path(__file__).parents[2] / "examples" / "brick_house.spec.json"
GOLDEN = Path(__file__).parents[1] / "golden" / "house_spec.npz"


def spec(**changes):
    data = json.loads(EXAMPLE.read_text())
    for path, value in changes.items():
        node = data
        *parents, leaf = path.split("__")
        for p in parents:
            node = node[p]
        node[leaf] = value
    return BuildSpec.model_validate(data)


def ops_by_id(doc):
    return {o.id: o for o in doc.ops}


def test_example_layout():
    doc, warnings = plan_template(spec())
    assert warnings == []
    ops = ops_by_id(doc)
    assert ops["walls"].footprint.x1 == 11 and ops["walls"].footprint.z1 == 7  # 12 x round(12 * 0.67)
    assert ops["walls"].y0 == 1 and ops["walls"].height == 9  # storeys 5 + 5, roof at y = 10
    assert ops["floors"].ys == [0, 5] and ops["roof"].y0 == 10 and ops["roof"].type == "gable"
    assert doc.style["glass"] == "minecraft:glass_pane"  # role default
    windows = [o for o in doc.ops if o.op == "window"]
    assert len(windows) == 5 and all(o.recess == 0 for o in windows)  # flush in 1-block walls
    for w in windows:  # never on the ground row or the eaves row, at least 2 tall
        assert w.y0 >= 2 and w.y1 <= 8 and w.y1 - w.y0 + 1 >= 2
    doors = [o for o in doc.ops if o.op == "door"]
    assert [(d.pos, d.hinge) for d in doors] == [((5, 1, 0), "left"), ((6, 1, 0), "right")]  # 2 wide: double


def test_golden_grid():
    """A-T: the example spec compiles to the committed grid. Regenerate with UPDATE_GOLDEN=1 after an
    intentional change, and look at the previews before committing."""
    c = compile_ops(plan_template(spec())[0])
    grid = c.grid.compact()
    if os.environ.get("UPDATE_GOLDEN"):
        np.savez_compressed(GOLDEN, idx=grid.idx, palette=np.array(grid.palette))
    g = np.load(GOLDEN)
    assert list(g["palette"]) == grid.palette
    assert np.array_equal(g["idx"], grid.idx)


def test_spec_edits_change_the_build_without_api():
    base = compile_ops(plan_template(spec())[0])
    taller = compile_ops(plan_template(spec(facade__storeys=3, roof__type="hip"))[0])
    assert taller.grid.shape[1] == base.grid.shape[1] + 5  # one more 5-block storey
    doc = plan_template(spec(facade__storeys=3, roof__type="hip"))[0]
    assert ops_by_id(doc)["roof"].type == "hip" and ops_by_id(doc)["floors"].ys == [0, 5, 10]
    low = ops_by_id(plan_template(spec(roof__pitch="low"))[0])["roof"]
    assert low.pitch == "1:2"
    wall = plan_template(spec(materials__wall={"chosen": "minecraft:stonebrick"}))[0]
    assert wall.style["wall"] == "minecraft:stonebrick"


def test_window_clamping_and_missing_door():
    s = spec(elements=[{"kind": "window", "bbox": [0.1, 0.0, 0.2, 0.05]},  # at the eaves
                       {"kind": "window", "bbox": [0.75, 0.97, 0.85, 1.0]},  # at the ground
                       {"kind": "garage", "bbox": [0.2, 0.6, 0.3, 1.0]}])  # fmt: skip
    doc, warnings = plan_template(s)
    w = [o for o in doc.ops if o.op == "window"]
    assert (w[0].y0, w[0].y1) == (7, 8) and (w[1].y0, w[1].y1) == (2, 3)
    assert any("garage" in x for x in warnings) and any("no door" in x for x in warnings)
    assert any(o.op == "door" for o in doc.ops)


def test_required_materials_and_roof_fallback(tmp_path):
    with pytest.raises(PlanError, match="materials.roof.chosen"):
        plan_template(spec(materials={"wall": {"chosen": "minecraft:brick_block"}}))
    index = PaletteIndex(import_nei(nei_dumps(tmp_path / "dumps")))
    # Colored Stone Bricks has no stairs in the fixture palette; Stone Bricks (stairs + slab) is the nearest.
    s = spec(
        materials={"wall": {"chosen": "minecraft:stonebrick"}, "roof": {"chosen": "ExtraUtilities:colorStoneBrick"}}
    )
    doc, warnings = plan_template(s, index)
    assert doc.style["roof"] == "minecraft:stonebrick" and any("RT.3" in w for w in warnings)


def test_doors_win_over_windows_on_short_buildings():
    """Owner bug: at 1 storey a measured upper window landed on the door's top half, which pops the door."""
    doc, warnings = plan_template(spec(facade__storeys=1))
    c = compile_ops(doc)
    ox, oy, oz = c.origin
    for x in (5, 6):
        lower = c.grid.palette[c.grid.idx[x + ox, 1 + oy, oz]]
        upper = c.grid.palette[c.grid.idx[x + ox, 2 + oy, oz]]
        assert lower.startswith("minecraft:wooden_door") and upper.startswith("minecraft:wooden_door@")
        assert int(upper.split("@")[1]) >= 8  # a real upper half
    assert any("overlap a door" in w for w in warnings)
