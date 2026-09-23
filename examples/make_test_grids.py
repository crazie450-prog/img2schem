"""Phase 0 hand-made test grids (SOW §7 Phase 0 task 6, re-scoped for GTNH 1.7.10) for docs/TEST_BED.md.

    python examples/make_test_grids.py                                   # vanilla-block grids
    python examples/make_test_grids.py --modded-full <modid:name[@meta]> --modded-stairs <modid:name>

Writes out/testgrids/<name>/<name>.schematic + preview PNGs, validates block names against the selected
world (`img2schem world use`), and copies each file into the instance's WorldEdit schematics folder.

Block names and metadata are 1.7.10 test-bed fixtures, not build output:
- wool: 0 white, 14 red;
- stairs: 0 ascends east, 1 west, 2 south, 3 north; +4 upside-down (BlockStairs.onBlockPlacedBy);
- wooden_door lower half 0-3 = east, south, west, north; upper half 8 (hinge left) (ItemDoor.onItemUse);
- glass panes and fences connect in game (no stored state in 1.7.10).
"""

from __future__ import annotations

from pathlib import Path

import typer

from img2schem.cli import _active_instance, _active_palette
from img2schem.config import load_settings
from img2schem.models import BlockGrid
from img2schem.stages.export_schem import SchemMeta, copy_to_schematics_dir, write_schematic
from img2schem.stages.preview import write_previews
from img2schem.stages.validate import failed, validate_grid

# Stairs metadata for "ascends toward" a direction.
ASCEND = {"east": 0, "west": 1, "south": 2, "north": 3}
UPSIDE_DOWN = 4


def test_cube() -> BlockGrid:
    """5x5x5 stone cube with orientation markers: front (z=0, north) white wool, west (x=0) red wool,
    top-front-east corner gold. Facing south after //paste you see white with red on your RIGHT and gold at
    the top LEFT."""
    g = BlockGrid.empty(5, 5, 5)
    g.fill((0, 0, 0), (4, 4, 4), "minecraft:stone")
    g.fill((0, 0, 0), (4, 4, 0), "minecraft:wool")
    g.fill((0, 0, 0), (0, 4, 4), "minecraft:wool@14")
    g.set(4, 4, 0, "minecraft:gold_block")
    return g


def test_house() -> BlockGrid:
    """20x12x8 (W x H x L) hollow brick house: two storeys, front door at the center of z=0, pane windows,
    gable roof of oak stairs with the ridge along X."""
    w, h, length = 20, 12, 8
    wall_top = 7
    g = BlockGrid.empty(w, h, length)
    g.fill((0, 0, 0), (w - 1, 0, length - 1), "minecraft:stonebrick")  # ground floor
    g.fill((0, 1, 0), (w - 1, wall_top, length - 1), "minecraft:brick_block")
    g.fill((1, 1, 1), (w - 2, wall_top, length - 2), "minecraft:air")  # hollow
    g.fill((1, 4, 1), (w - 2, 4, length - 2), "minecraft:planks")  # upper floor (oak)
    door = w // 2
    g.set(door, 1, 0, "minecraft:wooden_door@3")  # lower half, facing north
    g.set(door, 2, 0, "minecraft:wooden_door@8")  # upper half, hinge left
    for x0 in (3, 7, 12, 16):
        for y0 in (2, 5):
            for z in (0, length - 1):
                g.fill((x0, y0, z), (x0 + 1, y0 + 1, z), "minecraft:glass_pane")
    for k in range(length // 2):
        y = wall_top + 1 + k
        g.fill((0, y, k), (w - 1, y, k), f"minecraft:oak_stairs@{ASCEND['south']}")  # north slope
        g.fill((0, y, length - 1 - k), (w - 1, y, length - 1 - k), f"minecraft:oak_stairs@{ASCEND['north']}")
        if k:  # gable ends filled under the slopes
            for x in (0, w - 1):
                g.fill((x, y - 1, k), (x, y - 1, length - 1 - k), "minecraft:brick_block")
    return g


def test_modded(full: str, stairs: str) -> BlockGrid:
    """7x5x7: stone-brick base; a ring of vanilla stone-brick stairs at y=1, a ring of the modded stairs at
    y=2 (north row upside-down), stone-brick corners, and a modded full-block pillar in the middle."""
    g = BlockGrid.empty(7, 5, 7)
    g.fill((0, 0, 0), (6, 0, 6), "minecraft:stonebrick")

    def ring(y: int, block: str, north_extra: int = 0) -> None:
        # Stairs on each edge ascend toward the center; corners are full blocks.
        for i in range(1, 6):
            g.set(i, y, 0, f"{block}@{ASCEND['south'] + north_extra}")  # north edge
            g.set(i, y, 6, f"{block}@{ASCEND['north']}")  # south edge
            g.set(0, y, i, f"{block}@{ASCEND['east']}")  # west edge
            g.set(6, y, i, f"{block}@{ASCEND['west']}")  # east edge
        for x, z in ((0, 0), (0, 6), (6, 0), (6, 6)):
            g.set(x, y, z, "minecraft:stonebrick")

    ring(1, "minecraft:stone_brick_stairs")
    ring(2, stairs, north_extra=UPSIDE_DOWN)
    g.fill((3, 1, 3), (3, 4, 3), full)
    return g


def main(
    out: Path = typer.Option(Path("out/testgrids"), "--out"),
    modded_full: str | None = typer.Option(None, help="A modded full block, modid:name[@meta]."),
    modded_stairs: str | None = typer.Option(None, help="A modded stairs block, modid:name."),
    copy: bool = typer.Option(True, "--copy/--no-copy", help="Copy into the instance's WorldEdit folder."),
) -> None:
    settings = load_settings()
    instance = _active_instance(None) if settings.instance else None
    palette = _active_palette() if instance else None
    grids = {"img2schem_cube": test_cube(), "img2schem_house": test_house()}
    if modded_full and modded_stairs:
        grids["img2schem_modded"] = test_modded(modded_full, modded_stairs)
    elif modded_full or modded_stairs:
        raise typer.BadParameter("give both --modded-full and --modded-stairs")

    for name, grid in grids.items():
        d = out / name
        issues = validate_grid(grid, settings.budgets, palette)
        for i in issues:
            typer.echo(f"  {name}: {i.severity} {i.rule}: {i.message}")
        if failed(issues):
            typer.echo(f"{name}: validation failed; not exported")
            continue
        meta = SchemMeta(
            name=name,
            instance_name=instance.name if instance else None,
            mc_version=instance.mc_version if instance else None,
            loader=instance.loader if instance else None,
        )
        schem = write_schematic(d / f"{name}.schematic", grid, meta=meta)
        grid.save(d)
        write_previews(grid, d)
        typer.echo(f"{schem}  ({grid.shape[0]}x{grid.shape[1]}x{grid.shape[2]})")
        if copy and instance and instance.worldedit and instance.schematics_dir and settings.export.write_to_instance:
            target = copy_to_schematics_dir(schem, Path(instance.schematics_dir))
            typer.echo(f"  copied -> {target}   in game: //schem load {target.stem}   then //paste -a")
    if palette is None:
        typer.echo("note: no world selected, so block names were not checked (`img2schem world use NAME`)")


if __name__ == "__main__":
    typer.run(main)
