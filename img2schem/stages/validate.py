"""S5 validator (SOW §6.12, re-scoped for 1.7.10).

``validate_grid``: R10.1 (blocks parse), R10.1b (blocks exist in the selected world), R10.2 (budgets),
R10.3 (floating fragments), R10.3b (a door at ground level; windows not touching the roof), R10.5 (door pairs),
R10.6 (doors supported), R10.8 (single-block roof holes), R10.10 (mods required). File-level R10.1 failures are
raised by the reader. ``autofix`` repairs what it safely can first (removes small floating fragments, completes
or removes orphan door halves, removes unsupported doors); every change is reported. R10.9 (trim/wall contrast)
needs the style, so it lives in ``contrast_issues``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
from scipy import ndimage

from img2schem.config import Budgets
from img2schem.engine.materials import guess_shape
from img2schem.models import AIR, BlockGrid, Issue, Palette, WorldPalette
from img2schem.util.block import format_block, namespace, parse_block

ShapeOf = Callable[[str], str]
MIN_FRAGMENT = 4  # R10.3: floating fragments smaller than this are removed
# R10.3 connectivity: faces and edges (18-neighborhood). Stair and slab roofs step diagonally, so consecutive
# courses share only an edge yet form one continuous surface in game.
CONNECTIVITY = ndimage.generate_binary_structure(3, 2)
WINDOW, DOOR_L, ROOF = 2, 3, 4  # compiler labels


def _pos(cell: np.ndarray) -> tuple[int, int, int]:
    return int(cell[0]), int(cell[1]), int(cell[2])


def shape_lookup(palette: Palette | None) -> ShapeOf:
    """Block -> shape from the NEI palette, else guessed from vanilla-style names."""

    def shape_of(block: str) -> str:
        name, _ = parse_block(block)
        blk = palette.blocks.get(name) if palette else None
        return blk.shape if blk else guess_shape(name)

    return shape_of


def _doors(grid: BlockGrid, shape_of: ShapeOf) -> list[tuple[int, int, int, str, int]]:
    """(x, y, z, name, meta) of every door cell."""
    door_idx = [i for i, b in enumerate(grid.palette) if b != AIR and shape_of(b) == "door"]
    out = []
    for x, y, z in np.argwhere(np.isin(grid.idx, door_idx)):
        name, meta = parse_block(grid.palette[grid.idx[x, y, z]])
        out.append((int(x), int(y), int(z), name, meta))
    return out


def autofix(grid: BlockGrid, shape_of: ShapeOf) -> list[Issue]:
    """Repair in place what can be repaired safely; returns one issue per change (autofix_applied=True)."""
    issues: list[Issue] = []
    w, h, length = grid.shape

    def at(x: int, y: int, z: int) -> str | None:
        return grid.palette[grid.idx[x, y, z]] if 0 <= x < w and 0 <= y < h and 0 <= z < length else None

    # R10.5 door pairs: a lower half (meta bit 3 clear) needs an upper half of the same door above, and back.
    for x, y, z, name, meta in _doors(grid, shape_of):
        lower = not meta & 8
        other = at(x, y + 1, z) if lower else at(x, y - 1, z)
        if other is not None and other != AIR and parse_block(other)[0] == name:
            continue
        if lower and other == AIR:
            grid.set(x, y + 1, z, format_block(name, 8))
            msg = "added the missing upper half"
        elif lower and other is None and y + 1 >= h:
            grid.idx[x, y, z] = 0
            msg = "removed a lower half at the top of the build"
        else:
            grid.idx[x, y, z] = 0
            msg = f"removed an orphan {'lower' if lower else 'upper'} half"
        issues.append(Issue(rule="R10.5", severity="warning", pos=(x, y, z), autofix_applied=True,
                            message=f"door {name}: {msg}"))  # fmt: skip

    # R10.6 doors stand on something: remove an unsupported door (both halves).
    for x, y, z, name, meta in _doors(grid, shape_of):
        if meta & 8:
            continue
        below = at(x, y - 1, z)
        if below is None or below == AIR:
            grid.idx[x, y, z] = 0
            if at(x, y + 1, z) is not None and parse_block(at(x, y + 1, z) or AIR)[0] == name:
                grid.idx[x, y + 1, z] = 0
            issues.append(Issue(rule="R10.6", severity="warning", pos=(x, y, z), autofix_applied=True,
                                message=f"door {name} had nothing below it; removed"))  # fmt: skip

    # R10.3 floating fragments (face/edge-connected; grounded = touches the bottom layer).
    comps, n = ndimage.label(grid.idx != 0, structure=CONNECTIVITY)
    grounded = set(np.unique(comps[:, 0, :]).tolist()) - {0}
    for c in range(1, n + 1):
        if c in grounded:
            continue
        cells = np.argwhere(comps == c)
        if len(cells) < MIN_FRAGMENT:
            grid.idx[comps == c] = 0
            msg = f"removed a floating fragment of {len(cells)} blocks"
            issues.append(
                Issue(rule="R10.3", severity="warning", pos=_pos(cells[0]), autofix_applied=True, message=msg)
            )
    return issues


def validate_grid(
    grid: BlockGrid,
    budgets: Budgets,
    palette: WorldPalette | None = None,
    allow_large: bool = False,
    shape_of: ShapeOf | None = None,
    labels: np.ndarray | None = None,
) -> list[Issue]:
    """``labels`` (the compiler's per-cell labels) enable the window/roof checks."""
    issues: list[Issue] = []
    if int(grid.idx.min(initial=0)) < 0 or int(grid.idx.max(initial=0)) >= len(grid.palette):
        issues.append(Issue(rule="R10.1", severity="error", message="block index out of palette range"))

    used = {int(i) for i in set(grid.idx.reshape(-1).tolist())}
    for i, block in enumerate(grid.palette):
        if i not in used or block == AIR:
            continue
        try:
            parse_block(block)
        except ValueError as e:
            issues.append(Issue(rule="R10.1", severity="error", message=str(e)))
            continue
        if palette is not None and (reason := palette.validate_block(block)):
            issues.append(Issue(rule="R10.1b", severity="error", message=reason))

    dims = grid.shape
    if max(dims) > budgets.max_dim:
        issues.append(
            Issue(rule="R10.2", severity="warning", message=f"dimensions {dims} exceed max_dim {budgets.max_dim}")
        )
    nonair = grid.nonair()
    if nonair > budgets.max_nonair:
        issues.append(
            Issue(
                rule="R10.2",
                severity="warning",
                message=f"{nonair} non-air blocks exceed max_nonair {budgets.max_nonair}",
            )
        )
    total = dims[0] * dims[1] * dims[2]
    if total > budgets.hard_max_total and not allow_large:
        issues.append(
            Issue(
                rule="R10.2",
                severity="error",
                message=f"{total} cells exceed hard_max_total {budgets.hard_max_total}",
            )
        )
    if any(i.severity == "error" for i in issues):
        return issues  # structural errors: skip the geometry checks
    shape_of = shape_of or shape_lookup(None)
    w, h, length = grid.shape

    comps, n = ndimage.label(grid.idx != 0, structure=CONNECTIVITY)
    grounded = set(np.unique(comps[:, 0, :]).tolist()) - {0}
    for c in sorted(set(range(1, n + 1)) - grounded):
        cells = np.argwhere(comps == c)
        msg = f"floating fragment of {len(cells)} blocks (not connected to the ground)"
        issues.append(Issue(rule="R10.3", severity="warning", pos=_pos(cells[0]), message=msg))

    doors = _doors(grid, shape_of)
    for x, y, z, name, meta in doors:
        lower = not meta & 8
        ny = y + 1 if lower else y - 1
        other = grid.palette[grid.idx[x, ny, z]] if 0 <= ny < h else AIR
        if other == AIR or parse_block(other)[0] != name:
            msg = f"door {name}: {'lower' if lower else 'upper'} half without its pair"
            issues.append(Issue(rule="R10.5", severity="error", pos=(x, y, z), message=msg))
        elif lower and (y == 0 or grid.idx[x, y - 1, z] == 0):
            issues.append(Issue(rule="R10.6", severity="error", pos=(x, y, z),
                                message=f"door {name} has nothing below it and would pop off"))  # fmt: skip
    if not any(not meta & 8 and y <= 1 for _, y, _, _, meta in doors):
        issues.append(Issue(rule="R10.3b", severity="warning", message="no door at ground level"))

    if labels is not None:
        win = labels == WINDOW
        roof_above = np.zeros_like(win)
        roof_above[:, :-1, :] = labels[:, 1:, :] == ROOF
        for x, y, z in np.argwhere(win & roof_above)[:1]:
            issues.append(Issue(rule="R10.3b", severity="warning", pos=(int(x), int(y), int(z)),
                                message="a window touches the roof line"))  # fmt: skip
        roof = labels == ROOF
        hole = grid.idx == 0
        both_x = np.zeros_like(roof)
        both_x[1:-1] = roof[:-2] & roof[2:]
        both_z = np.zeros_like(roof)
        both_z[:, :, 1:-1] = roof[:, :, :-2] & roof[:, :, 2:]
        for x, y, z in np.argwhere(hole & (both_x | both_z))[:10]:
            issues.append(Issue(rule="R10.8", severity="warning", pos=(int(x), int(y), int(z)),
                                message="single-block hole in the roof"))  # fmt: skip

    mods = sorted({namespace(b) for b in grid.counts()} - {"minecraft"})
    if mods:
        issues.append(Issue(rule="R10.10", severity="info", message=f"mods required to paste: {', '.join(mods)}"))
    return issues


def contrast_issues(style: dict[str, str], lab_of: Callable[[str], tuple[float, float, float] | None],
                    min_de: float = 8.0) -> list[Issue]:  # fmt: skip
    """R10.9: trim that is too close in color to the wall disappears at a distance."""
    if "trim" not in style or "wall" not in style:
        return []
    a, b = lab_of(style["trim"]), lab_of(style["wall"])
    if a is None or b is None:
        return []
    de = float(np.linalg.norm(np.subtract(a, b)))
    if de >= min_de:
        return []
    return [Issue(rule="R10.9", severity="warning",
                  message=f"trim {style['trim']} is only dE {de:.1f} from wall {style['wall']} (< {min_de}); "
                          "pick a lighter or darker trim")]  # fmt: skip


def failed(issues: list[Issue], strict: bool = False) -> bool:
    """R10.4: errors fail; with ``strict`` warnings fail too."""
    bad = {"error", "warning"} if strict else {"error"}
    return any(i.severity in bad for i in issues)


def write_issues(issues: list[Issue], path: Path) -> None:
    path.write_text(json.dumps([i.model_dump() for i in issues], indent=1), encoding="utf-8")
