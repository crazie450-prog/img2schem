"""Phase 0 hand-made test grids (SOW §7 Phase 0 task 6) for the paste checks in docs/TEST_BED.md.

    python examples/make_test_grids.py                          # vanilla grids, active instance's DataVersion
    python examples/make_test_grids.py --modded-full fabdeco:slate_shingles \
        --modded-stairs fabdeco:slate_shingle_stairs            # adds the 7x5x7 modded grid

Writes out/testgrids/<name>/<name>.schem + preview PNGs, validates against the active instance's palette
(if one is selected), and copies each .schem into the instance's WorldEdit schematics folder when WorldEdit
is installed. Vanilla block IDs below are test-bed fixtures, not build output.
"""

from __future__ import annotations

from pathlib import Path

import typer

from img2schem.cli import _active_instance, _active_palette
from img2schem.config import load_settings
from img2schem.models import BlockGrid
from img2schem.stages.export_schem import SchemMeta, copy_to_schematics_dir, write_schem
from img2schem.stages.preview import write_previews
from img2schem.stages.validate import failed, validate_grid

FALLBACK_DATA_VERSION = 4189  # 1.21.4, the SOW §1.5 vanilla fallback


def test_cube() -> BlockGrid:
    """5x5x5 stone cube with orientation markers: front (z=0, north) white, west (x=0) red, top-front-east
    corner gold. Facing south after //paste you should see the white face with the red face on your RIGHT."""
    g = BlockGrid.empty(5, 5, 5)
    g.fill((0, 0, 0), (4, 4, 4), "minecraft:stone")
    g.fill((0, 0, 0), (4, 4, 0), "minecraft:white_concrete")
    g.fill((0, 0, 0), (0, 4, 4), "minecraft:red_concrete")
    g.set(4, 4, 0, "minecraft:gold_block")
    return g


def test_house() -> BlockGrid:
    """20x12x8 (W x H x L) hollow brick house: two storeys, front door at the center of z=0, pane windows,
    gable roof of oak stairs with the ridge along X."""
    w, h, length = 20, 12, 8
    wall_top = 7
    g = BlockGrid.empty(w, h, length)
    g.fill((0, 0, 0), (w - 1, 0, length - 1), "minecraft:stone_bricks")  # ground floor
    g.fill((0, 1, 0), (w - 1, wall_top, length - 1), "minecraft:bricks")
    g.fill((1, 1, 1), (w - 2, wall_top, length - 2), "minecraft:air")  # hollow
    g.fill((1, 4, 1), (w - 2, 4, length - 2), "minecraft:oak_planks")  # upper floor
    # Front door (two halves), facing out of the building (north).
    door = w // 2
    g.set(door, 1, 0, "minecraft:oak_door[facing=north,half=lower,hinge=left,open=false]")
    g.set(door, 2, 0, "minecraft:oak_door[facing=north,half=upper,hinge=left,open=false]")
    # 2-wide windows on both storeys, front and back; panes connect east-west.
    pane = "minecraft:glass_pane[east=true,north=false,south=false,west=true]"
    for x0 in (3, 7, 12, 16):
        for y0 in (2, 5):
            for z in (0, length - 1):
                g.fill((x0, y0, z), (x0 + 1, y0 + 1, z), pane)
    # Gable roof: north slope stairs ascend southward (facing=south), south slope ascend northward.
    for k in range(length // 2):
        y = wall_top + 1 + k
        g.fill((0, y, k), (w - 1, y, k), "minecraft:oak_stairs[facing=south,half=bottom,shape=straight]")
        g.fill(
            (0, y, length - 1 - k),
            (w - 1, y, length - 1 - k),
            "minecraft:oak_stairs[facing=north,half=bottom,shape=straight]",
        )
        if k:  # gable ends filled under the slopes
            for x in (0, w - 1):
                g.fill((x, y - 1, k), (x, y - 1, length - 1 - k), "minecraft:bricks")
    return g


def test_modded(full: str, stairs: str) -> BlockGrid:
    """7x5x7: stone-brick base; a ring of vanilla stairs (explicit states) at y=1, a ring of the modded
    stairs at y=2 (one row upside-down), full-block corners, and a modded full-block pillar in the middle."""
    g = BlockGrid.empty(7, 5, 7)
    g.fill((0, 0, 0), (6, 0, 6), "minecraft:stone_bricks")

    def ring(y: int, block: str, top_row_half: str = "bottom") -> None:
        # Stairs on each edge ascend toward the center; corners are full blocks.
        for i in range(1, 6):
            g.set(i, y, 0, f"{block}[facing=south,half={top_row_half},shape=straight]")  # north edge
            g.set(i, y, 6, f"{block}[facing=north,half=bottom,shape=straight]")  # south edge
            g.set(0, y, i, f"{block}[facing=east,half=bottom,shape=straight]")  # west edge
            g.set(6, y, i, f"{block}[facing=west,half=bottom,shape=straight]")  # east edge
        for x, z in ((0, 0), (0, 6), (6, 0), (6, 6)):
            g.set(x, y, z, "minecraft:stone_bricks")

    ring(1, "minecraft:stone_brick_stairs")
    ring(2, stairs, top_row_half="top")
    g.fill((3, 1, 3), (3, 4, 3), full)
    return g


def main(
    out: Path = typer.Option(Path("out/testgrids"), "--out"),
    modded_full: str | None = typer.Option(None, help="A modded full block id from your palette."),
    modded_stairs: str | None = typer.Option(None, help="A modded stairs block id from your palette."),
    schem_version: int = typer.Option(2, "--schem-version"),
    copy: bool = typer.Option(True, "--copy/--no-copy", help="Copy into the instance's WorldEdit folder."),
) -> None:
    settings = load_settings()
    instance = _active_instance(None) if settings.instance else None
    palette = _active_palette(None) if instance else None
    data_version = (instance.data_version if instance else None) or FALLBACK_DATA_VERSION
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
        schem = write_schem(d / f"{name}.schem", grid, data_version, schem_version=schem_version, meta=meta)
        grid.save(d)
        write_previews(grid, d)
        typer.echo(f"{schem}  ({grid.shape[0]}x{grid.shape[1]}x{grid.shape[2]}, DataVersion {data_version})")
        if copy and instance and instance.worldedit and instance.schematics_dir and settings.export.write_to_instance:
            target = copy_to_schematics_dir(schem, Path(instance.schematics_dir))
            typer.echo(f"  copied -> {target}   in game: //schem load {target.stem}   then //paste -a")
    if palette is None:
        typer.echo("note: no active instance, so block states were not checked against a palette")


if __name__ == "__main__":
    typer.run(main)
