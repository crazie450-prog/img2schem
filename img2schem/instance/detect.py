"""RI.2–RI.4: MC version, loader, mod list, DataVersion, client jar and WorldEdit for one game directory."""

from __future__ import annotations

import json
import re
import tomllib
import zipfile
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

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
    except (zipfile.BadZipFile, OSError, ValueError, KeyError, tomllib.TOMLDecodeError):
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


def world_version_from_jar(jar: Path) -> tuple[int | None, str | None]:
    """``(world_version, id)`` from the client jar's version.json."""
    try:
        with zipfile.ZipFile(jar) as z:
            data = json.loads(z.read("version.json"))
        wv = data.get("world_version")
        return (int(wv) if wv is not None else None), data.get("id")
    except (zipfile.BadZipFile, OSError, KeyError, ValueError):
        return None, None


def dataversion_table() -> dict[str, int]:
    text = resources.files("img2schem.palette").joinpath("data/dataversions.yaml").read_text(encoding="utf-8")
    return {str(k): int(v) for k, v in (yaml.safe_load(text) or {}).items()}


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
    data_version: int | None = None
    dv_source = "unknown"
    if client_jar:
        data_version, jar_id = world_version_from_jar(client_jar)
        if data_version is not None:
            dv_source = "jar"
        if mc_version is None and jar_id:
            mc_version = jar_id
    else:
        warnings.append(
            f"vanilla client jar for {mc_version or '?'} not found; launch that version once from the launcher (RI.3)"
        )
    if data_version is None and mc_version:
        data_version = dataversion_table().get(mc_version)
        dv_source = "table" if data_version is not None else "unknown"
    if data_version is None:
        warnings.append(f"unknown DataVersion for {mc_version or '?'}; add it to dataversions.yaml")

    worldedit = any(m.id == "worldedit" for m in mods)
    return InstanceInfo(
        name=name,
        launcher=launcher,
        game_dir=str(game_dir),
        mc_version=mc_version,
        loader=loader or "unknown",
        loader_version=loader_version,
        data_version=data_version,
        data_version_source=dv_source,  # type: ignore[arg-type]
        client_jar=str(client_jar) if client_jar else None,
        mods=mods,
        worldedit=worldedit,
        schematics_dir=str(game_dir / "config" / "worldedit" / "schematics"),
        warnings=warnings,
    )
