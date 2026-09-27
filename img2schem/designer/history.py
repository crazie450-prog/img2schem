"""Versions of a build (SOW RD.4): every design and edit is one entry, with undo and redo.

``builds/<name>.ops.json`` is the current version; ``builds/<name>.history/`` keeps every version
(``v001.ops.json`` ...) and ``log.json`` (the current version and what made each one). An edit after an undo
drops the versions that were undone, like any editor.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

BUILDS = Path("builds")


def resolve_build(ref: str | Path) -> Path:
    """A build name (``watchtower``) or a path to an ops.json."""
    p = Path(ref)
    if p.suffix == ".json" or p.exists():
        return p
    return BUILDS / f"{ref}.ops.json"


class History:
    def __init__(self, ops_path: Path):
        self.ops_path = ops_path
        self.dir = ops_path.parent / (ops_path.name.removesuffix(".json").removesuffix(".ops") + ".history")
        self.log_path = self.dir / "log.json"
        self.log: dict[str, Any] = (json.loads(self.log_path.read_text(encoding="utf-8")) if self.log_path.is_file()
                                    else {"current": 0, "versions": []})  # fmt: skip

    @property
    def versions(self) -> list[dict[str, Any]]:
        return self.log["versions"]  # type: ignore[no-any-return]

    @property
    def current(self) -> int:
        return int(self.log["current"])

    def commit(self, text: str, **meta: Any) -> int:
        """Save ``text`` as the next version after the current one (dropping undone versions) and make it the
        build's ops.json. Returns the new version number."""
        self.dir.mkdir(parents=True, exist_ok=True)
        for v in self.versions[self.current :]:
            (self.dir / v["file"]).unlink(missing_ok=True)
        del self.versions[self.current :]
        n = self.current + 1
        entry = {"n": n, "file": f"v{n:03d}.ops.json", "time": time.strftime("%Y-%m-%d %H:%M:%S"), **meta}
        (self.dir / entry["file"]).write_text(text, encoding="utf-8")
        self.versions.append(entry)
        self.log["current"] = n
        self._write(text)
        return n

    def ensure_started(self, note: str = "starting point") -> None:
        """An ops.json made outside the history (hand-written, `compile`) becomes version 1 before its first edit."""
        if not self.versions and self.ops_path.is_file():
            self.commit(self.ops_path.read_text(encoding="utf-8"), kind="import", instruction=note)

    def step(self, delta: int) -> dict[str, Any]:
        """Undo (-1) or redo (+1): make that version current; returns its entry."""
        target = self.current + delta
        if not 1 <= target <= len(self.versions):
            raise ValueError("nothing to undo" if delta < 0 else "nothing to redo")
        self.log["current"] = target
        entry = self.versions[target - 1]
        self._write((self.dir / entry["file"]).read_text(encoding="utf-8"))
        return entry

    def _write(self, text: str) -> None:
        self.ops_path.parent.mkdir(parents=True, exist_ok=True)
        self.ops_path.write_text(text, encoding="utf-8")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text(json.dumps(self.log, indent=1), encoding="utf-8")
