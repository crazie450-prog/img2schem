"""The local web UI's server (SOW §6.9, Phase 3): REST for builds, versions and exports, and a WebSocket that
runs a design or edit and streams its progress. It wraps the same stages as the CLI (designer/runner.py,
stages/build.py) and serves the built UI from ./static. Bind it to 127.0.0.1 only (RU.10): the API key stays in
this process and never reaches the browser."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from img2schem.config import Settings, load_settings
from img2schem.designer import runner
from img2schem.designer.history import History
from img2schem.designer.tools import DesignState
from img2schem.engine.compiler import CompileError
from img2schem.engine.ops import OpsDoc
from img2schem.instance.discover import resolve_instance
from img2schem.instance.world import read_world_palette, resolve_world
from img2schem.models import InstanceInfo, Palette, WorldPalette
from img2schem.server.grid import grid_payload
from img2schem.stages.build import BuildFailed, build_outputs
from img2schem.stages.ingest import IngestError, ingest

STATIC = Path(__file__).parent / "static"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
GRID_EVERY_S = 0.25  # at most this often during a run


class Context:
    """Settings, palette, world and instance, loaded once and reloaded when their files change."""

    def __init__(self, builds: Path, out: Path):
        self.builds, self.out = builds, out
        self._palette: tuple[str, float, Palette | None] | None = None

    @property
    def settings(self) -> Settings:
        return load_settings()

    def palette(self) -> Palette | None:
        path = self.settings.palette
        if not path or not Path(path).is_file():
            return None
        mtime = Path(path).stat().st_mtime
        if self._palette is None or self._palette[:2] != (path, mtime):
            self._palette = (path, mtime, Palette.model_validate_json(Path(path).read_text(encoding="utf-8")))
        return self._palette[2]

    def instance(self) -> InstanceInfo | None:
        s = self.settings
        if not s.instance:
            return None
        try:
            return resolve_instance(s.instance)
        except LookupError:
            return None

    def world(self) -> WorldPalette | None:
        inst, s = self.instance(), self.settings
        if not inst or not s.world:
            return None
        try:
            return read_world_palette(resolve_world(Path(inst.game_dir), s.world))
        except (LookupError, ValueError, OSError):
            return None

    def ops_file(self, name: str) -> Path:
        if not NAME.match(name):
            raise HTTPException(400, "build names use letters, digits, - and _ (up to 64)")
        return self.builds / f"{name}.ops.json"

    def run_dir(self, name: str) -> Path:
        return self.out / f"{name}_{time.strftime('%Y%m%d-%H%M%S')}"


def _issues(state: DesignState) -> list[dict[str, Any]]:
    return [i.model_dump() for i in state.issues]


def build_info(ctx: Context, name: str) -> dict[str, Any]:
    ops_file = ctx.ops_file(name)
    if not ops_file.is_file():
        raise HTTPException(404, f"no build {name!r}")
    hist = History(ops_file)
    text = ops_file.read_text(encoding="utf-8")
    info: dict[str, Any] = {"name": name, "ops": text, "current": hist.current, "versions": hist.versions,
                            "cost_usd": round(sum(v.get("cost_usd") or 0 for v in hist.versions), 4)}  # fmt: skip
    try:
        state = DesignState(OpsDoc.model_validate_json(text), ctx.palette(), ctx.settings.budgets, ctx.world())
        info["issues"] = _issues(state)
    except (ValueError, CompileError) as e:
        info["issues"] = [{"rule": "compile", "severity": "error", "message": str(e)}]
    return info


class OpsBody(BaseModel):
    text: str


def create_app(builds: Path = Path("builds"), out: Path = Path("out")) -> FastAPI:
    app = FastAPI(title="img2schem", docs_url=None, redoc_url=None)
    ctx = Context(builds, out)
    app.state.ctx = ctx

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        s = ctx.settings
        inst = ctx.instance()
        return {
            "model": s.claude.model,
            "budgets": {k: v.model_dump() for k, v in s.claude.budget_usd.items()},
            "api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "instance": f"{inst.name} (MC {inst.mc_version}, {inst.loader})" if inst else None,
            "worldedit": bool(inst and inst.worldedit),
            "world": s.world,
            "palette": ctx.palette() is not None,
        }

    @app.get("/api/builds")
    def builds_list() -> list[dict[str, Any]]:
        out_list = []
        for f in sorted(ctx.builds.glob("*.ops.json"), key=lambda p: -p.stat().st_mtime):
            hist = History(f)
            out_list.append({"name": f.name.removesuffix(".ops.json"), "current": hist.current,
                             "versions": len(hist.versions), "updated": f.stat().st_mtime,
                             "cost_usd": round(sum(v.get("cost_usd") or 0 for v in hist.versions), 4)})  # fmt: skip
        return out_list

    @app.get("/api/builds/{name}")
    def build_get(name: str) -> dict[str, Any]:
        return build_info(ctx, name)

    @app.get("/api/builds/{name}/grid")
    def build_grid(name: str) -> dict[str, Any]:
        ops_file = ctx.ops_file(name)
        if not ops_file.is_file():
            raise HTTPException(404, f"no build {name!r}")
        try:
            state = DesignState(OpsDoc.model_validate_json(ops_file.read_text(encoding="utf-8")), ctx.palette(),
                                ctx.settings.budgets)  # fmt: skip
        except (ValueError, CompileError) as e:
            raise HTTPException(422, str(e)) from None
        if state.compiled is None:
            return {"size": [0, 0, 0], "blocks": [], "cells": [], "total": 0, "counts": {}}
        return grid_payload(state.compiled.grid, ctx.palette())

    @app.put("/api/builds/{name}/ops")
    def build_save(name: str, body: OpsBody) -> dict[str, Any]:
        """The text editor's save: a valid, compiling ops.json becomes a new version."""
        ops_file = ctx.ops_file(name)
        try:
            raw = json.loads(body.text)
        except json.JSONDecodeError as e:
            raise HTTPException(400, {"message": f"JSON: {e.msg}", "line": e.lineno, "col": e.colno}) from None
        try:
            doc = OpsDoc.model_validate(raw)
            state = DesignState(doc, ctx.palette(), ctx.settings.budgets, ctx.world())
        except ValidationError as e:
            raise HTTPException(400, {"message": "; ".join(
                f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()[:8])}) from None
        except (ValueError, CompileError) as e:
            raise HTTPException(400, {"message": str(e)}) from None
        errors = [i for i in state.issues if i.severity == "error"]
        if errors:
            raise HTTPException(400, {"message": "; ".join(f"{i.rule} {i.message}" for i in errors)})
        text = doc.model_dump_json(by_alias=True, indent=1)
        hist = History(ops_file)
        hist.ensure_started()
        if not ops_file.is_file() or text != ops_file.read_text(encoding="utf-8"):
            hist.commit(text, kind="manual", instruction="edited in the ops editor")
        return build_info(ctx, name)

    @app.post("/api/builds/{name}/{step}")
    def build_step(name: str, step: str) -> dict[str, Any]:
        if step not in ("undo", "redo", "export"):
            raise HTTPException(404, f"unknown action {step!r}")
        ops_file = ctx.ops_file(name)
        if not ops_file.is_file():
            raise HTTPException(404, f"no build {name!r}")
        if step == "export":
            return export(ctx, name, copy=True)
        try:
            History(ops_file).step(-1 if step == "undo" else 1)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        return build_info(ctx, name)

    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                msg = await websocket.receive_json()
                await run_job(ctx, websocket, msg)
        except WebSocketDisconnect:
            pass

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        page = STATIC / "index.html"
        if page.is_file():
            return page.read_text(encoding="utf-8")
        return "<h1>img2schem</h1><p>The web UI is not built: <code>cd web; npm install; npm run build</code>.</p>"

    if (STATIC / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")
    return app


def export(ctx: Context, name: str, copy: bool) -> dict[str, Any]:
    """Compile the build's current version into a run folder (and the WorldEdit folder)."""
    ops_file = ctx.ops_file(name)
    doc = OpsDoc.model_validate_json(ops_file.read_text(encoding="utf-8"))
    try:
        built = build_outputs(doc, name, ctx.run_dir(name), settings=ctx.settings, palette=ctx.palette(),
                              world=ctx.world(), instance=ctx.instance(), copy=copy, ops_file=ops_file)  # fmt: skip
    except (CompileError, BuildFailed) as e:
        raise HTTPException(400, str(e)) from None
    return {"schematic": str(built.schematic), "copied_to": str(built.copied_to) if built.copied_to else None,
            "load": f"//schem load {name}" if built.copied_to else None, "dims": built.report["dims_wxhxl"],
            "blocks": built.report["nonair"],
            "issues": [i.model_dump() for i in built.issues]}  # fmt: skip


async def run_job(ctx: Context, websocket: WebSocket, msg: dict[str, Any]) -> None:
    """Run a design or edit in a worker thread and stream its events:
    {type: started | text | tool | applied | grid | critique | warning | done | exported | error}."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def emit(event: dict[str, Any] | None) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def worker() -> None:
        try:
            _work(ctx, msg, emit)
        except (runner.RunError, IngestError, ValueError) as e:
            emit({"type": "error", "message": str(e)})
        except HTTPException as e:
            emit({"type": "error", "message": str(e.detail)})
        except Exception as e:  # report anything else to the page instead of dying silently
            emit({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            emit(None)

    threading.Thread(target=worker, daemon=True).start()
    while (event := await queue.get()) is not None:
        await websocket.send_json(event)


def _work(ctx: Context, msg: dict[str, Any], emit: Any) -> None:
    action, name = msg.get("action"), str(msg.get("name") or "")
    ops_file = ctx.ops_file(name)
    budget = str(msg.get("budget") or "default")
    ctx.settings.claude.budget(budget)  # ValueError for an unknown budget
    run_dir = ctx.run_dir(name)
    last = [0.0]
    palette = ctx.palette()

    def changed(state: DesignState) -> None:
        now = time.monotonic()
        if state.compiled is not None and now - last[0] >= GRID_EVERY_S:
            last[0] = now
            emit({"type": "grid", "grid": grid_payload(state.compiled.grid, palette)})

    def tool(tool_name: str, args: Any, r: Any) -> None:
        emit({"type": "applied", "tool": tool_name, "id": args.get("id") if isinstance(args, dict) else None,
              "ok": not r.is_error, "error": str(r.content)[:300] if r.is_error else None})  # fmt: skip

    cb = runner.Callbacks(progress=lambda kind, text: emit({"type": kind, "text": text}),
                          warning=lambda m: emit({"type": "warning", "message": m}), tool=tool,
                          critique=lambda n: emit({"type": "critique", "n": n}), changed=changed)  # fmt: skip
    replay = Path(msg["replay"]) if msg.get("replay") else None
    emit({"type": "started", "action": action, "model": ctx.settings.claude.model, "budget": budget})
    if action == "design":
        photos = []
        for i, p in enumerate(msg.get("photos") or [], start=1):
            raw_dir = run_dir / f"upload_{i}"
            raw_dir.mkdir(parents=True, exist_ok=True)
            src = raw_dir / Path(str(p.get("name") or "photo.png")).name
            src.write_bytes(base64.b64decode(p["data"]))
            photos.append(ingest(src, run_dir / f"photo_{i}"))
        run = runner.design(name, str(msg.get("prompt") or ""), photos, settings=ctx.settings, palette=palette,
                            world=ctx.world(), out=run_dir, builds=ctx.builds, budget=budget, replay=replay,
                            critique_passes=msg.get("critique"), cb=cb,
                            sources=[str(p.get("name")) for p in msg.get("photos") or []])  # fmt: skip
    elif action == "edit":
        if not ops_file.is_file():
            raise ValueError(f"no build {name!r}")
        run = runner.edit(ops_file, str(msg.get("instruction") or ""), settings=ctx.settings, palette=palette,
                          world=ctx.world(), out=run_dir, budget=budget, replay=replay,
                          render=bool(msg.get("render")), cb=cb)  # fmt: skip
    else:
        raise ValueError(f"unknown action {action!r}")
    r = run.result
    if run.state.compiled is not None:
        emit({"type": "grid", "grid": grid_payload(run.state.compiled.grid, palette)})
    done = {"type": "done", "stopped": r.stopped, "turns": r.turns, "cost_usd": round(r.cost_usd, 4),
            "summary": r.summary, "version": run.version, "warnings": r.warnings}  # fmt: skip
    emit(done)
    if run.version is not None and msg.get("export", True):  # like the CLI: compile and copy to WorldEdit
        try:
            emit({"type": "exported", **export(ctx, name, copy=True)})
        except HTTPException as e:
            emit({"type": "warning", "message": f"export: {e.detail}"})
