"""RP.1–RP.2: asset sources (vanilla jar, mod jars incl. nested jars, resource packs) and a virtual FS.

Precedence, lowest to highest: vanilla client jar, mod jars sorted by mod id (nested jars right after
their parent), then resource packs enabled in options.txt (last entry wins). Jars are read in place with
``zipfile``; nothing is extracted to disk.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from img2schem.models import InstanceInfo

NESTED_JAR_DIRS = ("META-INF/jars/", "META-INF/jarjar/")
BUILTIN_PACKS = {"vanilla", "fabric", "mod_resources", "builtin", "programmer_art", "high_contrast"}


@dataclass
class Source:
    label: str
    kind: str  # "vanilla" | "mod" | "resourcepack"
    files: dict[str, bytes | tuple[zipfile.ZipFile, str] | Path] = field(default_factory=dict)

    def read(self, path: str) -> bytes:
        ref = self.files[path]
        if isinstance(ref, bytes):
            return ref
        if isinstance(ref, Path):
            return ref.read_bytes()
        return ref[0].read(ref[1])


def _zip_source(
    label: str, kind: str, z: zipfile.ZipFile, errors: list[dict[str, str]], depth: int = 0
) -> list[Source]:
    """A jar/zip as a Source, followed by its nested jars (recursively)."""
    src = Source(label, kind)
    nested: list[Source] = []
    for name in z.namelist():
        if name.startswith("assets/") and not name.endswith("/"):
            src.files[name] = (z, name)
        elif kind == "mod" and name.startswith(NESTED_JAR_DIRS) and name.endswith(".jar") and depth < 4:
            try:
                inner = zipfile.ZipFile(io.BytesIO(z.read(name)))
                nested.extend(_zip_source(f"{label}!/{name}", kind, inner, errors, depth + 1))
            except (zipfile.BadZipFile, OSError) as e:
                errors.append({"file": f"{label}!/{name}", "message": f"bad nested jar: {e}"})
    return [src, *nested]


def _folder_source(label: str, root: Path) -> Source:
    src = Source(label, "resourcepack")
    assets = root / "assets"
    if assets.is_dir():
        for p in assets.rglob("*"):
            if p.is_file():
                src.files[p.relative_to(root).as_posix()] = p
    return src


def enabled_resource_packs(game_dir: Path) -> list[Path]:
    """Resource packs from options.txt ``resourcePacks:[...]``, lowest to highest priority."""
    opts = game_dir / "options.txt"
    if not opts.is_file():
        return []
    for line in opts.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("resourcePacks:"):
            try:
                entries = json.loads(line.split(":", 1)[1])
            except ValueError:
                return []
            out = []
            for e in entries:
                if not isinstance(e, str) or e in BUILTIN_PACKS or not e.startswith("file/"):
                    continue
                p = game_dir / "resourcepacks" / e[len("file/") :]
                if p.exists():
                    out.append(p)
            return out
    return []


def collect_sources(instance: InstanceInfo, errors: list[dict[str, str]]) -> list[Source]:
    game_dir = Path(instance.game_dir)
    sources: list[Source] = []
    if instance.client_jar:
        sources.extend(
            _zip_source(Path(instance.client_jar).name, "vanilla", zipfile.ZipFile(instance.client_jar), errors)
        )
    for mod in sorted(instance.mods, key=lambda m: m.id):  # instance.mods is already id-sorted
        jar = game_dir / "mods" / mod.jar
        try:
            sources.extend(_zip_source(mod.jar, "mod", zipfile.ZipFile(jar), errors))
        except (zipfile.BadZipFile, OSError) as e:
            errors.append({"file": mod.jar, "message": f"unreadable mod jar: {e}"})
    for pack in enabled_resource_packs(game_dir):
        if pack.is_dir():
            sources.append(_folder_source(pack.name, pack))
        else:
            try:
                sources.extend(_zip_source(pack.name, "resourcepack", zipfile.ZipFile(pack), errors))
            except (zipfile.BadZipFile, OSError) as e:
                errors.append({"file": pack.name, "message": f"unreadable resource pack: {e}"})
    return sources


class AssetFS:
    """Virtual FS ``assets/<ns>/...`` -> bytes; later sources override earlier ones."""

    def __init__(self, sources: list[Source], errors: list[dict[str, str]]):
        self.index: dict[str, Source] = {}
        self.errors = errors
        self._json_cache: dict[str, Any] = {}
        for src in sources:
            for path in src.files:
                self.index[path] = src

    def source_of(self, path: str) -> Source | None:
        return self.index.get(path)

    def read_json(self, path: str) -> Any:
        """Parsed JSON or None; malformed files are logged to ``errors`` and never raise (RP.16)."""
        if path in self._json_cache:
            return self._json_cache[path]
        src = self.index.get(path)
        data = None
        if src is not None:
            try:
                data = json.loads(src.read(path).decode("utf-8-sig"))
            except (ValueError, UnicodeDecodeError, OSError, KeyError) as e:
                self.errors.append({"file": f"{src.label}:{path}", "message": str(e)})
        self._json_cache[path] = data
        return data
