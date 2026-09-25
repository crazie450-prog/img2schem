"""`img2schem` command line (SOW §5.2, re-scoped for GTNH / 1.7.10 in docs/SOW_GTNH.md).
Commands: instance, world, palette, inspect, preview, validate, doctor."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from img2schem.config import load_settings, save_user_setting, user_config_path
from img2schem.instance.discover import discover_all, resolve_instance
from img2schem.instance.world import list_worlds, read_world_palette, resolve_world
from img2schem.models import BlockGrid, InstanceInfo, Palette, WorldPalette
from img2schem.stages.export_schem import SchemInfo, mods_required, read_schematic
from img2schem.util.block import namespace

if TYPE_CHECKING:  # the designer (and the Anthropic SDK) load only when a command needs them
    from img2schem.designer.runner import Callbacks, RunResult

EXIT_VALIDATION = 2
EXIT_BAD_INPUT = 4
EXIT_BUDGET = 5  # SOW §5.2: the API budget stopped a Claude stage

app = typer.Typer(no_args_is_help=True, add_completion=False)
instance_app = typer.Typer(no_args_is_help=True, help="Discover and select Minecraft instances.")
world_app = typer.Typer(no_args_is_help=True, help="Select the world whose block registry validates builds.")
app.add_typer(instance_app, name="instance")
palette_app = typer.Typer(no_args_is_help=True, help="Block colors and shapes, imported from NEI data dumps.")
app.add_typer(world_app, name="world")
app.add_typer(palette_app, name="palette")
console = Console()


@app.callback()
def _startup() -> None:
    """Photo or description -> WorldEdit .schematic for GT New Horizons (Minecraft 1.7.10)."""
    from img2schem.util.env import load_dotenv

    for folder in (Path.cwd(), user_config_path().parent):  # secrets only via env vars / .env (never committed)
        load_dotenv(folder / ".env")
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


# ---------------------------------------------------------------- palette


def _load_palette(required: bool = False) -> Palette | None:
    path = load_settings().palette
    if path and Path(path).is_file():
        return Palette.model_validate_json(Path(path).read_text(encoding="utf-8"))
    if required:
        raise _fail("no palette imported; run `img2schem palette import <.minecraft/dumps folder>`")
    return None


@palette_app.command("import")
def palette_import(
    dumps: Path = typer.Argument(..., help="NEI dumps folder: block.csv, itempanel.csv, itempanel_icons/."),
) -> None:
    """Build the palette (shapes, variants, colors) from NEI data dumps and make it active."""
    from img2schem.palette.nei import dumps_key, import_nei

    try:
        out = load_settings().cache_path / "palettes" / dumps_key(dumps) / "palette.json"
        if not out.is_file():
            pal = import_nei(dumps)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(pal.model_dump_json(), encoding="utf-8")
    except (OSError, KeyError, ValueError) as e:
        raise _fail(f"cannot import {dumps}: {e}") from None
    save_user_setting("palette", str(out))
    console.print(f"Palette -> {out}")
    palette_report()


@palette_app.command("report")
def palette_report() -> None:
    """Blocks per shape, color coverage, what is usable for building, and the top mods."""
    pal = _load_palette(required=True)
    assert pal is not None
    variants = [v for b in pal.blocks.values() for v in b.variants]
    colored = sum(v.rgb is not None for v in variants)
    dark = sum("dark_icon" in v.flags for v in variants)
    excluded = sum("excluded" in v.flags for v in variants)
    usable = [b for b in pal.blocks.values() if b.usable()]
    console.print(
        f"{len(pal.blocks)} blocks, {len(variants)} variants, {colored} with a color "
        f"({colored / max(len(variants), 1):.0%}); flagged: {dark} dark_icon, {excluded} excluded"
        f"  [source: {pal.source}]"
    )
    console.print(
        f"[bold]usable for building: {sum(len(b.usable()) for b in usable)} variants of {len(usable)} blocks[/bold] "
        "(known shape, has a color, not flagged)"
    )
    console.print(
        "shapes: " + ", ".join(f"{k}={v}" for k, v in Counter(b.shape for b in pal.blocks.values()).most_common())
    )
    t = Table("mod", "blocks", "variants", "colored", "known shape", "usable variants")
    per: dict[str, list[int]] = {}
    for b in pal.blocks.values():
        row = per.setdefault(b.mod, [0, 0, 0, 0, 0])
        row[0] += 1
        row[1] += len(b.variants)
        row[2] += sum(v.rgb is not None for v in b.variants)
        row[3] += b.shape != "unknown"
        row[4] += len(b.usable())
    for mod, (nb, nv, nc, ns, nu) in sorted(per.items(), key=lambda kv: -kv[1][4])[:25]:
        t.add_row(mod, str(nb), str(nv), str(nc), str(ns), str(nu))
    console.print(t)


@palette_app.command("search")
def palette_search(
    text: str = typer.Argument(..., help="Words matched against block names and display names."),
    shape: str | None = typer.Option(None, "--shape"),
    mod: str | None = typer.Option(None, "--mod"),
    n: int = typer.Option(30, "--n"),
) -> None:
    """Find variants by name, e.g. `palette search "stone brick" --shape stairs`."""
    pal = _load_palette(required=True)
    assert pal is not None
    words = text.lower().split()
    t = Table("block (name@meta)", "display name", "shape", "color", "flags")
    hits = 0
    for b in pal.blocks.values():
        if (shape and b.shape != shape) or (mod and b.mod.lower() != mod.lower()):
            continue
        for v in b.variants:
            hay = f"{v.block} {v.display}".lower()
            if all(w in hay for w in words):
                color = f"[on {v.hex}]    [/] {v.hex}" if v.hex else "-"
                t.add_row(v.block, v.display, b.shape, color, ", ".join(v.flags))
                hits += 1
                if hits >= n:
                    break
        if hits >= n:
            break
    console.print(t if hits else "no matches")


@palette_app.command("family")
def palette_family(block: str = typer.Argument(..., help="A usable full block, e.g. minecraft:stonebrick.")) -> None:
    """The stairs, slab, wall, fence and gate that match a full block."""
    from img2schem.palette.query import PaletteIndex

    pal = _load_palette(required=True)
    assert pal is not None
    idx = PaletteIndex(pal)
    try:
        hit = idx.usable(block)
    except ValueError as e:
        raise _fail(str(e)) from None
    if hit is None:
        raise _fail(f"{block} is not a usable block (see `img2schem palette search`)")
    console.print(f"{hit[1].block}  {hit[1].display}  ({hit[0].shape}, {hit[1].hex})")
    for shape, member in idx.family(block).items():
        m = idx.usable(member) if member else None
        console.print(f"  {shape:10} {member or '-'}" + (f"  {m[1].display}  {m[1].hex}" if m else ""))


@palette_app.command("review")
def palette_review(
    blocks: list[str] = typer.Argument(..., help="Full blocks to check, e.g. chisel:marble minecraft:stonebrick."),
    out: Path = typer.Option(Path("out/palette_review.png"), help="Where to write the sheet."),
    scale: int = typer.Option(2, min=1, max=6, help="Size of the sheet (2 = 380 px per block)."),
) -> None:
    """A PNG sheet per block: its icon, measured color and family (stairs, slab, wall, fence, gate)."""
    from img2schem.palette.query import PaletteIndex
    from img2schem.palette.review import review_sheet

    pal = _load_palette(required=True)
    assert pal is not None
    idx = PaletteIndex(pal)
    for b in blocks:
        try:
            if idx.usable(b) is None:
                raise ValueError(f"{b} is not a usable block (find it with `img2schem palette search`)")
        except ValueError as e:
            raise _fail(str(e)) from None
    out.parent.mkdir(parents=True, exist_ok=True)
    review_sheet(idx, blocks, scale).save(out)
    console.print(f"wrote {out}")


# ---------------------------------------------------------------- files


def _load(path: Path) -> tuple[BlockGrid, SchemInfo]:
    try:
        return read_schematic(path)
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise _fail(f"cannot read {path}: {e}", EXIT_VALIDATION) from None


def _plan_file(spec_file: Path, pal: Palette | None, out: Path | None = None) -> Path:
    """Template-plan a spec.json into an ops.json (default: next to the spec); returns the ops path."""
    from pydantic import ValidationError

    from img2schem.models import BuildSpec
    from img2schem.palette.query import PaletteIndex
    from img2schem.stages.plan_template import PlanError, plan_template

    try:
        spec = BuildSpec.model_validate_json(spec_file.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise _fail(f"cannot read {spec_file}: {e}") from None
    try:
        doc, warnings = plan_template(spec, PaletteIndex(pal) if pal else None)
    except PlanError as e:
        raise _fail(str(e)) from None
    out = out or spec_file.with_name(spec_file.name.replace(".spec.json", "").removesuffix(".json") + ".ops.json")
    out.write_text(doc.model_dump_json(indent=1, by_alias=True), encoding="utf-8")
    for w in warnings:
        console.print(f"[yellow]warning:[/yellow] {w}")
    console.print(f"planned {spec_file} -> {out}  ({len(doc.ops)} ops)")
    return out


@app.command()
def plan(
    spec_file: Path = typer.Argument(..., metavar="SPEC.json"),
    designer: str = typer.Option("template", "--designer", help="template (no API). claude arrives in Phase 2."),
    out: Path | None = typer.Option(None, "--out", help="Output ops.json (default: next to the spec)."),
) -> None:
    """S3: spec.json -> ops.json (the build program), deterministic with --designer template."""

    if designer != "template":
        raise _fail(f"--designer {designer} is not available yet (Phase 2); use --designer template")
    out = _plan_file(spec_file, _load_palette(), out)
    console.print(f"next: img2schem compile {out}")


@app.command()
def materials(
    spec_file: Path = typer.Argument(..., metavar="SPEC.json"),
    photo: Path = typer.Argument(..., help="Photo of the building (JPEG/PNG/WEBP; HEIC with pillow-heif)."),
    corners: str | None = typer.Option(
        None, "--corners", help='Facade corners on the photo in pixels, e.g. "120,80 1500,95 1510,1100 110,1080".'
    ),
    roof_box: str | None = typer.Option(None, "--roof-box", help='A roof area on the photo: "x0,y0,x1,y1" pixels.'),
    replace: bool = typer.Option(False, "--replace", help="Also replace blocks you already chose in the spec."),
    run: Path | None = typer.Option(None, "--run", help="Working folder (default: out/<spec name>_photo)."),
) -> None:
    """Measure wall/window/door/roof colors on the photo and fill the spec's materials with matching blocks.

    Corners are counted on the original photo; with no --corners the whole photo is treated as the wall."""
    import numpy as np
    from PIL import Image, ImageDraw
    from pydantic import ValidationError

    from img2schem.models import BuildSpec
    from img2schem.palette.query import PaletteIndex
    from img2schem.stages.ingest import IngestError, ingest
    from img2schem.stages.materials import apply_materials, region_colors
    from img2schem.stages.rectify import parse_corners, rectify

    pal = _load_palette(required=True)
    assert pal is not None
    try:
        spec = BuildSpec.model_validate_json(spec_file.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise _fail(f"cannot read {spec_file}: {e}") from None
    run = run or Path("out") / f"{spec_file.name.split('.')[0]}_photo"
    try:
        image = ingest(photo, run)
        scale = json.loads((run / "image_meta.json").read_text())["resize_factor"]
        pts = [(x * scale, y * scale) for x, y in parse_corners(corners)] if corners else None
        rect = rectify(image, run, pts)
        roof_px = None
        if roof_box:
            x0, y0, x1, y1 = (round(float(v) * scale) for v in roof_box.split(","))
            roof_px = np.asarray(Image.open(image).convert("RGB"))[min(y0, y1) : max(y0, y1), min(x0, x1) : max(x0, x1)]
    except (IngestError, ValueError) as e:
        raise _fail(str(e)) from None
    if not pts:
        console.print("[yellow]warning:[/yellow] no --corners: using the whole photo as the wall (method none)")
    wall = np.asarray(Image.open(rect.image).convert("RGB"))
    regions = region_colors(wall, spec, roof_px)
    notes = apply_materials(spec, regions, PaletteIndex(pal), replace=replace)
    spec_file.write_text(spec.model_dump_json(indent=1), encoding="utf-8")

    debug = Image.open(rect.image).convert("RGB")
    draw = ImageDraw.Draw(debug)
    h, w = wall.shape[:2]
    for el in spec.elements:
        if el.face == "front":
            x0, y0, x1, y1 = el.bbox
            draw.rectangle([x0 * w, y0 * h, x1 * w, y1 * h], outline=(255, 0, 180), width=3)
            draw.text((x0 * w + 4, y0 * h + 4), el.kind, fill=(255, 0, 180))
    debug.save(run / "debug_layout.png")

    t = Table("role", "photo color", "chosen block", "next candidates")
    for role, m in spec.materials.items():
        if m.rgb:
            hexc = "#{:02x}{:02x}{:02x}".format(*m.rgb)
            t.add_row(role, f"[on {hexc}]    [/] {hexc}", m.chosen or "-", ", ".join(m.candidates[1:4]))
    console.print(t)
    for n in notes:
        console.print(f"[yellow]note:[/yellow] {n}")
    console.print(f"updated {spec_file}   check {run / 'debug_layout.png'}   next: img2schem compile {spec_file}")


@app.command("compile")
def compile_cmd(
    ops_file: Path = typer.Argument(..., metavar="OPS.json|SPEC.json"),
    out: Path | None = typer.Option(None, "--out", help="Output directory (default: out/<name>_<timestamp>)."),
    name: str | None = typer.Option(None, "--name", help="Schematic name (default: the file's stem)."),
    copy: bool = typer.Option(True, "--copy/--no-copy", help="Also copy into the instance's WorldEdit folder."),
) -> None:
    """Compile ops.json (S4) -> validate (S5) -> .schematic, previews, report.json (S7). No API calls.

    Given a spec.json, plans it first (like `img2schem plan`) and compiles the resulting ops.json."""
    import time

    from img2schem.engine.compiler import CompileError
    from img2schem.engine.ops import OpsDoc
    from img2schem.stages.build import BuildFailed, build_outputs

    s = load_settings()
    pal = _load_palette()
    try:
        raw = json.loads(ops_file.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "facade" in raw:  # a spec.json: plan it first (template designer)
            ops_file = _plan_file(ops_file, pal)
            raw = json.loads(ops_file.read_text(encoding="utf-8"))
        doc = OpsDoc.model_validate(raw)
    except (OSError, ValueError) as e:
        raise _fail(f"cannot read {ops_file}: {e}") from None
    name = name or ops_file.name.removesuffix(".json").removesuffix(".ops")
    out = out or Path("out") / f"{name}_{time.strftime('%Y%m%d-%H%M%S')}"
    inst = _active_instance(None) if s.instance else None
    try:
        built = build_outputs(doc, name, out, settings=s, palette=pal, world=_active_palette(), instance=inst,
                              copy=copy, ops_file=ops_file)  # fmt: skip
    except CompileError as e:
        raise _fail(str(e), EXIT_VALIDATION) from None
    except BuildFailed as e:
        for i in e.issues:
            console.print(f"{i.severity} {i.rule}: {i.message}")
        raise _fail(str(e), EXIT_VALIDATION) from None
    for i in built.issues:
        fix = " (fixed)" if i.autofix_applied else ""
        console.print(f"{i.severity} {i.rule}{fix}: {i.message}")
    w, h, length = built.report["dims_wxhxl"]
    console.print(f"{built.schematic}  ({w}x{h}x{length}, {built.report['nonair']} blocks)")
    if built.copied_to:
        console.print(f"copied -> {built.copied_to}   in game: //schem load {built.copied_to.stem}   then //paste -a")


def _callbacks() -> Callbacks:
    from img2schem.designer.runner import Callbacks

    def progress(kind: str, text: str) -> None:
        if kind == "tool":
            console.print(f"  [cyan]{text}[/cyan]")
        elif kind == "text":
            console.print(text, end="", style="dim", markup=False, highlight=False)

    return Callbacks(progress=progress, warning=lambda m: console.print(f"[yellow]warning:[/yellow] {m}"),
                     critique=lambda n: console.print(f"[bold]critique pass {n}[/bold]"))  # fmt: skip


def _report_run(run: RunResult, stage: str, name: str, out: Path, copy: bool) -> None:
    """Print a design/edit run, compile it like `compile`, add its API usage to report.json; exit 5 on a
    budget stop."""
    r = run.result
    console.print(f"\n{r.stopped} after {r.turns} turns, ${r.cost_usd:.2f}")
    if r.summary:
        console.print(r.summary)
    if not run.state.doc.ops:
        raise _fail("no ops were produced", EXIT_BUDGET if r.stopped == "budget" else 3)
    if run.version is None:
        console.print("no change was made")
        return
    console.print(f"build {name!r} version {run.version}   {'undo' if stage == 'edit' else 'refine'}: "
                  + (f"img2schem undo {name}" if stage == "edit" else f'img2schem edit {name} "..."'))  # fmt: skip
    compile_cmd(run.ops_path, out=out, name=name, copy=copy)
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    report["usage"] = {"design": {"cost_usd": round(r.cost_usd, 4), "turns": r.turns, "stopped": r.stopped,
                                  "per_turn": r.usage}}  # fmt: skip
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    if r.stopped == "budget":
        raise typer.Exit(EXIT_BUDGET)


def _run_dir(name: str, out: Path | None) -> Path:
    import time

    return out or Path("out") / f"{name}_{time.strftime('%Y%m%d-%H%M%S')}"


@app.command()
def design(
    prompt: str = typer.Argument("", help='What to build, e.g. "a stone watchtower"; with --photo, notes.'),
    photo: list[Path] = typer.Option([], "--photo", help="A photo of the building to recreate (repeatable)."),
    critique: int | None = typer.Option(None, "--critique", help="Critique passes against the photo (default 2)."),
    name: str = typer.Option("design", "--name", help="Build name: builds/<name>.ops.json, and the schematic."),
    out: Path | None = typer.Option(None, "--out", help="Run directory (default: out/<name>_<timestamp>)."),
    budget: str = typer.Option("default", "--budget", help="API budget: default ($1 warn / $5 stop) or large."),
    replay: Path | None = typer.Option(None, "--replay", help="Replay a recorded session.jsonl (no API calls)."),
    copy: bool = typer.Option(True, "--copy/--no-copy", help="Also copy into the instance's WorldEdit folder."),
) -> None:
    """Claude designs a build from a description or photos (S3), then it compiles like `compile`. Costs API
    credit. The build is kept as builds/<name>.ops.json with a version history: refine it with `edit`."""
    from img2schem.designer import runner
    from img2schem.designer.history import BUILDS
    from img2schem.stages.ingest import IngestError, ingest

    s = load_settings()
    run_dir = _run_dir(name, out)
    photos = []
    for i, p in enumerate(photo, start=1):
        try:
            photos.append(ingest(p, run_dir / f"photo_{i}"))
        except (IngestError, OSError) as e:
            raise _fail(str(e)) from None
    try:
        s.claude.budget(budget)
        if not prompt and not photo:
            raise runner.RunError("describe the build, or give --photo PATH")
        console.print(f"designing with {s.claude.model} (budget {budget})")
        run = runner.design(name, prompt, photos, settings=s, palette=_load_palette(), world=_active_palette(),
                            out=run_dir, builds=BUILDS, budget=budget, replay=replay, critique_passes=critique,
                            cb=_callbacks(), sources=[str(p) for p in photo])  # fmt: skip
    except (runner.RunError, ValueError) as e:
        raise _fail(str(e), 3 if isinstance(e, runner.RunError) and "stopped" in str(e) else EXIT_BAD_INPUT) from None
    _report_run(run, "design", name, run_dir, copy)


@app.command()
def edit(
    build: str = typer.Argument(..., help="Build name (builds/<name>.ops.json) or a path to an ops.json."),
    instruction: str = typer.Argument(..., help='The change, e.g. "make the roof steeper".'),
    out: Path | None = typer.Option(None, "--out", help="Run directory (default: out/<name>_<timestamp>)."),
    budget: str = typer.Option("default", "--budget", help="API budget: default ($1 warn / $5 stop) or large."),
    replay: Path | None = typer.Option(None, "--replay", help="Replay a recorded session.jsonl (no API calls)."),
    render: bool = typer.Option(False, "--render/--no-render", help="Let Claude look at renders (costs more)."),
    copy: bool = typer.Option(True, "--copy/--no-copy", help="Also copy into the instance's WorldEdit folder."),
) -> None:
    """Claude changes a build as instructed (RD.4); the result is a new version (`undo` goes back)."""
    from img2schem.designer import runner
    from img2schem.designer.history import resolve_build

    ops_file = resolve_build(build)
    if not ops_file.is_file():
        raise _fail(f"no build {build!r} ({ops_file} not found)")
    name = ops_file.name.removesuffix(".json").removesuffix(".ops")
    s = load_settings()
    run_dir = _run_dir(name, out)
    try:
        s.claude.budget(budget)
        console.print(f"editing with {s.claude.model} (budget {budget})")
        run = runner.edit(ops_file, instruction, settings=s, palette=_load_palette(), world=_active_palette(),
                          out=run_dir, budget=budget, replay=replay, render=render, cb=_callbacks())  # fmt: skip
    except (runner.RunError, ValueError) as e:
        raise _fail(str(e), 3 if isinstance(e, runner.RunError) and "stopped" in str(e) else EXIT_BAD_INPUT) from None
    _report_run(run, "edit", name, run_dir, copy)


def _step(build: str, delta: int, copy: bool) -> None:
    from img2schem.designer.history import History, resolve_build

    ops_file = resolve_build(build)
    hist = History(ops_file)
    try:
        entry = hist.step(delta)
    except ValueError as e:
        raise _fail(str(e)) from None
    name = ops_file.name.removesuffix(".json").removesuffix(".ops")
    console.print(f"build {name!r} is at version {entry['n']}: {entry.get('instruction', '')}")
    compile_cmd(ops_file, out=_run_dir(name, None), name=name, copy=copy)


@app.command()
def undo(build: str = typer.Argument(..., help="Build name or ops.json path."),
         copy: bool = typer.Option(True, "--copy/--no-copy")) -> None:  # fmt: skip
    """Go back one version of a build (and recompile it)."""
    _step(build, -1, copy)


@app.command()
def redo(build: str = typer.Argument(..., help="Build name or ops.json path."),
         copy: bool = typer.Option(True, "--copy/--no-copy")) -> None:  # fmt: skip
    """Go forward one version after an undo (and recompile it)."""
    _step(build, +1, copy)


@app.command()
def history(build: str = typer.Argument(..., help="Build name or ops.json path.")) -> None:
    """The versions of a build: what made each one and what it cost."""
    from img2schem.designer.history import History, resolve_build

    hist = History(resolve_build(build))
    if not hist.versions:
        raise _fail(f"no history for {build!r}")
    t = Table("", "version", "kind", "instruction", "cost", "when")
    for v in hist.versions:
        cost = f"${v['cost_usd']:.2f}" if v.get("cost_usd") is not None else "-"
        t.add_row("→" if v["n"] == hist.current else "", str(v["n"]), v.get("kind", ""),
                  str(v.get("instruction", ""))[:60], cost, v.get("time", ""))  # fmt: skip
    console.print(t)
    total = sum(v.get("cost_usd") or 0 for v in hist.versions)
    console.print(f"total API cost: ${total:.2f}")


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
    for p in write_previews(grid, out or file.parent, px=max(px, 8), palette=_load_palette()):
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
    line(key, "ANTHROPIC_API_KEY set" if key else "ANTHROPIC_API_KEY not set: copy .env.example to .env and fill it in")
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    console.print(f"  API workspace: {ws}" if ws else "  API workspace: none (only needed for keys without one)")
    budgets = ", ".join(f"{n} warn ${b.warn:.2f} / stop ${b.stop:.2f}" for n, b in s.claude.budget_usd.items())
    console.print(f"  API budget per build: {budgets}")
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
    colors = _load_palette()
    line(
        colors is not None,
        f"palette: {len(colors.blocks)} blocks" if colors else "no palette (`img2schem palette import DUMPS`)",
    )
    for w in i.warnings:
        console.print(f"[yellow]warning:[/yellow] {w}")


if __name__ == "__main__":
    app()
