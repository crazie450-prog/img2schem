"""RI.2–RI.4: MC version, loader, mod list, client jar and WorldEdit for one game directory."""

from __future__ import annotations

import json
import re
import tomllib
import zipfile
from pathlib import Path
from typing import Any

from img2schem.models import InstanceInfo, Loader, ModInfo


def _read_zip_text(z: zipfile.ZipFile, name: str) -> str | None:
    try:
        return z.read(name).decode("utf-8", errors="replace")
    except KeyError:
        return None


def read_mod_jar(jar: Path) -> tuple[ModInfo, Loader | None]:
    """Mod id/name/version from a mod jar's metadata, plus which loader the metadata implies."""
    fallback = ModInfo(id=re.sub(r"[^a-z0-9_]", "_", jar.stem.lower()), jar=jar.name)
    try:
        with zipfile.ZipFile(jar) as z:
            for meta_name, loader in (("fabric.mod.json", "fabric"), ("quilt.mod.json", "quilt")):
                text = _read_zip_text(z, meta_name)
                if text is None:
                    continue
                data = json.loads(text, strict=False)
                if loader == "quilt":
                    data = data.get("quilt_loader", {})
                    md = data.get("metadata", {})
                    return ModInfo(
                        id=data["id"], name=md.get("name"), version=data.get("version"), jar=jar.name
                    ), "quilt"
                return ModInfo(
                    id=data["id"], name=data.get("name"), version=data.get("version"), jar=jar.name
                ), "fabric"
            for meta_name, loader in (("META-INF/neoforge.mods.toml", "neoforge"), ("META-INF/mods.toml", "forge")):
                text = _read_zip_text(z, meta_name)
                if text is None:
                    continue
                mods = tomllib.loads(text).get("mods") or [{}]
                first: dict[str, Any] = mods[0]
                version = first.get("version")
                if isinstance(version, str) and "${" in version:  # e.g. ${file.jarVersion}
                    version = _manifest_version(z)
                return ModInfo(
                    id=first.get("modId", fallback.id), name=first.get("displayName"), version=version, jar=jar.name
                ), loader  # type: ignore[return-value]
            text = _read_zip_text(z, "mcmod.info")  # Forge 1.7.10
            if text is not None:
                data = json.loads(text, strict=False)
                entries = data.get("modList", []) if isinstance(data, dict) else data
                first = entries[0] if entries else {}
                return ModInfo(
                    id=first.get("modid", fallback.id),
                    name=first.get("name"),
                    version=first.get("version"),
                    jar=jar.name,
                ), "forge"
    except (zipfile.BadZipFile, OSError, ValueError, KeyError, IndexError, AttributeError, tomllib.TOMLDecodeError):
        pass
    return fallback, None


def _manifest_version(z: zipfile.ZipFile) -> str | None:
    text = _read_zip_text(z, "META-INF/MANIFEST.MF") or ""
    m = re.search(r"^Implementation-Version:\s*(\S+)", text, re.M)
    return m.group(1) if m else None


def read_mods(game_dir: Path) -> tuple[list[ModInfo], set[Loader]]:
    mods_dir = game_dir / "mods"
    mods: list[ModInfo] = []
    loaders: set[Loader] = set()
    if mods_dir.is_dir():
        for jar in sorted(mods_dir.glob("*.jar")):
            info, loader = read_mod_jar(jar)
            mods.append(info)
            if loader:
                loaders.add(loader)
    mods.sort(key=lambda m: m.id)
    return mods, loaders


def schematics_dir(game_dir: Path) -> Path:
    """WorldEdit's save folder: ``schematic-save-dir`` in config/worldedit/worldedit.properties (default
    ``schematics``), relative to config/worldedit/. Read from the WorldEdit 6.3.0 (GTNH) jar."""
    we_dir = game_dir / "config" / "worldedit"
    save_dir = "schematics"
    props = we_dir / "worldedit.properties"
    if props.is_file():
        for line in props.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "schematic-save-dir" and value.strip():
                save_dir = value.strip()
    return we_dir / save_dir


def loader_from_version_id(version_id: str) -> tuple[Loader, str | None]:
    """Loader + loader version from a launcher version id such as ``fabric-loader-0.16.9-1.21.4``."""
    v = version_id.lower()
    patterns: list[tuple[Loader, str]] = [
        ("fabric", r"fabric-loader-([\w.+]+)-"),
        ("quilt", r"quilt-loader-([\w.+]+)-"),
        ("neoforge", r"neoforge-([\w.+\-]+)"),
        ("forge", r"forge-?([\w.+\-]+)"),
    ]
    for loader, pat in patterns:
        if loader in v:
            m = re.search(pat, v)
            return loader, (m.group(1) if m else None)
    return "vanilla", None


def detect_instance(
    *,
    name: str,
    launcher: str,
    game_dir: Path,
    mc_version: str | None,
    loader: Loader | None = None,
    loader_version: str | None = None,
    jar_candidates: list[Path] | None = None,
) -> InstanceInfo:
    warnings: list[str] = []
    mods, jar_loaders = read_mods(game_dir)
    if loader in (None, "unknown"):
        if len(jar_loaders) == 1:
            loader = next(iter(jar_loaders))
        elif not mods:
            loader = "vanilla"
        else:
            loader = "unknown"
            warnings.append(f"could not determine loader (mod metadata suggests {sorted(jar_loaders) or 'none'})")
    elif jar_loaders and loader not in jar_loaders and not (loader == "quilt" and "fabric" in jar_loaders):
        warnings.append(f"launcher says {loader} but mod jars declare {sorted(jar_loaders)}")

    client_jar = next((j for j in (jar_candidates or []) if j.is_file()), None)
    if client_jar is None:
        warnings.append(f"vanilla client jar for {mc_version or '?'} not found; launch that version once (RI.3)")

    worldedit = any(m.id.lower() == "worldedit" for m in mods)
    return InstanceInfo(
        name=name,
        launcher=launcher,
        game_dir=str(game_dir),
        mc_version=mc_version,
        loader=loader or "unknown",
        loader_version=loader_version,
        client_jar=str(client_jar) if client_jar else None,
        mods=mods,
        worldedit=worldedit,
        schematics_dir=str(schematics_dir(game_dir)),
        warnings=warnings,
    )
