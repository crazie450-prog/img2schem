"""Design and edit runs, shared by the CLI and the web server: the brief, the transport, the loop, the run
folder (ops.json, design.json, session.jsonl) and the build's version history. Output goes through callbacks."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from img2schem.config import Settings
from img2schem.designer.critique import critique_message, photo_brief
from img2schem.designer.history import History
from img2schem.designer.prompt import PROMPT_VERSION, system_prompt
from img2schem.designer.session import DesignResult, run_design
from img2schem.designer.tools import DesignState, ToolResult, tool_specs
from img2schem.designer.transport import LiveTransport, Progress, RecordingTransport, ReplayTransport, Transport
from img2schem.engine.ops import OpsDoc
from img2schem.models import Palette, WorldPalette


class RunError(RuntimeError):
    """The run could not start (no key, no SDK, bad input) or stopped on an API error (ops so far are kept)."""


@dataclass
class Callbacks:
    progress: Progress | None = None
    warning: Callable[[str], None] | None = None
    tool: Callable[[str, Any, ToolResult], None] | None = None
    critique: Callable[[int], None] | None = None  # a critique pass starts


@dataclass
class RunResult:
    result: DesignResult
    state: DesignState
    ops_path: Path  # in the run folder
    version: int | None  # the build's new version (None: nothing changed)


def make_transport(settings: Settings, out: Path, replay: Path | None) -> Transport:
    if replay:
        return ReplayTransport(replay)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RunError("ANTHROPIC_API_KEY is not set: copy .env.example to .env and fill it in")
    try:
        return RecordingTransport(LiveTransport(settings.claude.fallback_model), out / "session.jsonl")
    except ImportError:
        raise RunError('the Anthropic SDK is not installed: pip install -e ".[vlm]"') from None


def _run(state: DesignState, brief: str | list[dict[str, Any]], *, settings: Settings, out: Path, budget: str,
         replay: Path | None, render: bool, record: dict[str, Any], cb: Callbacks,
         critique: Callable[[int], list[dict[str, Any]]] | None = None,
         critique_passes: int = 0) -> tuple[DesignResult, Path]:  # fmt: skip
    limit = settings.claude.budget(budget)
    out.mkdir(parents=True, exist_ok=True)
    transport = make_transport(settings, out, replay)
    ops_path = out / f"{record['name']}.ops.json"
    try:
        result = run_design(state, brief, system_prompt(state.palette), tool_specs(render=render), settings.claude,
                            limit, transport, budget, cb.progress, cb.warning, critique, critique_passes,
                            cb.tool)  # fmt: skip
    except Exception as e:  # keep what was built before an API or network failure
        ops_path.write_text(state.doc.model_dump_json(by_alias=True, indent=1), encoding="utf-8")
        hint = ("\nhint: set ANTHROPIC_WORKSPACE_ID in .env (see .env.example), or use a key made inside a "
                "workspace") if "workspace" in str(e) else ""  # fmt: skip
        raise RunError(f"stopped: {type(e).__name__}: {e} (ops so far: {ops_path}){hint}") from e
    ops_path.write_text(state.doc.model_dump_json(by_alias=True, indent=1), encoding="utf-8")
    meta = {**record, "model": settings.claude.model, "prompt_version": PROMPT_VERSION, "budget": budget,
            **{k: v for k, v in vars(result).items() if k != "text"}, "cost_usd": round(result.cost_usd, 4)}
    (out / "design.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    return result, ops_path


def design(name: str, prompt: str, photos: list[Path], *, settings: Settings, palette: Palette | None,
           world: WorldPalette | None, out: Path, builds: Path, budget: str = "default",
           replay: Path | None = None, critique_passes: int | None = None, cb: Callbacks | None = None,
           sources: list[str] | None = None) -> RunResult:  # fmt: skip
    """``photos`` are already ingested images (``sources``: the owner's original files, for the record).
    Commits the build as a new version of ``builds/<name>``."""
    cb = cb or Callbacks()
    if not prompt and not photos:
        raise RunError("describe the build, or give a photo")
    passes = (2 if photos else 0) if critique_passes is None else critique_passes
    if passes and not photos:
        raise RunError("critique compares the build with a photo: add a photo")
    state = DesignState(OpsDoc(), palette, settings.budgets, world)
    brief: str | list[dict[str, Any]] = (
        photo_brief(photos, prompt) if photos else
        f"Design this build: {prompt}\n\nStart from nothing: set the style slots, build it with ops, check it "
        "with render_views, then call finish.")  # fmt: skip

    def critique_pass(n: int) -> list[dict[str, Any]]:
        assert state.compiled is not None
        if cb.critique:
            cb.critique(n)
        return critique_message(photos[0], state.compiled.grid, state.palette, n, passes, out / f"critique_{n}.png")

    record = {"name": name, "prompt": prompt, "photos": sources or [str(p) for p in photos]}
    result, ops_path = _run(state, brief, settings=settings, out=out, budget=budget, replay=replay, render=True,
                            record=record, cb=cb, critique=critique_pass if passes else None,
                            critique_passes=passes)  # fmt: skip
    version = None
    if state.doc.ops:
        hist = History(builds / f"{name}.ops.json")
        version = hist.commit(ops_path.read_text(encoding="utf-8"), kind="design",
                              instruction=prompt or ", ".join(Path(p).name for p in (sources or photos)), run=str(out),
                              cost_usd=round(result.cost_usd, 4), summary=result.summary)  # fmt: skip
    return RunResult(result, state, ops_path, version)


def edit(ops_file: Path, instruction: str, *, settings: Settings, palette: Palette | None,
         world: WorldPalette | None, out: Path, budget: str = "default", replay: Path | None = None,
         render: bool = False, cb: Callbacks | None = None) -> RunResult:  # fmt: skip
    """Claude changes the build as instructed; a change is committed as a new version."""
    cb = cb or Callbacks()
    try:
        doc = OpsDoc.model_validate_json(ops_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RunError(f"cannot read {ops_file}: {e}") from None
    name = ops_file.name.removesuffix(".json").removesuffix(".ops")
    state = DesignState(doc, palette, settings.budgets, world)
    before = doc.model_dump_json(by_alias=True, indent=1)
    issues = [f"{i.severity} {i.rule}: {i.message}" for i in state.issues if i.severity != "info"]
    brief = (
        f"Edit this existing build. The owner asks: {instruction}\n\n"
        f"Current ops.json:\n```json\n{doc.model_dump_json(by_alias=True, exclude_defaults=True)}\n```\n"
        f"Open validator issues: {json.dumps(issues) if issues else 'none'}\n\n"
        "Change only what the instruction asks for. Keep the other ops and their ids as they are; prefer "
        "replace_op on the op that makes a part over adding ops that overwrite it. Find new materials with "
        "search_palette. Then call finish with one or two sentences on what changed."
    )
    hist = History(ops_file)
    hist.ensure_started()
    result, ops_path = _run(state, brief, settings=settings, out=out, budget=budget, replay=replay, render=render,
                            record={"name": name, "instruction": instruction, "build": str(ops_file)},
                            cb=cb)  # fmt: skip
    after = state.doc.model_dump_json(by_alias=True, indent=1)
    version = None
    if after != before:
        version = hist.commit(after, kind="edit", instruction=instruction, run=str(out),
                              cost_usd=round(result.cost_usd, 4), summary=result.summary)  # fmt: skip
    return RunResult(result, state, ops_path, version)
