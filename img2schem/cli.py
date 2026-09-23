"""`img2schem` command line (SOW §5.2). Phase 0 commands: instance, palette build, inspect, preview,
validate, doctor."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from img2schem.config import load_settings, save_user_setting, user_config_path
from img2schem.instance.discover import discover_all, resolve_instance
from img2schem.models import InstanceInfo, Palette
from img2schem.stages.export_schem import mods_required, read_schem

EXIT_VALIDATION = 2
EXIT_BAD_INPUT = 4

app = typer.Typer(no_args_is_help=True, add_completion=False)
instance_app = typer.Typer(no_args_is_help=True, help="Discover and select Minecraft instances.")
palette_app = typer.Typer(no_args_is_help=True, help="Extract the block palette from an instance.")
app.add_typer(instance_app, name="instance")
app.add_typer(palette_app, name="palette")
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


def _active_palette(ref: str | None) -> Palette | None:
    """The active instance's palette (cache hit after the first build), or None if no instance is set."""
    from img2schem.palette.build import build_palette

    if not (ref or load_settings().instance):
        return None
    palette, _, _ = build_palette(_active_instance(ref), load_settings().cache_path)
    return palette


# ---------------------------------------------------------------- instance


@instance_app.command("list")
def instance_list(as_json: bool = JsonOpt) -> None:
    """Discovered instances: name, launcher, MC version, loader, DataVersion, mod count."""
    found = discover_all()
    if as_json:
        print(json.dumps([i.model_dump() for i in found], indent=1))
        return
    if not found:
        console.print("No instances found. Use `img2schem instance use PATH` with your instance folder.")
        return
    t = Table("launcher:name", "MC", "loader", "DataVersion", "mods", "WorldEdit", "warnings")
    for i in found:
        dv = f"{i.data_version} ({i.data_version_source})" if i.data_version else "?"
        loader = f"{i.loader} {i.loader_version or ''}".strip()
        t.add_row(
            f"{i.launcher}:{i.name}",
            i.mc_version or "?",
            loader,
            dv,
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


# ---------------------------------------------------------------- palette


@palette_app.command("build")
def palette_build(
    instance: str | None = typer.Option(None, "--instance", help="Name or path; default: active instance."),
    force: bool = typer.Option(False, "--force"),
    as_json: bool = JsonOpt,
) -> None:
    """Extract blocks, properties and shapes from the instance (Phase 0 subset of RP.1–RP.17)."""
    from img2schem.palette.build import build_palette

    info = _active_instance(instance)
    if not info.client_jar:
        raise _fail(f"vanilla client jar for {info.mc_version} not found; launch that version once (RI.3)")
    palette, d, hit = build_palette(info, load_settings().cache_path, force=force)
    report = json.loads((d / "palette_report.json").read_text(encoding="utf-8"))
    if as_json:
        print(json.dumps({"dir": str(d), "cache_hit": hit, "blocks": len(palette.blocks), **report}, indent=1))
        return
    console.print(f"{'Cache hit' if hit else 'Built'}: {len(palette.blocks)} blocks -> {d}")
    t = Table("mod", "blocks")
    for mod, n in report["blocks_per_mod"].items():
        t.add_row(mod, str(n))
    console.print(t)
    console.print("shapes: " + ", ".join(f"{k}={v}" for k, v in report["blocks_per_shape"].items()))
    console.print(f"code_rendered: {len(report['code_rendered'])}   parse errors: {len(report['parse_errors'])}")


# ---------------------------------------------------------------- files


def _load_schem(path: Path):  # type: ignore[no-untyped-def]
    try:
        return read_schem(path)
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise _fail(f"cannot read {path}: {e}", EXIT_VALIDATION) from None


@app.command()
def inspect(file: Path, as_json: bool = JsonOpt) -> None:
    """Dims, palette, counts, DataVersion and mods required of a .schem."""
    grid, info = _load_schem(file)
    counts = grid.counts()
    summary = {
        "file": str(file),
        "sponge_version": info.version,
        "data_version": info.data_version,
        "dims_wxhxl": list(grid.shape),
        "offset": list(info.offset),
        "we_offset": list(info.we_offset) if info.we_offset else None,
        "nonair": grid.nonair(),
        "palette_size": len(grid.palette),
        "mods_required": mods_required(grid.palette),
        "block_entities": info.block_entities,
        "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "metadata": info.metadata,
    }
    if as_json:
        print(json.dumps(summary, indent=1, default=str))
        return
    w, h, length = grid.shape
    console.print(f"[bold]{file.name}[/bold]  Sponge v{info.version}  DataVersion {info.data_version}")
    console.print(f"size W×H×L = {w}×{h}×{length}  offset {info.offset}  WEOffset {info.we_offset}")
    console.print(f"non-air {grid.nonair()}  palette {len(grid.palette)}  block entities {info.block_entities}")
    console.print(f"mods required: {', '.join(summary['mods_required']) or 'none (vanilla)'}")
    t = Table("block state", "count")
    for state, n in summary["counts"].items():  # type: ignore[union-attr]
        t.add_row(state, str(n))
    console.print(t)


@app.command()
def preview(
    file: Path,
    out: Path = typer.Option(None, "--out", help="Output directory (default: next to the file)."),
    px: int = typer.Option(8, "--px", help="Pixels per block (>= 8)."),
) -> None:
    """Render front/side/top/iso preview PNGs from a .schem."""
    from img2schem.stages.preview import write_previews

    grid, _ = _load_schem(file)
    for p in write_previews(grid, out or file.parent, px=max(px, 8)):
        console.print(str(p))


@app.command()
def validate(
    file: Path,
    strict: bool = typer.Option(False, "--strict", help="Warnings fail too."),
    instance: str | None = typer.Option(None, "--instance"),
    allow_large: bool = typer.Option(False, "--allow-large"),
    as_json: bool = JsonOpt,
) -> None:
    """Structural checks (R10.1, R10.1b, R10.2). Exit 2 on failure."""
    from img2schem.stages.validate import failed, validate_grid

    grid, _ = _load_schem(file)
    palette = _active_palette(instance)
    issues = validate_grid(grid, load_settings().budgets, palette, allow_large=allow_large)
    if palette is None:
        err.print("[yellow]warning:[/yellow] no active instance; skipping palette checks (R10.1b)")
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
    """Check API key, active instance, client jar, WorldEdit and its schematics folder."""
    s = load_settings()
    ok = True

    def line(good: bool, msg: str) -> None:
        nonlocal ok
        ok &= good
        console.print(("[green]✓[/green] " if good else "[red]✗[/red] ") + msg)

    console.print(f"config: {user_config_path()}")
    line(
        bool(os.environ.get("ANTHROPIC_API_KEY")),
        "ANTHROPIC_API_KEY set"
        if os.environ.get("ANTHROPIC_API_KEY")
        else "ANTHROPIC_API_KEY not set (needed from Phase 2; template builds work without it)",
    )
    if not s.instance:
        line(False, "no active instance (`img2schem instance use NAME`)")
        raise typer.Exit(0)
    try:
        i = resolve_instance(s.instance)
    except LookupError as e:
        line(False, str(e))
        raise typer.Exit(0) from None
    line(
        True,
        f"instance {i.launcher}:{i.name}: MC {i.mc_version}, {i.loader} {i.loader_version or ''}, {len(i.mods)} mods",
    )
    line(i.client_jar is not None, f"client jar: {i.client_jar or 'not found (launch the version once)'}")
    line(i.data_version is not None, f"DataVersion: {i.data_version} ({i.data_version_source})")
    line(i.worldedit, "WorldEdit mod installed" if i.worldedit else "WorldEdit mod not found in mods/")
    sd = Path(i.schematics_dir) if i.schematics_dir else None
    line(bool(sd and sd.is_dir()), f"schematics folder: {sd}" + ("" if sd and sd.is_dir() else " (missing)"))
    for w in i.warnings:
        console.print(f"[yellow]warning:[/yellow] {w}")


if __name__ == "__main__":
    app()
