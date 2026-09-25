"""The designer's system prompt: prompts/system_<version>.md + docs/DSL.md + a palette summary (SOW §6.7)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from img2schem.models import Palette
from img2schem.palette.query import PaletteIndex
from img2schem.util.color import hex_color

PROMPT_VERSION = "v1"
DSL = Path(__file__).parents[2] / "docs" / "DSL.md"  # the ops reference doubles as Claude's (CLAUDE.md)


def palette_summary(palette: Palette | None) -> str:
    """Building blocks with stairs (one line per block, variants counted), and what each mod contributes."""
    if palette is None:
        return "No palette is loaded: use vanilla `minecraft:` blocks, and set `<slot>.stairs` / `.slab` explicitly."
    idx = PaletteIndex(palette)
    lines = []
    for b in palette.blocks.values():
        if b.shape != "full_cube":
            continue
        with_stairs = [v for v in b.usable() if idx.family(v.block)["stairs"]]
        if not with_stairs:
            continue
        v = with_stairs[0]
        fam = idx.family(v.block)
        color = v.face_rgb or v.rgb
        more = f" (+{len(with_stairs) - 1} variants with stairs)" if len(with_stairs) > 1 else ""
        lines.append(f"{v.block} | {v.display} | {hex_color(color) if color else '-'} | "
                     f"stairs {fam['stairs']} | slab {fam['slab'] or '-'}{more}")  # fmt: skip
    mods = Counter(b.mod for b in palette.blocks.values() for _ in b.usable())
    return (
        "Full blocks that have matching stairs (block | name | true color | stairs | slab). Thousands more "
        "blocks exist: find them with search_palette.\n\n"
        + "\n".join(lines)
        + "\n\nUsable variants per mod: "
        + ", ".join(f"{m} {n}" for m, n in mods.most_common(30))
    )


def system_prompt(palette: Palette | None, version: str = PROMPT_VERSION) -> str:
    base = (Path(__file__).parent / "prompts" / f"system_{version}.md").read_text(encoding="utf-8")
    dsl = DSL.read_text(encoding="utf-8") if DSL.is_file() else "(docs/DSL.md not found)"
    return f"{base}\n\n# Ops reference (docs/DSL.md)\n\n{dsl}\n\n# Palette summary\n\n{palette_summary(palette)}\n"
