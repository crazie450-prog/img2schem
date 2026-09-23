"""`img2schem` command line (SOW §5.2, re-scoped for GTNH / 1.7.10 in docs/SOW_GTNH.md).
Phase 0 commands: instance, world, inspect, preview, validate, doctor."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from img2schem.config import load_settings, save_user_setting, user_config_path
from img2schem.instance.discover import discover_all, resolve_instance
from img2schem.instance.world import list_worlds, read_world_palette, resolve_world
from img2schem.models import BlockGrid, InstanceInfo, WorldPalette
from img2schem.stages.export_schem import SchemInfo, mods_required, read_schematic
from img2schem.util.block import namespace

EXIT_VALIDATION = 2
EXIT_BAD_INPUT = 4

app = typer.Typer(no_args_is_help=True, add_completion=False)
instance_app = typer.Typer(no_args_is_help=True, help="Discover and select Minecraft instances.")
world_app = typer.Typer(no_args_is_help=True, help="Select the world whose block registry validates builds.")
app.add_typer(instance_app, name="instance")
app.add_typer(world_app, name="world")
console = Console()
err = Console(stderr=True)

JsonOpt = typer.Option(False, "--json", help="Machine-readable summary on stdout.")


def _fail(msg: str, code: int = EXIT_BAD_INPUT) -> typer.Exit:
    err.print(f"[red]error:[/red] {msg}")
    return typer.Exit(code)


def _active_instance(ref: str | None) -> InstanceInfo:
    ref = ref or load_settings().instance
    if not ref:
        raise _fail("no instance selected; run `img2schem instance list` then `img2schem instance use NAME`")
    try:
        return resolve_instance(ref)
    except LookupError as e:
        raise _fail(str(e)) from None


def _active_palette(world: str | None = None) -> WorldPalette | None:
    """Block registry of the selected world, or None if no world is selected."""
    s = load_settings()
    ref = world or s.world
    if not ref:
        return None
    try:
        return read_world_palette(resolve_world(Path(_active_instance(None).game_dir), ref))
    except (LookupError, ValueError, OSError) as e:
        raise _fail(str(e)) from None


# ---------------------------------------------------------------- instance


@instance_app.command("list")
def instance_list(as_json: bool = JsonOpt) -> None:
    """Discovered instances: name, launcher, MC version, loader, mod count, WorldEdit."""
    found = discover_all()
    if as_json:
        print(json.dumps([i.model_dump() for i in found], indent=1))
        return
    if not found:
        console.print("No instances found. Use `img2schem instance use PATH` with your instance folder.")
        return
    t = Table("launcher:name", "MC", "loader", "mods", "WorldEdit", "warnings")
    for i in found:
        loader = f"{i.loader} {i.loader_version or ''}".strip()
        t.add_row(
            f"{i.launcher}:{i.name}",
            i.mc_version or "?",
            loader,
            str(len(i.mods)),
            "yes" if i.worldedit else "no",
            "; ".join(i.warnings),
        )
    console.print(t)


@instance_app.command("use")
def instance_use(ref: str = typer.Argument(..., help="Instance name, launcher:name, or path.")) -> None:
    """Set the active instance in the user config."""
    try:
        info = resolve_instance(ref)
    except LookupError as e:
        raise _fail(str(e)) from None
    value = ref if not Path(ref).exists() else str(Path(ref).resolve())
    path = save_user_setting("instance", value)
    console.print(
        f"Active instance: [bold]{info.launcher}:{info.name}[/bold] "
        f"(MC {info.mc_version}, {info.loader}, {len(info.mods)} mods) -> {path}"
    )
    for w in info.warnings:
        console.print(f"[yellow]warning:[/yellow] {w}")


# ---------------------------------------------------------------- world


@world_app.command("list")
def world_list() -> None:
    """Worlds (saves) of the active instance."""
    inst = _active_instance(None)
    worlds = list_worlds(Path(inst.game_dir))
    if not worlds:
        console.print(f"No worlds in {Path(inst.game_dir) / 'saves'}. Create one in game first.")
    for w in worlds:
        console.print(w.name)


@world_app.command("use")
def world_use(ref: str = typer.Argument(..., help="Save folder name, or a path to a world folder.")) -> None:
    """Select the world whose block registry (level.dat) validates builds; prints blocks per mod."""
    inst = _active_instance(None)
    try:
        world_dir = resolve_world(Path(inst.game_dir), ref)
        pal = read_world_palette(world_dir)
    except (LookupError, ValueError, OSError) as e:
        raise _fail(str(e)) from None
    save_user_setting("world", str(world_dir.resolve()))
    console.print(f"Active world: [bold]{world_dir.name}[/bold]: {len(pal.blocks)} registered blocks")
    t = Table("mod", "blocks")
    for mod, n in sorted(Counter(namespace(b) for b in pal.blocks).items(), key=lambda kv: -kv[1]):
        t.add_row(mod, str(n))
    console.print(t)


# ---------------------------------------------------------------- files


def _load(path: Path) -> tuple[BlockGrid, SchemInfo]:
    try:
        return read_schematic(path)
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise _fail(f"cannot read {path}: {e}", EXIT_VALIDATION) from None


@app.command()
def inspect(file: Path, as_json: bool = JsonOpt) -> None:
    """Dims, blocks, counts and mods required of a .schematic."""
    grid, info = _load(file)
    summary = {
        "file": str(file),
        "dims_wxhxl": list(grid.shape),
        "we_offset": list(info.offset) if info.offset else None,
        "we_origin": list(info.origin) if info.origin else None,
        "names_mapped": info.mapped,
        "nonair": grid.nonair(),
        "palette_size": len(grid.palette),
        "mods_required": mods_required(grid.palette),
        "tile_entities": info.tile_entities,
        "entities": info.entities,
        "counts": dict(sorted(grid.counts().items(), key=lambda kv: -kv[1])),
        "img2schem": info.img2schem,
    }
    if as_json:
        print(json.dumps(summary, indent=1, default=str))
        return
    w, h, length = grid.shape
    console.print(f"[bold]{file.name}[/bold]  W×H×L = {w}×{h}×{length}  WEOffset {info.offset}  WEOrigin {info.origin}")
    console.print(
        f"non-air {grid.nonair()}  distinct blocks {len(grid.palette) - 1}  "
        f"tile entities {info.tile_entities}  entities {info.entities}"
    )
    if not info.mapped:
        console.print("[yellow]no SchematicaMapping: blocks shown as numeric ids (id:<n>)[/yellow]")
    console.print(f"mods required: {', '.join(summary['mods_required']) or 'none (vanilla)'}")  # type: ignore[arg-type]
    t = Table("block (name@meta)", "count")
    for block, n in summary["counts"].items():  # type: ignore[union-attr]
        t.add_row(block, str(n))
    console.print(t)


@app.command()
def preview(
    file: Path,
    out: Path = typer.Option(None, "--out", help="Output directory (default: next to the file)."),
    px: int = typer.Option(8, "--px", help="Pixels per block (>= 8)."),
) -> None:
    """Render front/side/top/iso preview PNGs from a .schematic."""
    from img2schem.stages.preview import write_previews

    grid, _ = _load(file)
    for p in write_previews(grid, out or file.parent, px=max(px, 8)):
        console.print(str(p))


@app.command()
def validate(
    file: Path,
    strict: bool = typer.Option(False, "--strict", help="Warnings fail too."),
    world: str | None = typer.Option(None, "--world", help="Save name or path; default: active world."),
    allow_large: bool = typer.Option(False, "--allow-large"),
    as_json: bool = JsonOpt,
) -> None:
    """Structural checks (R10.1, R10.1b, R10.2). Exit 2 on failure."""
    from img2schem.stages.validate import failed, validate_grid

    grid, _ = _load(file)
    palette = _active_palette(world)
    issues = validate_grid(grid, load_settings().budgets, palette, allow_large=allow_large)
    if palette is None:
        err.print("[yellow]warning:[/yellow] no world selected; skipping block-name checks (R10.1b)")
    ok = not failed(issues, strict)
    if as_json:
        print(json.dumps({"ok": ok, "issues": [i.model_dump() for i in issues]}, indent=1))
    else:
        for i in issues:
            color = {"error": "red", "warning": "yellow", "info": "cyan"}[i.severity]
            console.print(f"[{color}]{i.severity}[/{color}] {i.rule}: {i.message}")
        console.print("[green]OK[/green]" if ok else "[red]FAILED[/red]")
    if not ok:
        raise typer.Exit(EXIT_VALIDATION)


@app.command()
def doctor() -> None:
    """Check the active instance, WorldEdit, its schematics folder and the selected world."""
    s = load_settings()

    def line(good: bool, msg: str) -> None:
        console.print(("[green]✓[/green] " if good else "[red]✗[/red] ") + msg)

    console.print(f"config: {user_config_path()}")
    key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    line(key, "ANTHROPIC_API_KEY set" if key else "ANTHROPIC_API_KEY not set (needed from Phase 2)")
    if not s.instance:
        line(False, "no active instance (`img2schem instance use NAME`)")
        return
    try:
        i = resolve_instance(s.instance)
    except LookupError as e:
        line(False, str(e))
        return
    line(
        True,
        f"instance {i.launcher}:{i.name}: MC {i.mc_version}, {i.loader} {i.loader_version or ''}, {len(i.mods)} mods",
    )
    line(i.mc_version == "1.7.10", f"Minecraft {i.mc_version} (img2schem targets 1.7.10 / GTNH)")
    line(i.worldedit, "WorldEdit mod installed" if i.worldedit else "WorldEdit mod not found in mods/")
    sd = Path(i.schematics_dir) if i.schematics_dir else None
    ok_sd = bool(sd and sd.is_dir())
    line(ok_sd, f"schematics folder: {sd}" + ("" if ok_sd else " (missing; created on first export)"))
    if s.world:
        try:
            pal = read_world_palette(resolve_world(Path(i.game_dir), s.world))
            line(True, f"world {pal.world}: {len(pal.blocks)} registered blocks")
        except (LookupError, ValueError, OSError) as e:
            line(False, f"world: {e}")
    else:
        line(False, "no world selected (`img2schem world list`, then `img2schem world use NAME`)")
    for w in i.warnings:
        console.print(f"[yellow]warning:[/yellow] {w}")


if __name__ == "__main__":
    app()
