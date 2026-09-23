"""RI.1: find Minecraft instances from the vanilla launcher, CurseForge, Modrinth App and Prism.

Launcher paths and metadata formats below are best-known defaults and must be verified on the owner's
machine (recorded in docs/DECISIONS.md). Each ``discover_<launcher>`` takes its root so tests can point
at fixture directories.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from img2schem.instance.detect import detect_instance, loader_from_version_id
from img2schem.models import InstanceInfo, Loader


def _home() -> Path:
    return Path.home()


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming"))


def default_roots() -> dict[str, list[Path]]:
    h = _home()
    if sys.platform == "win32":
        a = _appdata()
        return {
            "vanilla": [a / ".minecraft"],
            "curseforge": [h / "curseforge" / "minecraft"],
            "modrinth": [a / "ModrinthApp", a / "com.modrinth.theseus"],
            "prism": [a / "PrismLauncher"],
        }
    if sys.platform == "darwin":
        s = h / "Library" / "Application Support"
        return {
            "vanilla": [s / "minecraft"],
            "curseforge": [h / "Documents" / "curseforge" / "minecraft"],
            "modrinth": [s / "ModrinthApp", s / "com.modrinth.theseus"],
            "prism": [s / "PrismLauncher"],
        }
    share = h / ".local" / "share"
    return {
        "vanilla": [h / ".minecraft"],
        "curseforge": [h / "curseforge" / "minecraft"],
        "modrinth": [share / "ModrinthApp", share / "com.modrinth.theseus"],
        "prism": [share / "PrismLauncher"],
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _version_key(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", v))


def _is_release(v: str) -> bool:
    return re.fullmatch(r"\d+\.\d+(\.\d+)?", v) is not None


def vanilla_jar(mc_root: Path, mc_version: str | None) -> list[Path]:
    return [mc_root / "versions" / mc_version / f"{mc_version}.jar"] if mc_version else []


# ---------------------------------------------------------------- vanilla launcher


def discover_vanilla(root: Path) -> list[InstanceInfo]:
    data = _load_json(root / "launcher_profiles.json")
    if not isinstance(data, dict):
        return []
    versions_dir = root / "versions"
    releases = sorted(
        (p.name for p in versions_dir.iterdir() if p.is_dir() and _is_release(p.name)) if versions_dir.is_dir() else [],
        key=_version_key,
    )
    out: list[InstanceInfo] = []
    for pid, prof in sorted((data.get("profiles") or {}).items()):
        vid = prof.get("lastVersionId") or ""
        if vid == "latest-release":
            vid = releases[-1] if releases else ""
        elif vid.startswith("latest-"):
            continue  # snapshots are not supported targets
        if not vid:
            continue
        vjson = _load_json(versions_dir / vid / f"{vid}.json") or {}
        mc_version = vjson.get("inheritsFrom") or vid
        loader, loader_version = loader_from_version_id(vid)
        game_dir = Path(prof["gameDir"]) if prof.get("gameDir") else root
        out.append(
            detect_instance(
                name=prof.get("name") or vid or pid,
                launcher="vanilla",
                game_dir=game_dir,
                mc_version=mc_version,
                loader=loader,
                loader_version=loader_version,
                jar_candidates=vanilla_jar(root, mc_version),
            )
        )
    return out


# ---------------------------------------------------------------- CurseForge

_CF_LOADER_TYPES: dict[int, Loader] = {1: "forge", 4: "fabric", 5: "quilt", 6: "neoforge"}


def discover_curseforge(root: Path) -> list[InstanceInfo]:
    inst_root = root / "Instances"
    if not inst_root.is_dir():
        return []
    out: list[InstanceInfo] = []
    for d in sorted(p for p in inst_root.iterdir() if p.is_dir()):
        meta = _load_json(d / "minecraftinstance.json")
        if not isinstance(meta, dict):
            continue
        mc_version = meta.get("gameVersion")
        base = meta.get("baseModLoader") or {}
        loader: Loader | None = _CF_LOADER_TYPES.get(base.get("type") or -1)
        loader_version = None
        if base.get("name"):
            guessed, loader_version = loader_from_version_id(base["name"])
            loader = loader or guessed
        out.append(
            detect_instance(
                name=meta.get("name") or d.name,
                launcher="curseforge",
                game_dir=d,
                mc_version=mc_version,
                loader=loader,
                loader_version=loader_version,
                jar_candidates=vanilla_jar(root / "Install", mc_version),
            )
        )
    return out


# ---------------------------------------------------------------- Modrinth App

_MODRINTH_LOADERS: dict[str, Loader] = {
    "vanilla": "vanilla",
    "fabric": "fabric",
    "quilt": "quilt",
    "forge": "forge",
    "neoforge": "neoforge",
}


def _modrinth_db_profiles(root: Path) -> dict[str, dict[str, Any]]:
    """Newer Modrinth App versions keep profiles in app.db (SQLite) instead of profile.json."""
    db = root / "app.db"
    if not db.is_file():
        return {}
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT path, name, game_version, mod_loader, mod_loader_version FROM profiles"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    return {r[0]: {"name": r[1], "game_version": r[2], "loader": r[3], "loader_version": r[4]} for r in rows}


def discover_modrinth(root: Path) -> list[InstanceInfo]:
    prof_root = root / "profiles"
    if not prof_root.is_dir():
        return []
    db_profiles = _modrinth_db_profiles(root)
    out: list[InstanceInfo] = []
    for d in sorted(p for p in prof_root.iterdir() if p.is_dir()):
        meta: dict[str, Any] = db_profiles.get(d.name, {})
        pj = _load_json(d / "profile.json")
        if isinstance(pj, dict):
            m = pj.get("metadata") or {}
            lv = m.get("loader_version")
            meta = {
                "name": m.get("name"),
                "game_version": m.get("game_version"),
                "loader": m.get("loader"),
                "loader_version": lv.get("id") if isinstance(lv, dict) else lv,
            }
        mc_version = meta.get("game_version")
        out.append(
            detect_instance(
                name=meta.get("name") or d.name,
                launcher="modrinth",
                game_dir=d,
                mc_version=mc_version,
                loader=_MODRINTH_LOADERS.get(str(meta.get("loader") or "").lower()),
                loader_version=meta.get("loader_version"),
                jar_candidates=vanilla_jar(root / "meta", mc_version),
            )
        )
    return out


# ---------------------------------------------------------------- Prism Launcher

_PRISM_UIDS: dict[str, Loader] = {
    "net.fabricmc.fabric-loader": "fabric",
    "org.quiltmc.quilt-loader": "quilt",
    "net.neoforged": "neoforge",
    "net.minecraftforge": "forge",
}


def _read_cfg(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.startswith("["):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def discover_prism(root: Path) -> list[InstanceInfo]:
    inst_root = root / "instances"
    if not inst_root.is_dir():
        return []
    out: list[InstanceInfo] = []
    for d in sorted(p for p in inst_root.iterdir() if p.is_dir()):
        pack = _load_json(d / "mmc-pack.json")
        if not isinstance(pack, dict):
            continue
        mc_version = None
        loader: Loader = "vanilla"
        loader_version = None
        for comp in pack.get("components") or []:
            uid = comp.get("uid")
            if uid == "net.minecraft":
                mc_version = comp.get("version") or comp.get("cachedVersion")
            elif uid in _PRISM_UIDS:
                loader = _PRISM_UIDS[uid]
                loader_version = comp.get("version") or comp.get("cachedVersion")
        game_dir = next((d / g for g in (".minecraft", "minecraft") if (d / g).is_dir()), d / ".minecraft")
        jars = []
        if mc_version:
            jars.append(
                root / "libraries" / "com" / "mojang" / "minecraft" / mc_version / f"minecraft-{mc_version}-client.jar"
            )
        out.append(
            detect_instance(
                name=_read_cfg(d / "instance.cfg").get("name") or d.name,
                launcher="prism",
                game_dir=game_dir,
                mc_version=mc_version,
                loader=loader,
                loader_version=loader_version,
                jar_candidates=jars,
            )
        )
    return out


# ---------------------------------------------------------------- all + user path

DISCOVERERS = {
    "vanilla": discover_vanilla,
    "curseforge": discover_curseforge,
    "modrinth": discover_modrinth,
    "prism": discover_prism,
}


def discover_all(roots: dict[str, list[Path]] | None = None) -> list[InstanceInfo]:
    roots = roots or default_roots()
    out: list[InstanceInfo] = []
    for launcher, fn in DISCOVERERS.items():
        for root in roots.get(launcher, []):
            if root.is_dir():
                out.extend(fn(root))
    return out


def detect_path(path: Path) -> InstanceInfo:
    """RI.1: a user-supplied path — an instance folder from any launcher, or a bare game directory."""
    path = path.expanduser().resolve()
    # Launcher instance folders: look for their metadata next to or above the game dir.
    for cand in (path, path.parent):
        if (cand / "mmc-pack.json").is_file():
            return next(
                (i for i in discover_prism(cand.parent.parent) if Path(i.game_dir).resolve().parent == cand),
                _bare(path),
            )
        if (cand / "minecraftinstance.json").is_file():
            return next(
                (i for i in discover_curseforge(cand.parent.parent) if Path(i.game_dir).resolve() == cand), _bare(path)
            )
        if (cand / "profile.json").is_file():
            return next(
                (i for i in discover_modrinth(cand.parent.parent) if Path(i.game_dir).resolve() == cand), _bare(path)
            )
    return _bare(path)


def _bare(path: Path) -> InstanceInfo:
    releases = sorted(
        (p.name for p in (path / "versions").iterdir() if p.is_dir() and _is_release(p.name))
        if (path / "versions").is_dir()
        else [],
        key=_version_key,
    )
    mc_version = releases[-1] if releases else None
    info = detect_instance(
        name=path.name,
        launcher="path",
        game_dir=path,
        mc_version=mc_version,
        jar_candidates=vanilla_jar(path, mc_version) + vanilla_jar(default_roots()["vanilla"][0], mc_version),
    )
    if mc_version is None:
        info.warnings.append("MC version not detectable from a bare path; the client jar is needed (RI.3)")
    return info


def resolve_instance(ref: str, roots: dict[str, list[Path]] | None = None) -> InstanceInfo:
    """Match ``ref`` against discovered instance names (``name`` or ``launcher:name``), else treat as a path."""
    found = discover_all(roots)
    matches = [i for i in found if ref in (i.name, f"{i.launcher}:{i.name}")]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise LookupError(f"{ref!r} is ambiguous; use launcher:name ({[f'{i.launcher}:{i.name}' for i in matches]})")
    p = Path(ref)
    if p.exists():
        return detect_path(p)
    raise LookupError(f"no instance named {ref!r} and no such path")
