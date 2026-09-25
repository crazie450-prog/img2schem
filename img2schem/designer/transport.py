"""How a designer turn reaches Claude (SOW Phase 2 task 7): live over the Anthropic SDK, recorded to a JSONL
file, or replayed from one with no network (tests and `--replay`). Messages travel as plain dicts."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

Progress = Callable[[str, str], None]  # (kind, text): "text", "tool" (a tool call starting), "thinking"
FALLBACK_BETA = "server-side-fallback-2026-06-01"


class Transport(Protocol):
    def send(self, request: dict[str, Any], progress: Progress | None = None) -> dict[str, Any]: ...


def request_digest(request: dict[str, Any]) -> str:
    """A short hash of what a turn sends (to spot a replay that no longer matches the code)."""
    return hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()[:16]


class LiveTransport:
    """Streams each turn (SOW RD.2) with the fallback model re-running a declined turn server-side."""

    def __init__(self, fallback_model: str | None = None, client: Any = None):
        import anthropic  # optional dependency: pip install -e ".[vlm]"

        # A key that isn't scoped to a workspace must name one on every request (from .env).
        ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        self.client = client or anthropic.Anthropic(default_headers={"anthropic-workspace-id": ws} if ws else None)
        self.fallback_model = fallback_model

    def send(self, request: dict[str, Any], progress: Progress | None = None) -> dict[str, Any]:
        request = dict(request)
        if self.fallback_model:
            request["betas"] = [*request.get("betas", []), FALLBACK_BETA]
            request["fallbacks"] = [{"model": self.fallback_model}]
        attempts = 0
        while True:
            try:
                with self.client.beta.messages.stream(**request) as stream:
                    for event in cast(Any, stream):  # narrowed by event.type below
                        if progress is None:
                            continue
                        if event.type == "content_block_start" and event.content_block.type == "tool_use":
                            progress("tool", event.content_block.name)
                        elif event.type == "content_block_start" and event.content_block.type == "thinking":
                            progress("thinking", "")
                        elif event.type == "content_block_delta" and event.delta.type == "thinking_delta":
                            progress("text", event.delta.thinking)  # progress notes (display: "updates")
                        elif event.type == "text":
                            progress("text", event.text)
                    return stream.get_final_message().to_dict()  # type: ignore[no-any-return]
            except ValueError:  # tool input JSON the SDK could not parse at all: re-issue the turn (bounded)
                attempts += 1
                if attempts > 2:
                    raise


class RecordingTransport:
    """Passes turns to ``inner`` and appends each (request digest, response) to a JSONL file."""

    def __init__(self, inner: Transport, path: Path):
        self.inner, self.path = inner, path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def send(self, request: dict[str, Any], progress: Progress | None = None) -> dict[str, Any]:
        response = self.inner.send(request, progress)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"request_digest": request_digest(request), "response": response}) + "\n")
        return response


class ReplayTransport:
    """Answers turns from a recording, in order, without network or cost accounting surprises."""

    def __init__(self, path: Path):
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.responses = [r["response"] for r in lines]
        self.digests = [r.get("request_digest") for r in lines]
        self.turn = 0
        self.mismatches = 0  # requests that differ from the recording (the code or prompt changed since)

    def send(self, request: dict[str, Any], progress: Progress | None = None) -> dict[str, Any]:
        if self.turn >= len(self.responses):
            raise RuntimeError(f"the recording has only {len(self.responses)} turns")
        if self.digests[self.turn] not in (None, request_digest(request)):
            self.mismatches += 1
        response = self.responses[self.turn]
        self.turn += 1
        if progress:
            for block in response.get("content", []):
                if block.get("type") == "tool_use":
                    progress("tool", block["name"])
        return response
