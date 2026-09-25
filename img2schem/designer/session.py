"""The design loop (SOW RD.1-RD.5): Claude calls tools until it finishes, with a budget check before every
turn. Each tool call is validated and compiled as it arrives (tools.DesignState); errors go back to Claude as
``is_error`` results. The loop owns the conversation, so a live run, a recording and a replay take the same
path (transport.py)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from img2schem.config import BudgetUSD, ClaudeSettings
from img2schem.designer.budget import BudgetExceeded, BudgetGuard
from img2schem.designer.pricing import usage_cost, worst_case
from img2schem.designer.tools import DesignState
from img2schem.designer.transport import Progress, Transport

MAX_SAME_OP_ERRORS = 3  # RD.3


@dataclass
class DesignResult:
    stopped: str  # finished | end_turn | budget | turn_cap | refusal
    summary: str | None
    turns: int
    cost_usd: float
    usage: list[dict[str, Any]] = field(default_factory=list)  # per turn: model, tokens, cost
    warnings: list[str] = field(default_factory=list)
    text: list[str] = field(default_factory=list)  # Claude's prose between tool calls


def _clean(block: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in block.items() if v is not None}


def _tokens(obj: Any) -> int:
    """A generous token estimate for content we add to the conversation (images count ~1600)."""
    s = json.dumps(obj, default=str)
    return len(s) // 3 + 1600 * s.count('"type": "image"')


def run_design(
    state: DesignState,
    brief: str,
    system: str,
    tools: list[dict[str, Any]],
    settings: ClaudeSettings,
    budget: BudgetUSD,
    transport: Transport,
    budget_name: str = "default",
    progress: Progress | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> DesignResult:
    guard = BudgetGuard(budget, budget_name)
    messages: list[dict[str, Any]] = [{"role": "user", "content": brief}]
    result = DesignResult("turn_cap", None, 0, 0.0)
    context = _tokens([system, tools, brief])  # input tokens of the next request (estimated)
    op_errors: dict[str, int] = {}

    def warn(msg: str) -> None:
        result.warnings.append(msg)
        if on_warning:
            on_warning(msg)

    for turn in range(settings.turn_cap):
        try:
            guard.check(worst_case(settings.model, context, settings.max_tokens))
        except BudgetExceeded as e:
            result.stopped = "budget"
            warn(str(e))
            break
        request = {
            "model": settings.model,
            "max_tokens": settings.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "tools": tools,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": settings.effort},
            "cache_control": {"type": "ephemeral"},  # also cache the conversation so far
        }
        response = transport.send(request, progress)
        result.turns = turn + 1
        usage = response.get("usage") or {}
        cost = usage_cost(response.get("model") or settings.model, usage)
        result.cost_usd += cost
        result.usage.append({"model": response.get("model"), "cost_usd": round(cost, 5),
                             **{k: usage.get(k) for k in ("input_tokens", "output_tokens",
                                                          "cache_creation_input_tokens",
                                                          "cache_read_input_tokens")}})  # fmt: skip
        if msg := guard.add(cost):
            warn(msg)
        content = [_clean(b) for b in response.get("content", [])]
        messages.append({"role": "assistant", "content": content})
        result.text += [b["text"] for b in content if b.get("type") == "text" and b.get("text")]
        context = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                   "cache_read_input_tokens")) + (usage.get("output_tokens") or 0)
        stop = response.get("stop_reason")
        tool_uses = [b for b in content if b.get("type") == "tool_use"]
        if stop == "refusal":
            result.stopped = "refusal"
            warn("Claude declined to continue this design")
            break
        if not tool_uses:
            result.stopped = "end_turn"
            break
        results: list[dict[str, Any]] = []
        finished = False
        for b in tool_uses:
            if stop == "max_tokens":  # a truncated tool input parses as a valid partial object: don't run it
                results.append({"type": "tool_result", "tool_use_id": b["id"], "is_error": True,
                                "content": "your turn hit max_tokens and this call was cut off; "
                                           "send smaller calls (e.g. fewer ops per define)"})  # fmt: skip
                continue
            r = state.execute(b["name"], b.get("input"))
            op_id = (b.get("input") or {}).get("id") if isinstance(b.get("input"), dict) else None
            text = r.content
            if r.is_error and op_id:
                op_errors[op_id] = op_errors.get(op_id, 0) + 1
                if op_errors[op_id] >= MAX_SAME_OP_ERRORS:
                    warn(f"op {op_id!r} failed {op_errors[op_id]} times; skipped")
                    text = f"{text}\n{op_errors[op_id]} failures on op {op_id!r}: skip it and carry on."
            elif op_id:
                op_errors.pop(op_id, None)
            results.append({"type": "tool_result", "tool_use_id": b["id"], "content": text,
                            **({"is_error": True} if r.is_error else {})})  # fmt: skip
            finished = finished or r.done
        if finished:
            result.stopped = "finished"
            result.summary = state.summary
            break
        messages.append({"role": "user", "content": results})
        context += _tokens(results)
    return result
