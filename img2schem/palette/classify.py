"""RP.6: shape classification from the parent model chain, falling back to element geometry."""

from __future__ import annotations

from collections.abc import Callable

from img2schem.models import Shape
from img2schem.palette.models_resolve import ResolvedModel, short_name

# Most specific first: a slab's "double" variant points at a cube model, but the block is still a slab.
_RULES: list[tuple[Shape, Callable[[str], bool]]] = [
    ("stairs", lambda n: n in ("stairs", "inner_stairs", "outer_stairs")),
    ("slab", lambda n: n in ("slab", "slab_top")),
    ("wall", lambda n: n.startswith("template_wall_")),
    ("fence_gate", lambda n: n.startswith("template_fence_gate")),
    ("fence", lambda n: n.startswith("fence_")),
    ("pane", lambda n: n.startswith("template_glass_pane_")),
    ("trapdoor", lambda n: n.startswith("template_") and "trapdoor" in n),
    ("door", lambda n: n.startswith("door_")),
    ("column", lambda n: n.startswith("cube_column")),
    ("full_cube", lambda n: n.startswith("cube")),
]


def _is_unit_cube(model: ResolvedModel) -> bool:
    els = model.elements or []
    if len(els) != 1:
        return False
    e = els[0]
    return (
        [float(v) for v in e.get("from", [])] == [0, 0, 0]
        and [float(v) for v in e.get("to", [])] == [16, 16, 16]
        and len(e.get("faces") or {}) == 6
    )


def classify(models: list[ResolvedModel]) -> Shape:
    names = {short_name(p) for m in models for p in m.parents}
    for shape, rule in _RULES:
        if any(rule(n) for n in names):
            return shape
    if models and _is_unit_cube(models[0]):
        return "full_cube"
    return "other"


def is_code_rendered(models: list[ResolvedModel]) -> bool:
    """No usable JSON geometry: missing models, builtin/* parents, or no elements anywhere (RP.4)."""
    if not models:
        return True
    return all(m.missing or m.builtin is not None or not m.elements for m in models)
