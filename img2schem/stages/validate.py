"""S5 validator, Phase 0 structural rules: R10.1 (states parse), R10.1b (states exist in the active
palette, no flagged blocks), R10.2 (budgets). File-level R10.1 failures are raised by the reader and
reported by the caller. The remaining §6.12 rules and auto-fixes land in Phase 1.
"""

from __future__ import annotations

import json
from pathlib import Path

from img2schem.config import Budgets
from img2schem.models import AIR, BlockGrid, Issue, Palette
from img2schem.util.blockstate import parse_state

DEFAULT_EXCLUDE_FLAGS = ("utility", "gravity", "block_entity", "code_rendered")


def validate_grid(
    grid: BlockGrid,
    budgets: Budgets,
    palette: Palette | None = None,
    exclude_flags: tuple[str, ...] = DEFAULT_EXCLUDE_FLAGS,
    allow_large: bool = False,
) -> list[Issue]:
    issues: list[Issue] = []
    if int(grid.idx.min(initial=0)) < 0 or int(grid.idx.max(initial=0)) >= len(grid.palette):
        issues.append(Issue(rule="R10.1", severity="error", message="block index out of palette range"))

    used = {int(i) for i in set(grid.idx.reshape(-1).tolist())}
    for i, state in enumerate(grid.palette):
        if i not in used or state == AIR:
            continue
        try:
            block_id, _ = parse_state(state)
        except ValueError as e:
            issues.append(Issue(rule="R10.1", severity="error", message=str(e)))
            continue
        if palette is None:
            continue
        reason = palette.validate_state(state)
        if reason:
            issues.append(Issue(rule="R10.1b", severity="error", message=reason))
            continue
        flags = set(palette.blocks[block_id].flags) & set(exclude_flags)
        if flags:
            issues.append(
                Issue(
                    rule="R10.1b",
                    severity="error",
                    message=f"{block_id} is flagged {sorted(flags)} and excluded by default",
                )
            )

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
                rule="R10.2", severity="error", message=f"{total} cells exceed hard_max_total {budgets.hard_max_total}"
            )
        )
    return issues


def failed(issues: list[Issue], strict: bool = False) -> bool:
    """R10.4: errors fail; with ``strict`` warnings fail too."""
    bad = {"error", "warning"} if strict else {"error"}
    return any(i.severity in bad for i in issues)


def write_issues(issues: list[Issue], path: Path) -> None:
    path.write_text(json.dumps([i.model_dump() for i in issues], indent=1), encoding="utf-8")
