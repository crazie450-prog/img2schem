"""R11.1 layered settings: defaults -> user config.yaml -> ./config.yaml -> IMG2SCHEM_* env -> CLI flags.

Phase 0 subset of SOW §5.4; later phases add their sections here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class Budgets(BaseModel):
    max_dim: int = 128
    max_nonair: int = 250_000
    hard_max_total: int = 2_000_000


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


def load_settings() -> Settings:
    data: dict[str, Any] = {}
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
