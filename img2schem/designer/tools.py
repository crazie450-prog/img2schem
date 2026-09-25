"""Claude's tools (SOW §6.7): one ``add_<op>`` per DSL op, with input schemas generated from engine/ops.py,
plus editing, palette, inspection and render tools. ``DesignState`` executes them against an OpsDoc: every
change is validated, compiled and checked, and a change that fails is rolled back and reported as an error.
"""

from __future__ import annotations

import base64
import io
import json
import typing
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter, ValidationError

from img2schem.config import Budgets
from img2schem.engine.compiler import Compiled, CompileError, compile_ops
from img2schem.engine.ops import Op, OpsDoc
from img2schem.models import Issue, Palette, WorldPalette
from img2schem.palette.query import PaletteIndex
from img2schem.stages.preview import render_front, render_iso, render_side, render_top
from img2schem.stages.validate import check_build
from img2schem.util.color import hex_color

OP_CLASSES: tuple[type, ...] = typing.get_args(typing.get_args(Op)[0])
OP_ADAPTER: TypeAdapter[Op] = TypeAdapter(Op)
VIEWS = {"iso": render_iso, "front": render_front, "side": render_side, "top": render_top}


def _op_name(cls: type) -> str:
    return typing.get_args(cls.model_fields["op"].annotation)[0]  # type: ignore[attr-defined, no-any-return]


def _schema(cls: type) -> dict[str, Any]:
    s = cls.model_json_schema(by_alias=True)  # type: ignore[attr-defined]
    if "$ref" in s:  # recursive models (define) come back as a reference into $defs
        top = dict(s["$defs"][s.pop("$ref").split("/")[-1]])
        top["properties"] = dict(top["properties"])
        s = {**top, "$defs": s["$defs"]}
    s.pop("description", None)
    s["properties"].pop("op", None)
    s["required"] = [r for r in s.get("required", []) if r != "op"]
    if "ops" in s["properties"] and s["properties"]["ops"].get("type") == "array":  # define: nested ops
        s["properties"]["ops"] = {"type": "array", "minItems": 1, "items": {"type": "object"},
                                  "description": "Full op objects with their `op` field (any op except define), "
                                  "with the same fields as the add_ tools."}  # fmt: skip
        s.pop("$defs", None)
    return _untitled(s)  # type: ignore[no-any-return]


def _untitled(node: Any) -> Any:
    """Drop pydantic's generated ``title`` keys (noise in the prompt)."""
    if isinstance(node, dict):
        return {k: _untitled(v) for k, v in node.items() if not (k == "title" and isinstance(v, str))}
    if isinstance(node, list):
        return [_untitled(v) for v in node]
    return node


def tool_specs(render: bool = True) -> list[dict[str, Any]]:
    """Tool definitions, in a fixed order (the prompt cache depends on it)."""
    tools: list[dict[str, Any]] = []
    for cls in OP_CLASSES:
        doc = " ".join((cls.__doc__ or "").split())
        tools.append({"name": f"add_{_op_name(cls)}", "description": f"Add a `{_op_name(cls)}` op. {doc}",
                      "input_schema": _schema(cls)})  # fmt: skip
    obj = {"type": "object"}
    tools += [
        {"name": "replace_op", "description": "Replace the op with this id by `op` (a full op object with its `op` "
         "field, as the add_ tools take plus `op`), keeping its position in the build order.",
         "input_schema": {**obj, "properties": {"id": {"type": "string"}, "op": obj}, "required": ["id", "op"]}},
        {"name": "delete_op", "description": "Delete the op with this id.",
         "input_schema": {**obj, "properties": {"id": {"type": "string"}}, "required": ["id"]}},
        {"name": "set_style", "description": "Set material slots: {slot: block or $slot}, e.g. {\"wall\": "
         "\"minecraft:stonebrick\", \"roof.stairs\": \"minecraft:brick_stairs\"}. A null value removes the slot.",
         "input_schema": {**obj, "properties": {"slots": obj}, "required": ["slots"]}},
        {"name": "search_palette", "description": "Find usable blocks by words in their id or name, optionally "
         "only one shape (full_cube, stairs, slab, wall, fence, fence_gate, pane, door, trapdoor, log) or mod. "
         "Returns block ids with their true color. Use only block ids that palette tools returned.",
         "input_schema": {**obj, "properties": {"query": {"type": "string"}, "shape": {"type": "string"},
                                                "mod": {"type": "string"}, "n": {"type": "integer"}},
                          "required": ["query"]}},
        {"name": "get_family", "description": "The stairs, slab, wall, fence and fence gate that match a full "
         "block (what `$slot.stairs` etc. resolve to).",
         "input_schema": {**obj, "properties": {"block": {"type": "string"}}, "required": ["block"]}},
        {"name": "get_state_summary", "description": "The current style, every op (id, label, cells, bounds), "
         "the build's size and block counts, and open validator issues.",
         "input_schema": {**obj, "properties": {}}},
    ]  # fmt: skip
    if render:
        tools.append({"name": "render_views", "description": "Render the current build as images: `iso` (from the "
                      "north-west, above), `front` (from the north), `side` (from the west), `top`. Use it to "
                      "check massing and proportions; each image costs input tokens, so ask only for what you need.",
                      "input_schema": {**obj, "properties": {"views": {"type": "array", "items": {
                          "type": "string", "enum": list(VIEWS)}}}, "required": ["views"]}})  # fmt: skip
    tools.append({"name": "finish", "description": "Call when the build is done: a short summary for the owner.",
                  "input_schema": {**obj, "properties": {"summary": {"type": "string"}}, "required": ["summary"]}})
    for t in tools:
        t["eager_input_streaming"] = True  # streamed requests; inputs are validated here before use
    return tools


@dataclass
class ToolResult:
    content: str | list[dict[str, Any]]
    is_error: bool = False
    done: bool = False


@dataclass
class DesignState:
    doc: OpsDoc
    palette: Palette | None
    budgets: Budgets
    world: WorldPalette | None = None
    summary: str | None = None
    compiled: Compiled | None = None
    issues: list[Issue] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.index = PaletteIndex(self.palette) if self.palette else None
        if self.doc.ops:
            self._check(self.doc)

    # --------------------------------------------------------------- execution

    def execute(self, name: str, args: Any) -> ToolResult:
        if not isinstance(args, dict):
            return ToolResult(json.dumps({"INVALID_JSON": json.dumps(args)}), is_error=True)
        try:
            if name.startswith("add_"):
                return self._add(name.removeprefix("add_"), args)
            handler = getattr(self, f"_tool_{name}", None)
            if handler is None:
                return ToolResult(f"unknown tool {name!r}", is_error=True)
            return handler(args)  # type: ignore[no-any-return]
        except (ValidationError, ValueError, KeyError, TypeError) as e:
            return ToolResult(f"{type(e).__name__}: {e}", is_error=True)

    def _add(self, kind: str, args: dict[str, Any]) -> ToolResult:
        op = OP_ADAPTER.validate_python({**args, "op": kind})
        if any(o.id == op.id for o in self.doc.ops):
            return ToolResult(f"an op with id {op.id!r} exists; pick a new id or use replace_op", is_error=True)
        return self._commit([*self.doc.ops, op], self.doc.style, op.id)

    def _tool_replace_op(self, args: dict[str, Any]) -> ToolResult:
        i = self._find(args["id"])
        op = OP_ADAPTER.validate_python(args["op"])
        ops = list(self.doc.ops)
        ops[i] = op
        return self._commit(ops, self.doc.style, op.id)

    def _tool_delete_op(self, args: dict[str, Any]) -> ToolResult:
        i = self._find(args["id"])
        return self._commit([o for j, o in enumerate(self.doc.ops) if j != i], self.doc.style, None)

    def _tool_set_style(self, args: dict[str, Any]) -> ToolResult:
        style = dict(self.doc.style)
        for k, v in dict(args["slots"]).items():
            if v is None:
                style.pop(k, None)
            else:
                style[str(k)] = str(v)
        return self._commit(list(self.doc.ops), style, None)

    def _tool_search_palette(self, args: dict[str, Any]) -> ToolResult:
        if self.palette is None:
            return ToolResult("no palette is loaded; use vanilla minecraft: blocks", is_error=True)
        words = str(args["query"]).lower().split()
        shape, mod, n = args.get("shape"), args.get("mod"), min(int(args.get("n") or 20), 50)
        hits = []
        for b in self.palette.blocks.values():
            if (shape and b.shape != shape) or (mod and b.mod.lower() != str(mod).lower()):
                continue
            for v in b.usable():
                if all(w in f"{v.block} {v.display}".lower() for w in words):
                    color = v.face_rgb or v.rgb
                    hits.append({"block": v.block, "name": v.display, "shape": b.shape,
                                 "color": hex_color(color) if color else None})  # fmt: skip
        return ToolResult(json.dumps({"results": hits[:n], "more": max(0, len(hits) - n)}))

    def _tool_get_family(self, args: dict[str, Any]) -> ToolResult:
        if self.index is None:
            return ToolResult("no palette is loaded", is_error=True)
        if self.index.usable(args["block"]) is None:
            return ToolResult(f"{args['block']} is not a usable block; find one with search_palette", is_error=True)
        return ToolResult(json.dumps(self.index.family(args["block"])))

    def _tool_get_state_summary(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(json.dumps(self.state_summary()))

    def _tool_render_views(self, args: dict[str, Any]) -> ToolResult:
        if self.compiled is None:
            return ToolResult("nothing built yet", is_error=True)
        content: list[dict[str, Any]] = []
        for view in list(args["views"])[:4]:
            if view not in VIEWS:
                return ToolResult(f"unknown view {view!r} (use {', '.join(VIEWS)})", is_error=True)
            img = VIEWS[view](self.compiled.grid, 6, self.palette)
            img.thumbnail((1200, 1200))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            content += [{"type": "text", "text": f"{view} view"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                     "data": base64.standard_b64encode(buf.getvalue()).decode()}}]
        return ToolResult(content)  # fmt: skip

    def _tool_finish(self, args: dict[str, Any]) -> ToolResult:
        self.summary = str(args.get("summary", ""))
        return ToolResult("done", done=True)

    # --------------------------------------------------------------- helpers

    def _find(self, op_id: str) -> int:
        for i, o in enumerate(self.doc.ops):
            if o.id == op_id:
                return i
        raise ValueError(f"no op with id {op_id!r}")

    def _check(self, doc: OpsDoc) -> None:
        compiled = compile_ops(doc, self.index, self.budgets.hard_max_total)
        grid = compiled.grid.compact()
        issues = check_build(grid, compiled.labels, doc.style, self.budgets, self.palette, self.world)
        self.compiled = Compiled(grid, compiled.labels, compiled.op_index, compiled.origin, compiled.summaries)
        self.issues = issues

    def _commit(self, ops: list[Op], style: dict[str, str], op_id: str | None) -> ToolResult:
        """Validate and compile the candidate doc; keep it only if it compiles without errors."""
        doc = OpsDoc.model_validate({"version": self.doc.version, "style": style,
                                     "ops": [o.model_dump(by_alias=True) for o in ops]})  # fmt: skip
        before = (self.doc, self.compiled, self.issues)
        try:
            self._check(doc)
        except CompileError as e:
            return ToolResult(str(e), is_error=True)
        errors = [i for i in self.issues if i.severity == "error"]
        if errors:
            self.doc, self.compiled, self.issues = before
            return ToolResult("rolled back, the build would not validate: "
                              + "; ".join(f"{i.rule} {i.message}" for i in errors[:5]), is_error=True)  # fmt: skip
        self.doc = doc
        out: dict[str, Any] = {"ok": True}
        if op_id and self.compiled:
            s = next(s for s in self.compiled.summaries if s.id == op_id)
            out["op"] = {"id": s.id, "cells": s.cells, "overwritten": s.overwritten, "bounds": s.bounds,
                         "blocks": dict(sorted(s.blocks.items(), key=lambda kv: -kv[1])[:6])}  # fmt: skip
        out["build"] = self._totals()
        out["issues"] = [f"{i.severity} {i.rule}: {i.message}" for i in self.issues if i.severity != "info"][:10]
        return ToolResult(json.dumps(out))

    def _totals(self) -> dict[str, Any]:
        if self.compiled is None:
            return {"ops": len(self.doc.ops), "blocks": 0}
        g = self.compiled.grid
        return {"ops": len(self.doc.ops), "size_xyz": list(g.shape), "blocks": g.nonair(),
                "design_origin_in_grid": list(self.compiled.origin)}  # fmt: skip

    def state_summary(self) -> dict[str, Any]:
        ops = []
        by_id = {s.id: s for s in self.compiled.summaries} if self.compiled else {}
        for o in self.doc.ops:
            s = by_id.get(o.id)
            ops.append({"id": o.id, "op": o.op, "label": o.label, "cells": s.cells if s else 0,
                        "bounds": s.bounds if s else None})  # fmt: skip
        counts = self.compiled.grid.counts() if self.compiled else {}
        return {"style": self.doc.style, "ops": ops, "build": self._totals(),
                "top_blocks": dict(sorted(counts.items(), key=lambda kv: -kv[1])[:12]),
                "issues": [f"{i.severity} {i.rule}: {i.message}" for i in self.issues][:20]}  # fmt: skip
