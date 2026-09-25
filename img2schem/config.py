"""R11.1 layered settings: defaults -> user config.yaml -> ./config.yaml -> IMG2SCHEM_* env -> CLI flags.

Phase 0 subset of SOW §5.4; later phases add their sections here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class Budgets(BaseModel):
    # Owner decision D-026: grand-scale builds. max_dim / max_nonair only warn; hard_max_total stops the compile.
    max_dim: int = 256
    max_nonair: int = 1_000_000
    hard_max_total: int = 16_000_000
    max_height: int = 256  # Minecraft 1.7.10 worlds end at y = 256: a taller build cannot be pasted


class BudgetUSD(BaseModel):
    """Per-build API spend: a warning once ``warn`` is passed, a clean stop before ``stop`` would be passed."""

    warn: float = Field(gt=0)
    stop: float = Field(gt=0)

    @model_validator(mode="after")
    def _order(self) -> BudgetUSD:
        if self.stop < self.warn:
            raise ValueError(f"budget stop {self.stop} is below warn {self.warn}")
        return self


def _default_budgets() -> dict[str, BudgetUSD]:
    # Owner decision D-030: US$1 / US$5 per build by default, US$5 / US$10 with --budget large.
    return {"default": BudgetUSD(warn=1.0, stop=5.0), "large": BudgetUSD(warn=5.0, stop=10.0)}


class ClaudeSettings(BaseModel):
    # Model IDs and the rest come from designer/data/defaults.yaml (CLAUDE.md: never hard-coded).
    model: str
    fallback_model: str | None = None
    effort: str = "high"
    max_tokens: int = Field(32000, ge=1024)
    turn_cap: int = Field(30, ge=1)
    budget_usd: dict[str, BudgetUSD] = Field(default_factory=_default_budgets)

    def budget(self, name: str = "default") -> BudgetUSD:
        if name not in self.budget_usd:
            raise ValueError(f"no budget {name!r} (have: {', '.join(self.budget_usd)})")
        return self.budget_usd[name]


class ExportSettings(BaseModel):
    offset_mode: str = "front-center"
    include_we_metadata: bool = True
    write_to_instance: bool = True


class Settings(BaseModel):
    instance: str | None = None
    world: str | None = None  # save folder name or path; its level.dat lists the valid block names
    palette: str | None = None  # palette.json written by `palette import` (colors, shapes)
    schem_version: int = 2
    budgets: Budgets = Field(default_factory=Budgets)
    export: ExportSettings = Field(default_factory=ExportSettings)
    claude: ClaudeSettings = Field(default_factory=lambda: ClaudeSettings.model_validate(_packaged()["claude"]))
    cache_dir: str = "~/.cache/img2schem"

    @property
    def cache_path(self) -> Path:
        return Path(self.cache_dir).expanduser()


def user_config_path() -> Path:
    if env := os.environ.get("IMG2SCHEM_CONFIG"):
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "img2schem" / "config.yaml"


def _deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _packaged() -> dict[str, Any]:
    return _read_yaml(Path(__file__).parent / "designer" / "data" / "defaults.yaml")


def load_settings() -> Settings:
    data: dict[str, Any] = _packaged()
    for p in (user_config_path(), Path("config.yaml")):
        data = _deep_merge(data, _read_yaml(p))
    for key, field in (
        ("IMG2SCHEM_INSTANCE", "instance"),
        ("IMG2SCHEM_WORLD", "world"),
        ("IMG2SCHEM_CACHE_DIR", "cache_dir"),
    ):
        if key in os.environ:
            data[field] = os.environ[key]
    return Settings.model_validate(data)


def save_user_setting(key: str, value: Any) -> Path:
    path = user_config_path()
    data = _read_yaml(path)
    data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path
