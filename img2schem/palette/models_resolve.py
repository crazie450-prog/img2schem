"""RP.4–RP.5: blockstate -> model(s) -> parent chain, and the property/value sets a block accepts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from img2schem.palette.sources import AssetFS

MAX_PARENT_DEPTH = 16


def model_path(ref: str) -> str:
    """``minecraft:block/stone`` (or ``block/stone``) -> ``assets/minecraft/models/block/stone.json``."""
    ns, _, p = ref.partition(":") if ":" in ref else ("minecraft", "", ref)
    return f"assets/{ns}/models/{p}.json"


def short_name(ref: str) -> str:
    """Model ref without namespace or directories: ``minecraft:block/cube_all`` -> ``cube_all``."""
    return ref.split(":", 1)[-1].rsplit("/", 1)[-1]


@dataclass
class ResolvedModel:
    ref: str
    parents: list[str] = field(default_factory=list)  # nearest parent first
    elements: list[dict[str, Any]] | None = None
    textures: dict[str, str] = field(default_factory=dict)
    builtin: str | None = None  # e.g. "builtin/entity"
    missing: bool = False


def resolve_model(fs: AssetFS, ref: str) -> ResolvedModel:
    out = ResolvedModel(ref)
    textures: dict[str, str] = {}
    cur: str | None = ref
    depth = 0
    first = True
    while cur and depth < MAX_PARENT_DEPTH:
        if cur.split(":", 1)[-1].startswith("builtin/"):
            out.builtin = cur.split(":", 1)[-1]
            break
        m = fs.read_json(model_path(cur))
        if not isinstance(m, dict):
            out.missing = out.missing or first
            break
        for k, v in (m.get("textures") or {}).items():
            textures.setdefault(k, v)  # child definitions win
        if out.elements is None and isinstance(m.get("elements"), list):
            out.elements = m["elements"]
        parent = m.get("parent")
        if parent:
            out.parents.append(parent)
        cur = parent
        depth += 1
        first = False
    out.textures = textures
    return out


@dataclass
class BlockstateInfo:
    properties: dict[str, set[str]]
    model_refs: list[str]  # every model referenced, in file order, deduplicated


def _model_refs(value: Any) -> list[str]:
    """A variant/apply value is a model object or a list of weighted models."""
    items = value if isinstance(value, list) else [value]
    return [i["model"] for i in items if isinstance(i, dict) and isinstance(i.get("model"), str)]


def _when_props(when: Any, props: dict[str, set[str]]) -> None:
    if not isinstance(when, dict):
        return
    for k, v in when.items():
        if k in ("OR", "AND") and isinstance(v, list):
            for sub in v:
                _when_props(sub, props)
        else:
            vals = str(v).lower() if isinstance(v, bool) else str(v)
            props.setdefault(k, set()).update(vals.split("|"))


def parse_blockstate(data: Any) -> BlockstateInfo:
    """Raises ValueError if ``data`` is not a usable blockstate definition."""
    if not isinstance(data, dict):
        raise ValueError("blockstate is not a JSON object")
    props: dict[str, set[str]] = {}
    refs: list[str] = []
    if isinstance(data.get("variants"), dict):
        for key, value in data["variants"].items():
            if key and key != "normal":
                for pair in key.split(","):
                    k, _, v = pair.partition("=")
                    props.setdefault(k.strip(), set()).add(v.strip())
            refs.extend(_model_refs(value))
    elif isinstance(data.get("multipart"), list):
        for part in data["multipart"]:
            if not isinstance(part, dict):
                continue
            _when_props(part.get("when"), props)
            refs.extend(_model_refs(part.get("apply")))
    else:
        raise ValueError("blockstate has neither 'variants' nor 'multipart'")
    return BlockstateInfo(props, list(dict.fromkeys(refs)))
