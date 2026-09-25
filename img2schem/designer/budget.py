"""Per-build API budget guard (SOW RD.5, owner limits D-030).

The client asks ``check`` before every call with the call's worst-case cost (input plus ``max_tokens`` of
output at list price), so the hard stop is never passed: the build stops cleanly with the ops made so far.
``add`` records what a call actually cost and returns a warning once, when spending passes ``warn``.
"""

from __future__ import annotations

from img2schem.config import BudgetUSD


class BudgetExceeded(RuntimeError):
    pass


class BudgetGuard:
    def __init__(self, limit: BudgetUSD, name: str = "default"):
        self.limit, self.name = limit, name
        self.spent = 0.0
        self.warned = False

    def check(self, worst_case_usd: float) -> None:
        """Raise ``BudgetExceeded`` if a call costing up to ``worst_case_usd`` could pass the hard stop."""
        if self.spent + worst_case_usd > self.limit.stop:
            raise BudgetExceeded(
                f"stopping: ${self.spent:.2f} spent, and the next call could cost up to ${worst_case_usd:.2f}, "
                f"passing the {self.name} budget's ${self.limit.stop:.2f} limit"
                + ("" if self.name == "large" else " (use --budget large for up to $10)")
            )

    def add(self, cost_usd: float) -> str | None:
        """Record a call's actual cost; a warning message the first time spending passes ``warn``."""
        self.spent += cost_usd
        if not self.warned and self.spent >= self.limit.warn:
            self.warned = True
            return (f"this build has cost ${self.spent:.2f}, past the {self.name} budget's ${self.limit.warn:.2f} "
                    f"warning (hard limit ${self.limit.stop:.2f})")  # fmt: skip
        return None
