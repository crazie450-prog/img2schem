"""Modern block-state strings: ``namespace:id[prop=value,...]`` (no numeric IDs, SOW C10)."""

from __future__ import annotations

import re

_STATE_RE = re.compile(
    r"^(?P<id>[a-z0-9_.\-]+:[a-z0-9_./\-]+)"
    r"(?:\[(?P<props>[a-z0-9_]+=[a-z0-9_\-]+(?:,[a-z0-9_]+=[a-z0-9_\-]+)*)?\])?$"
)


def parse_state(state: str) -> tuple[str, dict[str, str]]:
    """Split a block-state string into ``(block_id, properties)``; raises ValueError if malformed."""
    m = _STATE_RE.match(state)
    if not m:
        raise ValueError(f"malformed block state: {state!r}")
    props: dict[str, str] = {}
    if m.group("props"):
        for pair in m.group("props").split(","):
            k, v = pair.split("=")
            if k in props:
                raise ValueError(f"duplicate property {k!r} in {state!r}")
            props[k] = v
    return m.group("id"), props


def format_state(block_id: str, props: dict[str, str] | None = None) -> str:
    if not props:
        return block_id
    return block_id + "[" + ",".join(f"{k}={v}" for k, v in sorted(props.items())) + "]"


def namespace(state: str) -> str:
    return state.split(":", 1)[0]
