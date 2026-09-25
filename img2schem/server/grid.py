"""The compiled build as the 3D viewer draws it: one entry per block (color, shape boxes, opacity) and only the
cells that can be seen (a block buried on all six sides by opaque full blocks is left out)."""

from __future__ import annotations

from typing import Any

import numpy as np

from img2schem.engine.materials import guess_shape
from img2schem.models import AIR, BlockGrid, Palette
from img2schem.stages.preview import block_color, block_parts
from img2schem.util.block import parse_block
from img2schem.util.color import hex_color

SEE_THROUGH = ("pane", "fence", "fence_gate", "wall", "door", "trapdoor")
POST = [(0.375, 0.0, 0.375, 0.625, 1.0, 0.625)]


def _entry(block: str, palette: Palette | None) -> dict[str, Any]:
    name, _ = parse_block(block)
    blk = palette.blocks.get(name) if palette else None
    shape = blk.shape if blk else guess_shape(name)
    color = (palette.color(block) if palette else None) or block_color(block)
    glass = "glass" in name.lower() or "ice" in name.lower()
    parts = block_parts(block, palette)
    if parts is None and shape in ("fence", "wall"):
        parts = POST
    return {"name": block, "shape": shape, "color": hex_color(color), "opacity": 0.45 if glass else 1.0,
            "parts": parts}  # fmt: skip


def grid_payload(grid: BlockGrid, palette: Palette | None) -> dict[str, Any]:
    entries = [_entry(b, palette) if b != AIR else {"name": AIR} for b in grid.palette]
    opaque_ids = np.array([b != AIR and e.get("parts") is None and e.get("opacity", 1) == 1
                           and e.get("shape") not in SEE_THROUGH for b, e in zip(grid.palette, entries, strict=True)])
    solid = np.pad(opaque_ids[grid.idx], 1)
    covered = (solid[:-2, 1:-1, 1:-1] & solid[2:, 1:-1, 1:-1] & solid[1:-1, :-2, 1:-1] & solid[1:-1, 2:, 1:-1]
               & solid[1:-1, 1:-1, :-2] & solid[1:-1, 1:-1, 2:])  # fmt: skip
    cells = np.argwhere((grid.idx != 0) & ~covered)
    ids = grid.idx[cells[:, 0], cells[:, 1], cells[:, 2]]
    counts = grid.counts()
    return {
        "size": list(grid.shape),
        "blocks": entries,
        "cells": np.column_stack([cells, ids]).astype(int).reshape(-1).tolist(),  # x, y, z, block, ...
        "total": grid.nonair(),
        "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
    }
