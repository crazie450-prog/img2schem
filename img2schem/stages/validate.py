"""S5 validator, Phase 0 structural rules: R10.1 (blocks parse), R10.1b (blocks exist in the selected
world's registry), R10.2 (budgets). File-level R10.1 failures are raised by the reader and reported by the
caller. The remaining §6.12 rules and auto-fixes land in Phase 1.
"""

from __future__ import annotations

import json
from pathlib import Path

from img2schem.config import Budgets
from img2schem.models import AIR, BlockGrid, Issue, WorldPalette
from img2schem.util.block import parse_block


def validate_grid(
    grid: BlockGrid,
    budgets: Budgets,
    palette: WorldPalette | None = None,
    allow_large: bool = False,
) -> list[Issue]:
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
    return issues


def failed(issues: list[Issue], strict: bool = False) -> bool:
    """R10.4: errors fail; with ``strict`` warnings fail too."""
    bad = {"error", "warning"} if strict else {"error"}
    return any(i.severity in bad for i in issues)


def write_issues(issues: list[Issue], path: Path) -> None:
    path.write_text(json.dumps([i.model_dump() for i in issues], indent=1), encoding="utf-8")
