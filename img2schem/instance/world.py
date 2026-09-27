"""Worlds of an instance and their block registries (Forge 1.7.10 ``level.dat`` -> ``FML.ItemData``).

Each ``ItemData`` entry is ``{K: "\\u0001modid:name", V: id}``; the ``\\u0001`` prefix marks blocks and
``\\u0002`` items. Only the names matter to img2schem: GTNH's WorldEdit remaps names to IDs on load.
"""

from __future__ import annotations

from pathlib import Path

import nbtlib

from img2schem.models import WorldPalette

BLOCK_PREFIX = "\u0001"


def list_worlds(game_dir: Path) -> list[Path]:
    saves = game_dir / "saves"
    if not saves.is_dir():
        return []
    return sorted(d for d in saves.iterdir() if (d / "level.dat").is_file())


def read_world_palette(world_dir: Path) -> WorldPalette:
    """Raises ValueError if level.dat has no Forge block registry."""
    level_dat = world_dir / "level.dat"
    root = nbtlib.load(str(level_dat))
    fml = root.get("FML")
    if fml is None or "ItemData" not in fml:
        raise ValueError(f"{level_dat} has no FML.ItemData block registry (not a Forge 1.7.10 world?)")
    blocks: dict[str, int] = {}
    for entry in fml["ItemData"]:
        key = str(entry["K"])
        if key.startswith(BLOCK_PREFIX):
            blocks[key[1:]] = int(entry["V"])
    return WorldPalette(world=world_dir.name, level_dat=str(level_dat), blocks=dict(sorted(blocks.items())))


def resolve_world(game_dir: Path, ref: str) -> Path:
    """A save folder name under ``saves/``, or a path to a world folder."""
    for cand in (game_dir / "saves" / ref, Path(ref)):
        if (cand / "level.dat").is_file():
            return cand
    raise LookupError(f"no world {ref!r} (looked in {game_dir / 'saves'})")
