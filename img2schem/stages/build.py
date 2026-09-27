"""Compile an OpsDoc into the run folder (S4 -> S5 -> S7): .schematic, previews, issues.json, report.json, and
optionally a copy in the instance's WorldEdit folder. Used by `compile` and the web server."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from img2schem.config import Settings
from img2schem.engine.compiler import compile_ops, paste_offset
from img2schem.engine.ops import OpsDoc
from img2schem.models import InstanceInfo, Issue, Palette, WorldPalette
from img2schem.palette.query import PaletteIndex
from img2schem.stages.export_schem import SchemMeta, copy_to_schematics_dir, mods_required, write_schematic
from img2schem.stages.preview import render_debug_ops, write_previews
from img2schem.stages.validate import check_build, failed, write_issues


class BuildFailed(ValueError):
    """Validation found errors; ``issues`` has them (issues.json is written)."""

    def __init__(self, issues: list[Issue]):
        super().__init__("validation failed; see issues.json")
        self.issues = issues


@dataclass
class Built:
    out: Path
    schematic: Path
    report: dict[str, Any]
    issues: list[Issue] = field(default_factory=list)
    copied_to: Path | None = None


def build_outputs(doc: OpsDoc, name: str, out: Path, *, settings: Settings, palette: Palette | None,
                  world: WorldPalette | None, instance: InstanceInfo | None, copy: bool,
                  ops_file: Path | None = None) -> Built:  # fmt: skip
    """Raises CompileError (from the engine) or BuildFailed."""
    t0 = time.perf_counter()
    compiled = compile_ops(doc, PaletteIndex(palette) if palette else None, settings.budgets.hard_max_total)
    t_compile = time.perf_counter() - t0
    out.mkdir(parents=True, exist_ok=True)
    grid = compiled.grid.compact()
    issues = check_build(grid, compiled.labels, doc.style, settings.budgets, palette, world)
    write_issues(issues, out / "issues.json")
    if failed(issues):
        raise BuildFailed(issues)
    grid.save(out)
    inst = instance
    meta = SchemMeta(name, inst.name if inst else None, inst.mc_version if inst else None,
                     inst.loader if inst else None)  # fmt: skip
    schem = write_schematic(out / f"{name}.schematic", grid, offset=paste_offset(compiled), meta=meta)
    write_previews(grid, out, palette=palette)
    render_debug_ops(grid, compiled.op_index, [o.id for o in doc.ops]).save(out / "debug_ops.png")
    report = {
        "name": name,
        "ops_file": str(ops_file) if ops_file else None,
        "dims_wxhxl": list(grid.shape),
        "nonair": grid.nonair(),
        "palette_size": len(grid.palette) - 1,
        "mods_required": mods_required(grid.palette),
        "ops_count": len(doc.ops),
        "set_cells_used": sum(len(o.cells) for o in doc.ops if o.op == "set"),
        "time_compile_s": round(t_compile, 3),
        "validation": {
            "ok": True,
            "autofixes": sum(i.autofix_applied for i in issues),
            "issues": [i.model_dump() for i in issues],
        },
        "ops": [vars(sm) for sm in compiled.summaries],
        "counts": dict(sorted(grid.counts().items(), key=lambda kv: -kv[1])),
    }
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    built = Built(out, schem, report, issues)
    if copy and inst and inst.worldedit and inst.schematics_dir and settings.export.write_to_instance:
        built.copied_to = copy_to_schematics_dir(schem, Path(inst.schematics_dir))
    return built
