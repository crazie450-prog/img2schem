"""`palette build`: instance -> palette.json + palette_report.json in the cache (Phase 0: RP.1–RP.6, RP.15–16).

Colors, families, tags, tiers and the atlas arrive in Phase 1.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

from img2schem.models import InstanceInfo, Palette, PaletteBlock, PaletteReport
from img2schem.palette.classify import classify, is_code_rendered
from img2schem.palette.models_resolve import parse_blockstate, resolve_model
from img2schem.palette.sources import AssetFS, collect_sources, enabled_resource_packs

EXTRACTOR_VERSION = "0.1"
_BLOCKSTATE_RE = re.compile(r"^assets/([^/]+)/blockstates/(.+)\.json$")


def cache_key(instance: InstanceInfo) -> str:
    """RP.15: hash over jar/pack names + sizes + mtimes and the extractor version."""
    h = hashlib.sha256(f"extractor={EXTRACTOR_VERSION}\n".encode())

    def add(p: Path) -> None:
        try:
            st = p.stat()
            h.update(f"{p.name}|{st.st_size}|{st.st_mtime_ns}\n".encode())
        except OSError:
            h.update(f"{p.name}|missing\n".encode())

    if instance.client_jar:
        add(Path(instance.client_jar))
    for m in instance.mods:
        add(Path(instance.game_dir) / "mods" / m.jar)
    for pack in enabled_resource_packs(Path(instance.game_dir)):
        add(pack)
        if pack.is_dir():
            for f in sorted(pack.rglob("*")):
                if f.is_file():
                    add(f)
    return h.hexdigest()[:16]


def palette_dir(cache_dir: Path, key: str) -> Path:
    return cache_dir / "palettes" / key


def extract(instance: InstanceInfo) -> tuple[Palette, PaletteReport]:
    errors: list[dict[str, str]] = []
    sources = collect_sources(instance, errors)
    fs = AssetFS(sources, errors)
    # RP.3: blocks are defined by vanilla/mod jars; resource packs can override a blockstate but not add blocks.
    real_blocks = {path for s in sources if s.kind != "resourcepack" for path in s.files if _BLOCKSTATE_RE.match(path)}
    palette = Palette(
        extractor_version=EXTRACTOR_VERSION,
        cache_key=cache_key(instance),
        instance_name=instance.name,
        mc_version=instance.mc_version,
    )
    for path in sorted(real_blocks):
        m = _BLOCKSTATE_RE.match(path)
        assert m
        ns, name = m.group(1), m.group(2)
        block_id = f"{ns}:{name}"
        data = fs.read_json(path)
        if data is None:
            continue  # already logged as a parse error
        try:
            info = parse_blockstate(data)
        except ValueError as e:
            src = fs.source_of(path)
            errors.append({"file": f"{src.label if src else '?'}:{path}", "message": str(e)})
            continue
        models = [resolve_model(fs, ref) for ref in info.model_refs]
        flags = ["code_rendered"] if is_code_rendered(models) else []
        src = fs.source_of(path)
        palette.blocks[block_id] = PaletteBlock(
            id=block_id,
            mod=ns,
            source=src.label if src else "?",
            shape=classify(models),
            properties={k: sorted(v) for k, v in sorted(info.properties.items())},
            default_state=block_id,  # partial states; unset properties take in-game defaults (RE.4)
            flags=flags,
        )
    report = PaletteReport(
        blocks_per_mod=dict(sorted(Counter(b.mod for b in palette.blocks.values()).items())),
        blocks_per_shape=dict(sorted(Counter(b.shape for b in palette.blocks.values()).items())),
        code_rendered=sorted(b.id for b in palette.blocks.values() if "code_rendered" in b.flags),
        excluded_per_flag=dict(Counter(f for b in palette.blocks.values() for f in b.flags)),
        parse_errors=errors,
    )
    return palette, report


def build_palette(instance: InstanceInfo, cache_dir: Path, force: bool = False) -> tuple[Palette, Path, bool]:
    """Returns ``(palette, directory, cache_hit)``."""
    key = cache_key(instance)
    d = palette_dir(cache_dir, key)
    pj = d / "palette.json"
    if pj.is_file() and not force:
        return Palette.model_validate_json(pj.read_text(encoding="utf-8")), d, True
    palette, report = extract(instance)
    d.mkdir(parents=True, exist_ok=True)
    pj.write_text(palette.model_dump_json(indent=1), encoding="utf-8")
    (d / "palette_report.json").write_text(report.model_dump_json(indent=1), encoding="utf-8")
    (d / "instance.json").write_text(instance.model_dump_json(indent=1), encoding="utf-8")
    return palette, d, False
